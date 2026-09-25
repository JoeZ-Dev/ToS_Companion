from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ExcursionMetrics:
    entry_price: float
    mae_pct: float
    mfe_pct: float
    mae_price: float
    mfe_price: float
    mae_ts: int
    mfe_ts: int
    bars_observed: int

    def to_dict(self) -> dict:
        return {
            "entry_price": self.entry_price,
            "mae_pct": self.mae_pct,
            "mfe_pct": self.mfe_pct,
            "mae_price": self.mae_price,
            "mfe_price": self.mfe_price,
            "mae_ts": self.mae_ts,
            "mfe_ts": self.mfe_ts,
            "bars_observed": self.bars_observed,
        }


def _read(bar: Any, *names: str):
    if isinstance(bar, dict):
        for name in names:
            if name in bar:
                return bar[name]
        return None
    for name in names:
        if hasattr(bar, name):
            return getattr(bar, name)
    return None


def measure_long_excursion(
    bars: Iterable[Any],
    *,
    entry_price: float,
    entry_ts: int,
    exit_ts: int | None = None,
) -> ExcursionMetrics | None:
    """Measure long-trade MAE/MFE over the evidence window after entry."""
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")

    observed: list[tuple[int, float, float]] = []
    for bar in bars:
        ts = _read(bar, "time", "ts")
        low = _read(bar, "low", "l")
        high = _read(bar, "high", "h")
        if None in (ts, low, high):
            continue
        ts_value = int(ts)
        if ts_value < int(entry_ts):
            continue
        if exit_ts is not None and ts_value > int(exit_ts):
            continue
        observed.append((ts_value, float(low), float(high)))

    if not observed:
        return None

    mae_ts, mae_price, _ = min(observed, key=lambda item: item[1])
    mfe_ts, _, mfe_price = max(observed, key=lambda item: item[2])
    return ExcursionMetrics(
        entry_price=float(entry_price),
        mae_pct=(mae_price - entry_price) / entry_price * 100.0,
        mfe_pct=(mfe_price - entry_price) / entry_price * 100.0,
        mae_price=mae_price,
        mfe_price=mfe_price,
        mae_ts=mae_ts,
        mfe_ts=mfe_ts,
        bars_observed=len(observed),
    )
