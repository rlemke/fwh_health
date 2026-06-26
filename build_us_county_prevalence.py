"""US county choropleth of adult prevalence for cancer / diabetes / stroke
(CDC PLACES, age-adjusted), rendered with a metric dropdown to MinIO.

PLACES gives county-level *prevalence* (% of adults) — the "cases" measure the
NCHS mortality map can't do at county level. Alzheimer's has no prevalence
estimate anywhere, so it's deaths-only (the state map). Geometry is the
census-domain TIGER county GeoJSON cached in MinIO, merged + simplified.
"""
from __future__ import annotations
import json
import boto3, requests
from shapely.geometry import shape, mapping
import choropleth

S3 = boto3.client("s3", endpoint_url="http://192.168.68.96:9000",
                  aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")
BUCKET = "afl-cache"
UA = {"User-Agent": "facetwork-health/1.0 (+github.com/rlemke/facetwork)"}

MEASURES = [
    ("cancer",   "CANCER",   "Cancer (non-skin) — % of adults"),
    ("diabetes", "DIABETES", "Diabetes — % of adults"),
    ("stroke",   "STROKE",   "Stroke — % of adults"),
]


def fetch_places():
    """county FIPS -> {metric_key: age-adjusted prevalence %}."""
    ids = ",".join(f"'{m[1]}'" for m in MEASURES)
    r = requests.get("https://data.cdc.gov/resource/swc5-untb.json",
                     params={"$where": f"measureid in({ids}) and data_value_type='Age-adjusted prevalence'",
                             "$select": "locationid,measureid,data_value", "$limit": "60000"},
                     headers=UA, timeout=120)
    r.raise_for_status()
    key_of = {m[1]: m[0] for m in MEASURES}
    out: dict[str, dict] = {}
    for d in r.json():
        fips = d.get("locationid"); dv = d.get("data_value")
        if not fips or dv is None:
            continue
        try:
            out.setdefault(fips, {})[key_of[d["measureid"]]] = round(float(dv), 1)
        except (KeyError, ValueError):
            pass
    return out


def _round(obj, nd=3):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, list):
        return [_round(x, nd) for x in obj]
    return obj


def load_counties():
    """Merge every per-state TIGER county GeoJSON in MinIO → [(geoid, name, geom)]."""
    keys = []
    for pg in S3.get_paginator("list_objects_v2").paginate(
            Bucket=BUCKET, Prefix="cache/census-us/output/tiger/county/"):
        for o in pg.get("Contents", []):
            if o["Key"].endswith("_county.geojson"):
                keys.append(o["Key"])
    out = []
    for k in sorted(keys):
        fc = json.loads(S3.get_object(Bucket=BUCKET, Key=k)["Body"].read())
        for f in fc["features"]:
            p = f.get("properties", {})
            geoid = p.get("GEOID")
            name = p.get("NAMELSAD") or p.get("NAME")
            if not geoid or not f.get("geometry"):
                continue
            geom = shape(f["geometry"]).simplify(0.02, preserve_topology=True)
            if geom.is_empty:
                continue
            gj = mapping(geom)
            gj = {"type": gj["type"], "coordinates": _round(gj["coordinates"])}
            out.append((geoid, name, gj))
    return out


def build():
    data = fetch_places()
    counties = load_counties()
    feats = []
    for geoid, name, geom in counties:
        rec = data.get(geoid)
        if rec is None:
            continue
        props = {"name": f"{name}", "fips": geoid}
        for key, _, _ in MEASURES:
            props[f"m_{key}"] = rec.get(key)
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    fc = {"type": "FeatureCollection", "features": feats}
    metrics = [{"key": f"m_{k}", "label": lbl} for k, _, lbl in MEASURES]
    attribution = ('Data: <a href="https://data.cdc.gov/resource/swc5-untb">CDC PLACES</a> '
                   '(age-adjusted adult prevalence). Geometry: US Census TIGER. '
                   'Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a> '
                   '(<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render(fc, metrics,
                             title="US disease prevalence by county",
                             subtitle="Adult prevalence (%), age-adjusted (CDC PLACES). Pick a condition:",
                             attribution_html=attribution, center=[-96, 38], zoom=3.4)
    key = "cache/health/maps/us-prevalence/index.html"
    S3.put_object(Bucket=BUCKET, Key=key, Body=html.encode("utf-8"), ContentType="text/html")
    print(f"counties joined: {len(feats)} / {len(counties)} geom, {len(data)} with PLACES data")
    print(f"uploaded: s3://{BUCKET}/{key}  ({len(html):,} bytes / {len(html)/1e6:.1f} MB)")


if __name__ == "__main__":
    build()
