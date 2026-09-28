from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from momentum_companion.clients.stream_mapping import LevelOneCache
from momentum_companion.recording.integrity import build_integrity_report
from momentum_companion.replay.catalog import RecordingCatalog


SIMULATION_SCHEMA_VERSION = 1
TRIGGER_STATES = frozenset({"BREAKOUT", "CONTINUATION"})
UTC = timezone.utc


@dataclass(frozen=True)
class TradeSimulationPolicy:
    signal_merge_window_ms: int = 15_000
    cooldown_ms: int = 120_000
    entry_wait_ms: int = 10_000
    max_hold_ms: int = 15 * 60 * 1000
    target_r: float = 2.0
    stop_fill_slippage_bps: float = 0.0
    target_fill_slippage_bps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_merge_window_ms": self.signal_merge_window_ms,
            "cooldown_ms": self.cooldown_ms,
            "entry_wait_ms": self.entry_wait_ms,
            "max_hold_ms": self.max_hold_ms,
            "target_r": self.target_r,
            "entry_execution": "first recorded L1 ask at or after observable trigger",
            "exit_execution": "recorded L1 bid",
            "stop_rule": (
                "closest detector-supported invalidation level below entry; "
                "TIGHT_CONSOLIDATION_BREAKOUT may use evidence.breakdown_level"
            ),
            "target_rule": "entry + target_r * (entry - stop)",
            "same_move_rule": (
                "merge first trigger per pattern instance when trigger observations "
                "fall within signal_merge_window_ms; reject later candidates during cooldown"
            ),
            "stop_fill_slippage_bps": self.stop_fill_slippage_bps,
            "target_fill_slippage_bps": self.target_fill_slippage_bps,
            "position_sizing": "normalized 1R; no dollar/share sizing",
            "missing_stop_policy": "candidate retained but not scored as a simulated trade",
            "data_quality_policy": (
                "do not score through unresolved gaps, explicit halts, or end of recording"
            ),
        }


def build_trade_simulation(
    recordings_root: Path,
    session_id: str,
    *,
    symbol: str | None = None,
    policy: TradeSimulationPolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or TradeSimulationPolicy()
    _validate_policy(active_policy)

    root = Path(recordings_root)
    catalog = RecordingCatalog(root)
    manifest = catalog.load_manifest(session_id)
    requested_symbol = str(symbol or "").strip().upper() or None
    symbols = [
        str(value).strip().upper()
        for value in manifest.get("symbols") or []
        if str(value).strip()
    ]
    if requested_symbol is not None:
        if requested_symbol not in symbols:
            raise ValueError(f"{requested_symbol} is not recorded in session {session_id}")
        symbols = [requested_symbol]

    integrity = build_integrity_report(root / session_id)
    candidates: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for current_symbol in symbols:
        pattern_events = catalog.load_pattern_events(session_id, symbol=current_symbol)
        triggers = _first_trigger_events(pattern_events)
        merged = _merge_trigger_candidates(
            triggers,
            window_ms=active_policy.signal_merge_window_ms,
        )
        quotes = _load_quote_timeline(catalog, session_id, current_symbol)
        status_events = catalog.load_security_status_events(
            session_id, symbol=current_symbol
        )
        symbol_integrity = (integrity.get("symbols") or {}).get(current_symbol) or {}
        gaps = (symbol_integrity.get("gaps") or {}).get("details") or []
        last_recording_ms = symbol_integrity.get("last_timestamp_ms")

        cooldown_until = -1
        for candidate in merged:
            if int(candidate["trigger_ts_ms"]) < cooldown_until:
                candidates.append(
                    {
                        **candidate,
                        "status": "SKIPPED_COOLDOWN",
                        "reason": "candidate_triggered_during_cooldown",
                        "simulation": None,
                    }
                )
                continue

            result = _simulate_candidate(
                candidate,
                quotes=quotes,
                status_events=status_events,
                gaps=gaps,
                recording_last_ms=last_recording_ms,
                policy=active_policy,
            )
            candidates.append(result)
            if result["status"] == "SIMULATED":
                trades.append(result["simulation"])
                cooldown_until = (
                    int(candidate["trigger_ts_ms"]) + active_policy.cooldown_ms
                )
            elif result["status"] == "DATA_QUALITY_BLOCKED":
                cooldown_until = (
                    int(candidate["trigger_ts_ms"]) + active_policy.cooldown_ms
                )

    return {
        "schema_version": SIMULATION_SCHEMA_VERSION,
        "kind": "trade_simulation",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "session_id": session_id,
        "symbol_filter": requested_symbol,
        "policy": active_policy.to_dict(),
        "summary": _summarize(candidates, trades),
        "candidates": candidates,
        "trades": trades,
    }


def _validate_policy(policy: TradeSimulationPolicy) -> None:
    if policy.signal_merge_window_ms < 0:
        raise ValueError("signal_merge_window_ms must be non-negative")
    if policy.cooldown_ms < 0:
        raise ValueError("cooldown_ms must be non-negative")
    if policy.entry_wait_ms < 0:
        raise ValueError("entry_wait_ms must be non-negative")
    if policy.max_hold_ms <= 0:
        raise ValueError("max_hold_ms must be positive")
    if policy.target_r <= 0:
        raise ValueError("target_r must be positive")
    if policy.stop_fill_slippage_bps < 0 or policy.target_fill_slippage_bps < 0:
        raise ValueError("slippage bps must be non-negative")


def _first_trigger_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    triggers: dict[str, dict[str, Any]] = {}
    for event in sorted(
        events,
        key=lambda item: (
            int(item.get("observation_ts_ms") or 0),
            str(item.get("event_id") or ""),
        ),
    ):
        if str(event.get("state") or "").upper() not in TRIGGER_STATES:
            continue
        pattern_id = str(event.get("pattern_id") or "").strip()
        if pattern_id:
            triggers.setdefault(pattern_id, event)
    return sorted(
        triggers.values(),
        key=lambda item: (
            str(item.get("symbol") or ""),
            int(item.get("observation_ts_ms") or 0),
            str(item.get("pattern_id") or ""),
        ),
    )


def _merge_trigger_candidates(
    triggers: list[dict[str, Any]],
    *,
    window_ms: int,
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for trigger in triggers:
        trigger_ms = int(trigger.get("observation_ts_ms") or 0)
        if not groups:
            groups.append([trigger])
            continue
        previous_ms = int(groups[-1][-1].get("observation_ts_ms") or 0)
        same_symbol = str(groups[-1][0].get("symbol") or "") == str(
            trigger.get("symbol") or ""
        )
        if same_symbol and trigger_ms - previous_ms <= window_ms:
            groups[-1].append(trigger)
        else:
            groups.append([trigger])

    candidates: list[dict[str, Any]] = []
    for group in groups:
        trigger_ms = min(int(item.get("observation_ts_ms") or 0) for item in group)
        evaluated = [
            int(item["evaluated_bar_ts_ms"])
            for item in group
            if item.get("evaluated_bar_ts_ms") is not None
        ]
        reference_prices = [
            value
            for value in (_trigger_reference_price(item) for item in group)
            if value is not None
        ]
        candidates.append(
            {
                "session_id": group[0].get("session_id"),
                "symbol": str(group[0].get("symbol") or "").upper(),
                "trigger_ts_ms": trigger_ms,
                "evaluated_bar_ts_ms": min(evaluated) if evaluated else None,
                "contributors": [
                    {
                        "pattern_id": item.get("pattern_id"),
                        "pattern_type": item.get("pattern_type"),
                        "trigger_state": item.get("state"),
                        "trigger_ts_ms": int(item.get("observation_ts_ms") or 0),
                        "evaluated_bar_ts_ms": item.get("evaluated_bar_ts_ms"),
                        "stop_level": _detector_stop_level(item),
                        "stop_basis": _detector_stop_basis(item),
                    }
                    for item in group
                ],
                "pattern_types": sorted(
                    {
                        str(item.get("pattern_type") or "")
                        for item in group
                        if str(item.get("pattern_type") or "")
                    }
                ),
                "reference_price": reference_prices[0] if reference_prices else None,
            }
        )
    return candidates


def _simulate_candidate(
    candidate: dict[str, Any],
    *,
    quotes: list[dict[str, Any]],
    status_events: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    recording_last_ms: int | None,
    policy: TradeSimulationPolicy,
) -> dict[str, Any]:
    trigger_ms = int(candidate["trigger_ts_ms"])
    entry_quote = next(
        (
            quote
            for quote in quotes
            if trigger_ms <= int(quote["ts_ms"]) <= trigger_ms + policy.entry_wait_ms
            and _positive_float(quote.get("ask")) is not None
            and _positive_float(quote.get("bid")) is not None
        ),
        None,
    )
    if entry_quote is None:
        return {
            **candidate,
            "status": "SKIPPED_NO_ENTRY",
            "reason": "no_complete_l1_quote_within_entry_wait",
            "simulation": None,
        }

    entry_ts_ms = int(entry_quote["ts_ms"])
    entry_price = float(entry_quote["ask"])
    entry_bid = float(entry_quote["bid"])
    spread = max(0.0, entry_price - entry_bid)
    midpoint = (entry_price + entry_bid) / 2.0 if entry_price + entry_bid > 0 else None
    spread_pct = spread / midpoint * 100.0 if midpoint else None

    stop_candidates = []
    for contributor in candidate["contributors"]:
        level = _positive_float(contributor.get("stop_level"))
        if level is not None and level < entry_price:
            stop_candidates.append((level, contributor.get("stop_basis")))
    if not stop_candidates:
        return {
            **candidate,
            "status": "SKIPPED_NO_STOP",
            "reason": "no_detector_supported_stop_below_entry",
            "entry_observation": {
                "ts_ms": entry_ts_ms,
                "bid": entry_bid,
                "ask": entry_price,
                "spread": spread,
                "spread_pct": spread_pct,
            },
            "simulation": None,
        }

    stop_price, stop_basis = max(stop_candidates, key=lambda item: item[0])
    risk_per_share = entry_price - stop_price
    target_price = entry_price + policy.target_r * risk_per_share
    natural_end_ms = entry_ts_ms + policy.max_hold_ms

    barrier = _first_quality_barrier(
        trigger_ms=entry_ts_ms,
        requested_end_ms=natural_end_ms,
        status_events=status_events,
        gaps=gaps,
        recording_last_ms=recording_last_ms,
    )
    effective_end_ms = min(
        natural_end_ms,
        int(barrier["ts_ms"]) if barrier is not None else natural_end_ms,
    )

    path = [
        quote
        for quote in quotes
        if entry_ts_ms < int(quote["ts_ms"]) <= effective_end_ms
        and _positive_float(quote.get("bid")) is not None
    ]

    exit_reason = None
    exit_quote = None
    for quote in path:
        bid = float(quote["bid"])
        if bid <= stop_price:
            exit_reason = "STOP"
            exit_quote = quote
            break
        if bid >= target_price:
            exit_reason = "TARGET"
            exit_quote = quote
            break

    if exit_quote is None and barrier is not None and int(barrier["ts_ms"]) <= natural_end_ms:
        return {
            **candidate,
            "status": "DATA_QUALITY_BLOCKED",
            "reason": barrier["reason"],
            "entry_observation": {
                "ts_ms": entry_ts_ms,
                "bid": entry_bid,
                "ask": entry_price,
                "spread": spread,
                "spread_pct": spread_pct,
            },
            "stop": {"price": stop_price, "basis": stop_basis},
            "target": {"price": target_price, "r_multiple": policy.target_r},
            "simulation": None,
        }

    if exit_quote is None:
        exit_quote = _last_quote_at_or_before(quotes, natural_end_ms, after_ms=entry_ts_ms)
        if exit_quote is None:
            return {
                **candidate,
                "status": "DATA_QUALITY_BLOCKED",
                "reason": "no_exit_quote_before_timeout",
                "simulation": None,
            }
        exit_reason = "TIMEOUT"

    exit_ts_ms = int(exit_quote["ts_ms"])
    raw_exit_bid = float(exit_quote["bid"])
    if exit_reason == "STOP":
        fill_multiplier = 1.0 - policy.stop_fill_slippage_bps / 10_000.0
    elif exit_reason == "TARGET":
        fill_multiplier = 1.0 - policy.target_fill_slippage_bps / 10_000.0
    else:
        fill_multiplier = 1.0
    exit_price = raw_exit_bid * fill_multiplier

    observed_bids = [entry_bid] + [
        float(quote["bid"])
        for quote in quotes
        if entry_ts_ms < int(quote["ts_ms"]) <= exit_ts_ms
        and _positive_float(quote.get("bid")) is not None
    ]
    min_bid = min(observed_bids)
    max_bid = max(observed_bids)
    realized_per_share = exit_price - entry_price
    realized_pct = realized_per_share / entry_price * 100.0
    realized_r = realized_per_share / risk_per_share
    mae_pct = (min_bid - entry_price) / entry_price * 100.0
    mfe_pct = (max_bid - entry_price) / entry_price * 100.0

    reference = _positive_float(candidate.get("reference_price"))
    entry_slippage_pct = (
        (entry_price - reference) / reference * 100.0
        if reference is not None
        else None
    )

    simulation = {
        "session_id": candidate["session_id"],
        "symbol": candidate["symbol"],
        "trigger_ts_ms": trigger_ms,
        "entry_ts_ms": entry_ts_ms,
        "entry_price": entry_price,
        "entry_bid": entry_bid,
        "entry_spread": spread,
        "entry_spread_pct": spread_pct,
        "reference_price": reference,
        "entry_slippage_pct_vs_reference": entry_slippage_pct,
        "stop_price": stop_price,
        "stop_basis": stop_basis,
        "target_price": target_price,
        "target_r": policy.target_r,
        "exit_ts_ms": exit_ts_ms,
        "exit_price": exit_price,
        "raw_exit_bid": raw_exit_bid,
        "exit_reason": exit_reason,
        "holding_ms": exit_ts_ms - entry_ts_ms,
        "risk_per_share": risk_per_share,
        "realized_per_share": realized_per_share,
        "realized_pct": realized_pct,
        "realized_r": realized_r,
        "mae_pct_l1_bid": mae_pct,
        "mfe_pct_l1_bid": mfe_pct,
        "pattern_types": list(candidate["pattern_types"]),
        "contributors": list(candidate["contributors"]),
        "data_quality": {"blocked": False, "barrier": barrier},
    }
    return {
        **candidate,
        "status": "SIMULATED",
        "reason": None,
        "simulation": simulation,
    }


def _load_quote_timeline(
    catalog: RecordingCatalog,
    session_id: str,
    symbol: str,
) -> list[dict[str, Any]]:
    cache = LevelOneCache()
    quotes: list[dict[str, Any]] = []
    for record in catalog.load_events(session_id, symbol):
        if record.get("kind") != "market_event":
            continue
        message = {
            "service": "LEVELONE_EQUITIES",
            "timestamp": int(record["stream_ts_ms"]),
            "content": [dict(record["raw"])],
        }
        for quote in cache.process_messages(message):
            if str(quote.get("symbol") or "").strip().upper() != symbol:
                continue
            quotes.append(
                {
                    "ts_ms": int(quote["ts_ms"]),
                    "bid": quote.get("bid"),
                    "ask": quote.get("ask"),
                    "last": quote.get("last"),
                    "security_status": quote.get("security_status"),
                }
            )
    return quotes


def _first_quality_barrier(
    *,
    trigger_ms: int,
    requested_end_ms: int,
    status_events: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    recording_last_ms: int | None,
) -> dict[str, Any] | None:
    barriers: list[dict[str, Any]] = []
    if recording_last_ms is None or int(recording_last_ms) < requested_end_ms:
        if recording_last_ms is not None and int(recording_last_ms) > trigger_ms:
            barriers.append(
                {"ts_ms": int(recording_last_ms), "reason": "end_of_recording"}
            )
        elif recording_last_ms is None:
            barriers.append({"ts_ms": trigger_ms, "reason": "end_of_recording"})

    for gap in gaps:
        if gap.get("fully_repaired"):
            continue
        before_ms = int(gap.get("before_ms") or 0)
        after_ms = int(gap.get("after_ms") or 0)
        if before_ms > trigger_ms and before_ms <= requested_end_ms and after_ms > before_ms:
            barriers.append({"ts_ms": before_ms, "reason": "unresolved_gap"})

    for event in status_events:
        status = str(event.get("provider_status") or "").strip().lower()
        ts_ms = event.get("provider_ts_ms")
        if status in {"halted", "suspended"} and ts_ms is not None:
            value = int(ts_ms)
            if trigger_ms < value <= requested_end_ms:
                barriers.append({"ts_ms": value, "reason": "explicit_halt"})

    if not barriers:
        return None
    return min(barriers, key=lambda item: (int(item["ts_ms"]), item["reason"]))


def _last_quote_at_or_before(
    quotes: list[dict[str, Any]],
    target_ms: int,
    *,
    after_ms: int,
) -> dict[str, Any] | None:
    eligible = [
        quote
        for quote in quotes
        if after_ms < int(quote["ts_ms"]) <= target_ms
        and _positive_float(quote.get("bid")) is not None
    ]
    return eligible[-1] if eligible else None


def _detector_stop_level(trigger: dict[str, Any]) -> float | None:
    evidence = trigger.get("evidence") or {}
    level = _positive_float(evidence.get("invalidation_level"))
    if level is not None:
        return level
    if str(trigger.get("pattern_type") or "") == "TIGHT_CONSOLIDATION_BREAKOUT":
        return _positive_float(evidence.get("breakdown_level"))
    return None


def _detector_stop_basis(trigger: dict[str, Any]) -> str | None:
    evidence = trigger.get("evidence") or {}
    if _positive_float(evidence.get("invalidation_level")) is not None:
        return "detector_evidence.invalidation_level"
    if (
        str(trigger.get("pattern_type") or "") == "TIGHT_CONSOLIDATION_BREAKOUT"
        and _positive_float(evidence.get("breakdown_level")) is not None
    ):
        return "detector_evidence.breakdown_level"
    return None


def _trigger_reference_price(trigger: dict[str, Any]) -> float | None:
    context = trigger.get("trigger_context") or {}
    price_context = context.get("price") or {}
    value = _positive_float(price_context.get("value"))
    if value is not None:
        return value
    evidence = trigger.get("evidence") or {}
    for key in ("breakout_price", "last_close", "close"):
        value = _positive_float(evidence.get(key))
        if value is not None:
            return value
    return None


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _summarize(
    candidates: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    exit_reasons: dict[str, int] = {}
    for candidate in candidates:
        status = str(candidate.get("status") or "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
    for trade in trades:
        symbol = str(trade.get("symbol") or "")
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        reason = str(trade.get("exit_reason") or "UNKNOWN")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    realized_rs = [float(trade["realized_r"]) for trade in trades]
    realized_pcts = [float(trade["realized_pct"]) for trade in trades]
    wins = sum(value > 0 for value in realized_rs)
    losses = sum(value < 0 for value in realized_rs)
    flats = sum(value == 0 for value in realized_rs)
    return {
        "candidate_count": len(candidates),
        "simulated_trade_count": len(trades),
        "candidate_status_counts": by_status,
        "trades_by_symbol": by_symbol,
        "exit_reason_counts": exit_reasons,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": wins / len(trades) if trades else None,
        "net_r": sum(realized_rs),
        "average_r": sum(realized_rs) / len(realized_rs) if realized_rs else None,
        "net_compounded_return_not_calculated": True,
        "average_realized_pct": (
            sum(realized_pcts) / len(realized_pcts) if realized_pcts else None
        ),
        "interpretation": (
            "diagnostic execution-policy output; not validated expectancy and not a live trading recommendation"
        ),
    }
