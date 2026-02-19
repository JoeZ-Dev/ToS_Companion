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

    def set_history(self, bars: List[BarDict]) -> None:
        self._last_full = list(bars)
        payload = json.dumps(bars)
        self._widget.set_data_payload(payload)

    def upsert_bar(self, bar: BarDict) -> None:
        payload = json.dumps(bar)
        self._widget.update_bar_payload(payload)
        if self._last_full is not None:
            if self._last_full and int(self._last_full[-1]["time"]) == int(bar["time"]):
                self._last_full[-1] = bar
            else:
                self._last_full.append(bar)
                if len(self._last_full) > 181:
                    self._last_full = self._last_full[-181:]

    def set_series(self, name: str, points: List[Dict]) -> None:
        # Placeholder for future indicators
        return None

    def set_markers(self, markers: List[Dict]) -> None:
        # Placeholder for future markers
        return None

    def shutdown(self) -> None:
        return None


class FakeChartAdapter(ChartAdapter):
    """Test fake."""

    def __init__(self) -> None:
        self.history: List[List[BarDict]] = []
        self.upserts: List[BarDict] = []

    def set_history(self, bars: List[BarDict]) -> None:
        self.history.append(list(bars))

    def upsert_bar(self, bar: BarDict) -> None:
        self.upserts.append(bar)

    def shutdown(self) -> None:
        return None
