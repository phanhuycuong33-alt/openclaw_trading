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
