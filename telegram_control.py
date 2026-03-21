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
from src.claude_client import review_positions_with_claude
from src.ecommerce_scanner import run_sell_scan
from src.second_advisor import rerank_with_second_advisor
from src.trading_strategy import choose_side, compute_tp_sl
from src.usage_tracker import get_copilot_usage
from src.web_fetcher import fetch_markets, fetch_trending
from trade_openclaw import run_trading


_SYMBOL_MEMORY_LOCK = threading.Lock()
_SYMBOL_MEMORY: dict[str, dict[str, int]] = {}


def _remember_symbol_outcome(symbol: str, pnl: float, force_exclude: bool = False) -> None:
    symbol = str(symbol or "").upper()
    if not symbol:
        return

    with _SYMBOL_MEMORY_LOCK:
        state = _SYMBOL_MEMORY.setdefault(
            symbol,
            {"bad_runs": 0, "good_runs": 0, "exclude_batches": 0},
        )
        if pnl > 0:
            state["good_runs"] += 1
            state["exclude_batches"] = 0
            if state["bad_runs"] > 0:
                state["bad_runs"] -= 1
        else:
            state["bad_runs"] += 1
            if force_exclude:
                state["exclude_batches"] = max(
                    int(state["exclude_batches"]),
                    min(2, int(state["bad_runs"])),
                )


def _get_temporarily_excluded_symbols() -> set[str]:
    with _SYMBOL_MEMORY_LOCK:
        return {
            symbol
            for symbol, state in _SYMBOL_MEMORY.items()
            if int(state.get("exclude_batches", 0)) > 0
        }


def _consume_symbol_exclusions(symbols: set[str]) -> None:
    if not symbols:
        return

    with _SYMBOL_MEMORY_LOCK:
        for symbol in symbols:
            state = _SYMBOL_MEMORY.get(symbol)
            if not state:
                continue
            current = int(state.get("exclude_batches", 0))
            if current > 0:
                state["exclude_batches"] = current - 1


def _active_trade_symbols(active_trades: list[dict[str, Any]]) -> set[str]:
    symbols: set[str] = set()
    for item in active_trades:
        symbol = str(item.get("trade_plan", {}).get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    return symbols


# ---------------------------------------------------------------------------
# Fee estimation
# ---------------------------------------------------------------------------

def _estimate_close_fee(qty: float, mark_price: float, fee_rate: float) -> float:
    """One-side taker fee for closing a position."""
    return abs(qty) * mark_price * fee_rate


def _estimate_open_fee(qty: float, entry_price: float, fee_rate: float) -> float:
    """One-side taker fee for opening a position."""
    return abs(qty) * entry_price * fee_rate


def _choose_adaptive_leverage(coin_data: dict[str, Any], settings: Any) -> int:
    base_leverage = max(1, int(settings.leverage))
    score = float(coin_data.get("pump_probability_score") or 0.0)
    abs_24h = abs(float(coin_data.get("price_change_percentage_24h") or 0.0))
    abs_7d = abs(float(coin_data.get("price_change_percentage_7d_in_currency") or 0.0))
    volume_score = float(coin_data.get("volume_score") or 0.0)

    leverage = base_leverage

    if abs_24h >= 15 or abs_7d >= 35:
        leverage -= 2
    elif abs_24h >= 10 or abs_7d >= 25:
        leverage -= 1

    if score < 0.45:
        leverage = min(leverage, 2)
    elif score < 0.65:
        leverage = min(leverage, 3)
    elif score >= 0.85 and volume_score >= 0.7 and abs_24h <= 8 and abs_7d <= 18:
        leverage = base_leverage

    return max(2 if base_leverage >= 2 else 1, min(leverage, base_leverage))


def _resolve_trade_leverage(
    coin_data: dict[str, Any],
    settings: Any,
    leverage_override: int | None = None,
) -> int:
    if leverage_override is not None:
        return max(1, int(leverage_override))
    return _choose_adaptive_leverage(coin_data, settings)


# ---------------------------------------------------------------------------
# Adaptive review analysis (rule-based + optional Claude override)
# ---------------------------------------------------------------------------

def _build_adaptive_review_recommendations(
    active_trades: list[dict[str, Any]],
    live_pnl_trader: "BinanceFuturesTrader | None",
    price_trader: "BinanceFuturesTrader",
    settings: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """
    Analyse each active trade and build per-coin recommendations.

    Returns: (recommendations, fresh_ranked, llm_source_label)
    """
    from src.web_fetcher import fetch_markets, fetch_trending

    # Re-fetch market data
    try:
        trending = fetch_trending()
        trending_ids = {c["id"] for c in trending if c.get("id")}
        markets = fetch_markets(vs_currency=settings.vs_currency, per_page=120)
        fresh_ranked = score_coins(markets, trending_ids)
    except Exception:
        fresh_ranked = []

    # Build a quick lookup: symbol → fresh coin data & score
    fresh_by_symbol: dict[str, dict[str, Any]] = {}
    for coin in fresh_ranked:
        sym = f"{str(coin.get('symbol', '')).upper()}USDT"
        fresh_by_symbol[sym] = coin

    # Symbols already in batch (avoid proposing them as replacements)
    active_symbols: set[str] = set()
    for item in active_trades:
        sym = str(item.get("trade_plan", {}).get("symbol") or "")
        if sym:
            active_symbols.add(sym)

    fee_rate = settings.binance_taker_fee_rate

    recommendations: list[dict[str, Any]] = []

    for idx, item in enumerate(active_trades, start=1):
        plan = item.get("trade_plan", {})
        symbol = str(plan.get("symbol") or "")
        if not symbol:
            continue

        side = str(plan.get("side") or "BUY")
        is_paper = bool(plan.get("dry_run"))

        # Fetch real PnL
        current_pnl = 0.0
        mark_price = 0.0
        qty = float(plan.get("quantity") or 0.0)
        entry_price = float(plan.get("entry_price") or 0.0)

        if not is_paper and live_pnl_trader is not None:
            try:
                snap = live_pnl_trader.get_position_snapshot(symbol)
                current_pnl = float(snap.get("unrealized_pnl") or 0.0)
                mark_price = float(snap.get("mark_price") or 0.0)
                qty_snap = abs(float(snap.get("position_amt") or qty))
                if qty_snap > 0:
                    qty = qty_snap
            except Exception:
                pass
        else:
            try:
                mark_price = price_trader.get_symbol_price(symbol)
            except Exception:
                mark_price = entry_price

            if side == "BUY":
                current_pnl = (mark_price - entry_price) * qty
            else:
                current_pnl = (entry_price - mark_price) * qty

        effective_mark_price = mark_price if mark_price > 0 else entry_price
        notional = effective_mark_price * qty
        entry_fee_est = _estimate_open_fee(qty, entry_price, fee_rate)
        close_fee_est = _estimate_close_fee(qty, effective_mark_price, fee_rate)
        total_trade_fee_est = entry_fee_est + close_fee_est
        net_pnl_if_close = current_pnl - total_trade_fee_est

        # Re-score coin in fresh market
        fresh_coin = fresh_by_symbol.get(symbol)
        fresh_score = float(fresh_coin.get("pump_probability_score", 0.0)) if fresh_coin else 0.0

        # Find best outside replacement candidate (higher fresh score, supports futures)
        replacement_symbol: str | None = None
        replacement_score: float = 0.0
        replacement_open_fee_est: float = 0.0
        for cand in fresh_ranked:
            cand_sym = f"{str(cand.get('symbol', '')).upper()}USDT"
            if cand_sym in active_symbols:
                continue
            cand_score = float(cand.get("pump_probability_score", 0.0))
            if cand_score > fresh_score and cand_score > replacement_score:
                try:
                    if price_trader.supports_symbol(cand_sym):
                        replacement_symbol = cand_sym
                        replacement_score = cand_score
                        replacement_open_fee_est = notional * fee_rate
                except Exception:
                    pass
            if replacement_symbol and replacement_score > fresh_score * 1.2:
                break  # found a significantly better coin

        # Decision logic
        if current_pnl >= 0:
            # Positive PnL
            net_pnl_if_rotate = net_pnl_if_close - replacement_open_fee_est
            if net_pnl_if_rotate > 0 and replacement_symbol:
                action = "CLOSE_REPLACE"
                reason = (
                    f"PnL dương +{current_pnl:.4f} USDT. "
                    f"Sau phí vào+ra ≈ {total_trade_fee_est:.4f}, net close = {net_pnl_if_close:+.4f}. "
                    f"Nếu xoay sang coin mới, phí mở thêm ≈ {replacement_open_fee_est:.4f}, net rotate = {net_pnl_if_rotate:+.4f}. "
                    f"Có coin thay thế {replacement_symbol} score {replacement_score:.3f} > {fresh_score:.3f}."
                )
            elif net_pnl_if_close <= 0:
                action = "HOLD"
                reason = (
                    f"PnL +{current_pnl:.4f} USDT nhưng phí vào+ra ≈ {total_trade_fee_est:.4f} sẽ ăn hết lợi nhuận "
                    f"(net {net_pnl_if_close:.4f}). Tiếp tục giữ."
                )
            else:
                action = "HOLD"
                reason = (
                    f"PnL +{current_pnl:.4f} USDT. Net sau phí vào+ra còn {net_pnl_if_close:+.4f}. "
                    f"Không có phương án thay coin đủ tốt sau khi tính phí. Tiếp tục giữ."
                )
        else:
            # Negative PnL (loss)
            score_dropped = fresh_coin is None or fresh_score < 0.3
            has_good_replacement = replacement_symbol is not None and replacement_score > 0.5

            if score_dropped and has_good_replacement:
                action = "CLOSE_REPLACE"
                reason = (
                    f"PnL lỗ {current_pnl:.4f} USDT. "
                    f"Score thị trường của coin yếu ({fresh_score:.3f}). "
                    f"Coin thay thế {replacement_symbol} score {replacement_score:.3f} tốt hơn đáng kể. "
                    f"Net close sau phí vào+ra hiện tại ≈ {net_pnl_if_close:+.4f}."
                )
            elif score_dropped:
                action = "CLOSE_CUT_LOSS"
                reason = (
                    f"PnL lỗ {current_pnl:.4f} USDT. "
                    f"Score thị trường của coin đã yếu ({fresh_score:.3f}). "
                    f"Cắt lỗ, không tìm được coin thay thế tốt. Net close sau phí vào+ra ≈ {net_pnl_if_close:+.4f}."
                )
            else:
                action = "HOLD"
                reason = (
                    f"PnL lỗ {current_pnl:.4f} USDT nhưng score thị trường vẫn ổn ({fresh_score:.3f}). "
                    f"Tiếp tục chờ phục hồi."
                )

        recommendations.append(
            {
                "index": idx,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "mark_price": mark_price if mark_price > 0 else entry_price,
                "notional": notional,
                "current_pnl": current_pnl,
                "entry_fee_est": entry_fee_est,
                "close_fee_est": close_fee_est,
                "total_trade_fee_est": total_trade_fee_est,
                "net_pnl_if_close": net_pnl_if_close,
                "replacement_open_fee_est": replacement_open_fee_est,
                "fresh_score": fresh_score,
                "action": action,
                "reason": reason,
                "replacement_symbol": replacement_symbol,
                "replacement_score": replacement_score,
                "is_paper": is_paper,
            }
        )

    llm_source = "rule-based"
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        try:
            llm_overrides = review_positions_with_claude(
                api_key=settings.anthropic_api_key,
                model=settings.model,
                positions=recommendations,
                fresh_market_summary=fresh_ranked[:20],
            )
            if llm_overrides:
                for rec in recommendations:
                    symbol = str(rec.get("symbol") or "").upper()
                    new_action = llm_overrides.get(symbol)
                    if new_action and new_action != rec.get("action"):
                        old_action = str(rec.get("action") or "")
                        rec["action"] = new_action
                        rec["reason"] = f"[Claude: {old_action} → {new_action}] {rec['reason']}"
                llm_source = "Claude AI"
        except Exception:
            pass

    return recommendations, fresh_ranked, llm_source


# ---------------------------------------------------------------------------
# Open a single replacement trade
# ---------------------------------------------------------------------------

def _open_single_replacement_trade(
    replacement_symbol: str,
    trader: "BinanceFuturesTrader",
    settings: Any,
    allocated_margin: float,
    fresh_ranked: list[dict[str, Any]],
    leverage_override: int | None = None,
) -> dict[str, Any] | None:
    """Find the candidate data for replacement_symbol, build and execute its trade plan.
    Returns an active_trades-compatible dict, or None on failure."""
    from src.trading_strategy import choose_side, compute_tp_sl

    # Find coin data from fresh_ranked
    coin_data: dict[str, Any] | None = None
    for c in fresh_ranked:
        if f"{str(c.get('symbol', '')).upper()}USDT" == replacement_symbol:
            coin_data = c
            break

    if coin_data is None:
        return None

    try:
        leverage = _resolve_trade_leverage(coin_data, settings, leverage_override)
        min_margin = trader.get_min_trade_margin(replacement_symbol, leverage, base_usdt_amount=1.0)
        allocated_margin = max(float(allocated_margin), float(min_margin))
        side = choose_side(coin_data)
        current_price = float(coin_data.get("current_price") or 0.0)
        tp_price, sl_price = compute_tp_sl(
            entry_price=current_price,
            side=side,
            tp_pct=settings.tp_pct,
            sl_pct=settings.sl_pct,
        )
        plan = trader.build_trade_plan(
            symbol=replacement_symbol,
            side=side,
            usdt_amount=allocated_margin,
            leverage=leverage,
            take_profit=tp_price,
            stop_loss=sl_price,
        )
        execution = trader.execute_trade(plan)
        return {
            "coin": coin_data,
            "symbol": replacement_symbol,
            "allocated_margin": round(allocated_margin, 6),
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
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Execute review actions automatically
# ---------------------------------------------------------------------------

def _auto_execute_review_actions(
    recommendations: list[dict[str, Any]],
    active_trades: list[dict[str, Any]],
    live_trader: "BinanceFuturesTrader",
    settings: Any,
    token: str,
    chat_id: str,
    fresh_ranked: list[dict[str, Any]],
    leverage_override: int | None = None,
) -> list[dict[str, Any]]:
    """Execute all non-HOLD recommendations immediately.
    Returns an updated active_trades list."""

    executed_lines: list[str] = []
    new_active_trades: list[dict[str, Any]] = []

    for rec in recommendations:
        action = rec.get("action")
        if action == "HOLD":
            if float(rec.get("current_pnl") or 0.0) > 0:
                _remember_symbol_outcome(rec["symbol"], float(rec.get("current_pnl") or 0.0))
            new_active_trades.append(active_trades[rec["index"] - 1])
            continue

        symbol = rec["symbol"]
        is_paper = rec["is_paper"]

        # Close the position
        close_ok = False
        if not is_paper:
            try:
                live_trader.close_position_market(symbol)
                close_ok = True
                executed_lines.append(f"✅ Đã close {symbol} (PnL {rec['current_pnl']:+.4f})")
            except Exception as exc:
                executed_lines.append(f"❌ Lỗi close {symbol}: {exc}")
                new_active_trades.append(active_trades[rec["index"] - 1])
                continue
        else:
            close_ok = True
            executed_lines.append(f"✅ [PAPER] Close {symbol} (PnL {rec['current_pnl']:+.4f})")

        if close_ok:
            _remember_symbol_outcome(
                symbol,
                float(rec.get("current_pnl") or 0.0),
                force_exclude=float(rec.get("current_pnl") or 0.0) <= 0,
            )

        # Open replacement if applicable
        if close_ok and action == "CLOSE_REPLACE" and rec.get("replacement_symbol"):
            rep_sym = rec["replacement_symbol"]
            try:
                replacement_margin = rec["notional"] / settings.leverage
                if replacement_margin < 1.0:
                    replacement_margin = max(1.0, rec.get("close_fee_est", 0) + 1.0)
                new_trade = _open_single_replacement_trade(
                    replacement_symbol=rep_sym,
                    trader=live_trader,
                    settings=settings,
                    allocated_margin=replacement_margin,
                    fresh_ranked=fresh_ranked,
                    leverage_override=leverage_override,
                )
                if new_trade:
                    new_active_trades.append(new_trade)
                    executed_lines.append(f"  ↳ Mở mới {rep_sym} (margin ≈ {replacement_margin:.4f} USDT)")
                else:
                    executed_lines.append(f"  ↳ Không mở được {rep_sym}")
            except Exception as exc:
                executed_lines.append(f"  ↳ Lỗi mở {rep_sym}: {exc}")

    extra_trades, extra_lines = _try_top_up_portfolio(
        trader=live_trader,
        settings=settings,
        active_trades=new_active_trades,
        fresh_ranked=fresh_ranked,
    )
    if extra_trades:
        new_active_trades.extend(extra_trades)
    executed_lines.extend(extra_lines)

    if not executed_lines:
        _send_message(token, chat_id, "Adaptive review: không có vị thế cần đóng/thay thế.")
        return active_trades

    summary = "Adaptive review tự động đã thực hiện:\n" + "\n".join(executed_lines)
    _send_message(token, chat_id, summary)
    return new_active_trades


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

    execution = output.get("execution", {})
    warnings = execution.get("warnings", []) if isinstance(execution, dict) else []
    if warnings:
        lines.append("Execution warning: " + " | ".join(str(item) for item in warnings))

    return "\n".join(lines)


def _format_sell_report(output: dict[str, Any]) -> str:
    keywords = output.get("keywords", [])
    opportunities = output.get("opportunities", [])

    lines = [
        "OpenClaw Sell Scan Result",
        f"Keywords: {', '.join(str(k) for k in keywords) if keywords else 'N/A'}",
        f"Deals found: {len(opportunities)}",
    ]

    if not opportunities:
        lines.append("Không tìm thấy sản phẩm có chênh lệch giá đủ lớn.")
        return "\n".join(lines)

    for idx, item in enumerate(opportunities[:5], start=1):
        lines.append(
            (
                f"{idx}) {item.get('title')} | {item.get('brand')} | ${float(item.get('price') or 0.0):.2f} "
                f"vs baseline ${float(item.get('baseline_price') or 0.0):.2f} "
                f"(gap {float(item.get('gap_pct') or 0.0):.1f}%)"
            )
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
    excluded_symbols: set[str] | None = None,
) -> list[tuple[dict[str, Any], str]]:
    selected: list[tuple[dict[str, Any], str]] = []
    seen: set[str] = set()
    excluded = {str(symbol).upper() for symbol in (excluded_symbols or set())}

    for coin in ranked:
        symbol = f"{str(coin.get('symbol', '')).upper()}USDT"
        if not symbol or symbol == "USDT" or symbol in seen or symbol in excluded:
            continue
        if trader.supports_symbol(symbol):
            selected.append((coin, symbol))
            seen.add(symbol)
        if len(selected) >= max_count:
            break

    return selected


def _build_cycle_trades(leverage_override: int | None = None) -> dict[str, Any]:
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

    effective_balance = available_balance if available_balance > 0 else 5.0
    reserve_balance = 1.0 if effective_balance > 1.5 else 0.0
    remaining_budget = max(0.0, effective_balance - reserve_balance)
    trade_slots = _select_trade_slots(effective_balance, settings.max_trade_candidates)

    trending = fetch_trending()
    trending_ids = {coin["id"] for coin in trending if coin.get("id")}
    markets = fetch_markets(vs_currency=settings.vs_currency, per_page=120)
    ranked = score_coins(markets, trending_ids)
    ranked = rerank_with_second_advisor(ranked)
    if not ranked:
        raise RuntimeError("Không có dữ liệu thị trường để chọn coin")

    temporarily_excluded_symbols = _get_temporarily_excluded_symbols()
    candidates = _pick_supported_candidates(
        ranked,
        trader,
        settings.max_trade_candidates,
        excluded_symbols=temporarily_excluded_symbols,
    )
    _consume_symbol_exclusions(temporarily_excluded_symbols)
    if not candidates:
        raise RuntimeError("Không tìm thấy coin futures phù hợp")

    attempts: list[dict[str, Any]] = []
    active_trades: list[dict[str, Any]] = []
    budget_used = 0.0

    for coin, symbol in candidates:
        leverage = _resolve_trade_leverage(coin, settings, leverage_override)
        side = choose_side(coin)
        current_price = float(coin.get("current_price") or 0.0)
        tp_price, sl_price = compute_tp_sl(
            entry_price=current_price,
            side=side,
            tp_pct=settings.tp_pct,
            sl_pct=settings.sl_pct,
        )

        try:
            required_margin = trader.get_min_trade_margin(
                symbol=symbol,
                leverage=leverage,
                base_usdt_amount=1.0,
            )
            if required_margin > remaining_budget:
                attempts.append(
                    {
                        "symbol": symbol,
                        "status": "skipped_budget",
                        "error": (
                            f"Không đủ budget còn lại {remaining_budget:.4f} USDT, "
                            f"cần khoảng {required_margin:.4f} USDT"
                        ),
                    }
                )
                continue

            plan = trader.build_trade_plan(
                symbol=symbol,
                side=side,
                usdt_amount=required_margin,
                leverage=leverage,
                take_profit=tp_price,
                stop_loss=sl_price,
            )
            execution = trader.execute_trade(plan)
            remaining_budget = max(0.0, remaining_budget - required_margin)
            budget_used += required_margin
            active_trades.append(
                {
                    "coin": coin,
                    "symbol": symbol,
                    "allocated_margin": round(required_margin, 6),
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
            if len(active_trades) >= trade_slots:
                break
        except Exception as exc:
            attempts.append({"symbol": symbol, "status": "failed", "error": str(exc)})

    if not active_trades:
        sample_errors = "; ".join(
            f"{item.get('symbol')}: {item.get('error')}"
            for item in attempts[:5]
            if item.get("status") in {"failed", "skipped_budget"}
        )
        open_positions_text = ""
        if not effective_dry_run:
            try:
                open_positions = trader.get_open_positions()
                if open_positions:
                    preview = ", ".join(
                        f"{pos.get('symbol')}({float(pos.get('position_amt') or 0.0):.6f})"
                        for pos in open_positions[:5]
                    )
                    open_positions_text = (
                        " Phát hiện vị thế đang mở trên Binance: "
                        f"{preview}."
                    )
            except Exception:
                pass
        raise RuntimeError(
            f"Không mở được lệnh nào trong batch. Balance khả dụng hiện tại: {available_balance:.4f} USDT. "
            f"Một số lỗi: {sample_errors or 'không có chi tiết'}.{open_positions_text}"
        )

    return {
        "available_balance": available_balance,
        "effective_balance": effective_balance,
        "reserve_balance": reserve_balance,
        "remaining_budget": remaining_budget,
        "budget_used": budget_used,
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
    next_review_in_sec: int | None = None,
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
    if next_review_in_sec is not None:
        if next_review_in_sec <= 0:
            lines.append("adaptive review: đến hạn ở vòng kế tiếp")
        else:
            lines.append(f"adaptive review sau: {next_review_in_sec}s")
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


def _collect_trade_pnl_snapshots(
    active_trades: list[dict[str, Any]],
    price_trader: BinanceFuturesTrader,
    live_pnl_trader: BinanceFuturesTrader | None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []

    for item in active_trades:
        plan = item.get("trade_plan", {})
        symbol = str(plan.get("symbol") or "").upper()
        if not symbol:
            continue

        is_paper = bool(plan.get("dry_run"))
        if not is_paper and live_pnl_trader is not None:
            snapshot = live_pnl_trader.get_position_snapshot(symbol)
            pnl = float(snapshot.get("unrealized_pnl") or 0.0)
        else:
            current_price = price_trader.get_symbol_price(symbol)
            pnl, _, _, _ = _calculate_plan_pnl(plan, current_price)

        snapshots.append({"symbol": symbol, "pnl": pnl})

    return snapshots


def _try_top_up_portfolio(
    trader: BinanceFuturesTrader,
    settings: Any,
    active_trades: list[dict[str, Any]],
    fresh_ranked: list[dict[str, Any]],
    leverage_override: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    opened_trades: list[dict[str, Any]] = []
    log_lines: list[str] = []
    working_active_trades = list(active_trades)

    try:
        available_balance = float(trader.get_available_usdt_balance())
    except Exception as exc:
        return [], [f"  ↳ Không đọc được số dư để top-up: {exc}"]

    if available_balance < 1.0:
        return [], []

    excluded_symbols = _active_trade_symbols(working_active_trades) | _get_temporarily_excluded_symbols()
    candidates = _pick_supported_candidates(
        fresh_ranked,
        trader,
        settings.max_trade_candidates,
        excluded_symbols=excluded_symbols,
    )

    for coin, symbol in candidates:
        try:
            required_margin = trader.get_min_trade_margin(
                symbol=symbol,
                leverage=max(1, int(leverage_override or settings.leverage)),
                base_usdt_amount=1.0,
            )
            if required_margin > available_balance:
                continue

            new_trade = _open_single_replacement_trade(
                replacement_symbol=symbol,
                trader=trader,
                settings=settings,
                allocated_margin=required_margin,
                fresh_ranked=fresh_ranked,
                leverage_override=leverage_override,
            )
            if not new_trade:
                log_lines.append(f"  ↳ Retry mở {symbol} thất bại")
                continue

            opened_trades.append(new_trade)
            working_active_trades.append(new_trade)
            excluded_symbols.add(symbol)
            used_margin = float(new_trade.get("allocated_margin") or required_margin)
            available_balance = max(0.0, available_balance - used_margin)
            log_lines.append(f"  ↳ Top-up mở {symbol} (margin ≈ {used_margin:.4f} USDT)")

            if available_balance < 1.0:
                break
        except Exception as exc:
            log_lines.append(f"  ↳ Retry mở {symbol} lỗi: {exc}")

    return opened_trades, log_lines


def _run_multi_trade_cycle(
    token: str,
    chat_id: str,
    stop_event: threading.Event,
    close_target_usdt: float,
    review_after_sec: int | None = None,
    leverage_override: int | None = None,
) -> None:
    settings = load_settings()
    accumulated_realized_pnl = 0.0
    cycle_index = 0

    while not stop_event.is_set():
        cycle_index += 1

        try:
            batch = _build_cycle_trades(leverage_override=leverage_override)
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
        budget_used = float(batch.get("budget_used") or 0.0)
        reserve_balance = float(batch.get("reserve_balance") or 0.0)
        remaining_budget = float(batch.get("remaining_budget") or 0.0)

        mode = "PAPER"
        if active_trades:
            first_plan = active_trades[0].get("trade_plan", {})
            mode = "PAPER" if bool(first_plan.get("dry_run")) else "BINANCE"

        symbols_text = ", ".join(
            str(item.get("trade_plan", {}).get("symbol") or "") for item in active_trades
        )
        effective_review_after_sec = int(review_after_sec) if review_after_sec is not None else int(settings.adaptive_review_min * 60)
        header_lines = [
            f"Batch {cycle_index} started | Mode: {mode}",
            f"Balance: {available_balance:.4f} USDT | Opened: {len(active_trades)} lệnh | Coins: {symbols_text}",
            f"Budget used: {budget_used:.4f} | Reserve: {reserve_balance:.4f} | Remaining: {remaining_budget:.4f}",
            f"Close condition: tổng pnl >= {close_target_usdt:.4f} USDT",
            f"Adaptive review (AI tự động): sau {effective_review_after_sec}s nếu PnL âm",
            f"Leverage override: {leverage_override}x" if leverage_override is not None else f"Leverage mode: adaptive <= {settings.leverage}x",
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

        batch_start_time = time.time()
        last_review_bucket = 0

        while not stop_event.is_set():
            remaining = settings.pnl_refresh_sec
            while remaining > 0 and not stop_event.is_set():
                time.sleep(1)
                remaining -= 1

            if stop_event.is_set():
                break

            elapsed_sec = time.time() - batch_start_time
            review_threshold_sec = effective_review_after_sec
            current_review_bucket = int(elapsed_sec // review_threshold_sec) if review_threshold_sec > 0 else 0
            next_review_due_sec = review_threshold_sec * (current_review_bucket + 1) if review_threshold_sec > 0 else 0
            next_review_in_sec = max(0, int(next_review_due_sec - elapsed_sec)) if review_threshold_sec > 0 else None

            try:
                report, total_pnl = _format_cycle_report(
                    cycle_index,
                    accumulated_realized_pnl,
                    active_trades,
                    price_trader,
                    live_pnl_trader,
                    next_review_in_sec=next_review_in_sec,
                )
                _send_message(token, chat_id, report)
            except Exception as exc:
                _send_message(token, chat_id, f"Lỗi refresh PnL batch {cycle_index}: {exc}")
                continue

            # ---------------------------------------------------------------
            # Adaptive review trigger: after N seconds with negative PnL
            # ---------------------------------------------------------------
            if (
                review_threshold_sec > 0
                and current_review_bucket > last_review_bucket
                and not stop_event.is_set()
                and active_trades
            ):
                last_review_bucket = current_review_bucket
                if total_pnl < close_target_usdt:
                    elapsed_s = int(elapsed_sec)
                    _send_message(
                        token,
                        chat_id,
                        f"⏰ {elapsed_s}s đã trôi qua – bắt đầu adaptive review (PnL {total_pnl:+.4f} USDT / target {close_target_usdt:+.4f}). "
                        "Đang phân tích từng vị thế...",
                    )
                    try:
                        recommendations, fresh_ranked, llm_src = _build_adaptive_review_recommendations(
                            active_trades,
                            live_pnl_trader,
                            price_trader,
                            settings,
                        )
                        action_summary = ", ".join(
                            f"{rec['symbol']}={rec['action']}" for rec in recommendations
                        )
                        _send_message(
                            token,
                            chat_id,
                            (
                                f"🧠 Adaptive review ({llm_src}) sau {elapsed_s}s: {action_summary}. "
                                "Đang tự động thực thi..."
                            ),
                        )

                        first_plan = active_trades[0].get("trade_plan", {}) if active_trades else {}
                        is_paper = bool(first_plan.get("dry_run"))
                        exec_trader = live_pnl_trader if (live_pnl_trader and not is_paper) else price_trader
                        active_trades = _auto_execute_review_actions(
                            recommendations=recommendations,
                            active_trades=active_trades,
                            live_trader=exec_trader,
                            settings=settings,
                            token=token,
                            chat_id=chat_id,
                            fresh_ranked=fresh_ranked,
                            leverage_override=leverage_override,
                        )

                        if active_trades:
                            new_symbols = ", ".join(
                                str(t.get("trade_plan", {}).get("symbol") or "") for t in active_trades
                            )
                            _send_message(
                                token,
                                chat_id,
                                f"Portfolio sau adaptive review: {new_symbols} ({len(active_trades)} vị thế)",
                            )
                        else:
                            _send_message(
                                token,
                                chat_id,
                                "Tất cả vị thế đã đóng sau adaptive review – bắt đầu batch mới.",
                            )
                            break  # restart outer while loop to open new batch
                    except Exception as exc:
                        _send_message(token, chat_id, f"Lỗi adaptive review: {exc}")

            # ---------------------------------------------------------------
            # Normal close condition
            # ---------------------------------------------------------------
            if total_pnl >= close_target_usdt:
                try:
                    first_plan = active_trades[0].get("trade_plan", {}) if active_trades else {}
                    is_paper = bool(first_plan.get("dry_run"))
                    pnl_snapshots = _collect_trade_pnl_snapshots(
                        active_trades,
                        price_trader,
                        live_pnl_trader,
                    )
                    for snapshot in pnl_snapshots:
                        pnl_value = float(snapshot.get("pnl") or 0.0)
                        _remember_symbol_outcome(
                            str(snapshot.get("symbol") or ""),
                            pnl_value,
                            force_exclude=pnl_value <= 0,
                        )
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
            "/trade hoặc /trade <target_usdt> [review_after_sec] [leverage] (multi-coin cycle)\n"
            "/sell hoặc /sell <keyword1,keyword2> (scan sản phẩm e-commerce)\n"
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

    if command.startswith("/sell"):
        raw_text = text.strip()
        parts = raw_text.split(maxsplit=1)
        keywords: list[str] | None = None
        if len(parts) == 2 and parts[1].strip():
            keywords = [kw.strip() for kw in parts[1].split(",") if kw.strip()]
        output = run_sell_scan(keywords=keywords)
        return _format_sell_report(output), False, output, False

    if command == "/trade":
        return "Đang khởi động chế độ multi-coin cycle...", False, None, False

    return "Lệnh không hợp lệ. Dùng /trade, /sell hoặc /run openclaw trading", False, None, False


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
                            review_after_sec: int | None = None
                            leverage_override: int | None = None

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

                            if len(parts) >= 3:
                                try:
                                    parsed_review_sec = int(parts[2])
                                    if parsed_review_sec <= 0:
                                        _send_message(token, chat_id, "review_after_sec phải > 0. Ví dụ: /trade 0.1 15")
                                        continue
                                    review_after_sec = parsed_review_sec
                                except ValueError:
                                    _send_message(token, chat_id, "Sai format. Dùng: /trade hoặc /trade 0.1 15")
                                    continue

                            if len(parts) >= 4:
                                try:
                                    parsed_leverage = int(parts[3])
                                    if parsed_leverage <= 0:
                                        _send_message(token, chat_id, "leverage phải > 0. Ví dụ: /trade 0.1 500 10")
                                        continue
                                    leverage_override = parsed_leverage
                                except ValueError:
                                    _send_message(token, chat_id, "Sai format. Dùng: /trade hoặc /trade 0.1 500 10")
                                    continue

                            if cycle_thread is not None and cycle_thread.is_alive():
                                _send_message(token, chat_id, "⏳ Multi-coin cycle đang chạy, vui lòng chờ hoặc dùng /stop.")
                                continue

                            review_text = (
                                f"{review_after_sec}s"
                                if review_after_sec is not None
                                else f"{settings.adaptive_review_min * 60}s"
                            )
                            leverage_text = (
                                f"{leverage_override}x"
                                if leverage_override is not None
                                else f"adaptive <= {settings.leverage}x"
                            )

                            _send_message(
                                token,
                                chat_id,
                                (
                                    "Đang khởi động multi-coin cycle: chọn coin theo số dư, "
                                    f"report PnL mỗi {settings.pnl_refresh_sec}s, "
                                    f"close all khi tổng pnl >= {target_usdt:.4f} USDT. "
                                    f"AI tự rotate coin nếu PnL âm sau {review_text}. "
                                    f"Leverage: {leverage_text}."
                                ),
                            )
                            cycle_thread = threading.Thread(
                                target=_run_multi_trade_cycle,
                                args=(token, chat_id, stop_event, target_usdt, review_after_sec, leverage_override),
                                daemon=True,
                            )
                            cycle_thread.start()
                            _send_message(token, chat_id, f"✅ Multi-coin cycle đã bắt đầu với target {target_usdt:.4f} USDT.")
                            continue

                        if text.strip().lower() == "/run openclaw trading":
                            _send_message(token, chat_id, "Đang làm việc... quét thị trường, chọn coin và chuẩn bị lệnh.")

                        if text.strip().lower().startswith("/sell"):
                            _send_message(token, chat_id, "Đang quét sàn TMĐT và tìm chênh lệch giá...")

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
