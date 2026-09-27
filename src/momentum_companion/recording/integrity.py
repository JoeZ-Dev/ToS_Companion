from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from momentum_companion.recording.provenance import normalize_manifest_provenance

INTEGRITY_REPORT_SCHEMA_VERSION = 1
INTEGRITY_REPORT_FILENAME = "integrity_report.json"
SIGNIFICANT_GAP_MS = 60_000
UTC = timezone.utc


def build_integrity_report(session_dir: Path) -> dict[str, Any]:
    """Build a read-only quality report from canonical and derived artifacts."""
    session_dir = Path(session_dir)
    try:
        manifest = json.loads(
            (session_dir / "manifest.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise ValueError(f"recording manifest missing: {session_dir.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid recording manifest: {session_dir.name}") from exc
    if manifest.get("kind") != "market_day_recording":
        raise ValueError(f"invalid recording session: {session_dir.name}")

    provenance_state = _provenance_completeness(
        normalize_manifest_provenance(manifest)
    )
    pattern_events = _load_derived_events(
        session_dir / "pattern_events.jsonl", kind="pattern_event"
    )
    status_events = _load_derived_events(
        session_dir / "security_status_events.jsonl", kind="security_status_event"
    )
    symbols = [
        str(value).strip().upper()
        for value in manifest.get("symbols") or []
        if str(value).strip()
    ]
    reports: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        reports[symbol] = _symbol_report(
            session_dir,
            symbol,
            manifest=manifest,
            pattern_events=[
                event
                for event in pattern_events
                if str(event.get("symbol") or "").strip().upper() == symbol
            ],
            status_events=[
                event
                for event in status_events
                if str(event.get("symbol") or "").strip().upper() == symbol
            ],
            provenance_state=provenance_state,
        )

    totals = {
        "symbols": len(reports),
        "raw_events": sum(item["raw_event_count"] for item in reports.values()),
        "repaired_historical_candles": sum(
            item["repaired_historical_candle_count"] for item in reports.values()
        ),
        "detected_gaps": sum(
            item["gaps"]["detected_count"] for item in reports.values()
        ),
        "repaired_gaps": sum(
            item["gaps"]["repaired_count"] for item in reports.values()
        ),
        "unresolved_gaps": sum(
            item["gaps"]["unresolved_count"] for item in reports.values()
        ),
        "status_events": sum(
            item["status_events"]["count"] for item in reports.values()
        ),
        "halt_status_events": sum(
            item["status_events"]["halt_count"] for item in reports.values()
        ),
        "pattern_events": sum(
            item["pattern_events"]["count"] for item in reports.values()
        ),
    }
    warnings = []
    if not manifest.get("ended_at_et"):
        warnings.append(_warning("recording_active", "Recording has not ended."))
    if not provenance_state["complete"]:
        warnings.append(
            _warning("provenance_incomplete", "Recording provenance is incomplete.")
        )
    if totals["unresolved_gaps"]:
        warnings.append(
            _warning(
                "unresolved_gaps",
                f"{totals['unresolved_gaps']} significant gap(s) remain unresolved.",
            )
        )

    return {
        "schema_version": INTEGRITY_REPORT_SCHEMA_VERSION,
        "kind": "recording_integrity_report",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "session_id": session_dir.name,
        "recording_started_at_et": manifest.get("started_at_et"),
        "recording_ended_at_et": manifest.get("ended_at_et"),
        "gap_threshold_ms": SIGNIFICANT_GAP_MS,
        "provenance": provenance_state,
        "totals": totals,
        "warnings": warnings,
        "symbols": reports,
    }


def write_integrity_report(session_dir: Path) -> dict[str, Any]:
    report = build_integrity_report(session_dir)
    path = Path(session_dir) / INTEGRITY_REPORT_FILENAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return report


def _symbol_report(
    session_dir: Path,
    symbol: str,
    *,
    manifest: Mapping[str, Any],
    pattern_events: list[dict[str, Any]],
    status_events: list[dict[str, Any]],
    provenance_state: dict[str, Any],
) -> dict[str, Any]:
    rows, malformed_rows, missing_file = _load_rows(session_dir / f"{symbol}.jsonl")
    raw_rows = [row for row in rows if row.get("kind") == "market_event"]
    level_one_rows = [
        row for row in raw_rows if row.get("service") == "LEVELONE_EQUITIES"
    ]
    repair_rows = [row for row in rows if row.get("kind") == "historical_candle"]
    raw_timestamps = sorted(
        {
            int(row["stream_ts_ms"])
            for row in level_one_rows
            if _is_int_like(row.get("stream_ts_ms"))
        }
    )
    repair_timestamps = {
        int(row["stream_ts_ms"])
        for row in repair_rows
        if _is_int_like(row.get("stream_ts_ms"))
    }
    gaps = _gaps(raw_timestamps, repair_timestamps)
    pattern_counts = Counter(
        str(event.get("pattern_type") or "UNKNOWN") for event in pattern_events
    )
    state_counts = Counter(
        str(event.get("state") or "UNKNOWN") for event in pattern_events
    )
    status_counts = Counter(
        str(event.get("provider_status") or "UNKNOWN") for event in status_events
    )
    halt_count = sum(
        1
        for event in status_events
        if str(event.get("provider_status") or "").strip().lower()
        in {"halted", "suspended"}
    )

    warnings: list[dict[str, str]] = []
    if missing_file:
        warnings.append(_warning("recording_file_missing", f"{symbol} raw file is missing."))
    elif not raw_rows:
        warnings.append(_warning("no_raw_events", f"{symbol} has no raw market events."))
    if malformed_rows:
        warnings.append(
            _warning(
                "malformed_rows",
                f"{symbol} contains {malformed_rows} malformed JSONL row(s).",
            )
        )
    if gaps["unresolved_count"]:
        warnings.append(
            _warning(
                "unresolved_gaps",
                f"{symbol} has {gaps['unresolved_count']} unresolved significant gap(s).",
            )
        )
    if repair_rows:
        warnings.append(
            _warning(
                "repaired_candles_present",
                "One-minute historical candles supplement raw L1 evidence.",
            )
        )
    if not provenance_state["complete"]:
        warnings.append(_warning("provenance_incomplete", "Provenance is incomplete."))
    artifacts = manifest.get("derived_artifacts")
    if not isinstance(artifacts, Mapping) or "pattern_events" not in artifacts:
        warnings.append(
            _warning("pattern_journal_unavailable", "Live pattern journal is unavailable.")
        )
    if not isinstance(artifacts, Mapping) or "security_status_events" not in artifacts:
        warnings.append(
            _warning("status_history_unavailable", "Explicit status history is unavailable.")
        )

    return {
        "first_timestamp_ms": raw_timestamps[0] if raw_timestamps else None,
        "last_timestamp_ms": raw_timestamps[-1] if raw_timestamps else None,
        "raw_event_count": len(raw_rows),
        "level_one_event_count": len(level_one_rows),
        "repaired_historical_candle_count": len(repair_rows),
        "malformed_row_count": malformed_rows,
        "gaps": gaps,
        "status_events": {
            "count": len(status_events),
            "halt_count": halt_count,
            "by_status": dict(sorted(status_counts.items())),
        },
        "pattern_events": {
            "count": len(pattern_events),
            "by_detector": dict(sorted(pattern_counts.items())),
            "by_state": dict(sorted(state_counts.items())),
        },
        "provenance_complete": provenance_state["complete"],
        "replay_confidence_warnings": warnings,
    }


def _load_rows(path: Path) -> tuple[list[dict[str, Any]], int, bool]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    malformed += 1
    except FileNotFoundError:
        return [], 0, True
    return rows, malformed, False


def _load_derived_events(path: Path, *, kind: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("kind") == kind:
                    events.append(event)
    except FileNotFoundError:
        pass
    return events


def _gaps(raw_timestamps: list[int], repair_timestamps: set[int]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    for previous, current in zip(raw_timestamps, raw_timestamps[1:]):
        duration = current - previous
        if duration <= SIGNIFICANT_GAP_MS:
            continue
        expected: list[int] = []
        minute = (previous // 60_000) * 60_000 + 60_000
        while minute < current:
            expected.append(minute)
            minute += 60_000
        repaired = sorted(set(expected) & repair_timestamps)
        fully_repaired = bool(expected) and len(repaired) == len(expected)
        details.append(
            {
                "after_ms": previous,
                "before_ms": current,
                "duration_ms": duration,
                "expected_repair_minutes": len(expected),
                "repaired_minutes": len(repaired),
                "fully_repaired": fully_repaired,
            }
        )
    return {
        "detected_count": len(details),
        "repaired_count": sum(1 for gap in details if gap["fully_repaired"]),
        "unresolved_count": sum(1 for gap in details if not gap["fully_repaired"]),
        "maximum_duration_ms": max(
            (int(gap["duration_ms"]) for gap in details), default=0
        ),
        "details": details,
    }


def _provenance_completeness(provenance: Mapping[str, Any]) -> dict[str, Any]:
    required_paths = [
        ("application", "git_revision"),
        ("detectors", "enabled"),
        ("detectors", "inventory_fingerprint"),
        ("schemas", "manifest"),
        ("schemas", "market_event"),
        ("schemas", "derived_journal"),
        ("pattern_evaluation", "bar_cadence_seconds"),
        ("session", "timezone"),
        ("session", "premarket_start_et"),
        ("session", "regular_market_open_et"),
        ("session", "regular_market_close_et"),
        ("session", "after_hours_end_et"),
        ("session", "recording_cutoff_et"),
        ("source_mode",),
    ]
    missing = []
    for path in required_paths:
        value: Any = provenance
        for key in path:
            value = value.get(key) if isinstance(value, Mapping) else None
        if value is None or value == []:
            missing.append(".".join(path))
    detectors = provenance.get("detectors")
    enabled = detectors.get("enabled") if isinstance(detectors, Mapping) else None
    if isinstance(enabled, list):
        for index, detector in enumerate(enabled):
            prefix = f"detectors.enabled[{index}]"
            if not isinstance(detector, Mapping):
                missing.append(prefix)
                continue
            for field in ("name", "config", "config_fingerprint"):
                if detector.get(field) is None:
                    missing.append(f"{prefix}.{field}")
            if (
                detector.get("name") == "MICRO_PULLBACK"
                and detector.get("semantic_revision") is None
            ):
                missing.append(f"{prefix}.semantic_revision")
    return {"complete": not missing, "missing_fields": missing}


def _is_int_like(value: Any) -> bool:
    try:
        int(value)
        return value is not None
    except (TypeError, ValueError):
        return False


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
