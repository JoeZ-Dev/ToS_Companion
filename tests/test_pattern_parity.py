import json

from momentum_companion.evaluation.pattern_parity import (
    build_pattern_parity_report,
    compare_pattern_transitions,
    reconstruct_pattern_transitions,
)
from momentum_companion.recording.provenance import deterministic_fingerprint
from momentum_companion.replay.engine import ReplayEngine


def _snapshot(state="VALID", resistance=10.0):
    return {
        "state": state,
        "evidence": {"resistance": resistance},
        "geometry": {"points": [], "lines": []},
    }


def test_reconstruction_uses_live_dedup_contract_and_observation_time():
    valid = _snapshot()
    breakout = _snapshot(state="BREAKOUT")
    timeline = [
        {
            "bar_ts": 100,
            "observation_ts_ms": 110_000,
            "symbol": "AEHL",
            "pattern": {
                "id": "p1",
                "symbol": "AEHL",
                "pattern_type": "ASCENDING_TRIANGLE",
                "state": valid["state"],
                "updated_at": 100,
                "evidence": valid["evidence"],
                "points": [],
                "lines": [],
            },
        },
        {
            "bar_ts": 110,
            "observation_ts_ms": 120_000,
            "symbol": "AEHL",
            "pattern": {
                "id": "p1",
                "symbol": "AEHL",
                "pattern_type": "ASCENDING_TRIANGLE",
                "state": valid["state"],
                "updated_at": 110,
                "evidence": valid["evidence"],
                "points": [],
                "lines": [],
            },
        },
        {
            "bar_ts": 120,
            "observation_ts_ms": 130_000,
            "symbol": "AEHL",
            "pattern": {
                "id": "p1",
                "symbol": "AEHL",
                "pattern_type": "ASCENDING_TRIANGLE",
                "state": breakout["state"],
                "updated_at": 120,
                "evidence": breakout["evidence"],
                "points": [],
                "lines": [],
            },
        },
    ]

    transitions = reconstruct_pattern_transitions(timeline, session_id="session")

    assert len(transitions) == 2
    assert transitions[0]["observation_ts_ms"] == 110_000
    assert transitions[0]["evaluated_bar_ts_ms"] == 100_000
    assert transitions[1]["state"] == "BREAKOUT"


def test_comparison_reports_live_and_replay_differences_explicitly():
    snapshot = _snapshot()
    fingerprint = deterministic_fingerprint(snapshot)
    live = [{
        "pattern_id": "p1",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": "VALID",
        "observation_ts_ms": 110_000,
        "evaluated_bar_ts_ms": 100_000,
        "snapshot_fingerprint": fingerprint,
    }]
    replay = [
        dict(live[0]),
        {
            **live[0],
            "pattern_id": "p2",
            "pattern_type": "LOCAL_RESISTANCE_BREAKOUT",
        },
    ]

    comparison = compare_pattern_transitions(live, replay)

    assert comparison["matched_count"] == 1
    assert comparison["live_only_count"] == 0
    assert comparison["replay_only_count"] == 1
    assert comparison["has_differences"] is True
    assert comparison["replay_only"][0]["pattern_id"] == "p2"


def test_comparison_normalizes_legacy_bar_start_observation_timestamps():
    snapshot = _snapshot()
    fingerprint = deterministic_fingerprint(snapshot)
    live = [{
        "pattern_id": "p1",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": "VALID",
        "observation_ts_ms": 100_000,
        "snapshot_fingerprint": fingerprint,
    }]
    replay = [{
        **live[0],
        "observation_ts_ms": 110_000,
        "evaluated_bar_ts_ms": 100_000,
    }]

    comparison = compare_pattern_transitions(live, replay)

    assert comparison["has_differences"] is False
    assert comparison["timestamp_contract"] == "legacy_evaluated_bar_timestamp"


def test_legacy_session_without_live_journal_reports_unavailable(tmp_path):
    session = tmp_path / "legacy"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"kind": "market_day_recording", "symbols": ["AEHL"]})
    )

    report = build_pattern_parity_report(tmp_path, "legacy")

    assert report["detector_provenance"]["status"] == "unknown"
    assert report["summary"]["symbols_without_live_journal"] == 1
    assert report["symbols"][0]["status"] == "live_journal_unavailable"


def test_report_replays_recording_and_matches_persisted_transitions(tmp_path):
    base = 1_800_000_000_000
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"kind": "market_day_recording", "symbols": ["AEHL"]})
    )
    prices = [10.0, 10.0, 10.0, 10.0, 10.0, 10.5, 10.6]
    rows = []
    for index, price in enumerate(prices):
        raw = {"key": "AEHL", "3": price, "8": 1000 + index * 100}
        if index == 0:
            raw.update({"1": 9.99, "2": 10.01})
        rows.append(
            {
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": "AEHL",
                "stream_ts_ms": base + index * 10_000,
                "raw": raw,
            }
        )
    (session / "AEHL.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )

    replay = ReplayEngine(recordings_root=tmp_path)
    loaded = replay.load("session", "AEHL")
    replay.seek(loaded["total_events"])
    transitions = reconstruct_pattern_transitions(
        replay.pattern_timeline,
        session_id="session",
    )
    assert transitions
    (session / "pattern_events.jsonl").write_text(
        "".join(
            json.dumps({"kind": "pattern_event", **event}) + "\n"
            for event in transitions
        )
    )

    report = build_pattern_parity_report(tmp_path, "session")

    assert report["summary"]["comparable_symbol_count"] == 1
    assert report["summary"]["matching_symbol_count"] == 1
    assert report["summary"]["live_only_transition_count"] == 0
    assert report["summary"]["replay_only_transition_count"] == 0
