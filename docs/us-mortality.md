# US Mortality by State — chronic deaths + COVID + flu

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildUSMortalityMap` / `USMortalityMap`) ·
**Builder:** `src/health/_lib.py` — `build_us_mortality` + `_fetch_nchs`, `_fetch_covid_us_state`, `_fetch_flu_us_state` ·
**Renderer:** `src/health/choropleth.py` (static, metric dropdown)

## Overview

A **US-state** choropleth of disease burden with a metric dropdown: four chronic
**age-adjusted death rates** (cancer / stroke / diabetes / Alzheimer's) plus two
infectious overlays — cumulative COVID-19 deaths/100k and peak flu activity. It
answers "which state has the highest death rate from cause X?" and folds three CDC
sources onto one map. Static (no time slider) — each metric is a single latest
snapshot.

## How it works

`build_us_mortality` fetches three sources, keyed differently, and merges them onto
state geometry:

1. **`_fetch_nchs()`** — `GET data.cdc.gov/resource/bi63-dtpu.json` (NCHS Leading
   Causes of Death) filtered `$where cause_name in(...)` for the four causes,
   `$limit 50000`. Keeps only the **max year** present and drops the `"United
   States"` aggregate row; value is `aadr` (age-adjusted death rate). Keyed by full
   **state name**.
2. **`_fetch_covid_us_state()`** — `GET .../kn79-hsxy.json` (CDC provisional county
   COVID death counts), summed to state via `state_name`, then divided by
   `STATE_POP` (2020 Census resident population, a hardcoded USPS-abbr → population
   table) to get **deaths/100k**. Keyed by **USPS abbr**.
3. **`_fetch_flu_us_state()`** — `GET .../6svj-q4zv.json` (CDC FluView ILINet)
   filtered to the most recent **complete** season (`FLU_SEASON = "2023-2024"`);
   takes the **peak** `activity_level` (0–13) per state. Keyed by **state name**.

The three dicts are joined onto census TIGER `us_state.geojson`: NCHS/flu on
`NAME`, COVID on `STUSPS`. Each state polygon is `shapely.simplify(0.02)`'d and
coordinate-rounded; properties become `m_cancer`, `m_stroke`, `m_diabetes`,
`m_alzheimer`, `m_covid`, `m_flu`. `choropleth.render` builds the metric-dropdown
HTML.

Data shape: `three CDC JSON feeds → {state: {metric: value}} → GeoJSON (6 metric
props) → static-choropleth HTML`.

## Fan-out

**Single-task — no fan-out.** One builder, three sequential fetches, one render.
The whole country is a handful of Socrata queries; per-state fan-out would only
multiply calls.

## Data & fields

- **Metrics / keys:** `m_cancer` / `m_stroke` / `m_diabetes` / `m_alzheimer`
  (deaths/100k, age-adjusted, NCHS latest year `year`), `m_covid` (cumulative
  deaths/100k, 2020–23), `m_flu` (peak ILINet activity level 0–13,
  `FLU_SEASON`). `NCHS_CAUSES` maps each key to its NCHS `cause_name` label.
- **Datasets:** `bi63-dtpu` (NCHS), `kn79-hsxy` (COVID county deaths),
  `6svj-q4zv` (FluView ILINet).
- **Join keys:** state `NAME` (NCHS, flu) and `STUSPS` (COVID) on the TIGER state
  file.
- **Missing / grey:** the note explains that Alzheimer's appears **deaths-only**
  ("no prevalence estimate anywhere"), COVID is cumulative not annual, and flu is a
  surveillance *intensity index* (not deaths/cases — flu isn't notifiable by count).

## External libraries / binaries

- **`requests`** (pip) — the three Socrata queries (`UA` header; `timeout` 90–120).
- **`shapely`** (pip) — `simplify(0.02)` + `mapping`/`shape` on state polygons.
- No binaries, no API key.

## Facets & workflows

`BuildUSMortalityMap() => (region, html_path, feature_count, detail)` — **event**
facet, `with Effect(kind="external") with Cost(tier="moderate") with Timeout(minutes=15)`.
Docstring: *"US state choropleth of age-adjusted death rates for cancer / stroke /
diabetes / Alzheimer's (CDC NCHS), with a cause dropdown."* Workflow
`USMortalityMap` is a one-step `andThen` yielding `(status="completed", html_path,
detail)`. Handler: `health_handlers._DISPATCH["health.maps.BuildUSMortalityMap"]`
= `_wrap(build_us_mortality, …)`.

## Cache / output

`storage.maps_root()/us-mortality/index.html` (local `health-maps/…`, fleet
`cache/health/maps/…`). `detail` = `"<N> states, NCHS <year> + COVID + flu"`. Reads
`census_geom("output/tiger/state/us_state.geojson")`.

## Gotchas & notes

- **COVID counts → rate needs `STATE_POP`.** The COVID feed is raw county death
  *counts*; the per-100k rate depends on the hardcoded 2020-Census population table.
  A state missing from `STATE_POP` is silently dropped from the COVID metric.
- **Flu is an intensity index, not counts.** `m_flu` is 0–13 ILINet activity, so its
  legend/scale is qualitatively different from the deaths metrics — the renderer's
  per-metric quantile scale handles this, and the note says so.
- **NCHS "latest year" floats.** `_fetch_nchs` takes `max(year)` in the response,
  so the map re-dates itself when NCHS publishes a new Leading-Causes release.

## Related specs

- [us-prevalence](us-prevalence.md) — the county-level *prevalence* (cases)
  counterpart from CDC PLACES.
- [respiratory-nhsn](respiratory-nhsn.md) — the CDC time-series US-state family.
- [rendering](rendering.md) · [storage-and-geometry](storage-and-geometry.md) ·
  [domain-package](domain-package.md).
