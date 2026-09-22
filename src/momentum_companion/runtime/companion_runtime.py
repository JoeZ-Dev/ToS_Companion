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
from momentum_companion.llm.client import LLMClient
from momentum_companion.llm.coach import LLMCoach
from momentum_companion.llm.service import LLMService
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
        setattr(self.token_provider, "rest_client", self.rest)

        self.llm_coach = LLMCoach()
        api_key = os.getenv("OPENAI_API_KEY") or self.app_state.get_secret("openai_api_key")
        llm_client = (
            LLMClient(
                api_key=api_key,
                model=self.app_state.get("llm_full_model") or "gpt-4o",
                mode=os.getenv("LLM_MODE", "live"),
            )
            if api_key
            else None
        )
        self.llm_service = LLMService(
            self.llm_coach,
            client=llm_client,
            journal=self.journal,
            state_callback=self._on_llm_state,
        )

        self._aggregator = BarAggregator10s()
        self._stream: SchwabStreamClient | None = None
        self._active_symbol: str | None = None
        self._pending_symbol: str | None = None
        self._lock = threading.RLock()
        self._et_tz = ZoneInfo("America/New_York")
        self._started = False
        self._recorder: MarketDayRecorder | None = None
        self._recording_symbols: set[str] = set()
        self._recorder_cutoff_thread: threading.Thread | None = None

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
        self.session.update_connection_state("READY")

    def stop(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._started = False
        self.stop_recording(reason="runtime_stopped")
        if stream is not None:
            try:
                stream.disconnect()
            except Exception:
                logger.warning("Failed to disconnect Schwab stream", exc_info=True)
        self.session.update_connection_state("DISCONNECTED")

    def select_symbol(self, symbol: str) -> dict[str, Any]:
        """Select a symbol, seed history/AE state, and subscribe live data."""
        normalized = self.session.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("symbol is required")

        with self._lock:
            prior = self._active_symbol
            self._active_symbol = normalized
            self._pending_symbol = normalized
            self._aggregator = BarAggregator10s()
            self.pattern_service.reset(normalized)

        self.session.add_symbol(normalized, make_active=True)
        if prior and prior != normalized and self._stream is not None:
            try:
                self._stream.unsubscribe(prior)
            except Exception:
                logger.debug("Previous symbol unsubscribe failed", exc_info=True)

        self.ae_engine.reset_intraday()
        self._load_history(normalized)
        try:
            self.ae_engine.compute_profile(normalized)
            seeded = self.ae_engine.seed_intraday_from_history(normalized)
            if seeded:
                self.session.update_ae_snapshot(normalized, seeded)
        except Exception:
            logger.warning("AE seed failed for %s", normalized, exc_info=True)

        self._ensure_stream()
        self._refresh_stream_subscription()

        return self.session.snapshot()

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
        if getattr(self.llm_service, "_client", None) is None:
            raise ValueError(
                "OpenAI API key is not configured on the joelab service"
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
            model_override=self.app_state.get("llm_full_model") or "gpt-4o",
            messages_override=messages,
        )
        self.session.update_llm_output(selected, result)
        return result

    def _load_history(self, symbol: str) -> None:
        try:
            now_et = datetime.now(self._et_tz)
            start_et = datetime(
                now_et.year,
                now_et.month,
                now_et.day,
                4,
                0,
                tzinfo=self._et_tz,
            )
            # Before 4 AM ET, fall back to a one-hour window rather than
            # constructing an invalid future start.
            if now_et < start_et:
                start_et = now_et.replace(minute=0, second=0, microsecond=0)
                start_et = start_et.replace(hour=max(0, start_et.hour - 1))
            start_ms = int(start_et.timestamp() * 1000)
            now_ms = int(now_et.timestamp() * 1000)
            response = self.rest.fetch_price_history(symbol, start_ms, now_ms, "1m")
            candles = response.get("candles") or []
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
            ]
            self.session.set_history(symbol, bars)
        except Exception:
            logger.warning("History load failed for %s", symbol, exc_info=True)
            self.session.set_history(symbol, [])

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
            if symbol != self._active_symbol:
                # Current aggregator remains single-active-symbol for parity
                # with the desktop app. Session state itself is multi-symbol.
                return
            completed = self._aggregator.ingest_price(update)

        self.ae_engine.record_quote_ts(int(ts_ms))
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
            snapshot = self.ae_engine.ingest_10s_bar(bar)
            if snapshot:
                self.session.update_ae_snapshot(symbol, snapshot)
        except Exception:
            logger.warning("AE live ingest failed for %s", symbol, exc_info=True)

    def _on_stream_state(self, state: str) -> None:
        self.session.update_connection_state(state)

    def _desired_stream_symbols(self) -> list[str]:
        with self._lock:
            symbols = set(self._recording_symbols)
            if self._active_symbol:
                symbols.add(self._active_symbol)
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
        if not normalized:
            raise ValueError("at least one recording symbol is required")

        with self._lock:
            if self._recorder is not None:
                raise RuntimeError("a recording session is already active")
            recorder = MarketDayRecorder(normalized)
            self._recorder = recorder
            self._recording_symbols = set(recorder.symbols)

        self._ensure_stream()
        self._refresh_stream_subscription()
        self.session.update_recorder_state(
            {
                "active": True,
                "symbols": recorder.symbols,
                "session_dir": str(recorder.session_dir),
                "cutoff_et": "15:00:00",
            }
        )

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
            state = {
                "active": False,
                "symbols": recorder.symbols,
                "session_dir": str(recorder.session_dir),
                "stop_reason": reason,
            }
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
            "llm_configured": getattr(self.llm_service, "_client", None) is not None,
            "db_path": str(self.db_path),
            "recordings_root": str(Path.home() / ".tos_companion" / "recordings"),
            "session_mode": self.session_mode(),
        }
