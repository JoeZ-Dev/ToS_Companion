import json

from momentum_companion.evaluation.trade_simulation import (
    TradeSimulationPolicy,
    build_trade_simulation,
)


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _session(tmp_path, *, include_stop=True):
    recordings = tmp_path / "recordings"
    session = recordings / "session"
    session.mkdir(parents=True)
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "kind": "market_day_recording",
                "symbols": ["TEST"],
                "started_at_et": "2026-09-28T09:30:00-04:00",
                "ended_at_et": "2026-09-28T09:40:00-04:00",
                "provenance": {
                    "application": {"git_revision": "a" * 40},
                    "pattern_evaluation": {"bar_cadence_seconds": 10},
                    "schemas": {
                        "manifest": 2,
                        "market_event": 1,
                        "derived_journal": 1,
                    },
                    "session": {"timezone": "America/New_York"},
                    "source_mode": "live",
                },
            }
        )
    )
    rows = [
        {
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TEST",
            "stream_ts_ms": 10_000,
            "raw": {"key": "TEST", "1": 9.95, "2": 10.05, "3": 10.00, "8": 1000},
        },
        {
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TEST",
            "stream_ts_ms": 20_000,
            "raw": {"key": "TEST", "1": 10.00, "2": 10.10, "3": 10.05, "8": 1200},
        },
        {
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TEST",
            "stream_ts_ms": 30_000,
            "raw": {"key": "TEST", "1": 10.55, "2": 10.60, "3": 10.58, "8": 1400},
        },
        {
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TEST",
            "stream_ts_ms": 60_000,
            "raw": {"key": "TEST", "1": 10.50, "2": 10.55, "3": 10.52, "8": 1500},
        },
        {
            "kind": "market_event",
            "service": "LEVELONE_EQUITIES",
            "symbol": "TEST",
            "stream_ts_ms": 130_000,
            "raw": {"key": "TEST", "1": 10.20, "2": 10.25, "3": 10.22, "8": 1600},
        },
    ]
    _write_jsonl(session / "TEST.jsonl", rows)

    stop_evidence = {"breakdown_level": 9.90} if include_stop else {}
    _write_jsonl(
        session / "pattern_events.jsonl",
        [
            {
                "kind": "pattern_event",
                "event_id": "a",
                "session_id": "session",
                "symbol": "TEST",
                "pattern_id": "TEST:TIGHT_CONSOLIDATION_BREAKOUT:1",
                "pattern_type": "TIGHT_CONSOLIDATION_BREAKOUT",
                "state": "BREAKOUT",
                "observation_ts_ms": 20_000,
                "evaluated_bar_ts_ms": 10_000,
                "evidence": {
                    **stop_evidence,
                    "last_close": 10.05,
                },
                "trigger_context": {
                    "price": {"available": True, "value": 10.05}
                },
            },
            {
                "kind": "pattern_event",
                "event_id": "b",
                "session_id": "session",
                "symbol": "TEST",
                "pattern_id": "TEST:LOCAL_RESISTANCE_BREAKOUT:1",
                "pattern_type": "LOCAL_RESISTANCE_BREAKOUT",
                "state": "BREAKOUT",
                "observation_ts_ms": 25_000,
                "evaluated_bar_ts_ms": 10_000,
                "evidence": {"last_close": 10.05},
            },
            {
                "kind": "pattern_event",
                "event_id": "c",
                "session_id": "session",
                "symbol": "TEST",
                "pattern_id": "TEST:TIGHT_CONSOLIDATION_BREAKOUT:2",
                "pattern_type": "TIGHT_CONSOLIDATION_BREAKOUT",
                "state": "BREAKOUT",
                "observation_ts_ms": 60_000,
                "evaluated_bar_ts_ms": 50_000,
                "evidence": {"breakdown_level": 10.00, "last_close": 10.52},
            },
        ],
    )
    return recordings


def test_simulator_merges_colliding_detectors_and_uses_recorded_ask_bid(tmp_path):
    recordings = _session(tmp_path)
    report = build_trade_simulation(
        recordings,
        "session",
        policy=TradeSimulationPolicy(max_hold_ms=100_000),
    )

    assert report["summary"]["candidate_count"] == 2
    assert report["summary"]["simulated_trade_count"] == 1
    assert report["summary"]["candidate_status_counts"] == {
        "SIMULATED": 1,
        "SKIPPED_COOLDOWN": 1,
    }

    first = report["candidates"][0]
    assert first["pattern_types"] == [
        "LOCAL_RESISTANCE_BREAKOUT",
        "TIGHT_CONSOLIDATION_BREAKOUT",
    ]
    trade = report["trades"][0]
    assert trade["entry_ts_ms"] == 20_000
    assert trade["entry_price"] == 10.10
    assert trade["entry_bid"] == 10.00
    assert trade["stop_price"] == 9.90
    assert trade["target_price"] == 10.50
    assert trade["exit_ts_ms"] == 30_000
    assert trade["exit_price"] == 10.55
    assert trade["exit_reason"] == "TARGET"
    assert trade["realized_r"] > 2.0
    assert report["summary"]["wins"] == 1
    assert report["summary"]["losses"] == 0


def test_simulator_keeps_missing_stop_candidate_but_does_not_score_trade(tmp_path):
    recordings = _session(tmp_path, include_stop=False)
    report = build_trade_simulation(
        recordings,
        "session",
        policy=TradeSimulationPolicy(max_hold_ms=100_000),
    )

    assert report["summary"]["simulated_trade_count"] == 1
    assert report["candidates"][0]["status"] == "SKIPPED_NO_STOP"
    # The first no-stop candidate does not consume cooldown; the later supported
    # candidate is still eligible for simulation.
    assert report["candidates"][1]["status"] == "SIMULATED"


def test_simulator_rejects_unknown_symbol(tmp_path):
    recordings = _session(tmp_path)
    try:
        build_trade_simulation(recordings, "session", symbol="NOPE")
    except ValueError as exc:
        assert "not recorded" in str(exc)
    else:
        raise AssertionError("expected ValueError")
