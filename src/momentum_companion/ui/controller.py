from __future__ import annotations

from typing import Any

from momentum_companion.llm.service import LLMService
from momentum_companion.ui.main_window import MainWindow
from momentum_companion.ui.chart_widget import ChartWidget


class UIController:
    """Coordinates UI state, signals/slots, and renders updates (§4.1)."""

    def __init__(self, window: MainWindow, llm_service: LLMService, rest_client=None) -> None:
        self._window = window
        self._llm_service = llm_service
        self._rest_client = rest_client
        self._hook_symbol_input()

    def handle_flash(self, symbol: str, rec: dict, payload: dict) -> None:
        """Trigger flash alert in UI."""
        self._window.flash_alert(f"Flash change for {symbol}")
        self._window.apply_llm_recommendation(rec)

    def handle_llm_output(self, rec: dict) -> None:
        """Render LLM recommendation."""
        self._window.apply_llm_recommendation(rec)

    def render_chart(self, bars: list[dict]) -> None:
        """Update chart widget with candlesticks."""
        times = [b["ts"] for b in bars]
        opens = [b["open"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        chart: ChartWidget = self._window.findChild(ChartWidget)
        if chart:
            chart.render_bars(times, opens, highs, lows, closes)

    def _hook_symbol_input(self) -> None:
        if hasattr(self._window, "symbol_input"):
            self._window.symbol_input.returnPressed.connect(self._on_symbol_entered)  # type: ignore[attr-defined]

    def _on_symbol_entered(self) -> None:
        symbol = self._window.symbol_input.text().strip().upper()
        if not symbol:
            return
        self._window.connection_label.setText("Connection: REQUESTED")
        self._window.banner.setText(f"Requested symbol: {symbol}")
        self._load_history(symbol)

    def _load_history(self, symbol: str) -> None:
        """Fetch minimal price history to seed chart."""
        if not self._rest_client:
            return
        try:
            self._window.banner.setText("")
            resp = self._rest_client.fetch_price_history(symbol, None, None, "day")
            candles = resp.get("candles") or []
            bars = [
                {"ts": c.get("datetime"), "open": c.get("open"), "high": c.get("high"), "low": c.get("low"), "close": c.get("close")}
                for c in candles
            ]
            if bars:
                self.render_chart(bars[-50:])  # show recent slice
                self._window.banner.setText("")
                self._window.connection_label.setText("Connection: READY (history)")
                self._window.last_update_label.setText(f"Last Update: history for {symbol}")
            else:
                self._window.banner.setText(f"No history data for {symbol}")
                self._window.connection_label.setText("Connection: READY (no data)")
        except Exception as exc:  # noqa: BLE001
            self._window.banner.setText(f"History load failed for {symbol}")
