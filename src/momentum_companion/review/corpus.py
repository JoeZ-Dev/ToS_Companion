from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from momentum_companion.replay.engine import ReplayEngine

MAX_WINDOW_MS = 45 * 60 * 1000
DEFAULT_WINDOW_MS = 20 * 60 * 1000
MAX_L1_WINDOW_MS = 2 * 60 * 1000
_NY = ZoneInfo("America/New_York")


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
        requested_end = last_ms if end_ms is None else int(end_ms)
        requested_start = (
            requested_end - DEFAULT_WINDOW_MS
            if start_ms is None
            else int(start_ms)
        )

        if requested_end < first_ms:
            return self._packet(
                engine,
                start_ms=requested_start,
                end_ms=requested_end,
                availability={
                    "status": "before_recording",
                    "first_event_ms": first_ms,
                    "last_event_ms": last_ms,
                    "events_in_window": 0,
                },
            )

        resolved_end = min(requested_end, last_ms)
        resolved_start = max(requested_start, first_ms)
        if resolved_start > resolved_end:
            return self._packet(
                engine,
                start_ms=requested_start,
                end_ms=requested_end,
                availability={
                    "status": "after_recording",
                    "first_event_ms": first_ms,
                    "last_event_ms": last_ms,
                    "events_in_window": 0,
                },
            )
        if resolved_end - resolved_start > MAX_WINDOW_MS:
            raise ValueError("review window may not exceed 45 minutes")

        engine.seek(engine.cursor_for_timestamp(resolved_end))
        events_in_window = sum(
            1
            for event in engine._events
            if resolved_start <= int(event["stream_ts_ms"]) <= resolved_end
        )
        return self._packet(
            engine,
            start_ms=resolved_start,
            end_ms=resolved_end,
            availability={
                "status": "available",
                "first_event_ms": first_ms,
                "last_event_ms": last_ms,
                "events_in_window": events_in_window,
                "requested_start_ms": requested_start,
                "requested_end_ms": requested_end,
            },
        )

    def full_session(
        self,
        session_id: str,
        symbol: str,
    ) -> dict[str, Any]:
        """Return compact causal review data for the entire recorded symbol in one pass."""

        engine = ReplayEngine(recordings_root=self.recordings_root)
        replay = engine.load(session_id, symbol)
        total = int(replay.get("total_events") or 0)
        normalized = str(symbol or "").strip().upper()

        if total == 0:
            return self._packet(engine, start_ms=None, end_ms=None)

        first_ms = int(engine._events[0]["stream_ts_ms"])
        last_ms = int(engine._events[-1]["stream_ts_ms"])

        # One seek to the end reconstructs the complete symbol exactly once.
        engine.seek(total)
        packet = self._packet(
            engine,
            start_ms=first_ms,
            end_ms=last_ms,
            availability={
                "status": "available",
                "first_event_ms": first_ms,
                "last_event_ms": last_ms,
                "events_in_window": total,
                "full_session": True,
            },
        )
        packet["purpose"] = "momentum_full_session_review"
        packet["window"]["full_session"] = True
        return packet

    def l1_window(
        self,
        session_id: str,
        symbol: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> dict[str, Any]:
        """Return carried-forward historical L1 state for a tightly bounded window."""

        requested_start = int(start_ms)
        requested_end = int(end_ms)
        if requested_start > requested_end:
            raise ValueError("start_ms must be <= end_ms")
        if requested_end - requested_start > MAX_L1_WINDOW_MS:
            raise ValueError("L1 review window may not exceed 120 seconds")

        engine = ReplayEngine(recordings_root=self.recordings_root)
        replay = engine.load(session_id, symbol)
        total = int(replay.get("total_events") or 0)
        normalized = str(symbol or "").strip().upper()

        if total == 0:
            return {
                "schema_version": 1,
                "purpose": "historical_l1_review",
                "session_id": session_id,
                "symbol": normalized,
                "window": {
                    "start_ms": requested_start,
                    "end_ms": requested_end,
                    "future_data_included": False,
                    "events_in_window": 0,
                },
                "frames": [],
            }

        events = engine._events
        first_ms = int(events[0]["stream_ts_ms"])
        last_ms = int(events[-1]["stream_ts_ms"])

        resolved_start = max(requested_start, first_ms)
        resolved_end = min(requested_end, last_ms)
        if resolved_start > resolved_end:
            status = "before_recording" if requested_end < first_ms else "after_recording"
            return {
                "schema_version": 1,
                "purpose": "historical_l1_review",
                "session_id": session_id,
                "symbol": normalized,
                "window": {
                    "start_ms": requested_start,
                    "end_ms": requested_end,
                    "future_data_included": False,
                    "availability": {
                        "status": status,
                        "first_event_ms": first_ms,
                        "last_event_ms": last_ms,
                    },
                    "events_in_window": 0,
                },
                "frames": [],
            }

        # Establish the carried-forward quote immediately before the requested
        # window, then advance one immutable recorded event at a time.
        prior_cursor = engine.cursor_for_timestamp(resolved_start - 1)
        engine.seek(prior_cursor)

        frames: list[dict[str, Any]] = []
        cursor = prior_cursor
        while cursor < len(events):
            event = events[cursor]
            event_ms = int(event["stream_ts_ms"])
            if event_ms > resolved_end:
                break

            engine.step(1)
            cursor += 1
            if event_ms < resolved_start:
                continue

            snapshot = engine.snapshot()
            state = (
                snapshot.get("session", {})
                .get("symbols", {})
                .get(normalized, {})
            )
            quote = dict(state.get("quote") or {})
            bid = quote.get("bid")
            ask = quote.get("ask")

            frames.append({
                "timestamp_ms": event_ms,
                "bid": bid,
                "ask": ask,
                "last": quote.get("last"),
                "bid_size": quote.get("bid_size"),
                "ask_size": quote.get("ask_size"),
                "last_size": quote.get("last_size"),
                "volume": quote.get("volume"),
                "spread": (
                    float(ask) - float(bid)
                    if bid is not None and ask is not None
                    else None
                ),
                "source_ts_type": quote.get("source_ts_type"),
                "raw_source": quote.get("raw_source"),
            })

        return {
            "schema_version": 1,
            "purpose": "historical_l1_review",
            "session_id": session_id,
            "symbol": normalized,
            "window": {
                "start_ms": resolved_start,
                "end_ms": resolved_end,
                "requested_start_ms": requested_start,
                "requested_end_ms": requested_end,
                "future_data_included": False,
                "availability": {
                    "status": "available",
                    "first_event_ms": first_ms,
                    "last_event_ms": last_ms,
                },
                "events_in_window": len(frames),
            },
            "frames": frames,
        }

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
    def _review_context(end_ms: int | None) -> dict[str, Any]:
        if end_ms is None:
            return {
                "opening_volatility_context": "unknown",
                "opening_structure_rule": False,
            }
        local = datetime.fromtimestamp(int(end_ms) / 1000.0, tz=_NY)
        minute_of_day = local.hour * 60 + local.minute
        if 9 * 60 + 30 <= minute_of_day < 9 * 60 + 35:
            context = "very_high"
            structure_rule = True
        elif 9 * 60 + 35 <= minute_of_day < 9 * 60 + 45:
            context = "elevated"
            structure_rule = True
        else:
            context = "normal"
            structure_rule = False
        return {
            "opening_volatility_context": context,
            "opening_structure_rule": structure_rule,
            "timestamp_et": local.isoformat(),
        }

    @staticmethod
    def _packet(
        engine: ReplayEngine,
        *,
        start_ms: int | None,
        end_ms: int | None,
        availability: dict[str, Any] | None = None,
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
                "availability": dict(availability or {}),
            },
            "review_context": ReviewCorpus._review_context(end_ms),
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
