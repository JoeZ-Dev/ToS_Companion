from __future__ import annotations

from typing import Any
import time
import threading
from functools import partial
from PySide6 import QtCore

from momentum_companion.llm.service import LLMService
from momentum_companion.ui.main_window import MainWindow
from momentum_companion.ui.chart_adapter import ChartAdapter
from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.data.contracts import QuoteEvent
from momentum_companion.data.bar_aggregator import BarAggregator10s, TenSecondBar
from momentum_companion.data.price_update import PriceUpdate


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
        self._display_window_sec = 60 * 60  # 1 hour window
        self._bars_lock = threading.Lock()
        self._render_timer = QtCore.QTimer()
        self._render_timer.setInterval(100)  # 10fps target
        self._render_timer.timeout.connect(self._render_tick)  # type: ignore[arg-type]
        self._render_timer.start()
        self._dirty = False
        self._last_forming_sig: tuple[int | None, float | None] = (None, None)
        self._hook_symbol_input()
        self._chart_adapter = ChartAdapter(self._window.chart_widget)
        self._initial_render_done = False

    def handle_flash(self, symbol: str, rec: dict, payload: dict) -> None:
        """Trigger flash alert in UI."""
        self._window.flash_alert(f"Flash change for {symbol}")
        self._window.apply_llm_recommendation(rec)

    def handle_llm_output(self, rec: dict) -> None:
        """Render LLM recommendation."""
        self._window.apply_llm_recommendation(rec)

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
        self._initial_render_done = False
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
            start_ms = end_ms - (self._display_window_sec * 1000)
            resp = self._rest_client.fetch_price_history(symbol, start_ms, end_ms, "day")
            candles = resp.get("candles") or []
            self._bars = [
                {"time": int(c.get("datetime") // 1000), "open": c.get("open"), "high": c.get("high"), "low": c.get("low"), "close": c.get("close")}
                for c in candles
                if c.get("datetime") is not None
            ]
            if self._bars:
                seed = self._bars[-180:]
                self._chart_adapter.set_history(seed)
                self._initial_render_done = True
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
        bid = event.get("bid")
        ask = event.get("ask")
        last = event.get("last")
        ts_ms = event.get("ts_ms")
        try:
            if ts_ms and last is not None:
                pu = PriceUpdate(timestamp=int(ts_ms // 1000), price=last, size=event.get("volume"), source="L1")
                with self._bars_lock:
                    completed = self._aggregator.ingest_price(pu)
                    if completed:
                        self._append_bar_locked(completed)
                        self._dirty = True
                    forming = self._aggregator.forming_bar()
                    sig = (forming.ts if forming else None, forming.close if forming else None)
                    if sig != self._last_forming_sig:
                        self._dirty = True
                        self._last_forming_sig = sig
        except Exception as exc:  # noqa: BLE001
            from momentum_companion.utils.logging import logging

            logging.getLogger(__name__).error("Quote handling failed: %s", exc, exc_info=True)
        # UI label updates on main thread
        QtCore.QTimer.singleShot(0, partial(self._update_labels_ui, ts_ms, bid, ask, last))

    def _update_labels_ui(self, ts_ms: int | None, bid: float | None, ask: float | None, last: float | None) -> None:
        self._window.connection_label.setText("Connection: STREAMING")
        if ts_ms:
            self._window.last_update_label.setText(f"Last Update: {ts_ms}")
        self._window.update_quote_display(bid, ask, last, ts_ms)

    def _append_bar(self, bar: TenSecondBar) -> None:
        with self._bars_lock:
            self._append_bar_locked(bar)

    def _append_bar_locked(self, bar: TenSecondBar) -> None:
        bar_dict = {"time": bar.ts, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume}
        self._bars.append(bar_dict)
        if len(self._bars) > 180:
            self._bars = self._bars[-180:]

    def _prune_and_render(self) -> None:
        cutoff_sec = int(time.time()) - self._display_window_sec
        with self._bars_lock:
            window_bars = [b for b in self._bars if b.get("time") is not None and b["time"] >= cutoff_sec]
            forming = self._aggregator.forming_bar()
        render_bars = list(window_bars)
        if forming:
            render_bars.append(
                {"time": forming.ts, "open": forming.open, "high": forming.high, "low": forming.low, "close": forming.close, "volume": forming.volume}
            )
        if not render_bars:
            return
        if not self._initial_render_done:
            self._chart_adapter.set_history(render_bars[-181:])
            self._initial_render_done = True
        else:
            self._chart_adapter.upsert_bar(render_bars[-1])

    def _render_tick(self) -> None:
        if not self._dirty:
            return
        self._prune_and_render()
        self._dirty = False

    def _on_stream_state(self, state: str) -> None:
        """Update UI with stream state transitions."""
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
