from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from dataclasses import asdict
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from momentum_companion.clients.stream_mapping import LevelOneCache

from momentum_companion.evaluation.batch_trade_simulation import deterministic_json
from momentum_companion.evaluation.counterfactual_execution import (
    CounterfactualConfig,
    _completed_bars,
    _evaluate_opportunity,
    _paired_policy_report,
    _recording_hashes,
    _repeat_bucket,
    _time_bucket,
)
from momentum_companion.evaluation.opportunity_review import (
    _trading_date,
    group_production_cooldown_opportunities,
)
from momentum_companion.evaluation.momentum_eligibility import (
    RvolObservation, RVOL_SOURCE, calculate_time_adjusted_rvol,
    classify_momentum_eligibility,
)
from momentum_companion.evaluation.trade_simulation import (
    TradeSimulationPolicy,
    _load_quote_timeline,
    build_trade_simulation,
)
from momentum_companion.recording.integrity import build_integrity_report
from momentum_companion.replay.catalog import RecordingCatalog


SCHEMA_VERSION = 1
LOCKED_CUTOFF_DATE = "2026-09-29"
MINIMUM_TRADING_DATES = 20
MINIMUM_OPPORTUNITIES = 500
MINIMUM_PAIRED_TRADES = 250
PAIRED_MEAN_NONINFERIORITY_R = -0.10
MOMENTUM_POLICY = "confirmed_detector_stop_momentum_eligible"
EVALUATED_POLICIES = ("production_baseline", "confirmed_detector_stop", MOMENTUM_POLICY)
_ET = ZoneInfo("America/New_York")


def validate_cutoff(cutoff_date: str | None) -> str:
    """Require the prospective cutoff explicitly and refuse alternate cutoffs."""
    value = str(cutoff_date or "").strip()
    if not value:
        raise ValueError("--cutoff-date is required and has no default")
    if value != LOCKED_CUTOFF_DATE:
        raise ValueError(
            f"cutoff is locked at {LOCKED_CUTOFF_DATE}; received {value}"
        )
    return value


def select_holdout_sessions(
    sessions: Iterable[Mapping[str, Any]],
    *,
    cutoff_date: str | None,
    end_date: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cutoff = validate_cutoff(cutoff_date)
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in sorted(sessions, key=lambda item: str(item["session_id"])):
        session = dict(raw)
        day = _trading_date(session)
        if day <= cutoff:
            excluded.append(
                {"session_id": session["session_id"], "trading_date": day,
                 "reason": "on_or_before_locked_cutoff"}
            )
        elif end_date is not None and day > end_date:
            excluded.append(
                {"session_id": session["session_id"], "trading_date": day,
                 "reason": "after_requested_end_date"}
            )
        else:
            session["trading_date"] = day
            eligible.append(session)
    return eligible, excluded


def build_prospective_holdout(
    recordings_root: Path,
    output_root: Path,
    *,
    cutoff_date: str | None,
    code_revision: str,
    end_date: str | None = None,
) -> dict[str, Any]:
    cutoff = validate_cutoff(cutoff_date)
    revision = str(code_revision or "").strip()
    if not revision:
        raise ValueError("code_revision is required")
    recordings = Path(recordings_root)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    catalog = RecordingCatalog(recordings)
    eligible, excluded = select_holdout_sessions(
        catalog.list_sessions(), cutoff_date=cutoff, end_date=end_date
    )
    evaluable: list[dict[str, Any]] = []
    for session in eligible:
        events = catalog.load_pattern_events(str(session["session_id"]))
        if not events:
            excluded.append(
                {
                    "session_id": session["session_id"],
                    "trading_date": session["trading_date"],
                    "reason": "no_persisted_pattern_events",
                }
            )
            continue
        evaluable.append(session)
    if not evaluable:
        raise ValueError(
            f"no evaluable captures exist after locked cutoff {LOCKED_CUTOFF_DATE}"
        )

    sources = [
        {
            "source_key": f"prospective_holdout:{session['session_id']}",
            "root": recordings,
            "session_id": str(session["session_id"]),
            "trading_date": session["trading_date"],
            "symbols": sorted(session.get("symbols") or []),
            "started_at_et": session.get("started_at_et"),
            "source_mode": "persisted_live_journal",
            "status_evidence": "recorded_when_available",
            "context_completeness": "recorded_provenance",
        }
        for session in evaluable
    ]
    before = _recording_hashes(recordings, sources)
    opportunities: list[dict[str, Any]] = []
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        session_id = source["session_id"]
        events = catalog.load_pattern_events(session_id)
        simulation = build_trade_simulation(recordings, session_id)
        simulation.pop("generated_at_utc", None)
        groups = group_production_cooldown_opportunities(
            source, simulation["candidates"], events
        )
        event_by_id = {
            str(event.get("pattern_id") or ""): event
            for event in events if str(event.get("pattern_id") or "")
        }
        integrity = build_integrity_report(recordings / session_id)
        for group in groups:
            key = (session_id, group["symbol"])
            data = cache.get(key)
            if data is None:
                quotes = _load_quote_timeline(catalog, session_id, group["symbol"])
                data = {
                    "quotes": quotes,
                    "bars": _completed_bars(quotes),
                    "status_events": catalog.load_security_status_events(
                        session_id, symbol=group["symbol"]
                    ),
                    "integrity": (integrity.get("symbols") or {}).get(
                        group["symbol"], {}
                    ),
                }
                cache[key] = data
            pattern_ids = {
                str(contributor.get("pattern_id") or "")
                for candidate in group["candidates"]
                for contributor in candidate.get("contributors") or []
            }
            group["detector_events"] = sorted(
                [event_by_id[value] for value in pattern_ids if value in event_by_id],
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
                "multi_pattern" if len(group["pattern_types"]) > 1
                else "single_pattern"
            )
            evaluated = _evaluate_opportunity(
                group, data, CounterfactualConfig()
            )
            group["policy_results"] = {
                policy: evaluated[policy] for policy in ("production_baseline", "confirmed_detector_stop")
            }
            eligibility = _holdout_momentum_eligibility(catalog, catalog.list_sessions(), group,
                group["policy_results"]["confirmed_detector_stop"])
            group["momentum_eligibility"] = {"confirmed_detector_stop": eligibility, MOMENTUM_POLICY: eligibility}
            confirmed = group["policy_results"]["confirmed_detector_stop"]
            if eligibility["classification"] in {"trade_candidate", "preferred_candidate"}:
                selected = dict(confirmed); selected["selection_reason"] = eligibility["classification"]
            else:
                selected = {"available": False, "reason": f"momentum_eligibility:{eligibility['classification']}",
                    "legs": [], "combined": {"trade_count": 0, "wins": 0, "losses": 0, "flats": 0,
                    "timeouts": 0, "net_r": 0.0, "realized_pct_sum": 0.0}}
            group["policy_results"][MOMENTUM_POLICY] = selected
            opportunities.append(group)

    opportunities.sort(
        key=lambda item: (
            item["trading_date"], item["session_id"], item["symbol"],
            int(item["review_ts_ms"]), item["opportunity_id"],
        )
    )
    if any(item["trading_date"] <= cutoff for item in opportunities):
        raise RuntimeError("pre-cutoff opportunity entered prospective holdout")
    after = _recording_hashes(recordings, sources)
    if before != after:
        raise RuntimeError("source captures changed during holdout evaluation")

    policy_results = {
        policy: _holdout_policy_metrics(opportunities, policy)
        for policy in EVALUATED_POLICIES
    }
    paired = _paired_policy_report(opportunities)
    dates = sorted({item["trading_date"] for item in opportunities})
    readiness = holdout_readiness(
        independent_trading_dates=len(dates),
        opportunities=len(opportunities),
        paired_trades=paired["overall"]["both_policies_traded"],
        momentum_trades=policy_results[MOMENTUM_POLICY]["aggregate"]["trades"],
    )
    success = _success_assessment(policy_results, paired, readiness)
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "prospective_unseen_execution_holdout",
        "classification": "prospective_unseen_holdout_not_deployment_approval",
        "code_revision": revision,
        "locked_protocol": {
            "cutoff_date": cutoff,
            "eligibility": "trading_date strictly after cutoff_date",
            "evaluated_policies": list(EVALUATED_POLICIES),
            "tuning_during_holdout": False,
            "policy_selection_during_holdout": False,
            "human_labels": "secondary_diagnostic_only",
            "policy_constants": asdict(CounterfactualConfig()),
            "production_simulation_constants": TradeSimulationPolicy().to_dict(),
            "momentum_eligibility": {"min_breakout_room_pct": 8.0,
                "preferred_breakout_room_pct": 10.0, "min_time_adjusted_rvol": 2.0,
                "rvol_source": RVOL_SOURCE, "new_preregistered_hypothesis": True,
                "original_two_policy_comparison_preserved": True},
        },
        "inventory": {
            "eligible_sessions": [
                {"session_id": item["session_id"], "trading_date": item["trading_date"]}
                for item in evaluable
            ],
            "excluded_sessions": sorted(
                excluded,
                key=lambda item: (
                    item["trading_date"], item["session_id"], item["reason"]
                ),
            ),
            "independent_trading_dates": dates,
            "opportunity_count": len(opportunities),
        },
        "source_capture_hashes_before": before,
        "source_capture_hashes_after": after,
        "source_captures_byte_identical": True,
        "policy_results": policy_results,
        "paired_selection_and_execution": paired,
        "minimum_size": readiness,
        "success_assessment": success,
        "opportunities": [_compact(item) for item in opportunities],
    }
    rows = _holdout_trade_rows(opportunities)
    write_holdout_outputs(destination, report, rows)
    return report


def holdout_readiness(
    *, independent_trading_dates: int, opportunities: int, paired_trades: int,
    momentum_trades: int | None = None,
) -> dict[str, Any]:
    ready = (
        independent_trading_dates >= MINIMUM_TRADING_DATES
        and opportunities >= MINIMUM_OPPORTUNITIES
        and paired_trades >= MINIMUM_PAIRED_TRADES
    )
    momentum_ready = ready and momentum_trades is not None and momentum_trades >= MINIMUM_PAIRED_TRADES
    return {
        "required_independent_trading_dates": MINIMUM_TRADING_DATES,
        "required_opportunities": MINIMUM_OPPORTUNITIES,
        "required_paired_trades": MINIMUM_PAIRED_TRADES,
        "observed_independent_trading_dates": independent_trading_dates,
        "observed_opportunities": opportunities,
        "observed_paired_trades": paired_trades,
        "required_momentum_trades": MINIMUM_PAIRED_TRADES,
        "observed_momentum_trades": momentum_trades,
        "ready_for_locked_assessment": ready,
        "momentum_ready_for_locked_assessment": momentum_ready,
        "rule": "all minimums must be met; do not stop early after favorable results",
    }


def _success_assessment(
    policies: Mapping[str, Mapping[str, Any]],
    paired: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    confirmed = policies["confirmed_detector_stop"]["aggregate"]
    paired_mean = paired["overall"]["paired_mean_delta_r"]
    positive_expectancy = (
        confirmed["net_r"] > 0 and (confirmed["average_r"] or 0) > 0
    )
    execution_not_materially_degraded = (
        paired_mean is not None and paired_mean >= PAIRED_MEAN_NONINFERIORITY_R
    )
    passed = bool(
        readiness["ready_for_locked_assessment"]
        and positive_expectancy
        and execution_not_materially_degraded
    )
    result = {
        "assessment_allowed": readiness["ready_for_locked_assessment"],
        "positive_out_of_sample_expectancy_required": True,
        "losing_less_is_success": False,
        "confirmed_positive_expectancy": positive_expectancy,
        "paired_mean_delta_floor_r": PAIRED_MEAN_NONINFERIORITY_R,
        "paired_execution_not_materially_degraded": execution_not_materially_degraded,
        "protocol_passed": passed,
        "deployment_approved": False,
    }
    momentum = policies.get(MOMENTUM_POLICY, {}).get("aggregate")
    if momentum is not None:
        positive = momentum["net_r"] > 0 and (momentum["average_r"] or 0) > 0
        result["momentum_policy"] = {"positive_out_of_sample_expectancy": positive,
            "protocol_passed": bool(readiness.get("momentum_ready_for_locked_assessment") and positive),
            "deployment_approved": False}
    return result


def _holdout_policy_metrics(
    opportunities: list[dict[str, Any]], policy: str
) -> dict[str, Any]:
    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        trades = [
            leg for item in items
            for leg in item["policy_results"][policy]["legs"]
            if leg.get("status") == "TRADE"
        ]
        values = [float(item["realized_r"]) for item in trades]
        return {
            "opportunities": len(items),
            "trades": len(trades),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "timeouts": sum(item.get("exit_reason") == "TIMEOUT" for item in trades),
            "win_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "net_r": sum(values),
            "average_r": sum(values) / len(values) if values else None,
            "unavailable": dict(sorted(Counter(
                item["policy_results"][policy].get("reason") or "unknown"
                for item in items
                if not item["policy_results"][policy]["available"]
            ).items())),
        }

    return {
        "aggregate": summarize(opportunities),
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


def _holdout_momentum_eligibility(catalog, sessions, group, confirmed):
    leg = next((item for item in confirmed.get("legs") or [] if item.get("status") == "TRADE"), None)
    decision = int((leg or {}).get("decision_ts_ms") or group.get("review_ts_ms") or 0)
    levels, complete = _causal_resistance_levels(group, decision)
    phase, offset = _market_phase_offset(decision)
    current = _phase_cumulative_volume(catalog, str(group["session_id"]), str(group["symbol"]), decision)
    history = []
    for session in sorted(sessions, key=_trading_date):
        day = _trading_date(session)
        if day >= group["trading_date"] or str(group["symbol"]) not in (session.get("symbols") or []): continue
        volume = _phase_cumulative_volume(catalog, str(session["session_id"]), str(group["symbol"]),
            _timestamp_for_phase(day, phase, offset))
        if volume is not None: history.append(RvolObservation(day, phase, offset, volume))
    rvol = calculate_time_adjusted_rvol(trading_date=group["trading_date"], market_phase=phase,
        phase_offset_seconds=offset, cumulative_volume=current, history=history)
    return classify_momentum_eligibility(entry_price=(float(leg["entry_price"]) if leg else None),
        decision_ts_ms=decision, detector_structure_valid=bool(group.get("detector_events")) and leg is not None,
        resistance_levels=levels, resistance_evidence_complete=complete, rvol=rvol)


def _causal_resistance_levels(group, decision):
    levels, complete = [], False
    for event in group.get("detector_events") or []:
        observed = int(event.get("observation_ts_ms") or 0); context = event.get("trigger_context") or {}
        as_of = int(context.get("context_as_of_ts_ms") or observed)
        if observed > decision or as_of > decision: continue
        registry = context.get("session_levels") or {}
        expected = ("premarket_high", "opening_range_high", "regular_session_high", "vwap")
        complete = complete or all(key in registry for key in expected)
        for key in expected:
            raw = registry.get(key); value = raw.get("value") if isinstance(raw, Mapping) else raw
            available = raw.get("available", value is not None) if isinstance(raw, Mapping) else value is not None
            if available and value is not None: levels.append({"type": key, "price": value, "available_at_ms": as_of})
        nearest = (context.get("structural_levels") or {}).get("nearest_resistance")
        if isinstance(nearest, Mapping) and nearest.get("price") is not None:
            levels.append({"type": str(nearest.get("source") or "nearest_resistance"),
                "price": nearest["price"], "available_at_ms": as_of})
    return levels, complete


def _market_phase_offset(timestamp_ms):
    local = datetime.fromtimestamp(timestamp_ms / 1000, tz=_ET); seconds = local.hour * 3600 + local.minute * 60 + local.second
    return ("regular", seconds - 34200) if seconds >= 34200 else ("premarket", seconds - 14400)


def _timestamp_for_phase(day, phase, offset):
    base = time(9, 30) if phase == "regular" else time(4, 0)
    return int(datetime.combine(datetime.fromisoformat(day).date(), base, tzinfo=_ET).timestamp() * 1000) + offset * 1000


def _phase_cumulative_volume(catalog, session_id, symbol, timestamp_ms):
    phase, _ = _market_phase_offset(timestamp_ms)
    local = datetime.fromtimestamp(timestamp_ms / 1000, tz=_ET)
    regular_start = int(datetime.combine(local.date(), time(9, 30), tzinfo=_ET).timestamp() * 1000)
    cache, latest, regular_base = LevelOneCache(), None, None
    for record in catalog.load_events(session_id, symbol):
        event_ts = int(record.get("stream_ts_ms") or 0)
        if event_ts > timestamp_ms: break
        if record.get("kind") != "market_event": continue
        for quote in cache.process_messages({"service": "LEVELONE_EQUITIES", "timestamp": event_ts, "content": [dict(record["raw"])]}):
            if str(quote.get("symbol") or "").upper() != symbol.upper() or quote.get("volume") is None: continue
            if phase == "regular" and event_ts < regular_start: regular_base = float(quote["volume"])
            latest = float(quote["volume"])
    if latest is None or (phase == "regular" and regular_base is None): return None
    return max(0.0, latest - regular_base) if phase == "regular" else latest


def _compact(item: Mapping[str, Any]) -> dict[str, Any]:
    compact = {
        key: item[key] for key in (
            "opportunity_id", "session_id", "trading_date", "symbol",
            "review_ts_ms", "pattern_types", "policy_results",
        )
    }
    compact["momentum_eligibility"] = item.get("momentum_eligibility") or {}
    return compact


def _holdout_trade_rows(
    opportunities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in opportunities:
        for policy in EVALUATED_POLICIES:
            result = item["policy_results"][policy]
            if not result["available"]:
                rows.append({
                    "opportunity_id": item["opportunity_id"], "policy": policy,
                    "trading_date": item["trading_date"], "symbol": item["symbol"],
                    "available": False, "reason": result["reason"],
                })
            for leg in result["legs"]:
                rows.append({
                    "opportunity_id": item["opportunity_id"], "policy": policy,
                    "trading_date": item["trading_date"], "symbol": item["symbol"],
                    "available": True, "reason": leg.get("reason") or "",
                    **{key: leg.get(key) for key in (
                        "status", "entry_ts_ms", "entry_price", "stop_price",
                        "target_price", "exit_ts_ms", "exit_price", "exit_reason",
                        "realized_r", "realized_pct", "mfe_r", "mae_r",
                    )},
                })
    return rows


def write_holdout_outputs(
    output_root: Path,
    report: Mapping[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "holdout-results.json").write_text(
        deterministic_json(dict(report)), encoding="utf-8"
    )
    fields = sorted({key for row in rows for key in row})
    with (root / "holdout-trades.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (root / "holdout-summary.md").write_text(
        _summary_markdown(report), encoding="utf-8"
    )
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir()) if path.is_file()
        and path.name != "artifact-hashes.json"
    }
    (root / "artifact-hashes.json").write_text(
        deterministic_json({"algorithm": "sha256", "files": hashes}),
        encoding="utf-8",
    )


def _summary_markdown(report: Mapping[str, Any]) -> str:
    readiness = report["minimum_size"]
    lines = [
        "# Prospective confirmed-entry holdout", "",
        "> Unseen-data holdout only. No tuning, policy selection, deployment, or live enablement is authorized.", "",
        f"Locked cutoff: `{report['locked_protocol']['cutoff_date']}`; only later trading dates are included.", "",
        "## Readiness", "",
        (
            f"Observed {readiness['observed_independent_trading_dates']} independent dates, "
            f"{readiness['observed_opportunities']} opportunities, and "
            f"{readiness['observed_paired_trades']} paired trades. Protocol assessment "
            f"ready: `{str(readiness['ready_for_locked_assessment']).lower()}`."
        ), "", "## Policy results", "",
        "| Policy | Trades | Wins | Losses | Timeouts | Net R | Average R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for policy in EVALUATED_POLICIES:
        if policy not in report["policy_results"]:
            continue
        item = report["policy_results"][policy]["aggregate"]
        average = "n/a" if item["average_r"] is None else f"{item['average_r']:.3f}"
        lines.append(
            f"| {policy} | {item['trades']} | {item['wins']} | {item['losses']} | "
            f"{item['timeouts']} | {item['net_r']:.3f} | {average} |"
        )
    paired = report["paired_selection_and_execution"]["overall"]
    lines += ["", "## Selection versus paired execution", "", (
        f"Both traded: {paired['both_policies_traded']}; baseline only: "
        f"{paired['baseline_only']}; confirmed only: {paired['confirmed_only']}; "
        f"neither: {paired['neither']}. Selection effect: "
        f"{paired['selection_effect_r']:.3f}R. Both-traded execution effect: "
        f"{paired['delayed_entry_execution_effect_r']:.3f}R."
    ), "", "Positive out-of-sample expectancy is required; merely losing less does not pass. No result from this report approves deployment.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the locked prospective confirmed-entry holdout."
    )
    parser.add_argument("recordings_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--cutoff-date", required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--end-date")
    args = parser.parse_args(argv)
    build_prospective_holdout(
        args.recordings_root, args.output_root,
        cutoff_date=args.cutoff_date, code_revision=args.code_revision,
        end_date=args.end_date,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
