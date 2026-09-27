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


def first_confirmed_retracement(
    bars: list[NormalizedBar],
    impulse: ImpulseLeg,
) -> Retracement | None:
    """Return the first confirmed pullback trough after an impulse.

    The ordinary retracement measurement follows the lowest low seen so far,
    which is useful descriptively but unstable for lifecycle identity. For a
    micro-pullback state machine we need the first trough that is confirmed by
    a later bar, so a subsequent lower low becomes a new structure instead of
    retroactively moving the original pullback low.
    """
    start = impulse.end_index + 1
    if start >= len(bars) - 1 or impulse.move <= 0:
        return None

    for low_index in range(start, len(bars) - 1):
        low_bar = bars[low_index]
        previous_low = (
            bars[low_index - 1].low
            if low_index - 1 >= start
            else impulse.end_price
        )
        next_bar = bars[low_index + 1]

        is_local_trough = low_bar.low <= previous_low and low_bar.low < next_bar.low
        if not is_local_trough:
            continue

        depth_pct = (impulse.end_price - low_bar.low) / impulse.move
        duration_sec = low_bar.time - impulse.end_time
        return Retracement(
            low_index=low_index,
            low_time=low_bar.time,
            low_price=low_bar.low,
            duration_sec=duration_sec,
            depth_pct=depth_pct,
        )

    return None
