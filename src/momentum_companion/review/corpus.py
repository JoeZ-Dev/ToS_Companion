from __future__ import annotations

from pathlib import Path
from typing import Any

from momentum_companion.replay.engine import ReplayEngine

MAX_WINDOW_MS = 45 * 60 * 1000
DEFAULT_WINDOW_MS = 20 * 60 * 1000


class ReviewCorpus:
    """Read-only, future-safe access to recording evidence for model review."""

    def __init__(self, recordings_root: Path) -> None:
        self.recordings_root = Path(recordings_root)

    def list_recordings(self) -> list[dict[str, Any]]:
        engine = ReplayEngine(recordings_root=self.recordings_root)
        return engine.catalog.list_sessions()

    def window(
        self,
        session_id: str,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict[str, Any]:
        engine = ReplayEngine(recordings_root=self.recordings_root)
        replay = engine.load(session_id, symbol)
        total = int(replay.get("total_events") or 0)
        if total == 0:
            return self._packet(engine, start_ms=start_ms, end_ms=end_ms)

        first_ms = int(engine._events[0]["stream_ts_ms"])
        last_ms = int(engine._events[-1]["stream_ts_ms"])
        if start_ms is not None and end_ms is not None:
            if int(start_ms) > int(end_ms):
                raise ValueError("start_ms must be <= end_ms")
            if int(end_ms) - int(start_ms) > MAX_WINDOW_MS:
                raise ValueError("review window may not exceed 45 minutes")
        resolved_end = last_ms if end_ms is None else int(end_ms)
        resolved_end = max(first_ms, min(resolved_end, last_ms))
        resolved_start = (
            max(first_ms, resolved_end - DEFAULT_WINDOW_MS)
            if start_ms is None
            else int(start_ms)
        )
        if resolved_start > resolved_end:
            raise ValueError("start_ms must be <= end_ms")
        if resolved_end - resolved_start > MAX_WINDOW_MS:
            raise ValueError("review window may not exceed 45 minutes")

        engine.seek(engine.cursor_for_timestamp(resolved_end))
        return self._packet(engine, start_ms=resolved_start, end_ms=resolved_end)

    def verification_window(
        self,
        session_id: str,
        symbol: str,
        *,
        trigger_ms: int,
        lookback_ms: int = 10 * 60 * 1000,
    ) -> dict[str, Any]:
        """Return evidence ending exactly at the proposed trigger, never after it."""
        if lookback_ms <= 0 or lookback_ms > MAX_WINDOW_MS:
            raise ValueError("lookback_ms must be between 1 and 2700000")
        return self.window(
            session_id,
            symbol,
            start_ms=int(trigger_ms) - int(lookback_ms),
            end_ms=int(trigger_ms),
        )

    @staticmethod
    def _packet(
        engine: ReplayEngine,
        *,
        start_ms: int | None,
        end_ms: int | None,
    ) -> dict[str, Any]:
        snapshot = engine.snapshot()
        replay = snapshot["replay"]
        symbol = replay.get("symbol")
        symbol_state = (snapshot.get("session", {}).get("symbols", {}) or {}).get(symbol, {}) if symbol else {}

        bars = [
            dict(bar)
            for bar in symbol_state.get("bars_10s") or []
            if start_ms is None or int(bar.get("ts", 0)) * 1000 >= int(start_ms)
            if end_ms is None or int(bar.get("ts", 0)) * 1000 <= int(end_ms)
        ]
        vwap = [
            dict(point)
            for point in symbol_state.get("vwap_points") or []
            if start_ms is None or int(point.get("time", 0)) * 1000 >= int(start_ms)
            if end_ms is None or int(point.get("time", 0)) * 1000 <= int(end_ms)
        ]

        return {
            "schema_version": 1,
            "purpose": "momentum_setup_review",
            "session_id": replay.get("session_id"),
            "symbol": symbol,
            "window": {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "future_data_included": False,
            },
            "bars_10s": bars,
            "vwap_points": vwap,
            "end_state": {
                "quote": dict(symbol_state.get("quote") or {}),
                "ae_snapshot": symbol_state.get("ae_snapshot"),
                "pattern_observations": [
                    dict(item) for item in symbol_state.get("pattern_observations") or []
                ],
                "market_context": dict(symbol_state.get("market_context") or {}),
            },
            "data_quality": replay.get("data_quality") or {},
            "replay": {
                "cursor": replay.get("cursor"),
                "total_events": replay.get("total_events"),
                "current_ts_ms": replay.get("current_ts_ms"),
            },
        }
