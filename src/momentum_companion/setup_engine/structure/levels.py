from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from momentum_companion.setup_engine.structure.swings import SwingPoint


@dataclass(frozen=True)
class LevelCluster:
    center: float
    low: float
    high: float
    points: tuple[SwingPoint, ...]


def cluster_levels(
    points: Iterable[SwingPoint],
    *,
    tolerance_pct: float,
    max_points: int | None = None,
) -> LevelCluster | None:
    candidates = list(points)
    if max_points is not None:
        candidates = candidates[-max_points:]
    if not candidates:
        return None

    center = sum(p.price for p in candidates) / len(candidates)
    tolerance = abs(center) * tolerance_pct
    clustered = tuple(p for p in candidates if abs(p.price - center) <= tolerance)
    if not clustered:
        return None

    center = sum(p.price for p in clustered) / len(clustered)
    return LevelCluster(
        center=center,
        low=min(p.price for p in clustered),
        high=max(p.price for p in clustered),
        points=clustered,
    )



@dataclass(frozen=True)
class LevelEvidence:
    touch_count: int
    total_touch_volume: float
    last_touch_ts: int | None
    round_number_increment: float
    round_number_distance_pct: float
    round_number_bonus: float
    strength_score: float


def _round_number_increment(price: float) -> float:
    if price < 2.0:
        return 0.10
    if price < 10.0:
        return 0.25
    return 0.50


def score_level(cluster: LevelCluster, bars) -> LevelEvidence:
    """Explain a structural level without changing detector selection.

    This ports the useful evidence components from Momentum Monitor while
    keeping them explicit: repeated touches, actual volume at those touches,
    and proximity to a price grid that tends to attract attention. The score
    is intentionally transparent and is evidence, not a learned probability.
    """

    materialized = list(bars)
    total_volume = 0.0
    for point in cluster.points:
        if 0 <= point.index < len(materialized):
            bar = materialized[point.index]
            total_volume += float(getattr(bar, "volume", 0.0) or 0.0)

    increment = _round_number_increment(cluster.center)
    nearest = round(cluster.center / increment) * increment
    distance_pct = (
        abs(cluster.center - nearest) / cluster.center
        if cluster.center
        else 0.0
    )
    round_bonus = max(0.0, 1.0 - distance_pct / 0.01)
    touch_count = len(cluster.points)
    strength = touch_count * 2.0 + (total_volume / 1_000_000.0) * 0.5 + round_bonus
    return LevelEvidence(
        touch_count=touch_count,
        total_touch_volume=total_volume,
        last_touch_ts=max((point.time for point in cluster.points), default=None),
        round_number_increment=increment,
        round_number_distance_pct=distance_pct,
        round_number_bonus=round_bonus,
        strength_score=strength,
    )
