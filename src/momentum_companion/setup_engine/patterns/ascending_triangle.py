from __future__ import annotations

from dataclasses import dataclass

from momentum_companion.setup_engine.pattern_contracts import (
    PatternLine,
    PatternObservation,
    PatternPoint,
    PatternState,
    PatternType,
)
from momentum_companion.setup_engine.patterns.swing_points import normalize_bars, swing_highs, swing_lows


@dataclass(frozen=True)
class AscendingTriangleConfig:
    min_bars: int = 7
    min_resistance_touches: int = 2
    resistance_tolerance_pct: float = 0.006
    min_rising_lows: int = 2
    breakout_buffer_pct: float = 0.0015


def detect_ascending_triangle(
    symbol: str,
    bars,
    config: AscendingTriangleConfig | None = None,
) -> PatternObservation | None:
    cfg = config or AscendingTriangleConfig()
    normalized = normalize_bars(bars)
    if len(normalized) < cfg.min_bars:
        return None

    highs = swing_highs(normalized)
    lows = swing_lows(normalized)
    if len(highs) < cfg.min_resistance_touches or len(lows) < cfg.min_rising_lows:
        return None

    recent_highs = highs[-4:]
    resistance = sum(p.price for p in recent_highs) / len(recent_highs)
    tolerance = resistance * cfg.resistance_tolerance_pct
    clustered = [p for p in recent_highs if abs(p.price - resistance) <= tolerance]
    if len(clustered) < cfg.min_resistance_touches:
        return None

    first_touch = clustered[0]
    relevant_lows = [p for p in lows if p.index >= first_touch.index]
    if len(relevant_lows) < cfg.min_rising_lows:
        relevant_lows = lows[-cfg.min_rising_lows :]
    else:
        relevant_lows = relevant_lows[-4:]

    if len(relevant_lows) < cfg.min_rising_lows:
        return None
    if not all(b.price > a.price for a, b in zip(relevant_lows, relevant_lows[1:])):
        return None

    support_first = relevant_lows[0]
    support_last = relevant_lows[-1]
    if support_last.time <= support_first.time:
        return None
    support_slope = (support_last.price - support_first.price) / (support_last.time - support_first.time)
    if support_slope <= 0:
        return None

    last = normalized[-1]
    resistance_low = min(p.price for p in clustered)
    resistance_high = max(p.price for p in clustered)
    breakout_level = resistance_high * (1 + cfg.breakout_buffer_pct)

    if last.close >= breakout_level:
        state = PatternState.BREAKOUT
    elif last.high >= resistance_low:
        state = PatternState.TESTING
    else:
        state = PatternState.VALID

    points = [
        *[PatternPoint(p.time, p.price, "resistance_touch") for p in clustered],
        *[PatternPoint(p.time, p.price, "higher_low") for p in relevant_lows],
    ]
    lines = [
        PatternLine(
            role="resistance",
            start=PatternPoint(clustered[0].time, resistance, "resistance"),
            end=PatternPoint(last.time, resistance, "resistance"),
        ),
        PatternLine(
            role="rising_support",
            start=PatternPoint(support_first.time, support_first.price, "support"),
            end=PatternPoint(support_last.time, support_last.price, "support"),
        ),
    ]

    initial_height = max(resistance - support_first.price, 1e-9)
    current_height = max(resistance - support_last.price, 0.0)
    compression_pct = max(0.0, min(100.0, (1 - current_height / initial_height) * 100))

    return PatternObservation(
        symbol=symbol.upper(),
        pattern_type=PatternType.ASCENDING_TRIANGLE,
        state=state,
        started_at=min(first_touch.time, support_first.time),
        updated_at=last.time,
        evidence={
            "resistance": resistance,
            "resistance_low": resistance_low,
            "resistance_high": resistance_high,
            "resistance_touches": len(clustered),
            "higher_lows": len(relevant_lows),
            "support_slope_per_sec": support_slope,
            "compression_pct": compression_pct,
            "breakout_level": breakout_level,
        },
        points=points,
        lines=lines,
    )
