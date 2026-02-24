from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, List
from zoneinfo import ZoneInfo
import pandas as pd

from momentum_companion.data.price_update import PriceUpdate

STALE_THRESHOLD_MS = 5_000
WINDOW_SEC = 10
VOLUME_ANOMALY_CAP_DEFAULT = 250_000
VOLUME_MEDIAN_LOOKBACK_MS = 60_000
ET_PREMARKET_START_MS = 4 * 60 * 60 * 1000
ET_MARKET_OPEN_MS = (9 * 60 + 30) * 60 * 1000
ET_MARKET_CLOSE_MS = 16 * 60 * 60 * 1000
ET_AFTERHOURS_END_MS = 20 * 60 * 60 * 1000
ET_TZ = ZoneInfo("America/New_York")
VOLUME_NORM_MULTIPLIER = 12  # amplify 10s volumes to match 1m visual scale


@dataclass
class TenSecondBar:
    """Represents a 10s bar per specs.md §5.2 and §5.3."""

    ts: int  # epoch seconds aligned to window start
    open: float
    high: float
    low: float
    close: float
    volume: float
    volume_norm: float | None
    is_extended: bool
    stale: bool = False


class BarAggregator10s:
    """Builds left-inclusive/right-exclusive 10s bars from price updates (§5.2)."""

    def __init__(self) -> None:
        self._current_bar: Optional[TenSecondBar] = None
        self._window_start: Optional[int] = None
        self._last_quote_ts_ms: Optional[int] = None
        self._last_cum_volume: Optional[float] = None
        self._last_volume_ts_ms: Optional[int] = None
        self._volume_history: List[float] = []

    def ingest_price(self, update: PriceUpdate) -> Optional[TenSecondBar]:
        """Consume a price update and return a completed bar when the window rolls."""
        if update.price is None:
            return None

        ts_sec = update.timestamp
        ts_ms = ts_sec * 1000
        is_extended = self._is_extended(ts_ms)
        self._last_quote_ts_ms = ts_ms
        is_stale = self._is_stale(ts_ms)

        if self._window_start is None:
            self._window_start = self._window_floor(ts_sec)

        if ts_sec >= self._window_start + WINDOW_SEC:
            completed = self._current_bar
            while ts_sec >= self._window_start + WINDOW_SEC:
                self._window_start += WINDOW_SEC
            self._current_bar = None
            self._start_bar(self._window_start, update.price, self._volume_delta(update), is_extended)
            return completed

        if self._current_bar is None:
            self._start_bar(self._window_start, update.price, self._volume_delta(update), is_extended)
            return None

        # update bar
        self._current_bar.high = max(self._current_bar.high, update.price)
        self._current_bar.low = min(self._current_bar.low, update.price)
        self._current_bar.close = update.price
        delta_vol = self._volume_delta(update)
        self._current_bar.volume += delta_vol
        self._current_bar.volume_norm = self._current_bar.volume * VOLUME_NORM_MULTIPLIER
        self._current_bar.stale = (self._current_bar.stale) or is_stale
        return None

    def close_out(self) -> Optional[TenSecondBar]:
        """Force-close the current forming bar (e.g., on shutdown)."""
        completed = self._current_bar
        self._current_bar = None
        self._window_start = None
        return completed

    def forming_bar(self) -> Optional[TenSecondBar]:
        """Return a copy of the current forming bar, if any."""
        if self._current_bar is None:
            return None
        return replace(self._current_bar)

    def _start_bar(self, ts: int, price: float, volume: float, is_extended: bool) -> None:
        vol_norm = volume * VOLUME_NORM_MULTIPLIER
        self._current_bar = TenSecondBar(
            ts=self._window_start if self._window_start is not None else ts,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=volume,
            volume_norm=vol_norm,
            is_extended=is_extended,
            stale=False,
        )

    @staticmethod
    def _window_floor(ts_sec: int) -> int:
        """Left-inclusive/right-exclusive window start."""
        return (ts_sec // WINDOW_SEC) * WINDOW_SEC

    @staticmethod
    def _is_extended(ts_ms: int) -> bool:
        dt_utc = pd.to_datetime(ts_ms, unit="ms", utc=True)
        dt_et = dt_utc.tz_convert(ET_TZ)
        ms_in_day = (dt_et.hour * 60 * 60 + dt_et.minute * 60 + dt_et.second) * 1000 + dt_et.microsecond // 1000
        return (ms_in_day < ET_MARKET_OPEN_MS and ms_in_day >= ET_PREMARKET_START_MS) or (
            ms_in_day >= ET_MARKET_CLOSE_MS and ms_in_day < ET_AFTERHOURS_END_MS
        )

    def _is_stale(self, ts_ms: int) -> bool:
        if self._last_quote_ts_ms is None:
            return False
        return (ts_ms - self._last_quote_ts_ms) > STALE_THRESHOLD_MS

    def _volume_delta(self, update: PriceUpdate) -> float:
        """
        Compute volume delta.
        For L1: uses cumulative volume in update.size.
        For TNS: size is trade size delta.
        """
        if update.source == "TNS" and update.size is not None:
            delta = update.size
        else:
            vol = update.size
            if vol is None:
                return 0.0
            if self._last_cum_volume is None or update.timestamp * 1000 <= (self._last_volume_ts_ms or 0):
                self._last_cum_volume = vol
                self._last_volume_ts_ms = update.timestamp * 1000
                return 0.0
            delta = vol - self._last_cum_volume
            self._last_cum_volume = vol
            self._last_volume_ts_ms = update.timestamp * 1000
        if delta < 0:
            return 0.0
        self._add_volume_history(delta, update.timestamp * 1000)
        cap = max(VOLUME_ANOMALY_CAP_DEFAULT, 10 * self._median_volume())
        if len(self._volume_history) < 10:
            return delta
        if delta > cap:
            return cap
        return delta

    def _add_volume_history(self, delta: float, ts_ms: int) -> None:
        self._volume_history.append(delta)
        if len(self._volume_history) > 600:
            self._volume_history = self._volume_history[-600:]

    def _median_volume(self) -> float:
        if not self._volume_history:
            return 0.0
        sorted_vols = sorted(self._volume_history)
        mid = len(sorted_vols) // 2
        if len(sorted_vols) % 2 == 0:
            return (sorted_vols[mid - 1] + sorted_vols[mid]) / 2
        return sorted_vols[mid]
