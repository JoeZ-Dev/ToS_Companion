from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Literal


@dataclass(frozen=True)
class ConfirmationResult:
    confirmed: bool
    elapsed_seconds: float
    required_seconds: float
    streak_started_at: int | None
    gap_broken: bool

    def to_dict(self) -> dict:
        return {
            "confirmed": self.confirmed,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "required_seconds": round(self.required_seconds, 3),
            "streak_started_at": self.streak_started_at,
            "gap_broken": self.gap_broken,
        }


def _required_seconds(
    *,
    pattern_started_at: int,
    breakout_started_at: int,
    min_seconds: float,
    max_seconds: float,
    formation_fraction: float,
) -> float:
    formation_seconds = max(0.0, float(breakout_started_at - pattern_started_at))
    adaptive = formation_seconds * formation_fraction
    return max(min_seconds, min(max_seconds, adaptive))


def evaluate_price_confirmation(
    bars: Iterable,
    *,
    trigger_price: float,
    pattern_started_at: int,
    direction: Literal["above", "below"] = "above",
    min_seconds: float = 5.0,
    max_seconds: float = 30.0,
    formation_fraction: float = 0.05,
    max_gap_seconds: float = 30.0,
    default_interval_seconds: float = 10.0,
) -> ConfirmationResult:
    """Confirm price acceptance using real elapsed time, not a fixed bar count.

    The required hold adapts to formation speed: quicker formations require a
    shorter hold, slower formations a longer one, bounded by min/max seconds.
    Genuine data gaps break the streak instead of being counted as confirmation.
    """
    materialized = list(bars)
    if not materialized:
        return ConfirmationResult(False, 0.0, min_seconds, None, False)

    times = [int(getattr(b, "time", b.get("time"))) for b in materialized]
    closes = [float(getattr(b, "close", b.get("close"))) for b in materialized]
    intervals = [b - a for a, b in zip(times, times[1:]) if 0 < b - a <= max_gap_seconds]
    interval = float(median(intervals)) if intervals else float(default_interval_seconds)

    def on_side(value: float) -> bool:
        return value >= trigger_price if direction == "above" else value <= trigger_price

    if not on_side(closes[-1]):
        return ConfirmationResult(False, 0.0, min_seconds, None, False)

    streak_index = len(materialized) - 1
    gap_broken = False
    while streak_index > 0:
        gap = times[streak_index] - times[streak_index - 1]
        if gap > max_gap_seconds:
            gap_broken = True
            break
        if not on_side(closes[streak_index - 1]):
            break
        streak_index -= 1

    streak_started_at = times[streak_index]
    elapsed = max(interval, float(times[-1] - streak_started_at) + interval)
    required = _required_seconds(
        pattern_started_at=pattern_started_at,
        breakout_started_at=streak_started_at,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        formation_fraction=formation_fraction,
    )
    return ConfirmationResult(
        confirmed=elapsed >= required,
        elapsed_seconds=elapsed,
        required_seconds=required,
        streak_started_at=streak_started_at,
        gap_broken=gap_broken,
    )
