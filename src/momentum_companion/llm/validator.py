from __future__ import annotations

from typing import Any, Dict, Literal

from momentum_companion.data.reason_codes import allowed_reason_codes

VALID_VALIDITY = {"VALID_FOR_TRADING", "NOT_VALID_FOR_TRADING"}
VALID_ACTIONS = {"HOLD", "EXIT_NOW", "SCALE_OUT_50", "MOVE_STOP_TO_BREAKEVEN", "RAISE_STOP_TO", "ADD_TO_POSITION"}
VALID_URGENCY = {"LOW", "MEDIUM", "HIGH"}
REQUIRED_FIELDS = {"validity", "setup_rating", "reason_codes"}


def validate_llm_output(resp: Dict[str, Any]) -> bool:
    """Basic schema validation per specs.md §11.3."""
    validity = resp.get("validity")
    if validity not in VALID_VALIDITY:
        return False
    # required fields
    if not REQUIRED_FIELDS.issubset(resp.keys()):
        return False
    # reason codes
    rcodes = resp.get("reason_codes", [])
    if not isinstance(rcodes, list) or not all(code in allowed_reason_codes() for code in rcodes):
        return False
    # in-position fields
    action = resp.get("trade_management_action")
    if action is not None and action not in VALID_ACTIONS:
        return False
    urgency = resp.get("action_urgency")
    if urgency is not None and urgency not in VALID_URGENCY:
        return False
    return True


def validate_llm_selected_candidates(payload: Dict[str, Any], llm_obj: Dict[str, Any], retry_attempted: bool = False) -> tuple[Dict[str, Any], bool, list[str], Literal["OK", "RETRY", "NO_EDGE"]]:
    """Ensure setups map to candidate_setups exactly. Returns sanitized copy."""
    reasons: list[str] = []
    out = dict(llm_obj) if isinstance(llm_obj, dict) else {}
    candidates = payload.get("candidate_setups") or []
    # If we have no candidates, do not gate.
    if not candidates:
        return out, True, reasons, "OK"
    setups = llm_obj.get("setups") or []
    if not setups:
        return out, True, reasons, "OK"
    sanitized_setups = []
    for setup in setups:
        if not isinstance(setup, dict):
            reasons.append("setup_not_dict")
            continue
        idx = setup.get("candidate_index")
        try:
            idx_int = int(idx)
        except Exception:
            reasons.append("candidate_index_missing")
            continue
        if idx_int < 0 or idx_int >= len(candidates):
            reasons.append("candidate_index_out_of_range")
            continue
        cand = candidates[idx_int]
        if not isinstance(cand, dict):
            reasons.append("candidate_invalid")
            continue
        def _num(val):
            try:
                return float(val)
            except Exception:
                return None
        setup_entry = _num(setup.get("entry_trigger_price"))
        setup_stop = _num(setup.get("stop_price"))
        setup_target = _num(setup.get("target_price"))
        cand_entry = _num(cand.get("entry_trigger_price"))
        cand_stop = _num(cand.get("stop_price"))
        cand_target = _num(cand.get("target_price"))
        entry_ok = setup_entry is not None and cand_entry is not None and abs(setup_entry - cand_entry) < 1e-6
        stop_ok = setup_stop is not None and cand_stop is not None and abs(setup_stop - cand_stop) < 1e-6
        target_ok = setup_target is not None and cand_target is not None and abs(setup_target - cand_target) < 1e-6
        label_ok = setup.get("target1_label") == cand.get("target1_label")
        if not (entry_ok and stop_ok and target_ok and label_ok):
            reasons.append("candidate_mismatch")
            continue
        sanitized = dict(setup)
        sanitized["entry_trigger_price"] = cand.get("entry_trigger_price")
        sanitized["stop_price"] = cand.get("stop_price")
        sanitized["target_price"] = cand.get("target_price")
        sanitized["target1_label"] = cand.get("target1_label")
        sanitized_setups.append(sanitized)
    out["setups"] = sanitized_setups
    if not sanitized_setups:
        action = "RETRY" if not retry_attempted else "NO_EDGE"
        return out, False, reasons, action
    return out, True, reasons, "OK"

def validate_trade_setups(snapshot: Dict[str, Any], llm_obj: Dict[str, Any], retry_attempted: bool = False) -> tuple[bool, list[str], Literal["OK", "RETRY", "NO_EDGE"]]:
    """
    Deterministic validation for discovery setups. Does not mutate inputs.
    Returns (is_valid, reasons, action)
    action in {"OK", "RETRY", "NO_EDGE"}
    """
    reasons: list[str] = []
    setups = llm_obj.get("setups") or []
    if not setups:
        bias = llm_obj.get("stock_bias")
        if bias == "NO_EDGE":
            return True, [], "OK"
        return True, [], "OK"

    session = snapshot.get("session") or {}
    pm_high = session.get("premarket_high")

    valid_found = False
    for setup in setups:
        try:
            entry = float(setup.get("entry_trigger_price"))
            stop = float(setup.get("stop_price"))
            target = float(setup.get("target_price"))
        except Exception:
            reasons.append("numeric fields invalid")
            continue
        risk = entry - stop
        reward = target - entry
        if risk <= 0 or reward <= 0:
            reasons.append("nonpositive risk/reward")
            continue
        rr = reward / risk
        move_pct = reward / entry if entry else 0.0
        if move_pct < 0.015:
            reasons.append("move_pct < 1.5%")
            continue
        if rr < 1.0:
            reasons.append("rr < 1.0")
            continue
        if entry < 5.0 and reward < 0.03:
            reasons.append("reward floor fail for sub-$5")
            continue
        # extension rule
        ext = setup.get("extension_target")
        if pm_high and target < pm_high and pm_high <= target * 1.25:
            if ext is None or float(ext) < float(pm_high) * 0.998:
                reasons.append("extension_target too low vs premarket_high")
                continue
        # structural target match
        label = setup.get("target1_label")
        if not _matches_structural_target(snapshot, label, target):
            reasons.append("target_label_mismatch")
            continue
        valid_found = True

    if valid_found:
        return True, reasons, "OK"
    action = "RETRY" if not retry_attempted else "NO_EDGE"
    return False, reasons, action


def _matches_structural_target(snapshot: Dict[str, Any], label: Any, target_price: float) -> bool:
    """Ensure target matches structural price per label."""
    tol = max(1e-4, 0.002 * target_price)
    levels = snapshot.get("levels") or {}
    micro = snapshot.get("micro") or {}
    session = snapshot.get("session") or {}
    bars = snapshot.get("bars_window") or []
    def _close(a: float | None, b: float | None) -> bool:
        return a is not None and b is not None and abs(float(a) - float(b)) <= tol
    if label == "nearest_resistance":
        expected = levels.get("nearest_resistance", {}).get("price") if isinstance(levels, dict) else None
        return _close(expected, target_price)
    if label == "micro_resistance_15m":
        expected = micro.get("micro_resistance_15m") if isinstance(micro, dict) else None
        return _close(expected, target_price)
    if label == "opening_range_high":
        expected = session.get("opening_range_high") if isinstance(session, dict) else None
        return _close(expected, target_price)
    if label == "premarket_high":
        expected = session.get("premarket_high") if isinstance(session, dict) else None
        return _close(expected, target_price)
    if label == "swing_high":
        for b in bars:
            if not isinstance(b, dict):
                continue
            h = b.get("h")
            try:
                h_f = float(h)
            except Exception:
                continue
            if _close(h_f, target_price):
                return True
        return False
    return True
