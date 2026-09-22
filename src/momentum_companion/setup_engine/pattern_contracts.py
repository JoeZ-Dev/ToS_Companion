from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PatternState(str, Enum):
    FORMING = "FORMING"
    VALID = "VALID"
    TESTING = "TESTING"
    IMPULSE = "IMPULSE"
    PULLBACK = "PULLBACK"
    TURNING = "TURNING"
    BREAKOUT = "BREAKOUT"
    CONTINUATION = "CONTINUATION"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class PatternPoint:
    time: int
    price: float
    role: str


@dataclass(frozen=True)
class PatternLine:
    role: str
    start: PatternPoint
    end: PatternPoint


@dataclass
class PatternObservation:
    symbol: str
    pattern_type: str
    state: PatternState
    started_at: int
    updated_at: int
    evidence: dict[str, Any] = field(default_factory=dict)
    points: list[PatternPoint] = field(default_factory=list)
    lines: list[PatternLine] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.symbol}:{self.pattern_type}:{self.started_at}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = self.id
        payload["pattern_type"] = self.pattern_type
        payload["state"] = self.state.value
        return payload
