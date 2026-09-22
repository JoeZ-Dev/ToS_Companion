from __future__ import annotations

from dataclasses import dataclass

from momentum_companion.setup_engine.structure.bars import NormalizedBar


@dataclass(frozen=True)
class SwingPoint:
    index: int
    time: int
    price: float


def swing_highs(bars: list[NormalizedBar], left: int = 1, right: int = 1) -> list[SwingPoint]:
    points: list[SwingPoint] = []
    if len(bars) < left + right + 1:
        return points
    for i in range(left, len(bars) - right):
        price = bars[i].high
        if all(price >= bars[j].high for j in range(i - left, i)) and all(
            price > bars[j].high for j in range(i + 1, i + right + 1)
        ):
            points.append(SwingPoint(i, bars[i].time, price))
    return points


def swing_lows(bars: list[NormalizedBar], left: int = 1, right: int = 1) -> list[SwingPoint]:
    points: list[SwingPoint] = []
    if len(bars) < left + right + 1:
        return points
    for i in range(left, len(bars) - right):
        price = bars[i].low
        if all(price <= bars[j].low for j in range(i - left, i)) and all(
            price < bars[j].low for j in range(i + 1, i + right + 1)
        ):
            points.append(SwingPoint(i, bars[i].time, price))
    return points
