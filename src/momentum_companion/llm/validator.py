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
