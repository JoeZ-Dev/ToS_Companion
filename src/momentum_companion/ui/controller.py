from __future__ import annotations

from typing import Any
import time
import json
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
from momentum_companion.clients.massive_fundamentals_client import MassiveFundamentalsClient
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


class _ModelSignals(QtCore.QObject):
    models_ready = QtCore.Signal(object, str, str)


class _LLMSignals(QtCore.QObject):
    llm_result_ready = QtCore.Signal(object)


class UIController:
    """Coordinates UI state, signals/slots, and renders updates (§4.1)."""

    _ALLOWED_SESSION_MODES = {"NORMAL", "SEAMLESS"}
    _ALLOWED_MARKET_STATES = {"premarket", "normal", "afterhours"}
    _BARS_WINDOW_MAX = 60
    _BARS_WINDOW_MIN_READY = 20
    _ENTRY_TO_TRIGGER_MAX_PCT = 0.02
    _ENTRY_TRIGGER_PROX_PCT = 0.015
    _MAX_STOP_PCT = 0.10
    _MAX_TARGET_PCT = 0.20
    _SWING_LOW_LOOKBACK_BARS = 12
    _SWING_HIGH_LOOKBACK_BARS = 24

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
        # Enable verbose debug logs to investigate stability issues (e.g., render/LLM flow).
        self._logger.setLevel(logging.DEBUG)
        self._et_tz = ZoneInfo("America/New_York")
        self._intraday_suppressed = False
        self._last_llm_ts: dict[str, float] = {}
        self._last_llm_hash: dict[str, str] = {}
        self._llm_enabled: bool = False
        self._app_state = app_state
        self._available_models: list[str] = []
        self._full_model = "gpt-4o"
        self._refresh_model = "gpt-4o-mini"
        self._llm_prompt_version = "LLM_COACH_PROMPT_V1"
        self._llm_prompt = self._default_developer_prompt()
        self._llm_prompt_refresh = self._default_developer_prompt_refresh()
        self._disable_rr_gate: bool = False
        self._massive_api_key: str | None = None
        self._massive_client: MassiveFundamentalsClient | None = None
        self._massive_cache_dir = Path(db_path).parent if db_path else Path.home() / ".tos_companion"
        self._model_signals = _ModelSignals()
        self._llm_signals = _LLMSignals()
        self._last_llm_payload: dict | None = None
        self._last_llm_rec_by_symbol: dict[str, dict] = {}
        self._bars_1m: list[dict] = []
        if hasattr(self._window, "populate_models"):
            # Single signal carries models + selections to enforce ordering
            self._model_signals.models_ready.connect(  # type: ignore[attr-defined]
                lambda models, full, refresh: (
                    self._window.populate_models(models),  # type: ignore[attr-defined]
                    getattr(self._window, "set_model_values", lambda *_: None)(full, refresh),
                )
            )
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
        if hasattr(self._window, "set_massive_key_callback"):
            self._window.set_massive_key_callback(self._set_massive_api_key)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_massive_test_callback"):
            self._window.set_massive_test_callback(self._test_massive_api_key)  # type: ignore[attr-defined]
        if hasattr(self._window, "options_btn"):
            self._window.options_btn.clicked.connect(self._open_options)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_full_model_callback"):
            self._window.set_full_model_callback(self._set_full_model)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_refresh_model_callback"):
            self._window.set_refresh_model_callback(self._set_refresh_model)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_prompt_callback"):
            self._window.set_prompt_callback(self._set_prompt)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_prompt_reset_callback"):
            self._window.set_prompt_reset_callback(self._reset_prompt)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_rr_gate_callback"):
            self._window.set_rr_gate_callback(self._set_rr_gate_disabled)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_tz_callback"):
            self._window.set_tz_callback(self._on_display_tz_changed)  # type: ignore[attr-defined]
        if hasattr(self._window, "_on_llm_result_ready"):
            try:
                self._llm_signals.llm_result_ready.connect(self._window._on_llm_result_ready)  # type: ignore[attr-defined]
            except Exception:
                self._logger.warning("Failed to connect LLM result signal to window", exc_info=True)
        if hasattr(self._window, "set_llm_full_callback"):
            self._window.set_llm_full_callback(self._run_llm_full)  # type: ignore[attr-defined]
        if hasattr(self._window, "set_llm_refresh_callback"):
            self._window.set_llm_refresh_callback(self._run_llm_refresh)  # type: ignore[attr-defined]
        self._load_stored_api_key()
        self._load_stored_massive_key()
        self._load_stored_models()
        self._load_stored_prompt()
        self._load_stored_rr_gate()
        self._on_display_tz_changed("America/New_York")

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
        self._load_bars_1m(symbol)
        if self._ae_engine:
            self._ae_engine.compute_profile(symbol)
            snap = self._ae_engine.seed_intraday_from_history(symbol)
            if snap and hasattr(self._window, "update_ae_panel"):
                self._last_ae_snapshot = snap
                self._window.update_ae_panel(snap)  # type: ignore[attr-defined]
        self._load_float(symbol)
        self._fetch_massive_fundamentals(symbol)
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

    def _load_bars_1m(self, symbol: str) -> None:
        """Fetch last ~90 minutes of 1m bars for LLM microstructure."""
        self._bars_1m = []
        if not self._rest_client:
            return
        try:
            end_ms = int(time.time() * 1000)
            start_ms = end_ms - 90 * 60 * 1000
            resp = self._rest_client.fetch_price_history(symbol, start_ms, end_ms, "1m")
            candles = resp.get("candles") or []
            bars: list[dict] = []
            for c in candles:
                if c.get("datetime") is None:
                    continue
                try:
                    bars.append(
                        {
                            "ts_ms": int(c.get("datetime")),
                            "o": float(c.get("open")),
                            "h": float(c.get("high")),
                            "l": float(c.get("low")),
                            "c": float(c.get("close")),
                            "v": float(c.get("volume") or 0),
                        }
                    )
                except Exception:
                    continue
            bars = sorted(bars, key=lambda b: b.get("ts_ms") or 0)
            if len(bars) > 60:
                bars = bars[-60:]
            self._bars_1m = bars
            self._logger.debug("Loaded 1m bars for %s count=%s", symbol, len(bars))
        except Exception:
            self._logger.debug("Failed to load 1m bars for %s", symbol, exc_info=True)

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
            # Ensure we pass the streaming token explicitly if provided.
            if "token" not in streamer_info and "streamerInfo" in streamer_info:
                streamer_info["token"] = streamer_info["streamerInfo"].get("token")  # type: ignore[index]
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

    def _set_massive_field(self, kind: str, status: str, value: float | int | None, as_of: str | None) -> None:
        if hasattr(self._window, "update_massive_fundamental"):
            QtCore.QTimer.singleShot(
                0, lambda k=kind, s=status, v=value, d=as_of: self._window.update_massive_fundamental(k, s, v, d)
            )

    def _fetch_massive_fundamentals(self, symbol: str) -> None:
        kinds = ("float", "short_interest", "short_vol_pct")
        if not hasattr(self._window, "update_massive_fundamental"):
            return
        if not self._massive_api_key:
            for k in kinds:
                self._set_massive_field(k, "MISSING_API_KEY", None, None)
            return
        for k in kinds:
            self._set_massive_field(k, "PENDING", None, None)
        if not self._massive_client and self._massive_api_key:
            self._massive_client = MassiveFundamentalsClient(self._massive_api_key, self._massive_cache_dir, self._logger)

        def task() -> None:
            client = self._massive_client
            if not client:
                for k in kinds:
                    self._set_massive_field(k, "FAILURE", None, None)
                return
            today = datetime.now(self._et_tz).strftime("%Y-%m-%d")
            res_float = client.fetch_float(symbol)
            self._set_massive_field("float", res_float.get("status", "FAILURE"), res_float.get("value"), res_float.get("as_of"))
            res_si = client.fetch_short_interest(symbol)
            self._set_massive_field(
                "short_interest", res_si.get("status", "FAILURE"), res_si.get("value"), res_si.get("as_of")
            )
            res_sv = client.fetch_short_volume_pct(symbol, today)
            self._set_massive_field(
                "short_vol_pct", res_sv.get("status", "FAILURE"), res_sv.get("value"), res_sv.get("as_of")
            )

        threading.Thread(target=task, daemon=True).start()

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
                                    QtCore.QTimer.singleShot(
                                        0, lambda s=snap: self._window.update_ae_panel(s)  # type: ignore[attr-defined]
                                    )
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
        ready, missing = self._is_snapshot_ready_for_llm(snapshot)
        if not ready:
            self._logger.debug("LLM auto skipped — snapshot not ready (missing %s)", ", ".join(missing))
            return
        # Time gate
        now_sec = time.time()
        is_first = symbol not in self._last_llm_ts
        last_ts = self._last_llm_ts.get(symbol, 0)
        interval = 60 if is_first else 30
        if now_sec - last_ts < interval:
            return
        # Change gate
        snap_hash = self._snapshot_hash(snapshot)
        if self._last_llm_hash.get(symbol) == snap_hash:
            return
        self._last_llm_hash[symbol] = snap_hash
        self._refresh_llm_status(symbol)
        normalized = self._normalize_snapshot_for_llm(snapshot)
        QtCore.QTimer.singleShot(0, lambda n=normalized: self._run_llm_from_snapshot(n, quote_event, is_first))

    def _run_llm_from_snapshot(self, snapshot: dict, quote_event: QuoteEvent, is_first: bool) -> None:
        try:
            session_mode = "RTH" if self._is_intraday_window() else "PRE"
            model = self._full_model if is_first else self._refresh_model
            self._last_llm_ts[snapshot.get("symbol") or ""] = time.time()
            self._logger.info(
                "LLM auto invoke model=%s symbol=%s is_first=%s prompt_version=%s",
                model,
                snapshot.get("symbol"),
                is_first,
                self._llm_prompt_version,
            )
            messages = self._build_llm_messages(snapshot)
            rec = self._llm_service.evaluate(
                snapshot,
                session_mode,
                quote_event,
                model_override=model,
                messages_override=messages,
            )  # type: ignore[attr-defined]
            # no structural enforcement in strategist mode
            if not self._validate_setup_schema(rec):
                self._logger.warning("Invalid LLM setup schema")
            self._emit_llm_result(
                snapshot,
                model,
                invocation="AUTO",
                parsed=rec,
                raw_text=json.dumps(rec),
                error=None,
            )
        except Exception:
            self._logger.exception("LLM evaluate failed")
        finally:
            self._refresh_llm_status(snapshot.get("symbol"))

    def _snapshot_hash(self, snapshot: dict) -> str:
        """Hash key fields to detect meaningful changes using normalized payload subset."""
        import hashlib

        normalized = self._normalize_snapshot_for_llm(snapshot)
        quote = normalized.get("quote") or {}
        levels = normalized.get("levels") or {}
        micro = normalized.get("micro") or {}
        bars = normalized.get("bars_5m") or []
        closes: list[float] = []
        if isinstance(bars, list):
            for b in bars[-10:]:
                if isinstance(b, dict) and b.get("c") is not None:
                    try:
                        closes.append(float(b.get("c")))
                    except Exception:
                        continue
        data = {
            "data_quality": normalized.get("data_quality"),
            "quote_last": quote.get("last"),
            "quote_bid": quote.get("bid"),
            "quote_ask": quote.get("ask"),
            "vwap": normalized.get("vwap"),
            "micro_state": micro.get("micro_state"),
            "micro_resistance_15m": micro.get("micro_resistance_15m"),
            "micro_support_15m": micro.get("micro_support_15m"),
            "nearest_res_price": (levels.get("nearest_resistance") or {}).get("price") if isinstance(levels, dict) else None,
            "nearest_res_source": (levels.get("nearest_resistance") or {}).get("source") if isinstance(levels, dict) else None,
            "nearest_sup_price": (levels.get("nearest_support") or {}).get("price") if isinstance(levels, dict) else None,
            "nearest_sup_source": (levels.get("nearest_support") or {}).get("source") if isinstance(levels, dict) else None,
            "bars_closes": closes,
        }
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
        bar_dict = {
            "time": bar.ts,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
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
        """Update UI with stream state transitions (marshal to UI thread)."""
        QtCore.QTimer.singleShot(0, lambda s=state: self._update_stream_state_ui(s))

    def _update_stream_state_ui(self, state: str) -> None:
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
        if hasattr(self._window, "llm_toggle"):
            self._window.llm_toggle.setText("LLM ON" if checked else "LLM OFF")
            if checked:
                self._window.llm_toggle.setStyleSheet(
                    "background-color: #1f7a3d; color: #ecf0f1; border: 1px solid #1b5e2b;"
                )
            else:
                self._window.llm_toggle.setStyleSheet(
                    "background-color: #6b1b1b; color: #f5eaea; border: 1px solid #7a2a2a;"
                )
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
        self._window.llm_status_line.setText(f"LLM Status: {state} | Key: {key_state} | Last: {last_txt}")

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

    def _set_massive_api_key(self, key: str) -> None:
        key = key.strip()
        self._massive_api_key = key or None
        if self._app_state is not None:
            if key:
                self._app_state.set_secret("massive_api_key", key)
            else:
                self._app_state.set("massive_api_key", "")
        if key:
            self._massive_client = MassiveFundamentalsClient(key, self._massive_cache_dir, self._logger)
        else:
            self._massive_client = None

    def _test_massive_api_key(self) -> str:
        if not self._massive_api_key:
            return "MISSING_API_KEY"
        client = self._massive_client or MassiveFundamentalsClient(self._massive_api_key, self._massive_cache_dir, self._logger)
        status = client.test_key()
        if hasattr(self._window, "set_massive_test_status"):
            self._window.set_massive_test_status(status.lower())
        return status

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

    def _set_prompt(self, prompt: str) -> None:
        prompt = prompt.strip()
        if prompt:
            self._llm_prompt = prompt
            if self._app_state:
                self._app_state.set("llm_prompt", prompt)
        self._refresh_llm_status()

    def _reset_prompt(self) -> None:
        self._llm_prompt = self._default_developer_prompt()
        if self._app_state:
            self._app_state.set("llm_prompt", self._llm_prompt)
        if hasattr(self._window, "set_prompt_value"):
            self._window.set_prompt_value(self._llm_prompt)
        self._refresh_llm_status()

    def _set_rr_gate_disabled(self, disabled: bool) -> None:
        self._disable_rr_gate = bool(disabled)
        if self._app_state:
            self._app_state.set("llm_disable_rr_gate", self._disable_rr_gate)
        if hasattr(self._window, "set_rr_gate_state"):
            self._window.set_rr_gate_state(self._disable_rr_gate)

    def _run_llm_full(self) -> None:
        self._run_llm_manual(self._full_model, refresh_mode=False)

    def _run_llm_refresh(self) -> None:
        self._run_llm_manual(self._refresh_model, refresh_mode=True)

    def _run_llm_manual(self, model: str, refresh_mode: bool = False) -> None:
        """Invoke LLM with current snapshot using selected model."""
        if not self._llm_enabled:
            return
        if not self._last_ae_snapshot:
            self._logger.warning("LLM run skipped: no snapshot")
            return
        ready, missing = self._is_snapshot_ready_for_llm(self._last_ae_snapshot)
        if not ready:
            msg = f"LLM skipped — snapshot not ready (missing {', '.join(missing)}; bars_len={len(self._last_ae_snapshot.get('bars_window') or []) if isinstance(self._last_ae_snapshot, dict) else 0})"
            self._logger.warning(msg)
            QtCore.QTimer.singleShot(
                0,
                lambda m=msg: getattr(self._window, "set_llm_recommendation", lambda *_: None)(m),
            )  # type: ignore[arg-type]
            return
        client = getattr(self._llm_service, "_client", None)
        if not client:
            self._logger.warning("LLM run skipped: no client")
            return
        symbol = self._pending_symbol or ""
        snap_keys = list(self._last_ae_snapshot.keys()) if isinstance(self._last_ae_snapshot, dict) else []
        barish_keys = [k for k in snap_keys if "bar" in k.lower() or "ohlc" in k.lower() or "candle" in k.lower() or "5m" in k.lower()]
        self._logger.debug("LLM source snapshot keys: %s | bar-related: %s", snap_keys, barish_keys)
        normalized = self._normalize_snapshot_for_llm(self._last_ae_snapshot)
        bars = normalized.get("bars_5m") if isinstance(normalized, dict) else None
        bars_len = len(bars) if isinstance(bars, list) else 0
        bars_1m = normalized.get("bars_1m") if isinstance(normalized, dict) else None
        bars_1m_len = len(bars_1m) if isinstance(bars_1m, list) else 0
        levels_info = normalized.get("levels") or {}
        self._logger.info(
            "LLM normalized snapshot keys=%s bars_5m_len=%s bars_1m_len=%s levels_fields=%s bars_ts=%s..%s",
            list(normalized.keys()),
            bars_len,
            bars_1m_len,
            list(levels_info.keys()) if isinstance(levels_info, dict) else None,
            bars[0]["ts_ms"] if bars_len else None,
            bars[-1]["ts_ms"] if bars_len else None,
        )
        prior_best_payload: dict | None = None
        if refresh_mode:
            compact_payload = self._build_refresh_payload(normalized)
            prior_best_payload = compact_payload.get("prior_best_setup") if isinstance(compact_payload, dict) else None
            messages = self._build_llm_refresh_messages(compact_payload)
        else:
            messages = self._build_llm_messages(normalized)

        def task() -> None:
            try:
                self._logger.info(
                    "LLM invoking model=%s for symbol=%s prompt_version=%s invocation=%s bars_len=%s",
                    model,
                    symbol,
                    self._llm_prompt_version,
                    "REFRESH" if refresh_mode else "MANUAL",
                    bars_len,
                )
                try:
                    if refresh_mode:
                        self._logger.info(
                            "LLM refresh payload sizes: system=%s dev=%s user=%s | previews: sys=%s ... dev=%s ... user=%s ...",
                            len(messages[0].get("content", "")),
                            len(messages[1].get("content", "")),
                            len(messages[2].get("content", "")),
                            messages[0].get("content", "")[:200],
                            messages[1].get("content", "")[:200],
                            messages[2].get("content", "")[:200],
                        )
                    else:
                        self._logger.info(
                            "LLM payload sizes: system=%s dev=%s user=%s | previews: sys=%s ... dev=%s ... user=%s ...",
                            len(messages[0].get("content", "")),
                            len(messages[1].get("content", "")),
                            len(messages[2].get("content", "")),
                            messages[0].get("content", "")[:200],
                            messages[1].get("content", "")[:200],
                            messages[2].get("content", "")[:200],
                        )
                        self._logger.info("LLM payload messages: %s", json.dumps(messages, indent=2))
                except Exception:
                    self._logger.info("LLM payload messages (unformatted): %s", messages)
                resp = client.complete(messages=messages, model_override=model)
                content = ""
                # Log full raw response for debugging/inspection
                try:
                    self._logger.info("LLM raw response: %s", json.dumps(resp, indent=2))
                except Exception:
                    self._logger.info("LLM raw response (unformatted): %s", resp)
                try:
                    choices = resp.get("choices") if isinstance(resp, dict) else None
                    if choices and isinstance(choices, list):
                        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                        if msg and msg.get("content"):
                            content = msg.get("content")
                except Exception:
                    content = ""
                if not content:
                    content = json.dumps(resp)
                parse_error = None
                try:
                    rec = json.loads(content)
                except Exception:
                    parse_error = "LLM response not JSON"
                    rec = {"validity": "NOT_VALID_FOR_TRADING", "reason_codes": ["DATA_STALE"], "summary": content}
                # no structural enforcement in strategist mode
                if refresh_mode:
                    prior_full_rec = self._last_llm_rec_by_symbol.get(symbol)
                    rec = self._patch_refresh_output(rec, prior_best_payload, prior_full_rec, refresh_mode=True)
                if not self._validate_setup_schema(rec):
                    self._logger.warning("Invalid LLM setup schema")
                self._emit_llm_result(
                    normalized,
                    model,
                    invocation="MANUAL",
                    parsed=rec,
                    raw_text=content,
                    error=parse_error,
                )
                self._last_llm_ts[self._pending_symbol or ""] = time.time()
                QtCore.QTimer.singleShot(0, lambda: self._refresh_llm_status())
            except Exception as e:
                # Surface response details when available (e.g., HTTP errors)
                try:
                    if isinstance(e, Exception) and hasattr(e, "response"):
                        resp_obj = getattr(e, "response", None)
                        if resp_obj is not None:
                            self._logger.warning("LLM invocation HTTP error: %s", getattr(resp_obj, "text", resp_obj))
                except Exception:
                    pass
                self._logger.warning("LLM invocation failed", exc_info=True)
                QtCore.QTimer.singleShot(
                    0,
                    lambda msg=str(e): getattr(self._window, "set_llm_recommendation", lambda *_: None)(
                        f"LLM error: {msg}"
                    ),
                )  # type: ignore[arg-type]
        threading.Thread(target=task, daemon=True).start()

    def _load_stored_api_key(self) -> None:
        if not self._app_state:
            return
        stored = self._app_state.get_secret("openai_api_key")
        if stored:
            try:
                self._llm_service._client = LLMClient(api_key=stored, model="gpt-5.1-codex-max")  # type: ignore[attr-defined]
            except Exception:
                self._logger.exception("Failed to load stored LLM API key")
            if hasattr(self._window, "set_api_key_value"):
                self._window.set_api_key_value(stored)
        if self._llm_service and getattr(self._llm_service, "_client", None):
            self._load_models_async()
        self._refresh_llm_status()
        self._load_stored_rr_gate()

    def _load_stored_massive_key(self) -> None:
        if not self._app_state:
            return
        stored = self._app_state.get_secret("massive_api_key")
        if stored:
            self._massive_api_key = stored
            self._massive_client = MassiveFundamentalsClient(stored, self._massive_cache_dir, self._logger)
            if hasattr(self._window, "set_massive_key_value"):
                self._window.set_massive_key_value(stored)

    def _load_models_async(self) -> None:
        if not self._llm_service or not getattr(self._llm_service, "_client", None):
            return
        def task() -> None:
            try:
                model_records = self._llm_service._client.list_models()  # type: ignore[attr-defined]
                fetched = len(model_records)
                ids: list[str] = []
                for rec in model_records:
                    mid = rec.get("id") if isinstance(rec, dict) else None
                    caps = rec.get("capabilities") if isinstance(rec, dict) else {}
                    is_chat = False
                    if isinstance(caps, dict):
                        is_chat = bool(caps.get("chat"))
                    rec_type = rec.get("type") if isinstance(rec, dict) else None
                    if not is_chat and rec_type and isinstance(rec_type, str):
                        is_chat = rec_type == "chat.completions"
                    if mid and is_chat:
                        ids.append(mid)
                defaults = ["gpt-4o", "gpt-4o-mini"]
                merged = sorted(set(ids + defaults)) if ids else defaults
                allowed_prefixes = ["gpt-5", "gpt-4.1", "gpt-4o", "gpt-4", "gpt-3.5", "o3"]
                banned_snippets = ["audio", "vision", "realtime", "embed", "whisper", "tts", "test", "beta", "sandbox"]
                filtered = [
                    m
                    for m in merged
                    if any(m.startswith(p) for p in allowed_prefixes)
                    and not any(b in m.lower() for b in banned_snippets)
                ]
                # Keep current selections visible even if not in filtered list
                candidate_order = (
                    ([self._full_model, self._refresh_model] if self._full_model or self._refresh_model else [])
                    + sorted(filtered, reverse=True)
                    + defaults
                )
                seen: set[str] = set()
                final: list[str] = []
                for m in candidate_order:
                    if m and m not in seen:
                        seen.add(m)
                        final.append(m)
                self._available_models = final
                # If current selections are not in the available list, fall back to first entries
                if self._full_model not in final and final:
                    self._full_model = final[0]
                if self._refresh_model not in final and len(final) > 1:
                    self._refresh_model = final[1]
                elif self._refresh_model not in final and final:
                    self._refresh_model = final[0]
                self._logger.info("LLM models fetched: %s (showing %s)", fetched, len(final))
                if final:
                    self._logger.debug("Model sample: %s", final[:10])
                # Emit once with models + selections to preserve order on the UI thread
                self._model_signals.models_ready.emit(final, self._full_model or "", self._refresh_model or "")
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
        if self._available_models and hasattr(self._window, "populate_models"):
            self._window.populate_models(self._available_models)

    def _load_stored_prompt(self) -> None:
        if not self._app_state:
            return
        stored = self._app_state.get("llm_prompt")
        if stored:
            # If stored prompt contains legacy markdown templates, replace with default compact contract
            if "```" in stored or "# ✅" in stored or "USER PAYLOAD" in stored:
                self._llm_prompt = self._default_developer_prompt()
                self._app_state.set("llm_prompt", self._llm_prompt)
            else:
                self._llm_prompt = stored
        if hasattr(self._window, "set_prompt_value"):
            self._window.set_prompt_value(self._llm_prompt)

    def _load_stored_rr_gate(self) -> None:
        if not self._app_state:
            return
        stored = self._app_state.get("llm_disable_rr_gate")
        if isinstance(stored, bool):
            self._disable_rr_gate = stored
        if hasattr(self._window, "set_rr_gate_state"):
            self._window.set_rr_gate_state(self._disable_rr_gate)

    def _on_display_tz_changed(self, tz_name: str) -> None:
        try:
            self._chart_adapter.set_timezone(tz_name)
            self._logger.info("Chart timezone set to %s", tz_name)
        except Exception:
            self._logger.debug("Failed to set chart timezone to %s", tz_name, exc_info=True)

    def _normalize_snapshot_for_llm(self, snapshot: dict) -> dict:
        quote_src = snapshot.get("quote") if isinstance(snapshot, dict) else {}
        if not isinstance(quote_src, dict):
            quote_src = {}
        # fall back to latest quote cache if missing
        bid = quote_src.get("bid", self._last_quote.get("bid"))
        ask = quote_src.get("ask", self._last_quote.get("ask"))
        last = quote_src.get("last", self._last_quote.get("last"))
        volume = quote_src.get("volume", self._last_quote.get("total_volume"))
        quote = {"bid": bid, "ask": ask, "last": last, "volume": volume}

        session_mode = snapshot.get("session_mode")
        if session_mode not in self._ALLOWED_SESSION_MODES:
            session_mode = "SEAMLESS"
        market_state = snapshot.get("market_state")
        if market_state not in self._ALLOWED_MARKET_STATES:
            market_state = self._compute_market_state()
        levels_src = snapshot.get("levels") if isinstance(snapshot, dict) else {}
        if not isinstance(levels_src, dict):
            levels_src = {}
        levels = {
            "nearest_resistance": levels_src.get("nearest_resistance"),
            "nearest_support": levels_src.get("nearest_support"),
        }
        session_src = snapshot.get("session") if isinstance(snapshot, dict) else {}
        if not isinstance(session_src, dict):
            session_src = {}
        session = {
            "premarket_high": session_src.get("premarket_high"),
            "premarket_low": session_src.get("premarket_low"),
            "opening_range_high": session_src.get("opening_range_high"),
            "opening_range_low": session_src.get("opening_range_low"),
            "open_price": session_src.get("open_price"),
        }
        micro_src = snapshot.get("micro") if isinstance(snapshot, dict) else {}
        if not isinstance(micro_src, dict):
            micro_src = {}
        micro = {
            "micro_resistance_15m": micro_src.get("micro_resistance_15m"),
            "micro_support_15m": micro_src.get("micro_support_15m"),
            "micro_state": micro_src.get("micro_state"),
        }
        bars_window = self._extract_bars_window(snapshot)
        bars_5m = bars_window
        bars_1m = self._bars_1m
        bars_1m_quality = "ok" if isinstance(bars_1m, list) and len(bars_1m) >= 60 else "partial"
        norm = {
            "schema_version": snapshot.get("schema_version", "AE-1.1"),
            "status": snapshot.get("status", "ok"),
            "data_quality": snapshot.get("data_quality"),
            "as_of_ts_ms": snapshot.get("as_of_ts_ms") or snapshot.get("as_of") or int(time.time() * 1000),
            "symbol": snapshot.get("symbol"),
            "session_mode": session_mode,
            "market_state": market_state,
            "quote": quote,
            "bars_window": bars_5m,
            "bars_5m": bars_5m,
            "bars_1m": bars_1m,
            "bars_1m_quality": bars_1m_quality,
            "invocation_type": snapshot.get("invocation_type", "MANUAL_RECALC"),
            "in_position": snapshot.get("in_position", False),
            "side": "LONG" if snapshot.get("in_position") else None,
            "entry_price": snapshot.get("entry_price"),
            "qty": snapshot.get("qty"),
            "current_stop_loss": snapshot.get("current_stop_loss"),
            "current_target_price": snapshot.get("current_target_price"),
            "vwap": snapshot.get("vwap"),
            "session": session,
            "micro": micro,
            "levels": levels,
        }
        return norm

    def _extract_bars_window(self, snapshot: dict) -> list[dict]:
        # Try common bar fields
        candidates = []
        for key in ("bars_window_5m", "bars_window", "bars_5m", "ohlcv_5m"):
            val = snapshot.get(key) if isinstance(snapshot, dict) else None
            if val:
                candidates.append(val)
        bars_raw = None
        for c in candidates:
            if isinstance(c, list) and c:
                bars_raw = c
                break
        if (not bars_raw or not isinstance(bars_raw, list)) and self._bars:
            try:
                bars_raw = []
                for b in self._bars:
                    if not isinstance(b, dict):
                        continue
                    t = b.get("time")
                    if t is None:
                        continue
                    bars_raw.append(
                        {
                            "ts_ms": int(t) * 1000,
                            "o": b.get("open"),
                            "h": b.get("high"),
                            "l": b.get("low"),
                            "c": b.get("close"),
                            "v": b.get("volume"),
                        }
                    )
            except Exception:
                bars_raw = None
        if not bars_raw or not isinstance(bars_raw, list):
            return []
        compact: list[dict] = []
        for idx, bar in enumerate(bars_raw):
            if not isinstance(bar, dict):
                continue
            # Skip incomplete bars if flagged
            if bar.get("complete") is False or bar.get("is_partial") is True:
                continue
            ts_ms = (
                bar.get("ts_ms")
                or bar.get("ts")
                or bar.get("timestamp_ms")
                or bar.get("t")
            )
            o = bar.get("o") if "o" in bar else bar.get("open")
            h = bar.get("h") if "h" in bar else bar.get("high")
            l = bar.get("l") if "l" in bar else bar.get("low")
            c = bar.get("c") if "c" in bar else bar.get("close")
            v = bar.get("v") if "v" in bar else bar.get("volume")
            if ts_ms is None or o is None or h is None or l is None or c is None or v is None:
                continue
            try:
                ts_int = int(ts_ms)
                compact.append(
                    {
                        "ts_ms": ts_int,
                        "o": round(float(o), 4),
                        "h": round(float(h), 4),
                        "l": round(float(l), 4),
                        "c": round(float(c), 4),
                        "v": float(v),
                    }
                )
            except Exception:
                continue
        # drop the last bar only if likely forming (assume 5m cadence)
        if compact:
            now_ms = int(time.time() * 1000)
            last_bar = compact[-1]
            ts_ms_last = last_bar.get("ts_ms")
            if ts_ms_last and isinstance(ts_ms_last, (int, float)):
                if now_ms < ts_ms_last + 5 * 60 * 1000:
                    compact = compact[:-1]
        # keep chronological order and cap length to max
        if len(compact) > self._BARS_WINDOW_MAX:
            compact = compact[-self._BARS_WINDOW_MAX :]
        # If still short, try a 5m backfill from REST history
        if len(compact) < self._BARS_WINDOW_MIN_READY:
            symbol = snapshot.get("symbol") if isinstance(snapshot, dict) else None
            if self._rest_client and symbol:
                try:
                    backfill = self._fetch_5m_history(symbol)
                    if backfill:
                        combined = compact + backfill
                        # dedupe by ts_ms and sort
                        dedup: dict[int, dict] = {}
                        for b in combined:
                            ts = b.get("ts_ms")
                            if ts is None:
                                continue
                            dedup[int(ts)] = b
                        compact = [dedup[k] for k in sorted(dedup.keys())]
                        if len(compact) > self._BARS_WINDOW_MAX:
                            compact = compact[-self._BARS_WINDOW_MAX :]
                except Exception:
                    self._logger.debug("5m backfill fetch failed for %s", symbol, exc_info=True)
        return compact

    def _fetch_5m_history(self, symbol: str) -> list[dict]:
        """Fetch 5m candles as a compact bars list."""
        resp = self._rest_client.fetch_price_history(symbol, None, None, "5m") if self._rest_client else {}
        candles = resp.get("candles") or []
        out: list[dict] = []
        for c in candles:
            if c.get("datetime") is None:
                continue
            try:
                out.append(
                    {
                        "ts_ms": int(c.get("datetime")),
                        "o": round(float(c.get("open")), 4),
                        "h": round(float(c.get("high")), 4),
                        "l": round(float(c.get("low")), 4),
                        "c": round(float(c.get("close")), 4),
                        "v": float(c.get("volume") or 0),
                    }
                )
            except Exception:
                continue
        return out

    def _is_snapshot_ready_for_llm(self, snapshot: dict) -> tuple[bool, list[str]]:
        normalized = self._normalize_snapshot_for_llm(snapshot)
        missing: list[str] = []
        session_mode = normalized.get("session_mode")
        if session_mode not in self._ALLOWED_SESSION_MODES:
            missing.append("session_mode")
        market_state = normalized.get("market_state")
        if market_state not in self._ALLOWED_MARKET_STATES:
            missing.append("market_state")
        quote = normalized.get("quote") or {}
        last = quote.get("last") if isinstance(quote, dict) else None
        bid = quote.get("bid") if isinstance(quote, dict) else None
        ask = quote.get("ask") if isinstance(quote, dict) else None
        if last is None:
            missing.append("quote.last")
        if bid is None and ask is None:
            missing.append("quote.bid/ask")
        bars = normalized.get("bars_5m") if isinstance(normalized, dict) else normalized.get("bars_window")
        bars_len = len(bars) if isinstance(bars, list) else 0
        if not isinstance(bars, list) or bars_len < self._BARS_WINDOW_MIN_READY:
            missing.append("bars_5m")
        return (len(missing) == 0, missing)

    def _build_structural_plan(self, payload: dict) -> dict:
        """Derive deterministic structural plan from normalized payload with conservative limits."""
        quote = payload.get("quote") or {}
        levels = payload.get("levels") or {}
        micro = payload.get("micro") or {}
        bars = payload.get("bars_window") or []
        invalid_reasons: list[str] = []

        last = quote.get("last") if isinstance(quote, dict) else None
        ask = quote.get("ask") if isinstance(quote, dict) else None
        nearest_res = levels.get("nearest_resistance") if isinstance(levels, dict) else None
        nearest_sup = levels.get("nearest_support") if isinstance(levels, dict) else None
        micro_res = micro.get("micro_resistance_15m") if isinstance(micro, dict) else None
        micro_sup = micro.get("micro_support_15m") if isinstance(micro, dict) else None

        entry = None
        entry_source = "last"
        market_state = payload.get("market_state")
        if last is not None and nearest_res and isinstance(nearest_res, dict):
            res_price = nearest_res.get("price")
            if res_price is not None:
                try:
                    last_f = float(last)
                    res_f = float(res_price)
                    if res_f > last_f and market_state == "normal":
                        pct = (res_f - last_f) / last_f
                        if pct <= self._ENTRY_TO_TRIGGER_MAX_PCT and pct <= self._ENTRY_TRIGGER_PROX_PCT:
                            entry = res_f
                            entry_source = "nearest_resistance_trigger"
                except Exception:
                    pass
        if entry is None:
            entry = ask if ask is not None else last
        try:
            entry_f = float(entry) if entry is not None else None
        except Exception:
            entry_f = None

        stop = None
        stop_source = None
        if entry_f is not None:
            if nearest_sup and isinstance(nearest_sup, dict) and nearest_sup.get("price") is not None:
                try:
                    sup_f = float(nearest_sup.get("price"))
                    if sup_f < entry_f:
                        stop = sup_f
                        stop_source = "nearest_support"
                except Exception:
                    pass
            if stop is None and micro_sup is not None:
                try:
                    micro_sup_f = float(micro_sup)
                    if micro_sup_f < entry_f:
                        stop = micro_sup_f
                        stop_source = "micro_support_15m"
                except Exception:
                    pass
            if stop is None:
                try:
                    lows = [float(b.get("l")) for b in bars[-self._SWING_LOW_LOOKBACK_BARS :] if isinstance(b, dict) and b.get("l") is not None]
                    lows = [v for v in lows if v < entry_f]
                    if lows:
                        stop = min(lows)
                        stop_source = "swing_low"
                except Exception:
                    pass

        target = None
        target_source = None
        if entry_f is not None and micro_res is not None:
            try:
                micro_f = float(micro_res)
                if micro_f > entry_f and (micro_f - entry_f) / entry_f <= self._MAX_TARGET_PCT:
                    target = micro_f
                    target_source = "micro_resistance_15m"
            except Exception:
                pass
        if target is None and entry_f is not None:
            try:
                highs = [float(b.get("h")) for b in bars[-self._SWING_HIGH_LOOKBACK_BARS :] if isinstance(b, dict) and b.get("h") is not None]
                if highs:
                    swing_high = max(highs)
                    if swing_high > entry_f and (swing_high - entry_f) / entry_f <= self._MAX_TARGET_PCT:
                        target = swing_high
                        target_source = "swing_high"
            except Exception:
                pass
        if target is None and nearest_res and isinstance(nearest_res, dict) and nearest_res.get("price") is not None and entry_f is not None:
            try:
                res_f = float(nearest_res.get("price"))
                if res_f > entry_f and (res_f - entry_f) / entry_f <= self._MAX_TARGET_PCT:
                    target = res_f
                    target_source = "nearest_resistance"
            except Exception:
                pass

        # Compute diagnostics
        risk_per_share = None
        reward_per_share = None
        risk_pct = None
        target_pct = None
        rr = None
        if entry_f is not None and stop is not None:
            try:
                stop_f = float(stop)
                risk_per_share = entry_f - stop_f
                if entry_f != 0:
                    risk_pct = risk_per_share / entry_f
            except Exception:
                pass
        if entry_f is not None and target is not None:
            try:
                target_f = float(target)
                reward_per_share = target_f - entry_f
                if entry_f != 0:
                    target_pct = reward_per_share / entry_f
            except Exception:
                pass
        if risk_per_share is not None and reward_per_share is not None and risk_per_share > 0 and reward_per_share > 0:
            try:
                rr = reward_per_share / risk_per_share
            except Exception:
                rr = None

        # Validity rules
        valid = True
        if entry_f is None:
            valid = False
            invalid_reasons.append("NO_ENTRY_PRICE")
        if stop is None or (entry_f is not None and float(stop) >= entry_f):
            valid = False
            invalid_reasons.append("NO_STOP_BELOW_ENTRY")
        if target is None or (entry_f is not None and float(target) <= entry_f):
            valid = False
            invalid_reasons.append("NO_TARGET_ABOVE_ENTRY")
        if risk_pct is not None and risk_pct > self._MAX_STOP_PCT:
            valid = False
            invalid_reasons.append("STOP_TOO_WIDE")
        if target_pct is not None and target_pct > self._MAX_TARGET_PCT:
            valid = False
            invalid_reasons.append("TARGET_TOO_FAR")
        if rr is not None and rr < 2.0:
            valid = False
            invalid_reasons.append("RR_BELOW_MINIMUM")

        return {
            "entry_candidate": entry_f,
            "stop_candidate": stop,
            "target_candidate": target,
            "rr_candidate": rr,
            "risk_per_share": risk_per_share,
            "reward_per_share": reward_per_share,
            "risk_pct": risk_pct,
            "target_pct": target_pct,
            "entry_source": entry_source,
            "stop_source": stop_source,
            "target_source": target_source,
            "valid": valid,
            "invalid_reasons": invalid_reasons[:3],
        }

    def _compute_market_state(self) -> str | None:
        now_et = datetime.now(self._et_tz)
        t = now_et.time()
        if dtime(4, 0) <= t < dtime(9, 30):
            return "premarket"
        if dtime(9, 30) <= t < dtime(16, 0):
            return "normal"
        if dtime(16, 0) <= t < dtime(20, 0):
            return "afterhours"
        return None

    def _default_developer_prompt(self) -> str:
        return (
            "SETUP_DISCOVERY_V1\n"
            "Return EXACTLY ONE JSON object and NOTHING ELSE.\n"
            "No markdown. No extra keys.\n\n"
            "Required JSON structure:\n"
            "{\n"
            '  "stock_bias": "HAS_POTENTIAL" | "NO_EDGE",\n'
            '  "summary": "2-3 sentence structural read",\n'
            '  "setups": [\n'
            "    {\n"
            '      "name": string,\n'
            '      "trigger_condition": string,\n'
            '      "entry_trigger_price": number,\n'
            '      "stop_price": number,\n'
            '      "target_price": number,\n'
            '      "rr_to_target1": number,\n'
            '      "move_pct_to_target1": number,\n'
            '      "setup_rating": "A+|A|A-|B+|B|B-|C+|C|C-|D",\n'
            '      "confirmation_requirements": string,\n'
            '      "target1_label": string,\n'
            '      "extension_trigger": string,\n'
            '      "extension_target": number|null,\n'
            '      "extension_notes": string,\n'
            '      "tape_warning": "NONE" | "SPIKEY_PULLBACKS"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Maximum 2 setups returned.\n"
            "- If there are 3+ plausible setups, return only the best 1–2 and do NOT include any rated below B+.\n"
            "- If only 1–2 candidates exist, you may include a lone B- or C/C+ (rating rules still apply).\n"
            "- stock_bias must be HAS_POTENTIAL only if at least one setup_rating >= B-. If best setup is C/C+, set stock_bias=NO_EDGE (you may still return the C/C+ setup in setups).\n"
            "- Rating must reflect rr_to_target1:\n"
            "    * rr_to_target1 < 1.0  -> setup_rating cannot be above C+\n"
            "    * 1.0 <= rr_to_target1 < 1.2 -> setup_rating cannot be above B-\n"
            "    * rr_to_target1 >= 1.2 -> rating may be B, B+, A-, etc based on structure/volume quality\n"
            "- Additional caps based on move_pct_to_target1 = (target_price - entry_trigger_price) / entry_trigger_price:\n"
            "    * move_pct_to_target1 < 0.05 -> setup_rating cannot be above B-\n"
            "    * 0.05 <= move_pct_to_target1 < 0.10 -> setup_rating cannot be above A-\n"
            "    * A+ requires move_pct_to_target1 >= 0.10\n"
            "- VWAP rule (based on entry_trigger_price vs vwap): if entry_trigger_price < vwap, cap at B max (no A+), and mention reclaim/hold behavior in trigger/confirmations.\n"
            "- Volume rule (no market-hours bias): A or A+ requires trigger/confirmations to reference volume expansion/continuation, and recent ~3 bars should show rising/elevated volume; otherwise cap at B+.\n"
            "- Only claim \"volume expansion\" or \"elevated volume\" if: (a) the most recent completed 1m bar volume > each of the prior 2 1m bars, OR (b) the most recent completed 1m bar volume >= 1.5x median volume of last 10 1m bars; otherwise use neutral wording.\n"
            "- Do NOT hard-gate on RR; rate appropriately instead.\n"
            "- Compute rr_to_target1 = (target_price - entry_trigger_price) / (entry_trigger_price - stop_price). If risk<=0 or reward<=0, do not include the setup.\n"
            "- Compute move_pct_to_target1 = (target_price - entry_trigger_price) / entry_trigger_price and include it for every setup.\n"
            "- Detect tape_warning via bars_1m: set SPIKEY_PULLBACKS only if in last 20 1m bars there are 2+ failed breakouts (price trades above local high/resistance, closes back below within 1–3 bars, retraces >=50% of breakout bar) AND those fails occur on elevated volume vs neighboring bars; else NONE.\n"
            "- If tape_warning=SPIKEY_PULLBACKS, cap setup_rating at B- unless trigger is explicitly break+hold/retest, and confirmation_requirements must include hold/retest (not just volume).\n"
            "- Entry must be trigger-based (not vague).\n"
            "- Use bars_5m for structure/regime context; use bars_1m for triggers/tape_warning/volume checks.\n"
            "- target1_label must strictly correspond to the structural source of target_price:\n"
            "    * If target_price equals levels.nearest_resistance.price -> target1_label=\"nearest_resistance\"\n"
            "    * If target_price equals micro.micro_resistance_15m -> target1_label=\"micro_resistance_15m\"\n"
            "    * If target_price equals session.opening_range_high -> target1_label=\"opening_range_high\"\n"
            "    * If target_price equals session.premarket_high -> target1_label=\"premarket_high\"\n"
            "    * If target_price matches a recent bar high from bars_window -> target1_label=\"swing_high\"\n"
            "- No freeform labels allowed.\n"
            "- If target1_label=\"swing_high\", target_price MUST match an exact high value from a bar in bars_window (within 0.2% tolerance). Do not round or fabricate structural levels.\n"
            "- Relevance: if proposing a reclaim setup (e.g., reclaim ORH/premarket_high), that level must have traded in the last 30 bars_1m or current price must be within ~8% of that level; otherwise do not propose that setup.\n"
            "- extension_trigger describes what must happen to treat it as a runner (e.g., 1m close above target1 with volume expansion).\n"
            "- extension_target must be above target_price for longs; otherwise set extension_target=null and extension_notes should state 'No higher structural level provided'.\n"
            "- Ratings are based on rr_to_target1, not extension potential.\n"
            "- If no high-quality setup exists, return stock_bias='NO_EDGE' and setups=[].\n"
            "- No trade validation logic. No risk gates. No null rules.\n"
        )

    def _default_developer_prompt_refresh(self) -> str:
        return (
            "SETUP_DISCOVERY_REFRESH_V1\n"
            "Return EXACTLY ONE JSON object in the SAME schema as full mode (stock_bias, summary, setups[]...).\n"
            'stock_bias MUST be one of: "HAS_POTENTIAL" | "NO_EDGE".\n'
            "Every setup MUST include ALL required keys: name, trigger_condition, entry_trigger_price, stop_price, target_price, rr_to_target1, move_pct_to_target1, setup_rating, confirmation_requirements, target1_label, extension_trigger, extension_target, extension_notes, tape_warning.\n"
            "If you do not change a field, copy it from prior_best_setup. Do not omit fields.\n"
            "Use prior_best_setup plus latest prices/levels to update triggers/targets/stops/RR if needed.\n"
            "Rating caps must match full mode: rr_to_target1 caps; move_pct_to_target1 caps (B- max <5%, A- max <10%, A+ only if >=10%); VWAP cap (if entry_trigger_price<vwap cap at B and mention reclaim/hold); A/A+ requires volume expansion in triggers/confirmations and rising recent volume; otherwise cap at B+.\n"
            "- Only claim \"volume expansion\" or \"elevated volume\" if: (a) the most recent completed 1m bar volume > each of the prior 2 1m bars, OR (b) the most recent completed 1m bar volume >= 1.5x median volume of last 10 1m bars; otherwise use neutral wording.\n"
            "- Use bars_5m for structure/regime context; use bars_1m for triggers/tape_warning/volume checks.\n"
            "- target1_label must strictly correspond to the structural source of target_price:\n"
            "    * If target_price equals levels.nearest_resistance.price -> target1_label=\"nearest_resistance\"\n"
            "    * If target_price equals micro.micro_resistance_15m -> target1_label=\"micro_resistance_15m\"\n"
            "    * If target_price equals session.opening_range_high -> target1_label=\"opening_range_high\"\n"
            "    * If target_price equals session.premarket_high -> target1_label=\"premarket_high\"\n"
            "    * If target_price matches a recent bar high from bars_window -> target1_label=\"swing_high\"\n"
            "- No freeform labels allowed.\n"
            "- If target1_label=\"swing_high\", target_price MUST match an exact high value from a bar in bars_window (within 0.2% tolerance). Do not round or fabricate structural levels.\n"
            "Summary must be <=2 sentences.\n"
            "No markdown. No extra keys.\n"
            "Self-check: ensure every setup has all required keys; ensure stock_bias is one of the two enums.\n"
        )

    def _build_llm_messages(self, snapshot: dict) -> list[dict[str, str]]:
        system_text = (
            "You are the LLM Coach for a momentum day-trading assistant.\n"
            "You are advisory-only: never place/modify/cancel orders and never arm triggers.\n"
            "Longs only.\n"
            "Do not compute indicators or fabricate missing data.\n"
            "Stateless: evaluate only the provided snapshot.\n"
            "Output MUST be a single JSON object only (no markdown, no extra text).\n"
            "Summary fields must be <=3 sentences."
        )
        developer_text = self._llm_prompt or self._default_developer_prompt()
        normalized = self._normalize_snapshot_for_llm(snapshot)
        user_text = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
        return [
            {"role": "system", "content": system_text},
            {"role": "developer", "content": developer_text},
            {"role": "user", "content": user_text},
        ]

    def _build_llm_refresh_messages(self, payload: dict) -> list[dict[str, str]]:
        system_text = (
            "You are the LLM Coach. Update the prior best setup using the latest prices/levels and small bar sample.\n"
            "Keep the SAME JSON schema as full mode (stock_bias, summary, setups[]...).\n"
            "Summary <=2 sentences. No markdown. JSON only."
        )
        developer_text = self._llm_prompt_refresh or self._default_developer_prompt_refresh()
        user_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return [
            {"role": "system", "content": system_text},
            {"role": "developer", "content": developer_text},
            {"role": "user", "content": user_text},
        ]

    def _validate_setup_schema(self, rec: dict) -> bool:
        if not isinstance(rec, dict):
            return False
        if "stock_bias" not in rec or "setups" not in rec:
            return False
        if not isinstance(rec["setups"], list):
            return False
        if len(rec["setups"]) > 2:
            return False
        for setup in rec["setups"]:
            if not isinstance(setup, dict):
                return False
            required = {
                "name",
                "trigger_condition",
                "entry_trigger_price",
                "stop_price",
                "target_price",
                "rr_to_target1",
                "move_pct_to_target1",
                "setup_rating",
                "confirmation_requirements",
                "target1_label",
                "extension_trigger",
                "extension_target",
                "extension_notes",
                "tape_warning",
            }
            if not required.issubset(setup.keys()):
                return False
            if not isinstance(setup.get("name"), str):
                return False
            if not isinstance(setup.get("trigger_condition"), str):
                return False
            if not isinstance(setup.get("confirmation_requirements"), str):
                return False
            if not isinstance(setup.get("target1_label"), str):
                return False
            if not isinstance(setup.get("extension_trigger"), str):
                return False
            if not isinstance(setup.get("extension_notes"), str):
                return False
            num_fields = ("entry_trigger_price", "stop_price", "target_price", "rr_to_target1")
            num_fields = ("entry_trigger_price", "stop_price", "target_price", "rr_to_target1", "move_pct_to_target1")
            for field in num_fields:
                val = setup.get(field)
                if not isinstance(val, (int, float)):
                    return False
            ext_target = setup.get("extension_target")
            if ext_target is not None and not isinstance(ext_target, (int, float)):
                return False
            if not isinstance(setup.get("setup_rating"), str):
                return False
            if not isinstance(setup.get("tape_warning"), str):
                return False
        return True

    @staticmethod
    def _rating_rank(rating: str) -> int:
        order = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D"]
        try:
            return order.index(rating)
        except Exception:
            return len(order)

    def _choose_best_setup(self, setups: list[dict] | None) -> dict | None:
        if not setups:
            return None
        sorted_setups = sorted(
            [s for s in setups if isinstance(s, dict)],
            key=lambda s: (self._rating_rank(str(s.get("setup_rating", ""))), -(s.get("rr_to_target1") or 0)),
        )
        return sorted_setups[0] if sorted_setups else None

    def _build_refresh_payload(self, snapshot: dict) -> dict:
        quote = snapshot.get("quote") if isinstance(snapshot, dict) else {}
        if not isinstance(quote, dict):
            quote = {}
        session_src = snapshot.get("session") if isinstance(snapshot, dict) else {}
        if not isinstance(session_src, dict):
            session_src = {}
        micro_src = snapshot.get("micro") if isinstance(snapshot, dict) else {}
        if not isinstance(micro_src, dict):
            micro_src = {}
        levels_src = snapshot.get("levels") if isinstance(snapshot, dict) else {}
        if not isinstance(levels_src, dict):
            levels_src = {}
        bars = snapshot.get("bars_window") if isinstance(snapshot, dict) else []
        recent_bars: list[dict] = []
        if isinstance(bars, list):
            recent_bars = bars[-3:] if len(bars) >= 3 else bars
        symbol = snapshot.get("symbol")
        prior = self._last_llm_rec_by_symbol.get(str(symbol)) if symbol else None
        prior_best = self._choose_best_setup(prior.get("setups") if isinstance(prior, dict) else None)
        prior_best_payload = (
            {
                "name": prior_best.get("name"),
                "trigger_condition": prior_best.get("trigger_condition"),
                "entry_trigger_price": prior_best.get("entry_trigger_price"),
                "stop_price": prior_best.get("stop_price"),
                "target_price": prior_best.get("target_price"),
                "rr_to_target1": prior_best.get("rr_to_target1"),
                "setup_rating": prior_best.get("setup_rating"),
                "tape_warning": prior_best.get("tape_warning"),
            }
            if prior_best
            else None
        )
        return {
            "schema": "REFRESH_COMPACT_V1",
            "symbol": symbol,
            "as_of_ts_ms": snapshot.get("as_of_ts_ms"),
            "quote": {
                "last": quote.get("last"),
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "volume": quote.get("volume"),
            },
            "vwap": snapshot.get("vwap"),
            "session": {
                "opening_range_high": session_src.get("opening_range_high"),
                "opening_range_low": session_src.get("opening_range_low"),
                "premarket_high": session_src.get("premarket_high"),
                "premarket_low": session_src.get("premarket_low"),
            },
            "micro": {
                "micro_resistance_15m": micro_src.get("micro_resistance_15m"),
                "micro_support_15m": micro_src.get("micro_support_15m"),
            },
            "levels": {
                "nearest_resistance": levels_src.get("nearest_resistance"),
                "nearest_support": levels_src.get("nearest_support"),
            },
            "recent_bars": recent_bars,
            "prior_best_setup": prior_best_payload,
        }

    def _patch_refresh_output(
        self,
        rec: dict,
        prior_best_setup: dict | None,
        prior_full_rec: dict | None,
        refresh_mode: bool,
    ) -> dict:
        """Patch refresh output to enforce schema and enum sanity without changing full-mode behavior."""
        if not refresh_mode or not isinstance(rec, dict):
            return rec
        # stock_bias sanity
        stock_bias = rec.get("stock_bias")
        if stock_bias not in {"HAS_POTENTIAL", "NO_EDGE"}:
            mapped = None
            if isinstance(stock_bias, str):
                lowered = stock_bias.lower()
                if lowered == "neutral":
                    mapped = "NO_EDGE"
                elif lowered == "has_potential":
                    mapped = "HAS_POTENTIAL"
                elif lowered == "no_edge":
                    mapped = "NO_EDGE"
            if mapped:
                rec["stock_bias"] = mapped
            else:
                fallback = None
                if prior_full_rec and isinstance(prior_full_rec, dict):
                    fb = prior_full_rec.get("stock_bias")
                    if fb in {"HAS_POTENTIAL", "NO_EDGE"}:
                        fallback = fb
                rec["stock_bias"] = fallback or "NO_EDGE"
        # setups patch
        setups = rec.get("setups")
        if isinstance(setups, list):
            for idx, s in enumerate(setups):
                if not isinstance(s, dict):
                    continue
                required_keys = [
                    "name",
                    "trigger_condition",
                    "entry_trigger_price",
                    "stop_price",
                    "target_price",
                    "rr_to_target1",
                    "setup_rating",
                    "confirmation_requirements",
                    "target1_label",
                    "extension_trigger",
                    "extension_target",
                    "extension_notes",
                    "tape_warning",
                ]
                prior = prior_best_setup if isinstance(prior_best_setup, dict) else None
                for key in required_keys:
                    if key not in s or s.get(key) is None:
                        if prior and key in prior:
                            s[key] = prior.get(key)
                        else:
                            if key == "confirmation_requirements":
                                s[key] = "(unchanged)"
                            elif key == "target1_label":
                                s[key] = "(unchanged)"
                            elif key == "extension_trigger":
                                s[key] = ""
                            elif key == "extension_target":
                                s[key] = None
                            elif key == "extension_notes":
                                s[key] = ""
                # setup_rating sanity
                rating = s.get("setup_rating")
                valid_ratings = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D"}
                if rating not in valid_ratings:
                    if prior and prior.get("setup_rating") in valid_ratings:
                        s["setup_rating"] = prior.get("setup_rating")
                    else:
                        s["setup_rating"] = "C+"
                # compute move_pct_to_target1 if missing
                if s.get("move_pct_to_target1") is None:
                    try:
                        entry = s.get("entry_trigger_price")
                        target = s.get("target_price")
                        if entry is not None and target is not None and float(entry) != 0:
                            s["move_pct_to_target1"] = (float(target) - float(entry)) / float(entry)
                    except Exception:
                        pass
                if s.get("move_pct_to_target1") is None and prior and prior.get("move_pct_to_target1") is not None:
                    s["move_pct_to_target1"] = prior.get("move_pct_to_target1")
        return rec

    def _format_llm_recommendation(self, rec: dict) -> str:
        validity = rec.get("validity") or "--"
        rating = rec.get("setup_rating") or "--"
        reasons = rec.get("reason_codes") or []
        summary = rec.get("summary") or ""
        entry = rec.get("entry_price")
        stop = rec.get("stop_loss")
        target = rec.get("target_price")
        rr = rec.get("risk_reward")

        def _fmt(val: Any) -> str:
            try:
                return f"{float(val):.4f}"
            except Exception:
                return "--"

        lines = [f"{validity} {rating}"]
        if validity == "VALID_FOR_TRADING" and entry is not None and stop is not None and target is not None and rr is not None:
            lines.append(f"Entry {_fmt(entry)} | Stop {_fmt(stop)} | Target {_fmt(target)} | RR {float(rr):.2f}")
        if reasons:
            lines.append(f"Reasons: {', '.join(reasons)}")
        if summary:
            lines.append(f"Summary: {summary}")
        return "\n".join(lines)

    def _format_llm_status(self, rec: dict, model: str, symbol: str | None) -> str:
        validity = rec.get("validity") or "--"
        rating = rec.get("setup_rating") or "--"
        ts_txt = datetime.now(self._et_tz).strftime("%Y-%m-%d %H:%M:%S")
        return f"LLM: {model} | {symbol or '--'} | {validity} {rating} | {ts_txt}"

    def _emit_llm_result(
        self,
        normalized_snapshot: dict,
        model: str,
        invocation: str,
        parsed: dict | None,
        raw_text: str,
        error: str | None,
    ) -> None:
        payload = {
            "symbol": normalized_snapshot.get("symbol"),
            "as_of_ts_ms": normalized_snapshot.get("as_of_ts_ms"),
            "model": model,
            "invocation_type": normalized_snapshot.get("invocation_type") or invocation,
            "parsed": parsed,
            "raw_text": raw_text,
            "error": error,
        }
        self._last_llm_payload = payload
        self._logger.info(
            "LLM UI payload emitted symbol=%s parsed_ok=%s error=%s",
            payload.get("symbol"),
            parsed is not None and error is None,
            error,
        )
        symbol = normalized_snapshot.get("symbol")
        if symbol and parsed and isinstance(parsed, dict):
            self._last_llm_rec_by_symbol[str(symbol)] = parsed
        try:
            self._llm_signals.llm_result_ready.emit(payload)
        except Exception:
            self._logger.warning("Failed to emit LLM UI payload", exc_info=True)

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
