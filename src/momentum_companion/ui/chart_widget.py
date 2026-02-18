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
        html = (
            "<!DOCTYPE html>"
            "<html><head>"
            f'<script src="{PLOTLY_CDN}"></script>'
            "</head><body>"
            '<div id="chart"></div>'
            "<script>"
            "window.hasCustomRange=false;"
            "Plotly.newPlot('chart',[{type:\"candlestick\",x:[],open:[],high:[],low:[],close:[],name:\"10s\",showlegend:false}],"
            "{title:\"10s Chart\",height:400,showlegend:false,uirevision:\"static\"});"
            "document.getElementById('chart').on('plotly_relayout',function(e){"
            "if(e['xaxis.range[0]']||e['xaxis.autorange']){window.hasCustomRange=true;}"
            "});"
            "window.updateData=function(payload){var data=JSON.parse(payload);"
            "var layout={height:400,showlegend:false,uirevision:\"static\"};"
            "if(!window.hasCustomRange && data.pad){layout.xaxis={range:[data.x[Math.max(0,data.x.length-50)], data.pad]};}"
            "Plotly.react('chart',[{type:\"candlestick\",x:data.x,open:data.open,high:data.high,low:data.low,close:data.close,"
            "name:\"10s\",showlegend:false}],layout);};"
            "</script>"
            "</body></html>"
        )
        self.setHtml(html)

    def render_bars(self, times: list, opens: list, highs: list, lows: list, closes: list) -> None:
        """Incrementally update candlesticks via JS to avoid full re-render flicker."""
        x_vals = [self._to_datetime_str(t) for t in times]
        pad_ts = None
        if times:
            pad_gap_ms = (times[-1] - times[-2]) if len(times) >= 2 else 10_000
            pad_ts = self._to_datetime_str(times[-1] + pad_gap_ms * 6)
        payload = json.dumps({"x": x_vals, "open": opens, "high": highs, "low": lows, "close": closes, "pad": pad_ts})
        # Execute JS in the page to update data
        self.page().runJavaScript(f"window.updateData('{payload}');")

    @staticmethod
    def _to_datetime_str(ts: int) -> str:
        """Convert ms epoch to ET string for axis readability."""
        try:
            return datetime.fromtimestamp(ts / 1000, tz=ZoneInfo("America/New_York")).isoformat()
        except Exception:
            return datetime.fromtimestamp(0, tz=ZoneInfo("America/New_York")).isoformat()
