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
            "</head><body style='margin:0;padding:0;background:#0f1419;color:#c8d1da;'>"
            "<div id='chart' style='width:100%;height:100%;display:flex;flex-direction:column;'>"
            "<div id='price-pane' style='flex:7;'></div>"
            "<div id='volume-pane' style='flex:3;'></div>"
            "</div>"
            "<script>"
            "const COLORS={"
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
            " const et=new Date(date.toLocaleString('en-US',{timeZone:'America/New_York'}));"
            " const hh=et.getHours().toString().padStart(2,'0');"
            " const mm=et.getMinutes().toString().padStart(2,'0');"
            " return `${hh}:${mm}`;"
            "}"
            "const baseOptions={"
            " layout:{background:{color:COLORS.bg},textColor:COLORS.text,fontFamily:'Segoe UI',fontSize:12},"
            " grid:{vertLines:{color:COLORS.grid},horzLines:{color:COLORS.grid}},"
            " rightPriceScale:{borderColor:COLORS.border},"
            " timeScale:{borderColor:COLORS.border,rightOffset:8,barSpacing:6,timeVisible:true,secondsVisible:false,localization:{timeFormatter:utcToET}},"
            " crosshair:{mode:1,vertLine:{color:COLORS.cross,width:1,style:0},horzLine:{color:COLORS.cross,width:1,style:0}}"
            "};"
            "const priceChart=LightweightCharts.createChart(document.getElementById('price-pane'), baseOptions);"
            "const volumeChart=LightweightCharts.createChart(document.getElementById('volume-pane'), {"
            " ...baseOptions,"
            " rightPriceScale:{visible:false},"
            " crosshair:{mode:1,vertLine:{color:COLORS.cross,width:1,style:0},horzLine:{visible:false}},"
            " timeScale:{...baseOptions.timeScale,secondsVisible:false}"
            "});"
            "function syncCharts(source,target){"
            " source.timeScale().subscribeVisibleTimeRangeChange((range)=>{"
            "   if(!range)return;"
            "   target.timeScale().setVisibleRange(range);"
            " });"
            "}"
            "syncCharts(priceChart,volumeChart);"
            "syncCharts(volumeChart,priceChart);"
            "const candleSeries=priceChart.addCandlestickSeries({"
            " upColor:COLORS.up,downColor:COLORS.down,"
            " borderUpColor:COLORS.up,borderDownColor:COLORS.down,"
            " wickUpColor:COLORS.up,wickDownColor:COLORS.down,"
            " priceLineVisible:true,lastValueVisible:true"
            "});"
            "const volumeSeries=volumeChart.addHistogramSeries({"
            " priceFormat:{type:'volume'},"
            " priceScaleId:'',"
            " scaleMargins:{top:0.1,bottom:0},"
            "});"
            "function withVolumeColor(bar){"
            " const color=(bar.close!==undefined && bar.open!==undefined && bar.close<bar.open)?COLORS.down:COLORS.up;"
            " return {time:bar.time,value:bar.volume??0,color};"
            "}"
            "window.lwc_setData=function(data){"
            " candleSeries.setData(data);"
            " const vol=data.map(withVolumeColor);"
            " volumeSeries.setData(vol);"
            "};"
            "window.lwc_update=function(bar){"
            " candleSeries.update(bar);"
            " volumeSeries.update(withVolumeColor(bar));"
            "};"
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
