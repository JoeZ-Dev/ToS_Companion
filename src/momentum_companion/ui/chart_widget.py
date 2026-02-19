from __future__ import annotations

import json
from pathlib import Path
import textwrap

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
            "priceScale": {"scaleMargins": {"top": 0.05, "bottom": 0.25}},
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
            "scaleMargins": {"top": 0.7, "bottom": 0},
            "lastValueVisible": False,
            "priceLineVisible": False,
        }
        line_styles = {
            "VWAP": {"color": "#b455ff", "lineWidth": 1, "lastValueVisible": False, "priceLineVisible": False},
            "EMA9": {"color": "#f5c542", "lineWidth": 1, "lastValueVisible": False, "priceLineVisible": False},
            "EMA20": {"color": "#4aa3ff", "lineWidth": 1, "lastValueVisible": False, "priceLineVisible": False},
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
                html,body,#chart {{ margin:0; padding:0; width:100%; height:100%; background:#0f1419; color:#c8d1da; }}
                #chart {{ position:relative; }}
                #overlay {{ position:absolute; top:8px; left:8px; display:flex; gap:8px; z-index:10; pointer-events:none; align-items:flex-start; }}
                .legend {{ background:rgba(16,20,25,0.92); color:#c8d1da; padding:6px 8px; border:1px solid rgba(197,203,206,0.2); border-radius:4px; font:12px 'Segoe UI',sans-serif; min-width:140px; pointer-events:none; }}
                .legend-row {{ display:flex; justify-content:space-between; gap:12px; }}
                #tooltip {{ position:absolute; display:none; min-width:120px; z-index:15; pointer-events:none; background:transparent; border:none; box-shadow:none; color:#c8d1da; font:12px 'Segoe UI',sans-serif; }}
                #magnifier {{ position:absolute; top:0; height:100%; display:none; background:rgba(128,128,128,0.1); z-index:12; pointer-events:none; }}
                #magnifier-line {{ position:absolute; top:0; bottom:0; left:50%; width:0; border-left:1px dashed rgba(200,200,200,0.6); }}
                .menu {{ position:relative; pointer-events:auto; }}
                .menu-btn {{ background:rgba(42,46,57,0.8); color:#c8d1da; border:1px solid rgba(197,203,206,0.2); border-radius:4px; padding:4px 8px; cursor:pointer; font:12px 'Segoe UI',sans-serif; }}
                .menu-list {{ position:absolute; top:100%; left:0; margin-top:4px; background:rgba(16,20,25,0.95); border:1px solid rgba(197,203,206,0.2); border-radius:4px; min-width:140px; display:none; flex-direction:column; z-index:20; }}
                .menu-item {{ padding:6px 8px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; gap:8px; }}
                .menu-item:hover {{ background:rgba(42,46,57,0.8); }}
                .menu-item .dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
              </style>
              <script>{js}</script>
            </head>
            <body>
              <div id='chart'>
                <div id='magnifier'><div id='magnifier-line'></div></div>
              </div>
              <div id='overlay'>
                <div class='menu'>
                  <div class='menu-btn' id='menu-btn'>Studies ▾</div>
                  <div class='menu-list' id='menu-list'></div>
                </div>
                <div class='legend' id='header-info' style='pointer-events:none;'></div>
                <div class='legend' id='legend' style='display:none;'></div>
              </div>
              <div class='legend' id='tooltip' style='display:none;'></div>
              <script>
                window.onerror=(msg)=>{{document.title='JSERR: '+msg;}};
                function utcToET(time){{
                  const date=new Date(time*1000);
                  const et=new Date(date.toLocaleString('en-US',{{timeZone:'America/New_York'}}));
                  const hh=et.getHours().toString().padStart(2,'0');
                  const mm=et.getMinutes().toString().padStart(2,'0');
                  return `${{hh}}:${{mm}}`;
                }}
                const options={options_json};
                options.localization.timeFormatter=utcToET;
                const container=document.getElementById('chart');
                const chart=LightweightCharts.createChart(container, options);
                const candleSeries=chart.addCandlestickSeries({candle_json});
                const volumeSeries=chart.addHistogramSeries({volume_json});
                chart.priceScale('').applyOptions({{visible:false}});
                const lineStyles={line_styles_json};
                const lineSeriesMap={{}};
                const menuState={{VOLUME:true,VWAP:true,EMA9:true,EMA20:true}};
                let lastPriceLine=null;
                let lastHeader=null;
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
                function ensureLineSeries(name){{
                  if(lineSeriesMap[name]){{return lineSeriesMap[name];}}
                  const style=lineStyles[name]||{{color:'#cccccc',lineWidth:1}};
                  lineSeriesMap[name]=chart.addLineSeries(style);
                  return lineSeriesMap[name];
                }}
                function setSeriesVisible(name, visible){{
                  if(name==='VOLUME'){{volumeSeries.applyOptions({{visible:visible}}); menuState.VOLUME=visible; return;}}
                  const s=ensureLineSeries(name);
                  s.applyOptions({{visible:visible}});
                  menuState[name]=visible;
                }}
                function buildMenu(){{
                  const menu=document.getElementById('menu-list');
                  const items=[{{name:'VOLUME', label:'Volume', color:'#888888'}},{{name:'VWAP', label:'VWAP', color:lineStyles.VWAP.color}},{{name:'EMA9', label:'EMA9', color:lineStyles.EMA9.color}},{{name:'EMA20', label:'EMA20', color:lineStyles.EMA20.color}}];
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
                const MAG_WIDTH=120;
                const PAD=8;
                function clamp(v,min,max){{return Math.max(min, Math.min(max, v));}}
                chart.subscribeCrosshairMove(param=>{{
                  if(!param || param.time===undefined || !param.point){{toolTip.style.display='none';magnifier.style.display='none';return;}}
                  const priceVal=(param.seriesPrices && (param.seriesPrices.get?param.seriesPrices.get(candleSeries):param.seriesPrices[candleSeries]))||param.price|| (lastHeader?lastHeader.last:undefined);
                  const volVal = (param.seriesPrices && (param.seriesPrices.get?param.seriesPrices.get(volumeSeries):param.seriesPrices[volumeSeries])) || (lastHeader?lastHeader.barVol:undefined);
                  const ts=typeof param.time==='number'?param.time:param.time.timestamp;
                  const priceRow = priceVal!==undefined ? `<div class='legend-row'><span>Price</span><span>${{Number(priceVal).toFixed(2)}}</span></div>` : '';
                  const volRow = volVal!==undefined ? `<div class='legend-row'><span>Vol</span><span>${{Number(volVal).toLocaleString()}}</span></div>` : '';
                  toolTip.innerHTML=`<div class='legend-row'><span>Time</span><span>${{utcToET(ts)}}</span></div>${{priceRow}}${{volRow}}`;
                  const bandLeft=clamp(param.point.x - MAG_WIDTH/2, 0, container.clientWidth - MAG_WIDTH);
                  magnifier.style.left=`${{bandLeft}}px`;
                  magnifier.style.width=`${{MAG_WIDTH}}px`;
                  magnifier.style.display='block';
                  const left=clamp(bandLeft + MAG_WIDTH/2 - toolTip.clientWidth/2, PAD, container.clientWidth - toolTip.clientWidth - PAD);
                  const top=PAD;
                  toolTip.style.left=`${{left}}px`;
                  toolTip.style.top=`${{top}}px`;
                  toolTip.style.display='block';
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
                window.lwc_setData=function(data){{
                  const bars=data||[];
                  candleSeries.setData(bars);
                  const vol=bars.map(volumePoint).filter(v=>v);
                  volumeSeries.setData(vol);
                  if(bars.length>0){{updateLastPriceLine(bars[bars.length-1]);}}
                }};
                window.lwc_update=function(bar){{
                  if(!bar){{return;}}
                  candleSeries.update(bar);
                  const vb=volumePoint(bar);
                  if(vb){{volumeSeries.update(vb);}}
                  updateLastPriceLine(bar);
                }};
                window.lwc_setSeries=function(name, points){{
                  const s=ensureLineSeries(name);
                  s.setData(points||[]);
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
