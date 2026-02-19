from __future__ import annotations

from pathlib import Path
import json

from PySide6 import QtWebEngineWidgets

ASSET_JS = Path(__file__).parent / "assets" / "lightweight-charts.standalone.production.js"


class LightweightChartWidget(QtWebEngineWidgets.QWebEngineView):
    """Lightweight Charts via inlined HTML/JS using bundled standalone script."""

    def __init__(self) -> None:
        super().__init__()
        self._init_chart()

    def _init_chart(self) -> None:
        js = ASSET_JS.read_text(encoding="utf-8")
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<script>{js}</script>"
            "</head><body style='margin:0;padding:0;'>"
            "<div id='chart' style='width:100%;height:100%;'></div>"
            "<script>"
            "const chart = LightweightCharts.createChart(document.getElementById('chart'), {"
            "height:400,"
            "timeScale:{timeVisible:true,secondsVisible:false,rightOffset:6},"
            "priceScale:{scaleMargins:{top:0.1,bottom:0.1}}"
            "});"
            "const candleSeries = chart.addCandlestickSeries();"
            "window.lwc_setData = function(data){ candleSeries.setData(data); };"
            "window.lwc_update = function(bar){ candleSeries.update(bar); };"
            "</script>"
            "</body></html>"
        )
        self.setHtml(html)

    def set_data(self, bars: list[dict]) -> None:
        payload = json.dumps(bars)
        self.page().runJavaScript(f"window.lwc_setData({payload});")

    def update_bar(self, bar: dict) -> None:
        payload = json.dumps(bar)
        self.page().runJavaScript(f"window.lwc_update({payload});")
