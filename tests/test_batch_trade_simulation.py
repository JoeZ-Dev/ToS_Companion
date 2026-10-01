import json

from momentum_companion.evaluation.batch_trade_simulation import (
    POLICY_NAMES,
    build_batch_trade_simulation,
    deterministic_json,
)


def _write_session(root, session_id, day, symbol):
    session = root / session_id
    session.mkdir(parents=True, exist_ok=True)
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "market_day_recording",
                "symbols": [symbol],
                "started_at_et": f"{day}T09:30:00-04:00",
                "ended_at_et": f"{day}T10:30:00-04:00",
                "stop_reason": "test",
            }
        ),
        encoding="utf-8",
    )
    (session / f"{symbol}.jsonl").write_text(
        json.dumps(
            {
                "kind": "market_event",
                "service": "LEVELONE_EQUITIES",
                "symbol": symbol,
                "stream_ts_ms": 1_000,
                "raw": {"key": symbol, "1": 9.9, "2": 10.0},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _trade(session_id, symbol, realized_r, realized_pct, *, timeout=False):
    policy_results = {}
    for name in POLICY_NAMES:
        policy_results[name] = {
            "name": name,
            "available": True,
            "exit_ts_ms": 2_000,
            "exit_price": 10.0 + realized_pct / 10.0,
            "exit_reason": "TIMEOUT" if timeout else ("TARGET" if realized_r > 0 else "STOP"),
            "realized_pct": realized_pct,
            "realized_r": realized_r,
        }
    return {
        "session_id": session_id,
        "symbol": symbol,
        "trigger_ts_ms": 1_000,
        "entry_ts_ms": 1_000,
        "exit_ts_ms": 2_000,
        "full_path": {
            "complete": True,
            "mfe_pct": 12.0,
            "mae_pct": -3.0,
            "mfe_r": 2.4,
            "mae_r": -0.6,
        },
        "exit_policy_results": policy_results,
    }


def _simulator(_root, session_id, *, policy):
    del policy
    if session_id == "2026-01-01_a":
        trades = [_trade(session_id, "AAA", 2.0, 10.0)]
        candidates = [
            {"symbol": "AAA", "status": "SIMULATED", "reason": None},
            {
                "symbol": "AAA",
                "status": "DATA_QUALITY_BLOCKED",
                "reason": "unresolved_gap",
            },
        ]
    elif session_id == "2026-01-02_b":
        trades = [
            _trade(session_id, "BBB", -1.0, -5.0),
            _trade(session_id, "BBB", -1.0, -5.0, timeout=True),
        ]
        candidates = [
            {"symbol": "BBB", "status": "SIMULATED", "reason": None},
            {"symbol": "BBB", "status": "SIMULATED", "reason": None},
        ]
    else:
        trades = []
        candidates = []
    return {
        "schema_version": 2,
        "kind": "trade_simulation",
        "generated_at_utc": "changes-every-run",
        "session_id": session_id,
        "summary": {
            "candidate_count": len(candidates),
            "simulated_trade_count": len(trades),
        },
        "candidates": candidates,
        "trades": trades,
    }


def _report(tmp_path):
    recordings = tmp_path / "recordings"
    _write_session(recordings, "2026-01-03_c", "2026-01-03", "CCC")
    _write_session(recordings, "2026-01-01_a", "2026-01-01", "AAA")
    _write_session(recordings, "2026-01-02_b", "2026-01-02", "BBB")
    return build_batch_trade_simulation(
        recordings,
        code_revision="a" * 40,
        simulator=_simulator,
    )


def test_batch_enumerates_all_sessions_and_accounts_for_eligibility(tmp_path):
    report = _report(tmp_path)

    assert [
        item["session_id"] for item in report["inventory"]["sessions"]
    ] == ["2026-01-01_a", "2026-01-02_b", "2026-01-03_c"]
    assert report["inventory"]["unique_trading_day_count"] == 3
    assert report["inventory"]["unique_symbol_day_count"] == 3
    assert report["eligibility_summary"] == {
        "eligible_session_count": 2,
        "eligible_complete_session_count": 1,
        "eligible_partial_session_count": 1,
        "ineligible_session_count": 1,
        "eligible_session_ids": ["2026-01-01_a", "2026-01-02_b"],
        "partial_session_ids": ["2026-01-01_a"],
        "ineligible_session_ids": ["2026-01-03_c"],
    }
    assert report["inventory"]["sessions"][2]["eligibility"]["reasons"][0][
        "code"
    ] == "pattern_journal_unavailable"


def test_batch_aggregates_policies_and_independence_weighting(tmp_path):
    report = _report(tmp_path)
    fixed = report["aggregate_results"]["fixed_2r"]

    assert fixed["candidate_count"] == 4
    assert fixed["simulated_trade_count"] == 3
    assert fixed["wins"] == 1
    assert fixed["losses"] == 2
    assert fixed["timeouts"] == 1
    assert fixed["net_r"] == 0.0
    assert fixed["average_r"] == 0.0
    assert fixed["median_r"] == -1.0
    assert fixed["combined_realized_pct"] == 0.0
    assert fixed["complete_full_path_count"] == 3
    assert fixed["incomplete_full_path_count"] == 0

    independence = report["independence"]
    weighting = independence["equal_symbol_day_weighting"]["fixed_2r"]
    concentration = independence["concentration_by_policy"]["fixed_2r"]
    assert weighting["trade_weighted_average_r"] == 0.0
    assert weighting["equal_symbol_day_weighted_average_r"] == 0.5
    assert weighting["average_r_change"] == 0.5
    assert concentration["largest_group_trade_share"] == 2 / 3


def test_batch_output_is_deterministic_and_omits_wall_clock_fields(tmp_path):
    first = _report(tmp_path)
    second = _report(tmp_path)

    assert first == second
    assert deterministic_json(first) == deterministic_json(second)
    assert "changes-every-run" not in deterministic_json(first)
