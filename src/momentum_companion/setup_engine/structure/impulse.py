from __future__ import annotations

from dataclasses import dataclass

from momentum_companion.setup_engine.structure.bars import NormalizedBar


@dataclass(frozen=True)
class ImpulseLeg:
    start_index: int
    end_index: int
    start_time: int
    end_time: int
    start_price: float
    end_price: float

    @property
    def move(self) -> float:
        return self.end_price - self.start_price

    @property
    def move_pct(self) -> float:
        return self.move / self.start_price if self.start_price else 0.0


def strongest_bullish_impulse(
    bars: list[NormalizedBar],
    *,
    min_move_pct: float,
    reserve_tail_bars: int = 1,
) -> ImpulseLeg | None:
    best: ImpulseLeg | None = None
    stop = max(0, len(bars) - reserve_tail_bars)
    for start_i in range(0, max(0, stop - 1)):
        start_price = bars[start_i].low
        if start_price <= 0:
            continue
        for end_i in range(start_i + 1, stop):
            leg = ImpulseLeg(
                start_index=start_i,
                end_index=end_i,
                start_time=bars[start_i].time,
                end_time=bars[end_i].time,
                start_price=start_price,
                end_price=bars[end_i].high,
            )
            if leg.move_pct < min_move_pct:
                continue
            if best is None or leg.move_pct > best.move_pct:
                best = leg
    return best
