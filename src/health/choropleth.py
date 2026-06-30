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
    note: str = "",               # caveat about data NOT present
    note_popup: bool = False,     # show ``note`` as a dismissible popup (on load + ℹ️ button)
                                  # instead of the always-on amber box
) -> str:
    data_js = json.dumps(fc, separators=(",", ":"))
    metrics_js = json.dumps(metrics)
    first = metrics[0]["key"]
    if note and note_popup:
        note_html = '<button id="infobtn" class="infobtn">&#8505;&#65039; About this data</button>'
        modal_html = (f'<div id="infomodal" class="modal"><div class="modalcard">'
                      f'<button id="infoclose" class="modalclose">&times;</button>'
                      f'<h2>About this data</h2><div class="modalbody">{note}</div></div></div>')
    elif note:
        note_html = f'<div class="note"><b>Where data is missing (grey):</b> {note}</div>'
        modal_html = ""
    else:
        note_html = modal_html = ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
 html,body,#map{{height:100%;margin:0}}
 .panel{{position:absolute;top:10px;left:10px;z-index:2;background:#fff;padding:12px 14px;border-radius:8px;
  box-shadow:0 1px 6px rgba(0,0,0,.3);font:14px/1.4 system-ui,sans-serif;max-width:340px}}
 .panel h1{{font-size:15px;margin:0 0 6px}} .panel p{{margin:0 0 8px;color:#555;font-size:12px}}
 .panel .note{{margin:8px 0 0;padding:6px 8px;background:#fff8e1;border-left:3px solid #f6c343;
  color:#5d4b00;font-size:11px;line-height:1.35;border-radius:3px}}
 select{{width:100%;padding:6px;font-size:14px}}
 .legend{{position:absolute;bottom:24px;left:10px;z-index:2;background:#fff;padding:8px 10px;border-radius:8px;
  box-shadow:0 1px 6px rgba(0,0,0,.3);font:12px system-ui,sans-serif}}
 .legend i{{display:inline-block;width:14px;height:14px;margin-right:6px;vertical-align:-2px}}
 .maplibregl-popup-content{{font:13px system-ui,sans-serif}} .maplibregl-popup-content b{{font-size:14px}}
 .attribution{{position:absolute;bottom:0;right:0;z-index:2;background:rgba(255,255,255,.85);
  padding:4px 8px;font:11px system-ui,sans-serif;color:#444;max-width:420px}}
 .attribution a{{color:#1565c0;text-decoration:none}}
 .infobtn{{margin-top:8px;width:100%;padding:7px;font-size:13px;cursor:pointer;background:#fff8e1;
  border:1px solid #f6c343;border-radius:4px;color:#5d4b00}}
 .infobtn:hover{{background:#fff2c4}}
 .modal{{position:absolute;inset:0;z-index:5;background:rgba(0,0,0,.45);display:flex;
  align-items:center;justify-content:center}}
 .modalcard{{background:#fff;max-width:460px;margin:16px;padding:18px 20px 20px;border-radius:10px;
  box-shadow:0 4px 24px rgba(0,0,0,.4);position:relative;font:13px/1.5 system-ui,sans-serif;
  max-height:80vh;overflow:auto}}
 .modalcard h2{{margin:0 0 8px;font-size:16px}} .modalbody{{color:#333}} .modalbody b{{color:#111}}
 .modalclose{{position:absolute;top:6px;right:10px;border:none;background:none;font-size:24px;
  line-height:1;cursor:pointer;color:#999}} .modalclose:hover{{color:#444}}
</style></head><body>
<div id="map"></div>
<div class="panel"><h1>{title}</h1><p>{subtitle}</p><select id="metric"></select>{note_html}</div>
<div class="legend" id="legend"></div>
<div class="attribution">{attribution_html}</div>
{modal_html}
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
// "About this data" popup: shown on load (modal markup present), reopened via the
// ℹ️ button, dismissed by × or a backdrop click.
const _im=document.getElementById('infomodal');
if(_im){{const ib=document.getElementById('infobtn'),ic=document.getElementById('infoclose');
 if(ib)ib.onclick=()=>{{_im.style.display='flex';}};
 if(ic)ic.onclick=()=>{{_im.style.display='none';}};
 _im.onclick=e=>{{if(e.target===_im)_im.style.display='none';}};}}
</script></body></html>"""
