from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


USAGE_FILE = Path("usage_stats.json")


def _today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _read_stats() -> dict[str, Any]:
    if not USAGE_FILE.exists():
        return {}
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_stats(payload: dict[str, Any]) -> None:
    USAGE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def increment_copilot_queries(limit: int) -> dict[str, Any]:
    stats = _read_stats()
    day = _today_key()
    daily = stats.get(day, {})
    used = int(daily.get("copilot_queries", 0)) + 1
    daily["copilot_queries"] = used
    stats[day] = daily
    _write_stats(stats)
    return get_copilot_usage(limit)


def get_copilot_usage(limit: int) -> dict[str, Any]:
    stats = _read_stats()
    day = _today_key()
    daily = stats.get(day, {})
    used = int(daily.get("copilot_queries", 0))
    pct = min((used / limit) * 100.0, 100.0) if limit > 0 else 0.0
    return {
        "day": day,
        "used": used,
        "limit": limit,
        "used_pct": round(pct, 2),
        "remaining": max(limit - used, 0),
        "approximate": True,
    }
