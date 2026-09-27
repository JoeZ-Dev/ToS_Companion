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
    LevelCluster,
    normalize_bars,
    swing_highs,
)


PATTERN_NAME = "LOCAL_RESISTANCE_BREAKOUT"


@dataclass(frozen=True)
class LocalResistanceBreakoutConfig:
    """Generic local horizontal-resistance breakout geometry.

    Defaults are intentionally structural starting points, not values fitted to
    the recorded development corpus.
    """

    min_bars: int = 6
    max_lookback_sec: int = 10 * 60
    min_resistance_touches: int = 2
    resistance_tolerance_pct: float = 0.006
    max_level_points: int = 5
    breakout_buffer_pct: float = 0.0015
    confirmation_policy: AdaptiveConfirmationPolicy = AdaptiveConfirmationPolicy(
        min_seconds=5.0,
        max_seconds=30.0,
        formation_fraction=0.10,
    )


@dataclass(frozen=True)
class LocalResistanceBreakoutDetector:
    config: LocalResistanceBreakoutConfig = LocalResistanceBreakoutConfig()
    name: str = PATTERN_NAME

    def detect(self, symbol: str, bars: Iterable) -> PatternObservation | None:
        return detect_local_resistance_breakout(symbol, bars, self.config)


def detect_local_resistance_breakout(
    symbol: str,
    bars,
    config: LocalResistanceBreakoutConfig | None = None,
) -> PatternObservation | None:
    cfg = config or LocalResistanceBreakoutConfig()
    normalized = normalize_bars(bars)
    if len(normalized) < cfg.min_bars:
        return None

    end_time = normalized[-1].time
    window = [
        bar
        for bar in normalized
        if end_time - bar.time <= cfg.max_lookback_sec
    ]
    if len(window) < cfg.min_bars:
        return None

    highs = swing_highs(window)
    level = _select_stable_resistance_cluster(
        highs,
        tolerance_pct=cfg.resistance_tolerance_pct,
        max_points=cfg.max_level_points,
        min_points=cfg.min_resistance_touches,
    )
    if level is None:
        return None

    first_touch = level.points[0]
    breakout_level = level.high * (1 + cfg.breakout_buffer_pct)

    # A local resistance setup must still be intact before the current bar.
    # If price already closed through the breakout level after the first touch,
    # this resistance was previously resolved and must not be resurrected.
    prior_bars = window[first_touch.index + 1 : -1]
    if any(bar.close >= breakout_level for bar in prior_bars):
        return None

    last = window[-1]
    previous = window[-2]
    confirmation = measure_confirmation(
        window,
        qualifies=lambda bar: bar.close >= breakout_level,
        formation_started_at=first_touch.time,
        policy=cfg.confirmation_policy,
    )

    crossed_now = previous.close < breakout_level <= last.close
    if crossed_now:
        state = PatternState.BREAKOUT
    elif last.high >= level.low:
        state = PatternState.TESTING
    else:
        state = PatternState.VALID

    points = [
        PatternPoint(point.time, point.price, "resistance_touch")
        for point in level.points
    ]
    resistance_start = PatternPoint(
        first_touch.time,
        level.center,
        "resistance",
    )
    resistance_end = PatternPoint(
        last.time,
        level.center,
        "resistance",
    )

    return PatternObservation(
        symbol=symbol.upper(),
        pattern_type=PATTERN_NAME,
        state=state,
        started_at=first_touch.time,
        updated_at=last.time,
        evidence={
            "resistance": level.center,
            "resistance_low": level.low,
            "resistance_high": level.high,
            "resistance_touches": len(level.points),
            "breakout_level": breakout_level,
            "crossed_now": crossed_now,
            "previous_close": previous.close,
            "last_close": last.close,
            "breakout_confirmation": confirmation.to_dict(),
            "selection": "recent_clustered_swing_highs",
            "lifecycle": "single_breakout",
        },
        points=points,
        lines=[
            PatternLine(
                "resistance",
                resistance_start,
                resistance_end,
            )
        ],
    )



def _select_stable_resistance_cluster(
    points,
    *,
    tolerance_pct: float,
    max_points: int,
    min_points: int,
) -> LevelCluster | None:
    """Build sequential price clusters without letting a later outlier drag a level.

    Generic averaging across all recent swing highs can move an established
    resistance level upward after price has already broken it. Sequential
    clustering preserves the identity of an existing level while allowing a
    materially higher swing to begin a new candidate level.
    """
    clusters: list[list] = []
    for point in list(points)[-max_points:]:
        best_index = None
        best_distance = None
        for index, cluster in enumerate(clusters):
            center = sum(item.price for item in cluster) / len(cluster)
            tolerance = abs(center) * tolerance_pct
            distance = abs(point.price - center)
            if distance <= tolerance and (
                best_distance is None or distance < best_distance
            ):
                best_index = index
                best_distance = distance
        if best_index is None:
            clusters.append([point])
        else:
            clusters[best_index].append(point)

    eligible = [cluster for cluster in clusters if len(cluster) >= min_points]
    if not eligible:
        return None

    chosen = max(
        eligible,
        key=lambda cluster: (
            cluster[-1].time,
            len(cluster),
            -(
                max(item.price for item in cluster)
                - min(item.price for item in cluster)
            ),
        ),
    )
    center = sum(item.price for item in chosen) / len(chosen)
    return LevelCluster(
        center=center,
        low=min(item.price for item in chosen),
        high=max(item.price for item in chosen),
        points=tuple(chosen),
    )
