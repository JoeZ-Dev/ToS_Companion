from __future__ import annotations

from typing import Literal, Optional, TypedDict

ErrorCategory = Literal[
    "AUTH_ERROR",
    "CONNECTIVITY_ERROR",
    "EXECUTION_ERROR",
    "DATA_INTEGRITY_ERROR",
    "USER_INPUT_ERROR",
]

JournalEventType = Literal[
    "BROKER_SUBMIT",
    "BROKER_REPLACE",
    "BROKER_CANCEL",
    "BROKER_FILL",
    "SYNTHETIC_ARM",
    "SYNTHETIC_DISARM",
    "SYNTHETIC_FIRE",
    "FLATTEN",
    "LLM_REQUEST_SENT",
    "LLM_RESPONSE_RECEIVED",
    "LLM_SCHEMA_INVALID",
    "LLM_TRANSFER_APPLIED",
    "LLM_INVALID_OUTPUT",
    "ERROR",
    "DISCONNECT",
    "TIMEOUT",
    "NO_QUOTE",
    "STALE_QUOTE",
    "STREAM_DOWN",
    "AUTH_REQUIRED",
    "GATE_UNKNOWN_WORKING_ORDERS",
]


class JournalEvent(TypedDict, total=False):
    event_id: str
    ts_utc: str
    symbol: str
    event_type: JournalEventType
    session_mode: Literal["NORMAL", "SEAMLESS"]
    connection_state: Literal["CONNECTED", "RECONNECTING", "STALE"]
    side: Optional[str]
    qty: Optional[float]
    qty_filled: Optional[float]
    order_type: Optional[str]
    limit_price: Optional[float]
    stop_price: Optional[float]
    broker_order_id: Optional[str]
    emm_active: int
    emm_ref_price: Optional[float]
    emm_bound_price: Optional[float]
    emm_attempt_n: Optional[int]
    notes_json: Optional[str]
    error_category: Optional[ErrorCategory]
