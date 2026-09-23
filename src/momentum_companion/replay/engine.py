from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from momentum_companion.analysis.ae import AEEngine
from momentum_companion.clients.stream_mapping import LevelOneCache
from momentum_companion.data.bar_aggregator import BarAggregator10s, TenSecondBar
from momentum_companion.data.price_update import PriceUpdate
from momentum_companion.replay.catalog import RecordingCatalog
from momentum_companion.session import CompanionSession
from momentum_companion.setup_engine.pattern_service import PatternEvaluationService


class ReplayEngine:
    """Deterministic, isolated replay of recorded L1 evidence.

    Replay owns its own session, aggregators, AE, pattern state, and clock.
    It never subscribes to Schwab and never mutates the live CompanionRuntime.
    """

    def __init__(self, *, recordings_root: Path) -> None:
        self.catalog = RecordingCatalog(recordings_root)
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._session_id: str | None = None
        self._symbol: str | None = None
        self._cursor = 0
        self._status = "EMPTY"
        self._current_ts_ms = 0
        self._reset_analysis()

    def _reset_analysis(self) -> None:
        self.session = CompanionSession()
        self._cache = LevelOneCache()
        self._aggregator = BarAggregator10s()
        self.pattern_service = PatternEvaluationService()
        self.ae_engine = AEEngine(
            None,
            None,
            now_ms_provider=lambda: self._current_ts_ms,
        )
        if self._symbol:
            self.session.add_symbol(self._symbol, make_active=True)
            self.pattern_service.reset(self._symbol)
            self.ae_engine.prepare_replay(self._symbol)

    def load(self, session_id: str, symbol: str) -> dict[str, Any]:
        normalized = str(symbol or "").strip().upper()
        events = self.catalog.load_events(session_id, normalized)
        with self._lock:
            self._session_id = session_id
            self._symbol = normalized
            self._events = events
            self._cursor = 0
            self._current_ts_ms = int(events[0]["stream_ts_ms"]) if events else 0
            self._status = "PAUSED" if events else "COMPLETE"
            self._reset_analysis()
            return self._replay_state()

    def step(self, count: int = 1) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("count must be positive")
        with self._lock:
            if self._symbol is None:
                raise RuntimeError("no replay loaded")
            end = min(len(self._events), self._cursor + count)
            while self._cursor < end:
                self._ingest_record(self._events[self._cursor])
                self._cursor += 1
            self._status = "COMPLETE" if self._cursor >= len(self._events) else "PAUSED"
            return self._replay_state()

    def seek(self, cursor: int) -> dict[str, Any]:
        with self._lock:
            if self._symbol is None:
                raise RuntimeError("no replay loaded")
            target = max(0, min(int(cursor), len(self._events)))
            self._cursor = 0
            self._current_ts_ms = (
                int(self._events[0]["stream_ts_ms"]) if self._events else 0
            )
            self._reset_analysis()
            while self._cursor < target:
                self._ingest_record(self._events[self._cursor])
                self._cursor += 1
            self._status = "COMPLETE" if self._cursor >= len(self._events) else "PAUSED"
            return self._replay_state()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "replay": self._replay_state(),
                "session": self.session.snapshot(),
            }

    def _ingest_record(self, record: dict[str, Any]) -> None:
        if self._symbol is None:
            return
        self._current_ts_ms = int(record["stream_ts_ms"])
        message = {
            "service": "LEVELONE_EQUITIES",
            "timestamp": self._current_ts_ms,
            "content": [dict(record["raw"])],
        }
        for quote in self._cache.process_messages(message):
            self.session.ingest_quote(quote)
            last = quote.get("last")
            if last is None:
                continue
            update = PriceUpdate(
                timestamp=int(self._current_ts_ms // 1000),
                price=float(last),
                size=quote.get("volume"),
                source="L1",
            )
            completed = self._aggregator.ingest_price(update)
            self.ae_engine.record_quote_ts(self._current_ts_ms)
            if completed is not None:
                self._handle_completed_bar(completed)

    def _handle_completed_bar(self, bar: TenSecondBar) -> None:
        assert self._symbol is not None
        self.session.ingest_bar(self._symbol, bar)
        patterns = self.pattern_service.ingest_completed_bar(self._symbol, bar)
        self.session.update_pattern_observations(self._symbol, patterns)
        snapshot = self.ae_engine.ingest_10s_bar(bar)
        if snapshot is not None:
            self.session.update_ae_snapshot(self._symbol, snapshot)

    def _replay_state(self) -> dict[str, Any]:
        total = len(self._events)
        current = (
            int(self._events[self._cursor - 1]["stream_ts_ms"])
            if self._cursor > 0
            else (int(self._events[0]["stream_ts_ms"]) if self._events else None)
        )
        return {
            "status": self._status,
            "session_id": self._session_id,
            "symbol": self._symbol,
            "cursor": self._cursor,
            "total_events": total,
            "current_ts_ms": current,
            "progress": (self._cursor / total) if total else 1.0,
        }
