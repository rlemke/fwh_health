# HIV by Transmission Route — Europe (ECDC) & US (AIDSVu)

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildEuropeHIVTransmissionMap` / `EuropeHIVTransmissionMap`, `BuildUSHIVTransmissionMap` / `USHIVTransmissionMap`) ·
**Builder:** `src/health/_lib.py` — `build_europe_hiv_transmission` (+ `_fetch_ecdc_hiv_transmission`, `_ecdc_get`, `_ecdc_count_measure_id`), `build_us_hiv_transmission` (+ `_fetch_aidsvu_hiv_transmission`, `_aidsvu_state_newdx_urls`, `_aidsvu_header`, `_aidsvu_int`) ·
**Renderer:** `src/health/choropleth_time.py` (route dropdown + year slider)

## Overview

Two sibling **time-slider** choropleths that answer the question the world HIV map
explicitly *can't*: the **per-geography gay-vs-straight split** of new HIV
diagnoses, broken out by **route of transmission**. Europe does it per EU/EEA
**country** (ECDC), the US per **state** (CDC surveillance, via AIDSVu) — deliberate counterparts sharing
the same route vocabulary, a route dropdown, and a year slider. Both report
**counts, not rates** (population denominators by route don't exist).

## How it works

### Europe — ECDC Surveillance Atlas (`build_europe_hiv_transmission`)

The ECDC Atlas (TESSy, `healthtopicId 75` / `datasetId 2048`) is driven through its
REST API (`ECDC_BASE`):

1. **`_ecdc_count_measure_id(pop_label)`** resolves each transmission population's
   **"Reported cases" (Unit `"N"`) measure id** at run time via
   `GetIndicatorMeasuresForHealthTopicDatasetAndPopulation` — robust to dataset
   version id drift.
2. **`_fetch_ecdc_hiv_transmission()`** then calls
   `GetMeasureResultsForTimeUnitAndGeoRegion` per measure id **× per EU/EEA country**
   (`EU_EEA`), keeping years ≥ `HIV_YEAR_FROM (2000)`. ECDC ISO-2 quirks are mapped
   to Natural Earth via `ECDC_TO_NE` (`UK→GB`, `EL→GR`).
3. Join onto Natural Earth by ISO-2 (only EU/EEA reporting countries kept),
   `simplify(0.05)`, and render. `EU_HIV_POPS` defines the six routes.

### US — AIDSVu (`build_us_hiv_transmission`)

This map used to drive CDC NCHHSTP AtlasPlus's undocumented JSON backend. On
2026-08-25 every path under `/grasp/AtlasPlus/` began returning 404 (the tool page
itself still served 200), so the builder now reads **AIDSVu** (Emory Rollins School
of Public Health), which republishes the same CDC surveillance data as documented
per-year state workbooks (`AIDSVu_State_NewDX_<year>-<publication date>.xlsx`,
2008–2023):

1. **`_aidsvu_state_newdx_urls()`** scrapes the workbook URLs from the datasets page
   (`AIDSVU_DATASETS_URL`, overridable via `FW_AIDSVU_DATASETS_URL`). They are
   scraped, never constructed: the filename carries a publication datestamp that
   changes on every republish.
2. For each year ≥ `US_HIV_YEAR_FROM (2008)`, the workbook's `Data` sheet is read
   with `openpyxl`; **`_aidsvu_header()`** locates the header row by content (the
   row containing `Year` and `State`), and the six `US_HIV_TX` "Cases" columns are
   read per state. Blank/suppressed cells become `None` (`_aidsvu_int`), never 0.
3. `GEO ID` is the state FIPS **unpadded** (Arizona is 4, Colorado 8) — zero-padded
   and joined onto census TIGER **state** geometry by `STATEFP`, `simplify(0.02)`,
   render.

Data shape (both): `route×geo×year source rows → {geo: {route: {year: count}}} →
GeoJSON (one prop per route×year) → time-slider HTML`.

## Fan-out

**Single-task per map — no `foreach`.** Europe fans its *fetch* over 6 routes × ~31
countries of REST calls; the US downloads one workbook per year. Both aggregate in-memory into one
render — no fleet fan-out.

## Data & fields

- **Europe routes / keys** (`EU_HIV_POPS`): `tx_total`, `tx_msm` (sex between men —
  gay & other MSM, incl. bisexual men), `tx_hetero`, `tx_idu` (injecting drug use),
  `tx_mtct` (mother-to-child), `tx_unknown`. Unit: *new HIV diagnoses (reported
  cases)*. Join key **ISO_A2**; years 2000–2024.
- **US routes / keys** (`US_HIV_TX`): `tx_all`, `tx_msm` (male-to-male sexual
  contact), `tx_hetero`, `tx_idu` (injection drug use), `tx_msmidu` (MSM & IDU),
  `tx_other`. Unit: *new HIV diagnoses (cases, ages 13+)*. Join key **STATEFP**;
  years from `US_HIV_YEAR_FROM (2008)`.
- **Counts, not rates** — stated prominently in both notes; more populous
  geographies show bigger numbers.
- **Missing / grey:** non-reporting/non-EU-EEA countries (Europe); suppressed small
  cells + COVID-disrupted 2020 + preliminary latest year (US).

## External libraries / binaries

- **`requests`** (pip) — ECDC REST (per route × country), the AIDSVu datasets page
  + per-year workbooks, plus Natural Earth. All use `BROWSER_UA`.
- **`openpyxl`** (pip) — reads the AIDSVu `.xlsx` workbooks (imported lazily; only
  this map needs it).
- **`shapely`** (pip) — `simplify` (0.05 Europe, 0.02 US).
- No binaries, no API key.

## Facets & workflows

Both are **event** facets returning `(region, html_path, feature_count, detail)`,
each `with Effect(kind="external") with Cost(tier="moderate") with Timeout(minutes=15)`:

| Facet | Workflow | Source |
|---|---|---|
| `BuildEuropeHIVTransmissionMap()` | `EuropeHIVTransmissionMap` | ECDC Surveillance Atlas |
| `BuildUSHIVTransmissionMap()` | `USHIVTransmissionMap` | AIDSVu (CDC surveillance) |

Handlers: `_wrap(build_europe_hiv_transmission, …)` and
`_wrap(build_us_hiv_transmission, …)` in `health_handlers._DISPATCH`.

## Cache / output

`storage.maps_root()/europe-hiv-transmission/index.html` and
`.../us-hiv-transmission/index.html`. Europe reads Natural Earth over HTTP; the US
reads census TIGER state geometry via `census_geom(...)`. `detail` reports the
joined geography count + year span.

## Gotchas & notes

- **AtlasPlus was withdrawn (2026-08-25)** — its undocumented backend 404s, which
  surfaced as a JSON parse of an error body and dead-lettered the map. AIDSVu is the
  replacement; if its page layout or naming changes, `_aidsvu_state_newdx_urls`
  raises rather than rendering an empty map.
- **`GEO ID` is unpadded FIPS, not a sequential index** — treating it as an index
  would silently mis-attribute every state after Arizona.
- **ECDC measure ids are resolved at run time**, on purpose — hardcoding them breaks
  on the next dataset version. Keep `_ecdc_count_measure_id`.
- **`ECDC_TO_NE` (`UK→GB`, `EL→GR`) is load-bearing** — without it the UK and Greece
  fail the Natural Earth ISO-2 join and go grey.
- **Bisexual men are counted under MSM** in both datasets (noted in both maps).

## Related specs

- [world-hiv](world-hiv.md) — the world HIV map whose missing per-country
  gay/straight split these two provide regionally.
- [rendering](rendering.md) — the shared time-slider renderer.
- [storage-and-geometry](storage-and-geometry.md) · [domain-package](domain-package.md).
