from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from momentum_companion.evaluation.excursions import compute_excursions
from momentum_companion.recording.integrity import build_integrity_report
from momentum_companion.replay.engine import ReplayEngine

OUTCOME_SCHEMA_VERSION = 1
OUTCOME_FILENAME = "pattern_outcomes.json"
DEFAULT_HORIZON_MS = 15 * 60 * 1000
FORWARD_MINUTES = (1, 2, 5, 10, 15)
TRIGGER_STATES = frozenset({"BREAKOUT", "CONTINUATION"})
BAR_SELECTION_TOLERANCE_MS = 10_000
UTC = timezone.utc


def build_pattern_outcomes(
    recordings_root: Path,
    session_id: str,
    *,
    symbol: str | None = None,
    horizon_ms: int = DEFAULT_HORIZON_MS,
) -> dict[str, Any]:
    if int(horizon_ms) <= 0:
        raise ValueError("horizon_ms must be positive")
    engine = ReplayEngine(
        recordings_root=Path(recordings_root),
        max_bars_per_symbol=1_000_000,
    )
    manifest = engine.catalog.load_manifest(session_id)
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

    integrity = build_integrity_report(Path(recordings_root) / session_id)
    outcomes: list[dict[str, Any]] = []
    for current_symbol in symbols:
        events = engine.catalog.load_pattern_events(
            session_id, symbol=current_symbol
        )
        triggers = _first_trigger_events(events)
        if not triggers:
            continue
        loaded = engine.load(session_id, current_symbol)
        engine.seek(int(loaded.get("total_events") or 0))
        state = engine.session.snapshot()["symbols"].get(current_symbol) or {}
        bars = sorted(
            [dict(bar) for bar in state.get("bars_10s") or []],
            key=lambda bar: int(bar.get("ts") or 0),
        )
        status_events = engine.catalog.load_security_status_events(
            session_id, symbol=current_symbol
        )
        symbol_integrity = (integrity.get("symbols") or {}).get(current_symbol) or {}
        for trigger in triggers:
            outcomes.append(
                _measure_trigger(
                    trigger,
                    bars=bars,
                    status_events=status_events,
                    gaps=(symbol_integrity.get("gaps") or {}).get("details") or [],
                    recording_last_ms=symbol_integrity.get("last_timestamp_ms"),
                    horizon_ms=int(horizon_ms),
                )
            )

    return {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "kind": "pattern_outcome_measurements",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "session_id": session_id,
        "horizon_ms": int(horizon_ms),
        "forward_minutes": list(FORWARD_MINUTES),
        "bar_selection_rule": (
            "first observed bar timestamp at or within 10 seconds after target; "
            "no interpolation"
        ),
        "outcomes": outcomes,
    }


def write_pattern_outcomes(
    recordings_root: Path,
    session_id: str,
    *,
    horizon_ms: int = DEFAULT_HORIZON_MS,
) -> dict[str, Any]:
    report = build_pattern_outcomes(
        recordings_root,
        session_id,
        horizon_ms=horizon_ms,
    )
    path = Path(recordings_root) / session_id / OUTCOME_FILENAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return report


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
        pattern_id = str(event.get("pattern_id") or "")
        if pattern_id:
            triggers.setdefault(pattern_id, event)
    return list(triggers.values())


def _measure_trigger(
    trigger: dict[str, Any],
    *,
    bars: list[dict[str, Any]],
    status_events: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    recording_last_ms: int | None,
    horizon_ms: int,
) -> dict[str, Any]:
    trigger_ms = int(trigger.get("observation_ts_ms") or 0)
    requested_end_ms = trigger_ms + horizon_ms
    end_ms = requested_end_ms
    truncated_end = recording_last_ms is None or int(recording_last_ms) < end_ms
    if recording_last_ms is not None:
        end_ms = min(end_ms, int(recording_last_ms))

    intersecting_gaps = [
        gap
        for gap in gaps
        if int(gap.get("before_ms") or 0) > trigger_ms
        and int(gap.get("after_ms") or 0) < requested_end_ms
    ]
    unresolved = [gap for gap in intersecting_gaps if not gap.get("fully_repaired")]
    if unresolved:
        end_ms = min(end_ms, min(int(gap["after_ms"]) for gap in unresolved))

    halt_events = [
        event
        for event in status_events
        if str(event.get("provider_status") or "").strip().lower()
        in {"halted", "suspended"}
        and event.get("provider_ts_ms") is not None
        and trigger_ms < int(event["provider_ts_ms"]) <= requested_end_ms
    ]
    if halt_events:
        end_ms = min(end_ms, min(int(event["provider_ts_ms"]) for event in halt_events))

    entry_bar = _bar_at_or_just_after(bars, trigger_ms)
    entry_price = _float_or_none(entry_bar.get("close")) if entry_bar else None
    excursion = None
    if entry_bar is not None and entry_price is not None and entry_price > 0:
        future_bars = [
            bar for bar in bars if int(bar.get("ts") or 0) * 1000 > trigger_ms
        ]
        stats = compute_excursions(
            future_bars,
            entry_ts=trigger_ms // 1000,
            entry_price=entry_price,
            exit_ts=end_ms // 1000,
            side="long",
        )
        if stats is not None:
            excursion = {
                **stats.to_dict(),
                "mae_ts_ms": stats.mae_ts * 1000,
                "mfe_ts_ms": stats.mfe_ts * 1000,
                "time_to_mae_ms": stats.mae_ts * 1000 - trigger_ms,
                "time_to_mfe_ms": stats.mfe_ts * 1000 - trigger_ms,
            }

    forward_returns: dict[str, dict[str, Any]] = {}
    for minutes in FORWARD_MINUTES:
        target_ms = trigger_ms + minutes * 60_000
        if entry_price is None:
            forward_returns[str(minutes)] = _unavailable_return(
                target_ms, "entry_reference_unavailable"
            )
        elif target_ms > end_ms:
            forward_returns[str(minutes)] = _unavailable_return(
                target_ms, "measurement_horizon_truncated"
            )
        else:
            bar = _bar_at_or_just_after(bars, target_ms)
            price = _float_or_none(bar.get("close")) if bar else None
            if bar is None or price is None:
                forward_returns[str(minutes)] = _unavailable_return(
                    target_ms, "observation_unavailable"
                )
            else:
                forward_returns[str(minutes)] = {
                    "available": True,
                    "target_ts_ms": target_ms,
                    "observation_ts_ms": int(bar["ts"]) * 1000,
                    "price": price,
                    "return_pct": (price - entry_price) / entry_price * 100.0,
                }

    return {
        "session_id": trigger.get("session_id"),
        "symbol": trigger.get("symbol"),
        "pattern_id": trigger.get("pattern_id"),
        "pattern_type": trigger.get("pattern_type"),
        "trigger_state": trigger.get("state"),
        "trigger_ts_ms": trigger_ms,
        "source_mode": trigger.get("source_mode"),
        "entry_reference": {
            "available": entry_price is not None,
            "price": entry_price,
            "bar_ts_ms": int(entry_bar["ts"]) * 1000 if entry_bar else None,
            "basis": "trigger_bar_close" if entry_price is not None else None,
        },
        "excursion": excursion,
        "forward_returns": forward_returns,
        "invalidation": _measure_invalidation(trigger, bars, trigger_ms, end_ms),
        "measurement": {
            "requested_horizon_ms": horizon_ms,
            "requested_end_ts_ms": requested_end_ms,
            "actual_end_ts_ms": end_ms,
            "truncated": end_ms < requested_end_ms,
            "truncated_by_end_of_recording": truncated_end,
            "truncated_by_unresolved_gap": bool(unresolved),
            "truncated_by_halt": bool(halt_events),
            "repaired_gap_present": any(
                bool(gap.get("fully_repaired")) for gap in intersecting_gaps
            ),
            "data_quality_flags": [
                flag
                for flag, present in (
                    ("end_of_recording", truncated_end),
                    ("unresolved_gap", bool(unresolved)),
                    ("explicit_halt", bool(halt_events)),
                    (
                        "repaired_gap",
                        any(bool(gap.get("fully_repaired")) for gap in intersecting_gaps),
                    ),
                )
                if present
            ],
        },
    }


def _measure_invalidation(
    trigger: dict[str, Any],
    bars: list[dict[str, Any]],
    trigger_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    evidence = trigger.get("evidence") or {}
    level = evidence.get("invalidation_level")
    basis = "detector_evidence.invalidation_level"
    if level is None and trigger.get("pattern_type") == "TIGHT_CONSOLIDATION_BREAKOUT":
        level = evidence.get("breakdown_level")
        basis = "detector_evidence.breakdown_level"
    level_value = _float_or_none(level)
    if level_value is None:
        return {
            "available": False,
            "level": None,
            "basis": None,
            "first_breach_ts_ms": None,
            "time_to_invalidation_ms": None,
        }
    breach = next(
        (
            bar
            for bar in bars
            if trigger_ms < int(bar.get("ts") or 0) * 1000 <= end_ms
            and _float_or_none(bar.get("close")) is not None
            and float(bar["close"]) <= level_value
        ),
        None,
    )
    breach_ms = int(breach["ts"]) * 1000 if breach else None
    return {
        "available": True,
        "level": level_value,
        "basis": basis,
        "breach_rule": "bar_close_at_or_below_level",
        "first_breach_ts_ms": breach_ms,
        "time_to_invalidation_ms": breach_ms - trigger_ms if breach_ms is not None else None,
    }


def _bar_at_or_just_after(
    bars: Iterable[dict[str, Any]], target_ms: int
) -> dict[str, Any] | None:
    for bar in bars:
        observed_ms = int(bar.get("ts") or 0) * 1000
        if target_ms <= observed_ms <= target_ms + BAR_SELECTION_TOLERANCE_MS:
            return bar
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _unavailable_return(target_ms: int, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "target_ts_ms": target_ms,
        "observation_ts_ms": None,
        "price": None,
        "return_pct": None,
        "reason": reason,
    }
