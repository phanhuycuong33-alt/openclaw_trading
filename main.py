from __future__ import annotations

import json
from pathlib import Path

from src.analyzer import score_coins
from src.claude_client import summarize_with_claude
from src.copilot_prompt import build_copilot_prompt
from src.config import load_settings
from src.usage_tracker import CopilotQuotaExceededError, increment_copilot_queries
from src.web_fetcher import fetch_markets, fetch_trending


def run() -> None:
    settings = load_settings()

    trending = fetch_trending()
    trending_ids = {coin["id"] for coin in trending if coin.get("id")}

    markets = fetch_markets(vs_currency=settings.vs_currency, per_page=100)
    ranked = score_coins(markets, trending_ids)
    top_ranked = ranked[: settings.top_n]

    output_path = Path("output_top_coins.json")
    output_path.write_text(json.dumps(top_ranked, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_path = Path("copilot_prompt.txt")

    print(f"Đã lưu top coin vào: {output_path}")
    print("\nTop 5 theo điểm pump_probability_score:")
    for idx, coin in enumerate(top_ranked[:5], start=1):
        print(
            f"{idx}. {coin.get('name')} ({coin.get('symbol', '').upper()}) | "
            f"Score={coin.get('pump_probability_score')} | "
            f"24h={coin.get('price_change_percentage_24h')}% | "
            f"7d={coin.get('price_change_percentage_7d_in_currency')}%"
        )

    if settings.llm_provider == "anthropic":
        print("\n=== Claude Analysis ===")
        analysis = summarize_with_claude(
            api_key=settings.anthropic_api_key,
            model=settings.model,
            ranked_coins=top_ranked,
        )
        print(analysis)
        return

    copilot_prompt = build_copilot_prompt(top_ranked)
    prompt_path.write_text(copilot_prompt, encoding="utf-8")
    print("\n=== Copilot Mode ===")
    print(f"Đã tạo prompt cho Copilot tại: {prompt_path}")
    try:
        usage = increment_copilot_queries(settings.copilot_daily_query_limit)
    except CopilotQuotaExceededError as exc:
        print(f"Lỗi: {exc}")
        print("Gợi ý: Copilot có thể đã hết token/request quota. Hãy chờ reset quota hoặc tăng COPILOT_DAILY_QUERY_LIMIT nếu chỉ muốn bỏ qua local tracker.")
        raise SystemExit(1)
    print(
        "Copilot usage (estimate): "
        f"{usage['used']}/{usage['limit']} ({usage['used_pct']}%)"
    )
    print("Mở file copilot_prompt.txt và dán vào GitHub Copilot Chat để lấy nhận định.")


if __name__ == "__main__":
    run()
