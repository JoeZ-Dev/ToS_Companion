from __future__ import annotations

from typing import Any


class SyntheticTriggerEngine:
    """Manages synthetic stops/triggers (arming, disarming, firing) per specs.md §9.4."""

    def __init__(self, trade_executor: Any) -> None:
        self._trade_executor = trade_executor
        self._armed = {}

    def arm_stop(self, symbol: str, stop_price: float, side: str) -> None:
        """Arm a synthetic stop."""
        self._armed[symbol] = {"stop_price": stop_price, "side": side}

    def disarm(self, symbol: str) -> None:
        """Disarm all triggers for the symbol."""
        if symbol in self._armed:
            del self._armed[symbol]

    def on_quote(self, quote: Any) -> None:
        """Evaluate triggers on incoming quotes."""
        symbol = quote.get("symbol")
        if symbol not in self._armed:
            return
        trig = self._armed[symbol]
        stop_price = trig["stop_price"]
        side = trig["side"]
        if side.upper() == "SELL" and quote.get("bid") is not None and quote["bid"] <= stop_price:
            self._trade_executor.submit_order({"symbol": symbol, "side": "SELL", "qty": quote.get("qty", 0)})
            self.disarm(symbol)
        if side.upper() == "BUY" and quote.get("ask") is not None and quote["ask"] >= stop_price:
            self._trade_executor.submit_order({"symbol": symbol, "side": "BUY", "qty": quote.get("qty", 0)})
            self.disarm(symbol)
