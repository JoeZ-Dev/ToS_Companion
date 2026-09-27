from __future__ import annotations

from dataclasses import dataclass

from momentum_companion.setup_engine.structure.bars import NormalizedBar


@dataclass(frozen=True)
class PriceRange:
    start_index: int
    end_index: int
    start_time: int
    end_time: int
    high: float
    low: float

    @property
    def center(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def width_pct(self) -> float:
        center = self.center
        return self.width / center if center else 0.0

    @property
    def duration_sec(self) -> int:
        return self.end_time - self.start_time


def tight_range_suffix(
    bars: list[NormalizedBar],
    *,
    min_bars: int,
    max_bars: int,
    max_width_pct: float,
) -> PriceRange | None:
    """Return the longest trailing bar range that satisfies a width limit.

    This is a reusable geometry primitive. It does not know whether the range
    will be used for a breakout, breakdown, squeeze, or another pattern.
    """

    if min_bars < 2:
        raise ValueError("min_bars must be at least 2")
    if max_bars < min_bars:
        raise ValueError("max_bars must be >= min_bars")
    if max_width_pct <= 0:
        raise ValueError("max_width_pct must be positive")
    if len(bars) < min_bars:
        return None

    largest = min(max_bars, len(bars))
    for count in range(largest, min_bars - 1, -1):
        start_index = len(bars) - count
        segment = bars[start_index:]
        high = max(bar.high for bar in segment)
        low = min(bar.low for bar in segment)
        center = (high + low) / 2.0
        if center <= 0:
            continue
        width_pct = (high - low) / center
        if width_pct <= max_width_pct:
            return PriceRange(
                start_index=start_index,
                end_index=len(bars) - 1,
                start_time=segment[0].time,
                end_time=segment[-1].time,
                high=high,
                low=low,
            )
    return None
