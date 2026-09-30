import copy

import pytest

from momentum_companion.evaluation.opportunity_review import (
    _assert_blinded_record,
    _blinded_record,
    _deterministic_triggered_sample,
    _encode_pdf,
    _encode_png,
    _render_chart,
    group_production_cooldown_opportunities,
)


def _source(tmp_path):
    return {
        "source_key": "replay:session",
        "root": tmp_path,
        "source_mode": "replay_current_code",
        "status_evidence": "unavailable",
        "context_completeness": "partial",
        "session_id": "session",
        "trading_date": "2026-09-23",
        "started_at_et": "2026-09-23T09:30:00-04:00",
    }


def _candidate(timestamp, status, pattern="TIGHT_CONSOLIDATION_BREAKOUT"):
    pattern_id = f"TEST:{pattern}:{timestamp // 1000}"
    return {
        "symbol": "TEST",
        "trigger_ts_ms": timestamp,
        "evaluated_bar_ts_ms": timestamp - 1_000,
        "reference_price": 10.0,
        "pattern_types": [pattern],
        "contributors": [
            {
                "pattern_id": pattern_id,
                "pattern_type": pattern,
                "trigger_state": "BREAKOUT",
                "trigger_ts_ms": timestamp,
                "evaluated_bar_ts_ms": timestamp - 1_000,
                "stop_level": 9.8,
                "stop_basis": "detector_evidence.breakdown_level",
            }
        ],
        "status": status,
        "reason": None,
        "simulation": {"realized_r": -1.0} if status == "SIMULATED" else None,
    }


def test_production_cooldown_grouping_attaches_suppressed_candidates(tmp_path):
    candidates = [
        _candidate(100_000, "SIMULATED"),
        _candidate(130_000, "SKIPPED_COOLDOWN", "MICRO_PULLBACK"),
        _candidate(150_000, "SKIPPED_COOLDOWN"),
        _candidate(300_000, "SKIPPED_NO_STOP", "ASCENDING_TRIANGLE"),
    ]
    events = [
        {
            "kind": "pattern_event",
            "event_id": str(index),
            "pattern_id": candidate["contributors"][0]["pattern_id"],
            "state": "BREAKOUT",
            "observation_ts_ms": candidate["trigger_ts_ms"],
        }
        for index, candidate in enumerate(candidates)
    ]

    groups = group_production_cooldown_opportunities(
        _source(tmp_path), candidates, events
    )

    assert len(groups) == 2
    assert groups[0]["raw_candidate_count"] == 3
    assert groups[0]["repeated_candidate_count"] == 2
    assert groups[0]["trigger_transition_count"] == 3
    assert groups[0]["simulated_trade_count"] == 1
    assert groups[1]["raw_candidate_count"] == 1
    assert groups[1]["repeated_candidate_count"] == 0


def test_blinded_record_discards_future_bars_and_outcome_fields():
    review_ts = 1_790_170_800_000
    item = {
        "review_id": "TRG-test",
        "kind": "triggered",
        "trading_date": "2026-09-23",
        "session_id": "session",
        "symbol": "TEST",
        "review_ts_ms": review_ts,
        "started_at_et": "2026-09-23T09:30:00-04:00",
        "source_mode": "replay_current_code",
        "status_evidence": "unavailable",
        "context_completeness": "partial",
    }
    packet = {
        "bars_10s": [
            {
                "ts": review_ts // 1000 - 10,
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 100,
                "mfe_pct": 999,
            },
            {
                "ts": review_ts // 1000 + 10,
                "open": 10.1,
                "high": 99.0,
                "low": 1.0,
                "close": 50.0,
                "volume": 1_000,
            },
        ],
        "vwap_points": [
            {"time": review_ts // 1000, "value": 10.05},
            {"time": review_ts // 1000 + 10, "value": 50.0},
        ],
        "end_state": {
            "quote": {"bid": 10.0, "ask": 10.1, "last": 10.05},
            "pattern_observations": [
                {"pattern_type": "TIGHT_CONSOLIDATION_BREAKOUT"}
            ],
            "ae_snapshot": {"exit_reason": "STOP", "realized_r": -1},
        },
        "data_quality": {"evidence_tier": "L1"},
        "window": {"availability": {}},
    }

    blinded = _blinded_record(item, packet, 20 * 60 * 1000)

    assert len(blinded["bars_10s"]) == 1
    assert blinded["bars_10s"][0]["ts"] * 1000 <= review_ts
    assert len(blinded["vwap_points"]) == 1
    rendered = str(blinded)
    assert "TIGHT_CONSOLIDATION_BREAKOUT" not in rendered
    assert "realized_r" not in rendered
    assert "exit_reason" not in rendered
    assert "mfe_pct" not in rendered
    _assert_blinded_record(blinded)


def test_blinded_guard_rejects_future_or_outcome_content():
    base = {
        "review_ts_ms": 100_000,
        "future_data_included": False,
        "bars_10s": [{"ts": 100, "open": 1}],
    }
    future = copy.deepcopy(base)
    future["bars_10s"].append({"ts": 101, "open": 2})
    with pytest.raises(ValueError, match="future bar"):
        _assert_blinded_record(future)

    outcome = copy.deepcopy(base)
    outcome["realized_r"] = 2.0
    with pytest.raises(ValueError, match="forbidden blinded field"):
        _assert_blinded_record(outcome)


def test_sampling_and_rendering_are_deterministic_and_ignore_outcomes(tmp_path):
    opportunities = []
    for index in range(8):
        candidate = _candidate(100_000 + index * 200_000, "SIMULATED")
        candidate["simulation"] = {"realized_r": float(index)}
        groups = group_production_cooldown_opportunities(
            _source(tmp_path), [candidate], []
        )
        groups[0]["opportunity_id"] = f"OPP-{index}"
        opportunities.extend(groups)

    first = _deterministic_triggered_sample(opportunities, count=4, seed="seed")
    altered = copy.deepcopy(opportunities)
    for group in altered:
        group["candidates"][0]["outcome_reference"] = {
            "realized_r": -999.0,
            "mfe_pct": 999.0,
        }
    second = _deterministic_triggered_sample(altered, count=4, seed="seed")
    assert [item["opportunity_id"] for item in first] == [
        item["opportunity_id"] for item in second
    ]

    record = {
        "review_id": "TRG-test",
        "trading_date": "2026-09-23",
        "symbol": "TEST",
        "review_time_et": "2026-09-23T10:00:00-04:00",
        "review_ts_ms": 200_000,
        "context_start_ms": 100_000,
        "source_mode": "replay_current_code",
        "current_quote": {"bid": 10.0, "ask": 10.1, "spread": 0.1},
        "bars_10s": [
            {
                "ts": 100,
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 100,
            }
        ],
        "vwap_points": [{"time": 100, "value": 10.05}],
    }
    canvas_a = _render_chart(record)
    canvas_b = _render_chart(record)
    assert _encode_png(canvas_a) == _encode_png(canvas_b)
    assert _encode_pdf([{"record": record, "canvas": canvas_a}]) == _encode_pdf(
        [{"record": record, "canvas": canvas_b}]
    )
