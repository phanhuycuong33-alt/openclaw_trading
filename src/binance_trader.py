from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from binance.client import Client
from binance.exceptions import BinanceAPIException


@dataclass
class TradePlan:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    take_profit: float
    stop_loss: float
    leverage: int
    dry_run: bool


class BinanceFuturesTrader:
    def __init__(self, api_key: str, api_secret: str, dry_run: bool = True) -> None:
        if not dry_run and (not api_key or not api_secret):
            raise ValueError("Thiếu BINANCE_API_KEY hoặc BINANCE_API_SECRET")

        self.dry_run = dry_run
        self.client = Client(api_key, api_secret)
        self._exchange_info_cache: dict[str, Any] | None = None
        self._hedge_mode_cache: bool | None = None

    def _exchange_info(self) -> dict[str, Any]:
        if self._exchange_info_cache is None:
            self._exchange_info_cache = self.client.futures_exchange_info()
        return self._exchange_info_cache

    def _is_hedge_mode(self) -> bool:
        if self._hedge_mode_cache is None:
            payload = self.client.futures_get_position_mode()
            self._hedge_mode_cache = bool(payload.get("dualSidePosition"))
        return self._hedge_mode_cache

    @staticmethod
    def _order_position_side(side: str) -> str:
        return "LONG" if side.upper() == "BUY" else "SHORT"

    def get_available_usdt_balance(self) -> float:
        balances = self.client.futures_account_balance()
        for item in balances:
            if item.get("asset") == "USDT":
                return float(item.get("availableBalance") or 0.0)
        return 0.0

    def get_symbol_price(self, symbol: str) -> float:
        ticker = self.client.futures_symbol_ticker(symbol=symbol.upper())
        return float(ticker["price"])

    def get_position_amount(self, symbol: str) -> float:
        positions = self.client.futures_position_information(symbol=symbol.upper())
        if not positions:
            return 0.0
        return float(positions[0].get("positionAmt") or 0.0)

    def get_position_snapshot(self, symbol: str) -> dict[str, Any]:
        positions = self.client.futures_position_information(symbol=symbol.upper())
        if not positions:
            return {
                "symbol": symbol.upper(),
                "position_amt": 0.0,
                "entry_price": 0.0,
                "mark_price": 0.0,
                "unrealized_pnl": 0.0,
                "side": "FLAT",
            }

        item = positions[0]
        position_amt = float(item.get("positionAmt") or 0.0)
        entry_price = float(item.get("entryPrice") or 0.0)
        mark_price = float(item.get("markPrice") or 0.0)
        unrealized_pnl = float(item.get("unRealizedProfit") or 0.0)
        side = "LONG" if position_amt > 0 else ("SHORT" if position_amt < 0 else "FLAT")

        return {
            "symbol": symbol.upper(),
            "position_amt": position_amt,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "unrealized_pnl": unrealized_pnl,
            "side": side,
        }

    def get_open_positions(self) -> list[dict[str, Any]]:
        positions = self.client.futures_position_information()
        results: list[dict[str, Any]] = []
        for item in positions:
            position_amt = float(item.get("positionAmt") or 0.0)
            if position_amt == 0:
                continue
            results.append(
                {
                    "symbol": str(item.get("symbol") or "").upper(),
                    "position_amt": position_amt,
                    "position_side": str(item.get("positionSide") or "BOTH").upper(),
                    "entry_price": float(item.get("entryPrice") or 0.0),
                    "mark_price": float(item.get("markPrice") or 0.0),
                    "unrealized_pnl": float(item.get("unRealizedProfit") or 0.0),
                }
            )
        return results

    def close_position_from_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(snapshot.get("symbol") or "").upper()
        position_amt = float(snapshot.get("position_amt") or 0.0)
        if not symbol or position_amt == 0:
            return None

        side = "SELL" if position_amt > 0 else "BUY"
        quantity = abs(position_amt)
        position_side = str(snapshot.get("position_side") or "BOTH").upper()

        order_args: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }

        if self._is_hedge_mode():
            order_args["positionSide"] = "LONG" if position_side in {"LONG", "BOTH"} and position_amt > 0 else "SHORT"
        else:
            order_args["reduceOnly"] = True

        return self.client.futures_create_order(**order_args)

    def close_all_open_positions(self) -> dict[str, Any]:
        positions = self.get_open_positions()
        closed = 0
        errors: list[str] = []

        for position in positions:
            try:
                result = self.close_position_from_snapshot(position)
                if result is not None:
                    closed += 1
            except Exception as exc:
                errors.append(f"{position.get('symbol')}: {exc}")

        return {
            "closed": closed,
            "errors": errors,
            "requested": len(positions),
        }

    def close_position_market(self, symbol: str) -> dict[str, Any] | None:
        position_amt = self.get_position_amount(symbol)
        if position_amt == 0:
            return None

        side = "SELL" if position_amt > 0 else "BUY"
        qty = abs(position_amt)
        order_args: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "reduceOnly": True,
        }
        if self._is_hedge_mode():
            order_args["positionSide"] = "LONG" if position_amt > 0 else "SHORT"
            order_args.pop("reduceOnly", None)
        return self.client.futures_create_order(**order_args)

    def supports_symbol(self, symbol: str) -> bool:
        symbol = symbol.upper()
        info = self._exchange_info()
        for item in info.get("symbols", []):
            if (
                item.get("symbol") == symbol
                and item.get("contractType") == "PERPETUAL"
                and item.get("status") == "TRADING"
            ):
                return True
        return False

    def _get_symbol_filters(self, symbol: str) -> dict[str, Any]:
        info = self._exchange_info()
        for item in info["symbols"]:
            if item["symbol"] == symbol and item.get("contractType") == "PERPETUAL":
                return item
        raise ValueError(f"Không tìm thấy symbol futures: {symbol}")

    @staticmethod
    def _step_precision(step: float) -> int:
        text = f"{step:.16f}".rstrip("0")
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1])

    @staticmethod
    def _round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        precision = BinanceFuturesTrader._step_precision(step)
        rounded = (value // step) * step
        return round(rounded, precision)

    @staticmethod
    def _extract_filter(symbol_info: dict[str, Any], filter_type: str) -> dict[str, Any]:
        for f in symbol_info.get("filters", []):
            if f.get("filterType") == filter_type:
                return f
        raise ValueError(f"Thiếu filter {filter_type}")

    @staticmethod
    def _round_step_up(value: float, step: float) -> float:
        if step <= 0:
            return value
        quotient = value / step
        rounded_units = int(-(-quotient // 1))
        precision = BinanceFuturesTrader._step_precision(step)
        return round(rounded_units * step, precision)

    def _get_min_order_notional(self, symbol_info: dict[str, Any]) -> float:
        for filter_type in ("MIN_NOTIONAL", "NOTIONAL"):
            try:
                flt = self._extract_filter(symbol_info, filter_type)
            except ValueError:
                continue
            raw = flt.get("notional") or flt.get("minNotional") or 0.0
            try:
                return float(raw or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def get_min_trade_margin(self, symbol: str, leverage: int, base_usdt_amount: float = 1.0) -> float:
        symbol = symbol.upper()
        symbol_info = self._get_symbol_filters(symbol)

        ticker = self.client.futures_symbol_ticker(symbol=symbol)
        entry_price = float(ticker["price"])

        lot_filter = self._extract_filter(symbol_info, "LOT_SIZE")
        step_size = float(lot_filter["stepSize"])
        min_qty = float(lot_filter["minQty"])

        min_notional = self._get_min_order_notional(symbol_info)
        qty_for_notional = min_qty
        if min_notional > 0:
            qty_for_notional = max(min_qty, self._round_step_up(min_notional / entry_price, step_size))

        required_notional = qty_for_notional * entry_price
        required_margin = required_notional / max(leverage, 1)
        return max(base_usdt_amount, required_margin)

    def build_trade_plan(
        self,
        symbol: str,
        side: str,
        usdt_amount: float,
        leverage: int,
        take_profit: float,
        stop_loss: float,
    ) -> TradePlan:
        symbol = symbol.upper()
        symbol_info = self._get_symbol_filters(symbol)

        ticker = self.client.futures_symbol_ticker(symbol=symbol)
        entry_price = float(ticker["price"])

        lot_filter = self._extract_filter(symbol_info, "LOT_SIZE")
        step_size = float(lot_filter["stepSize"])
        min_qty = float(lot_filter["minQty"])

        price_filter = self._extract_filter(symbol_info, "PRICE_FILTER")
        tick_size = float(price_filter["tickSize"])

        notional = usdt_amount * leverage
        raw_qty = notional / entry_price
        quantity = self._round_step(raw_qty, step_size)

        if quantity < min_qty:
            quantity = min_qty

        order_notional = quantity * entry_price
        min_notional = self._get_min_order_notional(symbol_info)
        if min_notional > 0 and order_notional < min_notional:
            min_qty_for_notional = self._round_step_up(min_notional / entry_price, step_size)
            quantity = max(quantity, min_qty_for_notional)
            order_notional = quantity * entry_price
            required_margin = order_notional / max(leverage, 1)
            if order_notional < min_notional:
                raise ValueError(
                    (
                        f"{symbol} yêu cầu notional tối thiểu {min_notional:.4f} USDT, "
                        f"nhưng lệnh hiện tại chỉ có {order_notional:.4f} USDT. "
                        f"Cần tối thiểu margin khoảng {required_margin:.4f} USDT ở leverage {leverage}x."
                    )
                )

        tp = self._round_step(take_profit, tick_size)
        sl = self._round_step(stop_loss, tick_size)

        return TradePlan(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            take_profit=tp,
            stop_loss=sl,
            leverage=leverage,
            dry_run=self.dry_run,
        )

    def execute_trade(self, plan: TradePlan) -> dict[str, Any]:
        hedge_mode = self._is_hedge_mode()
        position_side = self._order_position_side(plan.side)

        if plan.dry_run:
            return {
                "mode": "DRY_RUN",
                "entry_order": {
                    "symbol": plan.symbol,
                    "side": plan.side,
                    "type": "MARKET",
                    "quantity": plan.quantity,
                    "positionSide": position_side if hedge_mode else None,
                },
                "tp_order": None,
                "sl_order": None,
                "warnings": ["TP/SL không đặt trên sàn; bot sẽ monitor runtime để quản lý thoát lệnh."],
            }

        try:
            self.client.futures_change_margin_type(symbol=plan.symbol, marginType="ISOLATED")
        except BinanceAPIException as exc:
            if exc.code not in (-4046,):
                raise

        self.client.futures_change_leverage(symbol=plan.symbol, leverage=plan.leverage)

        entry_args: dict[str, Any] = {
            "symbol": plan.symbol,
            "side": plan.side,
            "type": "MARKET",
            "quantity": plan.quantity,
        }
        if hedge_mode:
            entry_args["positionSide"] = position_side

        entry_order = self.client.futures_create_order(**entry_args)

        return {
            "mode": "LIVE_RUNTIME_MONITOR",
            "entry_order": entry_order,
            "tp_order": None,
            "sl_order": None,
            "warnings": ["TP/SL không đặt trên sàn; bot sẽ monitor runtime để quản lý thoát lệnh."],
        }
