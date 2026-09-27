from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from momentum_companion.setup_engine.confirmation import (
    AdaptiveConfirmationPolicy,
    measure_confirmation,
)
from momentum_companion.setup_engine.pattern_contracts import (
    PatternLine,
    PatternObservation,
    PatternPoint,
    PatternState,
)
from momentum_companion.setup_engine.structure import (
    measure_retracement,
    normalize_bars,
    latest_bullish_impulse,
)


PATTERN_NAME = "MICRO_PULLBACK"


@dataclass(frozen=True)
class MicroPullbackConfig:
    min_bars: int = 5
    max_duration_sec: int = 180
    min_impulse_pct: float = 0.02
    min_retracement_pct: float = 0.08
    max_retracement_pct: float = 0.50
    continuation_buffer_pct: float = 0.001
    confirmation_policy: AdaptiveConfirmationPolicy = AdaptiveConfirmationPolicy(
        min_seconds=5.0,
        max_seconds=20.0,
        formation_fraction=0.10,
    )


@dataclass(frozen=True)
class MicroPullbackDetector:
    config: MicroPullbackConfig = MicroPullbackConfig()
    name: str = PATTERN_NAME

    def detect(self, symbol: str, bars: Iterable) -> PatternObservation | None:
        return detect_micro_pullback(symbol, bars, self.config)


def detect_micro_pullback(symbol: str, bars, config: MicroPullbackConfig | None = None) -> PatternObservation | None:
    cfg = config or MicroPullbackConfig()
    normalized = normalize_bars(bars)
    if len(normalized) < cfg.min_bars:
        return None

    end_time = normalized[-1].time
    window = [b for b in normalized if end_time - b.time <= cfg.max_duration_sec + 180]
    if len(window) < cfg.min_bars:
        return None

    impulse = latest_bullish_impulse(window, min_move_pct=cfg.min_impulse_pct, reserve_tail_bars=1)
    if impulse is None:
        return None
    retracement = measure_retracement(window, impulse)
    if retracement is None:
        return None
    if retracement.duration_sec <= 0 or retracement.duration_sec > cfg.max_duration_sec:
        return None
    if not (cfg.min_retracement_pct <= retracement.depth_pct <= cfg.max_retracement_pct):
        return None

    pullback_bars = window[impulse.end_index + 1 :]
    last = pullback_bars[-1]
    prior = pullback_bars[-2] if len(pullback_bars) > 1 else window[impulse.end_index]

    # Continuation is not "price is back above the old impulse high". A valid
    # micro-pullback must first print a pullback low, then at least one completed
    # recovery bar, then break the recovery pivot formed after that low.
    recovery_before_last = window[retracement.low_index + 1 : -1]
    recovery_pivot = (
        max(recovery_before_last, key=lambda bar: bar.high)
        if recovery_before_last
        else None
    )
    continuation_level = (
        recovery_pivot.high * (1 + cfg.continuation_buffer_pct)
        if recovery_pivot is not None
        else None
    )

    # Because detectors are intentionally stateless, reconstruct whether this
    # same impulse/pullback already completed on an earlier bar. Once a prior
    # bar broke the recovery pivot available at that time, the instance is
    # finished and must not later reappear as PULLBACK/TURNING/CONTINUATION.
    for candidate_index in range(retracement.low_index + 2, len(window) - 1):
        prior_recovery = window[retracement.low_index + 1 : candidate_index]
        if not prior_recovery:
            continue
        prior_pivot = max(bar.high for bar in prior_recovery)
        prior_level = prior_pivot * (1 + cfg.continuation_buffer_pct)
        if window[candidate_index].close >= prior_level:
            return None

    confirmation = measure_confirmation(
        window[retracement.low_index + 1 :],
        qualifies=(
            (lambda bar: continuation_level is not None and bar.close >= continuation_level)
        ),
        formation_started_at=retracement.low_time,
        policy=cfg.confirmation_policy,
    )
    state = (
        PatternState.CONTINUATION
        if continuation_level is not None and last.close >= continuation_level
        else PatternState.TURNING
        if last.close > prior.close and last.close > retracement.low_price
        else PatternState.PULLBACK
    )

    points = [
        PatternPoint(impulse.start_time, impulse.start_price, "impulse_start"),
        PatternPoint(impulse.end_time, impulse.end_price, "impulse_high"),
        PatternPoint(retracement.low_time, retracement.low_price, "pullback_low"),
    ]
    lines = [
        PatternLine("impulse", points[0], points[1]),
        PatternLine("pullback", points[1], points[2]),
    ]

    return PatternObservation(
        symbol=symbol.upper(),
        pattern_type=PATTERN_NAME,
        state=state,
        started_at=impulse.start_time,
        updated_at=last.time,
        evidence={
            "impulse_start": impulse.start_price,
            "impulse_high": impulse.end_price,
            "impulse_pct": impulse.move_pct,
            "pullback_low": retracement.low_price,
            "duration_sec": retracement.duration_sec,
            "retracement_pct": retracement.depth_pct,
            "continuation_level": continuation_level,
            "recovery_pivot": recovery_pivot.high if recovery_pivot is not None else None,
            "recovery_pivot_time": recovery_pivot.time if recovery_pivot is not None else None,
            "continuation_confirmation": confirmation.to_dict(),
            "continuation_basis": "post_pullback_recovery_pivot",
            "impulse_selection": "latest_qualifying",
            "lifecycle": "single_continuation",
        },
        points=points,
        lines=lines,
    )
