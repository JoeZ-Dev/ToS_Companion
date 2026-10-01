from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from momentum_companion.recording.provenance import (
    deterministic_fingerprint,
    detector_inventory,
)
from momentum_companion.replay.catalog import RecordingCatalog
from momentum_companion.replay.engine import ReplayEngine
from momentum_companion.setup_engine.patterns import build_default_pattern_engine


PARITY_SCHEMA_VERSION = 1


def build_pattern_parity_report(
    recordings_root: Path,
    session_id: str,
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Compare persisted live transitions with current-code replay reconstruction."""

    root = Path(recordings_root)
    catalog = RecordingCatalog(root)
    manifest = catalog.load_manifest(session_id)
    requested_symbol = str(symbol or "").strip().upper() or None
    symbols = [
        str(value).strip().upper()
        for value in manifest.get("symbols") or []
        if str(value).strip()
    ]
    if requested_symbol is not None:
        if requested_symbol not in symbols:
            raise ValueError(f"{requested_symbol} is not recorded in session {session_id}")
        symbols = [requested_symbol]

    provenance = _detector_provenance_comparison(manifest)
    results: list[dict[str, Any]] = []
    for current_symbol in symbols:
        live = catalog.load_pattern_events(session_id, symbol=current_symbol)
        if not live:
            results.append(
                {
                    "symbol": current_symbol,
                    "status": "live_journal_unavailable",
                    "comparison": compare_pattern_transitions([], []),
                    "replay_data_quality": None,
                }
            )
            continue

        replay = ReplayEngine(recordings_root=root)
        loaded = replay.load(session_id, current_symbol)
        completed = replay.seek(int(loaded.get("total_events") or 0))
        reconstructed = reconstruct_pattern_transitions(
            replay.pattern_timeline,
            session_id=session_id,
        )
        comparison = compare_pattern_transitions(live, reconstructed)
        results.append(
            {
                "symbol": current_symbol,
                "status": "match" if not comparison["has_differences"] else "differences",
                "comparison": comparison,
                "replay_data_quality": completed.get("data_quality"),
            }
        )

    comparable = [item for item in results if item["status"] != "live_journal_unavailable"]
    return {
        "schema_version": PARITY_SCHEMA_VERSION,
        "kind": "live_replay_pattern_parity",
        "session_id": session_id,
        "symbol_filter": requested_symbol,
        "comparison_contract": {
            "fields": [
                "pattern_id",
                "pattern_type",
                "state",
                "observation_ts_ms",
                "evaluated_bar_ts_ms",
                "snapshot_fingerprint",
            ],
            "snapshot": "state + evidence + geometry",
            "trigger_context_compared": False,
            "reason": (
                "trigger context includes live-only external context; transition parity "
                "compares deterministic detector output"
            ),
        },
        "detector_provenance": provenance,
        "summary": {
            "symbol_count": len(results),
            "comparable_symbol_count": len(comparable),
            "matching_symbol_count": sum(item["status"] == "match" for item in results),
            "symbols_with_differences": sum(
                item["status"] == "differences" for item in results
            ),
            "symbols_without_live_journal": sum(
                item["status"] == "live_journal_unavailable" for item in results
            ),
            "matched_transition_count": sum(
                item["comparison"]["matched_count"] for item in results
            ),
            "live_only_transition_count": sum(
                item["comparison"]["live_only_count"] for item in results
            ),
            "replay_only_transition_count": sum(
                item["comparison"]["replay_only_count"] for item in results
            ),
        },
        "symbols": results,
    }


def reconstruct_pattern_transitions(
    timeline: Iterable[Mapping[str, Any]],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    """Apply the live journal's meaningful-change deduplication to replay output."""

    last_snapshots: dict[tuple[str, str], str] = {}
    transitions: list[dict[str, Any]] = []
    ordered = sorted(
        timeline,
        key=lambda item: (
            int(item.get("observation_ts_ms") or 0),
            int(item.get("bar_ts") or 0),
        ),
    )
    for row in ordered:
        pattern = row.get("pattern") or {}
        symbol = str(row.get("symbol") or pattern.get("symbol") or "").strip().upper()
        pattern_id = str(pattern.get("id") or "").strip()
        pattern_type = str(pattern.get("pattern_type") or "").strip()
        if not symbol or not pattern_id or not pattern_type:
            continue
        snapshot = {
            "state": str(pattern.get("state") or ""),
            "evidence": pattern.get("evidence") or {},
            "geometry": {
                "points": pattern.get("points") or [],
                "lines": pattern.get("lines") or [],
            },
        }
        fingerprint = deterministic_fingerprint(snapshot)
        key = (symbol, pattern_id)
        if last_snapshots.get(key) == fingerprint:
            continue
        last_snapshots[key] = fingerprint
        evaluated_bar_ts_ms = _seconds_to_ms(pattern.get("updated_at"))
        if evaluated_bar_ts_ms is None and row.get("bar_ts") is not None:
            evaluated_bar_ts_ms = int(row["bar_ts"]) * 1000
        transitions.append(
            {
                "session_id": session_id,
                "symbol": symbol,
                "pattern_id": pattern_id,
                "pattern_type": pattern_type,
                "state": snapshot["state"],
                "observation_ts_ms": int(row.get("observation_ts_ms") or 0),
                "evaluated_bar_ts_ms": evaluated_bar_ts_ms,
                "snapshot_fingerprint": fingerprint,
                "evidence": snapshot["evidence"],
                "geometry": snapshot["geometry"],
                "source_mode": "replay_reconstruction",
            }
        )
    return transitions


def compare_pattern_transitions(
    live_events: Iterable[Mapping[str, Any]],
    replay_events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    live = [_comparison_row(event) for event in live_events]
    replay = [_comparison_row(event) for event in replay_events]
    legacy_bar_timestamps = bool(live) and all(
        row["evaluated_bar_ts_ms"] is None for row in live
    )
    if legacy_bar_timestamps:
        replay = [
            {
                **row,
                "observation_ts_ms": row["evaluated_bar_ts_ms"],
                "evaluated_bar_ts_ms": None,
            }
            for row in replay
        ]
    live_by_signature: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    replay_by_signature: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in live:
        live_by_signature[_signature(row)].append(row)
    for row in replay:
        replay_by_signature[_signature(row)].append(row)

    live_only: list[dict[str, Any]] = []
    replay_only: list[dict[str, Any]] = []
    matched = 0
    for signature in sorted(
        set(live_by_signature) | set(replay_by_signature),
        key=lambda value: tuple(str(item) for item in value),
    ):
        live_rows = live_by_signature.get(signature, [])
        replay_rows = replay_by_signature.get(signature, [])
        shared = min(len(live_rows), len(replay_rows))
        matched += shared
        live_only.extend(live_rows[shared:])
        replay_only.extend(replay_rows[shared:])

    return {
        "live_transition_count": len(live),
        "replay_transition_count": len(replay),
        "matched_count": matched,
        "live_only_count": len(live_only),
        "replay_only_count": len(replay_only),
        "has_differences": bool(live_only or replay_only),
        "timestamp_contract": (
            "legacy_evaluated_bar_timestamp"
            if legacy_bar_timestamps
            else "observation_and_evaluated_bar_timestamps"
        ),
        "live_only": live_only,
        "replay_only": replay_only,
        "live_by_pattern_type": dict(sorted(Counter(row["pattern_type"] for row in live).items())),
        "replay_by_pattern_type": dict(
            sorted(Counter(row["pattern_type"] for row in replay).items())
        ),
    }


def _comparison_row(event: Mapping[str, Any]) -> dict[str, Any]:
    fingerprint = event.get("snapshot_fingerprint")
    if not fingerprint:
        fingerprint = deterministic_fingerprint(
            {
                "state": str(event.get("state") or ""),
                "evidence": event.get("evidence") or {},
                "geometry": event.get("geometry") or {"points": [], "lines": []},
            }
        )
    return {
        "pattern_id": str(event.get("pattern_id") or ""),
        "pattern_type": str(event.get("pattern_type") or ""),
        "state": str(event.get("state") or ""),
        "observation_ts_ms": _int_or_none(event.get("observation_ts_ms")),
        "evaluated_bar_ts_ms": _int_or_none(event.get("evaluated_bar_ts_ms")),
        "snapshot_fingerprint": str(fingerprint),
    }


def _signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["pattern_id"],
        row["pattern_type"],
        row["state"],
        row["observation_ts_ms"],
        row["evaluated_bar_ts_ms"],
        row["snapshot_fingerprint"],
    )


def _detector_provenance_comparison(manifest: Mapping[str, Any]) -> dict[str, Any]:
    recorded = ((manifest.get("provenance") or {}).get("detectors") or {}).get(
        "enabled"
    )
    current = detector_inventory(build_default_pattern_engine())
    if not isinstance(recorded, list):
        return {
            "status": "unknown",
            "recorded": recorded,
            "current": current,
            "differences": [],
        }
    recorded_by_name = {
        str(item.get("name") or ""): item
        for item in recorded
        if isinstance(item, Mapping) and item.get("name")
    }
    current_by_name = {str(item["name"]): item for item in current}
    differences = []
    for name in sorted(set(recorded_by_name) | set(current_by_name)):
        before = recorded_by_name.get(name)
        now = current_by_name.get(name)
        if before is None or now is None or (
            before.get("config_fingerprint") != now.get("config_fingerprint")
            or before.get("semantic_revision") != now.get("semantic_revision")
        ):
            differences.append({"name": name, "recorded": before, "current": now})
    return {
        "status": "match" if not differences else "mismatch",
        "recorded": recorded,
        "current": current,
        "differences": differences,
    }


def _seconds_to_ms(value: Any) -> int | None:
    try:
        return int(value) * 1000 if value is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
