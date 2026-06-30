"""Health-map builders: fetch open public-health data → join geometry → render a
MapLibre choropleth → write HTML to the configured storage backend.

Each map is a ``build_*`` function returning ``{html_path, region, ...}``. Two
families: static-choropleth maps (``choropleth.py``, metric dropdown) — US state
mortality (CDC NCHS), US county prevalence (CDC PLACES), world NCD burden (WHO /
World Bank) — and a five-map NHSN respiratory family (``choropleth_time.py``,
series dropdown + month slider) built off the generic ``_fetch_nhsn_series`` /
``_nhsn_map`` over CDC Hospital Respiratory Data: admissions, bed strain, ICU
severity, children-vs-adults, and the "tripledemic" combined burden. Geometry is
reused from the census domain's TIGER cache (state + per-state county GeoJSON)
and Natural Earth (world).
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


# --- World HIV/AIDS over time: by sex + key population ----------------------
#
# Two openly-fetchable, per-country, over-time dimensions on one map (category
# dropdown + year slider):
#   * New HIV infections by SEX (all / women / men) — WHO GHO SDGHIV, a rate per
#     1,000 uninfected, 1990-2024, reported every year. This is the men-vs-women
#     cut and the "is it rising or falling?" trend.
#   * HIV prevalence AMONG key populations (gay men & other MSM, sex workers,
#     people who inject drugs, transgender people) — UNAIDS Key Populations
#     Atlas, a percentage, reported only in the survey years a country ran
#     (sparse). This is the closest open per-country proxy for the gay / sex-work
#     / drug-use dimension.
# A true per-country "gay vs straight vs bisexual" split of new infections does
# NOT exist as an open world dataset (UNAIDS publishes it only globally/region-
# ally), so the map says so in its note rather than fabricating it.

HIV_YEAR_FROM = 2000
# UNAIDS' Azure gateway 403s non-browser User-Agents — this download needs one.
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
KP_ATLAS_URL = "https://aidsinfo.unaids.org/public/documents/KPAtlasDB_2025_en.zip"
_HIV_SEX = {"SEX_BTSX": "inf_total", "SEX_FMLE": "inf_women", "SEX_MLE": "inf_men"}
_HIV_KP = {
    "HIV prevalence among men who have sex with men": "prev_msm",
    "HIV prevalence among sex workers":               "prev_sw",
    "HIV prevalence among people who inject drugs":    "prev_pwid",
    "HIV prevalence among transgender people":         "prev_trans",
}


def _fetch_sdghiv():
    """ISO3 -> {series_key: {year: rate}} — new HIV infections per 1,000
    uninfected, split by sex (all/women/men), from WHO GHO SDGHIV."""
    rows = requests.get("https://ghoapi.azureedge.net/api/SDGHIV",
                        headers=UA, timeout=120).json()["value"]
    out: dict[str, dict[str, dict[str, float]]] = {}
    for d in rows:
        if d.get("SpatialDimType") != "COUNTRY" or d.get("NumericValue") is None:
            continue
        key = _HIV_SEX.get(d.get("Dim1"))
        yr = d.get("TimeDim")
        if not key or yr is None or yr < HIV_YEAR_FROM:
            continue
        out.setdefault(d["SpatialDim"], {}).setdefault(key, {})[str(yr)] = \
            round(float(d["NumericValue"]), 2)
    return out


def _fetch_kp_atlas():
    """ISO3 -> {series_key: {year: prevalence%}} — HIV prevalence among key
    populations (MSM, sex workers, PWID, transgender) from the UNAIDS Key
    Populations Atlas bulk CSV. National rows (Area Level 2), 'Total' subgroup."""
    import zipfile
    blob = requests.get(KP_ATLAS_URL, headers=BROWSER_UA, timeout=120).content
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        text = z.read(name).decode("utf-8-sig")
    out: dict[str, dict[str, dict[str, float]]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        key = _HIV_KP.get(r.get("Indicator", ""))
        if not key or r.get("Area Level") != "2" or r.get("Subgroup") != "Total":
            continue
        iso = r.get("Area ID") or ""
        yr = (r.get("Time Period") or "").strip()
        val = (r.get("Data value") or "").strip()
        if len(iso) != 3 or not yr.isdigit() or int(yr) < HIV_YEAR_FROM or not val:
            continue
        try:
            out.setdefault(iso, {}).setdefault(key, {})[yr] = round(float(val), 2)
        except ValueError:
            continue
    return out


def build_world_hiv() -> MapResult:
    sex = _fetch_sdghiv()
    kp = _fetch_kp_atlas()
    gj = requests.get(NE_URL, headers=UA, timeout=60).json()
    years = [str(y) for y in range(HIV_YEAR_FROM, 2025)]
    rate_unit = "new infections / 1,000 uninfected (rate)"
    prev_unit = "% of that group living with HIV"
    series = [
        {"key": "inf_total", "label": "New HIV infections — all",   "unit": rate_unit},
        {"key": "inf_women", "label": "New HIV infections — women", "unit": rate_unit},
        {"key": "inf_men",   "label": "New HIV infections — men",   "unit": rate_unit},
        {"key": "prev_msm",  "label": "HIV prevalence — gay men & other men who have sex with men", "unit": prev_unit},
        {"key": "prev_sw",   "label": "HIV prevalence — sex workers",             "unit": prev_unit},
        {"key": "prev_pwid", "label": "HIV prevalence — people who inject drugs", "unit": prev_unit},
        {"key": "prev_trans","label": "HIV prevalence — transgender people",      "unit": prev_unit},
    ]
    all_keys = [s["key"] for s in series]
    feats, joined = [], 0
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
        props = {"name": p.get("NAME") or p.get("ADMIN"), "iso": iso}
        rec_sex, rec_kp = sex.get(iso, {}), kp.get(iso, {})
        has = False
        for key in all_keys:
            src = rec_sex.get(key) or rec_kp.get(key) or {}
            for y in years:
                if y in src:
                    props[f"{key}_{y}"] = src[y]
                    has = True
        joined += 1 if has else 0
        feats.append({"type": "Feature", "geometry": g, "properties": props})
    attribution = (
        'Data: <a href="https://www.who.int/data/gho">WHO GHO</a> SDGHIV — new HIV infections / 1,000 '
        'uninfected, by sex (UNAIDS estimates, 1990–2024) &amp; <a href="https://kpatlas.unaids.org">UNAIDS '
        'Key Populations Atlas</a> — HIV prevalence among key populations (survey years). Geometry: Natural '
        'Earth. Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a> '
        '(<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    note = (
        "Two measures share this map — each dropdown item has its own colour scale and unit. The "
        "<b>all / women / men</b> series are the <b>new-infection rate</b> per 1,000 uninfected people, "
        "reported every year, so you can watch the epidemic rise and fall and compare the sexes. The "
        "key-population series are <b>HIV prevalence</b> — the share of gay men &amp; other MSM, sex workers, "
        "people who inject drugs, and transgender people already living with HIV — reported only in the survey "
        "years a country ran, so many country-years are grey. A true per-country &lsquo;gay vs straight vs "
        "bisexual&rsquo; split of new infections is <b>not</b> openly published worldwide (UNAIDS reports it "
        "only at global / regional level), so it is left out here rather than faked.")
    html = choropleth_time.render_timeseries(
        {"type": "FeatureCollection", "features": feats}, series, years,
        title="World HIV/AIDS — by sex and key population, over time",
        subtitle="New-infection rate (women / men / all) and HIV prevalence among key populations. Pick a category, drag the year slider or press play:",
        value_label="value", value_decimals=2,
        attribution_html=attribution, note=note, note_popup=True, center=[10, 25], zoom=1.4)
    path = storage.join(storage.maps_root(), "world-hiv", "index.html")
    storage.write_text(path, html)
    return MapResult("world-hiv", path, joined,
                     f"{joined} countries with HIV data ({years[0]}–{years[-1]})")


# --- Europe HIV new diagnoses by transmission route (ECDC Atlas) ------------
#
# Where the world map can't show a per-country gay/straight split, Europe can:
# the ECDC Surveillance Atlas (TESSy, healthtopicId 75 / datasetId 2048) reports
# confirmed NEW HIV diagnoses split by route of transmission, per EU/EEA country
# per year. We pull the COUNT ("Reported cases") for each route so the dropdown
# is the route and the slider is the year. Measure ids are resolved by their
# population label at run time (robust to dataset-version id drift). ECDC keys by
# ISO-2 with two quirks vs Natural Earth: UK->GB, EL->GR.

ECDC_BASE = "https://atlas.ecdc.europa.eu/public/AtlasService/rest"
ECDC_TO_NE = {"UK": "GB", "EL": "GR"}
EU_EEA = ("AT BE BG HR CY CZ DK EE FI FR DE EL HU IS IE IT LV LT LU MT NL NO "
          "PL PT RO SK SI ES SE UK LI").split()
# (series_key, dropdown label, ECDC population label)
EU_HIV_POPS = [
    ("tx_total",   "All new HIV diagnoses",                "HIV infection|Confirmed cases"),
    ("tx_msm",     "Sex between men (gay & other MSM)",     "HIV infection|Confirmed cases - Sex between men"),
    ("tx_hetero",  "Heterosexual contact",                 "HIV infection|Confirmed cases - By Heterosexual transmission"),
    ("tx_idu",     "Injecting drug use",                   "HIV infection|Confirmed cases - Injecting drug-use-related transmission"),
    ("tx_mtct",    "Mother-to-child",                      "HIV infection|Confirmed cases - By Mother to Child Transmission"),
    ("tx_unknown", "Unknown / not reported",               "HIV infection|Confirmed cases - By Unknown Transmission"),
]


def _ecdc_get(path: str, **params):
    r = requests.get(f"{ECDC_BASE}/{path}", params=params, headers=BROWSER_UA, timeout=60)
    r.raise_for_status()
    return r.json()


def _ecdc_count_measure_id(pop_label: str):
    """Resolve a population label to its 'Reported cases' (count) measure id."""
    d = _ecdc_get("GetIndicatorMeasuresForHealthTopicDatasetAndPopulation",
                  datasetId=2048, healthtopicId=75, measurePopulation=pop_label)
    counts = [m for m in (d.get("Measures") or []) if m.get("Unit") == "N" and m.get("Id")]
    return counts[0]["Id"] if counts else None


def _fetch_ecdc_hiv_transmission():
    """NE-ISO2 -> {series_key: {year: count}} — confirmed new HIV diagnoses by
    transmission route across EU/EEA, from the ECDC Surveillance Atlas REST API."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for key, _label, pop in EU_HIV_POPS:
        mid = _ecdc_count_measure_id(pop)
        if not mid:
            continue
        for c in EU_EEA:
            d = _ecdc_get("GetMeasureResultsForTimeUnitAndGeoRegion",
                          measureId=mid, timeUnit="Y", geoCode=c)
            ne = ECDC_TO_NE.get(c, c)
            for r in d.get("MeasureResults") or []:
                if r.get("YValue") is None:
                    continue
                yr = str(r.get("TimeCode") or "")
                if not yr.isdigit() or int(yr) < HIV_YEAR_FROM:
                    continue
                out.setdefault(ne, {}).setdefault(key, {})[yr] = int(round(float(r["YValue"])))
    return out


def build_europe_hiv_transmission() -> MapResult:
    data = _fetch_ecdc_hiv_transmission()
    gj = requests.get(NE_URL, headers=UA, timeout=60).json()
    years = [str(y) for y in range(HIV_YEAR_FROM, 2025)]
    series = [{"key": k, "label": l, "unit": "new HIV diagnoses (reported cases)"}
              for k, l, _ in EU_HIV_POPS]
    keys = [s["key"] for s in series]
    feats, joined = [], 0
    for f in gj["features"]:
        p = f["properties"]
        iso2 = p.get("ISO_A2")
        if iso2 in (None, "-99"):
            iso2 = p.get("ISO_A2_EH")
        rec = data.get(iso2)
        if not rec:                       # only EU/EEA reporting countries
            continue
        geom = shape(f["geometry"]).simplify(0.05, preserve_topology=True)
        if geom.is_empty:
            continue
        g = mapping(geom)
        g = {"type": g["type"], "coordinates": _round(g["coordinates"], 2)}
        props = {"name": p.get("NAME") or p.get("ADMIN"), "iso": iso2}
        has = False
        for key in keys:
            src = rec.get(key) or {}
            for y in years:
                if y in src:
                    props[f"{key}_{y}"] = src[y]
                    has = True
        joined += 1 if has else 0
        feats.append({"type": "Feature", "geometry": g, "properties": props})
    attribution = (
        'Data: <a href="https://atlas.ecdc.europa.eu/public/index.aspx">ECDC Surveillance Atlas of '
        'Infectious Diseases</a> (ECDC/WHO Europe TESSy) — confirmed new HIV diagnoses by transmission '
        'route, EU/EEA. Geometry: Natural Earth. Built by an FFL workflow on '
        '<a href="https://github.com/rlemke/facetwork">Facetwork</a> '
        '(<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    note = (
        "This is the <b>gay-vs-straight</b> view the world map couldn&rsquo;t show: in Europe, ECDC records "
        "how each new HIV diagnosis was acquired. Each value is the <b>number of confirmed new HIV "
        "diagnoses</b> a country reported that year for the selected route: <b>sex between men</b> (gay &amp; "
        "other men who have sex with men — bisexual men are counted here too), <b>heterosexual contact</b>, "
        "<b>injecting drug use</b>, <b>mother-to-child</b>, and <b>unknown / not reported</b> (a large share "
        "in several countries, because the route often isn&rsquo;t ascertained). These are <b>counts, not "
        "rates</b>, so more populous countries naturally show bigger numbers, and earlier years / some "
        "countries report less completely. Scope: EU/EEA reporting countries. Each route has its own colour "
        "scale; pick one from the dropdown and drag the year slider or press play.")
    html = choropleth_time.render_timeseries(
        {"type": "FeatureCollection", "features": feats}, series, years,
        title="Europe — new HIV diagnoses by transmission route, over time",
        subtitle="EU/EEA confirmed new HIV diagnoses by how they were acquired (gay / straight / drug use / …). Pick a route, drag the year slider or press play:",
        value_label="new HIV diagnoses (cases)", value_decimals=0,
        attribution_html=attribution, note=note, note_popup=True, center=[12, 54], zoom=3.0)
    path = storage.join(storage.maps_root(), "europe-hiv-transmission", "index.html")
    storage.write_text(path, html)
    return MapResult("europe-hiv-transmission", path, joined,
                     f"{joined} EU/EEA countries ({years[0]}–{years[-1]})")


# --- US HIV new diagnoses by transmission category (CDC AtlasPlus) ----------
#
# The US counterpart to the Europe transmission map. CDC NCHHSTP AtlasPlus drives
# its public tool from an undocumented JSON backend:
#   * GET  .../AtlasPlus/getInitData/00  -> id catalog (varvals): every selectable
#     id with its dimension type (vtid). We read it to resolve state ids (vtid 3,
#     geoLevel 1002, with a 2-digit fips) and year ids (vtid 2) at run time.
#   * POST .../AtlasPlus/qtOutputData {"VariableIDs": "<comma-joined ids>"} ->
#     sourcedata rows. The backend groups ids by dimension, so ONE post with all
#     state ids + all year ids + one transmission id returns every state x year
#     for that category (6 posts total). Row = [indicator, yearId, geoId, _, race,
#     sex, age, txId, rate, cases, ...]; the transmission breakdown has no rate
#     (col 8 null) — values are CASES (col 9). Suppressed cells come back null.
# Source is undocumented/unsupported (CDC may change it without notice); AIDSVu's
# per-year state xlsx is the documented fallback if this breaks.

ATLASPLUS = "https://gis.cdc.gov/grasp/AtlasPlus"
ATLAS_HDRS = {**BROWSER_UA, "Content-Type": "application/json; charset=UTF-8",
              "X-Requested-With": "XMLHttpRequest",
              "Referer": "https://gis.cdc.gov/grasp/nchhstpatlas/tables.html"}
US_HIV_YEAR_FROM = 2008
# (series_key, dropdown label, AtlasPlus transmission-category id)
US_HIV_TX = [
    ("tx_all",     "All transmission categories",                      801),
    ("tx_msm",     "Male-to-male sexual contact (gay & other MSM)",    802),
    ("tx_hetero",  "Heterosexual contact",                             805),
    ("tx_idu",     "Injection drug use",                               803),
    ("tx_msmidu",  "Male-to-male sexual contact & injection drug use", 804),
    ("tx_other",   "Other",                                            806),
]


def _fetch_atlasplus_hiv_transmission():
    """state-FIPS -> {series_key: {year: cases}} — US HIV new diagnoses by
    transmission category, from the CDC AtlasPlus JSON backend."""
    init = requests.get(f"{ATLASPLUS}/getInitData/00", headers=BROWSER_UA, timeout=120).json()
    vv = init["varvals"]
    states = [v for v in vv if v.get("vtid") == 3 and v.get("geoLevel") == 1002 and v.get("fips")]
    gid_fips = {s["id"]: s["fips"] for s in states}
    years = {str(v["name"]): v["id"] for v in vv if v.get("vtid") == 2}
    yid_year = {v["id"]: str(v["name"]) for v in vv if v.get("vtid") == 2}
    ywanted = [y for y in (str(x) for x in range(US_HIV_YEAR_FROM, 2025)) if y in years]
    sids = [str(s["id"]) for s in states]
    yids = [str(years[y]) for y in ywanted]
    out: dict[str, dict[str, dict[str, int]]] = {}
    for key, _label, tx in US_HIV_TX:
        vids = ",".join(["203"] + sids + yids + ["650", "551", "601", str(tx)])
        body = json.dumps({"VariableIDs": vids})
        rows = requests.post(f"{ATLASPLUS}/qtOutputData", data=body,
                             headers=ATLAS_HDRS, timeout=120).json().get("sourcedata") or []
        for r in rows:
            cases = r[9]
            if cases is None:
                continue
            fips, yr = gid_fips.get(r[2]), yid_year.get(r[1])
            if not fips or not yr:
                continue
            out.setdefault(fips, {}).setdefault(key, {})[yr] = int(cases)
    return out


def build_us_hiv_transmission() -> MapResult:
    data = _fetch_atlasplus_hiv_transmission()
    fc = json.loads(storage.read_bytes(storage.census_geom("output/tiger/state/us_state.geojson")))
    years = sorted({y for st in data.values() for ser in st.values() for y in ser})
    series = [{"key": k, "label": l, "unit": "new HIV diagnoses (cases, ages 13+)"}
              for k, l, _ in US_HIV_TX]
    keys = [s["key"] for s in series]
    feats, joined = [], 0
    for f in fc["features"]:
        p = f.get("properties") or {}
        rec = data.get(p.get("STATEFP"))
        if not rec:
            continue
        geom = mapping(shape(f["geometry"]).simplify(0.02, preserve_topology=True))
        geom = {"type": geom["type"], "coordinates": _round(geom["coordinates"])}
        props = {"name": p.get("NAME")}
        has = False
        for key in keys:
            src = rec.get(key) or {}
            for y in years:
                if y in src:
                    props[f"{key}_{y}"] = src[y]
                    has = True
        joined += 1 if has else 0
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    attribution = (
        'Data: <a href="https://gis.cdc.gov/grasp/nchhstpatlas/">CDC NCHHSTP AtlasPlus</a> — new HIV '
        'diagnoses (ages 13+) by transmission category, US states. Geometry: US Census TIGER. '
        'Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a> '
        '(<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    note = (
        "The US counterpart to the Europe map: CDC AtlasPlus records how each new HIV diagnosis (ages 13+) "
        "was acquired. Each value is the <b>number of new diagnoses</b> a state reported that year for the "
        "selected route: <b>male-to-male sexual contact</b> (gay &amp; other men who have sex with men, "
        "defined by sex assigned at birth — bisexual men are counted here too), <b>heterosexual contact</b>, "
        "<b>injection drug use</b>, <b>MSM &amp; injection drug use</b>, and <b>Other</b> (which folds in "
        "perinatal at ages 13+). These are <b>counts, not rates</b> — CDC publishes no rate for the "
        "transmission breakdown because population denominators by route don&rsquo;t exist — so more populous "
        "states show bigger numbers. Counts are statistically adjusted for missing transmission information; "
        "small suppressed cells are grey; 2020 reflects COVID-19 disruption and the latest year is "
        "preliminary. Each route has its own colour scale; pick one and drag the year slider or press play.")
    html = choropleth_time.render_timeseries(
        {"type": "FeatureCollection", "features": feats}, series, years,
        title="United States — new HIV diagnoses by transmission route, over time",
        subtitle="New HIV diagnoses (ages 13+) by how they were acquired (gay / straight / drug use / …), per state. Pick a route, drag the year slider or press play:",
        value_label="new HIV diagnoses (cases)", value_decimals=0,
        attribution_html=attribution, note=note, note_popup=True, center=[-96, 38], zoom=3.4)
    path = storage.join(storage.maps_root(), "us-hiv-transmission", "index.html")
    storage.write_text(path, html)
    span = f"{years[0]}–{years[-1]}" if years else "n/a"
    return MapResult("us-hiv-transmission", path, joined,
                     f"{joined} states/territories ({span})")


# --- US autism identification by state over time (IDEA Part B child count) --
#
# There is no openly-fetchable per-state clinical-prevalence series for autism
# (CDC ADDM covers ~11 sites; IHME GBD is license-gated). The one all-50-states,
# annual, 20-year source is the US Dept of Education's IDEA Section 618 Part B
# Child Count — students (ages 3-21) served under special education with autism
# as their disability category. It is IDENTIFICATION/eligibility, not a clinical
# diagnosis rate, but it is the standard administrative measure of autism in US
# schools. Files live on data.ed.gov (CKAN); we enumerate the year CSVs from two
# packages and parse them. The schema drifts a lot across 20 years, so the parser
# is header-based: per (state, disability) the count ages 3-21 = an early-childhood
# (age 3-5) total column + a school-age (6-21 / 5-21) total column; the two eras
# differ (2005-2011 one row per state+disability; 2012-2024 split by educational
# environment, summed over the detailed placement rows), state names are upper- or
# title-cased by year, and transition-year files (2019) carry reconciliation
# "Combined ..." totals which we prefer.

IDEA_DATASETS = [
    "207550d8-e977-448a-bf44-15e35104b9d1",   # 2005-2011  bchildcount{YEAR}.csv
    "71ca7d0c-a161-4abe-9e2b-4e68ffb1061a",   # 2012-2024  bchildcountandedenvironment{YEAR}.csv
]
IDEA_YEAR_FROM = 2005
# Consistent (early-childhood, school-age) column pairs; transition files carry both.
_IDEA_PAIRS = [
    (["age 3 to 5"], ["age 6 to 21", "ages 6-21", "age 6-21"]),                  # historical
    (["age 3 to 5 (early childhood)", "age 3-5"], ["age 5 (school age)-21"]),    # current (age 5 split)
]


def _idea_num(x):
    x = (x or "").strip().replace(",", "")
    return int(x) if x.lstrip("-").isdigit() and x not in ("-", "") else None


def _idea_norm(h):
    return " ".join((h or "").split()).lower()


def _idea_year_urls():
    """{year(int): csv download url} for Part B child count, from data.ed.gov CKAN."""
    import re
    urls = {}
    for ds in IDEA_DATASETS:
        d = requests.get("https://data.ed.gov/api/3/action/package_show",
                         params={"id": ds}, headers=BROWSER_UA, timeout=60).json()
        for r in d["result"]["resources"]:
            u = r.get("url", "")
            fn = u.rsplit("/", 1)[-1].lower()
            m = re.match(r"bchildcount(?:andedenvironments?)?(\d{4})(?:-\d{2})?\.csv$", fn)
            if m and "lea" not in fn:
                urls[int(m.group(1))] = u
    return urls


def _parse_idea_childcount(txt):
    """CSV text -> {STATE_UPPER: {'autism': n, 'alltot': n}} (count ages 3-21)."""
    rows = list(csv.reader(io.StringIO(txt)))
    hi = 0
    for i, r in enumerate(rows):
        cl = [_idea_norm(c) for c in r]
        if "year" in cl and any(c.startswith("state") for c in cl) and any("disab" in c for c in cl):
            hi = i
            break
    low = [_idea_norm(c) for c in rows[hi]]
    cstate = next(i for i, h in enumerate(low) if h.startswith("state"))
    cdis = next(i for i, h in enumerate(low) if "disab" in h)
    cenv = next((i for i, h in enumerate(low) if "environ" in h or "setting" in h), None)
    data_rows = rows[hi + 1:]

    def find_sub(*must):
        return next((i for i, h in enumerate(low) if all(m in h for m in must)), None)

    def pick(cands):
        return next((low.index(c) for c in cands if c in low), None)

    def coverage(ci):
        return sum(1 for r in data_rows if ci is not None and ci < len(r) and _idea_num(r[ci]) is not None)

    cec, csa = find_sub("combined", "3-5"), (find_sub("combined", "6-21") or find_sub("combined", "school age"))
    if cec is None or csa is None:
        cec = csa = None
        best = -1
        for ec_c, sa_c in _IDEA_PAIRS:
            ec, sa = pick(ec_c), pick(sa_c)
            if ec is None or sa is None:
                continue
            cov = coverage(ec)
            if cov > best:
                best, cec, csa = cov, ec, sa
    out: dict[str, dict[str, int]] = {}
    if cec is None or csa is None:
        return out
    mx = max(cstate, cdis, cec, csa, cenv or 0)
    for r in data_rows:
        if mx >= len(r):
            continue
        st = " ".join(r[cstate].split()).upper()
        if not st:
            continue
        if cenv is not None:                      # skip convenience Total rows (sum the placements)
            env = _idea_norm(r[cenv])
            if not env or env.startswith("total"):
                continue
        dis = _idea_norm(r[cdis])
        tgt = "autism" if dis == "autism" else ("alltot" if "all disab" in dis else None)
        if not tgt:
            continue
        v = (_idea_num(r[cec]) or 0) + (_idea_num(r[csa]) or 0)
        out.setdefault(st, {})[tgt] = out.setdefault(st, {}).get(tgt, 0) + v
    return out


def build_us_autism() -> MapResult:
    urls = _idea_year_urls()
    years = [y for y in range(IDEA_YEAR_FROM, 2025) if y in urls]
    by_year = {}
    for y in years:
        txt = requests.get(urls[y], headers=BROWSER_UA, timeout=120).content.decode("latin-1")
        by_year[y] = _parse_idea_childcount(txt)
    ystr = [str(y) for y in years]
    series = [
        {"key": "autism_n",    "label": "Students identified with autism (count)",
         "unit": "students served under IDEA, ages 3–21"},
        {"key": "autism_per1k", "label": "Autism per 1,000 special-education students",
         "unit": "per 1,000 students served under IDEA"},
    ]
    fc = json.loads(storage.read_bytes(storage.census_geom("output/tiger/state/us_state.geojson")))
    feats, joined = [], 0
    for f in fc["features"]:
        p = f.get("properties") or {}
        name = p.get("NAME") or ""
        key = name.upper()
        geom = mapping(shape(f["geometry"]).simplify(0.02, preserve_topology=True))
        geom = {"type": geom["type"], "coordinates": _round(geom["coordinates"])}
        props = {"name": name}
        has = False
        for y, ys in zip(years, ystr):
            rec = (by_year.get(y) or {}).get(key)
            if not rec:
                continue
            n = rec.get("autism")
            alld = rec.get("alltot")
            if n is not None:
                props[f"autism_n_{ys}"] = n
                has = True
            if n is not None and alld:
                props[f"autism_per1k_{ys}"] = round(n / alld * 1000)
        joined += 1 if has else 0
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    attribution = (
        'Data: <a href="https://www.ed.gov/data/idea-section-618-data">US Dept of Education, IDEA Section 618</a> '
        'Part B Child Count (students served under special education by disability category, via data.ed.gov). '
        'Geometry: US Census TIGER. Built by an FFL workflow on '
        '<a href="https://github.com/rlemke/facetwork">Facetwork</a> '
        '(<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    note = (
        "This shows autism <b>identification in schools</b>, not a clinical diagnosis rate. Each value is the "
        "number of students aged 3–21 served under the Individuals with Disabilities Education Act (IDEA) whose "
        "primary special-education category is <b>autism</b> — the only measure that covers all 50 states every "
        "year for 20 years (CDC ADDM covers only a few sites; global modelled estimates aren&rsquo;t openly "
        "available per state). The <b>count</b> tracks the dramatic rise but is dominated by state size; "
        "<b>per 1,000 special-education students</b> is population-independent and comparable across states. "
        "The rise reflects expanded diagnostic criteria, greater awareness, and &lsquo;diagnostic "
        "substitution&rsquo; (children once labelled intellectual disability or learning disability now "
        "identified as autistic) as much as any true change in occurrence, and states differ in eligibility "
        "practices — so cross-state differences are partly policy, not prevalence. Autism became an IDEA "
        "reporting category in 1991–92.")
    html = choropleth_time.render_timeseries(
        {"type": "FeatureCollection", "features": feats}, series, ystr,
        title="United States — autism identification in schools, by state over time",
        subtitle="Students served under IDEA with autism (ages 3–21), per state. Pick a measure, drag the year slider or press play:",
        value_label="students", value_decimals=0,
        attribution_html=attribution, note=note, note_popup=True, center=[-96, 38], zoom=3.4)
    path = storage.join(storage.maps_root(), "us-autism", "index.html")
    storage.write_text(path, html)
    span = f"{ystr[0]}–{ystr[-1]}" if ystr else "n/a"
    return MapResult("us-autism", path, joined, f"{joined} states ({span})")


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
