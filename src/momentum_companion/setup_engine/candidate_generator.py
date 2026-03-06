from __future__ import annotations

from typing import Any, Dict, List


def _current_price(quote: dict) -> float | None:
    bid = quote.get("bid")
    ask = quote.get("ask")
    last = quote.get("last")
    mid = (bid + ask) / 2 if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) else None
    for val in (last, mid, bid, ask):
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _risk_reward_valid(entry: float, stop: float, target: float) -> bool:
    risk = entry - stop
    reward = target - entry
    if risk <= 0 or reward <= 0:
        return False
    move_pct = reward / entry if entry else 0.0
    return move_pct >= 0.015


def _swing_high_above(bars_window: list[dict] | None, current_price: float) -> float | None:
    if not bars_window:
        return None
    highs_above: list[float] = []
    for b in bars_window:
        if not isinstance(b, dict):
            continue
        h = b.get("h")
        try:
            h_f = float(h)
        except Exception:
            continue
        if h_f > current_price:
            highs_above.append(h_f)
    return min(highs_above) if highs_above else None


def _structural_targets_above(entry: float, entry_label: str, payload: Dict[str, Any]) -> tuple[float | None, str | None]:
    """Return first structural level above entry with matching label."""
    levels = payload.get("levels") or {}
    micro = payload.get("micro") or {}
    session = payload.get("session") or {}
    bars_window = payload.get("bars_window") or []
    targets: list[tuple[float, str]] = []
    nr = levels.get("nearest_resistance") if isinstance(levels, dict) else None
    if isinstance(nr, dict) and nr.get("price") is not None:
        targets.append((float(nr.get("price")), "nearest_resistance"))
    micro_res = micro.get("micro_resistance_15m") if isinstance(micro, dict) else None
    if micro_res is not None:
        targets.append((float(micro_res), "micro_resistance_15m"))
    orh = session.get("opening_range_high") if isinstance(session, dict) else None
    if orh is not None:
        targets.append((float(orh), "opening_range_high"))
    pmh = session.get("premarket_high") if isinstance(session, dict) else None
    if pmh is not None:
        targets.append((float(pmh), "premarket_high"))
    swing = _swing_high_above(bars_window, entry)
    if swing is not None:
        targets.append((float(swing), "swing_high"))

    for price, label in targets:
        if price > entry and label != entry_label:
            return price, label
    return None, None


def generate_candidate_setups(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic candidate setups using normalized snapshot fields."""
    quote = payload.get("quote") or {}
    current_price = _current_price(quote)
    if current_price is None:
        return []
    levels = payload.get("levels") or {}
    micro = payload.get("micro") or {}
    session = payload.get("session") or {}
    bars_window = payload.get("bars_window") or []
    structure_context = payload.get("structure_context") or {}
    volume_structure = payload.get("volume_structure") or {}
    candidates: list[dict] = []

    # gate for tight resistance unless breakout
    tight_res = structure_context.get("next_resistance_distance_pct")
    tight_res_block = tight_res is not None and isinstance(tight_res, (int, float)) and tight_res < 0.4

    def _append_candidate(c: dict) -> None:
        if volume_structure.get("volume_state") == "DISTRIBUTION":
            note = c.get("notes", "")
            if "distribution" not in note.lower():
                c["notes"] = (note + " distribution; require hold/retest").strip()
        candidates.append(c)

    # A) nearest_resistance breakout
    nr = levels.get("nearest_resistance") if isinstance(levels, dict) else None
    nr_price = nr.get("price") if isinstance(nr, dict) else None
    try:
        nr_price_f = float(nr_price) if nr_price is not None else None
    except Exception:
        nr_price_f = None
    if nr_price_f and nr_price_f > current_price:
        entry = nr_price_f
        stop = max(current_price * 0.985, entry * 0.985)
        target, label = _structural_targets_above(entry, "nearest_resistance", payload)
        if target is not None and label is not None and _risk_reward_valid(entry, stop, target):
            _append_candidate(
                {
                    "name": "NEAREST_RES_BREAK_HOLD",
                    "entry_trigger_price": entry,
                    "stop_price": stop,
                    "target_price": target,
                    "target1_label": label,
                    "notes": f"break+hold {nr.get('source') or 'nearest_resistance'}",
                }
            )
    # B) micro breakout
    micro_res = micro.get("micro_resistance_15m") if isinstance(micro, dict) else None
    micro_sup = micro.get("micro_support_15m") if isinstance(micro, dict) else None
    mr_price = float(micro_res) if micro_res is not None else None
    if mr_price and mr_price > current_price:
        entry = mr_price
        stop = float(micro_sup) if micro_sup is not None else entry * 0.97
        target, label = _structural_targets_above(entry, "micro_resistance_15m", payload)
        if target is not None and label is not None and _risk_reward_valid(entry, stop, target):
            _append_candidate(
                {
                    "name": "MICRO_BREAK_HOLD",
                    "entry_trigger_price": entry,
                    "stop_price": stop,
                    "target_price": target,
                    "target1_label": label,
                    "notes": "micro break+hold",
                }
            )

    # C) VWAP pullback when extended
    dist_vwap = payload.get("derived", {}).get("distance_to_vwap_pct") if isinstance(payload.get("derived"), dict) else None
    vwap = payload.get("vwap")
    if isinstance(dist_vwap, (int, float)) and dist_vwap > 0.05 and isinstance(vwap, (int, float)) and current_price > vwap:
        entry = vwap
        stop = entry * 0.98
        target, label = _structural_targets_above(entry, "vwap", payload)
        if target is not None and label is not None and _risk_reward_valid(entry, stop, target):
            _append_candidate(
                {
                    "name": "VWAP_PULLBACK_RETEST",
                    "entry_trigger_price": entry,
                    "stop_price": stop,
                    "target_price": target,
                    "target1_label": label,
                    "notes": "pullback to vwap then reclaim",
                }
            )

    # tight resistance gate: if too tight and no breakout candidate, drop non-breakout setups
    if tight_res_block:
        candidates = [c for c in candidates if c["name"] in {"NEAREST_RES_BREAK_HOLD", "MICRO_BREAK_HOLD"}]
        if not candidates:
            return []

    return candidates[:3]
