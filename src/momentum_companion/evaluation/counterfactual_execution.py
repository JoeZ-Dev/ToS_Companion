from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from momentum_companion.evaluation.batch_trade_simulation import deterministic_json
from momentum_companion.evaluation.opportunity_review import (
    _source_sessions,
    group_production_cooldown_opportunities,
)
from momentum_companion.evaluation.trade_simulation import (
    TradeSimulationPolicy,
    _first_quality_barrier,
    _load_quote_timeline,
    _positive_float,
    build_trade_simulation,
)
from momentum_companion.recording.integrity import build_integrity_report
from momentum_companion.replay.catalog import RecordingCatalog


SCHEMA_VERSION = 1
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
POLICY_ORDER = (
    "production_baseline",
    "confirmed_detector_stop",
    "confirmed_structural_stop",
    "retest_structural_stop",
    "confirmed_volatility_stop",
    "confirmed_structural_one_reentry",
)
LOCKED_PRIOR_FINDINGS = {
    "reviewed_triggers": 50,
    "human_validity_counts": {"clear": 9, "uncertain": 8, "rejected": 33},
    "blinded_controls": 10,
    "simulated_trades": 35,
    "simulated_net_r": -25.35,
    "all_simulations_included_tight_consolidation_breakout": True,
    "all_simulations_used_breakdown_level_stop": True,
    "stopped_then_later_reached_2r": 5,
    "fixed_2r_beat_tested_trailing_policies": True,
    "runner_optimization_paused": True,
}


@dataclass(frozen=True)
class CounterfactualConfig:
    """Locked research constants; this is intentionally not a parameter sweep."""

    confirmation_max_wait_ms: int = 120_000
    retest_max_wait_ms: int = 180_000
    quote_entry_wait_ms: int = 10_000
    retest_tolerance_pct: float = 0.0015
    structural_buffer_pct: float = 0.0015
    swing_lookback_bars: int = 12
    volatility_lookback_bars: int = 12
    volatility_atr_multiplier: float = 1.5
    volatility_risk_cap_pct: float = 0.08
    minimum_risk_pct: float = 0.001
    target_r: float = 2.0
    max_hold_ms: int = 15 * 60 * 1000
    reentry_max_wait_ms: int = 120_000
    stop_fill_slippage_bps: float = 0.0
    target_fill_slippage_bps: float = 0.0

    def validate(self) -> None:
        if self.volatility_atr_multiplier <= 0:
            raise ValueError("volatility_atr_multiplier must be positive")
        if not 0 < self.volatility_risk_cap_pct < 1:
            raise ValueError("volatility_risk_cap_pct must be between zero and one")
        if not 0 <= self.retest_tolerance_pct < 1:
            raise ValueError("retest_tolerance_pct must be between zero and one")
        if self.swing_lookback_bars < 2 or self.volatility_lookback_bars < 2:
            raise ValueError("bar lookbacks must be at least two")


def policy_definitions(config: CounterfactualConfig) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "research_classification": "exploratory_historical_comparison_not_validation",
        "locked_prior_findings": LOCKED_PRIOR_FINDINGS,
        "constants_locked_before_aggregate_inspection": True,
        "constants": asdict(config),
        "shared_execution": {
            "entry_side": "first recorded L1 ask at or after the causal decision",
            "exit_side": "recorded L1 bid",
            "target": "fixed 2R",
            "horizon": "15 minutes from each entry",
            "bar_rule": "10-second bar may be used only after its end timestamp",
            "portfolio_rule": "at most one initial position per cooldown opportunity",
            "slippage": {
                "stop_fill_slippage_bps": config.stop_fill_slippage_bps,
                "target_fill_slippage_bps": config.target_fill_slippage_bps,
            },
        },
        "policies": {
            "production_baseline": {
                "entry": "immediate production trigger entry",
                "stop": "closest existing detector-supported stop below ask",
                "unavailable": "no detector stop or no timely complete quote",
            },
            "confirmed_detector_stop": {
                "entry": "first completed 10-second close at/above contributor level after opportunity start",
                "stop": "closest existing detector-supported stop below ask",
            },
            "confirmed_structural_stop": {
                "entry": "same causal completed-bar confirmation",
                "stop": "lowest explicit formation support, else most recent completed-bar swing low, buffered by detector breakout tolerance",
            },
            "retest_structural_stop": {
                "entry": "after confirmation, first later completed bar touching the breakout tolerance band and closing at/above the level",
                "stop": "causal structural stop as of retest completion",
            },
            "confirmed_volatility_stop": {
                "entry": "same causal completed-bar confirmation",
                "stop": "entry minus 1.5 times median true range of 12 preceding completed 10-second bars, capped at 8% entry risk",
            },
            "confirmed_structural_one_reentry": {
                "entry": "confirmed structural policy; after a stop only, at most one renewed completed-bar confirmation",
                "stop": "structural risk is recomputed from data complete at the re-entry decision",
                "reporting": "initial and re-entry legs are separate plus combined",
            },
        },
    }


def build_counterfactual_research(
    recordings_root: Path,
    replay_overlays_root: Path,
    output_root: Path,
    *,
    code_revision: str,
    review_manifest: Path | None = None,
    labels_csv: Path | None = None,
    config: CounterfactualConfig | None = None,
) -> dict[str, Any]:
    cfg = config or CounterfactualConfig()
    cfg.validate()
    revision = str(code_revision).strip()
    if not revision:
        raise ValueError("code_revision is required")
    recordings = Path(recordings_root)
    overlays = Path(replay_overlays_root)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    sources = _source_sessions(recordings, overlays)
    before = _recording_hashes(recordings, sources)
    labels = _load_labels(review_manifest, labels_csv)

    opportunities: list[dict[str, Any]] = []
    source_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        root = Path(source["root"])
        session_id = source["session_id"]
        catalog = RecordingCatalog(root)
        events = catalog.load_pattern_events(session_id)
        simulation = build_trade_simulation(root, session_id)
        simulation.pop("generated_at_utc", None)
        groups = group_production_cooldown_opportunities(
            source, simulation["candidates"], events
        )
        event_by_id = {
            str(event.get("pattern_id") or ""): event
            for event in events
            if str(event.get("pattern_id") or "")
        }
        integrity = build_integrity_report(root / session_id)
        for group in groups:
            key = (session_id, group["symbol"])
            cached = source_cache.get(key)
            if cached is None:
                quotes = _load_quote_timeline(catalog, session_id, group["symbol"])
                cached = {
                    "quotes": quotes,
                    "bars": _completed_bars(quotes),
                    "status_events": catalog.load_security_status_events(
                        session_id, symbol=group["symbol"]
                    ),
                    "integrity": (integrity.get("symbols") or {}).get(
                        group["symbol"], {}
                    ),
                }
                source_cache[key] = cached
            group["detector_events"] = sorted(
                [
                    event_by_id[pattern_id]
                    for pattern_id in {
                        str(c.get("pattern_id") or "")
                        for candidate in group["candidates"]
                        for c in candidate.get("contributors") or []
                    }
                    if pattern_id in event_by_id
                ],
                key=lambda item: (
                    int(item.get("observation_ts_ms") or 0),
                    str(item.get("pattern_id") or ""),
                ),
            )
            group["time_bucket"] = _time_bucket(group["review_ts_ms"])
            group["repeat_bucket"] = _repeat_bucket(
                group["repeated_candidate_count"]
            )
            group["pattern_status"] = (
                "multi_pattern" if len(group["pattern_types"]) > 1 else "single_pattern"
            )
            group["policy_results"] = _evaluate_opportunity(group, cached, cfg)
            group["detector_policy_results"] = {}
            for detector in group["pattern_types"]:
                isolated = _isolate_detector_opportunity(group, detector)
                if isolated is not None:
                    group["detector_policy_results"][detector] = _evaluate_opportunity(
                        isolated, cached, cfg
                    )
            group["human_label"] = labels["by_opportunity"].get(
                group["opportunity_id"]
            )
            opportunities.append(group)

    opportunities.sort(
        key=lambda item: (
            item["trading_date"], item["session_id"], item["symbol"],
            int(item["review_ts_ms"]), item["opportunity_id"],
        )
    )
    if len(opportunities) != 893:
        raise RuntimeError(f"expected 893 opportunities, found {len(opportunities)}")
    after = _recording_hashes(recordings, sources)
    if before != after:
        raise RuntimeError("original capture hashes changed during evaluation")

    rows = _trade_rows(opportunities)
    summaries = {
        policy: _policy_report(opportunities, policy) for policy in POLICY_ORDER
    }
    baseline_metrics = summaries["production_baseline"]["portfolio"]
    for policy, report in summaries.items():
        metrics = report["portfolio"]
        report["comparison_with_production_baseline"] = {
            "trade_count_delta": metrics["trades_entered"] - baseline_metrics["trades_entered"],
            "net_r_delta": metrics["net_r"] - baseline_metrics["net_r"],
            "average_r_delta": _difference(metrics["average_r"], baseline_metrics["average_r"]),
            "win_rate_delta": _difference(metrics["win_rate"], baseline_metrics["win_rate"]),
        }
    paired = _paired_policy_report(opportunities)
    if paired["overall"]["both_policies_traded"] != 518:
        raise RuntimeError("expected 518 paired baseline/confirmation opportunities")
    if round(paired["overall"]["delayed_entry_execution_effect_r"], 3) != -12.834:
        raise RuntimeError("locked paired execution delta changed")
    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": "offline_counterfactual_execution_research",
        "classification": "exploratory_historical_comparison_not_validation",
        "code_revision": revision,
        "corpus": {
            "trading_dates": [
                "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"
            ],
            "opportunity_count": len(opportunities),
            "grouping": "production_cooldown_grouping",
            "source_capture_hashes_before": before,
            "source_capture_hashes_after": after,
            "source_captures_byte_identical": True,
        },
        "policy_order": list(POLICY_ORDER),
        "policy_results": summaries,
        "paired_production_vs_confirmed_detector_stop": paired,
        "human_label_diagnostic": _label_diagnostic(opportunities, labels),
        "opportunities": [_compact_opportunity(item) for item in opportunities],
        "interpretation_guardrails": {
            "aggregate_net_r_selects_winner": False,
            "runner_optimization_paused": True,
            "future_holdout_maximum_recommendations": 2,
        },
    }
    definitions = policy_definitions(cfg)
    (destination / "policy-definitions.json").write_text(
        deterministic_json(definitions), encoding="utf-8"
    )
    (destination / "counterfactual-results.json").write_text(
        deterministic_json(result), encoding="utf-8"
    )
    _write_csv(destination / "counterfactual-trades.csv", rows)
    (destination / "counterfactual-summary.md").write_text(
        _render_summary(result), encoding="utf-8"
    )
    hashes = _artifact_hashes(destination)
    (destination / "artifact-hashes.json").write_text(
        deterministic_json(
            {
                "algorithm": "sha256",
                "files": hashes,
                "source_capture_hashes": after,
            }
        ),
        encoding="utf-8",
    )
    return result


def _evaluate_opportunity(
    opportunity: Mapping[str, Any], data: Mapping[str, Any], cfg: CounterfactualConfig
) -> dict[str, Any]:
    quotes = data["quotes"]
    bars = data["bars"]
    trigger_ms = int(opportunity["review_ts_ms"])
    initial = opportunity["candidates"][0]
    initial_pattern_ids = {
        str(item.get("pattern_id") or "") for item in initial.get("contributors") or []
    }
    events = [
        event for event in opportunity["detector_events"]
        if str(event.get("pattern_id") or "") in initial_pattern_ids
        and int(event.get("observation_ts_ms") or 0) <= trigger_ms
    ]
    levels = _breakout_levels(events)
    production_stops = [
        (
            float(c["stop_level"]),
            str(c.get("stop_basis") or ""),
            int(c.get("trigger_ts_ms") or trigger_ms),
        )
        for c in initial.get("contributors") or []
        if _positive_float(c.get("stop_level")) is not None
    ]
    baseline_decision = trigger_ms
    confirm = _find_confirmation(bars, trigger_ms, levels, cfg.confirmation_max_wait_ms)
    retest = _find_retest(bars, confirm, cfg) if confirm else None
    common = dict(
        opportunity=opportunity,
        data=data,
        quotes=quotes,
        bars=bars,
        levels=levels,
        cfg=cfg,
    )
    results = {
        "production_baseline": _run_policy(
            policy="production_baseline",
            decision=baseline_decision,
            stop_kind="detector",
            production_stops=production_stops,
            **common,
        ),
        "confirmed_detector_stop": _run_policy(
            policy="confirmed_detector_stop", decision=confirm,
            stop_kind="detector", production_stops=production_stops, **common
        ),
        "confirmed_structural_stop": _run_policy(
            policy="confirmed_structural_stop", decision=confirm,
            stop_kind="structural", production_stops=production_stops, **common
        ),
        "retest_structural_stop": _run_policy(
            policy="retest_structural_stop", decision=retest,
            stop_kind="structural", production_stops=production_stops, **common
        ),
        "confirmed_volatility_stop": _run_policy(
            policy="confirmed_volatility_stop", decision=confirm,
            stop_kind="volatility", production_stops=production_stops, **common
        ),
    }
    initial_result = _run_policy(
        policy="confirmed_structural_one_reentry", decision=confirm,
        stop_kind="structural", production_stops=production_stops, **common
    )
    results["confirmed_structural_one_reentry"] = _with_reentry(
        initial_result, opportunity=opportunity, data=data, events=events, cfg=cfg
    )
    return results


def _isolate_detector_opportunity(
    opportunity: Mapping[str, Any], detector: str
) -> dict[str, Any] | None:
    matches = []
    for candidate in opportunity["candidates"]:
        contributors = [
            item for item in candidate.get("contributors") or []
            if str(item.get("pattern_type") or "") == detector
        ]
        if contributors:
            matches.append((int(candidate["trigger_ts_ms"]), candidate, contributors))
    if not matches:
        return None
    trigger_ms, candidate, contributors = min(matches, key=lambda item: item[0])
    pattern_ids = {str(item.get("pattern_id") or "") for item in contributors}
    isolated = dict(opportunity)
    isolated["review_ts_ms"] = trigger_ms
    isolated["pattern_types"] = [detector]
    isolated["pattern_status"] = "single_pattern_isolated_counterfactual"
    isolated["candidates"] = [{**candidate, "contributors": contributors, "pattern_types": [detector]}]
    isolated["detector_events"] = [
        event for event in opportunity["detector_events"]
        if str(event.get("pattern_id") or "") in pattern_ids
        and int(event.get("observation_ts_ms") or 0) <= trigger_ms
    ]
    return isolated


def _run_policy(
    *, policy: str, decision: Mapping[str, Any] | int | None,
    stop_kind: str, production_stops: list[tuple[float, str, int]],
    opportunity: Mapping[str, Any], data: Mapping[str, Any],
    quotes: list[dict[str, Any]], bars: list[dict[str, Any]],
    levels: list[dict[str, Any]], cfg: CounterfactualConfig,
) -> dict[str, Any]:
    if decision is None:
        return _unavailable(policy, "no_causal_entry_condition")
    decision_ms = int(decision if isinstance(decision, int) else decision["completed_at_ms"])
    entry_quote = next(
        (
            quote for quote in quotes
            if decision_ms <= int(quote["ts_ms"]) <= decision_ms + cfg.quote_entry_wait_ms
            and _positive_float(quote.get("ask")) is not None
            and _positive_float(quote.get("bid")) is not None
        ), None,
    )
    if entry_quote is None:
        return _unavailable(policy, "no_complete_l1_quote_within_entry_wait")
    entry = float(entry_quote["ask"])
    entry_ms = int(entry_quote["ts_ms"])
    if stop_kind == "detector":
        choices = [
            (value, basis, evidence_ms)
            for value, basis, evidence_ms in production_stops
            if value < entry
            and (policy == "production_baseline" or evidence_ms <= decision_ms)
        ]
        if not choices:
            return _unavailable(policy, "no_detector_supported_stop_below_entry")
        stop, basis, evidence_ms = max(choices, key=lambda item: item[0])
        stop_evidence = {
            "basis": basis, "evidence_ts_ms": evidence_ms, "as_of_ms": decision_ms
        }
    elif stop_kind == "structural":
        structural = _structural_stop(
            opportunity["detector_events"], bars, decision_ms, entry, cfg
        )
        if structural is None:
            return _unavailable(policy, "no_causal_structural_stop_below_entry")
        stop, stop_evidence = structural
    else:
        volatility = _volatility_stop(bars, decision_ms, entry, cfg)
        if volatility is None:
            return _unavailable(policy, "insufficient_preceding_completed_bars")
        stop, stop_evidence = volatility
    risk = entry - stop
    if risk <= entry * cfg.minimum_risk_pct:
        return _unavailable(policy, "non_positive_or_too_small_risk")
    trade = _simulate_trade(
        policy, opportunity, data, entry_quote, stop, stop_evidence, cfg
    )
    trade["decision_ts_ms"] = decision_ms
    trade["decision_evidence"] = (
        {"kind": "immediate_trigger", "trigger_ts_ms": decision_ms}
        if isinstance(decision, int) else dict(decision)
    )
    trade["entry_level_evidence"] = levels
    return {"available": True, "reason": None, "legs": [trade], "combined": _combine([trade])}


def _simulate_trade(
    policy: str, opportunity: Mapping[str, Any], data: Mapping[str, Any],
    entry_quote: Mapping[str, Any], stop: float, stop_evidence: Mapping[str, Any],
    cfg: CounterfactualConfig,
) -> dict[str, Any]:
    entry_ms = int(entry_quote["ts_ms"])
    entry = float(entry_quote["ask"])
    entry_bid = float(entry_quote["bid"])
    risk = entry - stop
    target = entry + cfg.target_r * risk
    natural_end = entry_ms + cfg.max_hold_ms
    integrity = data["integrity"]
    barrier = _first_quality_barrier(
        trigger_ms=entry_ms,
        requested_end_ms=natural_end,
        status_events=data["status_events"],
        gaps=(integrity.get("gaps") or {}).get("details") or [],
        recording_last_ms=integrity.get("last_timestamp_ms"),
    )
    effective_end = min(natural_end, int(barrier["ts_ms"])) if barrier else natural_end
    path = [
        q for q in data["quotes"]
        if entry_ms < int(q["ts_ms"]) <= effective_end
        and _positive_float(q.get("bid")) is not None
    ]
    exit_quote = None
    exit_reason = None
    target_before_stop = False
    for quote in path:
        bid = float(quote["bid"])
        if bid <= stop:
            exit_quote, exit_reason = quote, "STOP"
            break
        if bid >= target:
            exit_quote, exit_reason, target_before_stop = quote, "TARGET", True
            break
    if exit_quote is None and barrier:
        return {
            "policy": policy, "leg": 1, "status": "DATA_QUALITY_BLOCKED",
            "reason": barrier["reason"], "entry_ts_ms": entry_ms,
            "entry_price": entry, "entry_bid": entry_bid, "stop_price": stop,
            "stop_evidence": dict(stop_evidence), "target_price": target,
        }
    if exit_quote is None:
        exit_quote = path[-1] if path else None
        if exit_quote is None:
            return {
                "policy": policy, "leg": 1, "status": "DATA_QUALITY_BLOCKED",
                "reason": "no_exit_quote_before_timeout", "entry_ts_ms": entry_ms,
                "entry_price": entry, "entry_bid": entry_bid, "stop_price": stop,
                "stop_evidence": dict(stop_evidence), "target_price": target,
            }
        exit_reason = "TIMEOUT"
    exit_bid = float(exit_quote["bid"])
    multiplier = 1.0
    if exit_reason == "STOP":
        multiplier -= cfg.stop_fill_slippage_bps / 10_000
    elif exit_reason == "TARGET":
        multiplier -= cfg.target_fill_slippage_bps / 10_000
    exit_price = exit_bid * multiplier
    full_path = [
        q for q in data["quotes"]
        if entry_ms < int(q["ts_ms"]) <= effective_end
        and _positive_float(q.get("bid")) is not None
    ]
    bids = [entry_bid] + [float(q["bid"]) for q in full_path]
    stopped_later_2r = bool(
        exit_reason == "STOP"
        and any(
            int(q["ts_ms"]) > int(exit_quote["ts_ms"]) and float(q["bid"]) >= target
            for q in full_path
        )
    )
    spread = entry - entry_bid
    return {
        "policy": policy, "leg": 1, "status": "TRADE", "reason": None,
        "opportunity_id": opportunity["opportunity_id"],
        "session_id": opportunity["session_id"], "trading_date": opportunity["trading_date"],
        "symbol": opportunity["symbol"], "pattern_types": list(opportunity["pattern_types"]),
        "pattern_status": opportunity["pattern_status"], "time_bucket": opportunity["time_bucket"],
        "repeat_bucket": opportunity["repeat_bucket"], "entry_ts_ms": entry_ms,
        "entry_price": entry, "entry_bid": entry_bid, "entry_spread": spread,
        "entry_spread_pct": spread / ((entry + entry_bid) / 2) * 100,
        "stop_price": stop, "stop_evidence": dict(stop_evidence),
        "target_price": target, "target_r": cfg.target_r,
        "exit_ts_ms": int(exit_quote["ts_ms"]), "exit_price": exit_price,
        "raw_exit_bid": exit_bid, "exit_reason": exit_reason,
        "risk_per_share": risk, "realized_r": (exit_price - entry) / risk,
        "realized_pct": (exit_price - entry) / entry * 100,
        "mfe_r": (max(bids) - entry) / risk, "mae_r": (min(bids) - entry) / risk,
        "target_before_stop": target_before_stop,
        "stopped_then_later_reached_2r": stopped_later_2r,
        "stop_slippage_beyond_minus_1r": (
            max(0.0, -1.0 - (exit_price - entry) / risk) if exit_reason == "STOP" else 0.0
        ),
        "quality_barrier": barrier,
    }


def _with_reentry(
    initial: dict[str, Any], *, opportunity: Mapping[str, Any],
    data: Mapping[str, Any], events: list[dict[str, Any]], cfg: CounterfactualConfig,
) -> dict[str, Any]:
    if not initial.get("available") or not initial.get("legs"):
        return initial
    first = initial["legs"][0]
    if first.get("status") != "TRADE" or first.get("exit_reason") != "STOP":
        return initial
    start = int(first["exit_ts_ms"])
    confirmation = _find_confirmation(
        data["bars"], start, _breakout_levels(events), cfg.reentry_max_wait_ms
    )
    if confirmation is None:
        initial["reentry_unavailable_reason"] = "no_renewed_completed_bar_confirmation"
        return initial
    reentry = _run_policy(
        policy="confirmed_structural_one_reentry", decision=confirmation,
        stop_kind="structural", production_stops=[], opportunity=opportunity,
        data=data, quotes=data["quotes"], bars=data["bars"],
        levels=_breakout_levels(events), cfg=cfg,
    )
    if reentry.get("available") and reentry.get("legs"):
        leg = reentry["legs"][0]
        leg["leg"] = 2
        initial["legs"].append(leg)
        initial["combined"] = _combine(initial["legs"])
    else:
        initial["reentry_unavailable_reason"] = reentry.get("reason")
    return initial


def _find_confirmation(
    bars: list[dict[str, Any]], after_ms: int,
    levels: list[dict[str, Any]], wait_ms: int,
) -> dict[str, Any] | None:
    if not levels:
        return None
    for bar in bars:
        end = int(bar["end_ts_ms"])
        if end <= after_ms or end > after_ms + wait_ms:
            continue
        qualifying = [item for item in levels if float(bar["close"]) >= item["level"]]
        if qualifying:
            selected = min(qualifying, key=lambda item: (item["level"], item["detector"]))
            return {
                "kind": "completed_bar_confirmation", "completed_at_ms": end,
                "bar_start_ms": bar["start_ts_ms"], "bar_close": bar["close"],
                "level": selected["level"], "detector": selected["detector"],
            }
    return None


def _find_retest(
    bars: list[dict[str, Any]], confirmation: Mapping[str, Any],
    cfg: CounterfactualConfig,
) -> dict[str, Any] | None:
    level = float(confirmation["level"])
    after = int(confirmation["completed_at_ms"])
    for bar in bars:
        end = int(bar["end_ts_ms"])
        if end <= after or end > after + cfg.retest_max_wait_ms:
            continue
        if float(bar["low"]) <= level * (1 + cfg.retest_tolerance_pct) and float(bar["close"]) >= level:
            return {
                "kind": "completed_bar_retest_hold", "completed_at_ms": end,
                "bar_start_ms": bar["start_ts_ms"], "bar_low": bar["low"],
                "bar_close": bar["close"], "level": level,
                "tolerance_pct": cfg.retest_tolerance_pct,
            }
    return None


def _structural_stop(
    events: Iterable[Mapping[str, Any]], bars: list[dict[str, Any]],
    decision_ms: int, entry: float, cfg: CounterfactualConfig,
) -> tuple[float, dict[str, Any]] | None:
    explicit: list[tuple[float, str, int]] = []
    keys = ("breakdown_level", "pullback_low", "range_low", "support", "support_low")
    for event in events:
        if int(event.get("observation_ts_ms") or 0) > decision_ms:
            continue
        evidence = event.get("evidence") or {}
        for key in keys:
            value = _positive_float(evidence.get(key))
            if value is not None and value < entry:
                explicit.append((value, f"detector_evidence.{key}", int(event.get("observation_ts_ms") or 0)))
        for point in (event.get("geometry") or {}).get("points") or []:
            role = str(point.get("role") or "").lower()
            value = _positive_float(point.get("price"))
            point_ms = int(float(point.get("time") or 0) * 1000)
            if value is not None and value < entry and point_ms <= decision_ms and (
                "low" in role or "support" in role or "trough" in role
            ):
                explicit.append((value, f"geometry.{role}", point_ms))
    if explicit:
        value, basis, evidence_ms = max(explicit, key=lambda item: (item[0], item[2]))
        stop = value * (1 - cfg.structural_buffer_pct)
        if stop < entry:
            return stop, {
                "basis": basis, "raw_level": value, "evidence_ts_ms": evidence_ms,
                "as_of_ms": decision_ms, "buffer_pct": cfg.structural_buffer_pct,
            }
    prior = [bar for bar in bars if int(bar["end_ts_ms"]) <= decision_ms][-cfg.swing_lookback_bars:]
    if not prior:
        return None
    candidates = []
    for index in range(1, len(prior) - 1):
        if prior[index]["low"] <= prior[index - 1]["low"] and prior[index]["low"] <= prior[index + 1]["low"]:
            candidates.append(prior[index])
    selected = candidates[-1] if candidates else min(prior, key=lambda bar: bar["low"])
    raw = float(selected["low"])
    stop = raw * (1 - cfg.structural_buffer_pct)
    if stop >= entry:
        return None
    return stop, {
        "basis": "most_recent_valid_completed_bar_swing_low",
        "raw_level": raw, "evidence_ts_ms": selected["end_ts_ms"],
        "as_of_ms": decision_ms, "buffer_pct": cfg.structural_buffer_pct,
    }


def _volatility_stop(
    bars: list[dict[str, Any]], decision_ms: int, entry: float,
    cfg: CounterfactualConfig,
) -> tuple[float, dict[str, Any]] | None:
    prior = [bar for bar in bars if int(bar["end_ts_ms"]) <= decision_ms]
    if len(prior) < cfg.volatility_lookback_bars:
        return None
    window = prior[-cfg.volatility_lookback_bars:]
    ranges = []
    previous_close = None
    for bar in window:
        high, low = float(bar["high"]), float(bar["low"])
        value = high - low
        if previous_close is not None:
            value = max(value, abs(high - previous_close), abs(low - previous_close))
        ranges.append(value)
        previous_close = float(bar["close"])
    atr = median(ranges)
    risk = min(atr * cfg.volatility_atr_multiplier, entry * cfg.volatility_risk_cap_pct)
    if risk <= entry * cfg.minimum_risk_pct:
        return None
    return entry - risk, {
        "basis": "preceding_completed_10s_bar_median_true_range",
        "as_of_ms": decision_ms, "last_bar_end_ms": window[-1]["end_ts_ms"],
        "lookback_bars": cfg.volatility_lookback_bars, "median_true_range": atr,
        "multiplier": cfg.volatility_atr_multiplier,
        "risk_cap_pct": cfg.volatility_risk_cap_pct,
    }


def _breakout_levels(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    answer = []
    for event in events:
        evidence = event.get("evidence") or {}
        value = None
        for key in ("breakout_level", "continuation_level", "recovery_pivot", "resistance_high", "impulse_high"):
            value = _positive_float(evidence.get(key))
            if value is not None:
                break
        if value is not None:
            answer.append({
                "detector": str(event.get("pattern_type") or ""),
                "pattern_id": str(event.get("pattern_id") or ""),
                "level": value, "source_key": key,
                "available_at_ms": int(event.get("observation_ts_ms") or 0),
            })
    return sorted(answer, key=lambda item: (item["level"], item["detector"], item["pattern_id"]))


def _completed_bars(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for quote in quotes:
        value = _positive_float(quote.get("last"))
        if value is not None:
            ts = int(quote["ts_ms"])
            buckets[(ts // 10_000) * 10_000].append((ts, value))
    bars = []
    for start, points in sorted(buckets.items()):
        ordered = sorted(points)
        values = [value for _, value in ordered]
        bars.append({
            "start_ts_ms": start, "end_ts_ms": start + 10_000,
            "open": values[0], "high": max(values), "low": min(values),
            "close": values[-1], "last_observation_ts_ms": ordered[-1][0],
        })
    return bars


def _unavailable(policy: str, reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "legs": [], "combined": None}


def _combine(legs: list[Mapping[str, Any]]) -> dict[str, Any]:
    trades = [leg for leg in legs if leg.get("status") == "TRADE"]
    values = [float(leg["realized_r"]) for leg in trades]
    return {
        "trade_count": len(trades),
        "net_r": sum(values),
        "realized_pct_sum": sum(float(leg["realized_pct"]) for leg in trades),
        "wins": sum(value > 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "flats": sum(value == 0 for value in values),
        "timeouts": sum(leg.get("exit_reason") == "TIMEOUT" for leg in trades),
    }


def _policy_report(opportunities: list[dict[str, Any]], policy: str) -> dict[str, Any]:
    def select(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [leg for item in items for leg in item["policy_results"][policy]["legs"] if leg.get("status") == "TRADE"]
    trades = select(opportunities)
    portfolio = _metrics(opportunities, policy, trades)
    dimensions = {}
    getters = {
        "date": lambda x: x["trading_date"], "symbol": lambda x: x["symbol"],
        "single_multi_pattern": lambda x: x["pattern_status"],
        "time_bucket": lambda x: x["time_bucket"], "repeat_bucket": lambda x: x["repeat_bucket"],
    }
    for name, getter in getters.items():
        dimensions[name] = []
        for value in sorted({getter(item) for item in opportunities}):
            subset = [item for item in opportunities if getter(item) == value]
            dimensions[name].append({name: value, **_metrics(subset, policy, select(subset))})
    detector = []
    for value in sorted({d for item in opportunities for d in item["pattern_types"]}):
        subset = [
            {**item, "policy_results": item["detector_policy_results"][value]}
            for item in opportunities
            if value in item.get("detector_policy_results", {})
        ]
        detector.append({
            "detector": value,
            "counting_note": "independent detector-only counterfactual; multi-pattern membership is non-additive and excluded from portfolio summation",
            **_metrics(subset, policy, select(subset)),
        })
    symbol_rows = dimensions["symbol"]
    total_abs_r = sum(abs(float(row["net_r"])) for row in symbol_rows)
    concentration = sorted(
        [
            {
                "symbol": row["symbol"],
                "trades_entered": row["trades_entered"],
                "net_r": row["net_r"],
                "absolute_net_r_share": abs(float(row["net_r"])) / total_abs_r if total_abs_r else None,
            }
            for row in symbol_rows
        ],
        key=lambda row: (-abs(float(row["net_r"])), row["symbol"]),
    )
    return {
        "portfolio": portfolio,
        "symbol_concentration": {"top_five_by_absolute_net_r": concentration[:5]},
        "by": {**dimensions, "detector": detector},
    }


def _metrics(items: list[dict[str, Any]], policy: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    rs = [float(t["realized_r"]) for t in trades]
    pcts = [float(t["realized_pct"]) for t in trades]
    wins = sum(value > 0 for value in rs)
    losses = sum(value < 0 for value in rs)
    flats = len(rs) - wins - losses
    timeouts = sum(t["exit_reason"] == "TIMEOUT" for t in trades)
    stopped = [t for t in trades if t["exit_reason"] == "STOP"]
    unavailable = Counter(
        item["policy_results"][policy].get("reason") or "available"
        for item in items if not item["policy_results"][policy]["available"]
    )
    return {
        "opportunities": len(items),
        "opportunities_eligible": sum(item["policy_results"][policy]["available"] for item in items),
        "trades_entered": len(trades), "wins": wins, "losses": losses,
        "flats": flats, "timeouts": timeouts,
        "win_rate": wins / len(trades) if trades else None,
        "net_r": sum(rs), "average_r": sum(rs) / len(rs) if rs else None,
        "median_r": median(rs) if rs else None,
        "average_realized_pct": sum(pcts) / len(pcts) if pcts else None,
        "average_mfe_r": sum(float(t["mfe_r"]) for t in trades) / len(trades) if trades else None,
        "average_mae_r": sum(float(t["mae_r"]) for t in trades) / len(trades) if trades else None,
        "target_before_stop_count": sum(bool(t["target_before_stop"]) for t in trades),
        "stopped_then_later_reached_2r_count": sum(bool(t["stopped_then_later_reached_2r"]) for t in trades),
        "average_stop_slippage_beyond_minus_1r": (
            sum(float(t["stop_slippage_beyond_minus_1r"]) for t in stopped) / len(stopped)
            if stopped else None
        ),
        "maximum_loss_r": min(rs) if rs else None,
        "unavailable_reasons": dict(sorted(unavailable.items())),
    }


def _paired_policy_report(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        both: list[tuple[dict[str, Any], dict[str, Any]]] = []
        baseline_only: list[dict[str, Any]] = []
        confirmed_only: list[dict[str, Any]] = []
        neither = 0
        for item in items:
            baseline = _first_trade(item, "production_baseline")
            confirmed = _first_trade(item, "confirmed_detector_stop")
            if baseline is not None and confirmed is not None:
                both.append((baseline, confirmed))
            elif baseline is not None:
                baseline_only.append(baseline)
            elif confirmed is not None:
                confirmed_only.append(confirmed)
            else:
                neither += 1
        baseline_paired = [float(pair[0]["realized_r"]) for pair in both]
        confirmed_paired = [float(pair[1]["realized_r"]) for pair in both]
        deltas = [confirmed - baseline for baseline, confirmed in zip(
            baseline_paired, confirmed_paired
        )]
        baseline_only_r = sum(float(item["realized_r"]) for item in baseline_only)
        confirmed_only_r = sum(float(item["realized_r"]) for item in confirmed_only)
        paired_delta = sum(deltas)
        selection_effect = confirmed_only_r - baseline_only_r
        return {
            "opportunities": len(items),
            "both_policies_traded": len(both),
            "baseline_only": len(baseline_only),
            "confirmed_only": len(confirmed_only),
            "neither": neither,
            "paired_baseline_net_r": sum(baseline_paired),
            "paired_baseline_average_r": (
                sum(baseline_paired) / len(baseline_paired) if baseline_paired else None
            ),
            "paired_confirmed_net_r": sum(confirmed_paired),
            "paired_confirmed_average_r": (
                sum(confirmed_paired) / len(confirmed_paired) if confirmed_paired else None
            ),
            "paired_mean_delta_r": sum(deltas) / len(deltas) if deltas else None,
            "confirmed_better": sum(delta > 0 for delta in deltas),
            "baseline_better": sum(delta < 0 for delta in deltas),
            "equal": sum(delta == 0 for delta in deltas),
            "baseline_only_net_r": baseline_only_r,
            "confirmed_only_net_r": confirmed_only_r,
            "selection_effect_r": selection_effect,
            "delayed_entry_execution_effect_r": paired_delta,
            "aggregate_net_r_delta_reconciled": selection_effect + paired_delta,
        }

    return {
        "definitions": {
            "selection_effect_r": "confirmed-only net R minus baseline-only net R; positive means confirmation avoided net losing baseline selections",
            "delayed_entry_execution_effect_r": "confirmed net R minus baseline net R on opportunities traded by both policies",
        },
        "overall": summarize(opportunities),
        "by_date": [
            {"date": value, **summarize([
                item for item in opportunities if item["trading_date"] == value
            ])}
            for value in sorted({item["trading_date"] for item in opportunities})
        ],
        "by_symbol": [
            {"symbol": value, **summarize([
                item for item in opportunities if item["symbol"] == value
            ])}
            for value in sorted({item["symbol"] for item in opportunities})
        ],
    }


def _first_trade(item: Mapping[str, Any], policy: str) -> dict[str, Any] | None:
    return next(
        (
            leg for leg in item["policy_results"][policy]["legs"]
            if leg.get("status") == "TRADE"
        ),
        None,
    )


def _load_labels(manifest_path: Path | None, labels_path: Path | None) -> dict[str, Any]:
    result = {
        "expected_count": 60, "loaded_count": 0, "by_opportunity": {},
        "class_counts": {}, "control_count": 0, "rows": [],
    }
    if manifest_path is None or labels_path is None:
        return result
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest_items = {
        str(item["review_id"]): item for item in manifest.get("items") or []
    }
    evidence_path = Path(manifest_path).with_name("machine-evidence.json")
    if not evidence_path.is_file():
        raise ValueError(f"review evidence not found: {evidence_path}")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(Path(labels_path).open(encoding="utf-8", newline="")))
    required = {
        "review_id", "valid_setup", "human_pattern_types", "timing",
        "entry_quality", "stop_structure_visible", "notes",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError("locked labels CSV does not match the required schema")
    if len(rows) != 60:
        raise ValueError(f"expected 60 locked label rows, found {len(rows)}")
    normalization = {"yes": "clear", "uncertain": "uncertain", "no": "rejected"}
    counts: Counter[str] = Counter()
    control_count = 0
    seen: set[str] = set()
    for row in rows:
        review_id = str(row.get("review_id") or "")
        if review_id in seen or review_id not in manifest_items or review_id not in evidence:
            raise ValueError(f"unknown or duplicate locked review_id: {review_id}")
        seen.add(review_id)
        raw = str(row.get("valid_setup") or "").strip().lower()
        if raw not in normalization:
            raise ValueError(f"unsupported valid_setup value for {review_id}: {raw}")
        normalized = normalization[raw]
        kind = str(evidence[review_id].get("kind") or "")
        opportunity_id = evidence[review_id].get("opportunity_id")
        if kind == "control":
            control_count += 1
            if opportunity_id is not None:
                raise ValueError(f"control unexpectedly maps to opportunity: {review_id}")
        elif kind == "triggered":
            if not opportunity_id:
                raise ValueError(f"triggered review lacks opportunity_id: {review_id}")
            counts[normalized] += 1
            result["by_opportunity"][str(opportunity_id)] = normalized
        else:
            raise ValueError(f"unsupported review evidence kind for {review_id}: {kind}")
        result["rows"].append({
            **{key: str(row.get(key) or "") for key in sorted(required)},
            "opportunity_id": opportunity_id,
            "validity_class": normalized,
            "excluded_control": kind == "control",
        })
    expected = {"clear": 9, "uncertain": 8, "rejected": 33}
    if dict(counts) != expected:
        raise ValueError(f"locked triggered label counts changed: {dict(counts)}")
    if control_count != 10:
        raise ValueError(f"expected 10 excluded controls, found {control_count}")
    if len(result["by_opportunity"]) != 50:
        raise ValueError("expected 50 triggered review-to-opportunity mappings")
    result["loaded_count"] = len(rows)
    result["class_counts"] = dict(sorted(counts.items()))
    result["control_count"] = control_count
    return result


def _label_diagnostic(opportunities: list[dict[str, Any]], labels: Mapping[str, Any]) -> dict[str, Any]:
    classes = {}
    for label in ("clear", "uncertain", "rejected"):
        subset = [item for item in opportunities if item.get("human_label") == label]
        classes[label] = {
            "labeled_opportunity_count": len(subset),
            "policies": {policy: _metrics(subset, policy, [leg for item in subset for leg in item["policy_results"][policy]["legs"] if leg.get("status") == "TRADE"]) for policy in POLICY_ORDER},
        }
    return {
        "labels_are_diagnostic_only": True,
        "labels_used_to_alter_trades": False,
        "expected_locked_label_count": labels["expected_count"],
        "loaded_locked_label_count": labels["loaded_count"],
        "locked_class_counts": labels["class_counts"],
        "excluded_control_count": labels["control_count"],
        "known_locked_aggregate_counts": LOCKED_PRIOR_FINDINGS[
            "human_validity_counts"
        ],
        "known_locked_control_count": LOCKED_PRIOR_FINDINGS["blinded_controls"],
        "aggregate_counts_not_reverse_assigned_to_items": False,
        "missing_labels_explicit": labels["loaded_count"] != labels["expected_count"],
        "by_validity_class": classes,
    }


def _compact_opportunity(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in (
        "opportunity_id", "session_id", "trading_date", "symbol", "review_ts_ms",
        "pattern_types", "pattern_status", "time_bucket", "repeat_bucket",
        "raw_candidate_count", "repeated_candidate_count", "human_label", "policy_results",
    )}


def _trade_rows(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in opportunities:
        for policy in POLICY_ORDER:
            result = item["policy_results"][policy]
            if not result["available"]:
                rows.append({
                    "opportunity_id": item["opportunity_id"], "policy": policy,
                    "available": False, "unavailable_reason": result["reason"],
                    "trading_date": item["trading_date"], "symbol": item["symbol"],
                    "detectors": "+".join(item["pattern_types"]),
                    "pattern_status": item["pattern_status"], "time_bucket": item["time_bucket"],
                    "repeat_bucket": item["repeat_bucket"], "human_label": item.get("human_label") or "",
                })
            for leg in result["legs"]:
                rows.append({
                    "opportunity_id": item["opportunity_id"], "policy": policy,
                    "available": True, "unavailable_reason": "", "trading_date": item["trading_date"],
                    "symbol": item["symbol"], "detectors": "+".join(item["pattern_types"]),
                    "pattern_status": item["pattern_status"], "time_bucket": item["time_bucket"],
                    "repeat_bucket": item["repeat_bucket"], "human_label": item.get("human_label") or "",
                    **{key: leg.get(key) for key in (
                        "leg", "status", "reason", "decision_ts_ms", "entry_ts_ms", "entry_price",
                        "entry_bid", "entry_spread", "stop_price", "target_price", "exit_ts_ms",
                        "exit_price", "raw_exit_bid", "exit_reason", "risk_per_share", "realized_r",
                        "realized_pct", "mfe_r", "mae_r", "target_before_stop",
                        "stopped_then_later_reached_2r", "stop_slippage_beyond_minus_1r",
                    )},
                    "stop_basis": (leg.get("stop_evidence") or {}).get("basis"),
                })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _render_summary(result: Mapping[str, Any]) -> str:
    lines = [
        "# Counterfactual execution research", "",
        "> Exploratory historical comparison, not validation. Aggregate net R is not a winner-selection rule.", "",
        "The corpus contains 893 production-cooldown-grouped opportunities from September 23, 24, 25, and 28. Entries use ask, exits use bid, every target is fixed at 2R, and each leg has a 15-minute horizon.", "",
        "## Portfolio comparison", "",
        "| Policy | Eligible | Trades | W/L/T | Win rate | Net R | Avg R | Median R |", "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for policy in POLICY_ORDER:
        m = result["policy_results"][policy]["portfolio"]
        pct = "n/a" if m["win_rate"] is None else f"{m['win_rate'] * 100:.1f}%"
        lines.append(
            f"| {policy} | {m['opportunities_eligible']} | {m['trades_entered']} | {m['wins']}/{m['losses']}/{m['timeouts']} | {pct} | {m['net_r']:.3f} | {_fmt(m['average_r'])} | {_fmt(m['median_r'])} |"
        )
    labels = result["human_label_diagnostic"]
    lines += ["", "## Human-label diagnostic", ""]
    if labels["missing_labels_explicit"]:
        lines.append(
            f"The configured label input contained {labels['loaded_locked_label_count']} of {labels['expected_locked_label_count']} locked labels. Per-class results remain explicit and empty; aggregate label counts were not reverse-assigned to review items."
        )
        lines.append(
            "Locked aggregate context is preserved as 9 clear, 8 uncertain, 33 "
            "rejected triggered reviews and 10 controls. Item-level policy behavior "
            "by class requires the filled review-ID label file."
        )
    else:
        lines.append(
            "All 60 locked reviews loaded: 9 clear, 8 uncertain, and 33 "
            "rejected triggered opportunities; 10 controls were excluded from "
            "opportunity-policy results. Labels did not alter any trade."
        )
    paired = result["paired_production_vs_confirmed_detector_stop"]["overall"]
    lines += [
        "", "## Paired baseline versus confirmation", "",
        "| Both | Baseline only | Confirmed only | Neither | Paired baseline R | Paired confirmed R | Paired delta R | Selection effect R |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {paired['both_policies_traded']} | {paired['baseline_only']} | "
            f"{paired['confirmed_only']} | {paired['neither']} | "
            f"{paired['paired_baseline_net_r']:.3f} | "
            f"{paired['paired_confirmed_net_r']:.3f} | "
            f"{paired['delayed_entry_execution_effect_r']:.3f} | "
            f"{paired['selection_effect_r']:.3f} |"
        ),
    ]
    lines += ["", "## Interpretation", "", _interpretation(result), ""]
    return "\n".join(lines)


def _interpretation(result: Mapping[str, Any]) -> str:
    paired = result["paired_production_vs_confirmed_detector_stop"]["overall"]
    return (
        "Confirmation's historical aggregate improvement came from skipping weak "
        "baseline trades, not superior execution on shared selections. On "
        f"{paired['both_policies_traded']} common opportunities, confirmation was "
        f"{abs(paired['delayed_entry_execution_effect_r']):.3f}R worse. Confirmed "
        "entry with the existing detector stop is only a future holdout eligibility "
        "hypothesis. No policy is approved for deployment."
    )


def _recording_hashes(
    recordings: Path, sources: Iterable[Mapping[str, Any]]
) -> dict[str, str]:
    """Hash original capture bytes, never overlay symlinks or derived files."""
    result = {}
    for session in sorted({str(source["session_id"]) for source in sources}):
        digest = hashlib.sha256()
        session_root = recordings / session
        for path in sorted(session_root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                digest.update(path.relative_to(recordings).as_posix().encode())
                digest.update(path.read_bytes())
        result[session] = digest.hexdigest()
    return result


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "artifact-hashes.json"
    }


def _time_bucket(ts_ms: int) -> str:
    local = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone(NY)
    minute = local.hour * 60 + local.minute
    if minute < 9 * 60 + 30:
        return "premarket"
    if minute < 10 * 60 + 30:
        return "open_first_hour"
    if minute < 14 * 60:
        return "midday"
    return "late_day"


def _repeat_bucket(value: int) -> str:
    if value == 0:
        return "0"
    if value <= 2:
        return "1-2"
    if value <= 5:
        return "3-5"
    return "6+"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _difference(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic offline counterfactual execution research.")
    parser.add_argument("recordings_root", type=Path)
    parser.add_argument("replay_overlays_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--review-manifest", type=Path)
    parser.add_argument("--labels-csv", type=Path)
    args = parser.parse_args(argv)
    build_counterfactual_research(
        args.recordings_root, args.replay_overlays_root, args.output_root,
        code_revision=args.code_revision, review_manifest=args.review_manifest,
        labels_csv=args.labels_csv,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
