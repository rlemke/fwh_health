"""US state choropleth of age-adjusted death rates for cancer / diabetes /
Alzheimer's / stroke (CDC NCHS), rendered as a self-contained MapLibre HTML with
a cause dropdown and written to MinIO. Geometry is the census-domain TIGER state
GeoJSON already cached in MinIO, simplified for inline embedding.

Honest scope: NCHS gives age-adjusted DEATH RATES (per 100k) by state — the
clean, comparable, all-four-causes US mortality source. County-level deaths get
suppressed for small counties; county *prevalence* (a different measure) is a
separate CDC PLACES map.
"""
from __future__ import annotations
import io, json, html as html_mod
import boto3, requests
from shapely.geometry import shape, mapping

S3 = boto3.client("s3", endpoint_url="http://192.168.68.96:9000",
                  aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")
BUCKET = "afl-cache"
UA = {"User-Agent": "facetwork-health/1.0 (+github.com/rlemke/facetwork)"}

# NCHS "Leading Causes of Death" cause_name -> our metric key/label/colour-ramp
CAUSES = [
    ("cancer",    "Cancer",              "Cancer — deaths/100k (age-adj.)"),
    ("stroke",    "Stroke",              "Stroke — deaths/100k (age-adj.)"),
    ("diabetes",  "Diabetes",            "Diabetes — deaths/100k (age-adj.)"),
    ("alzheimer", "Alzheimer's disease", "Alzheimer's — deaths/100k (age-adj.)"),
]


def fetch_nchs():
    """state name -> {cause_key: age-adjusted death rate} for the latest year."""
    names = ",".join("'" + c[1].replace("'", "''") + "'" for c in CAUSES)  # SoQL: escape ' as ''
    r = requests.get("https://data.cdc.gov/resource/bi63-dtpu.json",
                     params={"$where": f"cause_name in({names})", "$limit": "50000"},
                     headers=UA, timeout=90)
    r.raise_for_status()
    rows = r.json()
    year = max(int(d["year"]) for d in rows)
    key_of = {c[1]: c[0] for c in CAUSES}
    out: dict[str, dict] = {}
    for d in rows:
        if int(d["year"]) != year:
            continue
        st = d["state"]
        if st in ("United States",):
            continue
        try:
            out.setdefault(st, {})[key_of[d["cause_name"]]] = round(float(d["aadr"]), 1)
        except (KeyError, ValueError, TypeError):
            pass
    return out, year


def load_states():
    """Simplified national state geometry from the census TIGER cache in MinIO."""
    raw = S3.get_object(Bucket=BUCKET, Key="cache/census-us/output/tiger/state/us_state.geojson")["Body"].read()
    fc = json.loads(raw)
    feats = []
    for f in fc["features"]:
        p = f.get("properties", {})
        name = p.get("NAME") or p.get("name")
        if not name:
            continue
        geom = shape(f["geometry"]).simplify(0.02, preserve_topology=True)
        feats.append({"name": name, "geometry": mapping(geom)})
    return feats


def build():
    data, year = fetch_nchs()
    states = load_states()
    feats = []
    for s in states:
        rec = data.get(s["name"])
        if rec is None:
            continue
        props = {"name": s["name"]}
        for key, _, _ in CAUSES:
            props[f"m_{key}"] = rec.get(key)
        feats.append({"type": "Feature", "geometry": s["geometry"], "properties": props})
    fc = {"type": "FeatureCollection", "features": feats}
    html = render(fc, year)
    key = "cache/health/maps/us-mortality/index.html"
    S3.put_object(Bucket=BUCKET, Key=key, Body=html.encode("utf-8"), ContentType="text/html")
    print(f"states joined: {len(feats)}  year: {year}")
    print(f"uploaded: s3://{BUCKET}/{key}  ({len(html):,} bytes)")


def render(fc: dict, year: int) -> str:
    metrics = [{"key": f"m_{k}", "label": lbl} for k, _, lbl in CAUSES]
    data_js = json.dumps(fc, separators=(",", ":"))
    metrics_js = json.dumps(metrics)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>US disease mortality by state</title><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  html,body,#map{{height:100%;margin:0}}
  .panel{{position:absolute;top:10px;left:10px;z-index:2;background:#fff;padding:12px 14px;border-radius:8px;
    box-shadow:0 1px 6px rgba(0,0,0,.3);font:14px/1.4 system-ui,sans-serif;max-width:330px}}
  .panel h1{{font-size:15px;margin:0 0 6px}} .panel p{{margin:0 0 8px;color:#555;font-size:12px}}
  select{{width:100%;padding:6px;font-size:14px}}
  .legend{{position:absolute;bottom:24px;left:10px;z-index:2;background:#fff;padding:8px 10px;border-radius:8px;
    box-shadow:0 1px 6px rgba(0,0,0,.3);font:12px system-ui,sans-serif}}
  .legend i{{display:inline-block;width:14px;height:14px;margin-right:6px;vertical-align:-2px}}
  .maplibregl-popup-content{{font:13px system-ui,sans-serif}} .maplibregl-popup-content b{{font-size:14px}}
  .attribution{{position:absolute;bottom:0;right:0;z-index:2;background:rgba(255,255,255,.85);
    padding:4px 8px;font:11px system-ui,sans-serif;color:#444;max-width:380px}}
  .attribution a{{color:#1565c0;text-decoration:none}}
</style></head><body>
<div id="map"></div>
<div class="panel"><h1>US disease mortality by state</h1>
  <p>Age-adjusted death rate per 100,000 (CDC NCHS, {year}). Pick a cause:</p>
  <select id="metric"></select></div>
<div class="legend" id="legend"></div>
<div class="attribution">Data: <a href="https://data.cdc.gov/resource/bi63-dtpu">CDC NCHS — Leading Causes of Death</a> ({year}).
  Geometry: US Census TIGER. Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a>;
  see the <a href="https://github.com/rlemke/fwh_health">fwh_health</a> domain.</div>
<script>
const DATA = {data_js}, METRICS = {metrics_js};
const map = new maplibregl.Map({{container:'map',
  style:{{version:8,sources:{{carto:{{type:'raster',
    tiles:['https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{{z}}/{{x}}/{{y}}.png'],tileSize:256,
    attribution:'© OpenStreetMap © CARTO'}}}},layers:[{{id:'bg',type:'raster',source:'carto'}}]}},
  center:[-96,38],zoom:3.4}});
const RAMP=['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4','#2c7fb8','#253494'];
function vals(k){{return DATA.features.map(f=>f.properties[k]).filter(v=>v!=null).sort((a,b)=>a-b);}}
function breaks(k){{const v=vals(k);return [0.1,0.27,0.45,0.63,0.81].map(q=>v[Math.floor(q*v.length)]);}}
function colorExpr(k){{const b=breaks(k);const e=['step',['coalesce',['get',k],-1],'#e0e0e0'];
  e.push(-0.0001,'#e0e0e0'); b.forEach((bk,i)=>e.push(bk,RAMP[i+1])); return e;}}
function legend(k){{const b=breaks(k);let h='<b>'+METRICS.find(m=>m.key===k).label+'</b><br>';
  h+='<div><i style="background:#e0e0e0"></i>no data</div>';
  const lo=[0,...b]; b.concat([Math.max(...vals(k))]).forEach((hi,i)=>{{
    h+='<div><i style="background:'+RAMP[i+1]+'"></i>'+lo[i].toFixed(0)+' – '+hi.toFixed(0)+'</div>';}});
  document.getElementById('legend').innerHTML=h;}}
map.on('load',()=>{{
  map.addSource('s',{{type:'geojson',data:DATA}});
  map.addLayer({{id:'fill',type:'fill',source:'s',paint:{{'fill-color':colorExpr('m_cancer'),'fill-opacity':0.85}}}});
  map.addLayer({{id:'line',type:'line',source:'s',paint:{{'line-color':'#fff','line-width':0.5}}}});
  const sel=document.getElementById('metric');
  METRICS.forEach(m=>{{const o=document.createElement('option');o.value=m.key;o.textContent=m.label;sel.appendChild(o);}});
  function apply(k){{map.setPaintProperty('fill','fill-color',colorExpr(k));legend(k);cur=k;}}
  let cur='m_cancer'; sel.onchange=()=>apply(sel.value); apply('m_cancer');
  map.on('click','fill',e=>{{const p=e.features[0].properties;let h='<b>'+p.name+'</b><br>';
    METRICS.forEach(m=>{{const v=p[m.key];h+=m.label.split(' —')[0]+': '+(v!=null?(+v).toFixed(1):'n/a')+'<br>';}});
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(h).addTo(map);}});
  map.on('mouseenter','fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','fill',()=>map.getCanvas().style.cursor='');
}});
</script></body></html>"""


if __name__ == "__main__":
    build()
