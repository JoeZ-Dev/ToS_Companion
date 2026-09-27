import json

from momentum_companion.evaluation.pattern_outcomes import (
    _measure_trigger,
    build_pattern_outcomes,
)


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_pattern_outcomes_reuses_excursions_and_measures_forward_ladder(tmp_path):
    base = 1_800_000_000_000
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "market_day_recording",
                "symbols": ["AEHL"],
                "ended_at_et": "2026-09-27T10:00:00-04:00",
                "derived_artifacts": {
                    "pattern_events": {"path": "pattern_events.jsonl"},
                    "security_status_events": {
                        "path": "security_status_events.jsonl"
                    },
                },
            }
        )
    )
    raw_rows = []
    for seconds in range(0, 920, 10):
        price = 10.0 + seconds / 1000.0
        raw_rows.append(
            {
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": "AEHL",
                "stream_ts_ms": base + seconds * 1000,
                "raw": {
                    "key": "AEHL",
                    "1": price - 0.01,
                    "2": price + 0.01,
                    "3": price,
                    "8": 1000 + seconds,
                },
            }
        )
    _write_jsonl(session / "AEHL.jsonl", raw_rows)
    _write_jsonl(
        session / "pattern_events.jsonl",
        [
            {
                "kind": "pattern_event",
                "event_id": "forming",
                "session_id": "session",
                "symbol": "AEHL",
                "pattern_id": "AEHL:TIGHT_CONSOLIDATION_BREAKOUT:1",
                "pattern_type": "TIGHT_CONSOLIDATION_BREAKOUT",
                "state": "VALID",
                "observation_ts_ms": base,
                "evidence": {"breakdown_level": 9.5},
                "source_mode": "live",
            },
            {
                "kind": "pattern_event",
                "event_id": "trigger",
                "session_id": "session",
                "symbol": "AEHL",
                "pattern_id": "AEHL:TIGHT_CONSOLIDATION_BREAKOUT:1",
                "pattern_type": "TIGHT_CONSOLIDATION_BREAKOUT",
                "state": "BREAKOUT",
                "observation_ts_ms": base,
                "evidence": {"breakdown_level": 9.5},
                "source_mode": "live",
            },
        ],
    )

    report = build_pattern_outcomes(tmp_path, "session")
    outcome = report["outcomes"][0]

    assert len(report["outcomes"]) == 1
    assert outcome["entry_reference"] == {
        "available": True,
        "price": 10.0,
        "bar_ts_ms": base,
        "basis": "trigger_bar_close",
    }
    assert outcome["excursion"]["mfe_pct"] > 0
    assert outcome["excursion"]["time_to_mfe_ms"] == 900_000
    assert outcome["forward_returns"]["1"]["available"] is True
    assert outcome["forward_returns"]["15"]["observation_ts_ms"] == base + 900_000
    assert outcome["measurement"]["truncated"] is False
    assert outcome["invalidation"]["available"] is True
    assert outcome["invalidation"]["first_breach_ts_ms"] is None


def test_outcome_truncates_at_unresolved_gap_and_explicit_halt_without_fabrication():
    trigger = {
        "session_id": "session",
        "symbol": "AEHL",
        "pattern_id": "p1",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": "BREAKOUT",
        "observation_ts_ms": 100_000,
        "evidence": {},
        "source_mode": "live",
    }
    bars = [
        {"ts": 100, "high": 10.2, "low": 9.9, "close": 10.0},
        {"ts": 110, "high": 10.4, "low": 10.0, "close": 10.3},
        {"ts": 400, "high": 12.0, "low": 8.0, "close": 11.0},
    ]

    outcome = _measure_trigger(
        trigger,
        bars=bars,
        status_events=[
            {"provider_status": "Halted", "provider_ts_ms": 350_000}
        ],
        gaps=[
            {
                "after_ms": 110_000,
                "before_ms": 400_000,
                "fully_repaired": False,
            }
        ],
        recording_last_ms=1_000_000,
        horizon_ms=900_000,
    )

    assert outcome["measurement"]["actual_end_ts_ms"] == 110_000
    assert outcome["measurement"]["truncated_by_unresolved_gap"] is True
    assert outcome["measurement"]["truncated_by_halt"] is True
    assert outcome["forward_returns"]["1"]["available"] is False
    assert outcome["forward_returns"]["1"]["price"] is None


def test_explicit_tight_range_breakdown_level_measures_first_close_breach():
    trigger = {
        "session_id": "session",
        "symbol": "AEHL",
        "pattern_id": "p1",
        "pattern_type": "TIGHT_CONSOLIDATION_BREAKOUT",
        "state": "BREAKOUT",
        "observation_ts_ms": 100_000,
        "evidence": {"breakdown_level": 9.5},
        "source_mode": "live",
    }
    bars = [
        {"ts": 100, "high": 10.1, "low": 9.8, "close": 10.0},
        {"ts": 110, "high": 10.0, "low": 9.2, "close": 9.4},
    ]

    outcome = _measure_trigger(
        trigger,
        bars=bars,
        status_events=[],
        gaps=[],
        recording_last_ms=110_000,
        horizon_ms=900_000,
    )

    assert outcome["invalidation"]["basis"] == "detector_evidence.breakdown_level"
    assert outcome["invalidation"]["first_breach_ts_ms"] == 110_000
    assert outcome["invalidation"]["time_to_invalidation_ms"] == 10_000


def test_trigger_bar_extremes_are_not_counted_as_post_trigger_excursion():
    trigger = {
        "session_id": "session",
        "symbol": "AEHL",
        "pattern_id": "p1",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": "BREAKOUT",
        "observation_ts_ms": 100_000,
        "evidence": {},
        "source_mode": "live",
    }
    bars = [
        {"ts": 100, "high": 20.0, "low": 5.0, "close": 10.0},
        {"ts": 110, "high": 10.5, "low": 9.8, "close": 10.2},
    ]

    outcome = _measure_trigger(
        trigger,
        bars=bars,
        status_events=[],
        gaps=[],
        recording_last_ms=110_000,
        horizon_ms=900_000,
    )

    assert outcome["excursion"]["mfe_price"] == 10.5
    assert outcome["excursion"]["mae_price"] == 9.8


def test_observation_time_uses_completed_bar_reference_without_future_leakage():
    trigger = {
        "session_id": "session",
        "symbol": "AEHL",
        "pattern_id": "p1",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": "BREAKOUT",
        "observation_ts_ms": 110_000,
        "evaluated_bar_ts_ms": 100_000,
        "evidence": {},
        "source_mode": "live",
    }
    bars = [
        {"ts": 100, "high": 20.0, "low": 5.0, "close": 10.0},
        {"ts": 110, "high": 10.5, "low": 9.8, "close": 10.2},
    ]

    outcome = _measure_trigger(
        trigger,
        bars=bars,
        status_events=[],
        gaps=[],
        recording_last_ms=110_000,
        horizon_ms=900_000,
    )

    assert outcome["trigger_ts_ms"] == 110_000
    assert outcome["evaluated_bar_ts_ms"] == 100_000
    assert outcome["entry_reference"] == {
        "available": True,
        "price": 10.0,
        "bar_ts_ms": 100_000,
        "basis": "evaluated_completed_bar_close",
    }
    assert outcome["excursion"]["mfe_price"] == 10.5
    assert outcome["excursion"]["mae_price"] == 9.8
    assert outcome["excursion"]["time_to_mfe_ms"] == 0


def test_missing_evaluated_bar_is_unavailable_instead_of_using_next_bar():
    trigger = {
        "session_id": "session",
        "symbol": "AEHL",
        "pattern_id": "p1",
        "pattern_type": "ASCENDING_TRIANGLE",
        "state": "BREAKOUT",
        "observation_ts_ms": 110_000,
        "evaluated_bar_ts_ms": 100_000,
        "evidence": {},
    }

    outcome = _measure_trigger(
        trigger,
        bars=[{"ts": 110, "high": 10.5, "low": 9.8, "close": 10.2}],
        status_events=[],
        gaps=[],
        recording_last_ms=110_000,
        horizon_ms=900_000,
    )

    assert outcome["entry_reference"]["available"] is False
    assert outcome["entry_reference"]["bar_ts_ms"] is None
    assert outcome["excursion"] is None
