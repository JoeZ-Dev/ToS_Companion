from __future__ import annotations

from typing import Any
import time
import threading
from functools import partial
import statistics
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
from momentum_companion.indicators.engine import IndicatorsEngine
import pandas as pd


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
        self._indicators = IndicatorsEngine()
        self._last_quote: dict[str, Any] = {"bid": None, "ask": None, "last": None, "total_volume": None}

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
                {
                    "time": int(c.get("datetime") // 1000),
                    "open": c.get("open"),
                    "high": c.get("high"),
                    "low": c.get("low"),
                    "close": c.get("close"),
                    "volume": c.get("volume") or 0,
                }
                for c in candles
                if c.get("datetime") is not None
            ]
            if self._bars:
                self._chart_adapter.set_history(self._bars)
                self._update_studies(self._bars)
                self._update_header(self._bars, None)
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
            # track latest quote for header
            self._last_quote = {
                "bid": bid,
                "ask": ask,
                "last": last,
                "total_volume": event.get("volume"),
            }
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

    def _update_studies(self, bars: list[dict]) -> None:
        """Compute VWAP/EMA studies and push to chart adapter."""
        if not bars:
            return
        try:
            df = pd.DataFrame(bars)
            if df.empty or "close" not in df:
                return
            if "volume" not in df:
                df["volume"] = 0
            df["ts_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
            anchor = df["ts_utc"].iloc[-1].normalize() + pd.Timedelta(hours=4)
            studies = self._indicators.compute_studies(df, anchor)

            def series_to_points(series: pd.Series, times: pd.Series) -> list[dict]:
                if series is None:
                    return []
                series = series.dropna()
                if series.empty:
                    return []
                pts: list[dict] = []
                for idx, val in series.items():
                    # Prefer datetime-like index; fall back to times alignment
                    if hasattr(idx, "timestamp"):
                        t = int(pd.Timestamp(idx).timestamp())
                    else:
                        if idx in times.index:
                            t = int(times.loc[idx])
                        else:
                            # best-effort fallback by position
                            t = int(times.iloc[len(pts)])
                    pts.append({"time": t, "value": float(val)})
                return pts

            times = df["time"]
            if "vwap" in studies:
                self._chart_adapter.set_series("VWAP", series_to_points(studies["vwap"], times))
            if "ema9" in studies:
                self._chart_adapter.set_series("EMA9", series_to_points(studies["ema9"], times))
            if "ema20" in studies:
                self._chart_adapter.set_series("EMA20", series_to_points(studies["ema20"], times))
        except Exception:  # noqa: BLE001
            from momentum_companion.utils.logging import logging

            logging.getLogger(__name__).exception("Failed to compute studies")

    def _update_header(self, bars: list[dict], forming: dict | None) -> None:
        """Compute header snapshot (last/bid/ask/dayVol/barVol/vel) and push to chart."""
        if not bars and not forming:
            return
        last_bar = forming or (bars[-1] if bars else None)
        if not last_bar:
            return
        bar_vol = last_bar.get("volume") or 0
        now_sec = int(time.time())
        elapsed = 10
        if forming and forming.get("time") is not None:
            elapsed = max(1, now_sec - int(forming["time"]))
        current_rate = bar_vol / max(elapsed, 1)
        completed_rates = [b.get("volume", 0) / 10 for b in bars[-30:] if b.get("volume") is not None]
        baseline = statistics.median(completed_rates) if completed_rates else 0
        vel = current_rate / baseline if baseline else None
        hdr = {
            "last": self._last_quote.get("last") if self._last_quote.get("last") is not None else last_bar.get("close"),
            "bid": self._last_quote.get("bid"),
            "ask": self._last_quote.get("ask"),
            "dayVol": self._last_quote.get("total_volume"),
            "barVol": bar_vol,
            "vel": vel,
        }
        try:
            self._chart_adapter.set_header(hdr)
        except Exception:  # noqa: BLE001
            from momentum_companion.utils.logging import logging

            logging.getLogger(__name__).exception("Failed to set header")

    def _prune_and_render(self) -> None:
        with self._bars_lock:
            window_bars = list(self._bars)
            forming = self._aggregator.forming_bar()
        render_bars = list(window_bars)
        if forming:
            forming_dict = {
                "time": forming.ts,
                "open": forming.open,
                "high": forming.high,
                "low": forming.low,
                "close": forming.close,
                "volume": forming.volume,
            }
            render_bars.append(forming_dict)
        if not render_bars:
            return
        # Studies computed on all stored bars
        self._update_studies(self._bars)
        forming_bar = locals().get("forming_dict", None)
        self._update_header(window_bars, forming_bar)
        if not self._initial_render_done:
            self._chart_adapter.set_history(render_bars)
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
