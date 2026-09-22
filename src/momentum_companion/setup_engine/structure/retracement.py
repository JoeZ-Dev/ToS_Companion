from __future__ import annotations

from dataclasses import dataclass

from momentum_companion.setup_engine.structure.bars import NormalizedBar
from momentum_companion.setup_engine.structure.impulse import ImpulseLeg


@dataclass(frozen=True)
class Retracement:
    low_index: int
    low_time: int
    low_price: float
    duration_sec: int
    depth_pct: float


def measure_retracement(
    bars: list[NormalizedBar],
    impulse: ImpulseLeg,
) -> Retracement | None:
    after = bars[impulse.end_index + 1 :]
    if not after or impulse.move <= 0:
        return None
    low_offset, low_bar = min(enumerate(after), key=lambda item: item[1].low)
    low_index = impulse.end_index + 1 + low_offset
    duration_sec = after[-1].time - impulse.end_time
    depth_pct = (impulse.end_price - low_bar.low) / impulse.move
    return Retracement(
        low_index=low_index,
        low_time=low_bar.time,
        low_price=low_bar.low,
        duration_sec=duration_sec,
        depth_pct=depth_pct,
    )
