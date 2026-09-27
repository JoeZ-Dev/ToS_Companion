from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO

from momentum_companion.recording.provenance import (
    DERIVED_JOURNAL_SCHEMA_VERSION,
    deterministic_fingerprint,
)
from momentum_companion.recording.trigger_context import TRIGGER_STATES

UTC = timezone.utc
PATTERN_JOURNAL_FILENAME = "pattern_events.jsonl"


def _as_milliseconds(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value) * 1000
    except (TypeError, ValueError):
        return None


def _detector_provenance(
    pattern_type: str, provenance: Mapping[str, Any]
) -> dict[str, Any]:
    detectors = provenance.get("detectors")
    enabled = detectors.get("enabled") if isinstance(detectors, Mapping) else None
    if isinstance(enabled, list):
        for detector in enabled:
            if not isinstance(detector, Mapping):
                continue
            if str(detector.get("name") or "") == pattern_type:
                return {
                    "name": pattern_type,
                    "config_fingerprint": detector.get("config_fingerprint"),
                    "semantic_revision": detector.get("semantic_revision"),
                }
    return {
        "name": pattern_type,
        "config_fingerprint": None,
        "semantic_revision": None,
    }


def build_pattern_event(
    *,
    session_id: str,
    observation: Mapping[str, Any],
    observation_ts_ms: int,
    provenance: Mapping[str, Any],
    source_mode: str,
    trigger_context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Build one stable journal row and the snapshot key used for deduplication."""
    symbol = str(observation.get("symbol") or "").strip().upper()
    pattern_type = str(observation.get("pattern_type") or "").strip()
    pattern_id = str(observation.get("id") or "").strip()
    started_at_ms = _as_milliseconds(observation.get("started_at"))
    if not pattern_id and symbol and pattern_type and started_at_ms is not None:
        pattern_id = f"{symbol}:{pattern_type}:{started_at_ms // 1000}"
    if not symbol or not pattern_type or not pattern_id:
        raise ValueError("pattern observation requires symbol, pattern_type, and id")

    snapshot = {
        "state": str(observation.get("state") or ""),
        "evidence": observation.get("evidence") or {},
        "geometry": {
            "points": observation.get("points") or [],
            "lines": observation.get("lines") or [],
        },
    }
    snapshot_fingerprint = deterministic_fingerprint(snapshot)
    event_identity = {
        "session_id": session_id,
        "symbol": symbol,
        "pattern_id": pattern_id,
        "observation_ts_ms": int(observation_ts_ms),
        "snapshot_fingerprint": snapshot_fingerprint,
        "source_mode": source_mode,
    }
    event = {
        "schema_version": DERIVED_JOURNAL_SCHEMA_VERSION,
        "kind": "pattern_event",
        "event_id": deterministic_fingerprint(event_identity),
        "session_id": session_id,
        "symbol": symbol,
        "pattern_id": pattern_id,
        "pattern_type": pattern_type,
        "state": snapshot["state"],
        "pattern_start_ts_ms": started_at_ms,
        "observation_ts_ms": int(observation_ts_ms),
        "recorded_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "evidence": snapshot["evidence"],
        "geometry": snapshot["geometry"],
        "detector": _detector_provenance(pattern_type, provenance),
        "source_mode": source_mode,
        "snapshot_fingerprint": snapshot_fingerprint,
    }
    if snapshot["state"].upper() in TRIGGER_STATES:
        event["trigger_context"] = dict(trigger_context or {}) or None
    return event, snapshot_fingerprint


class PatternEventJournal:
    """Append meaningful live pattern observation changes to a derived journal."""

    def __init__(
        self,
        session_dir: Path,
        *,
        provenance: Mapping[str, Any],
        source_mode: str = "live",
    ) -> None:
        self.session_dir = Path(session_dir)
        self.session_id = self.session_dir.name
        self.provenance = provenance
        self.source_mode = source_mode
        self.path = self.session_dir / PATTERN_JOURNAL_FILENAME
        self._handle: TextIO | None = None
        self._last_snapshots: dict[tuple[str, str], str] = {}
        self.count = 0

    def append_observations(
        self,
        observations: Iterable[Mapping[str, Any]],
        *,
        observation_ts_ms: int,
        trigger_context: Mapping[str, Any] | None = None,
    ) -> int:
        appended = 0
        for observation in observations:
            event, snapshot_fingerprint = build_pattern_event(
                session_id=self.session_id,
                observation=observation,
                observation_ts_ms=observation_ts_ms,
                provenance=self.provenance,
                source_mode=self.source_mode,
                trigger_context=trigger_context,
            )
            key = (event["symbol"], event["pattern_id"])
            if self._last_snapshots.get(key) == snapshot_fingerprint:
                continue
            if self._handle is None:
                self._handle = self.path.open("a", encoding="utf-8")
            self._handle.write(json.dumps(event, separators=(",", ":")) + "\n")
            self._handle.flush()
            self._last_snapshots[key] = snapshot_fingerprint
            self.count += 1
            appended += 1
        return appended

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None
