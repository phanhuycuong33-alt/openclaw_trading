from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic


def summarize_with_claude(api_key: str, model: str, ranked_coins: list[dict[str, Any]]) -> str:
    if not api_key:
        return "Chưa có ANTHROPIC_API_KEY. Bỏ qua phần phân tích bằng Claude."

    client = Anthropic(api_key=api_key)

    prompt = (
        "Bạn là chuyên gia phân tích crypto theo hướng thận trọng. "
        "Dựa trên dữ liệu JSON dưới đây, hãy:\n"
        "1) Chọn 1 coin có khả năng tăng mạnh ngắn hạn cao nhất theo dữ liệu hiện tại.\n"
        "2) Nêu rõ vì sao chọn coin đó (volume, momentum 24h/7d, trending, vốn hóa).\n"
        "3) Đưa ra rủi ro chính và điều kiện vô hiệu nhận định.\n"
        "4) Trả lời bằng tiếng Việt, ngắn gọn, có bullet.\n\n"
        f"Dữ liệu JSON:\n{json.dumps(ranked_coins, ensure_ascii=False, indent=2)}"
    )

    try:
        message = client.messages.create(
            model=model,
            max_tokens=900,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        return f"Không gọi được Claude API: {exc}"

    parts = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)

    return "\n".join(parts).strip()


def review_positions_with_claude(
    api_key: str,
    model: str,
    positions: list[dict[str, Any]],
    fresh_market_summary: list[dict[str, Any]],
) -> dict[str, str]:
    """Ask Claude to review open positions and decide action for each.

    Returns a dict mapping symbol → "HOLD" | "CLOSE_REPLACE" | "CLOSE_CUT_LOSS"
    Only returns entries where Claude disagrees or confirms rule-based action.
    Falls back to empty dict on any error (caller uses rule-based decisions).

    positions: list of per-coin dicts from _build_adaptive_review_recommendations
    fresh_market_summary: top-20 freshly scored coins for context
    """
    if not api_key:
        return {}

    client = Anthropic(api_key=api_key)

    pos_summary = []
    for p in positions:
        pos_summary.append({
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "entry_price": p.get("entry_price"),
            "mark_price": p.get("mark_price"),
            "unrealized_pnl_usdt": p.get("current_pnl"),
            "close_fee_est_usdt": p.get("close_fee_est"),
            "net_pnl_if_close_usdt": p.get("net_pnl_if_close"),
            "fresh_market_score": p.get("fresh_score"),
            "rule_based_action": p.get("action"),
            "rule_based_reason": p.get("reason"),
            "best_replacement_candidate": p.get("replacement_symbol"),
            "replacement_score": p.get("replacement_score"),
        })

    market_ctx = [
        {"symbol": c.get("symbol", "").upper() + "USDT",
         "score": c.get("pump_probability_score"),
         "change_24h": c.get("price_change_percentage_24h"),
         "change_7d": c.get("price_change_percentage_7d_in_currency"),
         "volume_score": c.get("volume_score")}
        for c in fresh_market_summary[:20]
    ]

    prompt = (
        "Bạn là AI trading bot quản lý danh mục futures crypto. "
        "Bạn đang THỰC CHIẾN với tiền thật, đã chạy được 30+ phút và PnL tổng đang âm.\n\n"
        "Nhiệm vụ: Quyết định hành động cho từng vị thế. CHỈ trả lời bằng JSON hợp lệ, không thêm giải thích ngoài JSON.\n\n"
        "Quy tắc quyết định:\n"
        "- CLOSE_REPLACE: đóng vị thế này + mở coin thay thế tốt hơn (net PnL sau phí có lợi hơn giữ nguyên)\n"
        "- CLOSE_CUT_LOSS: đóng cắt lỗ, không mở thay thế (thị trường coin này xấu, không có replacement tốt)\n"
        "- HOLD: tiếp tục giữ (coin vẫn có momentum, hoặc phí close sẽ làm mất lãi)\n\n"
        "Ưu tiên: tối đa hoá lợi nhuận toàn danh mục, chấp nhận mất phí nếu replacement thực sự tốt hơn.\n\n"
        f"Vị thế hiện tại:\n{json.dumps(pos_summary, ensure_ascii=False, indent=2)}\n\n"
        f"Top coins thị trường hiện tại:\n{json.dumps(market_ctx, ensure_ascii=False, indent=2)}\n\n"
        "Trả lời JSON dạng:\n"
        '{"decisions": [{"symbol": "BTCUSDT", "action": "HOLD", "reason": "..."}, ...]}'
    )

    try:
        message = client.messages.create(
            model=model,
            max_tokens=600,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return {}

    raw = ""
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            raw += text

    # Extract JSON from response
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            return {}
        data = json.loads(raw[start:end])
        result: dict[str, str] = {}
        for item in data.get("decisions", []):
            sym = str(item.get("symbol", "")).upper()
            action = str(item.get("action", "")).upper()
            if sym and action in {"HOLD", "CLOSE_REPLACE", "CLOSE_CUT_LOSS"}:
                result[sym] = action
        return result
    except Exception:
        return {}
