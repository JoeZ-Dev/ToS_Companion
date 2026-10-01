from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from momentum_companion.evaluation.batch_trade_simulation import deterministic_json
from momentum_companion.evaluation.prospective_holdout import (
    MINIMUM_OPPORTUNITIES,
    MINIMUM_PAIRED_TRADES,
    MINIMUM_TRADING_DATES,
)
from momentum_companion.recording.integrity import build_integrity_report


SCHEMA_VERSION = 1
ET = ZoneInfo("America/New_York")
ALLOWED_DATE_STATUSES = frozenset({"included", "pending", "excluded"})
ALLOWED_ELIGIBILITY = frozenset(
    {"trade_candidate", "preferred_candidate", "monitor_only", "unavailable"}
)
ALLOWED_INVENTORY_KEYS = frozenset(
    {
        "trading_date", "opportunity_id", "baseline_entered",
        "confirmed_entered", "momentum_evidence", "momentum_eligibility",
    }
)
FORBIDDEN_OUTCOME_KEYS = frozenset(
    {
        "average_r", "expectancy", "exit", "exit_price", "exit_reason",
        "exit_ts_ms", "loss", "losses", "mae", "mae_r", "mfe", "mfe_r",
        "net_r", "outcome", "pnl", "policy_comparison", "realized_pct",
        "realized_r", "return", "target_before_stop", "timeout", "timeouts",
        "win", "win_rate", "wins",
    }
)


def load_date_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("kind") != "prospective_holdout_date_manifest":
        raise ValueError("invalid prospective holdout date manifest")
    if payload.get("recorded_before_outcome_review") is not True:
        raise ValueError("date manifest must be recorded before outcome review")
    seen: set[str] = set()
    for item in payload.get("dates") or []:
        day = str(item.get("trading_date") or "")
        date.fromisoformat(day)
        if day in seen:
            raise ValueError(f"duplicate exact trading date in manifest: {day}")
        seen.add(day)
        status = str(item.get("status") or "")
        if status not in ALLOWED_DATE_STATUSES:
            raise ValueError(f"invalid date status for {day}: {status}")
        counts = item.get("counts_toward") or {}
        if status != "included" and any(bool(value) for value in counts.values()):
            raise ValueError(f"non-included date cannot count toward holdout: {day}")
    return payload


def load_outcome_blind_inventory(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    _assert_outcome_blind(payload)
    rows = payload.get("opportunities") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        raise ValueError("outcome-blind inventory must contain an opportunities list")
    answer = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("inventory opportunities must be objects")
        item = dict(raw)
        unknown = sorted(set(item) - ALLOWED_INVENTORY_KEYS)
        if unknown:
            raise ValueError(
                f"inventory contains fields outside the outcome-blind schema: {unknown}"
            )
        day = str(item.get("trading_date") or "")
        date.fromisoformat(day)
        opportunity_id = str(item.get("opportunity_id") or "").strip()
        if not opportunity_id:
            raise ValueError("inventory opportunity_id is required")
        for key in ("baseline_entered", "confirmed_entered"):
            if not isinstance(item.get(key), bool):
                raise ValueError(f"{key} must be boolean for {opportunity_id}")
        eligibility = str(item.get("momentum_eligibility") or "unavailable")
        if eligibility not in ALLOWED_ELIGIBILITY:
            raise ValueError(f"invalid momentum eligibility for {opportunity_id}")
        item["momentum_eligibility"] = eligibility
        answer.append(item)
    return answer


def build_progress_report(
    date_manifest: Mapping[str, Any],
    inventory: Iterable[Mapping[str, Any]],
    *,
    rvol_evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Build counts only. This function never accepts or emits outcome fields."""
    _assert_outcome_blind(inventory)
    dates = list(date_manifest.get("dates") or [])
    included = sorted(
        str(item["trading_date"]) for item in dates if item.get("status") == "included"
    )
    pending = sorted(
        str(item["trading_date"]) for item in dates if item.get("status") == "pending"
    )
    excluded = sorted(
        (
            {
                "trading_date": str(item["trading_date"]),
                "classification": str(item.get("classification") or "excluded"),
                "reason": str(item.get("reason") or "unspecified"),
            }
            for item in dates if item.get("status") == "excluded"
        ),
        key=lambda item: item["trading_date"],
    )
    included_set = set(included)
    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in inventory:
        item = dict(raw)
        day = str(item["trading_date"])
        if day not in included_set:
            continue
        key = (day, str(item["opportunity_id"]))
        previous = deduplicated.get(key)
        if previous is not None and previous != item:
            raise ValueError(f"conflicting duplicate opportunity on {day}: {key[1]}")
        deduplicated[key] = item
    rows = [deduplicated[key] for key in sorted(deduplicated)]
    paired = sum(
        bool(item["baseline_entered"] and item["confirmed_entered"])
        for item in rows
    )
    eligibility_counts = {
        value: sum(item["momentum_eligibility"] == value for item in rows)
        for value in sorted(ALLOWED_ELIGIBILITY)
    }
    sidecar = _rvol_sidecar_coverage(rvol_evidence_root)
    warnings = []
    if pending:
        warnings.append(
            f"Pending dates do not count: {', '.join(pending)}."
        )
    if included and not rows:
        warnings.append(
            "Included dates exist but no outcome-blind opportunity inventory was supplied."
        )
    incomplete_symbols = sidecar["symbols_total"] - sidecar["symbols_with_20_distinct_prior_dates"]
    if incomplete_symbols:
        warnings.append(
            f"{incomplete_symbols} enrolled symbol(s) lack 20 distinct prior RVOL dates."
        )
    progress = {
        "independent_trading_dates": _target_progress(len(included), MINIMUM_TRADING_DATES),
        "grouped_opportunities": _target_progress(len(rows), MINIMUM_OPPORTUNITIES),
        "paired_opportunities": _target_progress(paired, MINIMUM_PAIRED_TRADES),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "outcome_blind_prospective_holdout_progress",
        "dates": {
            "included": included,
            "pending": pending,
            "excluded": excluded,
        },
        "counts": {
            "grouped_opportunities": len(rows),
            "baseline_confirmed_paired_opportunities": paired,
            "momentum_evidence": sidecar,
            "momentum_eligibility": eligibility_counts,
        },
        "progress": progress,
        "data_completeness_warnings": warnings,
    }


def audit_capture_date(
    recordings_root: Path,
    trading_date: str,
    *,
    coverage_start_et: time = time(7, 0),
    minimum_end_et: time = time(10, 30),
    material_gap_seconds: int = 60,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect recording completeness without reading pattern or trade outcomes."""
    day = date.fromisoformat(trading_date)
    root = Path(recordings_root)
    current = (now or datetime.now(ET)).astimezone(ET)
    sessions = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(str(manifest.get("started_at_et")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if started.astimezone(ET).date() != day:
            continue
        ended_raw = manifest.get("ended_at_et")
        ended = datetime.fromisoformat(str(ended_raw)).astimezone(ET) if ended_raw else None
        first_events = _first_event_timestamps(manifest_path.parent, manifest.get("symbols") or [])
        integrity = build_integrity_report(manifest_path.parent)
        sessions.append(
            {
                "session_id": manifest_path.parent.name,
                "started_at_et": started.astimezone(ET).isoformat(),
                "ended_at_et": ended.isoformat() if ended else None,
                "first_event_timestamp_by_symbol": first_events,
                "unresolved_gap_count": int((integrity.get("totals") or {}).get("unresolved_gaps") or 0),
            }
        )
    required_start = datetime.combine(day, coverage_start_et, tzinfo=ET)
    required_end = datetime.combine(day, minimum_end_et, tzinfo=ET)
    intervals = sorted(
        (
            datetime.fromisoformat(item["started_at_et"]).astimezone(ET),
            datetime.fromisoformat(item["ended_at_et"]).astimezone(ET)
            if item["ended_at_et"] else min(current, required_end),
        )
        for item in sessions
    )
    gaps = _coverage_gaps(
        intervals, required_start, required_end,
        material_gap=timedelta(seconds=material_gap_seconds),
    )
    incomplete = any(item["ended_at_et"] is None for item in sessions)
    unresolved = sum(item["unresolved_gap_count"] for item in sessions)
    if current < required_end:
        disposition, reason = "pending", "required_window_not_complete"
    elif not sessions:
        disposition, reason = "exclude_candidate", "no_recording_sessions"
    elif incomplete:
        disposition, reason = "pending", "recording_or_required_window_incomplete"
    elif gaps:
        disposition, reason = "exclude_candidate", "material_uncovered_interval"
    elif unresolved:
        disposition, reason = "exclude_candidate", "unresolved_market_data_gaps"
    else:
        disposition, reason = "include_candidate", "capture_requirements_met"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "outcome_blind_capture_date_audit",
        "trading_date": trading_date,
        "required_window_et": {
            "start": required_start.isoformat(),
            "minimum_end": required_end.isoformat(),
            "material_gap_seconds": material_gap_seconds,
        },
        "sessions": sessions,
        "material_uncovered_intervals": gaps,
        "disposition": disposition,
        "reason": reason,
    }


def _coverage_gaps(intervals, start, end, *, material_gap):
    cursor = start
    gaps = []
    for left, right in intervals:
        if right <= start or left >= end:
            continue
        left, right = max(left, start), min(right, end)
        if left - cursor > material_gap:
            gaps.append({"start_et": cursor.isoformat(), "end_et": left.isoformat()})
        cursor = max(cursor, right)
    if end - cursor > material_gap:
        gaps.append({"start_et": cursor.isoformat(), "end_et": end.isoformat()})
    return gaps


def _first_event_timestamps(session_dir: Path, symbols: Iterable[Any]) -> dict[str, str | None]:
    answer = {}
    for raw_symbol in sorted({str(value).strip().upper() for value in symbols if str(value).strip()}):
        first = None
        try:
            handle = (session_dir / f"{raw_symbol}.jsonl").open(encoding="utf-8")
        except OSError:
            answer[raw_symbol] = None
            continue
        with handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    stamp = int(row.get("stream_ts_ms") or 0)
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
                if stamp and (first is None or stamp < first):
                    first = stamp
        answer[raw_symbol] = (
            datetime.fromtimestamp(first / 1000, tz=ET).isoformat() if first else None
        )
    return answer


def _rvol_sidecar_coverage(root: Path | None) -> dict[str, int]:
    if root is None or not Path(root).is_dir():
        return {"symbols_total": 0, "symbols_with_20_distinct_prior_dates": 0}
    total = adequate = 0
    for path in sorted(Path(root).glob("*.json")):
        total += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        days = {
            str(item.get("trading_date") or "")
            for item in payload.get("sessions") or []
            if str(item.get("trading_date") or "")
        }
        if len(days) >= 20:
            adequate += 1
    return {
        "symbols_total": total,
        "symbols_with_20_distinct_prior_dates": adequate,
    }


def _target_progress(observed: int, required: int) -> dict[str, Any]:
    return {
        "observed": observed,
        "required": required,
        "remaining": max(0, required - observed),
        "complete": observed >= required,
    }


def _assert_outcome_blind(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_OUTCOME_KEYS:
                raise ValueError(f"outcome field is forbidden in progress input: {key}")
            _assert_outcome_blind(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_outcome_blind(nested)


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Outcome-blind prospective holdout progress and capture audit."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    progress = commands.add_parser("progress")
    progress.add_argument("date_manifest", type=Path)
    progress.add_argument("--inventory", type=Path)
    progress.add_argument("--rvol-evidence-dir", type=Path)
    audit = commands.add_parser("audit-date")
    audit.add_argument("recordings_root", type=Path)
    audit.add_argument("--date", required=True)
    args = parser.parse_args()
    if args.command == "progress":
        result = build_progress_report(
            load_date_manifest(args.date_manifest),
            load_outcome_blind_inventory(args.inventory),
            rvol_evidence_root=args.rvol_evidence_dir,
        )
    else:
        result = audit_capture_date(args.recordings_root, args.date)
    print(deterministic_json(result), end="")


if __name__ == "__main__":
    _main()
