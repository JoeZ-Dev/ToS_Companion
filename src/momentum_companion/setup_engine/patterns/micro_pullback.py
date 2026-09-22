from __future__ import annotations

from dataclasses import dataclass

from momentum_companion.setup_engine.pattern_contracts import (
    PatternLine,
    PatternObservation,
    PatternPoint,
    PatternState,
    PatternType,
)
from momentum_companion.setup_engine.patterns.swing_points import normalize_bars


@dataclass(frozen=True)
class MicroPullbackConfig:
    min_bars: int = 5
    max_duration_sec: int = 180
    min_impulse_pct: float = 0.02
    min_retracement_pct: float = 0.08
    max_retracement_pct: float = 0.50
    continuation_buffer_pct: float = 0.001


def detect_micro_pullback(
    symbol: str,
    bars,
    config: MicroPullbackConfig | None = None,
) -> PatternObservation | None:
    cfg = config or MicroPullbackConfig()
    normalized = normalize_bars(bars)
    if len(normalized) < cfg.min_bars:
        return None

    end_time = normalized[-1].time
    window = [b for b in normalized if end_time - b.time <= cfg.max_duration_sec + 180]
    if len(window) < cfg.min_bars:
        return None

    # Use the strongest recent impulse that finishes before the final bar.
    best = None
    for start_i in range(0, len(window) - 3):
        start_price = window[start_i].low
        if start_price <= 0:
            continue
        for high_i in range(start_i + 1, len(window) - 1):
            high_price = window[high_i].high
            impulse_pct = (high_price - start_price) / start_price
            if impulse_pct < cfg.min_impulse_pct:
                continue
            score = impulse_pct
            if best is None or score > best[0]:
                best = (score, start_i, high_i, start_price, high_price)

    if best is None:
        return None

    _, start_i, high_i, impulse_start, impulse_high = best
    pullback_bars = window[high_i + 1 :]
    if not pullback_bars:
        return None

    duration_sec = pullback_bars[-1].time - window[high_i].time
    if duration_sec <= 0 or duration_sec > cfg.max_duration_sec:
        return None

    pullback_low_bar = min(pullback_bars, key=lambda b: b.low)
    impulse_range = impulse_high - impulse_start
    if impulse_range <= 0:
        return None
    retracement_pct = (impulse_high - pullback_low_bar.low) / impulse_range
    if retracement_pct < cfg.min_retracement_pct or retracement_pct > cfg.max_retracement_pct:
        return None

    last = pullback_bars[-1]
    prior = pullback_bars[-2] if len(pullback_bars) > 1 else window[high_i]
    continuation_level = impulse_high * (1 + cfg.continuation_buffer_pct)

    if last.close >= continuation_level:
        state = PatternState.CONTINUATION
    elif last.close > prior.close and last.close > pullback_low_bar.low:
        state = PatternState.TURNING
    else:
        state = PatternState.PULLBACK

    points = [
        PatternPoint(window[start_i].time, impulse_start, "impulse_start"),
        PatternPoint(window[high_i].time, impulse_high, "impulse_high"),
        PatternPoint(pullback_low_bar.time, pullback_low_bar.low, "pullback_low"),
    ]
    lines = [
        PatternLine(
            role="impulse",
            start=PatternPoint(window[start_i].time, impulse_start, "impulse_start"),
            end=PatternPoint(window[high_i].time, impulse_high, "impulse_high"),
        ),
        PatternLine(
            role="pullback",
            start=PatternPoint(window[high_i].time, impulse_high, "impulse_high"),
            end=PatternPoint(pullback_low_bar.time, pullback_low_bar.low, "pullback_low"),
        ),
    ]

    return PatternObservation(
        symbol=symbol.upper(),
        pattern_type=PatternType.MICRO_PULLBACK,
        state=state,
        started_at=window[start_i].time,
        updated_at=last.time,
        evidence={
            "impulse_start": impulse_start,
            "impulse_high": impulse_high,
            "impulse_pct": (impulse_high - impulse_start) / impulse_start,
            "pullback_low": pullback_low_bar.low,
            "duration_sec": duration_sec,
            "retracement_pct": retracement_pct,
            "continuation_level": continuation_level,
        },
        points=points,
        lines=lines,
    )
