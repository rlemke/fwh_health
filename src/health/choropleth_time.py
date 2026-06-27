"""Time-animated MapLibre choropleth — one map, a series dropdown + a month slider.

Sibling of ``choropleth.py``. The difference that matters: this renderer holds a
**fixed colour scale per series**, computed once across *all* months, so dragging
the month slider shows a wave rise and fall against a stable legend instead of
re-quantising every frame (which would make every month look the same). Each
feature carries one numeric property per ``<series>_<month>`` cell; missing cells
render grey ("no data"). A play/pause button animates the months.

``render_timeseries(fc, series, months, ...) -> str`` returns a self-contained
HTML string (MapLibre + CARTO basemap, no API key, works from ``file://``).
"""
from __future__ import annotations
import json


def render_timeseries(
    fc: dict,
    series: list[dict],          # [{"key": "covid", "label": "COVID-19"}, ...]
    months: list[str],           # ["2021-01", "2021-02", ...] sorted ascending
    *,
    title: str,
    subtitle: str,
    value_label: str,            # legend/popup unit, e.g. "avg weekly admissions / 100k"
    attribution_html: str,
    center: list[float],         # [lng, lat]
    zoom: float,
    name_key: str = "name",
    value_decimals: int = 2,
    note: str = "",              # caveat about missing/partial data (amber box)
) -> str:
    data_js = json.dumps(fc, separators=(",", ":"))
    series_js = json.dumps(series)
    months_js = json.dumps(months)
    first = series[0]["key"]
    note_html = f'<div class="note"><b>Reading this map:</b> {note}</div>' if note else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
 html,body,#map{{height:100%;margin:0}}
 .panel{{position:absolute;top:10px;left:10px;z-index:2;background:#fff;padding:12px 14px;border-radius:8px;
  box-shadow:0 1px 6px rgba(0,0,0,.3);font:14px/1.4 system-ui,sans-serif;max-width:360px}}
 .panel h1{{font-size:15px;margin:0 0 6px}} .panel p{{margin:0 0 8px;color:#555;font-size:12px}}
 .panel .note{{margin:8px 0 0;padding:6px 8px;background:#fff8e1;border-left:3px solid #f6c343;
  color:#5d4b00;font-size:11px;line-height:1.35;border-radius:3px}}
 select{{width:100%;padding:6px;font-size:14px}}
 .timerow{{display:flex;align-items:center;gap:8px;margin-top:10px}}
 .timerow input[type=range]{{flex:1}} .timerow button{{padding:4px 9px;font-size:13px;cursor:pointer}}
 .month{{font-weight:600;font-size:13px;min-width:74px;text-align:right;font-variant-numeric:tabular-nums}}
 .legend{{position:absolute;bottom:24px;left:10px;z-index:2;background:#fff;padding:8px 10px;border-radius:8px;
  box-shadow:0 1px 6px rgba(0,0,0,.3);font:12px system-ui,sans-serif}}
 .legend i{{display:inline-block;width:14px;height:14px;margin-right:6px;vertical-align:-2px}}
 .maplibregl-popup-content{{font:13px system-ui,sans-serif}} .maplibregl-popup-content b{{font-size:14px}}
 .attribution{{position:absolute;bottom:0;right:0;z-index:2;background:rgba(255,255,255,.85);
  padding:4px 8px;font:11px system-ui,sans-serif;color:#444;max-width:440px}}
 .attribution a{{color:#1565c0;text-decoration:none}}
</style></head><body>
<div id="map"></div>
<div class="panel"><h1>{title}</h1><p>{subtitle}</p>
 <select id="series"></select>
 <div class="timerow"><button id="play">▶</button>
  <input type="range" id="slider" min="0" max="{len(months) - 1}" value="{len(months) - 1}" step="1">
  <span class="month" id="month"></span></div>
 {note_html}</div>
<div class="legend" id="legend"></div>
<div class="attribution">{attribution_html}</div>
<script>
const DATA={data_js}, SERIES={series_js}, MONTHS={months_js}, DEC={value_decimals};
const NAMEKEY={json.dumps(name_key)}, VLABEL={json.dumps(value_label)};
const map=new maplibregl.Map({{container:'map',
 style:{{version:8,sources:{{carto:{{type:'raster',
  tiles:['https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{{z}}/{{x}}/{{y}}.png'],tileSize:256,
  attribution:'© OpenStreetMap © CARTO'}}}},layers:[{{id:'bg',type:'raster',source:'carto'}}]}},
 center:{json.dumps(center)},zoom:{zoom}}});
const RAMP=['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4','#2c7fb8','#253494'];
const NODATA='#e0e0e0';
function rampColors(n){{if(n<=1)return [RAMP[RAMP.length-1]];
  const out=[];for(let i=0;i<n;i++)out.push(RAMP[Math.round(i*(RAMP.length-1)/(n-1))]);return out;}}
function cell(s,mi){{return s+'_'+MONTHS[mi];}}
// FIXED scale per series: all values across every month, so the slider shows a
// wave against a stable legend (not a per-month re-quantise).
function seriesVals(s){{const v=[];for(let mi=0;mi<MONTHS.length;mi++){{const k=cell(s,mi);
  for(const f of DATA.features){{const x=f.properties[k];if(x!=null)v.push(x);}}}}
  return v.sort((a,b)=>a-b);}}
const BREAKS={{}};
function breaks(s){{if(BREAKS[s])return BREAKS[s];const v=seriesVals(s);
  if(!v.length){{BREAKS[s]=[1,2,3,4,5];return BREAKS[s];}}
  const raw=[0.1,0.27,0.45,0.63,0.81,0.93].map(q=>v[Math.floor(q*v.length)]);
  const out=[];for(const x of raw){{if(out.length===0||x>out[out.length-1])out.push(x);}}
  BREAKS[s]=out;return out;}}
function colorExpr(s,mi){{const b=breaks(s);const c=rampColors(b.length+1);
  const e=['step',['coalesce',['get',cell(s,mi)],-1],NODATA,-0.5,c[0]];
  b.forEach((bk,i)=>e.push(bk,c[i+1]));return e;}}
function fmtMonth(m){{const[y,mo]=m.split('-');
  return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+mo-1]+' '+y;}}
function legend(s){{const v=seriesVals(s),b=breaks(s);const c=rampColors(b.length+1);
  const lbl=SERIES.find(x=>x.key===s).label;
  let h='<b>'+lbl+'</b><br><span style="color:#666;font-size:11px">'+VLABEL+'</span><br>'+
        '<div><i style="background:'+NODATA+'"></i>no data</div>';
  const lo=[v.length?v[0]:0,...b];const hi=[...b,(v.length?v[v.length-1]:0)];
  for(let i=0;i<c.length;i++)
    h+='<div><i style="background:'+c[i]+'"></i>'+(+lo[i]).toFixed(DEC)+' – '+(+hi[i]).toFixed(DEC)+'</div>';
  document.getElementById('legend').innerHTML=h;}}
map.on('load',()=>{{
 map.addSource('s',{{type:'geojson',data:DATA}});
 map.addLayer({{id:'fill',type:'fill',source:'s',paint:{{'fill-color':colorExpr('{first}',MONTHS.length-1),'fill-opacity':0.85}}}});
 map.addLayer({{id:'line',type:'line',source:'s',paint:{{'line-color':'#fff','line-width':0.4}}}});
 const selS=document.getElementById('series'),sl=document.getElementById('slider'),
       mo=document.getElementById('month'),play=document.getElementById('play');
 SERIES.forEach(s=>{{const o=document.createElement('option');o.value=s.key;o.textContent=s.label;selS.appendChild(o);}});
 function apply(){{const s=selS.value,mi=+sl.value;
  map.setPaintProperty('fill','fill-color',colorExpr(s,mi));mo.textContent=fmtMonth(MONTHS[mi]);}}
 function relegend(){{legend(selS.value);}}
 selS.onchange=()=>{{relegend();apply();}}; sl.oninput=apply;
 let timer=null;
 play.onclick=()=>{{ if(timer){{clearInterval(timer);timer=null;play.textContent='▶';return;}}
  play.textContent='⏸'; timer=setInterval(()=>{{let mi=+sl.value;mi=(mi+1)%MONTHS.length;sl.value=mi;apply();}},700); }};
 map.on('click','fill',e=>{{const p=e.features[0].properties,mi=+sl.value,m=MONTHS[mi];
  let h='<b>'+p[NAMEKEY]+'</b><br><span style="color:#666">'+fmtMonth(m)+'</span><br>';
  SERIES.forEach(s=>{{const v=p[cell(s.key,mi)];h+=s.label+': '+(v!=null?(+v).toFixed(DEC):'n/a')+'<br>';}});
  new maplibregl.Popup({{maxWidth:'260px'}}).setLngLat(e.lngLat).setHTML(h).addTo(map);}});
 map.on('mouseenter','fill',()=>map.getCanvas().style.cursor='pointer');
 map.on('mouseleave','fill',()=>map.getCanvas().style.cursor='');
 relegend();apply();
}});
</script></body></html>"""
