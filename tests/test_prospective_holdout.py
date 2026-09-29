from __future__ import annotations

from dataclasses import asdict

import pytest

from momentum_companion.evaluation.counterfactual_execution import (
    CounterfactualConfig,
    _paired_policy_report,
)
from momentum_companion.evaluation.prospective_holdout import (
    LOCKED_CUTOFF_DATE,
    _success_assessment,
    holdout_readiness,
    select_holdout_sessions,
    validate_cutoff,
    write_holdout_outputs,
)
from momentum_companion.evaluation.trade_simulation import TradeSimulationPolicy


def _session(session_id: str, day: str) -> dict:
    return {
        "session_id": session_id,
        "started_at_et": f"{day}T09:00:00-04:00",
        "symbols": ["XYZ"],
    }


def test_pre_cutoff_captures_are_explicitly_excluded() -> None:
    eligible, excluded = select_holdout_sessions(
        [
            _session("before", "2026-09-28"),
            _session("cutoff", "2026-09-29"),
            _session("after", "2026-09-30"),
        ],
        cutoff_date=LOCKED_CUTOFF_DATE,
    )

    assert [item["session_id"] for item in eligible] == ["after"]
    assert [(item["session_id"], item["reason"]) for item in excluded] == [
        ("before", "on_or_before_locked_cutoff"),
        ("cutoff", "on_or_before_locked_cutoff"),
    ]


def test_cutoff_has_no_silent_default_and_cannot_move() -> None:
    with pytest.raises(ValueError, match="required and has no default"):
        validate_cutoff(None)
    with pytest.raises(ValueError, match="locked at 2026-09-29"):
        validate_cutoff("2026-09-28")
    assert validate_cutoff("2026-09-29") == "2026-09-29"


def test_paired_decomposition_reconciles_aggregate_policy_difference() -> None:
    def result(value: float | None) -> dict:
        if value is None:
            return {"available": False, "reason": "not_selected", "legs": []}
        return {
            "available": True,
            "reason": None,
            "legs": [{"status": "TRADE", "realized_r": value}],
        }

    values = [(1.0, 0.5), (-1.2, None), (None, 0.8), (-0.5, -0.2)]
    opportunities = [
        {
            "trading_date": "2026-10-01",
            "symbol": f"S{index}",
            "policy_results": {
                "production_baseline": result(baseline),
                "confirmed_detector_stop": result(confirmed),
            },
        }
        for index, (baseline, confirmed) in enumerate(values)
    ]
    paired = _paired_policy_report(opportunities)["overall"]
    baseline_net = sum(value for value, _ in values if value is not None)
    confirmed_net = sum(value for _, value in values if value is not None)

    assert paired["aggregate_net_r_delta_reconciled"] == pytest.approx(
        confirmed_net - baseline_net
    )
    assert paired["aggregate_net_r_delta_reconciled"] == pytest.approx(
        paired["selection_effect_r"]
        + paired["delayed_entry_execution_effect_r"]
    )


def test_frozen_production_and_research_policy_constants_are_unchanged() -> None:
    assert asdict(CounterfactualConfig()) == {
        "confirmation_max_wait_ms": 120_000,
        "retest_max_wait_ms": 180_000,
        "quote_entry_wait_ms": 10_000,
        "retest_tolerance_pct": 0.0015,
        "structural_buffer_pct": 0.0015,
        "swing_lookback_bars": 12,
        "volatility_lookback_bars": 12,
        "volatility_atr_multiplier": 1.5,
        "volatility_risk_cap_pct": 0.08,
        "minimum_risk_pct": 0.001,
        "target_r": 2.0,
        "max_hold_ms": 900_000,
        "reentry_max_wait_ms": 120_000,
        "stop_fill_slippage_bps": 0.0,
        "target_fill_slippage_bps": 0.0,
    }
    production = TradeSimulationPolicy()
    assert (
        production.signal_merge_window_ms,
        production.cooldown_ms,
        production.entry_wait_ms,
        production.max_hold_ms,
        production.target_r,
        production.stop_fill_slippage_bps,
        production.target_fill_slippage_bps,
    ) == (15_000, 120_000, 10_000, 900_000, 2.0, 0.0, 0.0)


def test_minimum_size_requires_dates_opportunities_and_pairs() -> None:
    assert holdout_readiness(
        independent_trading_dates=20, opportunities=500, paired_trades=250
    )["ready_for_locked_assessment"] is True
    assert holdout_readiness(
        independent_trading_dates=19, opportunities=1_000, paired_trades=500
    )["ready_for_locked_assessment"] is False


def test_success_requires_positive_expectancy_and_paired_noninferiority() -> None:
    ready = holdout_readiness(
        independent_trading_dates=20, opportunities=500, paired_trades=250
    )
    policies = {
        "confirmed_detector_stop": {"aggregate": {"net_r": 5.0, "average_r": 0.01}}
    }
    paired = {"overall": {"paired_mean_delta_r": -0.11}}
    result = _success_assessment(policies, paired, ready)
    assert result["confirmed_positive_expectancy"] is True
    assert result["paired_execution_not_materially_degraded"] is False
    assert result["protocol_passed"] is False
    assert result["deployment_approved"] is False


def test_output_trees_are_byte_identical(tmp_path) -> None:
    report = {
        "locked_protocol": {"cutoff_date": "2026-09-29"},
        "minimum_size": {
            "observed_independent_trading_dates": 0,
            "observed_opportunities": 0,
            "observed_paired_trades": 0,
            "ready_for_locked_assessment": False,
        },
        "policy_results": {
            policy: {
                "aggregate": {
                    "trades": 0, "wins": 0, "losses": 0, "timeouts": 0,
                    "net_r": 0.0, "average_r": None,
                }
            }
            for policy in ("production_baseline", "confirmed_detector_stop")
        },
        "paired_selection_and_execution": {
            "overall": {
                "both_policies_traded": 0, "baseline_only": 0,
                "confirmed_only": 0, "neither": 0,
                "selection_effect_r": 0.0,
                "delayed_entry_execution_effect_r": 0.0,
            }
        },
    }
    first, second = tmp_path / "a", tmp_path / "b"
    rows = [{"opportunity_id": "OPP-1", "policy": "production_baseline"}]

    write_holdout_outputs(first, report, rows)
    write_holdout_outputs(second, report, rows)

    first_files = {path.name: path.read_bytes() for path in first.iterdir()}
    second_files = {path.name: path.read_bytes() for path in second.iterdir()}
    assert first_files == second_files
