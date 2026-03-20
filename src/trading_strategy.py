from __future__ import annotations

from typing import Any

STABLE_SYMBOLS = {
    "usdt",
    "usdc",
    "dai",
    "fdusd",
    "usde",
    "tusd",
    "usdd",
    "busd",
}


def choose_trade_candidate(ranked_coins: list[dict[str, Any]]) -> dict[str, Any]:
    prioritized: list[dict[str, Any]] = []

    for coin in ranked_coins:
        symbol = str(coin.get("symbol", "")).lower()
        if symbol in STABLE_SYMBOLS:
            continue
        if not coin.get("current_price"):
            continue

        rank = coin.get("market_cap_rank")
        trend_bonus = float(coin.get("trend_bonus") or 0.0)
        momentum_24_score = float(coin.get("momentum_24_score") or 0.0)

        if isinstance(rank, int) and 15 <= rank <= 300 and (trend_bonus > 0 or momentum_24_score >= 0.6):
            prioritized.append(coin)

    if prioritized:
        prioritized.sort(key=lambda c: float(c.get("pump_probability_score") or 0.0), reverse=True)
        return prioritized[0]

    for coin in ranked_coins:
        symbol = str(coin.get("symbol", "")).lower()
        if symbol in STABLE_SYMBOLS:
            continue
        if not coin.get("current_price"):
            continue
        return coin

    if ranked_coins:
        return ranked_coins[0]
    raise ValueError("Không có coin nào để giao dịch")


def choose_side(candidate: dict[str, Any]) -> str:
    p24 = float(candidate.get("price_change_percentage_24h") or 0.0)
    p7d = float(candidate.get("price_change_percentage_7d_in_currency") or 0.0)
    return "BUY" if (0.7 * p24 + 0.3 * p7d) >= 0 else "SELL"


def compute_tp_sl(entry_price: float, side: str, tp_pct: float, sl_pct: float) -> tuple[float, float]:
    tp_ratio = tp_pct / 100.0
    sl_ratio = sl_pct / 100.0

    if side == "BUY":
        take_profit = entry_price * (1.0 + tp_ratio)
        stop_loss = entry_price * (1.0 - sl_ratio)
    else:
        take_profit = entry_price * (1.0 - tp_ratio)
        stop_loss = entry_price * (1.0 + sl_ratio)

    return take_profit, stop_loss
