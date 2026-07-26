# US Prevalence by County — CDC PLACES

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildUSPrevalenceMap` / `USPrevalenceMap`) ·
**Builder:** `src/health/_lib.py` — `build_us_prevalence` + `_fetch_places` ·
**Renderer:** `src/health/choropleth.py` (static, condition dropdown)

## Overview

The finest-grained map in the domain: a **US-county** choropleth of adult
**prevalence** (share of adults with the condition) for cancer / diabetes / stroke,
from CDC PLACES, with a condition dropdown. Where [us-mortality](us-mortality.md)
shows *deaths* per state, this shows *cases* per **county** (~2,956 counties). The
static counterpart's county-scale twin.

## How it works

`build_us_prevalence`:

1. **`_fetch_places()`** — `GET data.cdc.gov/resource/swc5-untb.json` (CDC PLACES
   county data) filtered `$where measureid in('CANCER','DIABETES','STROKE') and
   data_value_type='Age-adjusted prevalence'`, `$select locationid,measureid,
   data_value`, `$limit 60000`. Returns `{FIPS(locationid): {condition:
   percent}}`. `PLACES_MEASURES` maps each PLACES `measureid` to a key/label.
2. **Per-state county-geometry loop.** It iterates `STATE_FIPS` (the 2-digit FIPS
   for 50 states + DC + PR), reading each per-state county GeoJSON
   `census_geom("output/tiger/county/<FIPS>_county.geojson")` **only if it exists**
   (`storage.exists`) — so the county geometry is fetched one state file at a time,
   not one national blob.
3. **Join on `GEOID`.** Each county feature's `GEOID` looks up its PLACES record;
   counties with no data or empty geometry are skipped. Polygons are
   `shapely.simplify(0.02)`'d, coordinate-rounded, and tagged `m_cancer` /
   `m_diabetes` / `m_stroke` + `name` (`NAMELSAD`) + `fips`.
4. `choropleth.render` builds the condition-dropdown HTML.

Data shape: `PLACES JSON → {FIPS: {condition: %}} → per-state TIGER county
GeoJSON joined on GEOID → GeoJSON (3 metric props) → static-choropleth HTML`.

## Fan-out

**Single-task — no fan-out.** One PLACES query, then a serial loop over the
per-state county files already cached in MinIO by the census-us domain. This is a
fan-**in** (many county files → one map), not a fleet fan-out.

## Data & fields

- **Metrics / keys:** `m_cancer` / `m_diabetes` / `m_stroke` — age-adjusted adult
  prevalence (%). `data_value_type='Age-adjusted prevalence'` is filtered
  server-side.
- **Dataset:** CDC PLACES `swc5-untb`.
- **Join key:** county `GEOID` (5-digit FIPS) on the per-state
  `<FIPS>_county.geojson` TIGER files.
- **Missing / grey (stated in the note):** **Kentucky & Pennsylvania are blank for
  all three conditions** — PLACES (2025 release) models them from 2023 BRFSS and
  KY & PA have no usable 2023 BRFSS sample (the only two states with no estimates).
  Small counties may be suppressed. Alzheimer's has no prevalence estimate anywhere,
  so it is absent here (see [us-mortality](us-mortality.md) for deaths).

## External libraries / binaries

- **`requests`** (pip) — the single PLACES query (`UA`, `timeout=120`).
- **`shapely`** (pip) — `simplify(0.02)`, empty-geometry guard (`geom.is_empty`).
- No binaries, no API key.

## Facets & workflows

`BuildUSPrevalenceMap() => (region, html_path, feature_count, detail)` — **event**
facet, `with Effect(kind="external") with Cost(tier="moderate") with
Timeout(minutes=20)` (the **longest** timeout in the domain — it reads ~52 county
files and simplifies thousands of polygons). Docstring: *"US county choropleth of
adult prevalence for cancer / diabetes / stroke (CDC PLACES, age-adjusted)."*
Workflow `USPrevalenceMap`. Handler
`_wrap(build_us_prevalence, "BuildUSPrevalenceMap")`.

## Cache / output

`storage.maps_root()/us-prevalence/index.html`. `detail` = `"<N> counties, CDC
PLACES"`. Reads the per-state county TIGER files under `census_geom(...)`.

## Gotchas & notes

- **Depends on the census-us county cache being populated.** Missing
  `<FIPS>_county.geojson` files are silently skipped (`storage.exists` guard) — if
  the census-us domain hasn't cached county geometry, whole states drop out with no
  error. Run/seed census-us first.
- **~2,956 counties** is a large FeatureCollection; the `simplify(0.02)` +
  coordinate-rounding (`_round`, 3 dp) keeps the HTML embeddable. Do not remove the
  simplification.
- **KY/PA blanks are expected**, not a join bug — they are a BRFSS sampling gap.

## Related specs

- [us-mortality](us-mortality.md) — the state-level *deaths* counterpart (and where
  Alzheimer's lives).
- [world-ncd](world-ncd.md) — the world counterpart (diabetes prevalence + NCD).
- [rendering](rendering.md) · [storage-and-geometry](storage-and-geometry.md) ·
  [domain-package](domain-package.md).
