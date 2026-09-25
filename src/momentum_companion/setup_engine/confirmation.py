from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable

from momentum_companion.setup_engine.structure.bars import NormalizedBar, normalize_bars


@dataclass(frozen=True)
class AdaptiveConfirmationPolicy:
    """Configurable acceptance window for one pattern family.

    The required hold is proportional to the age/duration of the pattern, then
    clamped to explicit min/max bounds. It is never shorter than one observed
    bar cadence, so a detector cannot claim sub-bar precision it does not have.
    """

    min_seconds: float
    max_seconds: float
    pattern_fraction: float
    gap_multiplier: float = 2.5
    minimum_gap_reset_seconds: float = 20.0


@dataclass(frozen=True)
class AdaptiveConfirmation:
    direction: str
    level: float
    required_seconds: float
    elapsed_seconds: float
    observed_cadence_seconds: float
    consecutive_bars: int
    confirmed: bool
    run_started_at: int | None
    gap_reset_seconds: float
    gap_detected: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _cadence_seconds(bars: list[NormalizedBar]) -> float:
    diffs = [
        float(b.time - a.time)
        for a, b in zip(bars, bars[1:])
        if b.time > a.time
    ]
    if not diffs:
        return 10.0
    recent = diffs[-20:]
    floor = min(recent)
    # A large outage/halt must not inflate the cadence estimate that is then
    # used to decide whether that same outage counts as a gap.
    cadence_candidates = [value for value in recent if value <= floor * 2.5]
    return max(0.001, float(median(cadence_candidates or recent)))


def _on_side(bar: NormalizedBar, level: float, direction: str) -> bool:
    if direction == "above":
        return bar.close >= level
    if direction == "below":
        return bar.close <= level
    raise ValueError("direction must be 'above' or 'below'")


def evaluate_adaptive_confirmation(
    bars: Iterable,
    *,
    level: float,
    direction: str,
    pattern_started_at: int,
    policy: AdaptiveConfirmationPolicy,
) -> AdaptiveConfirmation:
    """Measure CURRENT contiguous acceptance of a level in real elapsed time.

    A close back through the level resets the run. A sufficiently large data
    gap also resets the run, so a halt/outage cannot be mistaken for a long
    successful hold. The newest bar contributes one observed cadence because
    completed bars represent a full interval; this avoids pretending to know
    sub-bar timing.
    """

    normalized = normalize_bars(bars)
    if not normalized:
        return AdaptiveConfirmation(
            direction=direction,
            level=float(level),
            required_seconds=float(policy.min_seconds),
            elapsed_seconds=0.0,
            observed_cadence_seconds=10.0,
            consecutive_bars=0,
            confirmed=False,
            run_started_at=None,
            gap_reset_seconds=float(policy.minimum_gap_reset_seconds),
            gap_detected=False,
        )

    cadence = _cadence_seconds(normalized)
    pattern_age = max(cadence, float(normalized[-1].time - int(pattern_started_at) + cadence))
    adaptive = pattern_age * float(policy.pattern_fraction)
    required = min(float(policy.max_seconds), max(float(policy.min_seconds), adaptive))
    required = max(required, cadence)

    gap_reset = max(
        float(policy.minimum_gap_reset_seconds),
        cadence * float(policy.gap_multiplier),
    )

    run: list[NormalizedBar] = []
    gap_detected = False
    for idx in range(len(normalized) - 1, -1, -1):
        bar = normalized[idx]
        if not _on_side(bar, float(level), direction):
            break
        if run:
            newer = run[-1]
            gap = float(newer.time - bar.time)
            if gap > gap_reset:
                gap_detected = True
                break
        run.append(bar)

    run.reverse()
    if not run:
        elapsed = 0.0
        started_at = None
    else:
        started_at = run[0].time
        elapsed = cadence
        for a, b in zip(run, run[1:]):
            elapsed += min(float(b.time - a.time), cadence)

    return AdaptiveConfirmation(
        direction=direction,
        level=float(level),
        required_seconds=required,
        elapsed_seconds=elapsed,
        observed_cadence_seconds=cadence,
        consecutive_bars=len(run),
        confirmed=bool(run and elapsed >= required),
        run_started_at=started_at,
        gap_reset_seconds=gap_reset,
        gap_detected=gap_detected,
    )
