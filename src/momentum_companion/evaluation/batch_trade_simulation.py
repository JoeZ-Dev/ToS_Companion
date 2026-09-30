from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

from momentum_companion.evaluation.trade_simulation import (
    SIMULATION_SCHEMA_VERSION,
    TradeSimulationPolicy,
    build_trade_simulation,
)
from momentum_companion.replay.catalog import RecordingCatalog


BATCH_SIMULATION_SCHEMA_VERSION = 1
POLICY_NAMES = (
    "fixed_2r",
    "trail_after_2r_retrace_15pct",
    "trail_after_2r_retrace_20pct",
    "trail_after_2r_retrace_25pct",
)


def build_batch_trade_simulation(
    recordings_root: Path,
    *,
    code_revision: str,
    policy: TradeSimulationPolicy | None = None,
    simulator: Callable[..., dict[str, Any]] = build_trade_simulation,
) -> dict[str, Any]:
    """Run the production simulator over every catalogued recording.

    The report intentionally has no wall-clock generation timestamp. Given the same
    recording corpus, simulator revision, and policy it serializes deterministically.
    """
    revision = str(code_revision or "").strip()
    if not revision:
        raise ValueError("code_revision is required")
    root = Path(recordings_root)
    active_policy = policy or TradeSimulationPolicy()
    catalog = RecordingCatalog(root)
    catalog_sessions = sorted(
        catalog.list_sessions(), key=lambda item: str(item["session_id"])
    )

    inventory_sessions: list[dict[str, Any]] = []
    session_results: list[dict[str, Any]] = []
    raw_trades: list[dict[str, Any]] = []
    raw_candidates: list[dict[str, Any]] = []

    for catalog_session in catalog_sessions:
        session_id = str(catalog_session["session_id"])
        integrity = catalog.integrity_report(session_id)
        simulation = simulator(root, session_id, policy=active_policy)
        simulation = {
            key: value
            for key, value in simulation.items()
            if key != "generated_at_utc"
        }
        trading_date = _trading_date(catalog_session)
        inventory = _inventory_entry(catalog_session, integrity, simulation)
        inventory_sessions.append(inventory)
        session_results.append(
            {
                "session_id": session_id,
                "trading_date": trading_date,
                "eligibility": inventory["eligibility"],
                "simulation": simulation,
            }
        )
        raw_candidates.extend(
            {**candidate, "trading_date": trading_date}
            for candidate in simulation.get("candidates") or []
        )
        raw_trades.extend(
            {**trade, "trading_date": trading_date}
            for trade in simulation.get("trades") or []
        )

    candidate_counts = Counter(
        str(candidate.get("status") or "UNKNOWN") for candidate in raw_candidates
    )
    candidate_reasons = Counter(
        str(candidate["reason"])
        for candidate in raw_candidates
        if candidate.get("reason")
    )
    trading_days = sorted(
        {str(item["trading_date"]) for item in inventory_sessions}
    )
    symbol_days = sorted(
        {
            (str(item["trading_date"]), str(symbol["symbol"]))
            for item in inventory_sessions
            for symbol in item["symbols"]
        }
    )

    report = {
        "schema_version": BATCH_SIMULATION_SCHEMA_VERSION,
        "kind": "batch_trade_simulation",
        "determinism": {
            "wall_clock_fields_omitted": True,
            "session_order": "session_id_ascending",
            "json_serialization": "sort_keys=True, indent=2, allow_nan=False",
        },
        "run_configuration": {
            "code_revision": revision,
            "simulator_schema_version": SIMULATION_SCHEMA_VERSION,
            "policy": active_policy.to_dict(),
            "policy_names": list(POLICY_NAMES),
        },
        "inventory": {
            "session_count": len(inventory_sessions),
            "trading_days": trading_days,
            "unique_trading_day_count": len(trading_days),
            "unique_symbol_day_count": len(symbol_days),
            "sessions": inventory_sessions,
        },
        "eligibility_summary": _eligibility_summary(inventory_sessions),
        "data_quality_totals": _data_quality_totals(
            inventory_sessions,
            raw_trades,
            candidate_counts,
            candidate_reasons,
        ),
        "aggregate_results": {
            name: _summarize_policy(raw_trades, name, len(raw_candidates))
            for name in POLICY_NAMES
        },
        "per_trading_day_results": _per_day_results(
            inventory_sessions, raw_candidates, raw_trades
        ),
        "per_symbol_day_results": _per_symbol_day_results(
            symbol_days, raw_candidates, raw_trades
        ),
        "independence": _independence_summary(
            trading_days, symbol_days, raw_trades
        ),
        "per_session_results": session_results,
        "raw_trade_records": raw_trades,
    }
    return report


def deterministic_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _inventory_entry(
    session: dict[str, Any],
    integrity: dict[str, Any],
    simulation: dict[str, Any],
) -> dict[str, Any]:
    started = session.get("started_at_et")
    ended = session.get("ended_at_et")
    symbols = []
    for symbol, quality in sorted((integrity.get("symbols") or {}).items()):
        first_ms = quality.get("first_timestamp_ms")
        last_ms = quality.get("last_timestamp_ms")
        symbols.append(
            {
                "symbol": symbol,
                "level_one_event_count": quality.get("level_one_event_count", 0),
                "first_timestamp_ms": first_ms,
                "last_timestamp_ms": last_ms,
                "recorded_duration_ms": (
                    int(last_ms) - int(first_ms)
                    if first_ms is not None and last_ms is not None
                    else None
                ),
                "malformed_row_count": quality.get("malformed_row_count", 0),
                "unresolved_gap_count": (quality.get("gaps") or {}).get(
                    "unresolved_count", 0
                ),
                "maximum_gap_ms": (quality.get("gaps") or {}).get(
                    "maximum_duration_ms", 0
                ),
                "halt_status_event_count": (quality.get("status_events") or {}).get(
                    "halt_count", 0
                ),
                "pattern_event_count": (quality.get("pattern_events") or {}).get(
                    "count", 0
                ),
                "pattern_state_counts": (quality.get("pattern_events") or {}).get(
                    "by_state", {}
                ),
                "limitations": [
                    warning.get("code")
                    for warning in quality.get("replay_confidence_warnings") or []
                ],
            }
        )
    return {
        "session_id": session["session_id"],
        "trading_date": _trading_date(session),
        "started_at_et": started,
        "ended_at_et": ended,
        "duration_ms": _iso_duration_ms(started, ended),
        "stop_reason": session.get("stop_reason"),
        "symbols": symbols,
        "totals": integrity.get("totals") or {},
        "limitations": [
            warning.get("code") for warning in integrity.get("warnings") or []
        ],
        "eligibility": _session_eligibility(integrity, simulation),
    }


def _session_eligibility(
    integrity: dict[str, Any], simulation: dict[str, Any]
) -> dict[str, Any]:
    summary = simulation.get("summary") or {}
    candidates = simulation.get("candidates") or []
    trades = simulation.get("trades") or []
    reasons: list[dict[str, Any]] = []
    status_counts = Counter(str(item.get("status") or "UNKNOWN") for item in candidates)
    reason_counts = Counter(
        str(item["reason"]) for item in candidates if item.get("reason")
    )
    incomplete_paths = sum(
        1 for trade in trades if not (trade.get("full_path") or {}).get("complete")
    )

    if not trades:
        pattern_events = int((integrity.get("totals") or {}).get("pattern_events") or 0)
        trigger_events = sum(
            int(count)
            for quality in (integrity.get("symbols") or {}).values()
            for state, count in ((quality.get("pattern_events") or {}).get("by_state") or {}).items()
            if state in {"BREAKOUT", "CONTINUATION"}
        )
        if not candidates and pattern_events == 0:
            reasons.append(
                {
                    "code": "pattern_journal_unavailable",
                    "count": 1,
                    "detail": "No persisted pattern journal exists, so production trigger candidates are unavailable.",
                }
            )
        elif not candidates and trigger_events == 0:
            reasons.append(
                {
                    "code": "no_trigger_candidates",
                    "count": 1,
                    "detail": "The journal contains no BREAKOUT or CONTINUATION trigger observations.",
                }
            )
        for reason, count in sorted(reason_counts.items()):
            reasons.append({"code": reason, "count": count})
        return {
            "status": "ineligible",
            "data_quality": "not_scored",
            "included_in_aggregate": False,
            "candidate_count": int(summary.get("candidate_count") or 0),
            "simulated_trade_count": 0,
            "reasons": reasons,
        }

    for reason, count in sorted(reason_counts.items()):
        reasons.append({"code": reason, "count": count})
    if incomplete_paths:
        reasons.append({"code": "incomplete_full_path", "count": incomplete_paths})
    partial = bool(
        incomplete_paths
        or status_counts.get("DATA_QUALITY_BLOCKED")
        or status_counts.get("SKIPPED_NO_ENTRY")
    )
    return {
        "status": "eligible",
        "data_quality": "partial" if partial else "complete",
        "included_in_aggregate": True,
        "candidate_count": int(summary.get("candidate_count") or 0),
        "simulated_trade_count": len(trades),
        "reasons": reasons,
    }


def _eligibility_summary(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        item for item in sessions if item["eligibility"]["status"] == "eligible"
    ]
    ineligible = [
        item for item in sessions if item["eligibility"]["status"] == "ineligible"
    ]
    partial = [
        item
        for item in eligible
        if item["eligibility"]["data_quality"] == "partial"
    ]
    return {
        "eligible_session_count": len(eligible),
        "eligible_complete_session_count": len(eligible) - len(partial),
        "eligible_partial_session_count": len(partial),
        "ineligible_session_count": len(ineligible),
        "eligible_session_ids": [item["session_id"] for item in eligible],
        "partial_session_ids": [item["session_id"] for item in partial],
        "ineligible_session_ids": [item["session_id"] for item in ineligible],
    }


def _data_quality_totals(
    sessions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    status_counts: Counter[str],
    reason_counts: Counter[str],
) -> dict[str, Any]:
    totals = [item["totals"] for item in sessions]
    complete_paths = sum(
        1 for trade in trades if (trade.get("full_path") or {}).get("complete")
    )
    malformed = sum(
        int(symbol.get("malformed_row_count") or 0)
        for session in sessions
        for symbol in session["symbols"]
    )
    return {
        "level_one_event_count": sum(
            int(symbol.get("level_one_event_count") or 0)
            for session in sessions
            for symbol in session["symbols"]
        ),
        "malformed_row_count": malformed,
        "unresolved_gap_count": sum(
            int(total.get("unresolved_gaps") or 0) for total in totals
        ),
        "halt_status_event_count": sum(
            int(total.get("halt_status_events") or 0) for total in totals
        ),
        "pattern_event_count": sum(
            int(total.get("pattern_events") or 0) for total in totals
        ),
        "provenance_incomplete_session_count": sum(
            "provenance_incomplete" in session["limitations"] for session in sessions
        ),
        "candidate_status_counts": dict(sorted(status_counts.items())),
        "candidate_exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "complete_full_path_count": complete_paths,
        "incomplete_full_path_count": len(trades) - complete_paths,
    }


def _summarize_policy(
    trades: Iterable[dict[str, Any]], policy_name: str, candidate_count: int
) -> dict[str, Any]:
    trade_list = list(trades)
    results = [
        (trade, (trade.get("exit_policy_results") or {}).get(policy_name) or {})
        for trade in trade_list
    ]
    available = [(trade, result) for trade, result in results if result.get("available")]
    realized_r = [float(result["realized_r"]) for _, result in available]
    realized_pct = [float(result["realized_pct"]) for _, result in available]
    mfe_pct = [float(trade["full_path"]["mfe_pct"]) for trade, _ in available]
    mae_pct = [float(trade["full_path"]["mae_pct"]) for trade, _ in available]
    mfe_r = [float(trade["full_path"]["mfe_r"]) for trade, _ in available]
    mae_r = [float(trade["full_path"]["mae_r"]) for trade, _ in available]
    complete = sum(
        1 for trade, _ in available if (trade.get("full_path") or {}).get("complete")
    )
    wins = sum(value > 0 for value in realized_r)
    losses = sum(value < 0 for value in realized_r)
    flats = len(realized_r) - wins - losses
    return {
        "candidate_count": candidate_count,
        "simulated_trade_count": len(available),
        "unavailable_trade_count": len(results) - len(available),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "timeouts": sum(result.get("exit_reason") == "TIMEOUT" for _, result in available),
        "win_rate": wins / len(available) if available else None,
        "net_r": sum(realized_r),
        "average_r": _average(realized_r),
        "median_r": median(realized_r) if realized_r else None,
        "combined_realized_pct": sum(realized_pct),
        "average_realized_pct": _average(realized_pct),
        "median_realized_pct": median(realized_pct) if realized_pct else None,
        "mfe": _excursion_summary(mfe_pct, mfe_r),
        "mae": _excursion_summary(mae_pct, mae_r),
        "complete_full_path_count": complete,
        "incomplete_full_path_count": len(available) - complete,
    }


def _excursion_summary(percentages: list[float], r_values: list[float]) -> dict[str, Any]:
    return {
        "average_pct": _average(percentages),
        "median_pct": median(percentages) if percentages else None,
        "minimum_pct": min(percentages) if percentages else None,
        "maximum_pct": max(percentages) if percentages else None,
        "average_r": _average(r_values),
        "median_r": median(r_values) if r_values else None,
        "minimum_r": min(r_values) if r_values else None,
        "maximum_r": max(r_values) if r_values else None,
    }


def _per_day_results(
    sessions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results = []
    for day in sorted({str(item["trading_date"]) for item in sessions}):
        day_candidates = [item for item in candidates if item["trading_date"] == day]
        day_trades = [item for item in trades if item["trading_date"] == day]
        results.append(
            {
                "trading_date": day,
                "session_ids": [
                    item["session_id"]
                    for item in sessions
                    if item["trading_date"] == day
                ],
                "policies": {
                    name: _summarize_policy(day_trades, name, len(day_candidates))
                    for name in POLICY_NAMES
                },
            }
        )
    return results


def _per_symbol_day_results(
    symbol_days: list[tuple[str, str]],
    candidates: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results = []
    for day, symbol in symbol_days:
        group_candidates = [
            item
            for item in candidates
            if item["trading_date"] == day and item.get("symbol") == symbol
        ]
        group_trades = [
            item
            for item in trades
            if item["trading_date"] == day and item.get("symbol") == symbol
        ]
        results.append(
            {
                "trading_date": day,
                "symbol": symbol,
                "policies": {
                    name: _summarize_policy(
                        group_trades, name, len(group_candidates)
                    )
                    for name in POLICY_NAMES
                },
            }
        )
    return results


def _independence_summary(
    trading_days: list[str],
    symbol_days: list[tuple[str, str]],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        by_group[(str(trade["trading_date"]), str(trade["symbol"]))].append(trade)

    concentration: dict[str, Any] = {}
    equal_weight: dict[str, Any] = {}
    for policy_name in POLICY_NAMES:
        groups = []
        for (day, symbol), group_trades in sorted(by_group.items()):
            summary = _summarize_policy(group_trades, policy_name, len(group_trades))
            if summary["simulated_trade_count"]:
                groups.append(
                    {
                        "trading_date": day,
                        "symbol": symbol,
                        "trade_count": summary["simulated_trade_count"],
                        "net_r": summary["net_r"],
                        "average_r": summary["average_r"],
                        "combined_realized_pct": summary["combined_realized_pct"],
                        "average_realized_pct": summary["average_realized_pct"],
                    }
                )
        groups.sort(key=lambda item: (-item["trade_count"], item["trading_date"], item["symbol"]))
        total_trades = sum(item["trade_count"] for item in groups)
        total_abs_net_r = sum(abs(float(item["net_r"])) for item in groups)
        ranked = []
        for item in groups:
            ranked.append(
                {
                    **item,
                    "trade_share": item["trade_count"] / total_trades if total_trades else None,
                    "absolute_net_r_share": (
                        abs(float(item["net_r"])) / total_abs_net_r
                        if total_abs_net_r
                        else None
                    ),
                }
            )
        overall = _summarize_policy(trades, policy_name, len(trades))
        equal_r = _average([float(item["average_r"]) for item in groups])
        equal_pct = _average(
            [float(item["average_realized_pct"]) for item in groups]
        )
        concentration[policy_name] = {
            "largest_symbol_day_groups": ranked,
            "largest_group_trade_share": ranked[0]["trade_share"] if ranked else None,
            "top_3_group_trade_share": (
                sum(item["trade_count"] for item in ranked[:3]) / total_trades
                if total_trades
                else None
            ),
        }
        equal_weight[policy_name] = {
            "contributing_symbol_day_count": len(groups),
            "trade_weighted_average_r": overall["average_r"],
            "equal_symbol_day_weighted_average_r": equal_r,
            "average_r_change": (
                equal_r - float(overall["average_r"])
                if equal_r is not None and overall["average_r"] is not None
                else None
            ),
            "trade_weighted_average_realized_pct": overall[
                "average_realized_pct"
            ],
            "equal_symbol_day_weighted_average_realized_pct": equal_pct,
            "average_realized_pct_change": (
                equal_pct - float(overall["average_realized_pct"])
                if equal_pct is not None
                and overall["average_realized_pct"] is not None
                else None
            ),
        }
    return {
        "warning": "Raw triggers and simulated trades are not independent observations.",
        "unique_trading_day_count": len(trading_days),
        "unique_symbol_day_count": len(symbol_days),
        "observed_symbol_day_with_trade_count": len(by_group),
        "concentration_by_policy": concentration,
        "equal_symbol_day_weighting": equal_weight,
    }


def _trading_date(session: dict[str, Any]) -> str:
    started = str(session.get("started_at_et") or "")
    return started[:10] if len(started) >= 10 else str(session["session_id"])[:10]


def _iso_duration_ms(started: Any, ended: Any) -> int | None:
    if not started or not ended:
        return None
    try:
        return round(
            (datetime.fromisoformat(str(ended)) - datetime.fromisoformat(str(started))).total_seconds()
            * 1000
        )
    except ValueError:
        return None


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic multi-session schema-v2 trade baseline."
    )
    parser.add_argument("recordings_root", type=Path)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = deterministic_json(
        build_batch_trade_simulation(
            args.recordings_root,
            code_revision=args.code_revision,
        )
    )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
