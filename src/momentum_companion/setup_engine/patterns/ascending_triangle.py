from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from momentum_companion.setup_engine.confirmation import (
    AdaptiveConfirmationPolicy,
    contiguous_tail,
    evaluate_adaptive_confirmation,
)
from momentum_companion.setup_engine.pattern_contracts import (
    PatternLine,
    PatternObservation,
    PatternPoint,
    PatternState,
)
from momentum_companion.setup_engine.structure import cluster_levels, score_level, swing_highs, swing_lows


PATTERN_NAME = "ASCENDING_TRIANGLE"


@dataclass(frozen=True)
class AscendingTriangleConfig:
    min_bars: int = 7
    min_resistance_touches: int = 2
    resistance_tolerance_pct: float = 0.006
    min_rising_lows: int = 2
    breakout_buffer_pct: float = 0.0015
    confirmation_policy: AdaptiveConfirmationPolicy = AdaptiveConfirmationPolicy(
        min_seconds=10.0,
        max_seconds=30.0,
        pattern_fraction=0.05,
    )


@dataclass(frozen=True)
class AscendingTriangleDetector:
    config: AscendingTriangleConfig = AscendingTriangleConfig()
    name: str = PATTERN_NAME

    def detect(self, symbol: str, bars: Iterable) -> PatternObservation | None:
        return detect_ascending_triangle(symbol, bars, self.config)


def detect_ascending_triangle(symbol: str, bars, config: AscendingTriangleConfig | None = None) -> PatternObservation | None:
    cfg = config or AscendingTriangleConfig()
    normalized = contiguous_tail(bars)
    if len(normalized) < cfg.min_bars:
        return None

    highs = swing_highs(normalized)
    lows = swing_lows(normalized)
    level = cluster_levels(highs, tolerance_pct=cfg.resistance_tolerance_pct, max_points=4)
    if level is None or len(level.points) < cfg.min_resistance_touches:
        return None

    first_touch = level.points[0]
    relevant_lows = [p for p in lows if p.index >= first_touch.index]
    relevant_lows = (relevant_lows if len(relevant_lows) >= cfg.min_rising_lows else lows)[-4:]
    if len(relevant_lows) < cfg.min_rising_lows:
        return None
    if not all(b.price > a.price for a, b in zip(relevant_lows, relevant_lows[1:])):
        return None

    support_first, support_last = relevant_lows[0], relevant_lows[-1]
    if support_last.time <= support_first.time:
        return None
    support_slope = (support_last.price - support_first.price) / (support_last.time - support_first.time)
    if support_slope <= 0:
        return None

    last = normalized[-1]
    breakout_level = level.high * (1 + cfg.breakout_buffer_pct)
    level_evidence = score_level(level, normalized)
    confirmation = evaluate_adaptive_confirmation(
        normalized,
        level=breakout_level,
        direction="above",
        pattern_started_at=min(first_touch.time, support_first.time),
        policy=cfg.confirmation_policy,
    )
    state = (
        PatternState.BREAKOUT if confirmation.confirmed
        else PatternState.TESTING if last.high >= level.low
        else PatternState.VALID
    )

    initial_height = max(level.center - support_first.price, 1e-9)
    current_height = max(level.center - support_last.price, 0.0)
    compression_pct = max(0.0, min(100.0, (1 - current_height / initial_height) * 100))

    points = [
        *[PatternPoint(p.time, p.price, "resistance_touch") for p in level.points],
        *[PatternPoint(p.time, p.price, "higher_low") for p in relevant_lows],
    ]
    lines = [
        PatternLine("resistance", PatternPoint(level.points[0].time, level.center, "resistance"), PatternPoint(last.time, level.center, "resistance")),
        PatternLine("rising_support", PatternPoint(support_first.time, support_first.price, "support"), PatternPoint(support_last.time, support_last.price, "support")),
    ]

    return PatternObservation(
        symbol=symbol.upper(),
        pattern_type=PATTERN_NAME,
        state=state,
        started_at=min(first_touch.time, support_first.time),
        updated_at=last.time,
        evidence={
            "resistance": level.center,
            "resistance_low": level.low,
            "resistance_high": level.high,
            "resistance_touches": len(level.points),
            "higher_lows": len(relevant_lows),
            "support_slope_per_sec": support_slope,
            "compression_pct": compression_pct,
            "breakout_level": breakout_level,
            "breakout_confirmation": confirmation.to_dict(),
            "level_evidence": {
                "touch_count": level_evidence.touch_count,
                "total_touch_volume": level_evidence.total_touch_volume,
                "last_touch_ts": level_evidence.last_touch_ts,
                "round_number_increment": level_evidence.round_number_increment,
                "round_number_distance_pct": level_evidence.round_number_distance_pct,
                "round_number_bonus": level_evidence.round_number_bonus,
                "strength_score": level_evidence.strength_score,
            },
        },
        points=points,
        lines=lines,
    )
