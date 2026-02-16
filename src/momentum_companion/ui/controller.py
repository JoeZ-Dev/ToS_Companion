from __future__ import annotations

from typing import Any

from momentum_companion.llm.service import LLMService
from momentum_companion.ui.main_window import MainWindow
from momentum_companion.ui.chart_widget import ChartWidget


class UIController:
    """Coordinates UI state, signals/slots, and renders updates (§4.1)."""

    def __init__(self, window: MainWindow, llm_service: LLMService) -> None:
        self._window = window
        self._llm_service = llm_service

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
