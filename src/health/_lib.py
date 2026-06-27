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


# 2020 Census resident population by USPS state abbr — to turn cumulative COVID
# death COUNTS (CDC, by county) into a comparable per-100k rate.
STATE_POP = {
    "AL": 5024279, "AK": 733391, "AZ": 7151502, "AR": 3011524, "CA": 39538223,
    "CO": 5773714, "CT": 3605944, "DE": 989948, "DC": 689545, "FL": 21538187,
    "GA": 10711908, "HI": 1455271, "ID": 1839106, "IL": 12812508, "IN": 6785528,
    "IA": 3190369, "KS": 2937880, "KY": 4505836, "LA": 4657757, "ME": 1362359,
    "MD": 6177224, "MA": 7029917, "MI": 10077331, "MN": 5706494, "MS": 2961279,
    "MO": 6154913, "MT": 1084225, "NE": 1961504, "NV": 3104614, "NH": 1377529,
    "NJ": 9288994, "NM": 2117522, "NY": 20201249, "NC": 10439388, "ND": 779094,
    "OH": 11799448, "OK": 3959353, "OR": 4237256, "PA": 13002700, "RI": 1097379,
    "SC": 5118425, "SD": 886667, "TN": 6910840, "TX": 29145505, "UT": 3271616,
    "VT": 643077, "VA": 8631393, "WA": 7705281, "WV": 1793716, "WI": 5893718, "WY": 576851,
}


def _fetch_covid_us_state():
    """USPS state abbr -> cumulative COVID-19 deaths per 100k (CDC provisional
    county death counts, Jan 2020-Jun 2023, aggregated to state)."""
    r = requests.get("https://data.cdc.gov/resource/kn79-hsxy.json",
                     params={"$select": "state_name,total_death", "$limit": "60000"},
                     headers=UA, timeout=120)
    r.raise_for_status()
    deaths: dict[str, int] = {}
    for d in r.json():
        st = d.get("state_name")
        try:
            deaths[st] = deaths.get(st, 0) + int(float(d.get("total_death") or 0))
        except (ValueError, TypeError):
            pass
    return {st: round(n / STATE_POP[st] * 100000, 1) for st, n in deaths.items() if st in STATE_POP}


def _fetch_who_covid_world():
    """ISO-2 country code -> cumulative COVID-19 deaths (latest, WHO global data)."""
    url = ("https://srhdpeuwpubsa.blob.core.windows.net/whdh/COVID/"
           "WHO-COVID-19-global-data.csv")
    text = requests.get(url, headers=UA, timeout=120).text
    rows = csv.DictReader(io.StringIO(text))
    out: dict[str, int] = {}
    for d in rows:  # chronological; cumulative is monotonic -> last seen = latest
        cc = d.get("Country_code")
        cd = d.get("Cumulative_deaths")
        if cc and cd:
            try:
                out[cc] = int(float(cd))
            except ValueError:
                pass
    return out


def build_us_mortality() -> MapResult:
    data, year = _fetch_nchs()
    covid = _fetch_covid_us_state()  # USPS abbr -> cumulative COVID deaths / 100k
    fc = json.loads(storage.read_bytes(storage.census_geom("output/tiger/state/us_state.geojson")))
    feats = []
    for f in fc["features"]:
        p = f.get("properties") or {}
        name, abbr = p.get("NAME"), p.get("STUSPS")
        rec = data.get(name) if name else None
        if rec is None:
            continue
        geom = mapping(shape(f["geometry"]).simplify(0.02, preserve_topology=True))
        geom = {"type": geom["type"], "coordinates": _round(geom["coordinates"])}
        props = {"name": name}
        for k, _, _ in NCHS_CAUSES:
            props[f"m_{k}"] = rec.get(k)
        props["m_covid"] = covid.get(abbr)
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    metrics = [{"key": f"m_{k}", "label": lbl} for k, _, lbl in NCHS_CAUSES]
    metrics.append({"key": "m_covid", "label": "COVID-19 — cumulative deaths/100k (2020–23)"})
    attribution = (f'Data: <a href="https://data.cdc.gov/resource/bi63-dtpu">CDC NCHS</a> (chronic, {year}) + '
                   '<a href="https://data.cdc.gov/resource/kn79-hsxy">CDC provisional COVID-19 deaths</a> (cumulative 2020–23). '
                   'Geometry: US Census TIGER. Built by an FFL workflow on '
                   '<a href="https://github.com/rlemke/facetwork">Facetwork</a> (<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render({"type": "FeatureCollection", "features": feats}, metrics,
                             title="US disease mortality by state",
                             subtitle=f"Death rate per 100,000 — chronic age-adjusted (NCHS, {year}) + COVID-19 cumulative. Pick a cause:",
                             attribution_html=attribution, center=[-96, 38], zoom=3.4)
    path = storage.join(storage.maps_root(), "us-mortality", "index.html")
    storage.write_text(path, html)
    return MapResult("us-mortality", path, len(feats), f"{len(feats)} states, NCHS {year} + COVID")


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
    """ISO3 -> value for the latest year. Prefers both-sex rows; falls back to
    no-sex-dimension indicators (e.g. HIV/measles carry Dim1=None)."""
    rows = requests.get(f"https://ghoapi.azureedge.net/api/{code}", headers=UA, timeout=60).json()["value"]
    cty = [d for d in rows if d.get("SpatialDimType") == "COUNTRY" and d.get("NumericValue") is not None]
    use = [d for d in cty if d.get("Dim1") == "SEX_BTSX"] \
        or [d for d in cty if d.get("Dim1") in (None, "")] \
        or cty
    yr = max(d["TimeDim"] for d in use)
    return {d["SpatialDim"]: round(float(d["NumericValue"]), 1) for d in use if d["TimeDim"] == yr}, yr


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
    hiv, hy = _fetch_who("MDG_0000000029")     # HIV prevalence, adults 15-49 (%)
    measles, my = _fetch_who("WHS3_62")        # measles — reported cases
    covid2 = _fetch_who_covid_world()          # ISO-2 -> cumulative COVID deaths
    gj = requests.get(NE_URL, headers=UA, timeout=60).json()
    metric_keys = ("m_diabetes", "m_ncd_premature", "m_ncd_rate", "m_covid", "m_hiv", "m_measles")
    feats = []
    for f in gj["features"]:
        p = f["properties"]
        iso = p.get("ISO_A3")
        if not iso or iso == "-99":
            iso = p.get("ISO_A3_EH") or p.get("ADM0_A3")
        iso2 = p.get("ISO_A2") if p.get("ISO_A2") not in (None, "-99") else p.get("ISO_A2_EH")
        pop = p.get("POP_EST") or 0
        cdeaths = covid2.get(iso2)
        covid_rate = round(cdeaths / pop * 100000, 1) if (cdeaths and pop) else None
        geom = shape(f["geometry"]).simplify(0.1, preserve_topology=True)
        if geom.is_empty:
            continue
        g = mapping(geom)
        g = {"type": g["type"], "coordinates": _round(g["coordinates"], 2)}
        feats.append({"type": "Feature", "geometry": g, "properties": {
            "name": p.get("NAME") or p.get("ADMIN"), "iso": iso,
            "m_diabetes": diab.get(iso), "m_ncd_premature": prem.get(iso), "m_ncd_rate": rate.get(iso),
            "m_covid": covid_rate, "m_hiv": hiv.get(iso), "m_measles": measles.get(iso)}})
    metrics = [
        {"key": "m_diabetes",      "label": f"Diabetes prevalence — % of adults ({dy})"},
        {"key": "m_ncd_premature", "label": f"Premature NCD deaths — % dying age 30–70 ({py})"},
        {"key": "m_ncd_rate",      "label": f"NCD mortality rate — deaths/100k, age-std ({ry})"},
        {"key": "m_covid",         "label": "COVID-19 — cumulative deaths/100k (WHO)"},
        {"key": "m_hiv",           "label": f"HIV prevalence — % of adults 15–49 ({hy})"},
        {"key": "m_measles",       "label": f"Measles — reported cases ({my})"},
    ]
    attribution = (f'Data: <a href="https://ourworldindata.org/grapher/diabetes-prevalence">OWID / World Bank</a> (diabetes, {dy}) &amp; '
                   f'<a href="https://www.who.int/data/gho">WHO GHO</a> (NCD {py}, HIV {hy}, measles {my}) &amp; '
                   '<a href="https://data.who.int/dashboards/covid19">WHO COVID-19</a> (cumulative deaths). '
                   'Premature NCD = cancer + cardiovascular + diabetes + chronic respiratory. Geometry: Natural Earth. '
                   'Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a> (<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render({"type": "FeatureCollection", "features": feats}, metrics,
                             title="World disease burden by country",
                             subtitle="Chronic (diabetes / NCD mortality) + infectious (COVID-19 / HIV / measles). Pick a metric:",
                             attribution_html=attribution, center=[10, 25], zoom=1.4)
    path = storage.join(storage.maps_root(), "world-ncd", "index.html")
    storage.write_text(path, html)
    joined = sum(1 for f in feats if any(f["properties"][k] is not None for k in metric_keys))
    return MapResult("world-ncd", path, joined, f"{joined} countries with data")
