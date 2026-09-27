import json

import pytest

from momentum_companion.evaluation.pattern_overlaps import build_pattern_overlaps


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _event(
    event_id,
    pattern_id,
    pattern_type,
    state,
    timestamp_ms,
    *,
    level,
):
    return {
        "kind": "pattern_event",
        "event_id": event_id,
        "session_id": "session",
        "symbol": "AEHL",
        "pattern_id": pattern_id,
        "pattern_type": pattern_type,
        "state": state,
        "pattern_start_ts_ms": timestamp_ms - 30_000,
        "observation_ts_ms": timestamp_ms,
        "evidence": {"breakout_level": level},
        "geometry": {"points": [], "lines": []},
    }


def test_overlap_analysis_captures_lifetimes_triggers_and_nearby_levels(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "market_day_recording",
                "symbols": ["AEHL"],
                "provenance": {
                    "pattern_evaluation": {"bar_cadence_seconds": 10}
                },
            }
        )
    )
    _write_jsonl(
        session / "pattern_events.jsonl",
        [
            _event("a1", "a", "ASCENDING_TRIANGLE", "VALID", 100_000, level=10.0),
            _event("b1", "b", "LOCAL_RESISTANCE_BREAKOUT", "VALID", 120_000, level=10.05),
            _event("a2", "a", "ASCENDING_TRIANGLE", "BREAKOUT", 130_000, level=10.0),
            _event("b2", "b", "LOCAL_RESISTANCE_BREAKOUT", "BREAKOUT", 150_000, level=10.05),
        ],
    )

    report = build_pattern_overlaps(tmp_path, "session")
    overlap = report["overlaps"][0]

    assert overlap["overlap_start_ts_ms"] == 120_000
    assert overlap["overlap_end_ts_ms"] == 140_000
    assert overlap["overlap_duration_ms"] == 20_000
    assert overlap["one_trigger_inside_other_lifetime"] is True
    assert overlap["trigger_collisions"] == [
        {
            "triggering_pattern_id": "a",
            "triggering_pattern_type": "ASCENDING_TRIANGLE",
            "trigger_state": "BREAKOUT",
            "trigger_ts_ms": 130_000,
            "inside_pattern_id": "b",
            "inside_pattern_type": "LOCAL_RESISTANCE_BREAKOUT",
        }
    ]
    closest = overlap["structural_level_comparison"]["closest_pair"]
    assert closest["distance_pct"] == pytest.approx(0.498753)
    assert closest["nearby"] is True
    assert report["summary"]["pattern_type_pairs"][0]["overlap_count"] == 1


def test_explicit_invalidation_ends_lifetime_and_same_detector_pairs_are_excluded(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"kind": "market_day_recording", "symbols": ["AEHL"]})
    )
    _write_jsonl(
        session / "pattern_events.jsonl",
        [
            _event("a1", "a", "ASCENDING_TRIANGLE", "VALID", 100_000, level=10.0),
            _event("a2", "a", "ASCENDING_TRIANGLE", "INVALIDATED", 120_000, level=10.0),
            _event("c1", "c", "MICRO_PULLBACK", "PULLBACK", 130_000, level=10.0),
            _event("d1", "d", "MICRO_PULLBACK", "PULLBACK", 130_000, level=10.0),
        ],
    )

    report = build_pattern_overlaps(tmp_path, "session")

    assert report["pattern_evaluation_cadence_seconds"] is None
    assert report["summary"]["total_overlaps"] == 0


def test_overlap_filters_symbol_and_rejects_invalid_requests(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"kind": "market_day_recording", "symbols": ["AEHL"]})
    )

    assert build_pattern_overlaps(tmp_path, "session", symbol="aehl")["overlaps"] == []
    with pytest.raises(ValueError, match="not recorded"):
        build_pattern_overlaps(tmp_path, "session", symbol="OTHER")
    with pytest.raises(ValueError, match="non-negative"):
        build_pattern_overlaps(tmp_path, "session", level_tolerance_pct=-1)
