from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd
import requests
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volume import MFIIndicator


_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}


def _fetch_ohlcv(symbol: str, interval: str = "15m", limit: int = 160) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/klines"
    response = requests.get(
        url,
        params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return pd.DataFrame()

    rows: list[dict[str, float]] = []
    for candle in payload:
        if isinstance(candle, list) and len(candle) >= 6:
            try:
                rows.append(
                    {
                        "open": float(candle[1]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "close": float(candle[4]),
                        "volume": float(candle[5]),
                    }
                )
            except (TypeError, ValueError):
                pass
    return pd.DataFrame(rows)


def _compute_advisor_score(symbol: str) -> dict[str, Any]:
    ohlcv = _fetch_ohlcv(symbol)
    if len(ohlcv) < 60:
        return {"score": 0.0, "label": "neutral", "reason": "insufficient_data"}

    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]
    volume = ohlcv["volume"]

    rsi_v = float(RSIIndicator(close=close, window=14).rsi().iloc[-1])
    ema20_v = float(EMAIndicator(close=close, window=20).ema_indicator().iloc[-1])
    ema50_v = float(EMAIndicator(close=close, window=50).ema_indicator().iloc[-1])
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_hist = float(macd.macd_diff().iloc[-1])
    mfi_v = float(MFIIndicator(high=high, low=low, close=close, volume=volume, window=14).money_flow_index().iloc[-1])

    score = 0.0
    reasons: list[str] = []

    if ema20_v > ema50_v:
        score += 0.45
        reasons.append("ema20>ema50")
    else:
        score -= 0.35
        reasons.append("ema20<=ema50")

    if macd_hist > 0:
        score += 0.35
        reasons.append("macd_up")
    else:
        score -= 0.25
        reasons.append("macd_down")

    if 45 <= rsi_v <= 68:
        score += 0.3
        reasons.append("rsi_healthy")
    elif rsi_v > 78:
        score -= 0.3
        reasons.append("rsi_overbought")
    elif rsi_v < 30:
        score += 0.1
        reasons.append("rsi_oversold")

    if mfi_v >= 55:
        score += 0.2
        reasons.append("mfi_support")
    elif mfi_v <= 35:
        score -= 0.2
        reasons.append("mfi_weak")

    score = max(-1.0, min(1.0, score))
    label = "bullish" if score >= 0.25 else ("bearish" if score <= -0.25 else "neutral")
    return {
        "score": round(score, 4),
        "label": label,
        "reason": ",".join(reasons),
        "rsi": round(rsi_v, 2),
        "macd_hist": round(macd_hist, 6),
        "mfi": round(mfi_v, 2),
    }


def get_second_advisor_signal(symbol: str, cache_ttl_sec: int = 300) -> dict[str, Any]:
    key = symbol.upper()
    now = time.time()

    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and (now - float(cached.get("ts") or 0.0) <= cache_ttl_sec):
            return dict(cached["signal"])

    try:
        signal = _compute_advisor_score(key)
    except Exception:
        signal = {"score": 0.0, "label": "neutral", "reason": "advisor_error"}

    with _CACHE_LOCK:
        _CACHE[key] = {"ts": now, "signal": dict(signal)}

    return signal


def rerank_with_second_advisor(
    ranked_coins: list[dict[str, Any]],
    top_k: int = 12,
    advisor_weight: float = 0.25,
) -> list[dict[str, Any]]:
    if not ranked_coins:
        return []

    enriched: list[dict[str, Any]] = []
    limit = max(1, min(top_k, len(ranked_coins)))

    for idx, coin in enumerate(ranked_coins):
        item = dict(coin)
        base_score = float(item.get("pump_probability_score") or 0.0)
        symbol = f"{str(item.get('symbol', '')).upper()}USDT"
        advisor_signal = {"score": 0.0, "label": "neutral", "reason": "not_scanned"}
        advisor_score_01 = 0.5

        if idx < limit and symbol and symbol != "USDT":
            advisor_signal = get_second_advisor_signal(symbol)
            advisor_score_01 = (float(advisor_signal.get("score") or 0.0) + 1.0) / 2.0

        final_score = ((1.0 - advisor_weight) * base_score) + (advisor_weight * advisor_score_01)
        item["advisor_signal"] = advisor_signal
        item["advisor_score"] = round(advisor_score_01, 4)
        item["blended_score"] = round(final_score, 4)
        enriched.append(item)

    enriched.sort(key=lambda x: float(x.get("blended_score") or x.get("pump_probability_score") or 0.0), reverse=True)
    return enriched
