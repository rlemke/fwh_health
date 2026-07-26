# US Autism Identification in Schools — IDEA §618

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildUSAutismMap` / `USAutismMap`) ·
**Builder:** `src/health/_lib.py` — `build_us_autism` + `_idea_year_urls`, `_parse_idea_childcount`, `_idea_num`, `_idea_norm` ·
**Renderer:** `src/health/choropleth_time.py` (measure dropdown + year slider)

## Overview

A **US-state** time-slider choropleth of autism **identification in schools** over
~20 years (2005–2024): students (ages 3–21) served under IDEA with autism as their
primary disability category, shown both as a **count** and **per 1,000
special-education students**. It is explicitly *identification/eligibility, not a
clinical diagnosis rate* — but it is the only all-50-states, annual, 20-year open
source (CDC ADDM covers ~11 sites; IHME GBD is license-gated).

## How it works

`build_us_autism`:

1. **`_idea_year_urls()`** — enumerates the per-year Part B Child Count CSVs from
   two data.ed.gov CKAN packages (`IDEA_DATASETS`: 2005–2011 `bchildcount{YEAR}.csv`
   and 2012–2024 `bchildcountandedenvironment{YEAR}.csv`) via
   `package_show`, regex-matching the filename to a year (excluding `lea` files).
2. **Per-year fetch + parse.** Each year's CSV is downloaded (latin-1 decoded) and
   run through **`_parse_idea_childcount`** — a **header-based** parser resilient to
   20 years of schema drift: it locates the header row, the state/disability/
   environment columns, and picks an (early-childhood, school-age) column pair from
   `_IDEA_PAIRS` (preferring transition-year `"Combined …"` totals), summing ages
   3–5 + 6–21 to a count per `(STATE, {autism, alltot})`. In the 2012+ era it
   **skips convenience Total rows** and sums the split-by-educational-environment
   placement rows instead.
3. **Join on state name (uppercased).** Census TIGER state `NAME.upper()` matches
   the parser's uppercased state key. Two derived series per year: `autism_n_<year>`
   (count) and `autism_per1k_<year>` = `round(autism / alltot * 1000)`.
4. `choropleth_time.render_timeseries` renders the measure dropdown + year slider.

Data shape: `data.ed.gov CKAN → per-year CSV → {STATE: {autism, alltot}} →
GeoJSON (autism_n / autism_per1k per year) → time-slider HTML`.

## Fan-out

**Single-task — no `foreach`.** One CKAN enumeration, then a serial per-year CSV
fetch+parse loop (~20 files), one render.

## Data & fields

- **Series / keys:** `autism_n` (students served, ages 3–21) and `autism_per1k`
  (autism per 1,000 special-education students — population-independent, comparable
  across states).
- **Source:** US Dept of Education **IDEA Section 618 Part B Child Count** via
  data.ed.gov CKAN (`IDEA_DATASETS`).
- **Join key:** state `NAME` (uppercased) on the TIGER state file.
- **Years:** 2005–2024 (`IDEA_YEAR_FROM`.. whichever files exist).
- **Caveat (note):** it is school **identification**, not clinical prevalence; the
  rise reflects expanded criteria, awareness, and diagnostic substitution, and
  states differ in eligibility practice — cross-state differences are partly policy,
  not occurrence.

## External libraries / binaries

- **`requests`** (pip) — CKAN `package_show` + per-year CSV downloads, with
  `BROWSER_UA`.
- **`shapely`** (pip) — `simplify(0.02)` on state polygons.
- **`csv`/`io`/`re`** (stdlib) — CSV parsing and filename→year matching.
- No binaries, no API key.

## Facets & workflows

`BuildUSAutismMap() => (region, html_path, feature_count, detail)` — **event** facet,
`with Effect(kind="external") with Cost(tier="moderate") with Timeout(minutes=15)`.
Docstring: *"US-state choropleth of autism identification in schools over time …
Source: US Dept of Education IDEA Section 618 Part B Child Count."* Workflow
`USAutismMap`. Handler `_wrap(build_us_autism, "BuildUSAutismMap")`.

## Cache / output

`storage.maps_root()/us-autism/index.html`. `detail` = `"<N> states (<first>–<last>)"`.
Reads census TIGER state geometry via `census_geom(...)`.

## Gotchas & notes

- **Schema drift is the whole problem.** The Part B files change layout across 20
  years (one-row-per-state early on; split-by-educational-environment later; state
  names upper- or title-cased by year; age-band column names differ). The
  header-based `_parse_idea_childcount` + `_IDEA_PAIRS` fallback list absorbs this —
  don't replace it with fixed column indices.
- **Transition-year "Combined" totals are preferred** (2019 carries reconciliation
  totals); the parser detects `combined … 3-5` / `combined … 6-21` first.
- **latin-1 decode** is deliberate — some year files aren't clean UTF-8.

## Related specs

- [respiratory-nhsn](respiratory-nhsn.md) / [world-hiv](world-hiv.md) — the other
  time-slider maps sharing `choropleth_time`.
- [rendering](rendering.md) · [storage-and-geometry](storage-and-geometry.md) ·
  [domain-package](domain-package.md).
