from __future__ import annotations

from typing import Any


def _normalize(value: float, min_value: float, max_value: float) -> float:
    if max_value <= min_value:
        return 0.0
    return max(0.0, min((value - min_value) / (max_value - min_value), 1.0))


def _safe_num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def score_coins(markets: list[dict[str, Any]], trending_ids: set[str]) -> list[dict[str, Any]]:
    if not markets:
        return []

    volumes = [_safe_num(c.get("total_volume")) for c in markets]
    chg24 = [_safe_num(c.get("price_change_percentage_24h")) for c in markets]
    chg7d = [_safe_num(c.get("price_change_percentage_7d_in_currency")) for c in markets]

    v_min, v_max = min(volumes), max(volumes)
    c24_min, c24_max = min(chg24), max(chg24)
    c7_min, c7_max = min(chg7d), max(chg7d)

    ranked: list[dict[str, Any]] = []
    for coin in markets:
        coin_id = coin.get("id", "")
        volume = _safe_num(coin.get("total_volume"))
        p24 = _safe_num(coin.get("price_change_percentage_24h"))
        p7d = _safe_num(coin.get("price_change_percentage_7d_in_currency"))
        rank = coin.get("market_cap_rank")

        volume_score = _normalize(volume, v_min, v_max)
        momentum_24_score = _normalize(p24, c24_min, c24_max)
        momentum_7d_score = _normalize(p7d, c7_min, c7_max)

        rank_bonus = 0.0
        if isinstance(rank, int):
            if rank <= 30:
                rank_bonus = 0.25
            elif rank <= 100:
                rank_bonus = 0.15
            elif rank <= 300:
                rank_bonus = 0.1

        trend_bonus = 0.2 if coin_id in trending_ids else 0.0

        pump_probability_score = (
            0.35 * volume_score
            + 0.25 * momentum_24_score
            + 0.2 * momentum_7d_score
            + rank_bonus
            + trend_bonus
        )

        enriched = {
            **coin,
            "volume_score": round(volume_score, 4),
            "momentum_24_score": round(momentum_24_score, 4),
            "momentum_7d_score": round(momentum_7d_score, 4),
            "rank_bonus": rank_bonus,
            "trend_bonus": trend_bonus,
            "pump_probability_score": round(pump_probability_score, 4),
        }
        ranked.append(enriched)

    ranked.sort(key=lambda x: x["pump_probability_score"], reverse=True)
    return ranked
