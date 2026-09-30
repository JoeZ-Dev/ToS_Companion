from __future__ import annotations

from copy import deepcopy
import csv
import json
import math

from momentum_companion.evaluation.counterfactual_execution import (
    CounterfactualConfig,
    _breakout_levels,
    _completed_bars,
    _evaluate_opportunity,
    _find_confirmation,
    _find_retest,
    _interpretation,
    _load_labels,
    _paired_policy_report,
    _policy_report,
    _structural_stop,
    _volatility_stop,
)


def _bar(start: int, *, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "start_ts_ms": start,
        "end_ts_ms": start + 10_000,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "last_observation_ts_ms": start + 9_000,
    }


def _event(*, observed: int = 100_000, level: float = 10.0, support: float = 9.5) -> dict:
    return {
        "pattern_id": "XYZ:LOCAL_RESISTANCE_BREAKOUT:1",
        "pattern_type": "LOCAL_RESISTANCE_BREAKOUT",
        "observation_ts_ms": observed,
        "evidence": {"breakout_level": level, "support": support},
        "geometry": {
            "points": [{"role": "support", "price": support, "time": observed / 1000 - 10}]
        },
    }


def _opportunity() -> dict:
    return {
        "opportunity_id": "OPP-test",
        "session_id": "session",
        "trading_date": "2026-09-23",
        "symbol": "XYZ",
        "review_ts_ms": 100_000,
        "pattern_types": ["LOCAL_RESISTANCE_BREAKOUT"],
        "pattern_status": "single_pattern",
        "time_bucket": "premarket",
        "repeat_bucket": "0",
        "raw_candidate_count": 1,
        "repeated_candidate_count": 0,
        "detector_events": [_event()],
        "candidates": [
            {
                "contributors": [
                    {
                        "pattern_id": "XYZ:LOCAL_RESISTANCE_BREAKOUT:1",
                        "pattern_type": "LOCAL_RESISTANCE_BREAKOUT",
                        "stop_level": 9.5,
                        "stop_basis": "detector_evidence.invalidation_level",
                    }
                ]
            }
        ],
    }


def _data() -> dict:
    quotes = [
        {"ts_ms": 100_001, "bid": 10.00, "ask": 10.02, "last": 10.01},
        {"ts_ms": 110_001, "bid": 10.04, "ask": 10.06, "last": 10.05},
        {"ts_ms": 120_001, "bid": 10.08, "ask": 10.10, "last": 10.09},
        {"ts_ms": 130_001, "bid": 10.40, "ask": 10.42, "last": 10.41},
        {"ts_ms": 140_001, "bid": 11.30, "ask": 11.32, "last": 11.31},
        {"ts_ms": 150_001, "bid": 11.30, "ask": 11.32, "last": 11.31},
        {"ts_ms": 1_000_000, "bid": 11.30, "ask": 11.32, "last": 11.31},
    ]
    return {
        "quotes": quotes,
        "bars": _completed_bars(quotes),
        "status_events": [],
        "integrity": {"last_timestamp_ms": 2_000_000, "gaps": {"details": []}},
    }


def test_completed_bar_confirmation_never_uses_future_bar() -> None:
    bars = [
        _bar(90_000, open_=9.9, high=10.1, low=9.8, close=10.01),
        _bar(100_000, open_=10.0, high=10.2, low=9.9, close=10.10),
    ]
    found = _find_confirmation(bars, 95_000, [{"level": 10.0, "detector": "D"}], 20_000)
    assert found is not None
    assert found["completed_at_ms"] == 100_000
    assert found["completed_at_ms"] <= 95_000 + 20_000
    assert _find_confirmation(bars, 95_000, [{"level": 10.0, "detector": "D"}], 4_999) is None


def test_entry_uses_ask_and_exit_uses_bid() -> None:
    results = _evaluate_opportunity(_opportunity(), _data(), CounterfactualConfig())
    trade = results["production_baseline"]["legs"][0]
    assert trade["entry_price"] == 10.02
    assert trade["entry_bid"] == 10.00
    assert trade["raw_exit_bid"] == trade["exit_price"]


def test_detector_policy_is_explicitly_unavailable_without_stop() -> None:
    opportunity = _opportunity()
    opportunity["candidates"][0]["contributors"][0]["stop_level"] = None
    results = _evaluate_opportunity(opportunity, _data(), CounterfactualConfig())
    assert results["production_baseline"] == {
        "available": False,
        "reason": "no_detector_supported_stop_below_entry",
        "legs": [],
        "combined": None,
    }


def test_structural_stop_uses_only_evidence_available_at_decision() -> None:
    bars = [
        _bar(60_000, open_=9.8, high=9.9, low=9.6, close=9.8),
        _bar(70_000, open_=9.8, high=9.9, low=9.7, close=9.8),
        _bar(80_000, open_=9.8, high=9.9, low=9.65, close=9.85),
        _bar(110_000, open_=10.0, high=10.1, low=8.0, close=10.05),
    ]
    future = _event(observed=130_000, support=9.95)
    result = _structural_stop([_event(support=9.5), future], bars, 100_000, 10.1, CounterfactualConfig())
    assert result is not None
    stop, evidence = result
    assert evidence["as_of_ms"] == 100_000
    assert evidence["evidence_ts_ms"] <= 100_000
    assert stop < 9.5


def test_retest_requires_a_later_completed_hold_bar() -> None:
    confirmation = {"completed_at_ms": 110_000, "level": 10.0}
    bars = [
        _bar(100_000, open_=9.9, high=10.1, low=9.99, close=10.05),
        _bar(110_000, open_=10.05, high=10.1, low=9.995, close=10.02),
    ]
    found = _find_retest(bars, confirmation, CounterfactualConfig())
    assert found is not None
    assert found["completed_at_ms"] == 120_000
    assert found["bar_low"] <= found["level"] * (1 + found["tolerance_pct"])


def test_volatility_stop_uses_preceding_completed_bars_and_fixed_cap() -> None:
    bars = [
        _bar(index * 10_000, open_=10, high=10.1, low=9.9, close=10)
        for index in range(13)
    ]
    cfg = CounterfactualConfig(volatility_lookback_bars=12, volatility_atr_multiplier=1.5)
    result = _volatility_stop(bars, 120_000, 10.0, cfg)
    assert result is not None
    stop, evidence = result
    assert evidence["last_bar_end_ms"] <= 120_000
    assert evidence["multiplier"] == 1.5
    assert math.isclose(stop, 9.7)


def test_one_reentry_is_limited_to_two_legs() -> None:
    opportunity = _opportunity()
    data = _data()
    data["quotes"] = [
        {"ts_ms": 100_001, "bid": 10.0, "ask": 10.02, "last": 10.01},
        {"ts_ms": 110_001, "bid": 10.05, "ask": 10.07, "last": 10.06},
        {"ts_ms": 120_001, "bid": 9.4, "ask": 9.42, "last": 10.06},
        {"ts_ms": 130_001, "bid": 10.1, "ask": 10.12, "last": 10.1},
        {"ts_ms": 140_001, "bid": 9.3, "ask": 9.32, "last": 10.1},
        {"ts_ms": 1_000_000, "bid": 9.3, "ask": 9.32, "last": 9.3},
    ]
    data["bars"] = _completed_bars(data["quotes"])
    results = _evaluate_opportunity(opportunity, data, CounterfactualConfig())
    assert len(results["confirmed_structural_one_reentry"]["legs"]) <= 2


def test_portfolio_counts_opportunity_once_and_detector_views_are_non_additive() -> None:
    opportunity = _opportunity()
    opportunity["pattern_types"] = ["A", "B"]
    opportunity["pattern_status"] = "multi_pattern"
    opportunity["policy_results"] = _evaluate_opportunity(opportunity, _data(), CounterfactualConfig())
    opportunity["detector_policy_results"] = {
        "A": opportunity["policy_results"],
        "B": opportunity["policy_results"],
    }
    report = _policy_report([opportunity], "production_baseline")
    assert report["portfolio"]["opportunities"] == 1
    assert sum(row["opportunities"] for row in report["by"]["detector"]) == 2
    assert all("non-additive" in row["counting_note"] for row in report["by"]["detector"])


def test_breakout_levels_are_stable_and_detector_specific() -> None:
    events = [_event(level=10.1), {**deepcopy(_event(level=10.2)), "pattern_id": "p2", "pattern_type": "MICRO_PULLBACK", "evidence": {"continuation_level": 10.2}}]
    assert [(item["detector"], item["level"]) for item in _breakout_levels(events)] == [
        ("LOCAL_RESISTANCE_BREAKOUT", 10.1),
        ("MICRO_PULLBACK", 10.2),
    ]


def test_locked_label_schema_normalizes_and_excludes_controls(tmp_path) -> None:
    review_ids = [f"CTL-{index:02d}" for index in range(10)] + [
        f"TRG-{index:02d}" for index in range(50)
    ]
    manifest = {"items": [
        {"review_id": review_id, "kind": "control" if review_id.startswith("CTL") else "triggered"}
        for review_id in review_ids
    ]}
    evidence = {
        review_id: (
            {"kind": "control"}
            if review_id.startswith("CTL")
            else {"kind": "triggered", "opportunity_id": f"OPP-{review_id[4:]}"}
        )
        for review_id in review_ids
    }
    manifest_path = tmp_path / "review-manifest.json"
    evidence_path = tmp_path / "machine-evidence.json"
    labels_path = tmp_path / "labels.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    fields = [
        "review_id", "valid_setup", "human_pattern_types", "timing",
        "entry_quality", "stop_structure_visible", "notes",
    ]
    trigger_values = ["yes"] * 9 + ["uncertain"] * 8 + ["no"] * 33
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for review_id in review_ids[:10]:
            writer.writerow({"review_id": review_id, "valid_setup": "no"})
        for review_id, value in zip(review_ids[10:], trigger_values):
            writer.writerow({"review_id": review_id, "valid_setup": value})

    loaded = _load_labels(manifest_path, labels_path)

    assert loaded["loaded_count"] == 60
    assert loaded["control_count"] == 10
    assert loaded["class_counts"] == {"clear": 9, "uncertain": 8, "rejected": 33}
    assert len(loaded["by_opportunity"]) == 50
    assert set(loaded["by_opportunity"].values()) == {"clear", "uncertain", "rejected"}
    assert all(row["opportunity_id"] is None for row in loaded["rows"][:10])


def test_paired_report_separates_selection_from_execution() -> None:
    def result(value: float | None) -> dict:
        if value is None:
            return {"available": False, "reason": "none", "legs": []}
        return {"available": True, "reason": None, "legs": [
            {"status": "TRADE", "realized_r": value}
        ]}

    opportunities = []
    values = [(1.0, 0.5), (-1.0, None), (None, 2.0), (None, None)]
    for index, (baseline, confirmed) in enumerate(values):
        opportunities.append({
            "trading_date": "2026-09-23",
            "symbol": f"S{index}",
            "policy_results": {
                "production_baseline": result(baseline),
                "confirmed_detector_stop": result(confirmed),
            },
        })

    report = _paired_policy_report(opportunities)["overall"]

    assert report["both_policies_traded"] == 1
    assert report["baseline_only"] == 1
    assert report["confirmed_only"] == 1
    assert report["neither"] == 1
    assert report["delayed_entry_execution_effect_r"] == -0.5
    assert report["selection_effect_r"] == 3.0
    assert report["aggregate_net_r_delta_reconciled"] == 2.5
    assert (report["confirmed_better"], report["baseline_better"], report["equal"]) == (0, 1, 0)


def test_interpretation_reports_locked_paired_conclusion() -> None:
    text = _interpretation({
        "paired_production_vs_confirmed_detector_stop": {
            "overall": {
                "both_policies_traded": 518,
                "delayed_entry_execution_effect_r": -12.833764788,
            }
        }
    })
    assert "skipping weak baseline trades" in text
    assert "518 common opportunities" in text
    assert "12.834R worse" in text
    assert "future holdout eligibility hypothesis" in text
    assert "No policy is approved for deployment" in text
