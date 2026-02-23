from __future__ import annotations

import json
from pathlib import Path
import textwrap

from PySide6 import QtWebEngineWidgets, QtCore

ASSET_JS = Path(__file__).parent / "assets" / "lightweight-charts.standalone.production.js"


class LightweightChartWidget(QtWebEngineWidgets.QWebEngineView):
    """Lightweight Charts via inlined HTML/JS using bundled standalone script."""

    def __init__(self) -> None:
        super().__init__()
        self._init_chart()

    def resizeEvent(self, event: QtCore.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        size = event.size()
        width = size.width()
        height = size.height()
        self.page().runJavaScript(f"if(window.chart){{chart.resize({width}, {height});}}")

    def set_timezone(self, tz_name: str) -> None:
        """Set chart time zone for axis/tooltip formatting."""
        safe_tz = tz_name or "UTC"
        self.page().runJavaScript(f"if(window.setChartTimeZone){{setChartTimeZone('{safe_tz}');}}")

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
            "priceScale": {"scaleMargins": {"top": 0.05, "bottom": 0.17}},
            "crosshair": {
                "mode": 1,
                "vertLine": {"color": "rgba(224,227,235,0.12)", "width": 1, "style": 0},
                "horzLine": {"color": "rgba(224,227,235,0.12)", "width": 1, "style": 0},
            },
            "localization": {},
        }
        candle_opts = {
            "upColor": "#26a69a",
            "downColor": "#ef5350",
            "borderUpColor": "#26a69a",
            "borderDownColor": "#ef5350",
            "wickUpColor": "#26a69a",
            "wickDownColor": "#ef5350",
            "priceLineVisible": False,
            "lastValueVisible": False,
        }
        volume_opts = {
            "priceFormat": {"type": "volume"},
            "priceScaleId": "",
            "scaleMargins": {"top": 0.83, "bottom": 0},
            "lastValueVisible": False,
            "priceLineVisible": False,
        }
        line_styles = {
            "VWAP": {"color": "rgba(180,85,255,0.7)", "lineWidth": 2, "lastValueVisible": False, "priceLineVisible": False},
            "EMA9": {"color": "#f5c542", "lineWidth": 1, "lastValueVisible": False, "priceLineVisible": False},
            "EMA20": {"color": "#4aa3ff", "lineWidth": 1, "lastValueVisible": False, "priceLineVisible": False},
            "MACD": {"color": "#1abc9c", "lineWidth": 1, "lastValueVisible": False, "priceLineVisible": False},
            "MACD_SIGNAL": {"color": "#d2b48c", "lineWidth": 1, "lastValueVisible": False, "priceLineVisible": False},
        }
        options_json = json.dumps(options)
        candle_json = json.dumps(candle_opts)
        volume_json = json.dumps(volume_opts)
        line_styles_json = json.dumps(line_styles)

        html = textwrap.dedent(
            f"""<!DOCTYPE html>
            <html>
            <head>
              <meta charset='utf-8'>
              <style>
                html,body{{ margin:0; padding:0; width:100%; height:100%; background:#0f1419; color:#c8d1da; }}
                #wrap{{ position:relative; width:100%; height:100%; }}
                #chart{{ position:relative; width:100%; height:100%; }}
                #overlay{{ position:absolute; top:8px; left:8px; display:flex; gap:8px; z-index:30; pointer-events:none; align-items:flex-start; }}
                .legend{{ background:rgba(16,20,25,0.92); color:#c8d1da; padding:6px 8px; border:1px solid rgba(197,203,206,0.2); border-radius:4px; font:12px 'Segoe UI',sans-serif; min-width:140px; pointer-events:none; }}
                .legend-row{{ display:flex; justify-content:space-between; gap:12px; }}
                #magnifier{{ position:absolute; top:0; bottom:0; width:120px; background:rgba(255,255,255,0.10); display:none; z-index:15; pointer-events:none; border-left:1px solid rgba(255,255,255,0.10); border-right:1px solid rgba(255,255,255,0.10); }}
                #magnifier-line{{ position:absolute; top:0; bottom:0; left:50%; transform:translateX(-50%); border-left:1px dashed rgba(255,255,255,0.35); }}
                #tooltip{{ position:absolute; display:none; z-index:40; pointer-events:none; background:transparent; border:none; padding:10px 12px; box-shadow:0 10px 26px rgba(0,0,0,0.5); min-width:10px; max-width:180px; text-align:center; font-family:'Segoe UI',sans-serif; }}
                .tt-symbol{{ font-size:12px; margin-bottom:2px; opacity:0.95; }}
                .tt-price{{ font-size:30px; font-weight:600; line-height:1.05; margin:0; }}
                .tt-time{{ font-size:12px; opacity:0.85; margin-top:2px; margin-bottom:6px; }}
                .tt-meta{{ font-size:11px; opacity:0.9; line-height:1.35; text-align:left; display:grid; grid-template-columns:auto auto; gap:2px 10px; }}
                .tt-k{{ opacity:0.75; }}
                .tt-v{{ justify-self:end; }}
                .menu{{ position:relative; pointer-events:auto; }}
                .menu-btn{{ background:rgba(42,46,57,0.8); color:#c8d1da; border:1px solid rgba(197,203,206,0.2); border-radius:4px; padding:4px 8px; cursor:pointer; font:12px 'Segoe UI',sans-serif; }}
                .menu-list{{ position:absolute; top:100%; left:0; margin-top:4px; background:rgba(16,20,25,0.95); border:1px solid rgba(197,203,206,0.2); border-radius:4px; min-width:140px; display:none; flex-direction:column; z-index:20; }}
                .menu-item{{ padding:6px 8px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; gap:8px; }}
                .menu-item:hover{{ background:rgba(42,46,57,0.8); }}
                .menu-item .dot{{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
                #macd-label{{ position:absolute; left:8px; top:82%; color:#9fb3c8; font:11px 'Segoe UI',sans-serif; opacity:0.8; pointer-events:none; z-index:25; letter-spacing:0.5px; }}
              </style>
              <script>{js}</script>
            </head>
            <body>
              <div id='wrap'>
                <div id='chart'></div>
                <div id='magnifier'><div id='magnifier-line'></div></div>
                <div id='overlay'>
                  <div class='menu'>
                    <div class='menu-btn' id='menu-btn'>Options ▾</div>
                    <div class='menu-list' id='menu-list'></div>
                  </div>
                  <div class='legend' id='header-info' style='pointer-events:none;'></div>
                  <div class='legend' id='legend' style='display:none;'></div>
                </div>
                <div id='macd-label'>MACD</div>
                <div id='tooltip'></div>
              </div>
              <script>
                window.onerror=(msg)=>{{document.title='JSERR: '+msg;}};
                let currentTz='America/New_York';
                function formatTime(seconds){{
                  const date=new Date(seconds*1000);
                  const localized=new Date(date.toLocaleString('en-US',{{timeZone:currentTz}}));
                  const hh=localized.getHours().toString().padStart(2,'0');
                  const mm=localized.getMinutes().toString().padStart(2,'0');
                  const ss=localized.getSeconds().toString().padStart(2,'0');
                  return `${{hh}}:${{mm}}:${{ss}}`;
                }}
                function setChartTimeZone(tzName){{
                  currentTz = tzName || 'UTC';
                  chart.applyOptions({{
                    localization:{{timeFormatter:formatTime}},
                    timeScale:{{tickMarkFormatter:formatTime}}
                  }});
                }}
                const options={options_json};
                options.localization.timeFormatter=formatTime;
                options.timeScale.tickMarkFormatter=formatTime;
                const container=document.getElementById('chart');
                const chart=LightweightCharts.createChart(container, options);
                const candleSeries=chart.addSeries(LightweightCharts.CandlestickSeries, {candle_json});
                const volumeSeries=chart.addSeries(LightweightCharts.HistogramSeries, {volume_json});
                chart.priceScale('').applyOptions({{visible:false}});
                const lineStyles={line_styles_json};
                const lineSeriesMap={{}};
                const macdSeriesMap={{}};
                const menuState={{VOLUME:true,VWAP:true,EMA9:true,EMA20:true,TOOLTIP:true}};
                let lastPriceLine=null;
                let lastHeader=null;
                const barStore=new Map();
                window.__symbol = window.__symbol || '';
                const MACD_PANE_INDEX=1;
                function volumePoint(bar){{
                  if(!bar||bar.time===undefined){{return null;}}
                  const up=bar.close===undefined||bar.open===undefined?true:(bar.close>=bar.open);
                  const color=up?'rgba(38,166,154,0.28)':'rgba(239,83,80,0.28)';
                  return {{time:bar.time,value:bar.volume||0,color}};
                }}
                function updateLastPriceLine(bar){{
                  if(!bar||bar.close===undefined){{return;}}
                  const up=bar.open===undefined?true:(bar.close>=bar.open);
                  const color=up?'#26a69a':'#ef5350';
                  if(lastPriceLine){{candleSeries.removePriceLine(lastPriceLine);}}
                  lastPriceLine=candleSeries.createPriceLine({{price:bar.close,color,lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dotted,axisLabelVisible:true}});
                }}
                function ensureLineSeries(name, paneIndex=0){{
                  const key=`${{name}}_${{paneIndex}}`;
                  if(lineSeriesMap[key]){{return lineSeriesMap[key];}}
                  const style=lineStyles[name]||{{color:'#cccccc',lineWidth:1}};
                  lineSeriesMap[key]=chart.addSeries(LightweightCharts.LineSeries, style, paneIndex);
                  return lineSeriesMap[key];
                }}
                function ensureMacdSeries(name){{
                  if(macdSeriesMap[name]){{return macdSeriesMap[name];}}
                  if(name==='MACD_HIST'){{
                    macdSeriesMap[name]=chart.addSeries(LightweightCharts.HistogramSeries, {{color:'#1abc9c', base:0, lastValueVisible:false, priceLineVisible:false}}, MACD_PANE_INDEX);
                  }} else if(name==='MACD_SIGNAL'){{
                    if(!macdSeriesMap['MACD_HIST']){{macdSeriesMap['MACD_HIST']=chart.addSeries(LightweightCharts.HistogramSeries, {{color:'#1abc9c', base:0, lastValueVisible:false, priceLineVisible:false}}, MACD_PANE_INDEX);}}
                    macdSeriesMap[name]=chart.addSeries(LightweightCharts.LineSeries, {{color:'#d2b48c', lineWidth:1, lastValueVisible:false, priceLineVisible:false}}, MACD_PANE_INDEX);
                  }} else {{
                    if(!macdSeriesMap['MACD_HIST']){{macdSeriesMap['MACD_HIST']=chart.addSeries(LightweightCharts.HistogramSeries, {{color:'#1abc9c', base:0, lastValueVisible:false, priceLineVisible:false}}, MACD_PANE_INDEX);}}
                    macdSeriesMap[name]=chart.addSeries(LightweightCharts.LineSeries, {{color:'#1abc9c', lineWidth:1, lastValueVisible:false, priceLineVisible:false}}, MACD_PANE_INDEX);
                  }}
                  return macdSeriesMap[name];
                }}
                function setSeriesVisible(name, visible){{
                  if(name==='VOLUME'){{volumeSeries.applyOptions({{visible:visible}}); menuState.VOLUME=visible; return;}}
                  if(name==='TOOLTIP'){{menuState.TOOLTIP=visible; toolTip.style.display=visible?'block':'none'; return;}}
                  const s=ensureLineSeries(name, 0);
                  s.applyOptions({{visible:visible}});
                  menuState[name]=visible;
                }}
                function buildMenu(){{
                  const menu=document.getElementById('menu-list');
                  const items=[{{name:'VOLUME', label:'Volume', color:'#888888'}},{{name:'VWAP', label:'VWAP', color:lineStyles.VWAP.color}},{{name:'EMA9', label:'EMA9', color:lineStyles.EMA9.color}},{{name:'EMA20', label:'EMA20', color:lineStyles.EMA20.color}},{{name:'TOOLTIP', label:'Tooltip', color:'#aaaaaa'}}];
                  menu.innerHTML='';
                  items.forEach(item=>{{
                    const div=document.createElement('div');
                    div.className='menu-item';
                    div.dataset.name=item.name;
                    const dot=document.createElement('span');
                    dot.className='dot';
                    dot.style.background=item.color;
                    const label=document.createElement('span');
                    label.textContent=item.label;
                    const state=document.createElement('span');
                    state.textContent=menuState[item.name]?'on':'off';
                    div.appendChild(dot);div.appendChild(label);div.appendChild(state);
                    div.onclick=()=>{{const newVis=!menuState[item.name];setSeriesVisible(item.name,newVis);state.textContent=newVis?'on':'off';}};
                    menu.appendChild(div);
                  }});
                }}
                function toggleMenu(){{
                  const menu=document.getElementById('menu-list');
                  menu.style.display=menu.style.display==='flex'?'none':'flex';
                }}
                document.getElementById('menu-btn').onclick=toggleMenu;
                document.addEventListener('click',(e)=>{{
                  const menu=document.getElementById('menu-list');
                  const btn=document.getElementById('menu-btn');
                  if(!menu.contains(e.target)&&!btn.contains(e.target)){{menu.style.display='none';}}
                }});
                buildMenu();
                const toolTip=document.getElementById('tooltip');
                const magnifier=document.getElementById('magnifier');
                const wrap=document.getElementById('wrap');
                const MAG_WIDTH=120;
                const PAD=30;
                function clamp(v,min,max){{return Math.max(min, Math.min(max, v));}}
                chart.subscribeCrosshairMove(param=>{{
                  if(!param || param.time===undefined || !param.point){{toolTip.style.display='none';magnifier.style.display='none';return;}}
                  if(!menuState.TOOLTIP){{toolTip.style.display='none';}}
                  const wrapW=wrap.clientWidth;
                  const bandLeft=clamp(param.point.x - MAG_WIDTH/2, 0, wrapW - MAG_WIDTH);
                  magnifier.style.left=`${{bandLeft}}px`;
                  magnifier.style.display='block';
                  const ts=typeof param.time==='number'?param.time:param.time.timestamp;
                  const priceVal=(param.seriesPrices && (param.seriesPrices.get?param.seriesPrices.get(candleSeries):param.seriesPrices[candleSeries]))||param.price|| (lastHeader?lastHeader.last:undefined);
                  const volVal = (param.seriesPrices && (param.seriesPrices.get?param.seriesPrices.get(volumeSeries):param.seriesPrices[volumeSeries])) || (lastHeader?lastHeader.barVol:undefined);
                  const bar=barStore.get(ts);
                  let tenths=0;
                  if(bar){{
                    if(bar.tenths!==undefined){{tenths=bar.tenths;}}
                    else if(bar.time_ms!==undefined){{tenths=Math.floor((bar.time_ms%1000)/100);}}
                    else if(bar.timeMs!==undefined){{tenths=Math.floor((bar.timeMs%1000)/100);}}
                  }}
                  const closePx = (bar&&bar.close!==undefined)?bar.close:priceVal;
                  const vol = (bar&&bar.volume!==undefined)?bar.volume:volVal;
                  const up = (bar&&bar.open!==undefined&&bar.close!==undefined)?(bar.close>=bar.open):true;
                  const accent = up ? '#26a69a' : '#ef5350';
                  if(menuState.TOOLTIP){{
                    toolTip.innerHTML = `
                      <div class="tt-symbol" style="color:${{accent}}">${{window.__symbol}}</div>
                      <div class="tt-price">${{closePx!==undefined?Number(closePx).toFixed(2):'--'}}</div>
                      <div class="tt-time">${{formatTime(ts)}}</div>
                      <div class="tt-meta">
                        <div class="tt-k">Vol</div><div class="tt-v">${{vol!==undefined?Number(vol).toLocaleString():'--'}}</div>
                        <div class="tt-k">O</div><div class="tt-v">${{(bar&&bar.open!==undefined)?Number(bar.open).toFixed(2):'--'}}</div>
                        <div class="tt-k">H</div><div class="tt-v">${{(bar&&bar.high!==undefined)?Number(bar.high).toFixed(2):'--'}}</div>
                        <div class="tt-k">L</div><div class="tt-v">${{(bar&&bar.low!==undefined)?Number(bar.low).toFixed(2):'--'}}</div>
                        <div class="tt-k">C</div><div class="tt-v">${{(bar&&bar.close!==undefined)?Number(bar.close).toFixed(2):'--'}}</div>
                      </div>
                    `;
                    toolTip.style.display='block';
                    const left=clamp((bandLeft + MAG_WIDTH/2) - toolTip.clientWidth/2, PAD, wrapW - toolTip.clientWidth - PAD);
                    toolTip.style.left=`${{left}}px`;
                    toolTip.style.top=`${{PAD}}px`;
                  }} else {{
                    toolTip.style.display='none';
                  }}
                }});
                function renderHeader(hdr){{
                  const el=document.getElementById('header-info');
                  if(!hdr){{el.innerHTML='';return;}}
                  const parts=[];
                  if(hdr.last!==undefined){{parts.push(`Last: ${{Number(hdr.last).toFixed(2)}}`);}}
                  if(hdr.bid!==undefined){{parts.push(`Bid: ${{Number(hdr.bid).toFixed(2)}}`);}}
                  if(hdr.ask!==undefined){{parts.push(`Ask: ${{Number(hdr.ask).toFixed(2)}}`);}}
                  if(hdr.dayVol!==undefined){{parts.push(`DayVol: ${{Number(hdr.dayVol).toLocaleString()}}`);}}
                  if(hdr.barVol!==undefined){{
                    if(hdr.vel!==undefined){{parts.push(`BarVol: ${{Number(hdr.barVol).toLocaleString()}} (vel: ${{Number(hdr.vel).toFixed(2)}}x)`);}} else {{parts.push(`BarVol: ${{Number(hdr.barVol).toLocaleString()}}`);}}
                  }}
                  el.innerHTML=parts.join(' | ');
                  lastHeader=hdr;
                }}
                window.lwc_setSymbol=function(s){{window.__symbol=s||'';}};
                window.lwc_setData=function(data){{
                  const bars=data||[];
                  barStore.clear();
                  bars.forEach(b=>{{ if(b && b.time!==undefined) barStore.set(b.time,b); }});
                  candleSeries.setData(bars);
                  const vol=bars.map(volumePoint).filter(v=>v);
                  volumeSeries.setData(vol);
                  if(bars.length>0){{updateLastPriceLine(bars[bars.length-1]);}}
                }};
                window.lwc_update=function(bar){{
                  if(!bar){{return;}}
                  if(bar.time!==undefined){{barStore.set(bar.time, bar);}}
                  candleSeries.update(bar);
                  const vb=volumePoint(bar);
                  if(vb){{volumeSeries.update(vb);}}
                  updateLastPriceLine(bar);
                }};
                window.lwc_setSeries=function(name, points){{
                  if(name.startsWith('MACD_HIST')){{
                    const target=ensureMacdSeries('MACD_HIST');
                    const mapped=(points||[]).map(p=>{{const c=(p.value||0)>=0 ? '#27ae60' : '#c0392b'; return {{...p, color:c}};}});
                    target.setData(mapped);
                    return;
                  }}
                  let target;
                  if(name.startsWith('MACD')){{target=ensureMacdSeries(name);}}
                  else {{target=ensureLineSeries(name, 0);}}
                  target.setData(points||[]);
                }};
                window.lwc_setHeader=function(hdr){{renderHeader(hdr);}};
              </script>
            </body></html>"""
        )
        self.setHtml(html)

    def set_data(self, bars: list[dict]) -> None:
        payload = json.dumps(bars)
        self.page().runJavaScript(f"window.lwc_setData({payload});")

    def update_bar(self, bar: dict) -> None:
        payload = json.dumps(bar)
        self.page().runJavaScript(f"window.lwc_update({payload});")

    def set_series(self, name: str, points: list[dict]) -> None:
        payload = json.dumps(points)
        self.page().runJavaScript(f"window.lwc_setSeries('{name}', {payload});")

    def set_header(self, header: dict) -> None:
        payload = json.dumps(header)
        self.page().runJavaScript(f"window.lwc_setHeader({payload});")
