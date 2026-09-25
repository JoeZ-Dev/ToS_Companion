from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Any


@dataclass(frozen=True)
class ExcursionStats:
    side: Literal["long", "short"]
    entry_ts: int
    entry_price: float
    exit_ts: int | None
    mae_pct: float
    mfe_pct: float
    mae_price: float
    mfe_price: float
    mae_ts: int
    mfe_ts: int
    bars_observed: int

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "entry_ts": self.entry_ts,
            "entry_price": self.entry_price,
            "exit_ts": self.exit_ts,
            "mae_pct": self.mae_pct,
            "mfe_pct": self.mfe_pct,
            "mae_price": self.mae_price,
            "mfe_price": self.mfe_price,
            "mae_ts": self.mae_ts,
            "mfe_ts": self.mfe_ts,
            "bars_observed": self.bars_observed,
        }


def _read(bar: Mapping[str, Any], *names: str):
    for name in names:
        if name in bar:
            return bar[name]
    return None


def compute_excursions(
    bars: Iterable[Mapping[str, Any]],
    *,
    entry_ts: int,
    entry_price: float,
    exit_ts: int | None = None,
    side: Literal["long", "short"] = "long",
) -> ExcursionStats | None:
    """Compute MAE/MFE from bars observed after an entry.

    This is descriptive evaluation only. It does not invent fills, slippage,
    stops, or targets. The caller chooses the entry/exit evidence window.
    """

    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if side not in ("long", "short"):
        raise ValueError("side must be long or short")

    observed: list[tuple[int, float, float]] = []
    for bar in bars:
        ts = _read(bar, "ts", "time")
        high = _read(bar, "high", "h")
        low = _read(bar, "low", "l")
        if ts is None or high is None or low is None:
            continue
        try:
            ts_i = int(ts)
            high_f = float(high)
            low_f = float(low)
        except (TypeError, ValueError):
            continue
        if ts_i < int(entry_ts):
            continue
        if exit_ts is not None and ts_i > int(exit_ts):
            continue
        observed.append((ts_i, high_f, low_f))

    if not observed:
        return None

    if side == "long":
        mae_ts, _, mae_price = min(observed, key=lambda item: item[2])
        mfe_ts, mfe_price, _ = max(observed, key=lambda item: item[1])
        mae_pct = (mae_price - entry_price) / entry_price * 100.0
        mfe_pct = (mfe_price - entry_price) / entry_price * 100.0
    else:
        mae_ts, mae_price, _ = max(observed, key=lambda item: item[1])
        mfe_ts, _, mfe_price = min(observed, key=lambda item: item[2])
        mae_pct = (entry_price - mae_price) / entry_price * 100.0
        mfe_pct = (entry_price - mfe_price) / entry_price * 100.0

    return ExcursionStats(
        side=side,
        entry_ts=int(entry_ts),
        entry_price=float(entry_price),
        exit_ts=int(exit_ts) if exit_ts is not None else None,
        mae_pct=float(mae_pct),
        mfe_pct=float(mfe_pct),
        mae_price=float(mae_price),
        mfe_price=float(mfe_price),
        mae_ts=int(mae_ts),
        mfe_ts=int(mfe_ts),
        bars_observed=len(observed),
    )
