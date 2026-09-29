from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any, Iterable, Mapping

MIN_BREAKOUT_ROOM_PCT = 8.0
PREFERRED_BREAKOUT_ROOM_PCT = 10.0
MIN_TIME_ADJUSTED_RVOL = 2.0
RVOL_LOOKBACK_SESSIONS = 20
RVOL_SOURCE = (
    "derived: cumulative LevelOne total_volume at the decision timestamp divided "
    "by the median cumulative total_volume at the same market-phase-relative "
    "timestamp across the previous 20 eligible sessions"
)


@dataclass(frozen=True)
class RvolObservation:
    trading_date: str
    market_phase: str
    phase_offset_seconds: int
    cumulative_volume: float


def calculate_time_adjusted_rvol(*, trading_date: str, market_phase: str,
    phase_offset_seconds: int, cumulative_volume: float | None,
    history: Iterable[RvolObservation | Mapping[str, Any]]) -> dict[str, Any]:
    if cumulative_volume is None or float(cumulative_volume) < 0:
        return _unavailable_rvol("current cumulative volume is unavailable")
    current_day = date.fromisoformat(trading_date)
    eligible: list[tuple[str, float]] = []
    for raw in history:
        item = raw if isinstance(raw, Mapping) else raw.__dict__
        try:
            prior_day = date.fromisoformat(str(item["trading_date"]))
            phase, offset = str(item["market_phase"]), int(item["phase_offset_seconds"])
            volume = float(item["cumulative_volume"])
        except (KeyError, TypeError, ValueError):
            continue
        if prior_day >= current_day or phase != market_phase or offset != phase_offset_seconds or volume < 0:
            continue
        eligible.append((prior_day.isoformat(), volume))
    eligible.sort(key=lambda item: item[0])
    eligible = eligible[-RVOL_LOOKBACK_SESSIONS:]
    if len(eligible) < RVOL_LOOKBACK_SESSIONS:
        return _unavailable_rvol(f"requires {RVOL_LOOKBACK_SESSIONS} previous eligible sessions; found {len(eligible)}")
    baseline = float(median(value for _, value in eligible))
    if baseline <= 0:
        return _unavailable_rvol("previous-session median cumulative volume is not positive")
    return {"status": "available", "value": float(cumulative_volume) / baseline,
        "current_cumulative_volume": float(cumulative_volume),
        "median_prior_cumulative_volume": baseline,
        "history_sessions": RVOL_LOOKBACK_SESSIONS, "source": RVOL_SOURCE}


def classify_momentum_eligibility(*, entry_price: float | None, decision_ts_ms: int,
    detector_structure_valid: bool, resistance_levels: Iterable[Mapping[str, Any]],
    resistance_evidence_complete: bool, rvol: Mapping[str, Any]) -> dict[str, Any]:
    """Classify eligibility without accepting bars or outcome fields."""
    room = _breakout_room(entry_price, decision_ts_ms, resistance_levels, resistance_evidence_complete)
    rvol_available = rvol.get("status") == "available" and rvol.get("value") is not None
    unavailable = []
    if room["status"] == "unavailable": unavailable.append(str(room["explanation"]))
    if not rvol_available: unavailable.append(str(rvol.get("explanation") or "time-adjusted RVOL is unavailable"))
    room_value = room.get("breakout_room_pct")
    rvol_value = float(rvol["value"]) if rvol_available else None
    room_pass = room_value is not None and float(room_value) >= MIN_BREAKOUT_ROOM_PCT
    preferred = room_value is not None and float(room_value) >= PREFERRED_BREAKOUT_ROOM_PCT
    rvol_pass = rvol_value is not None and rvol_value >= MIN_TIME_ADJUSTED_RVOL
    if unavailable:
        classification, explanation = "unavailable", "Unavailable: " + "; ".join(unavailable) + "."
    elif not detector_structure_valid or not room_pass or not rvol_pass:
        failed = []
        if not detector_structure_valid: failed.append("detector structure is not valid")
        if not room_pass: failed.append(f"{float(room_value):.2f}% breakout room")
        if not rvol_pass: failed.append(f"{float(rvol_value):.2f}× RVOL")
        classification, explanation = "monitor_only", "Monitor only: " + "; ".join(failed) + "."
    elif preferred:
        classification, explanation = "preferred_candidate", f"Preferred candidate: {float(room_value):.2f}% breakout room; {float(rvol_value):.2f}× RVOL."
    else:
        classification, explanation = "trade_candidate", f"Trade candidate: {float(room_value):.2f}% breakout room; {float(rvol_value):.2f}× RVOL."
    return {"classification": classification, "decision_ts_ms": int(decision_ts_ms),
        "breakout_room_pct": room_value, "limiting_resistance_type": room.get("limiting_resistance_type"),
        "limiting_resistance_price": room.get("limiting_resistance_price"),
        "breakout_room_status": room["status"], "time_adjusted_rvol": rvol_value,
        "explanation": explanation, "gates": {
            "valid_detector_structure": {"value": bool(detector_structure_valid), "passed": bool(detector_structure_valid)},
            "breakout_room": {"value_pct": room_value, "minimum_pct": MIN_BREAKOUT_ROOM_PCT,
                "preferred_pct": PREFERRED_BREAKOUT_ROOM_PCT, "passed": bool(room_pass), "preferred": bool(preferred)},
            "time_adjusted_rvol": {"value": rvol_value, "minimum": MIN_TIME_ADJUSTED_RVOL,
                "passed": bool(rvol_pass), "source": rvol.get("source", RVOL_SOURCE),
                "history_sessions": rvol.get("history_sessions")}}}


def unavailable_eligibility(*, decision_ts_ms: int, reason: str) -> dict[str, Any]:
    return classify_momentum_eligibility(entry_price=None, decision_ts_ms=decision_ts_ms,
        detector_structure_valid=False, resistance_levels=(), resistance_evidence_complete=False,
        rvol=_unavailable_rvol(reason))


def _breakout_room(entry_price, decision_ts_ms, resistance_levels, evidence_complete):
    if entry_price is None or float(entry_price) <= 0: return _unavailable_room("entry price is unavailable")
    candidates, saw = [], False
    for item in resistance_levels:
        available_at = item.get("available_at_ms")
        if available_at is None or int(available_at) > int(decision_ts_ms): continue
        try: price = float(item["price"])
        except (KeyError, TypeError, ValueError): continue
        saw = True
        if price > float(entry_price): candidates.append((price, str(item.get("type") or "known_resistance")))
    if not evidence_complete or not saw: return _unavailable_room("complete point-in-time resistance evidence is unavailable")
    if not candidates:
        return {"status": "at_least_preferred", "breakout_room_pct": PREFERRED_BREAKOUT_ROOM_PCT,
            "limiting_resistance_type": None, "limiting_resistance_price": None,
            "explanation": "no known overhead resistance through the preferred threshold"}
    price, level_type = min(candidates, key=lambda value: (value[0], value[1]))
    return {"status": "measured", "breakout_room_pct": ((price / float(entry_price)) - 1) * 100,
        "limiting_resistance_type": level_type, "limiting_resistance_price": price,
        "explanation": f"nearest causal overhead resistance is {level_type} at {price}"}


def _unavailable_room(reason):
    return {"status": "unavailable", "breakout_room_pct": None, "limiting_resistance_type": None,
        "limiting_resistance_price": None, "explanation": reason}


def _unavailable_rvol(reason):
    return {"status": "unavailable", "value": None, "history_sessions": 0,
        "source": RVOL_SOURCE, "explanation": reason}
