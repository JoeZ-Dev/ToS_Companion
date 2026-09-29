from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

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
EVALUATED_POLICIES = ("production_baseline", "confirmed_detector_stop")


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
                policy: evaluated[policy] for policy in EVALUATED_POLICIES
            }
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
    *, independent_trading_dates: int, opportunities: int, paired_trades: int
) -> dict[str, Any]:
    ready = (
        independent_trading_dates >= MINIMUM_TRADING_DATES
        and opportunities >= MINIMUM_OPPORTUNITIES
        and paired_trades >= MINIMUM_PAIRED_TRADES
    )
    return {
        "required_independent_trading_dates": MINIMUM_TRADING_DATES,
        "required_opportunities": MINIMUM_OPPORTUNITIES,
        "required_paired_trades": MINIMUM_PAIRED_TRADES,
        "observed_independent_trading_dates": independent_trading_dates,
        "observed_opportunities": opportunities,
        "observed_paired_trades": paired_trades,
        "ready_for_locked_assessment": ready,
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
    return {
        "assessment_allowed": readiness["ready_for_locked_assessment"],
        "positive_out_of_sample_expectancy_required": True,
        "losing_less_is_success": False,
        "confirmed_positive_expectancy": positive_expectancy,
        "paired_mean_delta_floor_r": PAIRED_MEAN_NONINFERIORITY_R,
        "paired_execution_not_materially_degraded": execution_not_materially_degraded,
        "protocol_passed": passed,
        "deployment_approved": False,
    }


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


def _compact(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item[key] for key in (
            "opportunity_id", "session_id", "trading_date", "symbol",
            "review_ts_ms", "pattern_types", "policy_results",
        )
    }


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
