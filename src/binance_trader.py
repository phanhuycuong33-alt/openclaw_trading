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

    def _exchange_info(self) -> dict[str, Any]:
        if self._exchange_info_cache is None:
            self._exchange_info_cache = self.client.futures_exchange_info()
        return self._exchange_info_cache

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

    def close_position_market(self, symbol: str) -> dict[str, Any] | None:
        position_amt = self.get_position_amount(symbol)
        if position_amt == 0:
            return None

        side = "SELL" if position_amt > 0 else "BUY"
        qty = abs(position_amt)
        return self.client.futures_create_order(
            symbol=symbol.upper(),
            side=side,
            type="MARKET",
            quantity=qty,
            reduceOnly=True,
        )

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
    def _round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        return (value // step) * step

    @staticmethod
    def _extract_filter(symbol_info: dict[str, Any], filter_type: str) -> dict[str, Any]:
        for f in symbol_info.get("filters", []):
            if f.get("filterType") == filter_type:
                return f
        raise ValueError(f"Thiếu filter {filter_type}")

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
        opposite_side = "SELL" if plan.side == "BUY" else "BUY"

        if plan.dry_run:
            return {
                "mode": "DRY_RUN",
                "entry_order": {
                    "symbol": plan.symbol,
                    "side": plan.side,
                    "type": "MARKET",
                    "quantity": plan.quantity,
                },
                "tp_order": {
                    "symbol": plan.symbol,
                    "side": opposite_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": plan.take_profit,
                    "closePosition": True,
                },
                "sl_order": {
                    "symbol": plan.symbol,
                    "side": opposite_side,
                    "type": "STOP_MARKET",
                    "stopPrice": plan.stop_loss,
                    "closePosition": True,
                },
            }

        try:
            self.client.futures_change_margin_type(symbol=plan.symbol, marginType="ISOLATED")
        except BinanceAPIException as exc:
            if exc.code not in (-4046,):
                raise

        self.client.futures_change_leverage(symbol=plan.symbol, leverage=plan.leverage)

        entry_order = self.client.futures_create_order(
            symbol=plan.symbol,
            side=plan.side,
            type="MARKET",
            quantity=plan.quantity,
        )

        tp_order = self.client.futures_create_order(
            symbol=plan.symbol,
            side=opposite_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=plan.take_profit,
            closePosition=True,
            workingType="MARK_PRICE",
        )

        sl_order = self.client.futures_create_order(
            symbol=plan.symbol,
            side=opposite_side,
            type="STOP_MARKET",
            stopPrice=plan.stop_loss,
            closePosition=True,
            workingType="MARK_PRICE",
        )

        return {
            "mode": "LIVE",
            "entry_order": entry_order,
            "tp_order": tp_order,
            "sl_order": sl_order,
        }
