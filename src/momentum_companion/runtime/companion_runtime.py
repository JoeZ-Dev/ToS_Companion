from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time as dtime
from pathlib import Path
import json
import os
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

from momentum_companion.analysis.ae import AEEngine
from momentum_companion.bootstrap import bootstrap
from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.data.bar_aggregator import BarAggregator10s, TenSecondBar
from momentum_companion.data.contracts import QuoteEvent
from momentum_companion.data.price_update import PriceUpdate
from momentum_companion.llm.codex_bridge_client import CodexBridgeClient
from momentum_companion.llm.coach import LLMCoach
from momentum_companion.llm.service import LLMService
from momentum_companion.recording.backfill import HistoricalBackfillManager, seconds_until_next_backfill
from momentum_companion.recording.history import (
    load_recorded_minute_candles,
    merge_candles_prefer_primary,
)
from momentum_companion.recording.market_day import MarketDayRecorder, reached_cutoff, seconds_until_cutoff
from momentum_companion.session import CompanionSession
from momentum_companion.setup_engine.pattern_service import PatternEvaluationService
from momentum_companion.utils.logging import logging

logger = logging.getLogger(__name__)


class CompanionRuntime:
    """Own the live backend independently from Qt or any browser connection.

    Schwab OAuth remains delegated to TokenProvider -> companion_auth. This
    runtime never exposes access or refresh tokens through its public state.
    """

    def __init__(
        self,
        instance_id: str = "default_instance",
        *,
        session: CompanionSession | None = None,
        token_provider: TokenProvider | None = None,
        rest_client: SchwabRestClient | None = None,
        ae_engine: AEEngine | None = None,
    ) -> None:
        db_path, app_state, journal = bootstrap(instance_id)
        self.db_path: Path = db_path
        self.app_state = app_state
        self.journal = journal
        self.session = session or CompanionSession()
        self.pattern_service = PatternEvaluationService()

        self.token_provider = token_provider or TokenProvider(
            state_callback=self._on_auth_state
        )
        self.rest = rest_client or SchwabRestClient(
            base_url="https://api.schwabapi.com/trader/v1",
            auth_token_provider=self.token_provider,
        )
        self.ae_engine = ae_engine or AEEngine(self.rest, self.db_path)
        self._ae_engines: dict[str, AEEngine] = {}
        self._aggregators: dict[str, BarAggregator10s] = {}
        self._analysis_symbols: set[str] = set()
        setattr(self.token_provider, "rest_client", self.rest)

        self.llm_coach = LLMCoach()
        self._llm_client = CodexBridgeClient(
            socket_path=os.getenv(
                "TOS_CODEX_BRIDGE_SOCKET",
                "/run/tos-codex/bridge.sock",
            ),
            timeout_seconds=float(os.getenv("TOS_CODEX_TIMEOUT_SECONDS", "120")),
        )
        self.llm_service = LLMService(
            self.llm_coach,
            client=self._llm_client,
            journal=self.journal,
            state_callback=self._on_llm_state,
        )

        self._stream: SchwabStreamClient | None = None
        self._active_symbol: str | None = None
        self._pending_symbol: str | None = None
        self._lock = threading.RLock()
        self._et_tz = ZoneInfo("America/New_York")
        self._started = False
        self._recorder: MarketDayRecorder | None = None
        self._recording_symbols: set[str] = set()
        self._recorder_cutoff_thread: threading.Thread | None = None
        self._last_recorder_state_emit = 0.0
        self._stream_watchdog_stop = threading.Event()
        self._stream_watchdog_thread: threading.Thread | None = None
        self._stale_resubscribe_at: float | None = None
        self._backfill_stop = threading.Event()
        self._backfill_thread: threading.Thread | None = None
        self._backfill_manager = HistoricalBackfillManager(self.rest)

    @property
    def active_symbol(self) -> str | None:
        with self._lock:
            return self._active_symbol

    def start(self) -> None:
        """Mark the long-running runtime available.

        Stream connection is established lazily when a symbol is selected.
        """
        with self._lock:
            if self._started:
                return
            self._started = True
        self._stream_watchdog_stop.clear()
        self._start_stream_watchdog()
        self._backfill_stop.clear()
        self._start_history_backfill_scheduler()
        self.session.update_connection_state("READY")

    def stop(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._started = False
        self._stream_watchdog_stop.set()
        self._backfill_stop.set()
        self.stop_recording(reason="runtime_stopped")
        if stream is not None:
            try:
                stream.disconnect()
            except Exception:
                logger.warning("Failed to disconnect Schwab stream", exc_info=True)
        self.session.update_connection_state("DISCONNECTED")

    def _start_stream_watchdog(self) -> None:
        if self._stream_watchdog_thread and self._stream_watchdog_thread.is_alive():
            return

        def worker() -> None:
            while not self._stream_watchdog_stop.wait(5.0):
                try:
                    self._check_stream_freshness_once()
                except Exception:
                    logger.warning("Stream freshness watchdog failed", exc_info=True)

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name="tos-stream-freshness-watchdog",
        )
        self._stream_watchdog_thread = thread
        thread.start()

    def _start_history_backfill_scheduler(self) -> None:
        if self._backfill_thread and self._backfill_thread.is_alive():
            return

        def worker() -> None:
            # If the service starts after 07:00 ET, catch up immediately.
            now_et = datetime.now(self._et_tz)
            if now_et.time() >= dtime(hour=7):
                try:
                    summary = self._backfill_manager.run_pending()
                    logger.info("recording history backfill summary=%s", summary)
                except Exception:
                    logger.warning("Recording history backfill failed", exc_info=True)

            while not self._backfill_stop.is_set():
                delay = seconds_until_next_backfill()
                if self._backfill_stop.wait(delay):
                    return
                try:
                    summary = self._backfill_manager.run_pending()
                    logger.info("recording history backfill summary=%s", summary)
                except Exception:
                    logger.warning("Recording history backfill failed", exc_info=True)

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name="tos-recording-history-backfill",
        )
        self._backfill_thread = thread
        thread.start()

    def _check_stream_freshness_once(
        self,
        *,
        now_monotonic: float | None = None,
    ) -> None:
        if not self.is_intraday_window():
            self._stale_resubscribe_at = None
            return

        with self._lock:
            stream = self._stream
            has_symbols = bool(self._analysis_symbols or self._recording_symbols)
        if stream is None or not has_symbols:
            self._stale_resubscribe_at = None
            return

        age = stream.seconds_since_last_level_one()
        if age is None or age <= 20.0:
            self._stale_resubscribe_at = None
            return

        now_value = time.monotonic() if now_monotonic is None else now_monotonic
        if self._stale_resubscribe_at is None:
            if stream.refresh_level_one_subscription():
                self._stale_resubscribe_at = now_value
                logger.warning(
                    "Schwab L1 stale for %.1fs; subscription refresh sent",
                    age,
                )
            return

        if now_value - self._stale_resubscribe_at >= 20.0:
            logger.error(
                "Schwab L1 still stale for %.1fs after subscription refresh; reconnecting",
                age,
            )
            self._stale_resubscribe_at = None
            stream.force_reconnect("stale_level_one")

    def select_symbol(self, symbol: str) -> dict[str, Any]:
        """Select a symbol, seed history/AE state, and subscribe live data."""
        normalized = self.session.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")

        with self._lock:
            self._active_symbol = normalized
            self._pending_symbol = normalized
            is_new_analysis_symbol = normalized not in self._analysis_symbols
            self._analysis_symbols.add(normalized)

        self.session.add_symbol(normalized, make_active=True)
        engine = self._ensure_symbol_analysis(normalized)

        if is_new_analysis_symbol:
            self.pattern_service.reset(normalized)
            bars, end_ms = self._load_history(normalized)
            try:
                engine.compute_profile(normalized)
                seeded = engine.seed_intraday_from_bars(normalized, bars, end_ms=end_ms)
                if seeded:
                    self.session.update_ae_snapshot(normalized, seeded)
                    self.session.set_vwap_points(normalized, engine.vwap_points)
            except Exception:
                logger.warning("AE seed failed for %s", normalized, exc_info=True)
        with self._lock:
            if self._pending_symbol == normalized:
                self._pending_symbol = None

        self._ensure_stream()
        self._refresh_stream_subscription()

        return self.session.snapshot()

    def _ensure_symbol_analysis(self, symbol: str) -> AEEngine:
        """Return independent analysis state for one watched symbol."""
        with self._lock:
            if symbol not in self._aggregators:
                self._aggregators[symbol] = BarAggregator10s()
            engine = self._ae_engines.get(symbol)
            if engine is None:
                if not self._ae_engines:
                    engine = self.ae_engine
                else:
                    engine = AEEngine(self.rest, self.db_path)
                self._ae_engines[symbol] = engine
            if symbol == self._active_symbol:
                # Backward-compatible alias for code that still inspects the
                # currently active AE engine.
                self.ae_engine = engine
            return engine

    def snapshot(self) -> dict[str, Any]:
        return self.session.snapshot()

    def auth_status(self) -> dict[str, Any]:
        """Report companion_auth availability without exposing credentials."""
        try:
            token = self.token_provider()
            return {
                "authorized": bool(token),
                "auth_owner": "companion_auth",
                "helper_url_configured": bool(
                    getattr(self.token_provider, "_auth_helper_url", None)
                ),
            }
        except Exception as exc:
            logger.warning("companion_auth status check failed", exc_info=True)
            return {
                "authorized": False,
                "auth_owner": "companion_auth",
                "helper_url_configured": bool(
                    getattr(self.token_provider, "_auth_helper_url", None)
                ),
                "error": type(exc).__name__,
            }

    def run_llm(self, symbol: str | None = None) -> dict[str, Any]:
        selected = self.session.normalize_symbol(symbol or self.active_symbol or "")
        if not selected:
            raise ValueError("select a symbol before running LLM analysis")

        state = self.session.snapshot()
        symbol_state = state["symbols"].get(selected)
        if not symbol_state:
            raise ValueError(f"no state available for {selected}")
        snapshot = symbol_state.get("ae_snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError(f"no AE snapshot available for {selected}")
        if not self._llm_client.is_available():
            raise ValueError(
                "Host Codex CLI bridge is unavailable or not authenticated"
            )

        quote = symbol_state.get("quote") or {}
        session_mode = self.session_mode()
        messages = [
            {"role": "system", "content": self.llm_coach.system_prompt},
            {
                "role": "user",
                "content": json.dumps(snapshot, separators=(",", ":"), default=str),
            },
        ]
        result = self.llm_service.evaluate(
            snapshot,
            session_mode,
            quote,
            model_override=None,
            messages_override=messages,
        )
        self.session.update_llm_output(selected, result)
        return result

    def _load_history(self, symbol: str) -> tuple[list[dict[str, Any]], int]:
        now_ms = int(datetime.now(self._et_tz).timestamp() * 1000)
        try:
            now_et = datetime.fromtimestamp(now_ms / 1000, tz=self._et_tz)
            start_et = datetime(
                now_et.year,
                now_et.month,
                now_et.day,
                tzinfo=self._et_tz,
            )
            start_ms = int(start_et.timestamp() * 1000)
            response = self.rest.fetch_price_history(symbol, start_ms, now_ms, "1m")
            schwab_candles = response.get("candles") or []
            recorded_candles = load_recorded_minute_candles(
                symbol,
                start_ms,
                now_ms,
            )
            candles = merge_candles_prefer_primary(
                schwab_candles,
                recorded_candles,
            )
            logger.info(
                "history merged symbol=%s schwab=%d recorded=%d merged=%d",
                symbol,
                len(schwab_candles),
                len(recorded_candles),
                len(candles),
            )
            bars = [
                {
                    "time": int(c["datetime"] // 1000),
                    "open": c.get("open"),
                    "high": c.get("high"),
                    "low": c.get("low"),
                    "close": c.get("close"),
                    "volume": c.get("volume") or 0,
                }
                for c in candles
                if c.get("datetime") is not None
                and start_ms <= c["datetime"] <= now_ms
            ]
            self.session.set_history(symbol, bars)
            return bars, now_ms
        except Exception:
            logger.warning("History load failed for %s", symbol, exc_info=True)
            self.session.set_history(symbol, [])
            return [], now_ms

    def _ensure_stream(self) -> None:
        with self._lock:
            if self._stream is not None:
                return

        prefs = self.rest.get_user_preference()
        root = prefs[0] if isinstance(prefs, list) else prefs
        streamer_info = root["streamerInfo"][0]
        stream = SchwabStreamClient(
            streamer_info,
            on_quote=self._handle_quote,
            token_provider=self.token_provider,
            journal=self.journal,
            state_callback=self._on_stream_state,
            raw_payload_callback=self._handle_raw_payload,
        )
        with self._lock:
            if self._stream is None:
                self._stream = stream
            else:
                return
        # Seed desired subscriptions before the async LOGIN completes so the
        # stream client can restore them itself on initial login/reconnect.
        stream.subscribe_level_one_symbols(self._desired_stream_symbols())
        stream.connect()

    def _handle_quote(self, event: QuoteEvent) -> None:
        symbol = self.session.normalize_symbol(str(event.get("symbol") or ""))
        if not symbol:
            return
        self.session.ingest_quote(event)

        ts_ms = event.get("ts_ms")
        last = event.get("last")
        if ts_ms is None or last is None:
            return

        source_ts_type = event.get("source_ts_type") or "QUOTE_TS"
        is_trade = source_ts_type == "TRADE_TS"
        size = event.get("last_size") if is_trade else event.get("volume")
        update = PriceUpdate(
            timestamp=int(ts_ms // 1000),
            price=float(last),
            size=size,
            source="TNS" if is_trade else "L1",
        )

        with self._lock:
            if symbol not in self._analysis_symbols or symbol == getattr(self, "_pending_symbol", None):
                return
            aggregator = self._aggregators.get(symbol)
            engine = self._ae_engines.get(symbol)

        if aggregator is None or engine is None:
            engine = self._ensure_symbol_analysis(symbol)
            with self._lock:
                aggregator = self._aggregators[symbol]

        completed = aggregator.ingest_price(update)
        engine.record_quote_ts(int(ts_ms))
        if completed is not None:
            self._handle_completed_bar(symbol, completed)

    def _handle_completed_bar(self, symbol: str, bar: TenSecondBar) -> None:
        self.session.ingest_bar(symbol, bar)

        try:
            patterns = self.pattern_service.ingest_completed_bar(symbol, bar)
            self.session.update_pattern_observations(symbol, patterns)
        except Exception:
            logger.warning("Pattern evaluation failed for %s", symbol, exc_info=True)

        try:
            with self._lock:
                engine = self._ae_engines.get(symbol)
            if engine is None:
                engine = self._ensure_symbol_analysis(symbol)
            snapshot = engine.ingest_10s_bar(bar)
            points = getattr(engine, "vwap_points", None)
            if points is not None:
                self.session.set_vwap_points(symbol, points)
            if snapshot:
                self.session.update_ae_snapshot(symbol, snapshot)
        except Exception:
            logger.warning("AE live ingest failed for %s", symbol, exc_info=True)

    def _on_stream_state(self, state: str) -> None:
        self.session.update_connection_state(state)

    def _desired_stream_symbols(self) -> list[str]:
        with self._lock:
            symbols = set(self._recording_symbols)
            symbols.update(self._analysis_symbols)
        return sorted(symbols)

    def _refresh_stream_subscription(self) -> None:
        stream = self._stream
        symbols = self._desired_stream_symbols()
        if stream is None or not symbols:
            return
        try:
            # This updates desired subscription state even before LOGIN.
            stream.subscribe_level_one_symbols(symbols)
        except Exception:
            logger.warning("Live multi-symbol subscribe failed for %s", symbols, exc_info=True)

    def start_recording(self, symbols: list[str]) -> dict[str, Any]:
        if reached_cutoff():
            raise ValueError("3:00 PM ET recording cutoff has already been reached")

        normalized = [
            self.session.normalize_symbol(symbol)
            for symbol in symbols
            if self.session.normalize_symbol(symbol)
        ]
        normalized = list(dict.fromkeys(normalized))
        with self._lock:
            if self._recorder is not None:
                raise RuntimeError("a recording session is already active")
            recorder = MarketDayRecorder(normalized)
            self._recorder = recorder
            self._recording_symbols = set(recorder.symbols)

        self._ensure_stream()
        self._refresh_stream_subscription()
        self.session.update_recorder_state(recorder.state())

        def cutoff_worker() -> None:
            delay = seconds_until_cutoff()
            if delay > 0:
                time.sleep(delay)
            with self._lock:
                active = self._recorder is recorder
            if active:
                self.stop_recording(reason="3pm_cutoff")

        thread = threading.Thread(
            target=cutoff_worker,
            daemon=True,
            name="tos-companion-recorder-cutoff",
        )
        self._recorder_cutoff_thread = thread
        thread.start()
        return self.session.snapshot()["recorder_state"]

    def add_recording_symbol(
        self,
        symbol: str,
        *,
        pre7_vwap: float | None = None,
        pre7_volume: float | None = None,
    ) -> dict[str, Any]:
        if reached_cutoff():
            raise ValueError("3:00 PM ET recording cutoff has already been reached")
        normalized = self.session.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")
        with self._lock:
            recorder = self._recorder
            if recorder is None:
                raise RuntimeError("no recording session is active")
            recorder.add_symbol(normalized)
            self._recording_symbols = set(recorder.active_symbols())
        self._ensure_stream()
        self._refresh_stream_subscription()
        if pre7_vwap is not None or pre7_volume is not None:
            return self.apply_recording_pre7_seed(
                normalized,
                pre7_vwap=pre7_vwap,
                pre7_volume=pre7_volume,
            )
        state = recorder.state()
        self.session.update_recorder_state(state)
        return state

    def apply_recording_pre7_seed(
        self,
        symbol: str,
        *,
        pre7_vwap: float | None,
        pre7_volume: float | None,
    ) -> dict[str, Any]:
        normalized = self.session.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")
        if pre7_vwap is None or pre7_volume is None:
            raise ValueError("PRE7 VWAP and PRE7 volume are both required")
        vwap_value = float(pre7_vwap)
        volume_value = float(pre7_volume)
        if vwap_value <= 0:
            raise ValueError("PRE7 VWAP must be greater than 0")
        if volume_value < 0:
            raise ValueError("PRE7 volume must be 0 or greater")

        with self._lock:
            recorder = self._recorder
            if recorder is None:
                raise RuntimeError("no recording session is active")
            recorder.set_pre7_seed(
                normalized,
                vwap=vwap_value,
                volume=volume_value,
            )
            self._analysis_symbols.add(normalized)

        self.session.add_symbol(normalized, make_active=False)
        engine = self._ensure_symbol_analysis(normalized)
        bars, end_ms = self._load_history(normalized)
        seeded = engine.seed_intraday_from_bars(
            normalized,
            bars,
            end_ms=end_ms,
            pre7_vwap=vwap_value,
            pre7_volume=volume_value,
        )
        if seeded is not None:
            self.session.update_ae_snapshot(normalized, seeded)
            self.session.set_vwap_points(normalized, engine.vwap_points)

        self._ensure_stream()
        self._refresh_stream_subscription()
        state = recorder.state()
        self.session.update_recorder_state(state)
        return state

    def remove_recording_symbol(self, symbol: str) -> dict[str, Any]:
        normalized = self.session.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")
        with self._lock:
            recorder = self._recorder
            if recorder is None:
                raise RuntimeError("no recording session is active")
            recorder.remove_symbol(normalized)
            self._recording_symbols = set(recorder.active_symbols())
            stream = self._stream
            active_symbol = self._active_symbol
        with self._lock:
            still_analyzed = normalized in self._analysis_symbols
        if stream is not None and not still_analyzed:
            try:
                stream.unsubscribe(normalized)
            except Exception:
                logger.warning("Recording symbol unsubscribe failed for %s", normalized, exc_info=True)
        self._refresh_stream_subscription()
        state = recorder.state()
        self.session.update_recorder_state(state)
        return state

    def stop_recording(self, *, reason: str = "stopped") -> dict[str, Any]:
        with self._lock:
            recorder = self._recorder
            self._recorder = None
            self._recording_symbols = set()
        if recorder is None:
            state = {"active": False}
            self.session.update_recorder_state(state)
            return state

        try:
            recorder.close(stop_reason=reason)
        finally:
            state = recorder.state()
            state["active"] = False
            state["stop_reason"] = reason
            self.session.update_recorder_state(state)
            self._refresh_stream_subscription()
        return state

    def _handle_raw_payload(self, payload: dict) -> None:
        with self._lock:
            recorder = self._recorder
        if recorder is None:
            return
        try:
            recorder.record_payload(payload)
            now = time.monotonic()
            if now - self._last_recorder_state_emit >= 5.0:
                self._last_recorder_state_emit = now
                self.session.update_recorder_state(recorder.state())
        except RuntimeError:
            pass
        except Exception:
            logger.warning("Raw market recording failed", exc_info=True)

    def _on_auth_state(self, state: str) -> None:
        self.session.update_connection_state(state)

    def _on_llm_state(self, state: str) -> None:
        logger.warning("LLM state: %s", state)

    def session_mode(self, now_et: datetime | None = None) -> str:
        current = now_et or datetime.now(self._et_tz)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self._et_tz)
        else:
            current = current.astimezone(self._et_tz)
        tod = current.time()
        if dtime(hour=9, minute=30) <= tod < dtime(hour=16):
            return "RTH"
        if dtime(hour=4) <= tod < dtime(hour=9, minute=30):
            return "PRE"
        if dtime(hour=16) <= tod <= dtime(hour=20):
            return "POST"
        return "CLOSED"

    def is_intraday_window(self) -> bool:
        now_et = datetime.now(self._et_tz)
        if now_et.weekday() >= 5:
            return False
        return self.session_mode(now_et) != "CLOSED"

    def readiness(self) -> dict[str, Any]:
        auth = self.auth_status()
        return {
            "ok": True,
            "auth_owner": "companion_auth",
            "companion_auth_authorized": bool(auth.get("authorized")),
            "companion_auth_helper_configured": bool(auth.get("helper_url_configured")),
            "llm_configured": self._llm_client.is_available(),
            "llm_provider": "codex_cli_bridge",
            "llm_socket": str(self._llm_client.socket_path),
            "db_path": str(self.db_path),
            "recordings_root": str(Path.home() / ".tos_companion" / "recordings"),
            "session_mode": self.session_mode(),
        }
