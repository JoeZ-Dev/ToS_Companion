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
from momentum_companion.setup_engine.structure import normalize_bars, tight_range_suffix


PATTERN_NAME = "TIGHT_CONSOLIDATION_BREAKOUT"


@dataclass(frozen=True)
class TightConsolidationBreakoutConfig:
    """Prospective structural defaults, not development-corpus-tuned values."""

    min_consolidation_bars: int = 4
    max_consolidation_bars: int = 12
    max_range_width_pct: float = 0.03
    breakout_buffer_pct: float = 0.0015
    confirmation_policy: AdaptiveConfirmationPolicy = AdaptiveConfirmationPolicy(
        min_seconds=5.0,
        max_seconds=30.0,
        formation_fraction=0.10,
    )


@dataclass(frozen=True)
class TightConsolidationBreakoutDetector:
    config: TightConsolidationBreakoutConfig = TightConsolidationBreakoutConfig()
    name: str = PATTERN_NAME

    def detect(self, symbol: str, bars: Iterable) -> PatternObservation | None:
        return detect_tight_consolidation_breakout(symbol, bars, self.config)


def detect_tight_consolidation_breakout(
    symbol: str,
    bars,
    config: TightConsolidationBreakoutConfig | None = None,
) -> PatternObservation | None:
    cfg = config or TightConsolidationBreakoutConfig()
    normalized = normalize_bars(bars)
    if len(normalized) < cfg.min_consolidation_bars + 1:
        return None

    # The range is measured only from bars completed before the current bar.
    # This prevents the breakout bar itself from expanding the consolidation
    # boundary and hiding the cross we are trying to detect.
    prior = normalized[:-1]
    consolidation = tight_range_suffix(
        prior,
        min_bars=cfg.min_consolidation_bars,
        max_bars=cfg.max_consolidation_bars,
        max_width_pct=cfg.max_range_width_pct,
    )
    if consolidation is None:
        return None

    last = normalized[-1]
    previous = normalized[-2]
    breakout_level = consolidation.high * (1 + cfg.breakout_buffer_pct)
    breakdown_level = consolidation.low * (1 - cfg.breakout_buffer_pct)

    # Once price closes materially below the prior range, the bullish
    # consolidation is no longer intact. A later setup must form a new range.
    if last.close <= breakdown_level:
        return None

    crossed_now = previous.close < breakout_level <= last.close
    if crossed_now:
        state = PatternState.BREAKOUT
    elif last.high >= consolidation.high:
        state = PatternState.TESTING
    else:
        state = PatternState.VALID

    confirmation = measure_confirmation(
        normalized,
        qualifies=lambda bar: bar.close >= breakout_level,
        formation_started_at=consolidation.start_time,
        policy=cfg.confirmation_policy,
    )

    upper_start = PatternPoint(
        consolidation.start_time,
        consolidation.high,
        "range_high",
    )
    upper_end = PatternPoint(last.time, consolidation.high, "range_high")
    lower_start = PatternPoint(
        consolidation.start_time,
        consolidation.low,
        "range_low",
    )
    lower_end = PatternPoint(last.time, consolidation.low, "range_low")

    return PatternObservation(
        symbol=symbol.upper(),
        pattern_type=PATTERN_NAME,
        state=state,
        started_at=consolidation.start_time,
        updated_at=last.time,
        evidence={
            "range_high": consolidation.high,
            "range_low": consolidation.low,
            "range_center": consolidation.center,
            "range_width_pct": consolidation.width_pct,
            "range_duration_sec": consolidation.duration_sec,
            "consolidation_bars": consolidation.end_index - consolidation.start_index + 1,
            "breakout_level": breakout_level,
            "breakdown_level": breakdown_level,
            "previous_close": previous.close,
            "last_close": last.close,
            "crossed_now": crossed_now,
            "breakout_confirmation": confirmation.to_dict(),
            "range_selection": "longest_trailing_tight_range",
            "lifecycle": "range_then_breakout",
        },
        points=[
            upper_start,
            PatternPoint(consolidation.end_time, consolidation.high, "range_high"),
            lower_start,
            PatternPoint(consolidation.end_time, consolidation.low, "range_low"),
        ],
        lines=[
            PatternLine("range_high", upper_start, upper_end),
            PatternLine("range_low", lower_start, lower_end),
        ],
    )
