from __future__ import annotations

import signal
import socket
import threading
import time
from typing import Any

import requests

from src.config import load_settings
from src.binance_trader import BinanceFuturesTrader
from src.usage_tracker import get_copilot_usage
from trade_openclaw import run_trading


def _send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20).raise_for_status()


def _get_updates(token: str, offset: int | None, timeout: int = 25) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    payload: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        payload["offset"] = offset
    response = requests.get(url, params=payload, timeout=timeout + 10)
    response.raise_for_status()
    return response.json()


def _format_trade_message(output: dict[str, Any]) -> str:
    settings = load_settings()
    usage = get_copilot_usage(settings.copilot_daily_query_limit)

    candidate = output.get("candidate", {})
    context = output.get("market_context", {})
    plan = output.get("trade_plan", {})
    fallback_reason = output.get("fallback_reason") or ""
    execution_mode = output.get("execution_mode") or ("PAPER" if plan.get("dry_run") else "BINANCE_LIVE")
    execution_mode_reason = output.get("execution_mode_reason") or ""

    lines = [
        "OpenClaw Trading Result",
        f"Coin: {candidate.get('name')} ({plan.get('symbol')})",
        f"Side: {plan.get('side')} | Leverage: {plan.get('leverage')}x",
        f"Score: {context.get('pump_probability_score')}",
        f"24h: {context.get('price_change_percentage_24h')}% | 7d: {context.get('price_change_percentage_7d')}%",
        f"Entry~ {plan.get('entry_price')} | Qty: {plan.get('quantity')}",
        f"TP: {plan.get('take_profit')} ({plan.get('tp_pct')}%) | SL: {plan.get('stop_loss')} ({plan.get('sl_pct')}%)",
        f"Mode: {execution_mode}",
    ]

    if execution_mode_reason:
        lines.append(f"Mode reason: {execution_mode_reason}")

    selected_rank_index = context.get("selected_rank_index")
    preferred_symbol = context.get("preferred_symbol")
    if isinstance(selected_rank_index, int) and selected_rank_index > 0:
        lines.append(
            f"Ghi chú: coin ưu tiên {preferred_symbol} không phù hợp futures, đã chuyển coin kế tiếp."
        )

    if fallback_reason:
        lines.append(f"Fallback: {fallback_reason}")

    attempts = output.get("attempts", [])
    failed_attempts = [a for a in attempts if a.get("status") == "failed"]
    if failed_attempts:
        lines.append(f"Retry: {len(failed_attempts)} coin fail trước khi khớp lệnh.")

    balance = output.get("balance", {})
    available = balance.get("available_usdt")
    required = balance.get("required_usdt")
    used_balance_pct = balance.get("used_balance_pct")
    if available is not None and required is not None:
        usage_text = "N/A" if used_balance_pct is None else f"{used_balance_pct:.2f}%"
        lines.append(
            f"Balance: {available:.4f} USDT | Required: {required:.4f} USDT | Used: {usage_text}"
        )

    lines.append(
        "Copilot usage (estimate): "
        f"{usage['used_pct']}% ({usage['used']}/{usage['limit']})"
    )

    return "\n".join(lines)


def _dynamic_profit_target(elapsed_sec: float, settings: Any) -> float:
    base = settings.profit_reenter_usdt
    if elapsed_sec < settings.target_decay_after_min * 60:
        return base

    over = elapsed_sec - settings.target_decay_after_min * 60
    steps = int(over // (settings.target_decay_every_min * 60)) + 1
    target = base - steps * settings.target_decay_step_usdt
    return max(settings.min_profit_target_usdt, target)


def _format_pnl_message(output: dict[str, Any], current_price: float) -> str:
    pnl, pnl_pct, mode, status = _calculate_pnl(output, current_price)
    return (
        f"PnL ({mode}) | Price: {current_price:.6f} | "
        f"{status}: {pnl:.6f} USDT ({pnl_pct:.3f}%)"
    )


def _calculate_pnl(output: dict[str, Any], current_price: float) -> tuple[float, float, str, str]:
    plan = output.get("trade_plan", {})
    side = str(plan.get("side"))
    entry = float(plan.get("entry_price") or 0.0)
    qty = float(plan.get("quantity") or 0.0)
    dry_run = bool(plan.get("dry_run"))

    if entry <= 0 or qty <= 0:
        return 0.0, 0.0, ("PAPER" if dry_run else "LIVE"), "N/A"

    if side == "BUY":
        pnl = (current_price - entry) * qty
    else:
        pnl = (entry - current_price) * qty

    pnl_pct = (pnl / (entry * qty)) * 100 if (entry * qty) else 0.0
    mode = "PAPER" if dry_run else "LIVE"
    status = "LỜI" if pnl >= 0 else "LỖ"
    return pnl, pnl_pct, mode, status


def _refresh_pnl(token: str, chat_id: str, output: dict[str, Any], stop_event: threading.Event) -> None:
    settings = load_settings()
    plan = output.get("trade_plan", {})
    symbol = str(plan.get("symbol") or "")
    if not symbol:
        return

    try:
        trader = BinanceFuturesTrader(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            dry_run=True,
        )
    except Exception as exc:
        _send_message(token, chat_id, f"Không thể khởi tạo PnL refresh: {exc}")
        return

    monitor_loops = max(1, int((settings.pnl_monitor_max_min * 60) / settings.pnl_refresh_sec))

    for loop_index in range(monitor_loops):
        remaining = settings.pnl_refresh_sec
        while remaining > 0 and not stop_event.is_set():
            step = min(1, remaining)
            time.sleep(step)
            remaining -= step

        if stop_event.is_set():
            return

        try:
            current_price = trader.get_symbol_price(symbol)
            msg = _format_pnl_message(output, current_price)
            pnl_value, _, _, _ = _calculate_pnl(output, current_price)
        except Exception as exc:
            msg = f"Server lỗi/kết nối Binance lỗi khi refresh PnL: {exc}"
            pnl_value = 0.0
        _send_message(token, chat_id, msg)

        elapsed_sec = (loop_index + 1) * settings.pnl_refresh_sec
        dynamic_target = _dynamic_profit_target(elapsed_sec, settings)

        if settings.auto_reenter_on_profit and pnl_value >= dynamic_target:
            _send_message(
                token,
                chat_id,
                (
                    f"Đã đạt ngưỡng chốt lời +{dynamic_target:.4f} USDT "
                    f"(elapsed {elapsed_sec // 60}m). "
                    "Bắt đầu quét lại thị trường để tìm coin mới..."
                ),
            )
            try:
                plan = output.get("trade_plan", {})
                dry_run = bool(plan.get("dry_run"))
                if not dry_run:
                    close_result = trader.close_position_market(symbol)
                    if close_result:
                        _send_message(token, chat_id, "Đã close vị thế hiện tại bằng market reduce-only.")

                next_output = run_trading()
                _send_message(token, chat_id, _format_trade_message(next_output))
            except Exception as exc:
                _send_message(token, chat_id, f"Re-enter thất bại: {exc}")
            break

        if elapsed_sec >= settings.target_decay_after_min * 60 and loop_index % 4 == 0:
            _send_message(
                token,
                chat_id,
                f"Target động hiện tại: +{dynamic_target:.4f} USDT sau {elapsed_sec // 60} phút.",
            )


def _handle_command(text: str) -> tuple[str, bool, dict[str, Any] | None, bool]:
    command = text.strip().lower()

    if command in {"/start", "/help"}:
        return "Commands:\n/run openclaw trading\n/trade\n/status\n/aiusage\n/stop", False, None, False

    if command == "/status":
        return "Server đang chạy và chờ lệnh.", False, None, False

    if command == "/aiusage":
        settings = load_settings()
        usage = get_copilot_usage(settings.copilot_daily_query_limit)
        return (
            "Copilot usage (estimate, local tracker): "
            f"{usage['used']}/{usage['limit']} ({usage['used_pct']}%). "
            f"Còn lại: {usage['remaining']}"
        ), False, None, False

    if command == "/stop":
        return "Đã nhận lệnh stop. Server sẽ tắt bot Telegram.", False, None, True

    if command in {"/run openclaw trading", "/trade"}:
        output = run_trading()
        return _format_trade_message(output), True, output, False

    return "Lệnh không hợp lệ. Dùng /run openclaw trading hoặc /trade", False, None, False


def run_telegram_bot() -> None:
    settings = load_settings()
    token = settings.telegram_bot_token

    if not token:
        raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN trong .env")

    allowed_chat = settings.telegram_allowed_chat_id
    offset: int | None = None
    running = True
    host = socket.gethostname()
    stop_event = threading.Event()
    refresh_threads: list[threading.Thread] = []
    trade_in_progress = False  # Prevent concurrent /trade executions

    print(f"[CONFIG] DRY_RUN={settings.dry_run}, AUTO_REENTER={settings.auto_reenter_on_profit}", flush=True)

    def _handle_shutdown_signal(signum: int, _frame: Any) -> None:
        nonlocal running
        running = False
        stop_event.set()
        print(f"Nhận signal {signum}, đang tắt Telegram bot...", flush=True)

    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    print("Telegram control đang chạy...")

    if allowed_chat:
        try:
            _send_message(token, allowed_chat, f"OpenClaw bot online trên {host}. Đang chờ lệnh /trade")
        except Exception:
            pass

    # Skip old messages on startup - Start fresh from the latest message
    try:
        print("[DEBUG] Initializing offset to skip old messages...", flush=True)
        latest_updates = _get_updates(token=token, offset=None, timeout=1)
        latest_results = latest_updates.get("result", [])
        if latest_results:
            offset = latest_results[-1].get("update_id", 0) + 1
            print(f"[DEBUG] ✓ Initialized offset={offset} (skipping {len(latest_results)} old messages)", flush=True)
        else:
            print("[DEBUG] ✓ No old messages to skip", flush=True)
    except Exception as e:
        print(f"[DEBUG] ⚠ Offset initialization failed: {e}. Will process all messages.", flush=True)
        offset = None

    try:
        while running:
            try:
                payload = _get_updates(token=token, offset=offset)
                results = payload.get("result", [])
                print(f"[DEBUG] Polling with offset={offset}, received {len(results)} messages", flush=True)

                for update in results:
                    update_id = update.get("update_id", 0)
                    offset = update_id + 1
                    message = update.get("message", {})
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    text = message.get("text", "")

                    if not text:
                        continue

                    print(f"[DEBUG] Processing update_id={update_id}, offset_next={offset}, text='{text}'", flush=True)

                    if allowed_chat and chat_id != allowed_chat:
                        _send_message(token, chat_id, "Unauthorized chat id")
                        continue

                    try:
                        print(f"[DEBUG] Received command: {text.strip().lower()}", flush=True)
                        if text.strip().lower() in {"/run openclaw trading", "/trade"}:
                            if trade_in_progress:
                                reply = "⏳ Đang chạy /trade, vui lòng chờ..."
                                _send_message(token, chat_id, reply)
                                print(f"[DEBUG] Trade already in progress, rejecting duplicate /trade", flush=True)
                                continue
                            
                            trade_in_progress = True
                            try:
                                _send_message(token, chat_id, "Đang làm việc... quét thị trường, chọn coin và chuẩn bị lệnh.")
                                print(f"[DEBUG] Executing /trade command", flush=True)
                            finally:
                                trade_in_progress = False

                        reply, should_refresh_pnl, output, should_stop = _handle_command(text)
                        print(f"[DEBUG] Command processed, should_refresh_pnl={should_refresh_pnl}, should_stop={should_stop}", flush=True)
                    except Exception as exc:
                        reply = f"Lỗi khi xử lý lệnh: {exc}"
                        should_refresh_pnl = False
                        output = None
                        should_stop = False

                    _send_message(token, chat_id, reply)

                    if should_refresh_pnl and output is not None and not stop_event.is_set():
                        thread = threading.Thread(
                            target=_refresh_pnl,
                            args=(token, chat_id, output, stop_event),
                            daemon=True,
                        )
                        refresh_threads.append(thread)
                        thread.start()

                    if should_stop:
                        running = False
                        stop_event.set()
                        break

            except KeyboardInterrupt:
                running = False
                stop_event.set()
                print("Nhận Ctrl+C, đang tắt Telegram bot...", flush=True)
            except Exception as exc:
                print(f"Telegram loop error: {exc}")
                if allowed_chat:
                    try:
                        _send_message(token, allowed_chat, f"Cảnh báo: server/bot gặp lỗi kết nối: {exc}")
                    except Exception:
                        pass
                time.sleep(settings.telegram_poll_interval_sec)
    finally:
        stop_event.set()
        for thread in refresh_threads:
            thread.join(timeout=2)
        if allowed_chat:
            try:
                _send_message(token, allowed_chat, f"OpenClaw bot offline trên {host}.")
            except Exception:
                pass


if __name__ == "__main__":
    run_telegram_bot()
