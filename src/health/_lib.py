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

from . import choropleth, choropleth_time, storage

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


# Most recent COMPLETE FluView season (2024-25 is only partially loaded; flu is
# seasonal, so a single current week in summer would be flat "Minimal").
FLU_SEASON = "2023-2024"


def _fetch_flu_us_state():
    """State name -> PEAK CDC FluView ILINet activity level (0-13) reached during
    the most recent complete season — an outpatient influenza-like-illness
    surveillance INTENSITY index (not case counts; flu isn't notifiable by count)."""
    r = requests.get("https://data.cdc.gov/resource/6svj-q4zv.json",
                     params={"$where": f"season='{FLU_SEASON}'",
                             "$select": "state,activity_level", "$limit": "5000"},
                     headers=UA, timeout=90)
    r.raise_for_status()
    peak: dict[str, int] = {}
    for d in r.json():
        lvl = (d.get("activity_level") or "").replace("Level", "").strip()
        if lvl.isdigit():
            st = d["state"]
            peak[st] = max(peak.get(st, 0), int(lvl))
    return peak


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
    flu = _fetch_flu_us_state()      # state name -> peak ILINet activity level (0-13)
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
        props["m_flu"] = flu.get(name)
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    metrics = [{"key": f"m_{k}", "label": lbl} for k, _, lbl in NCHS_CAUSES]
    metrics.append({"key": "m_covid", "label": "COVID-19 — cumulative deaths/100k (2020–23)"})
    fs = FLU_SEASON.replace("20", "", 1).replace("-20", "–")
    metrics.append({"key": "m_flu", "label": f"Flu — peak ILI activity level 0–13 ({fs} season)"})
    attribution = (f'Data: <a href="https://data.cdc.gov/resource/bi63-dtpu">CDC NCHS</a> (chronic, {year}) + '
                   '<a href="https://data.cdc.gov/resource/kn79-hsxy">CDC COVID-19 deaths</a> (cumulative 2020–23) + '
                   f'<a href="https://data.cdc.gov/resource/6svj-q4zv">CDC FluView ILINet</a> (peak activity, {FLU_SEASON}). '
                   'Geometry: US Census TIGER. Built by an FFL workflow on '
                   '<a href="https://github.com/rlemke/facetwork">Facetwork</a> (<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render({"type": "FeatureCollection", "features": feats}, metrics,
                             title="US disease burden by state",
                             subtitle=f"Death rates (NCHS {year} + COVID) + flu activity (FluView). Each metric has its own scale — pick one:",
                             note=(f"Chronic death rates are {year} (NCHS's latest Leading-Causes release); COVID is cumulative 2020–23; "
                                   "flu is the 2023–24 season activity index (a surveillance intensity, not deaths). "
                                   "Alzheimer's has no prevalence estimate anywhere, so it appears only here, on the deaths side."),
                             attribution_html=attribution, center=[-96, 38], zoom=3.4)
    path = storage.join(storage.maps_root(), "us-mortality", "index.html")
    storage.write_text(path, html)
    return MapResult("us-mortality", path, len(feats), f"{len(feats)} states, NCHS {year} + COVID + flu")


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
                             note=("Kentucky &amp; Pennsylvania are blank for all three conditions: CDC PLACES (2025 release) models "
                                   "these from 2023 BRFSS survey data, and KY &amp; PA have no usable 2023 BRFSS sample (they are the only "
                                   "two states with no estimates). Alzheimer's has no prevalence estimate anywhere — see the deaths-by-state map."),
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
                             note=("Per-cause cancer / stroke / Alzheimer's case &amp; death data isn't openly available worldwide, so this shows "
                                   "the non-communicable-disease burden (which spans those) plus COVID/HIV/measles where countries report to WHO. "
                                   "Grey countries have no estimate for the selected metric (HIV and measles are missing for the ~40–90 countries that don't report)."),
                             attribution_html=attribution, center=[10, 25], zoom=1.4)
    path = storage.join(storage.maps_root(), "world-ncd", "index.html")
    storage.write_text(path, html)
    joined = sum(1 for f in feats if any(f["properties"][k] is not None for k in metric_keys))
    return MapResult("world-ncd", path, joined, f"{joined} countries with data")


# --- US respiratory hospital metrics over time (CDC NHSN HRD) ---------------
#
# Weekly Hospital Respiratory Data (HRD) Metrics by Jurisdiction (NHSN), dataset
# mpgq-jmmr. Weekly, state/territory; we keep the 50 states + DC and average each
# selected weekly metric within the calendar month -> one value per (state,
# series, month). The month slider then animates ~5 years. One generic fetch +
# build powers five maps (admissions, bed strain, ICU severity, ped-vs-adult,
# tripledemic) — each just supplies its series→column mapping.

NHSN_HRD = "https://data.cdc.gov/resource/mpgq-jmmr.json"
RESP_MONTHS_BACK = 60  # ~5 years of monthly frames
NHSN_SRC = ('<a href="https://data.cdc.gov/Public-Health-Surveillance/'
            'Weekly-Hospital-Respiratory-Data-HRD-Metrics-by-Ju/mpgq-jmmr">CDC NHSN '
            'Hospital Respiratory Data (HRD)</a>')
# Shared honest-scope tail: NHSN reporting was voluntary before Nov 1 2024, and
# RSV/flu were added after COVID, so earlier months read low.
NHSN_NOTE_TAIL = ("Grey = no reporting that month. Hospital reporting was voluntary before it became "
                  "mandatory on Nov 1 2024 (and RSV/flu were added after COVID), so earlier months have "
                  "thinner coverage. The colour scale is fixed per series across all months, so colours "
                  "are comparable as you slide through time.")


def _fetch_nhsn_series(series_columns: dict[str, list[str]]):
    """Generic monthly NHSN-HRD fetch. ``series_columns`` maps a series key to the
    source column(s) that define it (multiple columns are SUMMED per week — used by
    the 'combined' tripledemic series). Returns (data, months) where
    data[STUSPS][f"{key}_{YYYY-MM}"] = mean of that month's weekly values, over the
    last RESP_MONTHS_BACK complete months (the partial latest month is dropped)."""
    states = ",".join(f"'{s}'" for s in STATE_POP)  # 50 states + DC (USPS abbr)
    cols = sorted({c for cs in series_columns.values() for c in cs})
    r = requests.get(NHSN_HRD, params={
        "$select": "jurisdiction,weekendingdate," + ",".join(cols),
        "$where": f"jurisdiction in({states})",
        "$order": "weekendingdate", "$limit": "100000"}, headers=UA, timeout=180)
    r.raise_for_status()
    acc: dict[str, dict[str, list]] = {}
    all_months: set[str] = set()
    for d in r.json():
        st = d.get("jurisdiction")
        wk = (d.get("weekendingdate") or "")[:10]
        if st not in STATE_POP or len(wk) < 7:
            continue
        month = wk[:7]
        all_months.add(month)
        smonth = acc.setdefault(st, {})
        for key, srccols in series_columns.items():
            parts = []
            for c in srccols:
                try:
                    parts.append(float(d[c]))
                except (KeyError, ValueError, TypeError):
                    pass
            if parts:  # at least one source column reported this week
                smonth.setdefault(f"{key}_{month}", []).append(sum(parts))
    months = sorted(all_months)[:-1] if all_months else []
    months = months[-RESP_MONTHS_BACK:]
    keep = set(months)
    data: dict[str, dict[str, float]] = {}
    for st, cells in acc.items():
        # month is the LAST "_YYYY-MM" segment (series keys may contain '_').
        data[st] = {cell: round(sum(v) / len(v), 2)
                    for cell, v in cells.items() if cell.rsplit("_", 1)[1] in keep and v}
    return data, months


def _nhsn_map(name: str, series_columns: dict[str, list[str]], series_meta: list[dict], *,
              title: str, subtitle: str, value_label: str, note: str, value_decimals: int = 1) -> MapResult:
    """Fetch the given NHSN series, join TIGER state geometry, render a month-slider
    choropleth (choropleth_time) and write it to ``maps_root()/<name>/index.html``."""
    data, months = _fetch_nhsn_series(series_columns)
    fc = json.loads(storage.read_bytes(storage.census_geom("output/tiger/state/us_state.geojson")))
    feats = []
    for f in fc["features"]:
        p = f.get("properties") or {}
        abbr, sname = p.get("STUSPS"), p.get("NAME")
        rec = data.get(abbr)
        if not rec:
            continue
        geom = mapping(shape(f["geometry"]).simplify(0.02, preserve_topology=True))
        geom = {"type": geom["type"], "coordinates": _round(geom["coordinates"])}
        props = {"name": sname}
        for key in series_columns:
            for m in months:
                props[f"{key}_{m}"] = rec.get(f"{key}_{m}")
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    span = f"{months[0]} – {months[-1]}" if months else "n/a"
    attribution = (f'Data: {NHSN_SRC} — weekly metrics averaged by month. Geometry: US Census TIGER. '
                   'Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a> '
                   '(<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth_time.render_timeseries(
        {"type": "FeatureCollection", "features": feats}, series_meta, months,
        title=title, subtitle=subtitle, value_label=value_label, note=note,
        attribution_html=attribution, center=[-96, 38], zoom=3.4, value_decimals=value_decimals)
    path = storage.join(storage.maps_root(), name, "index.html")
    storage.write_text(path, html)
    return MapResult(name, path, len(feats), f"{len(feats)} states × {len(months)} months ({span})")


# 1. New-admission burden per 100k, by virus.
def build_us_respiratory() -> MapResult:
    return _nhsn_map(
        "us-respiratory",
        {"covid": ["totalconfc19newadmper100k"], "flu": ["totalconfflunewadmper100k"],
         "rsv": ["totalconfrsvnewadmper100k"]},
        [{"key": "covid", "label": "COVID-19"}, {"key": "flu", "label": "Influenza"},
         {"key": "rsv", "label": "RSV"}],
        title="US respiratory-virus hospitalization burden",
        subtitle="New hospital admissions per 100k, by virus and month. Pick a virus, drag the slider or press play:",
        value_label="avg weekly new admissions / 100k", value_decimals=2,
        note="Each value is the average of that month's weekly new-admission rates per 100,000 people. " + NHSN_NOTE_TAIL)


# 2. Hospital strain: overall bed occupancy + the share occupied by each virus.
def build_us_hospital_strain() -> MapResult:
    return _nhsn_map(
        "us-hospital-strain",
        {"inpt_occ": ["pctinptbedsocc"], "icu_occ": ["pcticubedsocc"],
         "inpt_covid": ["pctconfc19inptbeds"], "inpt_flu": ["pctconffluinptbeds"],
         "inpt_rsv": ["pctconfrsvinptbeds"]},
        [{"key": "inpt_occ", "label": "All inpatient beds occupied (%)"},
         {"key": "icu_occ", "label": "All ICU beds occupied (%)"},
         {"key": "inpt_covid", "label": "Inpatient beds with COVID-19 (%)"},
         {"key": "inpt_flu", "label": "Inpatient beds with influenza (%)"},
         {"key": "inpt_rsv", "label": "Inpatient beds with RSV (%)"}],
        title="US hospital strain — bed occupancy",
        subtitle="How full are hospitals, and how much of that is respiratory virus? Pick a measure, slide through time:",
        value_label="% of beds", value_decimals=1,
        note=("'All beds occupied' is total inpatient/ICU occupancy (all causes); the per-virus rows are the "
              "share of inpatient beds held by confirmed COVID/flu/RSV patients. " + NHSN_NOTE_TAIL))


# 3. ICU severity: share of each virus's hospitalized patients who are in the ICU.
def build_us_icu_severity() -> MapResult:
    return _nhsn_map(
        "us-icu-severity",
        {"covid": ["pctconfc19hosppatsicu"], "flu": ["pctconffluhosppatsicu"],
         "rsv": ["pctconfrsvhosppatsicu"]},
        [{"key": "covid", "label": "COVID-19 patients in ICU (%)"},
         {"key": "flu", "label": "Influenza patients in ICU (%)"},
         {"key": "rsv", "label": "RSV patients in ICU (%)"}],
        title="US respiratory-virus ICU severity",
        subtitle="Of hospitalized COVID / flu / RSV patients, the share in intensive care. Pick a virus, slide through time:",
        value_label="% of hospitalized patients in ICU", value_decimals=1,
        note=("The fraction of each virus's confirmed inpatients who are in the ICU — a proxy for how severe the "
              "hospitalized cases are. Small-numerator states swing month to month. " + NHSN_NOTE_TAIL))


# 4. Pediatric vs adult admission rates (each per its own age-group population).
def build_us_ped_vs_adult() -> MapResult:
    return _nhsn_map(
        "us-ped-vs-adult",
        {"covid_adult": ["totalconfc19newadmadultper100k"], "covid_ped": ["totalconfc19newadmpedper100k"],
         "flu_adult": ["totalconfflunewadmadultper100k"], "flu_ped": ["totalconfflunewadmpedper100k"],
         "rsv_adult": ["totalconfrsvnewadmadultper100k"], "rsv_ped": ["totalconfrsvnewadmpedper100k"]},
        [{"key": "rsv_ped", "label": "RSV — children / 100k"}, {"key": "rsv_adult", "label": "RSV — adults / 100k"},
         {"key": "flu_ped", "label": "Influenza — children / 100k"}, {"key": "flu_adult", "label": "Influenza — adults / 100k"},
         {"key": "covid_ped", "label": "COVID-19 — children / 100k"}, {"key": "covid_adult", "label": "COVID-19 — adults / 100k"}],
        title="US respiratory admissions — children vs adults",
        subtitle="New admissions per 100k, by virus and age group. RSV & flu hit kids hardest — compare the pairs:",
        value_label="avg weekly new admissions / 100k", value_decimals=2,
        note=("Children's rates are per 100,000 children and adults' per 100,000 adults, so the two are directly "
              "comparable within a virus. RSV in young children is the standout. " + NHSN_NOTE_TAIL))


# 5. "Tripledemic": combined respiratory burden + the three viruses behind it.
def build_us_tripledemic() -> MapResult:
    return _nhsn_map(
        "us-tripledemic",
        {"combined": ["totalconfc19newadmper100k", "totalconfflunewadmper100k", "totalconfrsvnewadmper100k"],
         "covid": ["totalconfc19newadmper100k"], "flu": ["totalconfflunewadmper100k"],
         "rsv": ["totalconfrsvnewadmper100k"]},
        [{"key": "combined", "label": "All three viruses combined / 100k"},
         {"key": "covid", "label": "COVID-19 / 100k"}, {"key": "flu", "label": "Influenza / 100k"},
         {"key": "rsv", "label": "RSV / 100k"}],
        title="US 'tripledemic' — combined respiratory burden",
        subtitle="COVID + flu + RSV admissions per 100k, combined and split out. Press play to compare winter over winter:",
        value_label="avg weekly new admissions / 100k", value_decimals=2,
        note=("'Combined' sums the per-100k admission rates of whichever of the three viruses reported that month, so "
              "before flu/RSV reporting began it tracks COVID alone. Winter peaks (the 'tripledemic') stack up from "
              "2023-24 on. " + NHSN_NOTE_TAIL))
