from __future__ import annotations

import math
import signal
import socket
import threading
import time
from typing import Any

import requests

from src.analyzer import score_coins
from src.config import load_settings
from src.binance_trader import BinanceFuturesTrader
from src.trading_strategy import choose_side, compute_tp_sl
from src.usage_tracker import get_copilot_usage
from src.web_fetcher import fetch_markets, fetch_trending
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


def _calculate_plan_pnl(plan: dict[str, Any], current_price: float) -> tuple[float, float, str, str]:
    side = str(plan.get("side"))
    entry = float(plan.get("entry_price") or 0.0)
    qty = float(plan.get("quantity") or 0.0)
    dry_run = bool(plan.get("dry_run"))

    if entry <= 0 or qty <= 0:
        return 0.0, 0.0, ("PAPER" if dry_run else "BINANCE"), "N/A"

    if side == "BUY":
        pnl = (current_price - entry) * qty
    else:
        pnl = (entry - current_price) * qty

    pnl_pct = (pnl / (entry * qty)) * 100 if (entry * qty) else 0.0
    mode = "PAPER" if dry_run else "BINANCE"
    status = "LỜI" if pnl >= 0 else "LỖ"
    return pnl, pnl_pct, mode, status


def _select_trade_slots(balance_usdt: float, max_trade_candidates: int) -> int:
    slots = int(math.floor(balance_usdt)) - 1
    slots = max(1, slots)
    return max(1, min(slots, max_trade_candidates))


def _pick_supported_candidates(
    ranked: list[dict[str, Any]],
    trader: BinanceFuturesTrader,
    max_count: int,
) -> list[tuple[dict[str, Any], str]]:
    selected: list[tuple[dict[str, Any], str]] = []
    seen: set[str] = set()

    for coin in ranked:
        symbol = f"{str(coin.get('symbol', '')).upper()}USDT"
        if not symbol or symbol == "USDT" or symbol in seen:
            continue
        if trader.supports_symbol(symbol):
            selected.append((coin, symbol))
            seen.add(symbol)
        if len(selected) >= max_count:
            break

    return selected


def _build_cycle_trades() -> dict[str, Any]:
    settings = load_settings()
    fallback_reason = ""
    effective_dry_run = settings.dry_run

    if not settings.binance_api_key or not settings.binance_api_secret:
        effective_dry_run = True
        fallback_reason = "Thiếu BINANCE API key/secret -> chạy PAPER"

    trader = BinanceFuturesTrader(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        dry_run=effective_dry_run,
    )

    available_balance = 0.0
    try:
        available_balance = trader.get_available_usdt_balance()
    except Exception as exc:
        if not effective_dry_run:
            raise RuntimeError(f"Không đọc được số dư futures: {exc}") from exc
        available_balance = 5.0

    if not effective_dry_run and available_balance < 2.0:
        effective_dry_run = True
        fallback_reason = (
            f"Số dư futures thấp ({available_balance:.4f} USDT), cần >=2 USDT để chạy batch -> chuyển PAPER"
        )
        trader = BinanceFuturesTrader(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            dry_run=True,
        )

    trade_slots = _select_trade_slots(available_balance if available_balance > 0 else 5.0, settings.max_trade_candidates)

    trending = fetch_trending()
    trending_ids = {coin["id"] for coin in trending if coin.get("id")}
    markets = fetch_markets(vs_currency=settings.vs_currency, per_page=120)
    ranked = score_coins(markets, trending_ids)
    if not ranked:
        raise RuntimeError("Không có dữ liệu thị trường để chọn coin")

    candidates = _pick_supported_candidates(ranked, trader, trade_slots)
    if not candidates:
        raise RuntimeError("Không tìm thấy coin futures phù hợp")

    attempts: list[dict[str, Any]] = []
    active_trades: list[dict[str, Any]] = []

    for coin, symbol in candidates:
        side = choose_side(coin)
        current_price = float(coin.get("current_price") or 0.0)
        tp_price, sl_price = compute_tp_sl(
            entry_price=current_price,
            side=side,
            tp_pct=settings.tp_pct,
            sl_pct=settings.sl_pct,
        )

        try:
            plan = trader.build_trade_plan(
                symbol=symbol,
                side=side,
                usdt_amount=1.0,
                leverage=settings.leverage,
                take_profit=tp_price,
                stop_loss=sl_price,
            )
            execution = trader.execute_trade(plan)
            active_trades.append(
                {
                    "coin": coin,
                    "symbol": symbol,
                    "trade_plan": {
                        "symbol": plan.symbol,
                        "side": plan.side,
                        "quantity": plan.quantity,
                        "entry_price": plan.entry_price,
                        "take_profit": plan.take_profit,
                        "stop_loss": plan.stop_loss,
                        "leverage": plan.leverage,
                        "dry_run": plan.dry_run,
                    },
                    "execution": execution,
                }
            )
            attempts.append({"symbol": symbol, "status": "success"})
        except Exception as exc:
            attempts.append({"symbol": symbol, "status": "failed", "error": str(exc)})

    if not active_trades:
        raise RuntimeError("Không mở được lệnh nào trong batch")

    return {
        "available_balance": available_balance,
        "fallback_reason": fallback_reason,
        "trade_slots": trade_slots,
        "active_trades": active_trades,
        "attempts": attempts,
    }


def _format_cycle_report(
    cycle_index: int,
    accumulated_realized_pnl: float,
    active_trades: list[dict[str, Any]],
    price_trader: BinanceFuturesTrader,
    live_pnl_trader: BinanceFuturesTrader | None,
) -> tuple[str, float]:
    lines = [f"trade lần thứ {cycle_index} --- pnl tích luỹ = {accumulated_realized_pnl:+.4f}"]
    total_pnl = 0.0

    for item in active_trades:
        plan = item.get("trade_plan", {})
        symbol = str(plan.get("symbol") or "")
        if not symbol:
            continue

        is_paper = bool(plan.get("dry_run"))
        if not is_paper and live_pnl_trader is not None:
            snapshot = live_pnl_trader.get_position_snapshot(symbol)
            current_price = float(snapshot.get("mark_price") or 0.0)
            pnl = float(snapshot.get("unrealized_pnl") or 0.0)
            mode = "BINANCE_REAL"
        else:
            current_price = price_trader.get_symbol_price(symbol)
            pnl, _, mode, _ = _calculate_plan_pnl(plan, current_price)

        total_pnl += pnl
        coin_label = symbol.replace("USDT", "")
        lines.append(
            f"pnl - {coin_label} ({mode}) price {current_price:.6f} profit: {pnl:+.6f}"
        )

    status = "LỜI" if total_pnl >= 0 else "LỖ"
    lines.append(f"tổng pnl {total_pnl:+.6f} --> {status}")
    return "\n".join(lines), total_pnl


def _close_all_batch_positions(trader: BinanceFuturesTrader, active_trades: list[dict[str, Any]]) -> tuple[int, list[str]]:
    closed = 0
    errors: list[str] = []
    symbols = {str(item.get("trade_plan", {}).get("symbol") or "") for item in active_trades}

    for symbol in symbols:
        if not symbol:
            continue
        try:
            result = trader.close_position_market(symbol)
            if result is not None:
                closed += 1
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    return closed, errors


def _run_multi_trade_cycle(
    token: str,
    chat_id: str,
    stop_event: threading.Event,
    close_target_usdt: float,
) -> None:
    settings = load_settings()
    accumulated_realized_pnl = 0.0
    cycle_index = 0

    while not stop_event.is_set():
        cycle_index += 1

        try:
            batch = _build_cycle_trades()
        except Exception as exc:
            _send_message(token, chat_id, f"Không thể bắt đầu batch trade: {exc}")
            for _ in range(settings.telegram_poll_interval_sec):
                if stop_event.is_set():
                    return
                time.sleep(1)
            continue

        active_trades = batch.get("active_trades", [])
        fallback_reason = str(batch.get("fallback_reason") or "")
        available_balance = float(batch.get("available_balance") or 0.0)

        mode = "PAPER"
        if active_trades:
            first_plan = active_trades[0].get("trade_plan", {})
            mode = "PAPER" if bool(first_plan.get("dry_run")) else "BINANCE"

        symbols_text = ", ".join(
            str(item.get("trade_plan", {}).get("symbol") or "") for item in active_trades
        )
        header_lines = [
            f"Batch {cycle_index} started | Mode: {mode}",
            f"Balance: {available_balance:.4f} USDT | Opened: {len(active_trades)} lệnh | Coins: {symbols_text}",
            f"Close condition: tổng pnl >= {close_target_usdt:.4f} USDT",
        ]
        if fallback_reason:
            header_lines.append(f"Fallback: {fallback_reason}")
        _send_message(token, chat_id, "\n".join(header_lines))

        price_trader = BinanceFuturesTrader(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            dry_run=True,
        )

        live_pnl_trader: BinanceFuturesTrader | None = None
        if mode == "BINANCE":
            try:
                live_pnl_trader = BinanceFuturesTrader(
                    api_key=settings.binance_api_key,
                    api_secret=settings.binance_api_secret,
                    dry_run=False,
                )
            except Exception:
                live_pnl_trader = None

        while not stop_event.is_set():
            remaining = settings.pnl_refresh_sec
            while remaining > 0 and not stop_event.is_set():
                time.sleep(1)
                remaining -= 1

            if stop_event.is_set():
                break

            try:
                report, total_pnl = _format_cycle_report(
                    cycle_index,
                    accumulated_realized_pnl,
                    active_trades,
                    price_trader,
                    live_pnl_trader,
                )
                _send_message(token, chat_id, report)
            except Exception as exc:
                _send_message(token, chat_id, f"Lỗi refresh PnL batch {cycle_index}: {exc}")
                continue

            if total_pnl >= close_target_usdt:
                try:
                    first_plan = active_trades[0].get("trade_plan", {}) if active_trades else {}
                    is_paper = bool(first_plan.get("dry_run"))
                    if not is_paper:
                        live_trader = BinanceFuturesTrader(
                            api_key=settings.binance_api_key,
                            api_secret=settings.binance_api_secret,
                            dry_run=False,
                        )
                        closed_count, close_errors = _close_all_batch_positions(live_trader, active_trades)
                        close_message = f"Đã close {closed_count} vị thế live"
                        if close_errors:
                            close_message += " | Lỗi: " + "; ".join(close_errors)
                        _send_message(token, chat_id, close_message)

                    accumulated_realized_pnl += total_pnl
                    _send_message(
                        token,
                        chat_id,
                        f"Đã close, pnl = {total_pnl:+.6f} | pnl tích luỹ = {accumulated_realized_pnl:+.6f}",
                    )
                except Exception as exc:
                    _send_message(token, chat_id, f"Lỗi close batch {cycle_index}: {exc}")
                break

    _send_message(token, chat_id, "Đã dừng multi-trade cycle theo lệnh /stop")


def _format_pnl_message(output: dict[str, Any], current_price: float) -> str:
    pnl, pnl_pct, mode, status = _calculate_pnl(output, current_price)
    return (
        f"PnL ({mode}) | Price: {current_price:.6f} | "
        f"{status}: {pnl:.6f} USDT ({pnl_pct:.3f}%)"
    )


def _calculate_pnl(output: dict[str, Any], current_price: float) -> tuple[float, float, str, str]:
    return _calculate_plan_pnl(output.get("trade_plan", {}), current_price)


def _format_live_pnl_message(symbol: str, snapshot: dict[str, Any]) -> tuple[str, float]:
    current_price = float(snapshot.get("mark_price") or 0.0)
    pnl = float(snapshot.get("unrealized_pnl") or 0.0)
    entry_price = float(snapshot.get("entry_price") or 0.0)
    position_amt = abs(float(snapshot.get("position_amt") or 0.0))
    pnl_pct = (pnl / (entry_price * position_amt) * 100.0) if (entry_price > 0 and position_amt > 0) else 0.0
    status = "LỜI" if pnl >= 0 else "LỖ"
    text = (
        f"PnL (BINANCE_REAL) | {symbol} | Mark: {current_price:.6f} | "
        f"{status}: {pnl:.6f} USDT ({pnl_pct:.3f}%)"
    )
    return text, pnl


def _refresh_pnl(token: str, chat_id: str, output: dict[str, Any], stop_event: threading.Event) -> None:
    settings = load_settings()
    plan = output.get("trade_plan", {})
    symbol = str(plan.get("symbol") or "")
    if not symbol:
        return
    is_paper = bool(plan.get("dry_run"))

    try:
        trader = BinanceFuturesTrader(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            dry_run=is_paper,
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
            if is_paper:
                current_price = trader.get_symbol_price(symbol)
                msg = _format_pnl_message(output, current_price)
                pnl_value, _, _, _ = _calculate_pnl(output, current_price)
            else:
                snapshot = trader.get_position_snapshot(symbol)
                msg, pnl_value = _format_live_pnl_message(symbol, snapshot)
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
        return (
            "Commands:\n"
            "/trade hoặc /trade <target_usdt> (multi-coin cycle)\n"
            "/run openclaw trading (single trade)\n"
            "/status\n/aiusage\n/stop"
        ), False, None, False

    if command == "/status":
        return "Server đang chạy và chờ lệnh.", False, None, False

    if command == "/aiusage":
        settings = load_settings()
        usage = get_copilot_usage(settings.copilot_daily_query_limit)
        exhausted_text = " => HẾT TOKEN/QUOTA" if usage["remaining"] <= 0 else ""
        return (
            "Copilot usage (estimate, local tracker): "
            f"{usage['used']}/{usage['limit']} ({usage['used_pct']}%). "
            f"Còn lại: {usage['remaining']}{exhausted_text}"
        ), False, None, False

    if command == "/stop":
        return "Đã nhận lệnh stop. Server sẽ tắt bot Telegram.", False, None, True

    if command == "/run openclaw trading":
        output = run_trading()
        return _format_trade_message(output), True, output, False

    if command == "/trade":
        return "Đang khởi động chế độ multi-coin cycle...", False, None, False

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
    cycle_thread: threading.Thread | None = None

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
                        normalized_text = text.strip().lower()

                        if normalized_text.startswith("/trade"):
                            parts = text.strip().split()
                            target_usdt = settings.profit_reenter_usdt

                            if len(parts) >= 2:
                                try:
                                    parsed_target = float(parts[1])
                                    if parsed_target <= 0:
                                        _send_message(token, chat_id, "Target phải > 0. Ví dụ: /trade 0.1")
                                        continue
                                    target_usdt = parsed_target
                                except ValueError:
                                    _send_message(token, chat_id, "Sai format. Dùng: /trade hoặc /trade 0.1")
                                    continue

                            if cycle_thread is not None and cycle_thread.is_alive():
                                _send_message(token, chat_id, "⏳ Multi-coin cycle đang chạy, vui lòng chờ hoặc dùng /stop.")
                                continue

                            _send_message(
                                token,
                                chat_id,
                                (
                                    "Đang khởi động multi-coin cycle: chọn coin theo số dư, "
                                    f"report PnL mỗi {settings.pnl_refresh_sec}s, "
                                    f"close all khi tổng pnl >= {target_usdt:.4f} USDT."
                                ),
                            )
                            cycle_thread = threading.Thread(
                                target=_run_multi_trade_cycle,
                                args=(token, chat_id, stop_event, target_usdt),
                                daemon=True,
                            )
                            cycle_thread.start()
                            _send_message(token, chat_id, f"✅ Multi-coin cycle đã bắt đầu với target {target_usdt:.4f} USDT.")
                            continue

                        if text.strip().lower() == "/run openclaw trading":
                            _send_message(token, chat_id, "Đang làm việc... quét thị trường, chọn coin và chuẩn bị lệnh.")

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
        if cycle_thread is not None:
            cycle_thread.join(timeout=2)
        if allowed_chat:
            try:
                _send_message(token, allowed_chat, f"OpenClaw bot offline trên {host}.")
            except Exception:
                pass


if __name__ == "__main__":
    run_telegram_bot()
