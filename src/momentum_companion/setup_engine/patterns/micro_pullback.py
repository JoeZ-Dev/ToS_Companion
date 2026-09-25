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
    strongest_bullish_impulse,
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

    impulse = strongest_bullish_impulse(window, min_move_pct=cfg.min_impulse_pct, reserve_tail_bars=1)
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
    continuation_level = impulse.end_price * (1 + cfg.continuation_buffer_pct)
    confirmation = measure_confirmation(
        normalized,
        qualifies=lambda bar: bar.close >= continuation_level,
        formation_started_at=impulse.start_time,
        policy=cfg.confirmation_policy,
    )
    state = (
        PatternState.CONTINUATION if last.close >= continuation_level
        else PatternState.TURNING if last.close > prior.close and last.close > retracement.low_price
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
            "continuation_confirmation": confirmation.to_dict(),
        },
        points=points,
        lines=lines,
    )
