from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ExecutionIntelligenceState(str, Enum):
    """Small, stable public vocabulary for execution-time market state."""

    NEUTRAL = "neutral"
    ENTRY_SUPPORTIVE = "entry_supportive"
    ENTRY_DETERIORATING = "entry_deteriorating"
    HOLD_SUPPORTIVE = "hold_supportive"
    EXIT_PRESSURE = "exit_pressure"
    CONTINUATION_SUPPORTIVE = "continuation_supportive"


@dataclass(frozen=True)
class TopOfBook:
    timestamp_ms: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

    @property
    def spread(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


@dataclass(frozen=True)
class MicrostructureFeatures:
    """Normalized/replayable measurements. No trading policy belongs here."""

    timestamp_ms: int
    spread_pct: Optional[float] = None
    near_bid_depth: Optional[float] = None
    near_ask_depth: Optional[float] = None
    depth_imbalance: Optional[float] = None
    bid_depletion_rate: Optional[float] = None
    ask_depletion_rate: Optional[float] = None
    bid_replenishment_rate: Optional[float] = None
    ask_replenishment_rate: Optional[float] = None
    aggressive_buy_ratio: Optional[float] = None
    trade_rate_per_sec: Optional[float] = None
    share_rate_per_sec: Optional[float] = None
    price_velocity_pct_per_sec: Optional[float] = None
    price_progress_per_1k_shares: Optional[float] = None


@dataclass(frozen=True)
class ExecutionIntelligenceObservation:
    timestamp_ms: int
    state: ExecutionIntelligenceState
    features: MicrostructureFeatures
    reason_codes: tuple[str, ...] = ()
