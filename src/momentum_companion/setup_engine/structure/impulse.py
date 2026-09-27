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


def latest_bullish_impulse(
    bars: list[NormalizedBar],
    *,
    min_move_pct: float,
    reserve_tail_bars: int = 1,
) -> ImpulseLeg | None:
    """Return the most recent qualifying local bullish impulse.

    A micro-pullback should attach to the latest local impulse, not the largest
    move anywhere in a rolling window. Candidate impulse ends must be local
    highs. The impulse start is the lowest low after the prior local high,
    which prevents an old session low from being reused to qualify every later
    bar as part of the same move.
    """
    stop = max(0, len(bars) - reserve_tail_bars)
    if stop < 2:
        return None

    local_highs = [
        i
        for i in range(1, stop)
        if bars[i].high >= bars[i - 1].high
        and i + 1 < len(bars)
        and bars[i].high > bars[i + 1].high
    ]

    for end_i in reversed(local_highs):
        prior_highs = [i for i in local_highs if i < end_i]
        search_start = (prior_highs[-1] + 1) if prior_highs else 0
        if search_start >= end_i:
            continue

        start_i = min(
            range(search_start, end_i),
            key=lambda i: (bars[i].low, -i),
        )
        start_price = bars[start_i].low
        if start_price <= 0:
            continue

        leg = ImpulseLeg(
            start_index=start_i,
            end_index=end_i,
            start_time=bars[start_i].time,
            end_time=bars[end_i].time,
            start_price=start_price,
            end_price=bars[end_i].high,
        )
        if leg.move_pct >= min_move_pct:
            return leg

    return None
