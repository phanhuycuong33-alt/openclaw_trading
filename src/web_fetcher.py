from __future__ import annotations

from typing import Any

import requests


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_trending() -> list[dict[str, Any]]:
    url = f"{COINGECKO_BASE_URL}/search/trending"
    payload = _get_json(url)

    items = payload.get("coins", [])
    results: list[dict[str, Any]] = []
    for entry in items:
        coin = entry.get("item", {})
        results.append(
            {
                "id": coin.get("id"),
                "name": coin.get("name"),
                "symbol": coin.get("symbol"),
                "market_cap_rank": coin.get("market_cap_rank"),
                "price_btc": coin.get("price_btc"),
                "score": coin.get("score"),
            }
        )
    return results


def fetch_markets(vs_currency: str, per_page: int = 50) -> list[dict[str, Any]]:
    url = f"{COINGECKO_BASE_URL}/coins/markets"
    payload = _get_json(
        url,
        params={
            "vs_currency": vs_currency,
            "order": "volume_desc",
            "per_page": per_page,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h,7d",
        },
    )

    results: list[dict[str, Any]] = []
    for coin in payload:
        results.append(
            {
                "id": coin.get("id"),
                "name": coin.get("name"),
                "symbol": coin.get("symbol"),
                "market_cap_rank": coin.get("market_cap_rank"),
                "current_price": coin.get("current_price"),
                "market_cap": coin.get("market_cap"),
                "total_volume": coin.get("total_volume"),
                "price_change_percentage_24h": coin.get("price_change_percentage_24h"),
                "price_change_percentage_7d_in_currency": coin.get("price_change_percentage_7d_in_currency"),
            }
        )
    return results
