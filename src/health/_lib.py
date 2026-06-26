"""Health-map builders: fetch open public-health data → join geometry → render a
MapLibre choropleth → write HTML to the configured storage backend.

Three maps, each a ``build_*`` function returning ``{html_path, region, ...}``:
US state mortality (CDC NCHS), US county prevalence (CDC PLACES), world NCD
burden (WHO GHO + World Bank). Geometry is reused from the census domain's TIGER
cache (state + per-state county GeoJSON) and Natural Earth (world).
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

import requests
from shapely.geometry import mapping, shape

from . import choropleth, storage

UA = {"User-Agent": "facetwork-health/1.0 (+github.com/rlemke/facetwork)"}
NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
          "geojson/ne_110m_admin_0_countries.geojson")

# 2-digit FIPS for the 50 states + DC + PR (the per-state TIGER county files).
STATE_FIPS = [f"{i:02d}" for i in range(1, 57)] + ["72"]


@dataclass
class MapResult:
    region: str
    html_path: str
    feature_count: int
    detail: str


def _round(o, nd=3):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, (list, tuple)):
        return [_round(x, nd) for x in o]
    return o


# --- US state mortality (CDC NCHS) -----------------------------------------

NCHS_CAUSES = [
    ("cancer",    "Cancer",              "Cancer — deaths/100k (age-adj.)"),
    ("stroke",    "Stroke",              "Stroke — deaths/100k (age-adj.)"),
    ("diabetes",  "Diabetes",            "Diabetes — deaths/100k (age-adj.)"),
    ("alzheimer", "Alzheimer's disease", "Alzheimer's — deaths/100k (age-adj.)"),
]


def _fetch_nchs():
    names = ",".join("'" + c[1].replace("'", "''") + "'" for c in NCHS_CAUSES)
    r = requests.get("https://data.cdc.gov/resource/bi63-dtpu.json",
                     params={"$where": f"cause_name in({names})", "$limit": "50000"},
                     headers=UA, timeout=120)
    r.raise_for_status()
    rows = r.json()
    year = max(int(d["year"]) for d in rows)
    key_of = {c[1]: c[0] for c in NCHS_CAUSES}
    out: dict[str, dict] = {}
    for d in rows:
        if int(d["year"]) != year or d["state"] == "United States":
            continue
        try:
            out.setdefault(d["state"], {})[key_of[d["cause_name"]]] = round(float(d["aadr"]), 1)
        except (KeyError, ValueError, TypeError):
            pass
    return out, year


def build_us_mortality() -> MapResult:
    data, year = _fetch_nchs()
    fc = json.loads(storage.read_bytes(storage.census_geom("output/tiger/state/us_state.geojson")))
    feats = []
    for f in fc["features"]:
        name = (f.get("properties") or {}).get("NAME")
        rec = data.get(name) if name else None
        if rec is None:
            continue
        geom = mapping(shape(f["geometry"]).simplify(0.02, preserve_topology=True))
        geom = {"type": geom["type"], "coordinates": _round(geom["coordinates"])}
        props = {"name": name}
        for k, _, _ in NCHS_CAUSES:
            props[f"m_{k}"] = rec.get(k)
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    metrics = [{"key": f"m_{k}", "label": lbl} for k, _, lbl in NCHS_CAUSES]
    attribution = (f'Data: <a href="https://data.cdc.gov/resource/bi63-dtpu">CDC NCHS — Leading Causes of Death</a> ({year}). '
                   'Geometry: US Census TIGER. Built by an FFL workflow on '
                   '<a href="https://github.com/rlemke/facetwork">Facetwork</a> (<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render({"type": "FeatureCollection", "features": feats}, metrics,
                             title="US disease mortality by state",
                             subtitle=f"Age-adjusted death rate per 100,000 (CDC NCHS, {year}). Pick a cause:",
                             attribution_html=attribution, center=[-96, 38], zoom=3.4)
    path = storage.join(storage.maps_root(), "us-mortality", "index.html")
    storage.write_text(path, html)
    return MapResult("us-mortality", path, len(feats), f"{len(feats)} states, NCHS {year}")


# --- US county prevalence (CDC PLACES) -------------------------------------

PLACES_MEASURES = [
    ("cancer",   "CANCER",   "Cancer (non-skin) — % of adults"),
    ("diabetes", "DIABETES", "Diabetes — % of adults"),
    ("stroke",   "STROKE",   "Stroke — % of adults"),
]


def _fetch_places():
    ids = ",".join(f"'{m[1]}'" for m in PLACES_MEASURES)
    r = requests.get("https://data.cdc.gov/resource/swc5-untb.json",
                     params={"$where": f"measureid in({ids}) and data_value_type='Age-adjusted prevalence'",
                             "$select": "locationid,measureid,data_value", "$limit": "60000"},
                     headers=UA, timeout=120)
    r.raise_for_status()
    key_of = {m[1]: m[0] for m in PLACES_MEASURES}
    out: dict[str, dict] = {}
    for d in r.json():
        fips, dv = d.get("locationid"), d.get("data_value")
        if not fips or dv is None:
            continue
        try:
            out.setdefault(fips, {})[key_of[d["measureid"]]] = round(float(dv), 1)
        except (KeyError, ValueError):
            pass
    return out


def build_us_prevalence() -> MapResult:
    data = _fetch_places()
    feats = []
    for fips in STATE_FIPS:
        p = storage.census_geom(f"output/tiger/county/{fips}_county.geojson")
        if not storage.exists(p):
            continue
        fc = json.loads(storage.read_bytes(p))
        for f in fc["features"]:
            pr = f.get("properties") or {}
            geoid = pr.get("GEOID")
            rec = data.get(geoid) if geoid else None
            if rec is None or not f.get("geometry"):
                continue
            geom = shape(f["geometry"]).simplify(0.02, preserve_topology=True)
            if geom.is_empty:
                continue
            gj = mapping(geom)
            gj = {"type": gj["type"], "coordinates": _round(gj["coordinates"])}
            props = {"name": pr.get("NAMELSAD") or pr.get("NAME"), "fips": geoid}
            for k, _, _ in PLACES_MEASURES:
                props[f"m_{k}"] = rec.get(k)
            feats.append({"type": "Feature", "geometry": gj, "properties": props})
    metrics = [{"key": f"m_{k}", "label": lbl} for k, _, lbl in PLACES_MEASURES]
    attribution = ('Data: <a href="https://data.cdc.gov/resource/swc5-untb">CDC PLACES</a> (age-adjusted adult prevalence). '
                   'Geometry: US Census TIGER. Built by an FFL workflow on '
                   '<a href="https://github.com/rlemke/facetwork">Facetwork</a> (<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render({"type": "FeatureCollection", "features": feats}, metrics,
                             title="US disease prevalence by county",
                             subtitle="Adult prevalence (%), age-adjusted (CDC PLACES). Pick a condition:",
                             attribution_html=attribution, center=[-96, 38], zoom=3.4)
    path = storage.join(storage.maps_root(), "us-prevalence", "index.html")
    storage.write_text(path, html)
    return MapResult("us-prevalence", path, len(feats), f"{len(feats)} counties, CDC PLACES")


# --- World NCD burden (WHO GHO + World Bank) --------------------------------

def _fetch_who(code: str):
    rows = requests.get(f"https://ghoapi.azureedge.net/api/{code}", headers=UA, timeout=60).json()["value"]
    both = [d for d in rows if d.get("Dim1") == "SEX_BTSX"
            and d.get("SpatialDimType") == "COUNTRY" and d.get("NumericValue") is not None]
    yr = max(d["TimeDim"] for d in both)
    return {d["SpatialDim"]: round(float(d["NumericValue"]), 1) for d in both if d["TimeDim"] == yr}, yr


def _fetch_owid_diabetes():
    t = requests.get("https://ourworldindata.org/grapher/diabetes-prevalence.csv",
                     params={"csvType": "full"}, headers=UA, timeout=60).text
    rows = list(csv.DictReader(io.StringIO(t)))
    col = [c for c in rows[0] if "iabetes" in c][0]
    have = [r for r in rows if r.get("Code") and r[col]]
    yr = max(int(r["Year"]) for r in have)
    return {r["Code"]: round(float(r[col]), 1) for r in have if int(r["Year"]) == yr}, yr


def build_world_ncd() -> MapResult:
    diab, dy = _fetch_owid_diabetes()
    prem, py = _fetch_who("NCDMORT3070")
    rate, ry = _fetch_who("WHS2_131")
    gj = requests.get(NE_URL, headers=UA, timeout=60).json()
    feats = []
    for f in gj["features"]:
        p = f["properties"]
        iso = p.get("ISO_A3")
        if not iso or iso == "-99":
            iso = p.get("ISO_A3_EH") or p.get("ADM0_A3")
        geom = shape(f["geometry"]).simplify(0.1, preserve_topology=True)
        if geom.is_empty:
            continue
        g = mapping(geom)
        g = {"type": g["type"], "coordinates": _round(g["coordinates"], 2)}
        feats.append({"type": "Feature", "geometry": g, "properties": {
            "name": p.get("NAME") or p.get("ADMIN"), "iso": iso,
            "m_diabetes": diab.get(iso), "m_ncd_premature": prem.get(iso), "m_ncd_rate": rate.get(iso)}})
    metrics = [
        {"key": "m_diabetes",      "label": f"Diabetes prevalence — % of adults ({dy})"},
        {"key": "m_ncd_premature", "label": f"Premature NCD deaths — % dying age 30–70 ({py})"},
        {"key": "m_ncd_rate",      "label": f"NCD mortality rate — deaths/100k, age-std ({ry})"},
    ]
    attribution = (f'Data: <a href="https://ourworldindata.org/grapher/diabetes-prevalence">OWID / World Bank</a> '
                   f'(diabetes, {dy}) &amp; <a href="https://www.who.int/data/gho">WHO GHO</a> (NCD mortality, {py}). '
                   'Premature NCD = cancer + cardiovascular + diabetes + chronic respiratory. Geometry: Natural Earth. '
                   'Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a> (<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render({"type": "FeatureCollection", "features": feats}, metrics,
                             title="World non-communicable disease burden",
                             subtitle="Diabetes prevalence + NCD mortality (cancer / cardiovascular / diabetes / respiratory). Pick a metric:",
                             attribution_html=attribution, center=[10, 25], zoom=1.4)
    path = storage.join(storage.maps_root(), "world-ncd", "index.html")
    storage.write_text(path, html)
    joined = sum(1 for f in feats if any(f["properties"][k] is not None for k in ("m_diabetes", "m_ncd_premature", "m_ncd_rate")))
    return MapResult("world-ncd", path, joined, f"{joined} countries with data")
