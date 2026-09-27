from __future__ import annotations

from statistics import mean, median
from typing import Any, Iterable, Mapping


def volume_values(bars: Iterable[Any]) -> list[float]:
    values: list[float] = []
    for bar in bars:
        value = bar.get("volume") if isinstance(bar, Mapping) else getattr(bar, "volume", None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            values.append(float(value))
    return values


def recent_volume_stats(bars: Iterable[Any], *, lookback: int = 20) -> dict[str, Any]:
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    values = volume_values(bars)[-lookback:]
    return {
        "lookback": int(lookback),
        "observations": len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
    }


def volume_ratio(numerator_bars: Iterable[Any], baseline_bars: Iterable[Any]) -> float | None:
    numerator = volume_values(numerator_bars)
    baseline = volume_values(baseline_bars)
    if not numerator or not baseline:
        return None
    baseline_mean = mean(baseline)
    if baseline_mean <= 0:
        return None
    return mean(numerator) / baseline_mean


def current_volume_expansion(
    current_bar: Any,
    prior_bars: Iterable[Any],
    *,
    lookback: int = 20,
) -> float | None:
    current = volume_values([current_bar])
    prior = volume_values(prior_bars)[-lookback:]
    if not current or not prior:
        return None
    baseline = mean(prior)
    return current[0] / baseline if baseline > 0 else None


def volume_trend(bars: Iterable[Any], *, lookback: int = 20) -> dict[str, Any]:
    if lookback <= 1:
        raise ValueError("lookback must be greater than one")
    values = volume_values(bars)[-lookback:]
    if len(values) < 2:
        return {"lookback": lookback, "observations": len(values), "slope_per_bar": None, "direction": None}
    x_mean = (len(values) - 1) / 2
    y_mean = mean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    slope = sum(
        (index - x_mean) * (value - y_mean)
        for index, value in enumerate(values)
    ) / denominator
    direction = "flat"
    if slope > 0:
        direction = "rising"
    elif slope < 0:
        direction = "falling"
    return {
        "lookback": lookback,
        "observations": len(values),
        "slope_per_bar": slope,
        "direction": direction,
    }
