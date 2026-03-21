from __future__ import annotations

import statistics
from typing import Any

import requests


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_products_by_keyword(keyword: str, limit: int = 20) -> list[dict[str, Any]]:
    query = keyword.strip()
    if not query:
        return []

    url = "https://dummyjson.com/products/search"
    response = requests.get(url, params={"q": query, "limit": limit}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    products = payload.get("products", []) if isinstance(payload, dict) else []
    return [p for p in products if isinstance(p, dict)]


def run_sell_scan(
    keywords: list[str] | None = None,
    limit_per_keyword: int = 20,
    min_gap_pct: float = 12.0,
) -> dict[str, Any]:
    """Scan e-commerce products and return potential underpriced opportunities.

    Heuristic:
    - Search each keyword
    - Compute median price of results
    - Keep products priced significantly lower than median
    """
    resolved_keywords = [k.strip() for k in (keywords or ["iphone", "laptop", "headphone"]) if k.strip()]
    all_candidates: list[dict[str, Any]] = []

    for keyword in resolved_keywords:
        products = _fetch_products_by_keyword(keyword, limit=limit_per_keyword)
        prices = [_safe_float(item.get("price")) for item in products if _safe_float(item.get("price")) > 0]
        if not prices:
            continue

        baseline_price = float(statistics.median(prices))
        if baseline_price <= 0:
            continue

        for item in products:
            price = _safe_float(item.get("price"))
            if price <= 0:
                continue

            gap = baseline_price - price
            gap_pct = (gap / baseline_price) * 100.0
            if gap_pct < min_gap_pct:
                continue

            all_candidates.append(
                {
                    "keyword": keyword,
                    "title": str(item.get("title") or "Unknown"),
                    "brand": str(item.get("brand") or "N/A"),
                    "category": str(item.get("category") or "N/A"),
                    "price": price,
                    "baseline_price": baseline_price,
                    "gap": gap,
                    "gap_pct": gap_pct,
                    "rating": _safe_float(item.get("rating")),
                    "discount_pct": _safe_float(item.get("discountPercentage")),
                    "stock": int(item.get("stock") or 0),
                }
            )

    all_candidates.sort(key=lambda x: (x["gap_pct"], x["gap"], x["rating"]), reverse=True)

    top_items = all_candidates[:10]
    return {
        "keywords": resolved_keywords,
        "scanned_items": len(all_candidates),
        "opportunities": top_items,
    }
