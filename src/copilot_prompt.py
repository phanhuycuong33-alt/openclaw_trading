from __future__ import annotations

import json
from typing import Any


def build_copilot_prompt(ranked_coins: list[dict[str, Any]]) -> str:
    return (
        "Bạn là chuyên gia phân tích crypto theo hướng thận trọng.\n"
        "Dựa trên dữ liệu JSON sau, hãy:\n"
        "1) Chọn 1 coin có khả năng pump ngắn hạn cao nhất.\n"
        "2) Giải thích bằng volume, momentum 24h/7d, market cap rank, trend bonus.\n"
        "3) Nêu 3 rủi ro chính và điểm vô hiệu nhận định.\n"
        "4) Đưa ra kế hoạch quản trị rủi ro ngắn gọn (SL/TP theo %).\n"
        "5) Trả lời bằng tiếng Việt, dùng bullet rõ ràng.\n\n"
        f"DATA:\n{json.dumps(ranked_coins, ensure_ascii=False, indent=2)}"
    )
