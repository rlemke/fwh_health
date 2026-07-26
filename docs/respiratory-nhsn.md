# NHSN Respiratory Family — five time-slider maps off one engine

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildUSRespiratoryMap`, `BuildUSHospitalStrainMap`, `BuildUSICUSeverityMap`, `BuildUSPedVsAdultMap`, `BuildUSTripledemicMap`) ·
**Builder:** `src/health/_lib.py` — `_fetch_nhsn_series` + `_nhsn_map` (the shared engine) and the five thin `build_us_*` wrappers ·
**Renderer:** `src/health/choropleth_time.py`

## Overview

This is the domain's **flagship**: five US-state choropleths of respiratory-virus
hospital burden **over time** — COVID-19 / influenza / RSV — each with a series
dropdown and a **month slider** (`~5` years, `RESP_MONTHS_BACK = 60` monthly
frames). All five are built from **one** CDC source (NHSN Hospital Respiratory
Data, dataset `mpgq-jmmr`) through **one** generic fetch+render engine; each
`build_us_*` facet differs only in the `series_columns` mapping (series key →
source column) and its labels/notes. It is the multi-map analogue of a fan-out
engine: one code path, five published maps.

The five maps:

1. **`us-respiratory`** — new-admission burden per 100k, by virus.
2. **`us-hospital-strain`** — overall inpatient/ICU bed occupancy + share of
   inpatient beds held by each virus.
3. **`us-icu-severity`** — share of each virus's hospitalized patients in the ICU.
4. **`us-ped-vs-adult`** — new-admission rates per 100k split by age group
   (children vs adults) per virus.
5. **`us-tripledemic`** — combined COVID+flu+RSV admissions per 100k (plus each
   virus split out), winter over winter.

## How it works

`_fetch_nhsn_series(series_columns)` is the engine (`_lib.py`):

1. **One Socrata query.** `GET https://data.cdc.gov/resource/mpgq-jmmr.json` with
   `$select` = `jurisdiction,weekendingdate` + the union of all requested source
   columns, `$where jurisdiction in(<50 states + DC>)` (the USPS abbreviations are
   `STATE_POP`'s keys), `$order weekendingdate`, `$limit 100000`. NHSN HRD is
   **weekly**.
2. **Average weekly → monthly.** Each weekly row's value(s) are appended to a
   per-`(state, series_key, month)` bucket (`month = weekendingdate[:7]`,
   `YYYY-MM`). When a series maps to **several** source columns they are **summed
   per week first** (this is how the tripledemic `combined` series adds the three
   viruses' per-100k rates). Each `<series>_<month>` cell then becomes the **mean**
   of that month's weekly values.
3. **Trim to the window.** The partial latest month is dropped
   (`sorted(all_months)[:-1]`), then the last `RESP_MONTHS_BACK` (60) months kept.
4. `_nhsn_map` joins the result onto census TIGER **state** geometry (matched on
   `STUSPS`), simplifies each polygon (`shapely.simplify(0.02)`) and rounds
   coordinates, attaches one property per `<series>_<month>` cell, and calls
   `choropleth_time.render_timeseries(...)`.

Data shape: `weekly NHSN JSON → {STUSPS: {"<series>_<YYYY-MM>": monthly_mean}} →
GeoJSON (one prop per series×month) → time-slider HTML`.

## Fan-out

**Single-task per map — no `foreach`.** Each of the five facets is one atomic
fetch+render (one Socrata query covering all states × all weeks, then an in-memory
month aggregation). Fleet parallelism is *one map per runner* (five workflows can
run concurrently on the `health` task list), not a per-state fan-out — the whole
country comes back in a single query, so fanning out per state would only multiply
API calls.

## Data & fields

- **Source:** CDC NHSN **Hospital Respiratory Data (HRD) Metrics by Jurisdiction**,
  Socrata dataset `mpgq-jmmr` (`NHSN_HRD` constant), weekly, per state/territory.
- **Scope:** 50 states + DC (the `STATE_POP` keys); territories dropped.
- **Series → source columns** (the only thing that differs per map):
  - admissions (`us-respiratory`): `totalconfc19newadmper100k`,
    `totalconfflunewadmper100k`, `totalconfrsvnewadmper100k`.
  - strain (`us-hospital-strain`): `pctinptbedsocc`, `pcticubedsocc`,
    `pctconfc19inptbeds`, `pctconffluinptbeds`, `pctconfrsvinptbeds`.
  - ICU severity (`us-icu-severity`): `pctconfc19hosppatsicu`,
    `pctconffluhosppatsicu`, `pctconfrsvhosppatsicu`.
  - ped-vs-adult (`us-ped-vs-adult`): the `…newadmadultper100k` / `…newadmpedper100k`
    pair for each of covid/flu/rsv.
  - tripledemic (`us-tripledemic`): a `combined` key summing the three
    `…newadmper100k` columns, plus each virus split out.
- **Join key:** state `STUSPS` (USPS abbr) on the TIGER `us_state.geojson`.
- **Cell property key:** `<series_key>_<YYYY-MM>` (e.g. `covid_2024-01`). Series keys
  themselves may contain `_`, so the engine splits the **month** off as the last
  `_`-segment (`cell.rsplit("_", 1)[1]`).
- **Missing / grey:** months a state didn't report. NHSN reporting was **voluntary
  before it became mandatory on Nov 1 2024**, and RSV/flu columns were added after
  COVID — so earlier months read low/grey. This caveat is the shared
  `NHSN_NOTE_TAIL` appended to every map's note.

## External libraries / binaries

- **`requests`** (pip) — the single Socrata query. Sends the `UA` header;
  `timeout=180` (largest in the domain, because the query is wide).
- **`shapely`** (pip) — `shape`/`mapping` + `simplify(0.02)` on state polygons.
- No binaries. No API key (Socrata app-token optional and not used).

## Facets & workflows

All five are **event** facets returning `(region, html_path, feature_count, detail)`,
each `with Effect(kind="external") with Cost(tier="moderate") with Timeout(minutes=15)`:

| Facet | Workflow | Purpose (from FFL docstring) |
|---|---|---|
| `BuildUSRespiratoryMap()` | `USRespiratoryMap` | COVID/flu/RSV new admissions per 100k, by month |
| `BuildUSHospitalStrainMap()` | `USHospitalStrainMap` | inpatient/ICU bed occupancy + per-virus bed share |
| `BuildUSICUSeverityMap()` | `USICUSeverityMap` | share of each virus's inpatients in the ICU |
| `BuildUSPedVsAdultMap()` | `USPedVsAdultMap` | admission rates per 100k, children vs adults |
| `BuildUSTripledemicMap()` | `USTripledemicMap` | combined COVID+flu+RSV burden, winter over winter |

Each workflow is a one-step `andThen` that calls its facet and yields
`(status="completed", html_path, detail)`. The handler
(`health_handlers._DISPATCH`) maps each facet to `_wrap(build_us_*, …)`, which calls
the zero-arg builder and logs `detail -> html_path`.

## Cache / output

`storage.maps_root()/<name>/index.html` — `<root>/health-maps/<name>/` locally,
`<root>/cache/health/maps/<name>/` on the fleet (MinIO). `detail` reports
`"<N> states × <M> months (<first> – <last>)"`. Reads state geometry via
`storage.census_geom("output/tiger/state/us_state.geojson")` (the census-us TIGER
cache). See [storage-and-geometry](storage-and-geometry.md).

## Gotchas & notes

- **Fixed colour scale per series is load-bearing.** `choropleth_time` quantises
  each series **once across all months** (six break quantiles
  `0.1…0.93`), so dragging the slider shows a wave against a stable legend — not a
  per-frame re-quantise that would make every month look identical. See
  [rendering](rendering.md).
- **Multi-column series are summed *before* averaging.** The tripledemic `combined`
  series sums whichever of the three viruses reported that week, then averages — so
  before flu/RSV reporting existed it tracks COVID alone (stated in its note).
- **The partial latest month is intentionally dropped** — otherwise the last frame
  would be a low outlier from an incomplete month.
- **Pre-Nov-2024 undercounting** is a data property, not a bug; do not "fix" grey
  early months.

## Related specs

- [rendering](rendering.md) — `choropleth_time.render_timeseries` (slider, play,
  fixed per-series scale) that all five maps render through.
- [storage-and-geometry](storage-and-geometry.md) — TIGER state geometry reuse and
  the output-path backend split.
- [domain-package](domain-package.md) — facet/handler wiring and the FFL workflows.
- [us-mortality](us-mortality.md) — the other CDC-sourced US-state map (static, not
  a time slider).
