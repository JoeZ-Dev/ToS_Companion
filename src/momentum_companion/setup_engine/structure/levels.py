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
