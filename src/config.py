from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    model: str
    llm_provider: str
    vs_currency: str
    top_n: int
    binance_api_key: str
    binance_api_secret: str
    trade_usdt_amount: float
    leverage: int
    sl_pct: float
    tp_pct: float
    dry_run: bool
    telegram_bot_token: str
    telegram_allowed_chat_id: str
    telegram_poll_interval_sec: int
    auto_reenter_on_profit: bool
    profit_reenter_usdt: float
    target_decay_after_min: int
    target_decay_step_usdt: float
    target_decay_every_min: int
    min_profit_target_usdt: float
    pnl_refresh_sec: int
    pnl_monitor_max_min: int
    max_trade_candidates: int
    copilot_daily_query_limit: int
    adaptive_review_min: int
    binance_taker_fee_rate: float


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("MODEL", "claude-3-5-sonnet-20241022").strip()
    llm_provider = os.getenv("LLM_PROVIDER", "copilot").strip().lower()
    vs_currency = os.getenv("VS_CURRENCY", "usd").strip().lower()
    top_n_raw = os.getenv("TOP_N", "10").strip()
    binance_api_key = os.getenv("BINANCE_API_KEY", "").strip()
    binance_api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
    trade_usdt_amount_raw = os.getenv("TRADE_USDT_AMOUNT", "1").strip()
    leverage_raw = os.getenv("LEVERAGE", "3").strip()
    sl_pct_raw = os.getenv("SL_PCT", "3").strip()
    tp_pct_raw = os.getenv("TP_PCT", "6").strip()
    dry_run = _env_bool("DRY_RUN", True)
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_allowed_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    telegram_poll_interval_sec_raw = os.getenv("TELEGRAM_POLL_INTERVAL_SEC", "2").strip()
    auto_reenter_on_profit = _env_bool("AUTO_REENTER_ON_PROFIT", False)
    profit_reenter_usdt_raw = os.getenv("PROFIT_REENTER_USDT", "0.1").strip()
    target_decay_after_min_raw = os.getenv("TARGET_DECAY_AFTER_MIN", "30").strip()
    target_decay_step_usdt_raw = os.getenv("TARGET_DECAY_STEP_USDT", "0.02").strip()
    target_decay_every_min_raw = os.getenv("TARGET_DECAY_EVERY_MIN", "10").strip()
    min_profit_target_usdt_raw = os.getenv("MIN_PROFIT_TARGET_USDT", "0.02").strip()
    pnl_refresh_sec_raw = os.getenv("PNL_REFRESH_SEC", "15").strip()
    pnl_monitor_max_min_raw = os.getenv("PNL_MONITOR_MAX_MIN", "45").strip()
    max_trade_candidates_raw = os.getenv("MAX_TRADE_CANDIDATES", "20").strip()
    copilot_daily_query_limit_raw = os.getenv("COPILOT_DAILY_QUERY_LIMIT", "100").strip()
    adaptive_review_min_raw = os.getenv("ADAPTIVE_REVIEW_MIN", "30").strip()
    binance_taker_fee_rate_raw = os.getenv("BINANCE_TAKER_FEE_RATE", "0.0005").strip()

    try:
        top_n = max(1, min(int(top_n_raw), 50))
    except ValueError:
        top_n = 10

    try:
        trade_usdt_amount = max(1.0, float(trade_usdt_amount_raw))
    except ValueError:
        trade_usdt_amount = 1.0

    try:
        leverage = max(1, min(int(leverage_raw), 20))
    except ValueError:
        leverage = 3

    try:
        sl_pct = max(0.3, min(float(sl_pct_raw), 20.0))
    except ValueError:
        sl_pct = 3.0

    try:
        tp_pct = max(0.3, min(float(tp_pct_raw), 50.0))
    except ValueError:
        tp_pct = 6.0

    try:
        telegram_poll_interval_sec = max(1, min(int(telegram_poll_interval_sec_raw), 30))
    except ValueError:
        telegram_poll_interval_sec = 2

    try:
        profit_reenter_usdt = max(0.01, min(float(profit_reenter_usdt_raw), 100.0))
    except ValueError:
        profit_reenter_usdt = 0.1

    try:
        target_decay_after_min = max(1, min(int(target_decay_after_min_raw), 180))
    except ValueError:
        target_decay_after_min = 30

    try:
        target_decay_step_usdt = max(0.001, min(float(target_decay_step_usdt_raw), 10.0))
    except ValueError:
        target_decay_step_usdt = 0.02

    try:
        target_decay_every_min = max(1, min(int(target_decay_every_min_raw), 120))
    except ValueError:
        target_decay_every_min = 10

    try:
        min_profit_target_usdt = max(0.001, min(float(min_profit_target_usdt_raw), 10.0))
    except ValueError:
        min_profit_target_usdt = 0.02

    try:
        pnl_refresh_sec = max(5, min(int(pnl_refresh_sec_raw), 300))
    except ValueError:
        pnl_refresh_sec = 15

    try:
        pnl_monitor_max_min = max(1, min(int(pnl_monitor_max_min_raw), 24 * 60))
    except ValueError:
        pnl_monitor_max_min = 45

    try:
        max_trade_candidates = max(1, min(int(max_trade_candidates_raw), 100))
    except ValueError:
        max_trade_candidates = 20

    try:
        copilot_daily_query_limit = max(1, min(int(copilot_daily_query_limit_raw), 100000))
    except ValueError:
        copilot_daily_query_limit = 100

    try:
        adaptive_review_min = max(5, min(int(adaptive_review_min_raw), 240))
    except ValueError:
        adaptive_review_min = 30

    try:
        binance_taker_fee_rate = max(0.0, min(float(binance_taker_fee_rate_raw), 0.01))
    except ValueError:
        binance_taker_fee_rate = 0.0005

    return Settings(
        anthropic_api_key=api_key,
        model=model,
        llm_provider=llm_provider,
        vs_currency=vs_currency,
        top_n=top_n,
        binance_api_key=binance_api_key,
        binance_api_secret=binance_api_secret,
        trade_usdt_amount=trade_usdt_amount,
        leverage=leverage,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        dry_run=dry_run,
        telegram_bot_token=telegram_bot_token,
        telegram_allowed_chat_id=telegram_allowed_chat_id,
        telegram_poll_interval_sec=telegram_poll_interval_sec,
        auto_reenter_on_profit=auto_reenter_on_profit,
        profit_reenter_usdt=profit_reenter_usdt,
        target_decay_after_min=target_decay_after_min,
        target_decay_step_usdt=target_decay_step_usdt,
        target_decay_every_min=target_decay_every_min,
        min_profit_target_usdt=min_profit_target_usdt,
        pnl_refresh_sec=pnl_refresh_sec,
        pnl_monitor_max_min=pnl_monitor_max_min,
        max_trade_candidates=max_trade_candidates,
        copilot_daily_query_limit=copilot_daily_query_limit,
        adaptive_review_min=adaptive_review_min,
        binance_taker_fee_rate=binance_taker_fee_rate,
    )
