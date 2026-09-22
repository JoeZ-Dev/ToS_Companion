from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time as dtime
from pathlib import Path
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
from momentum_companion.session import CompanionSession
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

        self.token_provider = token_provider or TokenProvider(
            state_callback=self._on_auth_state
        )
        self.rest = rest_client or SchwabRestClient(
            base_url="https://api.schwabapi.com/trader/v1",
            auth_token_provider=self.token_provider,
        )
        self.ae_engine = ae_engine or AEEngine(self.rest, self.db_path)
        setattr(self.token_provider, "rest_client", self.rest)

        self._aggregator = BarAggregator10s()
        self._stream: SchwabStreamClient | None = None
        self._active_symbol: str | None = None
        self._pending_symbol: str | None = None
        self._lock = threading.RLock()
        self._et_tz = ZoneInfo("America/New_York")
        self._started = False

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
        if self._stream is not None and self._stream.is_connected():
            self._stream.subscribe_level_one(normalized)

        return self.session.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return self.session.snapshot()

    def _load_history(self, symbol: str) -> None:
        try:
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - 60 * 60 * 1000
            response = self.rest.fetch_price_history(symbol, start_ms, now_ms, "day")
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
        )
        with self._lock:
            if self._stream is None:
                self._stream = stream
            else:
                return
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
            snapshot = self.ae_engine.ingest_10s_bar(bar)
            if snapshot:
                self.session.update_ae_snapshot(symbol, snapshot)
        except Exception:
            logger.warning("AE live ingest failed for %s", symbol, exc_info=True)

    def _on_stream_state(self, state: str) -> None:
        self.session.update_connection_state(state)
        if state == "CONNECTED":
            symbol = self.active_symbol
            stream = self._stream
            if symbol and stream is not None:
                try:
                    stream.subscribe_level_one(symbol)
                except Exception:
                    logger.warning("Live subscribe failed for %s", symbol, exc_info=True)

    def _on_auth_state(self, state: str) -> None:
        self.session.update_connection_state(state)

    def is_intraday_window(self) -> bool:
        now_et = datetime.now(self._et_tz)
        if now_et.weekday() >= 5:
            return False
        tod = now_et.time()
        return dtime(hour=4) <= tod <= dtime(hour=20)
