from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from momentum_companion.setup_engine.structure.bars import NormalizedBar, normalize_bars


@dataclass(frozen=True)
class SessionLevelConfig:
    """Explicit clock configuration for reusable US equity session levels."""

    timezone: str = "America/New_York"
    premarket_start: time = time(4, 0)
    regular_start: time = time(9, 30)
    regular_end: time = time(16, 0)
    opening_range_minutes: int = 10

    def __post_init__(self) -> None:
        if self.opening_range_minutes <= 0:
            raise ValueError("opening_range_minutes must be positive")
        if self.opening_range_minutes > 390:
            raise ValueError("opening_range_minutes must not exceed the regular session")
        ZoneInfo(self.timezone)


def session_level_context(
    bars: Iterable[Any],
    *,
    as_of_ts: int,
    current_price: float | None = None,
    vwap: float | None = None,
    config: SessionLevelConfig | None = None,
) -> dict[str, Any]:
    """Return standardized session levels using evidence available at ``as_of_ts``.

    Bar timestamps and ``as_of_ts`` are epoch seconds. Prior-day levels use the
    latest earlier date represented by regular-session bars. A supplied VWAP is
    preferred so live callers can preserve their canonical anchored calculation;
    otherwise VWAP is calculated from the supplied current-session bars.
    """

    settings = config or SessionLevelConfig()
    timezone = ZoneInfo(settings.timezone)
    as_of = datetime.fromtimestamp(int(as_of_ts), tz=timezone)
    observations = [bar for bar in normalize_bars(bars) if bar.time <= int(as_of_ts)]
    current_day = as_of.date()

    current_bars = [bar for bar in observations if _local_date(bar, timezone) == current_day]
    premarket = [
        bar
        for bar in current_bars
        if settings.premarket_start <= _local_time(bar, timezone) < settings.regular_start
    ]
    regular = [
        bar
        for bar in current_bars
        if settings.regular_start <= _local_time(bar, timezone) < settings.regular_end
    ]

    opening_end = datetime.combine(
        current_day,
        settings.regular_start,
        tzinfo=timezone,
    ) + timedelta(minutes=settings.opening_range_minutes)
    opening_range = [
        bar
        for bar in regular
        if datetime.fromtimestamp(bar.time, tz=timezone) < opening_end
    ]

    prior_regular = _latest_prior_regular_session(
        observations,
        current_day=current_day,
        timezone=timezone,
        settings=settings,
    )
    resolved_vwap = _positive_number(vwap)
    vwap_source = "supplied"
    if resolved_vwap is None:
        resolved_vwap = _calculate_vwap(current_bars)
        vwap_source = "calculated_from_bars" if resolved_vwap is not None else None

    levels = {
        "premarket_high": _high(premarket),
        "premarket_low": _low(premarket),
        "regular_session_high": _high(regular),
        "regular_session_low": _low(regular),
        "opening_range_high": _high(opening_range),
        "opening_range_low": _low(opening_range),
        "prior_day_high": _high(prior_regular),
        "prior_day_low": _low(prior_regular),
        "prior_day_close": prior_regular[-1].close if prior_regular else None,
        "vwap": resolved_vwap,
    }
    price = _number(current_price)
    distances = {
        name: _distance_pct(price, level)
        for name, level in levels.items()
    }

    return {
        "schema_version": 1,
        "session_date": current_day.isoformat(),
        "timezone": settings.timezone,
        "as_of_ts": int(as_of_ts),
        "opening_range_minutes": settings.opening_range_minutes,
        "opening_range_complete": as_of >= opening_end,
        "levels": levels,
        "distances_pct": distances,
        "vwap_source": vwap_source,
    }


def _latest_prior_regular_session(
    bars: list[NormalizedBar],
    *,
    current_day: date,
    timezone: ZoneInfo,
    settings: SessionLevelConfig,
) -> list[NormalizedBar]:
    dates = {
        _local_date(bar, timezone)
        for bar in bars
        if _local_date(bar, timezone) < current_day
        and settings.regular_start <= _local_time(bar, timezone) < settings.regular_end
    }
    if not dates:
        return []
    prior_day = max(dates)
    return [
        bar
        for bar in bars
        if _local_date(bar, timezone) == prior_day
        and settings.regular_start <= _local_time(bar, timezone) < settings.regular_end
    ]


def _calculate_vwap(bars: list[NormalizedBar]) -> float | None:
    weighted = 0.0
    volume = 0.0
    for bar in bars:
        if bar.volume <= 0:
            continue
        weighted += ((bar.high + bar.low + bar.close) / 3.0) * bar.volume
        volume += bar.volume
    return weighted / volume if volume > 0 else None


def _local_date(bar: NormalizedBar, timezone: ZoneInfo) -> date:
    return datetime.fromtimestamp(bar.time, tz=timezone).date()


def _local_time(bar: NormalizedBar, timezone: ZoneInfo) -> time:
    return datetime.fromtimestamp(bar.time, tz=timezone).time()


def _high(bars: list[NormalizedBar]) -> float | None:
    return max((bar.high for bar in bars), default=None)


def _low(bars: list[NormalizedBar]) -> float | None:
    return min((bar.low for bar in bars), default=None)


def _number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value)


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _distance_pct(price: float | None, level: float | None) -> float | None:
    if price is None or level is None or level == 0:
        return None
    return (price - level) / level * 100.0
