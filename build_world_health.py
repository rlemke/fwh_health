"""World country choropleth of disease-burden metrics, rendered to MinIO.

Honest scope: current, openly-redistributable country-level data for these
specific diseases barely exists. Cancer/stroke/Alzheimer's cases & deaths are
not available worldwide (IHME/OWID are license-blocked; WHO's cause-specific
death series are empty or frozen at 2004; IARC's API isn't cleanly fetchable).
What IS clean and current covers the same non-communicable-disease burden:

- Diabetes prevalence (% of adults 20-79) — World Bank / IDF via Our World in Data
- Premature NCD mortality (% probability of dying age 30-70 from cancer,
  cardiovascular disease, diabetes or chronic respiratory disease) — WHO GHO
- Age-standardized NCD mortality rate (deaths/100k) — WHO GHO

Geometry: Natural Earth 1:110m country polygons, joined by ISO-A3.
"""
from __future__ import annotations
import csv, io, json
import boto3, requests
from shapely.geometry import shape, mapping
import choropleth

S3 = boto3.client("s3", endpoint_url="http://192.168.68.96:9000",
                  aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")
BUCKET = "afl-cache"
UA = {"User-Agent": "facetwork-health/1.0 (+github.com/rlemke/facetwork)"}
NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
          "geojson/ne_110m_admin_0_countries.geojson")


def fetch_who(code: str) -> tuple[dict, int]:
    """ISO3 -> value for the latest year, both sexes."""
    rows = requests.get(f"https://ghoapi.azureedge.net/api/{code}", headers=UA, timeout=60).json()["value"]
    both = [d for d in rows if d.get("Dim1") == "SEX_BTSX"
            and d.get("SpatialDimType") == "COUNTRY" and d.get("NumericValue") is not None]
    yr = max(d["TimeDim"] for d in both)
    return {d["SpatialDim"]: round(float(d["NumericValue"]), 1) for d in both if d["TimeDim"] == yr}, yr


def fetch_owid_diabetes() -> tuple[dict, int]:
    t = requests.get("https://ourworldindata.org/grapher/diabetes-prevalence.csv",
                     params={"csvType": "full"}, headers=UA, timeout=60).text
    rows = list(csv.DictReader(io.StringIO(t)))
    col = [c for c in rows[0] if "iabetes" in c][0]
    have = [r for r in rows if r.get("Code") and r[col]]
    yr = max(int(r["Year"]) for r in have)
    return {r["Code"]: round(float(r[col]), 1) for r in have if int(r["Year"]) == yr}, yr


def load_countries():
    gj = requests.get(NE_URL, headers=UA, timeout=60).json()
    out = []
    for f in gj["features"]:
        p = f["properties"]
        iso = p.get("ISO_A3")
        if not iso or iso == "-99":
            iso = p.get("ISO_A3_EH") or p.get("ADM0_A3")
        name = p.get("NAME") or p.get("ADMIN")
        geom = shape(f["geometry"]).simplify(0.1, preserve_topology=True)
        if geom.is_empty:
            continue
        g = mapping(geom)
        g = {"type": g["type"], "coordinates": _round(g["coordinates"])}
        out.append((iso, name, g))
    return out


def _round(o, nd=2):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, (list, tuple)):
        return [_round(x, nd) for x in o]
    return o


def build():
    diab, dy = fetch_owid_diabetes()
    prem, py = fetch_who("NCDMORT3070")
    rate, ry = fetch_who("WHS2_131")
    countries = load_countries()
    feats = []
    for iso, name, geom in countries:
        props = {"name": name, "iso": iso,
                 "m_diabetes": diab.get(iso), "m_ncd_premature": prem.get(iso), "m_ncd_rate": rate.get(iso)}
        if all(props[k] is None for k in ("m_diabetes", "m_ncd_premature", "m_ncd_rate")):
            # keep the polygon (renders grey) so the world looks complete
            pass
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    fc = {"type": "FeatureCollection", "features": feats}
    metrics = [
        {"key": "m_diabetes",      "label": f"Diabetes prevalence — % of adults ({dy})"},
        {"key": "m_ncd_premature", "label": f"Premature NCD deaths — % dying age 30–70 ({py})"},
        {"key": "m_ncd_rate",      "label": f"NCD mortality rate — deaths/100k, age-std ({ry})"},
    ]
    attribution = (f'Data: <a href="https://ourworldindata.org/grapher/diabetes-prevalence">Our World in Data / World Bank</a> '
                   f'(diabetes, {dy}) &amp; <a href="https://www.who.int/data/gho">WHO GHO</a> (NCD mortality, {py}). '
                   'Premature NCD = cancer + cardiovascular + diabetes + chronic respiratory. Geometry: Natural Earth. '
                   'Built by an FFL workflow on <a href="https://github.com/rlemke/facetwork">Facetwork</a> '
                   '(<a href="https://github.com/rlemke/fwh_health">fwh_health</a>).')
    html = choropleth.render(fc, metrics,
                             title="World non-communicable disease burden",
                             subtitle="Diabetes prevalence + NCD mortality (cancer / cardiovascular / diabetes / respiratory). Pick a metric:",
                             attribution_html=attribution, center=[10, 25], zoom=1.4)
    key = "cache/health/maps/world-ncd/index.html"
    S3.put_object(Bucket=BUCKET, Key=key, Body=html.encode("utf-8"), ContentType="text/html")
    joined = sum(1 for f in feats if any(f["properties"][k] is not None for k in ("m_diabetes","m_ncd_premature","m_ncd_rate")))
    print(f"countries: {len(feats)} polygons, {joined} with data  (diabetes {len(diab)}, premature {len(prem)}, rate {len(rate)})")
    print(f"uploaded: s3://{BUCKET}/{key}  ({len(html):,} bytes)")


if __name__ == "__main__":
    build()
