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
        options = {
            "layout": {
                "background": {"color": "#0f1419"},
                "textColor": "#c8d1da",
                "fontFamily": "Segoe UI",
                "fontSize": 12,
            },
            "grid": {
                "vertLines": {"color": "rgba(42,46,57,0.5)"},
                "horzLines": {"color": "rgba(42,46,57,0.5)"},
            },
            "rightPriceScale": {"borderColor": "rgba(197,203,206,0.2)"},
            "timeScale": {
                "borderColor": "rgba(197,203,206,0.2)",
                "timeVisible": True,
                "secondsVisible": False,
                "rightOffset": 6,
                "barSpacing": 6,
            },
            "priceScale": {"scaleMargins": {"top": 0.1, "bottom": 0.1}},
            "localization": {},
        }
        candle_opts = {
            "upColor": "#26a69a",
            "downColor": "#ef5350",
            "borderUpColor": "#26a69a",
            "borderDownColor": "#ef5350",
            "wickUpColor": "#26a69a",
            "wickDownColor": "#ef5350",
        }
        options_json = json.dumps(options)
        candle_json = json.dumps(candle_opts)
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body,#chart{margin:0;padding:0;width:100%;height:100%;background:#0f1419;color:#c8d1da;}</style>"
            f"<script>{js}</script>"
            "</head><body>"
            "<div id='chart'></div>"
            "<script>"
            "window.onerror=(msg,src,line,col,err)=>{document.title='JSERR: '+msg;};"
            "function utcToET(time){"
            " const date=new Date(time*1000);"
            " const et=new Date(date.toLocaleString('en-US',{timeZone:'America/New_York'}));"
            " const hh=et.getHours().toString().padStart(2,'0');"
            " const mm=et.getMinutes().toString().padStart(2,'0');"
            " return `${hh}:${mm}`;"
            "}"
            f"const options={options_json};"
            "options.localization.timeFormatter=utcToET;"
            "const container=document.getElementById('chart');"
            "const chart=LightweightCharts.createChart(container, options);"
            f"const candleSeries=chart.addCandlestickSeries({candle_json});"
            "window.lwc_setData=function(data){candleSeries.setData(data||[]);};"
            "window.lwc_update=function(bar){if(!bar){return;}candleSeries.update(bar);};"
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
