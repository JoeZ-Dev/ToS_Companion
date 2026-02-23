from __future__ import annotations

from typing import Any
import time
import threading
from functools import partial
import statistics
from pathlib import Path
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from PySide6 import QtCore

from momentum_companion.llm.service import LLMService
from momentum_companion.ui.main_window import MainWindow
from momentum_companion.ui.chart_adapter import ChartAdapter
from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.llm.client import LLMClient
from momentum_companion.state.app_state import AppStateStore
from momentum_companion.data.contracts import QuoteEvent
from momentum_companion.data.bar_aggregator import BarAggregator10s, TenSecondBar
from momentum_companion.data.price_update import PriceUpdate
from momentum_companion.indicators.engine import IndicatorsEngine
import pandas as pd
from momentum_companion.analysis.ae import AEEngine
from momentum_companion.utils.logging import logging


class UIController:
    """Coordinates UI state, signals/slots, and renders updates (§4.1)."""

    def __init__(
        self,
        window: MainWindow,
        llm_service: LLMService,
        rest_client: SchwabRestClient | None = None,
        stream_client: SchwabStreamClient | None = None,
        token_provider: TokenProvider | None = None,
        db_path: str | None = None,
        ae_engine: AEEngine | None = None,
        app_state: AppStateStore | None = None,
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
        self._render_timer.setInterval(50)  # 20fps target
        self._render_timer.timeout.connect(self._render_tick)  # type: ignore[arg-type]
        self._render_timer.start()
        self._dirty = False
        self._last_forming_sig: tuple[int | None, float | None, float | None, float | None, float | None, float | None] = (
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self._chart_adapter = ChartAdapter(self._window.chart_widget)
        self._initial_render_done = False
        self._indicators = IndicatorsEngine()
        self._last_quote: dict[str, Any] = {"bid": None, "ask": None, "last": None, "total_volume": None}
        self._ae_engine = ae_engine or AEEngine(rest_client, Path(db_path) if db_path else None)
        self._last_ae_snapshot: dict | None = None
        self._logger = logging.getLogger(__name__)
        self._et_tz = ZoneInfo("America/New_York")
        self._intraday_suppressed = False
        self._last_llm_ts: dict[str, float] = {}
        self._last_llm_hash: dict[str, str] = {}
        self._llm_enabled: bool = False
        self._app_state = app_state
        self._available_models: list[str] = []
        self._full_model = "gpt-4o"
        self._refresh_model = "gpt-4o-mini"
        self._hook_symbol_input()

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
        if hasattr(self._window, "llm_toggle"):
            self._window.llm_toggle.clicked.connect(self._on_llm_toggle)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_api_key_callback"):
            self._window.set_api_key_callback(self._set_api_key)  # type: ignore[attr-defined]
        if hasattr(self._window, "options_btn"):
            self._window.options_btn.clicked.connect(self._open_options)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_full_model_callback"):
            self._window.set_full_model_callback(self._set_full_model)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_refresh_model_callback"):
            self._window.set_refresh_model_callback(self._set_refresh_model)  # type: ignore[attr-defined]
        self._load_stored_api_key()
        self._load_stored_models()

    def _on_symbol_entered(self) -> None:
        raw = self._window.symbol_input.text()
        symbol = raw.strip().upper()
        self._window.symbol_input.setText(symbol)
        if not symbol:
            return
        self._pending_symbol = symbol
        self._aggregator = BarAggregator10s()
        self._bars = []
        self._initial_render_done = False
        if self._ae_engine:
            self._ae_engine.reset_intraday()
            if hasattr(self._window, "update_ae_panel"):
                self._window.update_ae_panel(None)  # type: ignore[attr-defined]
        self._last_llm_ts.pop(symbol, None)
        self._last_llm_hash.pop(symbol, None)
        self._window.symbol_input.setDisabled(True)
        self._window.connection_label.setText("Connection: REQUESTED")
        self._window.banner.setText(f"Requested symbol: {symbol}")
        self._load_history(symbol)
        if self._ae_engine:
            self._ae_engine.compute_profile(symbol)
            snap = self._ae_engine.seed_intraday_from_history(symbol)
            if snap and hasattr(self._window, "update_ae_panel"):
                self._last_ae_snapshot = snap
                self._window.update_ae_panel(snap)  # type: ignore[attr-defined]
        self._load_float(symbol)
        self._subscribe_stream(symbol)
        self._window.symbol_input.setDisabled(False)

    def _load_history(self, symbol: str) -> None:
        """Fetch minimal price history to seed chart."""
        if not self._rest_client:
            return
        try:
            self._window.banner.setText("")
            intraday_ok = self._is_intraday_window()
            end_ms = int(time.time() * 1000)
            start_ms = end_ms - (self._display_window_sec * 1000)
            bars = []
            if intraday_ok:
                bars = self._fetch_candles(symbol, start_ms, end_ms, "day")
            else:
                self._window.banner.setText("Market closed; intraday fetch skipped.")
                self._intraday_suppressed = True
            if not bars:
                bars = self._fetch_candles(symbol, None, None, "1d")
            self._bars = bars
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

    def _fetch_candles(self, symbol: str, start_ms: int | None, end_ms: int | None, freq: str) -> list[dict]:
        resp = self._rest_client.fetch_price_history(symbol, start_ms, end_ms, freq)
        candles = resp.get("candles") or []
        return [
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

    def _subscribe_stream(self, symbol: str) -> None:
        if not self._is_intraday_window():
            self._window.connection_label.setText("Connection: STREAM DEFERRED (market closed)")
            self._window.banner.setText("Stream deferred until market window opens.")
            return
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

    def _load_float(self, symbol: str) -> None:
        """Fetch sharesOutstanding from fundamentals and update the UI."""
        if not self._rest_client or not hasattr(self._window, "update_float"):
            return
        try:
            data = self._rest_client.fetch_quote_fundamental(symbol)
            shares = self._parse_shares_outstanding(data, symbol)
            self._window.update_float(shares)  # type: ignore[attr-defined]
            self._logger.debug("Loaded float for %s: %s", symbol, shares)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to load float for %s: %s", symbol, exc)
            self._window.update_float(None)  # type: ignore[attr-defined]

    def _handle_quote(self, event: QuoteEvent) -> None:
        bid = event.get("bid")
        ask = event.get("ask")
        last = event.get("last")
        ts_ms = event.get("ts_ms")
        try:
            self._logger.debug(
                "Quote received: ts=%s bid=%s ask=%s last=%s vol=%s",
                ts_ms,
                bid,
                ask,
                last,
                event.get("volume"),
            )
            if ts_ms and last is not None:
                if self._ae_engine:
                    self._ae_engine.record_quote_ts(ts_ms)
                pu = PriceUpdate(timestamp=int(ts_ms // 1000), price=last, size=event.get("volume"), source="L1")
                with self._bars_lock:
                    completed = self._aggregator.ingest_price(pu)
                    if completed:
                        self._append_bar_locked(completed)
                        self._request_render()
                        if self._ae_engine:
                            snap = self._ae_engine.ingest_10s_bar(completed)
                            if snap:
                                self._last_ae_snapshot = snap
                                if hasattr(self._window, "update_ae_panel"):
                                    self._window.update_ae_panel(snap)  # type: ignore[attr-defined]
                                self._maybe_invoke_llm(snap, event)
                    forming = self._aggregator.forming_bar()
                    sig = (
                        forming.ts if forming else None,
                        forming.open if forming else None,
                        forming.high if forming else None,
                        forming.low if forming else None,
                        forming.close if forming else None,
                        forming.volume if forming else None,
                    )
                    if sig != self._last_forming_sig:
                        self._last_forming_sig = sig
                        self._request_render()
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
        # UI label updates on main thread via queued invoke
        QtCore.QMetaObject.invokeMethod(
            self._window,
            "render_quote",
            QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(float, float(ts_ms) if ts_ms is not None else 0.0),
            QtCore.Q_ARG(float, float(bid) if bid is not None else 0.0),
            QtCore.Q_ARG(float, float(ask) if ask is not None else 0.0),
            QtCore.Q_ARG(float, float(last) if last is not None else 0.0),
        )

    def _maybe_invoke_llm(self, snapshot: dict, quote_event: QuoteEvent) -> None:
        """Gate and invoke LLM coach off the UI thread."""
        symbol = snapshot.get("symbol")
        if not symbol or not self._llm_service:
            return
        if not self._llm_enabled:
            return
        # Data quality gates
        if snapshot.get("data_quality") != "ok":
            return
        if not snapshot.get("has_intraday_data") or not snapshot.get("has_4h_data") or not snapshot.get("has_market_data"):
            return
        # Time gate
        now_sec = time.time()
        last_ts = self._last_llm_ts.get(symbol, 0)
        interval = 60 if symbol not in self._last_llm_ts else 30
        if now_sec - last_ts < interval:
            return
        # Change gate
        snap_hash = self._snapshot_hash(snapshot)
        if self._last_llm_hash.get(symbol) == snap_hash:
            return
        self._last_llm_ts[symbol] = now_sec
        self._last_llm_hash[symbol] = snap_hash
        self._refresh_llm_status(symbol)
        QtCore.QTimer.singleShot(0, lambda: self._run_llm(snapshot, quote_event))

    def _run_llm(self, snapshot: dict, quote_event: QuoteEvent) -> None:
        try:
            session_mode = "RTH" if self._is_intraday_window() else "PRE"
            model = self._full_model if snapshot.get("symbol") not in self._last_llm_ts else self._refresh_model
            rec = self._llm_service.evaluate(snapshot, session_mode, quote_event, model_override=model)  # type: ignore[attr-defined]
            if hasattr(self._window, "apply_llm_recommendation"):
                QtCore.QMetaObject.invokeMethod(
                    self._window,
                    "apply_llm_recommendation",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(dict, rec),  # type: ignore[arg-type]
                )
        except Exception:
            self._logger.exception("LLM evaluate failed")
        finally:
            self._refresh_llm_status(snapshot.get("symbol"))

    @staticmethod
    def _snapshot_hash(snapshot: dict) -> str:
        """Hash key fields to detect meaningful changes."""
        import hashlib
        import json

        keys = ["regime", "levels", "micro", "last_price", "vwap", "data_quality"]
        data = {k: snapshot.get(k) for k in keys}
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def _update_labels_ui(self, ts_ms: int | None, bid: float | None, ask: float | None, last: float | None) -> None:
        self._logger.debug("UI label update: ts=%s bid=%s ask=%s last=%s", ts_ms, bid, ask, last)
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
            if "macd" in studies:
                self._chart_adapter.set_series("MACD", series_to_points(studies["macd"], times))
            if "macd_signal" in studies:
                self._chart_adapter.set_series("MACD_SIGNAL", series_to_points(studies["macd_signal"], times))
            if "macd_hist" in studies:
                self._chart_adapter.set_series("MACD_HIST", series_to_points(studies["macd_hist"], times))
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
        if self._last_ae_snapshot and hasattr(self._window, "update_ae_panel"):
            self._window.update_ae_panel(self._last_ae_snapshot)  # type: ignore[attr-defined]

    def _render_tick(self) -> None:
        if not self._dirty:
            return
        self._prune_and_render()
        self._dirty = False

    def _request_render(self) -> None:
        """Mark dirty and schedule a render on the Qt event loop ASAP."""
        self._dirty = True
        QtCore.QTimer.singleShot(0, self._render_tick)

    def _is_intraday_window(self) -> bool:
        """Returns True if within 04:00–20:00 ET on a trading day (Mon–Fri)."""
        now_et = datetime.now(self._et_tz)
        if now_et.weekday() >= 5:  # Saturday/Sunday
            return False
        tod = now_et.time()
        if tod < dtime(hour=4) or tod > dtime(hour=20):
            return False
        return True

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

    def _on_llm_toggle(self, checked: bool) -> None:
        self._llm_enabled = checked
        if hasattr(self._window, "llm_status"):
            self._window.llm_status.setText("LLM: ON" if checked else "LLM: OFF")
        if hasattr(self._window, "llm_toggle"):
            self._window.llm_toggle.setText("Disable LLM" if checked else "Enable LLM")
        self._refresh_llm_status()

    def _open_options(self) -> None:
        if hasattr(self._window, "show_options_dialog"):
            self._window.show_options_dialog()

    def _refresh_llm_status(self, symbol: str | None = None) -> None:
        """Update LLM status line in UI."""
        if not hasattr(self._window, "llm_status_line"):
            return
        sym = symbol or self._pending_symbol or ""
        state = "ON" if self._llm_enabled else "OFF"
        key_state = "set" if getattr(self._llm_service, "_client", None) else "unset"
        last_ts = self._last_llm_ts.get(sym)
        last_txt = time.strftime("%H:%M:%S", time.localtime(last_ts)) if last_ts else "--"
        next_txt = "--"
        if last_ts:
            next_ts = last_ts + 30
            delta = max(0, int(next_ts - time.time()))
            next_txt = f"in {delta}s"
        self._window.llm_status_line.setText(f"LLM Status: {state} | Key: {key_state} | Last: {last_txt} | Next: {next_txt}")

    def _set_api_key(self, key: str) -> None:
        key = key.strip()
        if key:
            try:
                self._llm_service._client = LLMClient(api_key=key, model="gpt-5.1-codex-max")  # type: ignore[attr-defined]
                if self._app_state:
                    self._app_state.set_secret("openai_api_key", key)
                self._load_models_async()
            except Exception:
                self._logger.exception("Failed to set LLM API key")
        else:
            self._llm_service._client = None  # type: ignore[attr-defined]
            if self._app_state:
                self._app_state.set("openai_api_key", "")
        self._refresh_llm_status()

    def _set_full_model(self, model: str) -> None:
        model = model.strip()
        if model:
            self._full_model = model
            if self._app_state:
                self._app_state.set("llm_full_model", model)
        self._refresh_llm_status()

    def _set_refresh_model(self, model: str) -> None:
        model = model.strip()
        if model:
            self._refresh_model = model
            if self._app_state:
                self._app_state.set("llm_refresh_model", model)
        self._refresh_llm_status()

    def _load_stored_api_key(self) -> None:
        if not self._app_state:
            return
        stored = self._app_state.get_secret("openai_api_key")
        if stored:
            try:
                self._llm_service._client = LLMClient(api_key=stored, model="gpt-5.1-codex-max")  # type: ignore[attr-defined]
            except Exception:
                self._logger.exception("Failed to load stored LLM API key")
        if self._llm_service and getattr(self._llm_service, "_client", None):
            self._load_models_async()
        self._refresh_llm_status()

    def _load_models_async(self) -> None:
        if not self._llm_service or not getattr(self._llm_service, "_client", None):
            return
        def task() -> None:
            try:
                models = self._llm_service._client.list_models()  # type: ignore[attr-defined]
                self._available_models = models
                if hasattr(self._window, "populate_models"):
                    QtCore.QTimer.singleShot(0, lambda m=models: self._window.populate_models(m))  # type: ignore[attr-defined]
                QtCore.QTimer.singleShot(
                    0, lambda: getattr(self._window, "set_model_values", lambda *_: None)(self._full_model, self._refresh_model)
                )
            except Exception:
                self._logger.warning("Failed to list models from OpenAI", exc_info=True)
        threading.Thread(target=task, daemon=True).start()

    def _load_stored_models(self) -> None:
        if not self._app_state:
            return
        full = self._app_state.get("llm_full_model") or self._full_model
        refresh = self._app_state.get("llm_refresh_model") or self._refresh_model
        self._full_model = full
        self._refresh_model = refresh
        if hasattr(self._window, "_full_model_box") and self._window._full_model_box:
            self._window._full_model_box.setEditText(self._full_model)
        if hasattr(self._window, "_refresh_model_box") and self._window._refresh_model_box:
            self._window._refresh_model_box.setEditText(self._refresh_model)
        if hasattr(self._window, "set_model_values"):
            self._window.set_model_values(self._full_model, self._refresh_model)

    @staticmethod
    def _parse_shares_outstanding(payload: Any, symbol: str) -> float | None:
        """Extract sharesOutstanding from Schwab quote/fundamental response."""
        if not isinstance(payload, dict):
            return None
        sym = symbol.upper()
        candidates: list[dict] = []
        # Preferred: direct symbol key
        direct = payload.get(sym)
        if isinstance(direct, dict):
            candidates.append(direct)
        # Common wrapper: quotes map
        quotes_block = payload.get("quotes")
        if isinstance(quotes_block, dict):
            if sym in quotes_block and isinstance(quotes_block[sym], dict):
                candidates.append(quotes_block[sym])
            else:
                candidates.extend([v for v in quotes_block.values() if isinstance(v, dict)])
        # Fallback: any dict children
        if not candidates:
            candidates.extend([v for v in payload.values() if isinstance(v, dict)])
        for candidate in candidates:
            fundamental = candidate.get("fundamental") if isinstance(candidate, dict) else None
            if isinstance(fundamental, dict) and "sharesOutstanding" in fundamental:
                try:
                    return float(fundamental.get("sharesOutstanding"))
                except (TypeError, ValueError):
                    return None
        return None
