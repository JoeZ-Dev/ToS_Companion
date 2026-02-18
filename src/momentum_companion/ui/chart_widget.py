from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import json

from PySide6 import QtWebEngineWidgets


PLOTLY_CDN = "https://cdn.plot.ly/plotly-latest.min.js"


class ChartWidget(QtWebEngineWidgets.QWebEngineView):
    """Plotly chart with incremental updates via JavaScript."""

    def __init__(self) -> None:
        super().__init__()
        self._init_chart()

    def _init_chart(self) -> None:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <script src="{PLOTLY_CDN}"></script>
        </head>
        <body>
          <div id="chart"></div>
          <script>
            window.ts_vals = [];
            window.opens = [];
            window.highs = [];
            window.lows = [];
            window.closes = [];
            Plotly.newPlot('chart', [{{
              type: 'candlestick',
              x: [],
              open: [],
              high: [],
              low: [],
              close: [],
              name: '10s',
              showlegend: false
            }}], {{
              title: '10s Chart',
              height: 400,
              showlegend: false
            }});
            window.updateData = function(payload) {{
              const data = JSON.parse(payload);
              Plotly.react('chart', [{{
                type: 'candlestick',
                x: data.x,
                open: data.open,
                high: data.high,
                low: data.low,
                close: data.close,
                name: '10s',
                showlegend: false
              }}], {{
                height: 400,
                showlegend: false
              }});
            }}
          </script>
        </body>
        </html>
        """
        self.setHtml(html)

    def render_bars(self, times: list, opens: list, highs: list, lows: list, closes: list) -> None:
        """Incrementally update candlesticks via JS to avoid full re-render flicker."""
        x_vals = [self._to_datetime_str(t) for t in times]
        payload = json.dumps({"x": x_vals, "open": opens, "high": highs, "low": lows, "close": closes})
        # Execute JS in the page to update data
        self.page().runJavaScript(f"window.updateData('{payload}');")

    @staticmethod
    def _to_datetime_str(ts: int) -> str:
        """Convert ms epoch to ET string for axis readability."""
        try:
            return datetime.fromtimestamp(ts / 1000, tz=ZoneInfo("America/New_York")).isoformat()
        except Exception:
            return datetime.fromtimestamp(0, tz=ZoneInfo("America/New_York")).isoformat()
