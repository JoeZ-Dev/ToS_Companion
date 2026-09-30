from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import zlib
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from momentum_companion.evaluation.batch_trade_simulation import deterministic_json
from momentum_companion.evaluation.trade_simulation import (
    TRIGGER_STATES,
    TradeSimulationPolicy,
    _load_quote_timeline,
    build_trade_simulation,
)
from momentum_companion.replay.catalog import RecordingCatalog
from momentum_companion.replay.engine import ReplayEngine
from momentum_companion.review.corpus import ReviewCorpus


SCHEMA_VERSION = 1
DEFAULT_SEED = "tos-opportunity-review-v1"
CONTEXT_WINDOW_MS = 20 * 60 * 1000
CONTROL_QUIET_WINDOW_MS = TradeSimulationPolicy().cooldown_ms
CONTROL_GRID_MS = 5 * 60 * 1000
OUTCOME_WINDOW_MS = 15 * 60 * 1000
TRIGGERED_SAMPLE_SIZE = 50
CONTROL_SAMPLE_SIZE = 10
_NY = ZoneInfo("America/New_York")
_FORBIDDEN_BLINDED_KEYS = frozenset(
    {
        "exit",
        "exit_reason",
        "exit_price",
        "exit_ts_ms",
        "mfe",
        "mfe_pct",
        "mfe_r",
        "mae",
        "mae_pct",
        "mae_r",
        "net_r",
        "outcome",
        "pattern_type",
        "pattern_types",
        "realized_pct",
        "realized_r",
        "target_price",
        "win",
        "loss",
    }
)


class NoHistoryReplayEngine(ReplayEngine):
    """Replay recorded events without post-recording historical backfill."""

    def _seed_backfilled_history(self) -> None:
        return


def build_opportunity_review_export(
    recordings_root: Path,
    replay_overlays_root: Path,
    output_root: Path,
    *,
    code_revision: str,
    seed: str = DEFAULT_SEED,
    triggered_sample_size: int = TRIGGERED_SAMPLE_SIZE,
    control_sample_size: int = CONTROL_SAMPLE_SIZE,
    context_window_ms: int = CONTEXT_WINDOW_MS,
) -> dict[str, Any]:
    revision = str(code_revision or "").strip()
    if not revision:
        raise ValueError("code_revision is required")
    if triggered_sample_size <= 0 or control_sample_size <= 0:
        raise ValueError("sample sizes must be positive")
    if context_window_ms <= 0 or context_window_ms > 45 * 60 * 1000:
        raise ValueError("context_window_ms must be between 1 and 2700000")

    recordings = Path(recordings_root)
    overlays = Path(replay_overlays_root)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    sources = _source_sessions(recordings, overlays)
    if not sources:
        raise ValueError("no eligible replay or persisted-journal sessions found")

    source_before = _source_fingerprint(recordings, sources)
    opportunities: list[dict[str, Any]] = []
    simulations: dict[str, dict[str, Any]] = {}
    events_by_source: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        source_key = source["source_key"]
        catalog = RecordingCatalog(source["root"])
        events = catalog.load_pattern_events(source["session_id"])
        simulation = build_trade_simulation(source["root"], source["session_id"])
        simulation.pop("generated_at_utc", None)
        simulations[source_key] = simulation
        events_by_source[source_key] = events
        opportunities.extend(
            group_production_cooldown_opportunities(
                source,
                simulation.get("candidates") or [],
                events,
            )
        )

    opportunities.sort(key=_opportunity_sort_key)
    selected_opportunities = _deterministic_triggered_sample(
        opportunities,
        count=triggered_sample_size,
        seed=seed,
    )
    control_pool = _control_pool(sources, simulations, events_by_source)
    selected_controls = _deterministic_control_sample(
        control_pool,
        count=control_sample_size,
        seed=seed,
    )

    selected_items = _review_items(selected_opportunities, selected_controls, seed)
    packets = _build_causal_packets(selected_items, context_window_ms)
    blind_dir = destination / "blinded"
    triggered_dir = blind_dir / "triggered"
    control_dir = blind_dir / "controls"
    restricted_dir = destination / "restricted"
    triggered_dir.mkdir(parents=True, exist_ok=True)
    control_dir.mkdir(parents=True, exist_ok=True)
    restricted_dir.mkdir(parents=True, exist_ok=True)

    manifest_items: list[dict[str, Any]] = []
    machine_evidence: dict[str, Any] = {}
    outcomes: dict[str, Any] = {}
    rendered_pages: list[dict[str, Any]] = []
    source_by_key = {source["source_key"]: source for source in sources}
    opportunity_by_id = {
        item["opportunity_id"]: item for item in selected_opportunities
    }
    for item in selected_items:
        review_id = item["review_id"]
        packet = packets[review_id]
        blinded = _blinded_record(item, packet, context_window_ms)
        _assert_blinded_record(blinded)
        relative_png = Path("blinded") / item["kind_plural"] / f"{review_id}.png"
        png_path = destination / relative_png
        canvas = _render_chart(blinded)
        png_path.write_bytes(_encode_png(canvas))
        rendered_pages.append({"record": blinded, "canvas": canvas})
        manifest_items.append(
            {
                **blinded,
                "artifact_path": relative_png.as_posix(),
            }
        )

        source = source_by_key[item["source_key"]]
        if item["kind"] == "triggered":
            opportunity = opportunity_by_id[item["opportunity_id"]]
            machine_evidence[review_id] = _machine_evidence(
                opportunity,
                source,
                events_by_source[item["source_key"]],
            )
            outcomes[review_id] = _triggered_outcome(opportunity)
        else:
            machine_evidence[review_id] = {
                "kind": "control",
                "selection_rule": (
                    "active causal chart point with no engine trigger during the "
                    "preceding production cooldown interval"
                ),
                "source": _source_evidence(source),
            }
            outcomes[review_id] = {
                "kind": "control",
                "forward_window": _forward_quote_summary(
                    source,
                    item["symbol"],
                    int(item["review_ts_ms"]),
                ),
            }

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "blinded_opportunity_review_manifest",
        "run_configuration": {
            "code_revision": revision,
            "seed": seed,
            "grouping": "production_cooldown_grouping",
            "production_cooldown_ms": TradeSimulationPolicy().cooldown_ms,
            "context_window_ms": context_window_ms,
            "triggered_sample_size": triggered_sample_size,
            "control_sample_size": control_sample_size,
            "sampling_future_fields_used": False,
            "post_recording_history_used": False,
        },
        "blinding": {
            "bars_end_at_or_before_review_timestamp": True,
            "engine_pattern_withheld_from_primary_artifacts": True,
            "outcomes_separate": True,
            "forbidden_fields": sorted(_FORBIDDEN_BLINDED_KEYS),
        },
        "coverage": _sample_coverage(selected_opportunities, selected_controls),
        "items": manifest_items,
    }
    audit = _opportunity_audit(opportunities)
    pdf_path = destination / "blinded-review-pack.pdf"
    pdf_path.write_bytes(_encode_pdf(rendered_pages))
    (destination / "review-manifest.json").write_text(
        deterministic_json(manifest), encoding="utf-8"
    )
    (destination / "machine-evidence.json").write_text(
        deterministic_json(machine_evidence), encoding="utf-8"
    )
    (restricted_dir / "outcomes.json").write_text(
        deterministic_json(outcomes), encoding="utf-8"
    )
    (destination / "opportunity-audit.json").write_text(
        deterministic_json(audit), encoding="utf-8"
    )
    _write_label_template(destination / "labels.csv", manifest_items)

    source_after = _source_fingerprint(recordings, sources)
    if source_before != source_after:
        raise RuntimeError("source capture fingerprint changed during export")
    integrity = {
        "source_capture_sha256_before": source_before,
        "source_capture_sha256_after": source_after,
        "source_captures_byte_identical": True,
    }
    (destination / "source-integrity.json").write_text(
        deterministic_json(integrity), encoding="utf-8"
    )
    hashes = _artifact_hashes(destination)
    (destination / "artifact-hashes.json").write_text(
        deterministic_json(hashes), encoding="utf-8"
    )
    return {
        "manifest": manifest,
        "audit": audit,
        "integrity": integrity,
        "artifact_hashes": hashes,
    }


def group_production_cooldown_opportunities(
    source: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    pattern_events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach production cooldown suppressions to the preceding eligible candidate."""
    events = list(pattern_events)
    trigger_events_by_pattern: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if str(event.get("state") or "").upper() in TRIGGER_STATES:
            trigger_events_by_pattern[str(event.get("pattern_id") or "")].append(
                dict(event)
            )
    by_symbol: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_symbol[str(candidate.get("symbol") or "").upper()].append(candidate)

    groups: list[dict[str, Any]] = []
    for symbol, symbol_candidates in sorted(by_symbol.items()):
        current: dict[str, Any] | None = None
        for candidate in sorted(
            symbol_candidates,
            key=lambda value: (
                int(value.get("trigger_ts_ms") or 0),
                tuple(
                    str(item.get("pattern_id") or "")
                    for item in value.get("contributors") or []
                ),
            ),
        ):
            repeated = str(candidate.get("status") or "") == "SKIPPED_COOLDOWN"
            if not repeated or current is None:
                trigger_ms = int(candidate.get("trigger_ts_ms") or 0)
                identity = (
                    f"{source['source_key']}|{symbol}|{trigger_ms}|"
                    f"{len(groups)}"
                )
                current = {
                    "opportunity_id": "OPP-" + _sha256_text(identity)[:16],
                    "source_key": source["source_key"],
                    "source_root": source["root"],
                    "source_mode": source["source_mode"],
                    "status_evidence": source["status_evidence"],
                    "context_completeness": source["context_completeness"],
                    "session_id": source["session_id"],
                    "trading_date": source["trading_date"],
                    "started_at_et": source.get("started_at_et"),
                    "symbol": symbol,
                    "review_ts_ms": trigger_ms,
                    "candidates": [],
                }
                groups.append(current)
            assert current is not None
            current["candidates"].append(
                _candidate_evidence(candidate, repeated_signal=repeated)
            )

        for group in [item for item in groups if item["symbol"] == symbol]:
            pattern_ids = {
                str(contributor.get("pattern_id") or "")
                for candidate in group["candidates"]
                for contributor in candidate.get("contributors") or []
            }
            trigger_events = sorted(
                [
                    event
                    for pattern_id in pattern_ids
                    for event in trigger_events_by_pattern.get(pattern_id, [])
                ],
                key=lambda event: (
                    int(event.get("observation_ts_ms") or 0),
                    str(event.get("event_id") or ""),
                ),
            )
            group["trigger_transition_count"] = len(trigger_events)
            group["raw_candidate_count"] = len(group["candidates"])
            group["repeated_candidate_count"] = max(
                0, len(group["candidates"]) - 1
            )
            group["pattern_types"] = sorted(
                {
                    str(pattern)
                    for candidate in group["candidates"]
                    for pattern in candidate.get("pattern_types") or []
                }
            )
            group["candidate_pattern_cardinalities"] = [
                len(candidate.get("pattern_types") or [])
                for candidate in group["candidates"]
            ]
            group["simulated_trade_count"] = sum(
                candidate.get("production_status") == "SIMULATED"
                for candidate in group["candidates"]
            )
    return groups


def _candidate_evidence(
    candidate: Mapping[str, Any], *, repeated_signal: bool
) -> dict[str, Any]:
    return {
        "symbol": str(candidate.get("symbol") or ""),
        "trigger_ts_ms": int(candidate.get("trigger_ts_ms") or 0),
        "evaluated_bar_ts_ms": candidate.get("evaluated_bar_ts_ms"),
        "reference_price": candidate.get("reference_price"),
        "pattern_types": list(candidate.get("pattern_types") or []),
        "contributors": [
            {
                "pattern_id": item.get("pattern_id"),
                "pattern_type": item.get("pattern_type"),
                "trigger_state": item.get("trigger_state"),
                "trigger_ts_ms": item.get("trigger_ts_ms"),
                "evaluated_bar_ts_ms": item.get("evaluated_bar_ts_ms"),
                "stop_level": item.get("stop_level"),
                "stop_basis": item.get("stop_basis"),
            }
            for item in candidate.get("contributors") or []
        ],
        "candidate_role": (
            "repeated_signal" if repeated_signal else "opportunity_start"
        ),
        "production_status": candidate.get("status"),
        "production_reason": candidate.get("reason"),
        "outcome_reference": (
            dict(candidate.get("simulation") or {})
            if candidate.get("simulation") is not None
            else None
        ),
    }


def _source_sessions(recordings: Path, overlays: Path) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    replay_catalog = RecordingCatalog(overlays)
    for session in replay_catalog.list_sessions():
        day = _trading_date(session)
        if "2026-09-23" <= day <= "2026-09-25":
            sources.append(
                _source_record(
                    overlays,
                    session,
                    source_mode="replay_current_code",
                    status_evidence="unavailable",
                    context_completeness="partial",
                )
            )
    live_catalog = RecordingCatalog(recordings)
    for session in live_catalog.list_sessions():
        if _trading_date(session) != "2026-09-28":
            continue
        if not live_catalog.load_pattern_events(str(session["session_id"])):
            continue
        sources.append(
            _source_record(
                recordings,
                session,
                source_mode="persisted_live_journal",
                status_evidence="recorded_when_available",
                context_completeness="recorded_provenance",
            )
        )
    return sorted(sources, key=lambda item: item["source_key"])


def _source_record(
    root: Path,
    session: Mapping[str, Any],
    *,
    source_mode: str,
    status_evidence: str,
    context_completeness: str,
) -> dict[str, Any]:
    session_id = str(session["session_id"])
    return {
        "source_key": f"{source_mode}:{session_id}",
        "root": Path(root),
        "session_id": session_id,
        "trading_date": _trading_date(session),
        "symbols": sorted(str(value) for value in session.get("symbols") or []),
        "started_at_et": session.get("started_at_et"),
        "source_mode": source_mode,
        "status_evidence": status_evidence,
        "context_completeness": context_completeness,
    }


def _deterministic_triggered_sample(
    opportunities: list[dict[str, Any]], *, count: int, seed: str
) -> list[dict[str, Any]]:
    if len(opportunities) < count:
        raise ValueError(
            f"only {len(opportunities)} opportunities available for {count}"
        )
    dates = sorted({item["trading_date"] for item in opportunities})
    quotas = _balanced_quotas(dates, count)
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    covered: set[str] = set()
    while len(selected) < count:
        eligible_dates = [
            day
            for day in dates
            if sum(item["trading_date"] == day for item in selected) < quotas[day]
        ]
        if not eligible_dates:
            break
        day = eligible_dates[len(selected) % len(eligible_dates)]
        pool = [
            item
            for item in opportunities
            if item["trading_date"] == day and item["opportunity_id"] not in used
        ]
        if not pool:
            quotas[day] -= 1
            remaining = [value for value in dates if value != day]
            quotas[remaining[0]] += 1
            continue
        chosen = min(
            pool,
            key=lambda item: (
                -_coverage_score(_opportunity_features(item), covered),
                _seeded_rank(seed, item["opportunity_id"]),
            ),
        )
        selected.append(chosen)
        used.add(chosen["opportunity_id"])
        covered.update(_opportunity_features(chosen))
    return sorted(selected, key=_opportunity_sort_key)


def _balanced_quotas(values: list[str], total: int) -> dict[str, int]:
    base, extra = divmod(total, len(values))
    return {
        value: base + (1 if index < extra else 0)
        for index, value in enumerate(values)
    }


def _opportunity_features(item: Mapping[str, Any]) -> set[str]:
    repeated = int(item["repeated_candidate_count"])
    repeat_bucket = "none" if repeated == 0 else "few" if repeated <= 2 else "many"
    cardinality = (
        "multi"
        if any(value > 1 for value in item["candidate_pattern_cardinalities"])
        else "single"
    )
    return {
        f"symbol_day:{item['trading_date']}:{item['symbol']}",
        f"period:{_time_bucket(int(item['review_ts_ms']))}",
        f"cardinality:{cardinality}",
        f"repeat:{repeat_bucket}",
        *(f"pattern:{value}" for value in item["pattern_types"]),
    }


def _coverage_score(features: set[str], covered: set[str]) -> int:
    score = 0
    for feature in features - covered:
        if feature.startswith("symbol_day:"):
            score += 1000
        elif feature.startswith("pattern:"):
            score += 200
        else:
            score += 100
    return score


def _control_pool(
    sources: list[dict[str, Any]],
    simulations: Mapping[str, Mapping[str, Any]],
    events_by_source: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for source in sources:
        source_key = source["source_key"]
        candidate_times: dict[str, list[int]] = defaultdict(list)
        for candidate in simulations[source_key].get("candidates") or []:
            candidate_times[str(candidate.get("symbol") or "")].append(
                int(candidate.get("trigger_ts_ms") or 0)
            )
        raw_trigger_times: dict[str, list[int]] = defaultdict(list)
        for event in events_by_source[source_key]:
            if str(event.get("state") or "").upper() in TRIGGER_STATES:
                raw_trigger_times[str(event.get("symbol") or "")].append(
                    int(event.get("observation_ts_ms") or 0)
                )
        catalog = RecordingCatalog(source["root"])
        for symbol in source["symbols"]:
            events = catalog.load_events(source["session_id"], symbol)
            timestamps = [
                int(event["stream_ts_ms"])
                for event in events
                if event.get("kind") == "market_event"
            ]
            if not timestamps:
                continue
            next_grid = (
                (timestamps[0] + CONTEXT_WINDOW_MS + CONTROL_GRID_MS - 1)
                // CONTROL_GRID_MS
                * CONTROL_GRID_MS
            )
            index = 0
            while next_grid <= timestamps[-1]:
                while (
                    index + 1 < len(timestamps)
                    and timestamps[index + 1] <= next_grid
                ):
                    index += 1
                review_ts = timestamps[index]
                recent_count = sum(
                    review_ts - 5 * 60 * 1000 <= value <= review_ts
                    for value in timestamps
                )
                all_triggers = candidate_times[symbol] + raw_trigger_times[symbol]
                quiet = not any(
                    review_ts - CONTROL_QUIET_WINDOW_MS <= value <= review_ts
                    for value in all_triggers
                )
                if recent_count >= 20 and quiet:
                    identity = f"{source_key}|{symbol}|{review_ts}|control"
                    pool.append(
                        {
                            "control_id": "CONTROL-" + _sha256_text(identity)[:16],
                            "source_key": source_key,
                            "source_root": source["root"],
                            "session_id": source["session_id"],
                            "trading_date": source["trading_date"],
                            "symbol": symbol,
                            "review_ts_ms": review_ts,
                            "source_mode": source["source_mode"],
                            "started_at_et": source.get("started_at_et"),
                            "status_evidence": source["status_evidence"],
                            "context_completeness": source["context_completeness"],
                        }
                    )
                next_grid += CONTROL_GRID_MS
    return sorted(
        pool,
        key=lambda item: (
            item["trading_date"],
            item["symbol"],
            item["review_ts_ms"],
        ),
    )


def _deterministic_control_sample(
    controls: list[dict[str, Any]], *, count: int, seed: str
) -> list[dict[str, Any]]:
    if len(controls) < count:
        raise ValueError(f"only {len(controls)} controls available for {count}")
    dates = sorted({item["trading_date"] for item in controls})
    quotas = _balanced_quotas(dates, count)
    selected: list[dict[str, Any]] = []
    covered: set[str] = set()
    for day in dates:
        for _ in range(quotas[day]):
            pool = [
                item
                for item in controls
                if item["trading_date"] == day and item not in selected
            ]
            chosen = min(
                pool,
                key=lambda item: (
                    -_coverage_score(
                        {
                            f"symbol_day:{day}:{item['symbol']}",
                            f"period:{_time_bucket(int(item['review_ts_ms']))}",
                        },
                        covered,
                    ),
                    _seeded_rank(seed, item["control_id"]),
                ),
            )
            selected.append(chosen)
            covered.update(
                {
                    f"symbol_day:{day}:{chosen['symbol']}",
                    f"period:{_time_bucket(int(chosen['review_ts_ms']))}",
                }
            )
    return sorted(
        selected,
        key=lambda item: (
            item["trading_date"], item["symbol"], item["review_ts_ms"]
        ),
    )


def _review_items(
    opportunities: list[dict[str, Any]],
    controls: list[dict[str, Any]],
    seed: str,
) -> list[dict[str, Any]]:
    items = []
    for opportunity in opportunities:
        items.append(
            {
                **opportunity,
                "kind": "triggered",
                "kind_plural": "triggered",
                "review_id": "TRG-"
                + _sha256_text(f"{seed}|{opportunity['opportunity_id']}")[:12],
            }
        )
    for control in controls:
        items.append(
            {
                **control,
                "kind": "control",
                "kind_plural": "controls",
                "review_id": "CTL-"
                + _sha256_text(f"{seed}|{control['control_id']}")[:12],
            }
        )
    return sorted(items, key=lambda item: item["review_id"])


def _build_causal_packets(
    items: list[dict[str, Any]], context_window_ms: int
) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[
            (str(item["source_root"]), item["session_id"], item["symbol"])
        ].append(item)
    packets: dict[str, dict[str, Any]] = {}
    for (root, session_id, symbol), group_items in sorted(grouped.items()):
        engine = NoHistoryReplayEngine(recordings_root=Path(root))
        engine.load(session_id, symbol)
        for item in sorted(group_items, key=lambda value: value["review_ts_ms"]):
            review_ts = int(item["review_ts_ms"])
            target = engine.cursor_for_timestamp(review_ts)
            remaining = target - int(engine.snapshot()["replay"]["cursor"])
            if remaining > 0:
                engine.step(remaining)
            packet = ReviewCorpus._packet(
                engine,
                start_ms=review_ts - context_window_ms,
                end_ms=review_ts,
                availability={"status": "available"},
            )
            if int(packet["replay"]["current_ts_ms"] or 0) > review_ts:
                raise RuntimeError("replay advanced beyond review timestamp")
            if any(int(bar["ts"]) * 1000 > review_ts for bar in packet["bars_10s"]):
                raise RuntimeError("future bar entered blinded packet")
            packets[item["review_id"]] = packet
    return packets


def _blinded_record(
    item: Mapping[str, Any], packet: Mapping[str, Any], context_window_ms: int
) -> dict[str, Any]:
    review_ts = int(item["review_ts_ms"])
    bars = [
        {
            "ts": int(bar["ts"]),
            "open": bar.get("open"),
            "high": bar.get("high"),
            "low": bar.get("low"),
            "close": bar.get("close"),
            "volume": bar.get("volume"),
        }
        for bar in packet.get("bars_10s") or []
        if int(bar.get("ts") or 0) * 1000 <= review_ts
    ]
    vwap = [
        {"time": int(point["time"]), "value": point.get("value")}
        for point in packet.get("vwap_points") or []
        if int(point.get("time") or 0) * 1000 <= review_ts
    ]
    quote = packet.get("end_state", {}).get("quote") or {}
    bid = _number_or_none(quote.get("bid"))
    ask = _number_or_none(quote.get("ask"))
    spread = ask - bid if ask is not None and bid is not None else None
    first_event_ms = (
        packet.get("window", {}).get("availability", {}).get("first_event_ms")
    )
    started_ms = _parse_iso_ms(item.get("started_at_et"))
    if started_ms is None:
        started_ms = int(first_event_ms) if first_event_ms is not None else None
    return {
        "review_id": item["review_id"],
        "kind": item["kind"],
        "trading_date": item["trading_date"],
        "session_id": item["session_id"],
        "symbol": item["symbol"],
        "review_ts_ms": review_ts,
        "review_time_et": datetime.fromtimestamp(
            review_ts / 1000, tz=_NY
        ).isoformat(),
        "session_relative_ms": (
            review_ts - started_ms if started_ms is not None else None
        ),
        "time_bucket": _time_bucket(review_ts),
        "context_window_ms": context_window_ms,
        "context_start_ms": review_ts - context_window_ms,
        "context_truncated_at_recording_boundary": (
            bool(bars)
            and int(bars[0]["ts"]) * 1000 > review_ts - context_window_ms
        ),
        "bars_10s": bars,
        "vwap_points": vwap,
        "vwap_basis": "causal recorded L1 volume; no historical backfill",
        "current_quote": {
            "bid": bid,
            "ask": ask,
            "last": _number_or_none(quote.get("last")),
            "spread": spread,
            "spread_pct": (
                spread / ((ask + bid) / 2) * 100
                if spread is not None and ask is not None and bid is not None
                and ask + bid > 0
                else None
            ),
        },
        "source_mode": item["source_mode"],
        "status_evidence": item["status_evidence"],
        "context_completeness": item["context_completeness"],
        "data_quality": packet.get("data_quality") or {},
        "future_data_included": False,
        "engine_pattern_withheld": True,
    }


def _assert_blinded_record(record: Mapping[str, Any]) -> None:
    review_ts = int(record["review_ts_ms"])
    if record.get("future_data_included") is not False:
        raise ValueError("blinded record must explicitly exclude future data")
    if any(int(bar["ts"]) * 1000 > review_ts for bar in record["bars_10s"]):
        raise ValueError("blinded record contains a future bar")
    for key in _walk_keys(record):
        if key.lower() in _FORBIDDEN_BLINDED_KEYS:
            raise ValueError(f"forbidden blinded field: {key}")


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _machine_evidence(
    opportunity: Mapping[str, Any],
    source: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    pattern_ids = {
        str(contributor.get("pattern_id") or "")
        for candidate in opportunity["candidates"]
        for contributor in candidate.get("contributors") or []
    }
    evidence_events = [
        event
        for event in events
        if str(event.get("pattern_id") or "") in pattern_ids
        and str(event.get("state") or "").upper() in TRIGGER_STATES
    ]
    candidates = []
    for candidate in opportunity["candidates"]:
        candidates.append(
            {
                key: value
                for key, value in candidate.items()
                if key != "outcome_reference"
            }
        )
    return {
        "kind": "triggered",
        "grouping": "production_cooldown_grouping",
        "opportunity_id": opportunity["opportunity_id"],
        "source": _source_evidence(source),
        "review_ts_ms": opportunity["review_ts_ms"],
        "pattern_types": opportunity["pattern_types"],
        "raw_candidate_count": opportunity["raw_candidate_count"],
        "repeated_candidate_count": opportunity["repeated_candidate_count"],
        "trigger_transition_count": opportunity["trigger_transition_count"],
        "candidates": candidates,
        "detector_trigger_events": evidence_events,
    }


def _source_evidence(source: Mapping[str, Any]) -> dict[str, Any]:
    manifest = RecordingCatalog(source["root"]).load_manifest(source["session_id"])
    return {
        "session_id": source["session_id"],
        "source_mode": source["source_mode"],
        "status_evidence": source["status_evidence"],
        "context_completeness": source["context_completeness"],
        "provenance": manifest.get("provenance") or {},
    }


def _triggered_outcome(opportunity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "triggered",
        "opportunity_id": opportunity["opportunity_id"],
        "warning": "Restricted until validity labels are locked.",
        "candidate_outcomes": [
            {
                "trigger_ts_ms": candidate["trigger_ts_ms"],
                "production_status": candidate["production_status"],
                "production_reason": candidate["production_reason"],
                "simulation": candidate["outcome_reference"],
            }
            for candidate in opportunity["candidates"]
        ],
    }


def _forward_quote_summary(
    source: Mapping[str, Any], symbol: str, review_ts_ms: int
) -> dict[str, Any]:
    quotes = _load_quote_timeline(
        RecordingCatalog(source["root"]), source["session_id"], symbol
    )
    future = [
        quote
        for quote in quotes
        if review_ts_ms < int(quote["ts_ms"]) <= review_ts_ms + OUTCOME_WINDOW_MS
    ]
    bids = [float(item["bid"]) for item in future if _positive(item.get("bid"))]
    lasts = [float(item["last"]) for item in future if _positive(item.get("last"))]
    return {
        "horizon_ms": OUTCOME_WINDOW_MS,
        "quote_count": len(future),
        "first_ts_ms": int(future[0]["ts_ms"]) if future else None,
        "last_ts_ms": int(future[-1]["ts_ms"]) if future else None,
        "minimum_bid": min(bids) if bids else None,
        "maximum_bid": max(bids) if bids else None,
        "minimum_last": min(lasts) if lasts else None,
        "maximum_last": max(lasts) if lasts else None,
    }


def _opportunity_audit(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        raw_candidates = sum(item["raw_candidate_count"] for item in items)
        repeats = sum(item["repeated_candidate_count"] for item in items)
        patterns = Counter(
            pattern for item in items for pattern in item["pattern_types"]
        )
        compositions = Counter("+".join(item["pattern_types"]) for item in items)
        symbol_days = Counter(
            f"{item['trading_date']}:{item['symbol']}" for item in items
        )
        candidate_distribution = Counter(
            str(item["raw_candidate_count"]) for item in items
        )
        repeat_distribution = Counter(
            str(item["repeated_candidate_count"]) for item in items
        )
        trigger_distribution = Counter(
            str(item["trigger_transition_count"]) for item in items
        )
        trade_distribution = Counter(
            str(item["simulated_trade_count"]) for item in items
        )
        return {
            "opportunity_group_count": len(items),
            "raw_candidate_count": raw_candidates,
            "repeated_candidate_count": repeats,
            "repeated_candidate_share": (
                repeats / raw_candidates if raw_candidates else None
            ),
            "raw_candidates_per_opportunity": dict(
                sorted(candidate_distribution.items(), key=lambda x: int(x[0]))
            ),
            "repeated_signals_per_opportunity": dict(
                sorted(repeat_distribution.items(), key=lambda x: int(x[0]))
            ),
            "trigger_transitions_per_opportunity": dict(
                sorted(trigger_distribution.items(), key=lambda x: int(x[0]))
            ),
            "pattern_presence_by_opportunity": dict(sorted(patterns.items())),
            "pattern_composition_by_opportunity": dict(sorted(compositions.items())),
            "symbol_day_opportunity_counts": dict(sorted(symbol_days.items())),
            "simulated_trades_per_opportunity": dict(
                sorted(trade_distribution.items(), key=lambda x: int(x[0]))
            ),
            "opportunities_with_multiple_simulated_trades": sum(
                item["simulated_trade_count"] > 1 for item in items
            ),
        }

    replay = [
        item
        for item in opportunities
        if item["source_mode"] == "replay_current_code"
    ]
    persisted = [
        item
        for item in opportunities
        if item["source_mode"] == "persisted_live_journal"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "grouping": "production_cooldown_grouping",
        "grouping_policy": TradeSimulationPolicy().to_dict()["same_move_rule"],
        "all_sources": summary(opportunities),
        "exploratory_replay_2026_09_23_to_25": summary(replay),
        "persisted_live_2026_09_28": summary(persisted),
    }


def _sample_coverage(
    opportunities: list[dict[str, Any]], controls: list[dict[str, Any]]
) -> dict[str, Any]:
    patterns = Counter(
        pattern for item in opportunities for pattern in item["pattern_types"]
    )
    return {
        "triggered_count": len(opportunities),
        "control_count": len(controls),
        "triggered_by_date": dict(
            sorted(Counter(item["trading_date"] for item in opportunities).items())
        ),
        "controls_by_date": dict(
            sorted(Counter(item["trading_date"] for item in controls).items())
        ),
        "unique_triggered_symbol_day_count": len(
            {(item["trading_date"], item["symbol"]) for item in opportunities}
        ),
        "unique_control_symbol_day_count": len(
            {(item["trading_date"], item["symbol"]) for item in controls}
        ),
        "pattern_presence": dict(sorted(patterns.items())),
        "time_buckets": dict(
            sorted(
                Counter(
                    _time_bucket(int(item["review_ts_ms"]))
                    for item in opportunities
                ).items()
            )
        ),
        "single_pattern_opportunity_count": sum(
            len(item["pattern_types"]) == 1 for item in opportunities
        ),
        "multi_pattern_opportunity_count": sum(
            len(item["pattern_types"]) > 1 for item in opportunities
        ),
        "repeat_buckets": dict(
            sorted(
                Counter(
                    "none"
                    if item["repeated_candidate_count"] == 0
                    else "few"
                    if item["repeated_candidate_count"] <= 2
                    else "many"
                    for item in opportunities
                ).items()
            )
        ),
    }


def _write_label_template(path: Path, items: list[dict[str, Any]]) -> None:
    fields = [
        "review_id",
        "valid_setup",
        "human_pattern_types",
        "timing",
        "entry_quality",
        "stop_structure_visible",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in sorted(items, key=lambda value: value["review_id"]):
            writer.writerow({"review_id": item["review_id"]})


class _Canvas:
    def __init__(self, width: int = 1600, height: int = 900) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray((11, 18, 32) * (width * height))

    def point(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            index = (y * self.width + x) * 3
            self.pixels[index : index + 3] = bytes(color)

    def line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: tuple[int, int, int],
        width: int = 1,
    ) -> None:
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            for offset in range(-(width // 2), width // 2 + 1):
                self.point(x0 + offset, y0, color)
                self.point(x0, y0 + offset, color)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    def rect(
        self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]
    ) -> None:
        left, right = sorted((max(0, x0), min(self.width - 1, x1)))
        top, bottom = sorted((max(0, y0), min(self.height - 1, y1)))
        row = bytes(color) * (right - left + 1)
        for y in range(top, bottom + 1):
            start = (y * self.width + left) * 3
            self.pixels[start : start + len(row)] = row


def _render_chart(record: Mapping[str, Any]) -> _Canvas:
    canvas = _Canvas()
    left, right, top, bottom = 70, 1570, 45, 690
    volume_top, volume_bottom = 730, 855
    grid = (36, 49, 67)
    for index in range(6):
        y = top + (bottom - top) * index // 5
        canvas.line(left, y, right, y, grid)
    for index in range(7):
        x = left + (right - left) * index // 6
        canvas.line(x, top, x, volume_bottom, grid)
    bars = list(record.get("bars_10s") or [])
    prices = [
        float(bar[key])
        for bar in bars
        for key in ("high", "low")
        if _number_or_none(bar.get(key)) is not None
    ]
    prices.extend(
        float(point["value"])
        for point in record.get("vwap_points") or []
        if _number_or_none(point.get("value")) is not None
    )
    if not bars or not prices:
        canvas.line(left, top, right, bottom, (117, 131, 150), 3)
        canvas.line(left, bottom, right, top, (117, 131, 150), 3)
        return canvas
    low, high = min(prices), max(prices)
    padding = max((high - low) * 0.08, high * 0.002, 0.01)
    low -= padding
    high += padding
    start_ms = int(record["context_start_ms"])
    end_ms = int(record["review_ts_ms"])

    def x_for(ts_seconds: int) -> int:
        fraction = (ts_seconds * 1000 - start_ms) / max(1, end_ms - start_ms)
        return round(left + max(0.0, min(1.0, fraction)) * (right - left))

    def y_for(price: float) -> int:
        return round(bottom - (price - low) / max(1e-9, high - low) * (bottom - top))

    maximum_volume = max(float(bar.get("volume") or 0) for bar in bars) or 1.0
    candle_width = max(2, min(8, (right - left) // max(1, len(bars)) // 2))
    for bar in bars:
        values = [
            _number_or_none(bar.get(key))
            for key in ("open", "high", "low", "close")
        ]
        if any(value is None for value in values):
            continue
        open_price, high_price, low_price, close_price = (
            float(value) for value in values
        )
        x = x_for(int(bar["ts"]))
        color = (34, 197, 94) if close_price >= open_price else (239, 68, 68)
        canvas.line(x, y_for(low_price), x, y_for(high_price), color, 2)
        body_top = y_for(max(open_price, close_price))
        body_bottom = y_for(min(open_price, close_price))
        canvas.rect(
            x - candle_width,
            body_top,
            x + candle_width,
            max(body_top + 2, body_bottom),
            color,
        )
        volume_height = round(
            float(bar.get("volume") or 0)
            / maximum_volume
            * (volume_bottom - volume_top)
        )
        canvas.rect(
            x - candle_width,
            volume_bottom - volume_height,
            x + candle_width,
            volume_bottom,
            color,
        )
    vwap_points = [
        point
        for point in record.get("vwap_points") or []
        if _number_or_none(point.get("value")) is not None
    ]
    for first, second in zip(vwap_points, vwap_points[1:]):
        canvas.line(
            x_for(int(first["time"])),
            y_for(float(first["value"])),
            x_for(int(second["time"])),
            y_for(float(second["value"])),
            (251, 191, 36),
            3,
        )
    canvas.line(right, top, right, volume_bottom, (226, 232, 240), 3)
    return canvas


def _encode_png(canvas: _Canvas) -> bytes:
    raw = b"".join(
        b"\x00"
        + bytes(
            canvas.pixels[
                row * canvas.width * 3 : (row + 1) * canvas.width * 3
            ]
        )
        for row in range(canvas.height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", canvas.width, canvas.height, 8, 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )


def _encode_pdf(pages: list[dict[str, Any]]) -> bytes:
    objects: list[bytes] = []

    def reserve() -> int:
        objects.append(b"")
        return len(objects)

    def set_object(number: int, value: bytes) -> None:
        objects[number - 1] = value

    catalog_id = reserve()
    pages_id = reserve()
    font_id = reserve()
    page_ids: list[int] = []
    for index, page in enumerate(pages, start=1):
        canvas = page["canvas"]
        compressed = zlib.compress(bytes(canvas.pixels), level=9)
        image_id = reserve()
        set_object(
            image_id,
            (
                f"<< /Type /XObject /Subtype /Image /Width {canvas.width} "
                f"/Height {canvas.height} /ColorSpace /DeviceRGB "
                f"/BitsPerComponent 8 /Filter /FlateDecode "
                f"/Length {len(compressed)} >>\n"
            ).encode()
            + b"stream\n"
            + compressed
            + b"\nendstream",
        )
        content_id = reserve()
        record = page["record"]
        title = (
            f"{index:02d}/{len(pages):02d}  {record['review_id']}  "
            f"{record['trading_date']}  "
            f"{record['symbol']}  {record['review_time_et'][11:19]} ET"
        )
        subtitle = (
            "20-minute causal window ending at review time; "
            "pattern and outcome withheld"
        )
        quote = record["current_quote"]
        quote_text = (
            f"Bid {quote['bid']}   Ask {quote['ask']}   Spread {quote['spread']}   "
            f"Source {record['source_mode']}"
        )
        commands = (
            "q 720 0 0 405 36 110 cm /Im0 Do Q\n"
            "BT /F1 16 Tf 36 570 Td " + _pdf_text(title) + " Tj ET\n"
            "BT /F1 10 Tf 36 550 Td " + _pdf_text(subtitle) + " Tj ET\n"
            "BT /F1 9 Tf 36 530 Td " + _pdf_text(quote_text) + " Tj ET\n"
            "BT /F1 9 Tf 36 82 Td "
            + _pdf_text(
                "Label setup validity using only evidence on this page. "
                "Do not open restricted outcomes."
            )
            + " Tj ET\n"
        ).encode("latin-1", errors="replace")
        set_object(
            content_id,
            f"<< /Length {len(commands)} >>\nstream\n".encode()
            + commands
            + b"endstream",
        )
        page_id = reserve()
        page_ids.append(page_id)
        set_object(
            page_id,
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 792 612] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> "
                f"/XObject << /Im0 {image_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode(),
        )
    set_object(font_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    set_object(
        pages_id,
        (
            f"<< /Type /Pages /Count {len(page_ids)} /Kids ["
            + " ".join(f"{value} 0 R" for value in page_ids)
            + "] >>"
        ).encode(),
    )
    set_object(catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def _pdf_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"({escaped})"


def _artifact_hashes(root: Path) -> dict[str, Any]:
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "artifact-hashes.json"
    )
    return {
        "algorithm": "sha256",
        "files": {
            path.relative_to(root).as_posix(): _sha256_file(path) for path in paths
        },
    }


def _source_fingerprint(recordings: Path, sources: list[dict[str, Any]]) -> str:
    session_ids = sorted({source["session_id"] for source in sources})
    digest = hashlib.sha256()
    for session_id in session_ids:
        session_dir = recordings / session_id
        if not session_dir.exists():
            continue
        for path in sorted(item for item in session_dir.rglob("*") if item.is_file()):
            digest.update(path.relative_to(recordings).as_posix().encode())
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _opportunity_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        item["trading_date"],
        item["symbol"],
        int(item["review_ts_ms"]),
        item["opportunity_id"],
    )


def _seeded_rank(seed: str, identity: str) -> str:
    return _sha256_text(f"{seed}|{identity}")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _time_bucket(timestamp_ms: int) -> str:
    local = datetime.fromtimestamp(timestamp_ms / 1000, tz=_NY)
    minutes = local.hour * 60 + local.minute
    if minutes < 11 * 60:
        return "morning"
    if minutes < 14 * 60:
        return "midday"
    return "afternoon"


def _parse_iso_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        return round(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except ValueError:
        return None


def _trading_date(session: Mapping[str, Any]) -> str:
    started = str(session.get("started_at_et") or "")
    return started[:10] if len(started) >= 10 else str(session["session_id"])[:10]


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> bool:
    number = _number_or_none(value)
    return number is not None and number > 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic blinded opportunity review pack."
    )
    parser.add_argument("recordings_root", type=Path)
    parser.add_argument("replay_overlays_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--triggered-count", type=int, default=TRIGGERED_SAMPLE_SIZE)
    parser.add_argument("--control-count", type=int, default=CONTROL_SAMPLE_SIZE)
    parser.add_argument("--context-window-ms", type=int, default=CONTEXT_WINDOW_MS)
    args = parser.parse_args()
    build_opportunity_review_export(
        args.recordings_root,
        args.replay_overlays_root,
        args.output_root,
        code_revision=args.code_revision,
        seed=args.seed,
        triggered_sample_size=args.triggered_count,
        control_sample_size=args.control_count,
        context_window_ms=args.context_window_ms,
    )


if __name__ == "__main__":
    main()
