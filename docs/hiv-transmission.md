# HIV by Transmission Route — Europe (ECDC) & US (AtlasPlus)

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildEuropeHIVTransmissionMap` / `EuropeHIVTransmissionMap`, `BuildUSHIVTransmissionMap` / `USHIVTransmissionMap`) ·
**Builder:** `src/health/_lib.py` — `build_europe_hiv_transmission` (+ `_fetch_ecdc_hiv_transmission`, `_ecdc_get`, `_ecdc_count_measure_id`), `build_us_hiv_transmission` (+ `_fetch_atlasplus_hiv_transmission`) ·
**Renderer:** `src/health/choropleth_time.py` (route dropdown + year slider)

## Overview

Two sibling **time-slider** choropleths that answer the question the world HIV map
explicitly *can't*: the **per-geography gay-vs-straight split** of new HIV
diagnoses, broken out by **route of transmission**. Europe does it per EU/EEA
**country** (ECDC), the US per **state** (CDC) — deliberate counterparts sharing
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

### US — CDC NCHHSTP AtlasPlus (`build_us_hiv_transmission`)

AtlasPlus has **no documented API**; the builder drives its internal JSON backend
(`ATLASPLUS`):

1. `GET .../getInitData/00` returns a `varvals` id catalog. The builder reads it to
   resolve **state ids** (`vtid 3`, `geoLevel 1002`, 2-digit `fips`) and **year ids**
   (`vtid 2`) at run time.
2. For each transmission category in `US_HIV_TX`, **one** `POST
   .../qtOutputData {"VariableIDs": "<all state ids + all year ids + one tx id>"}`
   returns every state×year for that category (**6 posts total**). Each `sourcedata`
   row's cases are column `r[9]` (the transmission breakdown has **no rate**);
   suppressed cells come back null.
3. Join onto census TIGER **state** geometry by `STATEFP`, `simplify(0.02)`, render.

Data shape (both): `route×geo×year source rows → {geo: {route: {year: count}}} →
GeoJSON (one prop per route×year) → time-slider HTML`.

## Fan-out

**Single-task per map — no `foreach`.** Europe fans its *fetch* over 6 routes × ~31
countries of REST calls; the US does 6 posts. Both aggregate in-memory into one
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

- **`requests`** (pip) — ECDC REST (per route × country) and AtlasPlus GET+POST,
  plus Natural Earth. Both use `BROWSER_UA`; the US POST additionally sends
  `ATLAS_HDRS` (`Content-Type: application/json`, `X-Requested-With`, a `Referer`).
- **`shapely`** (pip) — `simplify` (0.05 Europe, 0.02 US).
- **`json`** (stdlib) — the AtlasPlus POST body.
- No binaries, no API key.

## Facets & workflows

Both are **event** facets returning `(region, html_path, feature_count, detail)`,
each `with Effect(kind="external") with Cost(tier="moderate") with Timeout(minutes=15)`:

| Facet | Workflow | Source |
|---|---|---|
| `BuildEuropeHIVTransmissionMap()` | `EuropeHIVTransmissionMap` | ECDC Surveillance Atlas |
| `BuildUSHIVTransmissionMap()` | `USHIVTransmissionMap` | CDC NCHHSTP AtlasPlus |

Handlers: `_wrap(build_europe_hiv_transmission, …)` and
`_wrap(build_us_hiv_transmission, …)` in `health_handlers._DISPATCH`.

## Cache / output

`storage.maps_root()/europe-hiv-transmission/index.html` and
`.../us-hiv-transmission/index.html`. Europe reads Natural Earth over HTTP; the US
reads census TIGER state geometry via `census_geom(...)`. `detail` reports the
joined geography count + year span.

## Gotchas & notes

- **AtlasPlus is undocumented and unsupported** — CDC may change the `getInitData`
  / `qtOutputData` backend without notice. The code comment names AIDSVu's per-year
  state xlsx as the documented fallback. Row-column positions (`r[1]` year id,
  `r[2]` geo id, `r[9]` cases) are backend-specific and brittle.
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
