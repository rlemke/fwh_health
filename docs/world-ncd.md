# World NCD + Infectious Burden — WHO GHO / World Bank

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildWorldNCDMap` / `WorldNCDMap`) ·
**Builder:** `src/health/_lib.py` — `build_world_ncd` + `_fetch_who`, `_fetch_owid_diabetes`, `_fetch_who_covid_world` ·
**Renderer:** `src/health/choropleth.py` (static, metric dropdown)

## Overview

A **world** country choropleth with a metric dropdown, joining six global
indicators onto Natural Earth country polygons: three non-communicable-disease
(NCD) metrics — diabetes prevalence, premature-NCD mortality, NCD mortality rate —
plus three infectious overlays — COVID-19 deaths/100k, HIV prevalence, measles
cases. It is the domain's honest answer to "why isn't there a per-cause world
cancer/stroke map": those series aren't openly redistributable, so the map shows
the **NCD burden** (which spans them) plus the infectious metrics that *are*
openly current.

## How it works

`build_world_ncd` fetches six sources and joins on ISO codes:

1. **`_fetch_owid_diabetes()`** — OWID grapher CSV
   (`ourworldindata.org/grapher/diabetes-prevalence.csv`), latest year, keyed by
   ISO3 `Code`. → `m_diabetes`.
2. **`_fetch_who("NCDMORT3070")`** — WHO GHO OData API
   (`ghoapi.azureedge.net/api/<code>`), premature-NCD probability. → `m_ncd_premature`.
3. **`_fetch_who("WHS2_131")`** — NCD mortality rate (age-std deaths/100k). →
   `m_ncd_rate`.
4. **`_fetch_who("MDG_0000000029")`** — HIV prevalence, adults 15–49 (%). → `m_hiv`.
5. **`_fetch_who("WHS3_62")`** — measles reported cases. → `m_measles`.
6. **`_fetch_who_covid_world()`** — WHO global COVID CSV (Azure blob), cumulative
   deaths per **ISO-2**, divided by Natural Earth `POP_EST` → deaths/100k
   (`m_covid`).

`_fetch_who` is the reusable GHO helper: it keeps `SpatialDimType == "COUNTRY"`
rows with a numeric value, **prefers both-sex** rows (`Dim1 == "SEX_BTSX"`), falls
back to no-sex-dimension rows (HIV/measles carry `Dim1=None`), takes the max
`TimeDim`, and returns `({ISO3: value}, year)`. Natural Earth ISO resolution is
defensive: `ISO_A3`, falling back to `ISO_A3_EH`/`ADM0_A3` when it is `-99`; ISO-2
similarly. Polygons are `shapely.simplify(0.1)`'d, rounded to 2 dp.

Data shape: `six WHO/OWID feeds → per-ISO dicts → Natural Earth GeoJSON (6 metric
props) → static-choropleth HTML`.

## Fan-out

**Single-task — no fan-out.** Six sequential fetches, one render.

## Data & fields

- **Metrics / keys:** `m_diabetes` (%, `dy`), `m_ncd_premature` (% dying age 30–70,
  `py`), `m_ncd_rate` (deaths/100k age-std, `ry`), `m_covid` (cumulative
  deaths/100k), `m_hiv` (% adults 15–49, `hy`), `m_measles` (reported cases, `my`).
  Each label carries its own latest year (per source).
- **Datasets / endpoints:** OWID grapher CSV; WHO GHO OData indicators
  `NCDMORT3070`, `WHS2_131`, `MDG_0000000029`, `WHS3_62`; WHO global COVID CSV.
- **Join key:** country **ISO_A3** (most metrics) and **ISO_A2** (COVID) on Natural
  Earth `ne_110m_admin_0_countries.geojson` (`NE_URL`).
- **`feature_count` semantics:** unlike the US maps, `build_world_ncd` returns the
  count of countries with **at least one** non-null metric (`joined`), not the raw
  feature count.
- **Missing / grey (note):** per-cause cancer/stroke/Alzheimer's isn't openly
  available worldwide (IHME/OWID license-blocked, WHO cause series empty/2004, IARC
  API not JSON); HIV/measles are missing for the ~40–90 countries that don't report.

## External libraries / binaries

- **`requests`** (pip) — OWID CSV, five WHO fetches, Natural Earth GeoJSON, WHO
  COVID CSV (`UA`, `timeout` 60–120).
- **`shapely`** (pip) — `simplify(0.1)` on world polygons, `mapping`/`shape`.
- **`csv`/`io`** (stdlib) — parse the OWID + WHO COVID CSVs.
- No binaries, no API key.

## Facets & workflows

`BuildWorldNCDMap() => (region, html_path, feature_count, detail)` — **event**
facet, `with Effect(kind="external") with Cost(tier="moderate") with
Timeout(minutes=15)`. Docstring: *"World country choropleth of
non-communicable-disease burden … joined onto Natural Earth geometry by ISO-A3."*
Workflow `WorldNCDMap`. Handler `_wrap(build_world_ncd, "BuildWorldNCDMap")`.

## Cache / output

`storage.maps_root()/world-ncd/index.html`. `detail` = `"<N> countries with data"`.
Reads Natural Earth over HTTP (not a cached artifact) — the only map that fetches
its geometry live rather than from the census cache.

## Gotchas & notes

- **Natural Earth ISO codes need fallbacks.** France, Norway, Kosovo, etc. carry
  `ISO_A3 == "-99"`; the builder falls back to `ISO_A3_EH`/`ADM0_A3`. Removing the
  fallback silently drops those countries.
- **COVID is ISO-2, everything else ISO-3.** The COVID rate needs `POP_EST` from
  the same NE feature; a country with `POP_EST` 0/None yields a null COVID cell.
- **Honest scope is a design choice, not a gap to "fix."** The map deliberately does
  not attempt per-cause world cancer/stroke data.

## Related specs

- [us-prevalence](us-prevalence.md) / [us-mortality](us-mortality.md) — the US
  chronic-disease maps this complements.
- [world-hiv](world-hiv.md) — the over-time world HIV map (WHO SDGHIV + UNAIDS).
- [rendering](rendering.md) · [storage-and-geometry](storage-and-geometry.md) ·
  [domain-package](domain-package.md).
