from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from momentum_companion.data.bar_aggregator import TenSecondBar
from momentum_companion.evaluation.batch_trade_simulation import (
    POLICY_NAMES,
    _data_quality_totals,
    _independence_summary,
    _summarize_policy,
    build_batch_trade_simulation,
    deterministic_json,
)
from momentum_companion.evaluation.trade_simulation import (
    TradeSimulationPolicy,
    build_trade_simulation,
)
from momentum_companion.recording.pattern_journal import build_pattern_event
from momentum_companion.recording.provenance import build_recording_provenance
from momentum_companion.recording.trigger_context import build_trigger_context
from momentum_companion.replay.catalog import RecordingCatalog
from momentum_companion.replay.engine import ReplayEngine


REPORT_SCHEMA_VERSION = 1
SOURCE_MODE = "replay_current_code"
STATUS_EVIDENCE = "unavailable"
CONTEXT_COMPLETENESS = "partial"
INACTIVITY_THRESHOLD_MS = 60_000
POST_INACTIVITY_EXCLUSION_MS = 5 * 60_000
TRIGGER_STATES = frozenset({"BREAKOUT", "CONTINUATION"})
VIEWS = (
    "inclusive_exploratory",
    "conservative_inactivity_exclusion",
    "strict_data_quality_exclusion",
)


class PatternJournalReplayEngine(ReplayEngine):
    """ReplayEngine adapter that captures production journal rows in memory.

    Historical backfill is deliberately not seeded. Pattern observations still
    travel through ReplayEngine's production quote, bar, AE, and detector path.
    """

    def __init__(self, *, recordings_root: Path, provenance: Mapping[str, Any]):
        self._journal_provenance = dict(provenance)
        self._last_pattern_snapshots: dict[tuple[str, str], str] = {}
        self.generated_pattern_events: list[dict[str, Any]] = []
        super().__init__(recordings_root=recordings_root)

    def _seed_backfilled_history(self) -> None:
        # Post-recording history files are not evidence captured at enrollment.
        return

    def _reset_analysis(self) -> None:
        super()._reset_analysis()
        if hasattr(self, "_last_pattern_snapshots"):
            self._last_pattern_snapshots.clear()
            self.generated_pattern_events.clear()

    def _handle_completed_bar(self, bar: TenSecondBar) -> None:
        before = len(self.pattern_timeline)
        super()._handle_completed_bar(bar)
        additions = self.pattern_timeline[before:]
        if not additions or self._symbol is None or self._session_id is None:
            return
        observation_ts_ms = int(additions[0]["observation_ts_ms"])
        symbol_state = (
            self.session.snapshot().get("symbols", {}).get(self._symbol) or {}
        )
        context = build_trigger_context(
            symbol_state=symbol_state,
            bar={
                "ts": bar.ts,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            },
            observation_ts_ms=observation_ts_ms,
        )
        context["replay_evidence"] = {
            "source_mode": SOURCE_MODE,
            "status_evidence": STATUS_EVIDENCE,
            "context_completeness": CONTEXT_COMPLETENESS,
            "post_recording_history_used": False,
        }
        for item in additions:
            event, fingerprint = build_pattern_event(
                session_id=self._session_id,
                observation=item["pattern"],
                observation_ts_ms=int(item["observation_ts_ms"]),
                provenance=self._journal_provenance,
                source_mode=SOURCE_MODE,
                trigger_context=context,
            )
            key = (event["symbol"], event["pattern_id"])
            if self._last_pattern_snapshots.get(key) == fingerprint:
                continue
            self._last_pattern_snapshots[key] = fingerprint
            # build_pattern_event intentionally uses wall time for live journals.
            # Replay replaces only that audit field with its causal observation time.
            event["recorded_at_utc"] = datetime.fromtimestamp(
                int(event["observation_ts_ms"]) / 1000,
                tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
            event["replay_evidence"] = dict(context["replay_evidence"])
            self.generated_pattern_events.append(event)


def build_replay_trade_baseline(
    recordings_root: Path,
    output_root: Path,
    *,
    code_revision: str,
    start_date: str = "2026-09-22",
    end_date: str = "2026-09-25",
    policy: TradeSimulationPolicy | None = None,
) -> dict[str, Any]:
    revision = str(code_revision or "").strip()
    if not revision:
        raise ValueError("code_revision is required")
    source_root = Path(recordings_root)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    active_policy = policy or TradeSimulationPolicy()
    catalog = RecordingCatalog(source_root)
    sessions = sorted(
        [
            item
            for item in catalog.list_sessions()
            if start_date <= _trading_date(item) <= end_date
        ],
        key=lambda item: str(item["session_id"]),
    )
    if not sessions:
        raise ValueError("no recording sessions matched the requested date range")

    source_fingerprint_before = _capture_fingerprint(source_root, sessions)
    provenance = build_recording_provenance(
        git_revision=revision,
        git_worktree_dirty=False,
    )
    provenance["source_mode"] = SOURCE_MODE

    generated: dict[str, dict[str, Any]] = {}
    for session in sessions:
        session_id = str(session["session_id"])
        integrity = catalog.integrity_report(session_id)
        events: list[dict[str, Any]] = []
        symbol_determinism: list[dict[str, Any]] = []
        for symbol in sorted(session["symbols"]):
            engine = PatternJournalReplayEngine(
                recordings_root=source_root,
                provenance=provenance,
            )
            loaded = engine.load(session_id, symbol)
            timestamps = [int(item["stream_ts_ms"]) for item in engine._events]
            if timestamps != sorted(timestamps):
                raise RuntimeError(f"non-causal replay order: {session_id}/{symbol}")
            engine.step(int(loaded["total_events"]))
            symbol_events = list(engine.generated_pattern_events)
            events.extend(symbol_events)
            symbol_determinism.append(
                {
                    "symbol": symbol,
                    "input_event_count": len(timestamps),
                    "timestamps_non_decreasing": True,
                    "first_timestamp_ms": timestamps[0] if timestamps else None,
                    "last_timestamp_ms": timestamps[-1] if timestamps else None,
                    "generated_pattern_event_count": len(symbol_events),
                    "generated_event_sha256": _fingerprint_json(symbol_events),
                    "post_recording_history_used": False,
                }
            )
        events.sort(
            key=lambda event: (
                int(event.get("observation_ts_ms") or 0),
                str(event.get("event_id") or ""),
            )
        )
        generated[session_id] = {
            "session": session,
            "integrity": integrity,
            "events": events,
            "symbol_replay": symbol_determinism,
            "detector_inventory_fingerprint": provenance["detectors"][
                "inventory_fingerprint"
            ],
        }

    view_results: dict[str, dict[str, Any]] = {}
    inclusive_candidates: dict[str, list[dict[str, Any]]] = {}
    conservative_candidates: dict[str, list[dict[str, Any]]] = {}
    for view_name in VIEWS:
        records: list[dict[str, Any]] = []
        for session_id, evidence in generated.items():
            gaps = _gaps_by_symbol(evidence["integrity"])
            inactivity_excluded: list[dict[str, Any]] = []
            gap_excluded: list[dict[str, Any]] = []
            if view_name == VIEWS[0]:
                selected_events = list(evidence["events"])
            else:
                inactivity_excluded = [
                    candidate
                    for candidate in inclusive_candidates[session_id]
                    if _candidate_after_inactivity(
                        candidate, gaps.get(candidate.get("symbol"), [])
                    )
                ]
                selected_events = _exclude_candidate_triggers(
                    evidence["events"], inactivity_excluded
                )
                if view_name == VIEWS[2]:
                    gap_excluded = [
                        candidate
                        for candidate in conservative_candidates[session_id]
                        if _candidate_overlaps_gap(
                            candidate, gaps.get(candidate.get("symbol"), [])
                        )
                    ]
                    selected_events = _exclude_candidate_triggers(
                        selected_events, gap_excluded
                    )
            overlay = _write_overlay_session(
                destination,
                view_name=view_name,
                source_root=source_root,
                session=evidence["session"],
                events=selected_events,
                provenance=provenance,
                code_revision=revision,
            )
            simulation = build_trade_simulation(
                overlay.parent,
                session_id,
                policy=active_policy,
            )
            simulation.pop("generated_at_utc", None)
            if view_name == VIEWS[0]:
                inclusive_candidates[session_id] = list(simulation["candidates"])
            elif view_name == VIEWS[1]:
                conservative_candidates[session_id] = list(simulation["candidates"])
            record = _session_view_record(
                evidence=evidence,
                selected_events=selected_events,
                simulation=simulation,
                view_name=view_name,
                inactivity_excluded=inactivity_excluded,
                gap_excluded=gap_excluded,
                code_revision=revision,
            )
            records.append(record)
        view_results[view_name] = _build_view_report(records, view_name=view_name)

    validated = build_batch_trade_simulation(
        source_root,
        code_revision=revision,
        policy=active_policy,
    )
    validated_day = [
        item
        for item in validated["per_trading_day_results"]
        if item["trading_date"] == "2026-09-28"
    ]
    validated_symbol_days = [
        item
        for item in validated["per_symbol_day_results"]
        if item["trading_date"] == "2026-09-28"
    ]
    validated_quality = _validated_day_quality(validated, "2026-09-28")
    source_fingerprint_after = _capture_fingerprint(source_root, sessions)
    if source_fingerprint_before != source_fingerprint_after:
        raise RuntimeError("source capture fingerprint changed during replay")

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "kind": "replay_current_code_trade_baseline",
        "run_configuration": {
            "code_revision": revision,
            "source_date_range": {"start": start_date, "end": end_date},
            "source_mode": SOURCE_MODE,
            "status_evidence": STATUS_EVIDENCE,
            "context_completeness": CONTEXT_COMPLETENESS,
            "post_recording_history_used": False,
            "policy": active_policy.to_dict(),
            "views": list(VIEWS),
        },
        "detector_provenance": provenance["detectors"],
        "source_capture_integrity": {
            "before_sha256": source_fingerprint_before,
            "after_sha256": source_fingerprint_after,
            "byte_identical": True,
        },
        "validated_persisted_baseline": {
            "classification": "validated_persisted_journal_only",
            "trading_date": "2026-09-28",
            "aggregate_results": validated["aggregate_results"],
            "per_trading_day_results": validated_day,
            "per_symbol_day_results": validated_symbol_days,
            "data_quality_totals": validated_quality,
        },
        "exploratory_replay_baseline": {
            "classification": "lower_confidence_exploratory_development",
            "warning": (
                "Status history is unavailable. Inactivity screens are sensitivity "
                "tests and are not assertions that a halt occurred."
            ),
            "views": view_results,
        },
        "cross_day_directional_comparison": _directional_comparison(view_results),
        "replay_generation": [
            {
                "session_id": session_id,
                "trading_date": _trading_date(evidence["session"]),
                "generated_pattern_event_count": len(evidence["events"]),
                "trigger_counts_by_pattern": _trigger_counts(evidence["events"]),
                "generated_event_sha256": _fingerprint_json(evidence["events"]),
                "symbol_replay": evidence["symbol_replay"],
                "status_evidence": STATUS_EVIDENCE,
                "context_completeness": CONTEXT_COMPLETENESS,
            }
            for session_id, evidence in generated.items()
        ],
        "determinism": {
            "wall_clock_fields_omitted_or_replaced_with_replay_time": True,
            "event_order": "stream_ts_ms_then_original_row_index",
            "output_serialization": "sort_keys=True, indent=2, allow_nan=False",
        },
    }
    return report


def _write_overlay_session(
    output_root: Path,
    *,
    view_name: str,
    source_root: Path,
    session: dict[str, Any],
    events: list[dict[str, Any]],
    provenance: dict[str, Any],
    code_revision: str,
) -> Path:
    session_id = str(session["session_id"])
    source_session = source_root / session_id
    overlay = output_root / "overlays" / view_name / session_id
    overlay.mkdir(parents=True, exist_ok=True)
    source_manifest = json.loads((source_session / "manifest.json").read_text())
    manifest = dict(source_manifest)
    manifest.pop("historical_backfill", None)
    manifest.pop("pre7_seeds", None)
    manifest["provenance"] = provenance
    manifest["derived_artifacts"] = {
        "pattern_events": {
            "path": "pattern_events.jsonl",
            "schema_version": 1,
            "source_mode": SOURCE_MODE,
        }
    }
    manifest["replay_evidence"] = {
        "code_revision": code_revision,
        "source_mode": SOURCE_MODE,
        "status_evidence": STATUS_EVIDENCE,
        "context_completeness": CONTEXT_COMPLETENESS,
        "post_recording_history_used": False,
        "sensitivity_view": view_name,
    }
    (overlay / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (overlay / "pattern_events.jsonl").write_text(
        "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    for symbol in session["symbols"]:
        target = overlay / f"{symbol}.jsonl"
        if target.is_symlink() or target.exists():
            target.unlink()
        os.symlink(source_session / f"{symbol}.jsonl", target)
    return overlay


def _exclude_candidate_triggers(
    events: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    excluded_pattern_ids = {
        str(contributor.get("pattern_id") or "")
        for candidate in candidates
        for contributor in candidate.get("contributors") or []
    }
    return [
        event
        for event in events
        if not (
            str(event.get("state") or "").upper() in TRIGGER_STATES
            and str(event.get("pattern_id") or "") in excluded_pattern_ids
        )
    ]


def _session_view_record(
    *,
    evidence: dict[str, Any],
    selected_events: list[dict[str, Any]],
    simulation: dict[str, Any],
    view_name: str,
    inactivity_excluded: list[dict[str, Any]],
    gap_excluded: list[dict[str, Any]],
    code_revision: str,
) -> dict[str, Any]:
    session = evidence["session"]
    metadata = {
        "source_mode": SOURCE_MODE,
        "status_evidence": STATUS_EVIDENCE,
        "context_completeness": CONTEXT_COMPLETENESS,
        "code_revision": code_revision,
        "detector_inventory_fingerprint": evidence[
            "detector_inventory_fingerprint"
        ],
    }
    candidates = [
        {**candidate, "research_evidence": metadata}
        for candidate in simulation.get("candidates") or []
    ]
    all_trades = [
        {**trade, "research_evidence": metadata}
        for trade in simulation.get("trades") or []
    ]
    retained_trades = (
        [
            trade
            for trade in all_trades
            if (trade.get("full_path") or {}).get("complete")
        ]
        if view_name == VIEWS[2]
        else all_trades
    )
    return {
        "session_id": session["session_id"],
        "trading_date": _trading_date(session),
        "symbols": list(session["symbols"]),
        "research_evidence": metadata,
        "generated_events": selected_events,
        "candidates": candidates,
        "trades": retained_trades,
        "all_simulated_trades_before_strict_path_filter": all_trades,
        "inactivity_excluded_candidates": inactivity_excluded,
        "gap_formation_excluded_candidates": gap_excluded,
    }


def _build_view_report(
    records: list[dict[str, Any]], *, view_name: str
) -> dict[str, Any]:
    days = sorted({record["trading_date"] for record in records})
    symbol_days = sorted(
        {
            (record["trading_date"], symbol)
            for record in records
            for symbol in record["symbols"]
        }
    )
    raw_trades = [
        {**trade, "trading_date": record["trading_date"]}
        for record in records
        for trade in record["trades"]
    ]
    return {
        "view": view_name,
        "aggregate_results": _group_summary(records),
        "per_trading_day_results": [
            {
                "trading_date": day,
                **_group_summary(
                    [record for record in records if record["trading_date"] == day]
                ),
            }
            for day in days
        ],
        "per_session_results": [
            {
                "session_id": record["session_id"],
                "trading_date": record["trading_date"],
                **_group_summary([record]),
                "research_evidence": record["research_evidence"],
            }
            for record in records
        ],
        "per_symbol_day_results": [
            {
                "trading_date": day,
                "symbol": symbol,
                **_group_summary(records, day=day, symbol=symbol),
            }
            for day, symbol in symbol_days
        ],
        "independence": _independence_summary(days, symbol_days, raw_trades),
        "raw_trade_records": raw_trades,
    }


def _validated_day_quality(report: dict[str, Any], day: str) -> dict[str, Any]:
    sessions = [
        item
        for item in report["inventory"]["sessions"]
        if item["trading_date"] == day
    ]
    results = [
        item
        for item in report["per_session_results"]
        if item["trading_date"] == day
    ]
    candidates = [
        candidate
        for item in results
        for candidate in item["simulation"].get("candidates") or []
    ]
    trades = [
        trade
        for item in results
        for trade in item["simulation"].get("trades") or []
    ]
    status_counts = Counter(
        str(candidate.get("status") or "UNKNOWN") for candidate in candidates
    )
    reason_counts = Counter(
        str(candidate["reason"])
        for candidate in candidates
        if candidate.get("reason")
    )
    return _data_quality_totals(
        sessions,
        trades,
        status_counts,
        reason_counts,
    )


def _group_summary(
    records: list[dict[str, Any]],
    *,
    day: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    events = [
        {**event, "trading_date": record["trading_date"]}
        for record in records
        for event in record["generated_events"]
        if (day is None or record["trading_date"] == day)
        and (symbol is None or event.get("symbol") == symbol)
    ]
    candidates = [
        {**candidate, "trading_date": record["trading_date"]}
        for record in records
        for candidate in record["candidates"]
        if (day is None or record["trading_date"] == day)
        and (symbol is None or candidate.get("symbol") == symbol)
    ]
    trades = [
        {**trade, "trading_date": record["trading_date"]}
        for record in records
        for trade in record["trades"]
        if (day is None or record["trading_date"] == day)
        and (symbol is None or trade.get("symbol") == symbol)
    ]
    all_trades = [
        {**trade, "trading_date": record["trading_date"]}
        for record in records
        for trade in record["all_simulated_trades_before_strict_path_filter"]
        if (day is None or record["trading_date"] == day)
        and (symbol is None or trade.get("symbol") == symbol)
    ]
    inactivity = [
        candidate
        for record in records
        for candidate in record["inactivity_excluded_candidates"]
        if (day is None or record["trading_date"] == day)
        and (symbol is None or candidate.get("symbol") == symbol)
    ]
    gap_formation = [
        candidate
        for record in records
        for candidate in record["gap_formation_excluded_candidates"]
        if (day is None or record["trading_date"] == day)
        and (symbol is None or candidate.get("symbol") == symbol)
    ]
    statuses = Counter(
        str(candidate.get("status") or "UNKNOWN") for candidate in candidates
    )
    reasons = Counter(
        str(candidate.get("reason"))
        for candidate in candidates
        if candidate.get("reason")
    )
    incomplete_filtered = len(all_trades) - len(trades)
    return {
        "generated_pattern_event_count": len(events),
        "trigger_counts_by_pattern": _trigger_counts(events),
        "merged_candidate_count": len(candidates),
        "simulated_trade_count": len(trades),
        "cooldown_exclusion_count": statuses.get("SKIPPED_COOLDOWN", 0),
        "missing_stop_exclusion_count": statuses.get("SKIPPED_NO_STOP", 0),
        "status_inactivity_exclusion_count": len(inactivity),
        "gap_data_quality_exclusion_count": (
            len(gap_formation)
            + statuses.get("DATA_QUALITY_BLOCKED", 0)
            + statuses.get("SKIPPED_NO_ENTRY", 0)
            + incomplete_filtered
        ),
        "gap_formation_exclusion_count": len(gap_formation),
        "incomplete_path_exclusion_count": incomplete_filtered,
        "recording_boundary_exclusion_count": reasons.get("end_of_recording", 0),
        "candidate_status_counts": dict(sorted(statuses.items())),
        "candidate_reason_counts": dict(sorted(reasons.items())),
        "policies": {
            name: _summarize_policy(trades, name, len(candidates))
            for name in POLICY_NAMES
        },
    }


def _directional_comparison(view_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for view_name, view in view_results.items():
        days = []
        for item in view["per_trading_day_results"]:
            policies = item["policies"]
            fixed = policies["fixed_2r"]
            trailing = {
                name: policies[name]["net_r"] for name in POLICY_NAMES[1:]
            }
            symbol_losses = sorted(
                [
                    {
                        "symbol": group["symbol"],
                        "net_r": group["policies"]["fixed_2r"]["net_r"],
                        "trade_count": group["policies"]["fixed_2r"][
                            "simulated_trade_count"
                        ],
                    }
                    for group in view["per_symbol_day_results"]
                    if group["trading_date"] == item["trading_date"]
                    and group["policies"]["fixed_2r"]["net_r"] < 0
                ],
                key=lambda value: (value["net_r"], value["symbol"]),
            )
            day_trades = [
                trade
                for trade in view["raw_trade_records"]
                if trade["trading_date"] == item["trading_date"]
            ]
            days.append(
                {
                    "trading_date": item["trading_date"],
                    "fixed_2r_net_r": fixed["net_r"],
                    "entry_engine_direction": (
                        "positive"
                        if fixed["net_r"] > 0
                        else "negative"
                        if fixed["net_r"] < 0
                        else "flat"
                    ),
                    "trailing_net_r": trailing,
                    "fixed_2r_outperforms_all_trailing": all(
                        fixed["net_r"] > value for value in trailing.values()
                    ),
                    "loss_attribution_by_pattern": _loss_attribution(day_trades),
                    "largest_losing_symbol_days": symbol_losses,
                }
            )
        result[view_name] = {
            "days": days,
            "remaining_trade_count": view["aggregate_results"]["simulated_trade_count"],
            "status_uncertainty_exclusion_count": view["aggregate_results"][
                "status_inactivity_exclusion_count"
            ],
        }
    return result


def _loss_attribution(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"losing_trade_count": 0, "net_r_on_losing_trades": 0.0}
    )
    for trade in trades:
        result = (trade.get("exit_policy_results") or {}).get("fixed_2r") or {}
        realized_r = float(result.get("realized_r") or 0.0)
        if realized_r >= 0:
            continue
        for pattern in trade.get("pattern_types") or ["UNKNOWN"]:
            values[str(pattern)]["losing_trade_count"] += 1
            values[str(pattern)]["net_r_on_losing_trades"] += realized_r
    return [
        {"pattern_type": pattern, **metrics}
        for pattern, metrics in sorted(
            values.items(),
            key=lambda item: (
                float(item[1]["net_r_on_losing_trades"]),
                item[0],
            ),
        )
    ]


def _gaps_by_symbol(integrity: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        symbol: list((quality.get("gaps") or {}).get("details") or [])
        for symbol, quality in (integrity.get("symbols") or {}).items()
    }


def _trigger_after_inactivity(
    event: Mapping[str, Any], gaps: list[dict[str, Any]]
) -> bool:
    trigger_ms = int(event.get("observation_ts_ms") or 0)
    return any(
        int(gap.get("duration_ms") or 0) >= INACTIVITY_THRESHOLD_MS
        and int(gap.get("before_ms") or 0)
        <= trigger_ms
        <= int(gap.get("before_ms") or 0) + POST_INACTIVITY_EXCLUSION_MS
        for gap in gaps
    )


def _pattern_overlaps_gap(
    event: Mapping[str, Any], gaps: list[dict[str, Any]]
) -> bool:
    start_ms = int(
        event.get("pattern_start_ts_ms") or event.get("observation_ts_ms") or 0
    )
    end_ms = int(event.get("observation_ts_ms") or 0)
    return any(
        start_ms < int(gap.get("before_ms") or 0)
        and end_ms > int(gap.get("after_ms") or 0)
        for gap in gaps
    )


def _candidate_after_inactivity(
    candidate: Mapping[str, Any], gaps: list[dict[str, Any]]
) -> bool:
    return _trigger_after_inactivity(
        {"observation_ts_ms": candidate.get("trigger_ts_ms")}, gaps
    )


def _candidate_overlaps_gap(
    candidate: Mapping[str, Any], gaps: list[dict[str, Any]]
) -> bool:
    start_values = [
        int(str(item.get("pattern_id") or "").rsplit(":", 1)[-1]) * 1000
        for item in candidate.get("contributors") or []
        if str(item.get("pattern_id") or "").rsplit(":", 1)[-1].isdigit()
    ]
    return _pattern_overlaps_gap(
        {
            "pattern_start_ts_ms": (
                min(start_values) if start_values else candidate.get("trigger_ts_ms")
            ),
            "observation_ts_ms": candidate.get("trigger_ts_ms"),
        },
        gaps,
    )


def _trigger_counts(events: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(
        str(event.get("pattern_type") or "UNKNOWN")
        for event in events
        if str(event.get("state") or "").upper() in TRIGGER_STATES
    )
    return dict(sorted(counts.items()))


def _capture_fingerprint(
    root: Path, sessions: list[dict[str, Any]]
) -> str:
    digest = hashlib.sha256()
    for session in sessions:
        session_dir = root / str(session["session_id"])
        for path in sorted(item for item in session_dir.iterdir() if item.is_file()):
            digest.update(path.relative_to(root).as_posix().encode())
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _fingerprint_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _trading_date(session: Mapping[str, Any]) -> str:
    started = str(session.get("started_at_et") or "")
    return started[:10] if len(started) >= 10 else str(session["session_id"])[:10]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build separated persisted and exploratory replay trade baselines."
    )
    parser.add_argument("recordings_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--start-date", default="2026-09-22")
    parser.add_argument("--end-date", default="2026-09-25")
    parser.add_argument("--report-name", default="replay-trade-baseline.json")
    args = parser.parse_args()
    report = build_replay_trade_baseline(
        args.recordings_root,
        args.output_root,
        code_revision=args.code_revision,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    (args.output_root / args.report_name).write_text(
        deterministic_json(report), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
