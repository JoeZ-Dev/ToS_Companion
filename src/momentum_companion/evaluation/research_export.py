from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from momentum_companion.evaluation.corpus_classification import (
    CLASSIFICATIONS,
    CorpusClassificationStore,
)
from momentum_companion.evaluation.pattern_outcomes import build_pattern_outcomes
from momentum_companion.evaluation.pattern_overlaps import (
    build_pattern_overlaps,
    pattern_instances,
)
from momentum_companion.recording.integrity import build_integrity_report
from momentum_companion.replay.catalog import RecordingCatalog


RESEARCH_EXPORT_SCHEMA_VERSION = 1


def build_research_export(
    recordings_root: Path,
    *,
    session_id: str | None = None,
    symbol: str | None = None,
    pattern_type: str | None = None,
    corpus_classification: str | None = None,
    has_trigger: bool | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    include_outcomes: bool = False,
) -> dict[str, Any]:
    """Compose read-only pattern research evidence from derived artifacts."""

    root = Path(recordings_root)
    normalized_symbol = str(symbol or "").strip().upper() or None
    normalized_type = str(pattern_type or "").strip().upper() or None
    classification_filter = (
        str(corpus_classification or "").strip().lower() or None
    )
    if classification_filter is not None and classification_filter not in CLASSIFICATIONS:
        raise ValueError(
            "corpus_classification must be unclassified, development, or holdout"
        )
    if start_ms is not None and int(start_ms) < 0:
        raise ValueError("start_ms must be non-negative")
    if end_ms is not None and int(end_ms) < 0:
        raise ValueError("end_ms must be non-negative")
    if start_ms is not None and end_ms is not None and int(start_ms) > int(end_ms):
        raise ValueError("start_ms must be less than or equal to end_ms")

    catalog = RecordingCatalog(root)
    corpus_store = CorpusClassificationStore(root.parent / "corpus_classifications.json")
    available = catalog.list_sessions()
    if session_id is not None:
        manifest = catalog.load_manifest(session_id)
        session_summaries = [
            {
                "session_id": session_id,
                "symbols": manifest.get("symbols") or [],
            }
        ]
    else:
        session_summaries = available

    sessions: list[dict[str, Any]] = []
    pattern_type_counts: Counter[str] = Counter()
    total_status_events = 0
    total_overlaps = 0
    total_outcomes = 0
    for session_summary in session_summaries:
        current_session = str(session_summary["session_id"])
        classification = corpus_store.get(current_session)
        if (
            classification_filter is not None
            and classification["classification"] != classification_filter
        ):
            continue
        manifest = catalog.load_manifest(current_session)
        manifest_symbols = {
            str(value).strip().upper()
            for value in manifest.get("symbols") or []
            if str(value).strip()
        }
        if normalized_symbol is not None and normalized_symbol not in manifest_symbols:
            if session_id is not None:
                raise ValueError(
                    f"{normalized_symbol} is not recorded in session {current_session}"
                )
            continue

        events = catalog.load_pattern_events(
            current_session,
            symbol=normalized_symbol,
        )
        cadence_seconds = _positive_int(
            (manifest.get("provenance") or {})
            .get("pattern_evaluation", {})
            .get("bar_cadence_seconds")
        )
        instances = pattern_instances(
            events,
            cadence_ms=(cadence_seconds or 0) * 1000,
        )
        selected = [
            instance
            for instance in instances
            if _matches_instance(
                instance,
                pattern_type=normalized_type,
                has_trigger=has_trigger,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        ]
        selected_ids = {instance["pattern_id"] for instance in selected}

        status_events = catalog.load_security_status_events(
            current_session,
            symbol=normalized_symbol,
        )
        overlap_report = build_pattern_overlaps(
            root,
            current_session,
            symbol=normalized_symbol,
        )
        overlaps = [
            overlap
            for overlap in overlap_report["overlaps"]
            if selected_ids.intersection(overlap["pattern_ids"])
            and _interval_matches(
                overlap["overlap_start_ts_ms"],
                overlap["overlap_end_ts_ms"],
                start_ms=start_ms,
                end_ms=end_ms,
            )
        ]
        overlap_ids_by_pattern: dict[str, list[str]] = {
            pattern_id: [] for pattern_id in selected_ids
        }
        for overlap in overlaps:
            for pattern_id in overlap["pattern_ids"]:
                if pattern_id in overlap_ids_by_pattern:
                    overlap_ids_by_pattern[pattern_id].append(overlap["overlap_id"])

        patterns = [
            _export_instance(
                instance,
                status_events=status_events,
                overlap_ids=overlap_ids_by_pattern[instance["pattern_id"]],
            )
            for instance in selected
        ]
        filtered_status = [
            event
            for event in status_events
            if _timestamp_matches(
                _status_timestamp(event),
                start_ms=start_ms,
                end_ms=end_ms,
            )
        ]
        integrity = build_integrity_report(root / current_session)
        if normalized_symbol is not None:
            integrity = {
                **integrity,
                "symbols": {
                    normalized_symbol: (integrity.get("symbols") or {}).get(
                        normalized_symbol
                    )
                },
            }

        session_export: dict[str, Any] = {
            "session_id": current_session,
            "corpus": classification,
            "provenance": manifest.get("provenance") or {},
            "integrity": integrity,
            "patterns": patterns,
            "security_status_events": filtered_status,
            "overlaps": overlaps,
        }
        if include_outcomes:
            outcome_report = build_pattern_outcomes(
                root,
                current_session,
                symbol=normalized_symbol,
            )
            session_outcomes = [
                outcome
                for outcome in outcome_report["outcomes"]
                if outcome.get("pattern_id") in selected_ids
            ]
            session_export["outcome_measurements"] = {
                "horizon_ms": outcome_report["horizon_ms"],
                "forward_minutes": outcome_report["forward_minutes"],
                "outcomes": session_outcomes,
            }
            total_outcomes += len(session_outcomes)

        sessions.append(session_export)
        pattern_type_counts.update(item["pattern_type"] for item in patterns)
        total_status_events += len(filtered_status)
        total_overlaps += len(overlaps)

    return {
        "schema_version": RESEARCH_EXPORT_SCHEMA_VERSION,
        "kind": "structured_pattern_research_export",
        "future_data_policy": {
            "blind_review_safe": False,
            "reason": (
                "complete lifecycle journals and overlap records may contain "
                "observations after a trigger"
            ),
            "blind_review_endpoint": "/api/review/verify",
            "outcomes_included": bool(include_outcomes),
            "outcomes_separated": True,
        },
        "filters": {
            "session_id": session_id,
            "symbol": normalized_symbol,
            "pattern_type": normalized_type,
            "corpus_classification": classification_filter,
            "has_trigger": has_trigger,
            "start_ms": int(start_ms) if start_ms is not None else None,
            "end_ms": int(end_ms) if end_ms is not None else None,
            "time_range_semantics": "pattern observed lifetime intersects range",
        },
        "summary": {
            "session_count": len(sessions),
            "pattern_instance_count": sum(
                len(session["patterns"]) for session in sessions
            ),
            "pattern_type_counts": dict(sorted(pattern_type_counts.items())),
            "security_status_event_count": total_status_events,
            "overlap_count": total_overlaps,
            "outcome_count": total_outcomes if include_outcomes else None,
        },
        "sessions": sessions,
    }


def _matches_instance(
    instance: Mapping[str, Any],
    *,
    pattern_type: str | None,
    has_trigger: bool | None,
    start_ms: int | None,
    end_ms: int | None,
) -> bool:
    if pattern_type is not None and instance["pattern_type"] != pattern_type:
        return False
    triggered = bool(instance["trigger_times"])
    if has_trigger is not None and triggered != has_trigger:
        return False
    return _interval_matches(
        instance["observed_start_ts_ms"],
        instance["observed_end_ts_ms"],
        start_ms=start_ms,
        end_ms=end_ms,
    )


def _interval_matches(
    interval_start: int,
    interval_end: int,
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> bool:
    if end_ms is not None and int(interval_start) > int(end_ms):
        return False
    if start_ms is not None and int(interval_end) < int(start_ms):
        return False
    return True


def _timestamp_matches(
    timestamp_ms: int | None,
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> bool:
    if timestamp_ms is None:
        return start_ms is None and end_ms is None
    if start_ms is not None and timestamp_ms < int(start_ms):
        return False
    if end_ms is not None and timestamp_ms > int(end_ms):
        return False
    return True


def _export_instance(
    instance: Mapping[str, Any],
    *,
    status_events: list[dict[str, Any]],
    overlap_ids: list[str],
) -> dict[str, Any]:
    trigger_status = [
        {
            **trigger,
            "latest_explicit_status": _latest_status_at(
                status_events, int(trigger["timestamp_ms"])
            ),
        }
        for trigger in instance["trigger_times"]
    ]
    during_lifetime = [
        event
        for event in status_events
        if _status_timestamp(event) is not None
        and int(instance["observed_start_ts_ms"])
        <= int(_status_timestamp(event))
        <= int(instance["observed_end_ts_ms"])
    ]
    return {
        "pattern_id": instance["pattern_id"],
        "symbol": instance["symbol"],
        "pattern_type": instance["pattern_type"],
        "formation_start_ts_ms": instance["formation_start_ts_ms"],
        "observed_start_ts_ms": instance["observed_start_ts_ms"],
        "observed_end_ts_ms": instance["observed_end_ts_ms"],
        "observed_end_basis": instance["observed_end_basis"],
        "has_trigger": bool(instance["trigger_times"]),
        "trigger_times": list(instance["trigger_times"]),
        "state_transition_journal": list(instance["events"]),
        "status_context": {
            "latest_at_first_observation": _latest_status_at(
                status_events, int(instance["observed_start_ts_ms"])
            ),
            "at_triggers": trigger_status,
            "events_during_observed_lifetime": during_lifetime,
        },
        "overlap_ids": sorted(overlap_ids),
    }


def _latest_status_at(
    events: Iterable[dict[str, Any]], timestamp_ms: int
) -> dict[str, Any] | None:
    eligible = [
        event
        for event in events
        if _status_timestamp(event) is not None
        and int(_status_timestamp(event)) <= timestamp_ms
    ]
    return eligible[-1] if eligible else None


def _status_timestamp(event: Mapping[str, Any]) -> int | None:
    value = event.get("provider_ts_ms")
    if value is None:
        value = event.get("observed_ts_ms")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
