# World HIV/AIDS Over Time — by sex & key population

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` (`BuildWorldHIVMap` / `WorldHIVMap`) ·
**Builder:** `src/health/_lib.py` — `build_world_hiv` + `_fetch_sdghiv`, `_fetch_kp_atlas` ·
**Renderer:** `src/health/choropleth_time.py` (category dropdown + year slider)

## Overview

A **world** choropleth of HIV/AIDS **over time** (2000–2024) with a category
dropdown and a **year slider + play**. Two openly-fetchable per-country, over-time
dimensions share one map: new-infection **rate** by sex (all / women / men) and HIV
**prevalence among key populations** (gay men & other MSM / sex workers / people who
inject drugs / transgender people). It is the "is it rising or falling, and who does
it hit" view the static world map can't give.

## How it works

`build_world_hiv` merges two sources, each `{ISO3: {series_key: {year: value}}}`:

1. **`_fetch_sdghiv()`** — WHO GHO `SDGHIV` OData feed. New HIV infections per 1,000
   uninfected, split by sex via `_HIV_SEX` (`SEX_BTSX`→`inf_total`,
   `SEX_FMLE`→`inf_women`, `SEX_MLE`→`inf_men`), country rows only, from
   `HIV_YEAR_FROM = 2000`. Reported **every year** (a dense rate series).
2. **`_fetch_kp_atlas()`** — the **UNAIDS Key Populations Atlas** bulk zip
   (`KPAtlasDB_2025_en.zip`), unzipped in memory; national rows (`Area Level == "2"`,
   `Subgroup == "Total"`) mapped via `_HIV_KP` to `prev_msm` / `prev_sw` / `prev_pwid`
   / `prev_trans`. HIV **prevalence %** reported only in **survey years** (sparse).

Both are joined onto Natural Earth by ISO3 (with the `-99` → `ISO_A3_EH`/`ADM0_A3`
fallback), simplified (`0.1`) and rounded (2 dp). Each `<series_key>_<year>` cell
that exists becomes a property; `choropleth_time.render_timeseries` renders the
year slider with a **fixed per-series colour scale**. Each series carries its own
`unit` (rate vs prevalence-%), which the renderer's legend honours.

Data shape: `WHO SDGHIV + UNAIDS KP zip → {ISO3: {series: {year: value}}} →
Natural Earth GeoJSON (one prop per series×year) → time-slider HTML`.

## Fan-out

**Single-task — no fan-out.** Two fetches (one of them a zip download), one render.

## Data & fields

- **Series / keys:** `inf_total` / `inf_women` / `inf_men` (new infections /1,000
  uninfected — a **rate**, unit `rate_unit`); `prev_msm` / `prev_sw` / `prev_pwid`
  / `prev_trans` (HIV **prevalence %** in that group — unit `prev_unit`).
- **Years:** `2000–2024` (`HIV_YEAR_FROM`..2024).
- **Sources:** WHO GHO `SDGHIV`; UNAIDS Key Populations Atlas `KPAtlasDB_2025_en.zip`.
- **Join key:** country **ISO_A3** on Natural Earth.
- **`feature_count`:** countries with **any** HIV data (`joined`).
- **Missing / grey (note):** the KP-prevalence series are grey in non-survey years
  (sparse by nature); a true per-country "gay vs straight vs bisexual" split of new
  infections is **not** openly published worldwide (UNAIDS reports it only
  global/regional), so it is omitted rather than fabricated. For the per-country
  transmission-route split, see [hiv-transmission](hiv-transmission.md).

## External libraries / binaries

- **`requests`** (pip) — WHO GHO fetch (`UA`, `timeout=120`), the KP Atlas zip, and
  Natural Earth.
- **`shapely`** (pip) — `simplify(0.1)` on world polygons.
- **`zipfile`/`io`/`csv`** (stdlib) — unzip + parse the KP Atlas CSV.
- No binaries, no API key.

**Header quirk:** the UNAIDS Azure gateway **403s non-browser User-Agents**, so the
KP Atlas download uses `BROWSER_UA` (a Chrome UA string), not the domain `UA`.

## Facets & workflows

`BuildWorldHIVMap() => (region, html_path, feature_count, detail)` — **event** facet,
`with Effect(kind="external") with Cost(tier="moderate") with Timeout(minutes=15)`.
Docstring: *"World choropleth of HIV/AIDS over time with a category dropdown + a
year slider (2000-2024)."* Workflow `WorldHIVMap`. Handler
`_wrap(build_world_hiv, "BuildWorldHIVMap")`.

## Cache / output

`storage.maps_root()/world-hiv/index.html`. `detail` = `"<N> countries with HIV
data (2000–2024)"`. Reads Natural Earth over HTTP.

## Gotchas & notes

- **`BROWSER_UA` is required** for the UNAIDS download — the default `UA` gets a 403.
- **Two units on one map.** Rate (infections/1,000) and prevalence (%) are different
  quantities; each series' own `unit` drives its legend so they aren't conflated.
- **Sparse KP series are expected** — many country-years are grey because the survey
  wasn't run, not because of a join miss.

## Related specs

- [hiv-transmission](hiv-transmission.md) — the per-country gay/straight split
  (Europe ECDC + US AtlasPlus) the world map can't do.
- [world-ncd](world-ncd.md) — the static world burden map (also carries HIV
  prevalence).
- [rendering](rendering.md) — the time-slider renderer with per-series units/scales.
- [storage-and-geometry](storage-and-geometry.md) · [domain-package](domain-package.md).
