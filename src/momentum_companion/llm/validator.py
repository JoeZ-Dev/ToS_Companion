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
        if _close(expected, target_price):
            return True
        # Allow breakout-through-resistance targets to the next higher swing high
        if expected is not None:
            for b in bars:
                if not isinstance(b, dict):
                    continue
                try:
                    h_f = float(b.get("h"))
                except Exception:
                    continue
                if h_f > float(expected) and _close(h_f, target_price):
                    return True
        return False
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
