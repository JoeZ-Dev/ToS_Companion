from __future__ import annotations

import json
import logging
import math
from typing import List, Dict, Optional

from momentum_companion.ui.chart_widget import LightweightChartWidget

logger = logging.getLogger(__name__)

BarDict = Dict[str, float]


class ChartAdapter:
    """Adapter boundary for chart rendering."""

    def __init__(self, widget: LightweightChartWidget) -> None:
        self._widget = widget
        self._last_full: Optional[List[BarDict]] = None
        self._last_time_sec: Optional[int] = None
        self._debug_logged = False
        self._series_drop_logged = False

    @staticmethod
    def _sanitize_bar(bar: Dict) -> Optional[BarDict]:
        try:
            if bar is None:
                return None
            ts = bar.get("time")
            if ts is None and bar.get("ts_ms") is not None:
                ts = int(int(bar["ts_ms"]) / 1000)
            if ts is None:
                return None
            ts_i = int(ts)
            # Handle ms accidentally
            if ts_i > 10**12:
                ts_i = int(ts_i / 1000)
            o = bar.get("open")
            h = bar.get("high")
            l = bar.get("low")
            c = bar.get("close")
            v_raw = bar.get("volume", 0.0)
            if any(x is None for x in (o, h, l, c)):
                return None
            o_f = float(o)
            h_f = float(h)
            l_f = float(l)
            c_f = float(c)
            if not all(math.isfinite(x) for x in (o_f, h_f, l_f, c_f)):
                return None
            v_f = float(v_raw) if v_raw is not None else 0.0
            if not math.isfinite(v_f):
                v_f = 0.0
            return {
                "time": ts_i,
                "open": o_f,
                "high": h_f,
                "low": l_f,
                "close": c_f,
                "volume": v_f,
            }
        except Exception:
            return None

    def set_history(self, bars: List[BarDict]) -> None:
        sanitized: List[BarDict] = []
        for b in bars:
            sb = self._sanitize_bar(b)
            if sb is not None:
                sanitized.append(sb)
            else:
                if not self._debug_logged:
                    try:
                        self._debug_logged = True
                        self._widget._logger.debug("Dropped malformed candle=%s", b)  # type: ignore[attr-defined]
                    except Exception:
                        pass
        sanitized = sorted(sanitized, key=lambda x: int(x.get("time") or 0))
        if not sanitized:
            return
        self._last_full = list(sanitized)
        self._last_time_sec = int(sanitized[-1]["time"])
        if not self._debug_logged and sanitized:
            try:
                self._debug_logged = True
                self._widget._logger.debug("ChartAdapter sample candle=%s", sanitized[0])  # type: ignore[attr-defined]
            except Exception:
                pass
        self._widget.set_data(sanitized)

    @staticmethod
    def _sanitize_point(p: Dict) -> Optional[Dict]:
        try:
            if p is None:
                return None
            t = p.get("time")
            if t is None and p.get("ts_ms") is not None:
                t = int(int(p["ts_ms"]) / 1000)
            if t is None:
                return None
            t_i = int(t)
            if t_i > 10**12:
                t_i = int(t_i / 1000)
            val = p.get("value")
            if val is None:
                return None
            val_f = float(val)
            if not math.isfinite(val_f):
                return None
            return {"time": t_i, "value": val_f}
        except Exception:
            return None

    def upsert_bar(self, bar: BarDict) -> None:
        sb = self._sanitize_bar(bar)
        if sb is None:
            return
        t = int(sb["time"])
        if self._last_time_sec is not None and t < self._last_time_sec:
            return
        self._widget.update_bar(sb)
        if self._last_full is not None:
            if self._last_full and int(self._last_full[-1]["time"]) == t:
                self._last_full[-1] = sb
            else:
                self._last_full.append(sb)
                if len(self._last_full) > 181:
                    self._last_full = self._last_full[-181:]
        self._last_time_sec = max(self._last_time_sec or t, t)

    def set_series(self, name: str, points: List[Dict]) -> None:
        sanitized: List[Dict] = []
        dropped_sample: Optional[Dict] = None
        for pt in points:
            sp = self._sanitize_point(pt)
            if sp is None:
                if dropped_sample is None:
                    dropped_sample = pt
                continue
            sanitized.append(sp)
        if not sanitized:
            if dropped_sample is not None and not self._series_drop_logged:
                self._series_drop_logged = True
                logger.debug("Dropped invalid series points for %s sample=%s", name, dropped_sample)
            return
        if dropped_sample is not None and not self._series_drop_logged:
            self._series_drop_logged = True
            logger.debug("Dropped invalid series points for %s sample=%s", name, dropped_sample)
        sanitized = sorted(sanitized, key=lambda x: x["time"])
        self._widget.set_series(name, sanitized)

    def set_header(self, header: Dict) -> None:
        self._widget.set_header(header)

    def set_markers(self, markers: List[Dict]) -> None:
        # Placeholder for future markers
        return None

    def set_disable_series(self, flag: bool) -> None:
        if hasattr(self._widget, "set_disable_series"):
            self._widget.set_disable_series(flag)

    def shutdown(self) -> None:
        return None

    def set_timezone(self, tz_name: str) -> None:
        """Update underlying chart timezone."""
        if hasattr(self._widget, "set_timezone"):
            self._widget.set_timezone(tz_name)


class FakeChartAdapter(ChartAdapter):
    """Test fake."""

    def __init__(self) -> None:
        self.history: List[List[BarDict]] = []
        self.upserts: List[BarDict] = []
        self.series: List[tuple[str, List[Dict]]] = []
        self.headers: List[Dict] = []

    def set_history(self, bars: List[BarDict]) -> None:
        self.history.append(list(bars))

    def upsert_bar(self, bar: BarDict) -> None:
        self.upserts.append(bar)

    def set_series(self, name: str, points: List[Dict]) -> None:
        self.series.append((name, list(points)))

    def set_header(self, header: Dict) -> None:
        self.headers.append(dict(header))

    def shutdown(self) -> None:
        return None
