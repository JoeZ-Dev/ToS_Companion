from __future__ import annotations

from typing import Literal, Optional, TypedDict

# AE → LLM payload (normalized) per specs.md §11.2.5


class QuoteSnapshot(TypedDict, total=False):
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    volume: Optional[float]


class Bar5m(TypedDict):
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_extended: bool


class LlmSnapshotPayload(TypedDict, total=False):
    schema_version: Literal["AE-1.1"]
    status: Literal["ok", "error"]
    data_quality: Literal["ok", "partial", "stale", "no_data", "error"]
    as_of_ts_ms: int
    symbol: str
    session_mode: Literal["NORMAL", "SEAMLESS"]
    quote: QuoteSnapshot
    market_state: Literal["premarket", "normal", "afterhours"]
    bars_window: list[Bar5m]


# LLM output schema per specs.md §11.3


class LlmCoachOutput(TypedDict, total=False):
    validity: Literal["VALID_FOR_TRADING", "NOT_VALID_FOR_TRADING"]
    setup_rating: str
    entry_price: Optional[float]
    stop_loss: Optional[float]
    target_price: Optional[float]
    risk_reward: Optional[float]
    summary: str
    reason_codes: list[str]
    # In-position context
    trade_management_action: Optional[
        Literal["HOLD", "EXIT_NOW", "SCALE_OUT_50", "MOVE_STOP_TO_BREAKEVEN", "RAISE_STOP_TO", "ADD_TO_POSITION"]
    ]
    action_urgency: Optional[Literal["LOW", "MEDIUM", "HIGH"]]
    updated_stop_loss: Optional[float]
    add_entry_price: Optional[float]
    add_qty: Optional[float]
    management_summary: Optional[str]
