from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class NormalizedBar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def _read(bar: Any, *names: str) -> Any:
    if isinstance(bar, dict):
        for name in names:
            if name in bar:
                return bar[name]
        return None
    for name in names:
        if hasattr(bar, name):
            return getattr(bar, name)
    return None


def normalize_bars(bars: Iterable[Any]) -> list[NormalizedBar]:
    result: list[NormalizedBar] = []
    for bar in bars:
        t = _read(bar, "time", "ts")
        o = _read(bar, "open", "o")
        h = _read(bar, "high", "h")
        l = _read(bar, "low", "l")
        c = _read(bar, "close", "c")
        v = _read(bar, "volume", "v")
        if None in (t, o, h, l, c):
            continue
        try:
            result.append(
                NormalizedBar(
                    time=int(t),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=float(v or 0.0),
                )
            )
        except (TypeError, ValueError):
            continue
    return sorted(result, key=lambda b: b.time)
