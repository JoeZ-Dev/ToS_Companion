from __future__ import annotations

from typing import Literal, Optional, TypedDict


class QuoteEvent(TypedDict):
    """Canonical quote event emitted by SchwabStreamClient per specs.md §13.1."""

    ts_ms: int
    symbol: str
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    bid_size: Optional[float]
    ask_size: Optional[float]
    last_size: Optional[float]
    volume: Optional[float]
    source_ts_type: Literal["TRADE_TS", "QUOTE_TS", "LOCAL_INGEST_TS"]
    raw_source: Literal["SCHWAB_STREAM"]
