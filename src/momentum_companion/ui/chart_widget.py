from __future__ import annotations

from datetime import datetime

from PySide6 import QtWebEngineWidgets
import plotly.graph_objects as go


class ChartWidget(QtWebEngineWidgets.QWebEngineView):
    """Placeholder for Plotly chart embedding."""

    def __init__(self) -> None:
        super().__init__()
        self._fig = go.Figure()
        self._fig.update_layout(title="10s Chart", height=400)
        self._fig.update_yaxes(showgrid=True)
        self._fig.update_layout(showlegend=False)
        self.setHtml(self._fig.to_html(include_plotlyjs="cdn"))

    def render_bars(self, times: list, opens: list, highs: list, lows: list, closes: list) -> None:
        """Render candlesticks with gaps off."""
        x_vals = [self._to_datetime(t) for t in times]
        self._fig = go.Figure(
            data=[
                go.Candlestick(
                    x=x_vals,
                    open=opens,
                    high=highs,
                    low=lows,
                    close=closes,
                    showlegend=False,
                    name="10s",
                )
            ]
        )
        self._fig.update_layout(height=400)
        self.setHtml(self._fig.to_html(include_plotlyjs="cdn"))

    @staticmethod
    def _to_datetime(ts: int) -> str:
        """Convert ms epoch to ISO string for x-axis readability."""
        try:
            return datetime.utcfromtimestamp(ts / 1000).isoformat()
        except Exception:
            return str(ts)
