from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List
from zoneinfo import ZoneInfo
import pandas as pd

from momentum_companion.data.contracts import QuoteEvent

STALE_THRESHOLD_MS = 5_000
WINDOW_MS = 10_000
VOLUME_ANOMALY_CAP_DEFAULT = 250_000
VOLUME_MEDIAN_LOOKBACK_MS = 60_000
ET_PREMARKET_START_MS = 4 * 60 * 60 * 1000
ET_MARKET_OPEN_MS = (9 * 60 + 30) * 60 * 1000
ET_MARKET_CLOSE_MS = 16 * 60 * 60 * 1000
ET_AFTERHOURS_END_MS = 20 * 60 * 60 * 1000
ET_TZ = ZoneInfo("America/New_York")


@dataclass
class TenSecondBar:
    """Represents a 10s bar per specs.md §5.2 and §5.3."""

    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_extended: bool
    stale: bool = False


class BarAggregator10s:
    """Builds left-inclusive/right-exclusive 10s bars from canonical quotes (§5.2)."""

    def __init__(self) -> None:
        self._current_bar: Optional[TenSecondBar] = None
        self._window_start: Optional[int] = None
        self._last_quote_ts: Optional[int] = None
        self._last_cum_volume: Optional[float] = None
        self._last_volume_ts: Optional[int] = None
        self._volume_history: List[float] = []

    def ingest_quote(self, quote: QuoteEvent) -> Optional[TenSecondBar]:
        """
        Consume a quote and return a completed bar when the window rolls.
        Drops quotes without last price. Volume uses deltas if cumulative provided.
        """
        if quote["last"] is None:
            return None

        ts = quote["ts_ms"]
        is_extended = self._is_extended(ts)
        self._last_quote_ts = ts
        is_stale = self._is_stale(quote)

        if self._window_start is None:
            self._window_start = self._window_floor(ts)

        if ts >= self._window_start + WINDOW_MS:
            completed = self._current_bar
            # roll window
            while ts >= self._window_start + WINDOW_MS:
                self._window_start += WINDOW_MS
            self._current_bar = None
            self._start_bar(ts, quote["last"], self._volume_delta(quote), is_extended)
            return completed

        if self._current_bar is None:
            self._start_bar(ts, quote["last"], self._volume_delta(quote), is_extended)
            return None

        # update bar
        self._current_bar.high = max(self._current_bar.high, quote["last"])
        self._current_bar.low = min(self._current_bar.low, quote["last"])
        self._current_bar.close = quote["last"]
        self._current_bar.volume += self._volume_delta(quote)
        self._current_bar.stale = (self._current_bar.stale) or is_stale
        return None

    def close_out(self) -> Optional[TenSecondBar]:
        """Force-close the current forming bar (e.g., on shutdown)."""
        completed = self._current_bar
        self._current_bar = None
        self._window_start = None
        return completed

    def _start_bar(self, ts: int, price: float, volume: float, is_extended: bool) -> None:
        self._current_bar = TenSecondBar(
            ts_ms=self._window_start if self._window_start is not None else self._window_floor(ts),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=volume,
            is_extended=is_extended,
            stale=self._is_stale({"ts_ms": ts, "last": price}),
        )

    @staticmethod
    def _window_floor(ts_ms: int) -> int:
        """Left-inclusive/right-exclusive window start."""
        return (ts_ms // WINDOW_MS) * WINDOW_MS

    @staticmethod
    def _is_extended(ts_ms: int) -> bool:
        """
        Determine extended hours flag using UTC ms converted to ET.
        """
        dt_utc = pd.to_datetime(ts_ms, unit="ms", utc=True)
        dt_et = dt_utc.tz_convert(ET_TZ)
        ms_in_day = (dt_et.hour * 60 * 60 + dt_et.minute * 60 + dt_et.second) * 1000 + dt_et.microsecond // 1000
        return (ms_in_day < ET_MARKET_OPEN_MS and ms_in_day >= ET_PREMARKET_START_MS) or (
            ms_in_day >= ET_MARKET_CLOSE_MS and ms_in_day < ET_AFTERHOURS_END_MS
        )

    def _is_stale(self, quote: QuoteEvent) -> bool:
        if self._last_quote_ts is None:
            return False
        return (quote["ts_ms"] - self._last_quote_ts) > STALE_THRESHOLD_MS

    def _volume_delta(self, quote: QuoteEvent) -> float:
        """Compute volume delta from cumulative volume if provided; clamp negatives to 0."""
        vol = quote.get("volume")
        if vol is None:
            return 0.0
        if self._last_cum_volume is None or quote["ts_ms"] <= (self._last_volume_ts or 0):
            # reset baseline on first seen or non-monotonic timestamp
            self._last_cum_volume = vol
            self._last_volume_ts = quote["ts_ms"]
            return 0.0
        delta = vol - self._last_cum_volume
        self._last_cum_volume = vol
        self._last_volume_ts = quote["ts_ms"]
        if delta < 0:
            return 0.0
        # anomaly handling
        self._add_volume_history(delta, quote["ts_ms"])
        cap = max(VOLUME_ANOMALY_CAP_DEFAULT, 10 * self._median_volume())
        if len(self._volume_history) < 10:
            return delta
        if delta > cap:
            return cap
        return delta

    def _add_volume_history(self, delta: float, ts_ms: int) -> None:
        self._volume_history.append(delta)
        # prune older than lookback
        cutoff = ts_ms - VOLUME_MEDIAN_LOOKBACK_MS
        # no timestamp tracking per entry; in lieu, keep last 60s worth by count approximation
        # For simplicity, cap to 600 entries (10 per second worst case) to limit growth.
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
