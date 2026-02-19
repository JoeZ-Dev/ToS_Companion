from __future__ import annotations

from pathlib import Path
import json

from PySide6 import QtWebEngineWidgets

ASSET_JS = Path(__file__).parent / "assets" / "lightweight-charts.standalone.production.js"


class LightweightChartWidget(QtWebEngineWidgets.QWebEngineView):
    """Lightweight Charts via inlined HTML/JS using bundled standalone script."""

    def __init__(self) -> None:
        super().__init__()
        self._ready = False
        self._pending_history: list[dict] | None = None
        self._pending_bar: dict | None = None
        self.loadFinished.connect(self._on_load_finished)  # type: ignore[arg-type]
        self._init_chart()

    def _init_chart(self) -> None:
        js = ASSET_JS.read_text(encoding="utf-8")
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body,#chart{margin:0;padding:0;width:100%;height:100%;background:#0f1419;color:#c8d1da;}</style>"
            f"<script>{js}</script>"
            "</head><body>"
            "<div id='chart'></div>"
            "<script>"
            "window.lwc_setData = function(){};"
            "window.lwc_update = function(){};"
            "// TODO: add volume pane in a follow-up step."
            "const CHART_COLORS={"
            " up:'#26a69a',"
            " down:'#ef5350',"
            " bg:'#0f1419',"
            " text:'#c8d1da',"
            " grid:'rgba(42,46,57,0.5)',"
            " border:'rgba(197,203,206,0.2)',"
            " cross:'rgba(224,227,235,0.12)'"
            "};"
            "function utcToET(time){"
            " const date=new Date(time*1000);"
            " const et = new Date(date.toLocaleString('en-US', {timeZone:'America/New_York'}));"
            " const hh = et.getHours().toString().padStart(2,'0');"
            " const mm = et.getMinutes().toString().padStart(2,'0');"
            " return `${hh}:${mm}`;"
            "}"
            "const chart = LightweightCharts.createChart(document.getElementById('chart'), {"
            " layout:{background:{color:CHART_COLORS.bg},textColor:CHART_COLORS.text},"
            " grid:{vertLines:{color:CHART_COLORS.grid},horzLines:{color:CHART_COLORS.grid}},"
            " rightPriceScale:{borderColor:CHART_COLORS.border},"
            " timeScale:{borderColor:CHART_COLORS.border,rightOffset:8,barSpacing:6,timeVisible:true,secondsVisible:false,localization:{timeFormatter:utcToET}},"
            " crosshair:{mode:1,vertLine:{color:CHART_COLORS.cross,width:1,style:0},horzLine:{color:CHART_COLORS.cross,width:1,style:0}},"
            " priceScale:{scaleMargins:{top:0.1,bottom:0.1}}"
            "});"
            "const candleSeries = chart.addCandlestickSeries({"
            " upColor:CHART_COLORS.up,downColor:CHART_COLORS.down,"
            " borderUpColor:CHART_COLORS.up,borderDownColor:CHART_COLORS.down,"
            " wickUpColor:CHART_COLORS.up,wickDownColor:CHART_COLORS.down"
            "});"
            "window.lwc_setData = function(data){ candleSeries.setData(data); };"
            "window.lwc_update = function(bar){ candleSeries.update(bar); };"
            "</script>"
            "</body></html>"
        )
        self.setHtml(html)
        # setHtml is async; bindings become available on loadFinished.

    def _on_load_finished(self, ok: bool) -> None:
        self._ready = ok
        if not ok:
            return
        if self._pending_history is not None:
            self.set_data(self._pending_history)
            self._pending_history = None
        if self._pending_bar is not None:
            self.update_bar(self._pending_bar)
            self._pending_bar = None

    def set_data(self, bars: list[dict]) -> None:
        payload = json.dumps(bars)
        if not self._ready:
            self._pending_history = bars
            return
        self.page().runJavaScript(f"window.lwc_setData({payload});")

    def update_bar(self, bar: dict) -> None:
        payload = json.dumps(bar)
        if not self._ready:
            self._pending_bar = bar
            return
        self.page().runJavaScript(f"window.lwc_update({payload});")
