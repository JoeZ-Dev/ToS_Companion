from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Callable, Iterable

from momentum_companion.setup_engine.structure.bars import NormalizedBar, normalize_bars


@dataclass(frozen=True)
class AdaptiveConfirmationPolicy:
    """Pattern-local confirmation policy.

    The target is derived from observed setup formation time rather than a
    universal fixed hold. Values are hypotheses to be tuned in replay; detectors
    may use different policies without changing the confirmation engine.
    """

    min_seconds: float = 5.0
    max_seconds: float = 30.0
    formation_fraction: float = 0.10

    def target_seconds(self, formation_seconds: float) -> float:
        raw = max(0.0, float(formation_seconds)) * self.formation_fraction
        return max(self.min_seconds, min(self.max_seconds, raw))


@dataclass(frozen=True)
class ConfirmationMeasurement:
    target_seconds: float
    acceptance_seconds: float
    confirmed: bool
    started_at: int | None
    last_confirmed_at: int | None
    median_bar_seconds: float | None

    def to_dict(self) -> dict:
        return {
            "target_seconds": self.target_seconds,
            "acceptance_seconds": self.acceptance_seconds,
            "confirmed": self.confirmed,
            "started_at": self.started_at,
            "last_confirmed_at": self.last_confirmed_at,
            "median_bar_seconds": self.median_bar_seconds,
            "policy": "adaptive_formation_time",
            "unvalidated_policy": True,
        }


def measure_confirmation(
    bars: Iterable,
    *,
    qualifies: Callable[[NormalizedBar], bool],
    formation_started_at: int,
    policy: AdaptiveConfirmationPolicy,
) -> ConfirmationMeasurement:
    """Measure consecutive end-of-series acceptance using real elapsed time.

    A gap does not become synthetic confirmation time. Each qualifying bar
    contributes at most its observed width; a discontinuity larger than 2.5x
    the recent median cadence resets the streak.
    """

    normalized = normalize_bars(bars)
    formation = max(0, (normalized[-1].time - formation_started_at) if normalized else 0)
    target = policy.target_seconds(formation)
    if not normalized:
        return ConfirmationMeasurement(target, 0.0, False, None, None, None)

    diffs = [
        b.time - a.time
        for a, b in zip(normalized, normalized[1:])
        if b.time > a.time
    ]
    cadence = float(median(diffs[-20:])) if diffs else None
    fallback_width = cadence or 10.0
    max_contiguous_gap = fallback_width * 2.5

    acceptance = 0.0
    streak_start: int | None = None
    last_confirmed_at: int | None = None

    # Only the current trailing streak matters. Walk backward so an old,
    # already-broken acceptance period cannot confirm the present setup.
    trailing: list[NormalizedBar] = []
    for bar in reversed(normalized):
        if not qualifies(bar):
            break
        trailing.append(bar)
    trailing.reverse()

    for index, bar in enumerate(trailing):
        if index + 1 < len(trailing):
            width = trailing[index + 1].time - bar.time
            if width <= 0 or width > max_contiguous_gap:
                acceptance = 0.0
                streak_start = trailing[index + 1].time
                continue
        else:
            width = fallback_width

        if streak_start is None:
            streak_start = bar.time
        acceptance += min(float(width), max_contiguous_gap)
        if acceptance >= target:
            last_confirmed_at = bar.time + int(width)

    return ConfirmationMeasurement(
        target_seconds=target,
        acceptance_seconds=acceptance,
        confirmed=acceptance >= target,
        started_at=streak_start,
        last_confirmed_at=last_confirmed_at,
        median_bar_seconds=cadence,
    )
