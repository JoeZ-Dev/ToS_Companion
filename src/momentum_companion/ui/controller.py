from __future__ import annotations

from typing import Any
import time
from functools import partial

from PySide6 import QtCore

from momentum_companion.llm.service import LLMService
from momentum_companion.ui.main_window import MainWindow
from momentum_companion.ui.chart_widget import ChartWidget
from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.data.contracts import QuoteEvent
from momentum_companion.data.bar_aggregator import BarAggregator10s, TenSecondBar


class UIController:
    """Coordinates UI state, signals/slots, and renders updates (§4.1)."""

    def __init__(
        self,
        window: MainWindow,
        llm_service: LLMService,
        rest_client: SchwabRestClient | None = None,
        stream_client: SchwabStreamClient | None = None,
        token_provider: TokenProvider | None = None,
    ) -> None:
        self._window = window
        self._llm_service = llm_service
        self._rest_client = rest_client
        self._stream_client = stream_client
        self._token_provider = token_provider
        self._aggregator = BarAggregator10s()
        self._bars: list[dict] = []
        self._pending_symbol: str | None = None
        self._display_window_ms = 10 * 60 * 1000  # 10 minutes
        self._last_render_monotonic = 0.0
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
        self._pending_symbol = symbol
        self._aggregator = BarAggregator10s()
        self._bars = []
        self._window.symbol_input.setDisabled(True)
        self._window.connection_label.setText("Connection: REQUESTED")
        self._window.banner.setText(f"Requested symbol: {symbol}")
        self._load_history(symbol)
        self._subscribe_stream(symbol)
        self._window.symbol_input.setDisabled(False)

    def _load_history(self, symbol: str) -> None:
        """Fetch minimal price history to seed chart."""
        if not self._rest_client:
            return
        try:
            self._window.banner.setText("")
            end_ms = int(time.time() * 1000)
            start_ms = end_ms - self._display_window_ms
            resp = self._rest_client.fetch_price_history(symbol, start_ms, end_ms, "day")
            candles = resp.get("candles") or []
            self._bars = [
                {"ts": c.get("datetime"), "open": c.get("open"), "high": c.get("high"), "low": c.get("low"), "close": c.get("close")}
                for c in candles
            ]
            if self._bars:
                self.render_chart(self._bars[-50:])  # show recent slice
                self._window.banner.setText("")
                self._window.connection_label.setText("Connection: READY (history)")
                self._window.last_update_label.setText(f"Last Update: history for {symbol}")
            else:
                self._window.banner.setText(f"No history data for {symbol}")
                self._window.connection_label.setText("Connection: READY (no data)")
        except Exception as exc:  # noqa: BLE001
            self._window.banner.setText(f"History load failed for {symbol}")
            self._window.connection_label.setText("Connection: HISTORY ERROR")

    def _subscribe_stream(self, symbol: str) -> None:
        client = self._ensure_stream_client()
        if not client:
            return
        client.subscribe_level_one(symbol)
        self._window.connection_label.setText("Connection: STREAM SUBSCRIBED")

    def _ensure_stream_client(self) -> SchwabStreamClient | None:
        if self._stream_client:
            return self._stream_client
        if not self._rest_client or not self._token_provider:
            self._window.banner.setText("Stream not available (missing rest/token)")
            return None
        try:
            prefs = self._rest_client.get_user_preference()
            streamer_info = prefs[0]["streamerInfo"][0] if isinstance(prefs, list) else prefs["streamerInfo"][0]
        except Exception:
            self._window.banner.setText("Failed to load streamer info")
            return None
        try:
            self._stream_client = SchwabStreamClient(
                streamer_info,
                on_quote=self._handle_quote,
                token_provider=self._token_provider,
                state_callback=self._on_stream_state,
            )
            self._window.connection_label.setText("Connection: CONNECTING")
            self._stream_client.connect()
        except Exception as exc:  # noqa: BLE001
            self._window.banner.setText(f"Stream connect failed: {exc}")
            self._window.connection_label.setText("Connection: STREAM ERROR")
            return None
        self._window.connection_label.setText("Connection: CONNECTING")
        return self._stream_client

    def _handle_quote(self, event: QuoteEvent) -> None:
        # Called from stream thread; marshal to UI thread.
        QtCore.QTimer.singleShot(0, partial(self._process_quote_ui, event))

    def _process_quote_ui(self, event: QuoteEvent) -> None:
        ts_ms = event.get("ts_ms")
        self._window.connection_label.setText("Connection: STREAMING")
        if ts_ms:
            self._window.last_update_label.setText(f"Last Update: {ts_ms}")
        self._window.update_quote_display(event.get("bid"), event.get("ask"), event.get("last"), ts_ms)
        completed = self._aggregator.ingest_quote(event)
        if completed:
            self._append_bar(completed)
        self._render_live_chart()
        self._window.stream_label.setText("Stream: CONNECTED")

    def _append_bar(self, bar: TenSecondBar) -> None:
        bar_dict = {"ts": bar.ts_ms, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}
        self._bars.append(bar_dict)
        self.render_chart(self._bars[-50:])

    def _render_live_chart(self) -> None:
        now = time.time()
        # simple throttle to avoid overwhelming WebView; ~2 fps
        if now - self._last_render_monotonic < 0.5:
            return
        self._last_render_monotonic = now
        forming = self._aggregator.forming_bar()
        cutoff = (forming.ts_ms if forming else int(time.time() * 1000)) - self._display_window_ms
        window_bars = [b for b in self._bars if b.get("ts") is not None and b["ts"] >= cutoff]
        if forming:
            window_bars.append({"ts": forming.ts_ms, "open": forming.open, "high": forming.high, "low": forming.low, "close": forming.close})
        if window_bars:
            self.render_chart(window_bars)

    def _on_stream_state(self, state: str) -> None:
        """Update UI with stream state transitions."""
        QtCore.QTimer.singleShot(0, partial(self._apply_stream_state_ui, state))

    def _apply_stream_state_ui(self, state: str) -> None:
        self._window.stream_label.setText(f"Stream: {state}")
        if state in {"DOWN", "STREAM_DOWN", "LOGIN_FAILED"}:
            self._window.banner.setText("Stream unavailable. Check auth/connection.")
            self._window.connection_label.setText("Connection: STREAM ERROR")
        elif state == "CONNECTED":
            self._window.connection_label.setText("Connection: STREAM CONNECTED")
            if self._pending_symbol and self._stream_client:
                self._stream_client.subscribe_level_one(self._pending_symbol)
        elif state == "RECONNECTING":
            self._window.connection_label.setText("Connection: RECONNECTING")
        elif state == "CONNECTING":
            self._window.connection_label.setText("Connection: CONNECTING")
