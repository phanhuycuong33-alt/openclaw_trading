from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.analyzer import score_coins
from src.binance_trader import BinanceFuturesTrader
from src.config import load_settings
from src.trading_strategy import choose_side, choose_trade_candidate, compute_tp_sl
from src.web_fetcher import fetch_markets, fetch_trending


def _pick_first_supported_candidate(
    ranked: list[dict[str, Any]],
    trader: BinanceFuturesTrader,
) -> tuple[dict[str, Any], str, int]:
    for index, coin in enumerate(ranked):
        symbol = f"{str(coin.get('symbol', '')).upper()}USDT"
        if not symbol or symbol == "USDT":
            continue
        if trader.supports_symbol(symbol):
            return coin, symbol, index
    raise RuntimeError("Không tìm thấy coin có futures symbol phù hợp trên Binance")


def _candidate_sequence(
    ranked: list[dict[str, Any]],
    preferred: dict[str, Any],
    trader: BinanceFuturesTrader,
    max_candidates: int,
) -> list[tuple[dict[str, Any], str, int]]:
    seq: list[tuple[dict[str, Any], str, int]] = []
    seen: set[str] = set()

    preferred_symbol = f"{str(preferred.get('symbol', '')).upper()}USDT"
    if preferred_symbol and preferred_symbol != "USDT" and trader.supports_symbol(preferred_symbol):
        seq.append((preferred, preferred_symbol, -1))
        seen.add(preferred_symbol)

    for index, coin in enumerate(ranked):
        symbol = f"{str(coin.get('symbol', '')).upper()}USDT"
        if not symbol or symbol == "USDT" or symbol in seen:
            continue
        if trader.supports_symbol(symbol):
            seq.append((coin, symbol, index))
            seen.add(symbol)
        if len(seq) >= max_candidates:
            break

    return seq


def run_trading() -> dict[str, Any]:
    settings = load_settings()

    trending = fetch_trending()
    trending_ids = {coin["id"] for coin in trending if coin.get("id")}

    markets = fetch_markets(vs_currency=settings.vs_currency, per_page=120)
    ranked = score_coins(markets, trending_ids)

    if not ranked:
        raise RuntimeError("Không lấy được dữ liệu thị trường")

    effective_dry_run = settings.dry_run
    fallback_reason = ""

    if not settings.dry_run and (not settings.binance_api_key or not settings.binance_api_secret):
        effective_dry_run = True
        fallback_reason = "Thiếu BINANCE_API_KEY/BINANCE_API_SECRET -> chuyển paper trade"

    trader = BinanceFuturesTrader(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        dry_run=effective_dry_run,
    )

    preferred = choose_trade_candidate(ranked)
    preferred_symbol = f"{str(preferred.get('symbol', '')).upper()}USDT"

    attempts: list[dict[str, Any]] = []

    available_balance = None
    if not effective_dry_run:
        available_balance = trader.get_available_usdt_balance()
        if available_balance < settings.trade_usdt_amount:
            effective_dry_run = True
            fallback_reason = (
                f"Số dư USDT futures không đủ ({available_balance:.4f} < {settings.trade_usdt_amount:.4f})"
                " -> chuyển paper trade"
            )
            trader = BinanceFuturesTrader(
                api_key=settings.binance_api_key,
                api_secret=settings.binance_api_secret,
                dry_run=True,
            )

    candidates = _candidate_sequence(
        ranked=ranked,
        preferred=preferred,
        trader=trader,
        max_candidates=settings.max_trade_candidates,
    )
    if not candidates:
        raise RuntimeError("Không tìm thấy coin futures hợp lệ để thử đặt lệnh")

    result = None
    plan = None
    candidate = None
    symbol = None
    selected_index = -1

    for coin, coin_symbol, index in candidates:
        side = choose_side(coin)
        current_price = float(coin.get("current_price") or 0.0)
        tp_price, sl_price = compute_tp_sl(
            entry_price=current_price,
            side=side,
            tp_pct=settings.tp_pct,
            sl_pct=settings.sl_pct,
        )

        try:
            built_plan = trader.build_trade_plan(
                symbol=coin_symbol,
                side=side,
                usdt_amount=settings.trade_usdt_amount,
                leverage=settings.leverage,
                take_profit=tp_price,
                stop_loss=sl_price,
            )
            exec_result = trader.execute_trade(built_plan)
            plan = built_plan
            result = exec_result
            candidate = coin
            symbol = coin_symbol
            selected_index = index
            attempts.append({"symbol": coin_symbol, "status": "success"})
            break
        except Exception as exc:
            attempts.append({"symbol": coin_symbol, "status": "failed", "error": str(exc)})
            continue

    if plan is None or result is None or candidate is None or symbol is None:
        sample_errors = "; ".join(
            f"{item.get('symbol')}: {item.get('error')}"
            for item in attempts[:5]
            if item.get("status") == "failed"
        )
        raise RuntimeError(
            f"Thử {len(attempts)} coin nhưng đều thất bại khi đặt lệnh. "
            f"Một số lỗi: {sample_errors or 'không có chi tiết'}"
        )

    output = {
        "candidate": candidate,
        "market_context": {
            "selected_reason": "highest ranked altcoin candidate",
            "preferred_symbol": preferred_symbol,
            "selected_rank_index": selected_index,
            "pump_probability_score": candidate.get("pump_probability_score"),
            "price_change_percentage_24h": candidate.get("price_change_percentage_24h"),
            "price_change_percentage_7d": candidate.get("price_change_percentage_7d_in_currency"),
        },
        "balance": {
            "available_usdt": available_balance,
            "required_usdt": settings.trade_usdt_amount,
            "used_balance_pct": (
                None
                if available_balance is None or available_balance <= 0
                else round((settings.trade_usdt_amount / available_balance) * 100.0, 4)
            ),
        },
        "fallback_reason": fallback_reason,
        "execution_mode": "PAPER" if plan.dry_run else "BINANCE_LIVE",
        "execution_mode_reason": (
            fallback_reason
            if fallback_reason
            else ("DRY_RUN bật trong cấu hình" if plan.dry_run else "Đủ điều kiện đặt lệnh Binance Futures")
        ),
        "attempts": attempts,
        "trade_plan": {
            "symbol": plan.symbol,
            "side": plan.side,
            "quantity": plan.quantity,
            "entry_price": plan.entry_price,
            "take_profit": plan.take_profit,
            "tp_pct": settings.tp_pct,
            "stop_loss": plan.stop_loss,
            "sl_pct": settings.sl_pct,
            "leverage": plan.leverage,
            "dry_run": plan.dry_run,
        },
        "execution": result,
    }

    out_file = Path("trade_result.json")
    out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Coin được chọn: {candidate.get('name')} ({symbol})")
    print(f"Side: {plan.side} | Qty: {plan.quantity} | Entry~{plan.entry_price}")
    print(f"TP: {plan.take_profit} | SL: {plan.stop_loss} | Leverage: {plan.leverage}x")
    print(f"Mode: {'DRY_RUN' if plan.dry_run else 'LIVE'}")
    if fallback_reason:
        print(f"Fallback: {fallback_reason}")
    print(f"Đã lưu kết quả vào: {out_file}")

    return output


if __name__ == "__main__":
    run_trading()
