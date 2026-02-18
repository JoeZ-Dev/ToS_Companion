from __future__ import annotations

from typing import Any

from momentum_companion.llm.service import LLMService
from momentum_companion.ui.main_window import MainWindow
from momentum_companion.ui.chart_widget import ChartWidget
from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.data.contracts import QuoteEvent


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
        self._subscribe_stream(symbol)

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
        self._stream_client = SchwabStreamClient(
            streamer_info, on_quote=self._handle_quote, token_provider=self._token_provider, state_callback=None
        )
        self._window.connection_label.setText("Connection: CONNECTING")
        self._stream_client.connect()
        return self._stream_client

    def _handle_quote(self, event: QuoteEvent) -> None:
        ts_ms = event.get("ts_ms")
        self._window.connection_label.setText("Connection: STREAMING")
        if ts_ms:
            self._window.last_update_label.setText(f"Last Update: {ts_ms}")
        self._window.update_quote_display(event.get("bid"), event.get("ask"), event.get("last"), ts_ms)
