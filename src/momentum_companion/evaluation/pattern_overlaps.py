from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from momentum_companion.recording.provenance import deterministic_fingerprint
from momentum_companion.replay.catalog import RecordingCatalog


OVERLAP_SCHEMA_VERSION = 1
OVERLAP_FILENAME = "pattern_overlaps.json"
DEFAULT_LEVEL_TOLERANCE_PCT = 1.0
TRIGGER_STATES = frozenset({"BREAKOUT", "CONTINUATION"})
UTC = timezone.utc


def build_pattern_overlaps(
    recordings_root: Path,
    session_id: str,
    *,
    symbol: str | None = None,
    level_tolerance_pct: float = DEFAULT_LEVEL_TOLERANCE_PCT,
) -> dict[str, Any]:
    """Derive conservative cross-detector coexistence from journal evidence."""

    tolerance = float(level_tolerance_pct)
    if tolerance < 0:
        raise ValueError("level_tolerance_pct must be non-negative")
    catalog = RecordingCatalog(Path(recordings_root))
    manifest = catalog.load_manifest(session_id)
    requested_symbol = str(symbol or "").strip().upper() or None
    symbols = {
        str(value).strip().upper()
        for value in manifest.get("symbols") or []
        if str(value).strip()
    }
    if requested_symbol is not None and requested_symbol not in symbols:
        raise ValueError(f"{requested_symbol} is not recorded in session {session_id}")

    cadence = (
        (manifest.get("provenance") or {})
        .get("pattern_evaluation", {})
        .get("bar_cadence_seconds")
    )
    cadence_seconds = _positive_int(cadence)
    cadence_ms = cadence_seconds * 1000 if cadence_seconds is not None else 0
    events = catalog.load_pattern_events(session_id, symbol=requested_symbol)
    instances = pattern_instances(events, cadence_ms=cadence_ms)

    overlaps: list[dict[str, Any]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in instances:
        by_symbol[instance["symbol"]].append(instance)
    for current_symbol in sorted(by_symbol):
        ordered = sorted(
            by_symbol[current_symbol],
            key=lambda item: (item["observed_start_ts_ms"], item["pattern_id"]),
        )
        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                if first["pattern_type"] == second["pattern_type"]:
                    continue
                overlap = _overlap_record(
                    session_id,
                    first,
                    second,
                    level_tolerance_pct=tolerance,
                )
                if overlap is not None:
                    overlaps.append(overlap)

    overlaps.sort(
        key=lambda item: (
            item["symbol"],
            item["overlap_start_ts_ms"],
            item["overlap_id"],
        )
    )
    return {
        "schema_version": OVERLAP_SCHEMA_VERSION,
        "kind": "pattern_overlap_analysis",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "session_id": session_id,
        "symbol_filter": requested_symbol,
        "level_tolerance_pct": tolerance,
        "pattern_evaluation_cadence_seconds": cadence_seconds,
        "lifetime_contract": {
            "start": "first_journal_observation",
            "end": (
                "first_explicit_invalidation_or_last_journal_observation_plus_one_"
                "known_evaluation_cadence"
            ),
            "interval": (
                "start inclusive and end exclusive; exact simultaneous journal "
                "observations are retained as zero-duration overlaps"
            ),
            "unknown_cadence": "no extension beyond the last journal observation",
            "interpretation": "conservative observed lifetime; no persistence inferred after it",
        },
        "overlaps": overlaps,
        "summary": _summarize(overlaps),
    }


def write_pattern_overlaps(
    recordings_root: Path,
    session_id: str,
    *,
    level_tolerance_pct: float = DEFAULT_LEVEL_TOLERANCE_PCT,
) -> dict[str, Any]:
    report = build_pattern_overlaps(
        recordings_root,
        session_id,
        level_tolerance_pct=level_tolerance_pct,
    )
    path = Path(recordings_root) / session_id / OVERLAP_FILENAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return report


def pattern_instances(
    events: Iterable[dict[str, Any]], *, cadence_ms: int
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        symbol = str(event.get("symbol") or "").strip().upper()
        pattern_id = str(event.get("pattern_id") or "").strip()
        if symbol and pattern_id and event.get("observation_ts_ms") is not None:
            grouped[(symbol, pattern_id)].append(event)

    instances: list[dict[str, Any]] = []
    for (symbol, pattern_id), rows in grouped.items():
        ordered = sorted(
            rows,
            key=lambda item: (
                int(item["observation_ts_ms"]),
                str(item.get("event_id") or ""),
            ),
        )
        invalidations = [
            int(item["observation_ts_ms"])
            for item in ordered
            if str(item.get("state") or "").upper() == "INVALIDATED"
        ]
        last_observation = int(ordered[-1]["observation_ts_ms"])
        if invalidations:
            observed_end = min(invalidations)
            end_basis = "first_explicit_invalidation"
        else:
            observed_end = last_observation + cadence_ms
            end_basis = (
                "last_observation_plus_evaluation_cadence"
                if cadence_ms
                else "last_observation_unknown_cadence"
            )
        trigger_times = [
            {
                "state": str(item.get("state") or "").upper(),
                "timestamp_ms": int(item["observation_ts_ms"]),
            }
            for item in ordered
            if str(item.get("state") or "").upper() in TRIGGER_STATES
        ]
        starts = [
            int(item["pattern_start_ts_ms"])
            for item in ordered
            if item.get("pattern_start_ts_ms") is not None
        ]
        instances.append(
            {
                "symbol": symbol,
                "pattern_id": pattern_id,
                "pattern_type": str(ordered[0].get("pattern_type") or ""),
                "formation_start_ts_ms": min(starts) if starts else None,
                "observed_start_ts_ms": int(ordered[0]["observation_ts_ms"]),
                "observed_end_ts_ms": observed_end,
                "observed_end_basis": end_basis,
                "trigger_times": trigger_times,
                "events": ordered,
            }
        )
    return instances


def _overlap_record(
    session_id: str,
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    level_tolerance_pct: float,
) -> dict[str, Any] | None:
    overlap_start = max(
        int(first["observed_start_ts_ms"]),
        int(second["observed_start_ts_ms"]),
    )
    overlap_end = min(
        int(first["observed_end_ts_ms"]),
        int(second["observed_end_ts_ms"]),
    )
    simultaneous_observations = {
        int(event["observation_ts_ms"]) for event in first["events"]
    } & {
        int(event["observation_ts_ms"]) for event in second["events"]
    }
    if overlap_start > overlap_end or (
        overlap_start == overlap_end and overlap_start not in simultaneous_observations
    ):
        return None

    ordered = sorted([first, second], key=lambda item: item["pattern_id"])
    participants = [_participant(item) for item in ordered]
    trigger_collisions: list[dict[str, Any]] = []
    for source, other in ((ordered[0], ordered[1]), (ordered[1], ordered[0])):
        for trigger in source["trigger_times"]:
            timestamp = int(trigger["timestamp_ms"])
            if _inside_observed_lifetime(other, timestamp):
                trigger_collisions.append(
                    {
                        "triggering_pattern_id": source["pattern_id"],
                        "triggering_pattern_type": source["pattern_type"],
                        "trigger_state": trigger["state"],
                        "trigger_ts_ms": timestamp,
                        "inside_pattern_id": other["pattern_id"],
                        "inside_pattern_type": other["pattern_type"],
                    }
                )

    first_event = _event_at(ordered[0]["events"], overlap_start)
    second_event = _event_at(ordered[1]["events"], overlap_start)
    level_comparison = _compare_levels(
        _structural_levels(first_event),
        _structural_levels(second_event),
        tolerance_pct=level_tolerance_pct,
    )
    identity = {
        "session_id": session_id,
        "symbol": first["symbol"],
        "pattern_ids": [item["pattern_id"] for item in ordered],
        "overlap_start_ts_ms": overlap_start,
        "overlap_end_ts_ms": overlap_end,
    }
    return {
        "overlap_id": deterministic_fingerprint(identity),
        "session_id": session_id,
        "symbol": first["symbol"],
        "pattern_ids": [item["pattern_id"] for item in ordered],
        "pattern_types": [item["pattern_type"] for item in ordered],
        "participants": participants,
        "overlap_start_ts_ms": overlap_start,
        "overlap_end_ts_ms": overlap_end,
        "overlap_duration_ms": max(0, overlap_end - overlap_start),
        "trigger_collisions": trigger_collisions,
        "one_trigger_inside_other_lifetime": bool(trigger_collisions),
        "structural_level_comparison": level_comparison,
    }


def _participant(instance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pattern_id": instance["pattern_id"],
        "pattern_type": instance["pattern_type"],
        "formation_start_ts_ms": instance["formation_start_ts_ms"],
        "observed_start_ts_ms": instance["observed_start_ts_ms"],
        "observed_end_ts_ms": instance["observed_end_ts_ms"],
        "observed_end_basis": instance["observed_end_basis"],
        "trigger_times": list(instance["trigger_times"]),
    }


def _inside_observed_lifetime(instance: Mapping[str, Any], timestamp_ms: int) -> bool:
    if int(instance["observed_start_ts_ms"]) <= timestamp_ms < int(
        instance["observed_end_ts_ms"]
    ):
        return True
    return any(
        int(event.get("observation_ts_ms") or 0) == timestamp_ms
        and str(event.get("state") or "").upper() != "INVALIDATED"
        for event in instance["events"]
    )


def _event_at(events: list[dict[str, Any]], timestamp_ms: int) -> dict[str, Any]:
    eligible = [
        event
        for event in events
        if int(event.get("observation_ts_ms") or 0) <= timestamp_ms
    ]
    return eligible[-1] if eligible else events[0]


def _structural_levels(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    evidence = event.get("evidence") or {}
    if isinstance(evidence, Mapping):
        for key, value in evidence.items():
            label = str(key).lower()
            if not _is_level_label(label):
                continue
            number = _finite_float(value)
            if number is not None:
                levels.append(
                    {"label": f"evidence.{key}", "price": number}
                )

    geometry = event.get("geometry") or {}
    if isinstance(geometry, Mapping):
        for point in geometry.get("points") or []:
            if isinstance(point, Mapping):
                number = _finite_float(point.get("price"))
                if number is not None:
                    levels.append(
                        {
                            "label": f"geometry.point.{point.get('role') or 'unknown'}",
                            "price": number,
                        }
                    )
        for line in geometry.get("lines") or []:
            if not isinstance(line, Mapping):
                continue
            for endpoint_name in ("start", "end"):
                endpoint = line.get(endpoint_name)
                if not isinstance(endpoint, Mapping):
                    continue
                number = _finite_float(endpoint.get("price"))
                if number is not None:
                    levels.append(
                        {
                            "label": (
                                f"geometry.line.{line.get('role') or 'unknown'}."
                                f"{endpoint_name}"
                            ),
                            "price": number,
                        }
                    )
    return _deduplicate_levels(levels)


def _is_level_label(label: str) -> bool:
    if label in {"resistance", "support", "recovery_pivot"}:
        return True
    return label.endswith(("_level", "_high", "_low")) and not label.endswith(
        ("_pct", "_time")
    )


def _deduplicate_levels(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, float]] = set()
    result: list[dict[str, Any]] = []
    for level in levels:
        key = (level["label"], level["price"])
        if key not in seen:
            seen.add(key)
            result.append(level)
    return result


def _compare_levels(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    *,
    tolerance_pct: float,
) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    for first_level in first:
        for second_level in second:
            distance = _level_distance_pct(first_level["price"], second_level["price"])
            comparisons.append(
                {
                    "first": first_level,
                    "second": second_level,
                    "distance_pct": distance,
                    "shared": math.isclose(
                        first_level["price"], second_level["price"], rel_tol=1e-9
                    ),
                    "nearby": distance <= tolerance_pct,
                }
            )
    comparisons.sort(key=lambda item: item["distance_pct"])
    return {
        "tolerance_pct": tolerance_pct,
        "first_levels": first,
        "second_levels": second,
        "closest_pair": comparisons[0] if comparisons else None,
        "nearby_pairs": [item for item in comparisons if item["nearby"]],
    }


def _level_distance_pct(first: float, second: float) -> float:
    midpoint = (abs(first) + abs(second)) / 2.0
    if midpoint == 0:
        return 0.0 if first == second else math.inf
    return abs(first - second) / midpoint * 100.0


def _summarize(overlaps: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for overlap in overlaps:
        pair = tuple(sorted(overlap["pattern_types"]))
        item = pairs.setdefault(
            pair,
            {
                "pattern_types": list(pair),
                "overlap_count": 0,
                "trigger_collision_count": 0,
                "nearby_level_overlap_count": 0,
                "total_observed_overlap_ms": 0,
            },
        )
        item["overlap_count"] += 1
        item["trigger_collision_count"] += len(overlap["trigger_collisions"])
        item["nearby_level_overlap_count"] += int(
            bool(overlap["structural_level_comparison"]["nearby_pairs"])
        )
        item["total_observed_overlap_ms"] += overlap["overlap_duration_ms"]
    return {
        "total_overlaps": len(overlaps),
        "overlaps_with_trigger_collision": sum(
            bool(item["trigger_collisions"]) for item in overlaps
        ),
        "overlaps_with_nearby_levels": sum(
            bool(item["structural_level_comparison"]["nearby_pairs"])
            for item in overlaps
        ),
        "pattern_type_pairs": [pairs[key] for key in sorted(pairs)],
    }


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
