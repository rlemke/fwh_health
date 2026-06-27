"""Shared self-contained MapLibre choropleth renderer for the health maps.

One function, ``render(fc, metrics, ...)`` → a self-contained HTML string: a
quantile-binned fill layer driven by a metric dropdown, a legend, click popups,
and an attribution footer. Used by the US-state, US-county, and world maps so
they share one look and one code path. Missing values render grey ("no data").
"""
from __future__ import annotations
import json


def render(
    fc: dict,
    metrics: list[dict],          # [{"key": "m_cancer", "label": "Cancer — ..."}]
    *,
    title: str,
    subtitle: str,
    attribution_html: str,
    center: list[float],          # [lng, lat]
    zoom: float,
    name_key: str = "name",
    value_decimals: int = 1,
) -> str:
    data_js = json.dumps(fc, separators=(",", ":"))
    metrics_js = json.dumps(metrics)
    first = metrics[0]["key"]
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
 html,body,#map{{height:100%;margin:0}}
 .panel{{position:absolute;top:10px;left:10px;z-index:2;background:#fff;padding:12px 14px;border-radius:8px;
  box-shadow:0 1px 6px rgba(0,0,0,.3);font:14px/1.4 system-ui,sans-serif;max-width:340px}}
 .panel h1{{font-size:15px;margin:0 0 6px}} .panel p{{margin:0 0 8px;color:#555;font-size:12px}}
 select{{width:100%;padding:6px;font-size:14px}}
 .legend{{position:absolute;bottom:24px;left:10px;z-index:2;background:#fff;padding:8px 10px;border-radius:8px;
  box-shadow:0 1px 6px rgba(0,0,0,.3);font:12px system-ui,sans-serif}}
 .legend i{{display:inline-block;width:14px;height:14px;margin-right:6px;vertical-align:-2px}}
 .maplibregl-popup-content{{font:13px system-ui,sans-serif}} .maplibregl-popup-content b{{font-size:14px}}
 .attribution{{position:absolute;bottom:0;right:0;z-index:2;background:rgba(255,255,255,.85);
  padding:4px 8px;font:11px system-ui,sans-serif;color:#444;max-width:420px}}
 .attribution a{{color:#1565c0;text-decoration:none}}
</style></head><body>
<div id="map"></div>
<div class="panel"><h1>{title}</h1><p>{subtitle}</p><select id="metric"></select></div>
<div class="legend" id="legend"></div>
<div class="attribution">{attribution_html}</div>
<script>
const DATA={data_js}, METRICS={metrics_js}, DEC={value_decimals}, NAMEKEY={json.dumps(name_key)};
const map=new maplibregl.Map({{container:'map',
 style:{{version:8,sources:{{carto:{{type:'raster',
  tiles:['https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{{z}}/{{x}}/{{y}}.png'],tileSize:256,
  attribution:'© OpenStreetMap © CARTO'}}}},layers:[{{id:'bg',type:'raster',source:'carto'}}]}},
 center:{json.dumps(center)},zoom:{zoom}}});
const RAMP=['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4','#2c7fb8','#253494'];
const NODATA='#e0e0e0';
// n colours sampled across the FULL ramp (always includes the lightest + darkest),
// so however many distinct breaks survive, the top bin is the darkest colour and
// the bottom data bin is the pale yellow — both clearly distinct from no-data grey.
function rampColors(n){{if(n<=1)return [RAMP[RAMP.length-1]];
  const out=[];for(let i=0;i<n;i++)out.push(RAMP[Math.round(i*(RAMP.length-1)/(n-1))]);return out;}}
function vals(k){{return DATA.features.map(f=>f.properties[k]).filter(v=>v!=null).sort((a,b)=>a-b);}}
function breaks(k){{const v=vals(k);if(!v.length)return [1,2,3,4,5];
  // Quantile breaks, deduped to STRICTLY ASCENDING — discrete/skewed metrics
  // (e.g. flu activity level 0–13) otherwise produce equal adjacent breaks,
  // which makes MapLibre's `step` expression invalid so the fill won't update.
  const raw=[0.1,0.27,0.45,0.63,0.81].map(q=>v[Math.floor(q*v.length)]);
  const out=[];for(const x of raw){{if(out.length===0||x>out[out.length-1])out.push(x);}}
  return out;}}
function colorExpr(k){{const b=breaks(k);const c=rampColors(b.length+1);
  // missing (-1) -> grey; all real data (>=0) spans the ramp light->dark.
  const e=['step',['coalesce',['get',k],-1],NODATA,-0.5,c[0]];
  b.forEach((bk,i)=>e.push(bk,c[i+1]));return e;}}
function legend(k){{const v=vals(k),b=breaks(k);const c=rampColors(b.length+1);const m=METRICS.find(x=>x.key===k);
  let h='<b>'+m.label+'</b><br><div><i style="background:'+NODATA+'"></i>no data</div>';
  const lo=[v.length?v[0]:0,...b];const hi=[...b,(v.length?v[v.length-1]:0)];
  for(let i=0;i<c.length;i++){{
    h+='<div><i style="background:'+c[i]+'"></i>'+(+lo[i]).toFixed(DEC)+' – '+(+hi[i]).toFixed(DEC)+'</div>';}}
  document.getElementById('legend').innerHTML=h;}}
map.on('load',()=>{{
 map.addSource('s',{{type:'geojson',data:DATA}});
 map.addLayer({{id:'fill',type:'fill',source:'s',paint:{{'fill-color':colorExpr('{first}'),'fill-opacity':0.85}}}});
 map.addLayer({{id:'line',type:'line',source:'s',paint:{{'line-color':'#fff','line-width':0.4}}}});
 const sel=document.getElementById('metric');
 METRICS.forEach(m=>{{const o=document.createElement('option');o.value=m.key;o.textContent=m.label;sel.appendChild(o);}});
 function apply(k){{map.setPaintProperty('fill','fill-color',colorExpr(k));legend(k);}}
 sel.onchange=()=>apply(sel.value); apply('{first}');
 map.on('click','fill',e=>{{const p=e.features[0].properties;let h='<b>'+p[NAMEKEY]+'</b><br>';
  METRICS.forEach(m=>{{const v=p[m.key];h+=m.label.split(' —')[0]+': '+(v!=null?(+v).toFixed(DEC):'n/a')+'<br>';}});
  new maplibregl.Popup({{maxWidth:'280px'}}).setLngLat(e.lngLat).setHTML(h).addTo(map);}});
 map.on('mouseenter','fill',()=>map.getCanvas().style.cursor='pointer');
 map.on('mouseleave','fill',()=>map.getCanvas().style.cursor='');
}});
</script></body></html>"""
