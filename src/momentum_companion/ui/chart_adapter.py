from __future__ import annotations

import json
from typing import List, Dict, Optional

from momentum_companion.ui.chart_widget import LightweightChartWidget

BarDict = Dict[str, float]


class ChartAdapter:
    """Adapter boundary for chart rendering."""

    def __init__(self, widget: LightweightChartWidget) -> None:
        self._widget = widget
        self._last_full: Optional[List[BarDict]] = None
        self._last_time_sec: Optional[int] = None
        self._debug_logged = False

    @staticmethod
    def _sanitize_bar(bar: Dict) -> Optional[BarDict]:
        try:
            ts_ms = bar.get("ts_ms")
            ts_sec = int(bar.get("time")) if "time" in bar else int(int(ts_ms) / 1000) if ts_ms is not None else None
            if ts_sec is None:
                return None
            o = bar.get("open")
            h = bar.get("high")
            l = bar.get("low")
            c = bar.get("close")
            v_raw = bar.get("volume")
            if None in (o, h, l, c):
                return None
            v = float(v_raw) if v_raw is not None else 0.0
            return {
                "time": int(ts_sec),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
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
        self._widget.set_series(name, points)

    def set_header(self, header: Dict) -> None:
        self._widget.set_header(header)

    def set_markers(self, markers: List[Dict]) -> None:
        # Placeholder for future markers
        return None

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
