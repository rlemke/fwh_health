# fwh_health — Feature Specifications

This directory holds one **spec per health map (or shared capability)**. Each
document follows a common shape ([`SPEC_TEMPLATE.md`](SPEC_TEMPLATE.md)) and states,
for that feature: how it works (fetch → join geometry → render → write), whether it
**fans out** (these maps are single-task builders), the **data & fields** it renders
and what is missing/grey and why, the **external libraries** it uses (almost always
just `requests` + `shapely`), its **facets & workflows**, and its **cache/output**.
Claims are grounded in the FFL `/** … */` docstrings, the builders in
`src/health/_lib.py`, and the renderers — the source of truth for each facet remains
its FFL docstring; these specs are the feature-level narrative over them.

**Start here:** [**NHSN Respiratory Family**](respiratory-nhsn.md) — the flagship:
**five** published US-state time-slider maps (COVID / flu / RSV) built from **one**
CDC source through **one** generic fetch+render engine (`_fetch_nhsn_series` +
`_nhsn_map`). The clearest example of the domain's "one engine, many maps" shape.

## Cross-cutting

| Spec | What it covers |
|------|----------------|
| [rendering.md](rendering.md) | The two MapLibre renderers — static (`choropleth.render`, metric dropdown) and time-slider (`choropleth_time.render_timeseries`, fixed per-series scale + play). Ramp, quantile-break dedup, "About this data" note, no-data grey. |
| [storage-and-geometry.md](storage-and-geometry.md) | Backend-aware output paths (local `health-maps/` vs MinIO `cache/health/maps/`), reused census TIGER + Natural Earth geometry, remote stage+finalize writes. |
| [domain-package.md](domain-package.md) | Discovery (`facetwork.domains` entry point), facet→builder dispatch (`_DISPATCH`), the 12 FFL facets/workflows, and the **stale 3-facet coverage test** flagged honestly. |

## US chronic-disease maps (static)

| Spec | What it covers |
|------|----------------|
| [us-mortality.md](us-mortality.md) | US **state** age-adjusted death rates — cancer / stroke / diabetes / Alzheimer's + COVID/flu overlays (CDC NCHS + COVID + FluView). |
| [us-prevalence.md](us-prevalence.md) | US **county** adult prevalence — cancer / diabetes / stroke (CDC PLACES, ~2,956 counties); the finest-grained map. |

## World maps

| Spec | What it covers |
|------|----------------|
| [world-ncd.md](world-ncd.md) | World country NCD burden (diabetes / premature-NCD / NCD mortality) + COVID / HIV / measles overlays (WHO GHO + OWID/World Bank), joined on ISO codes. |
| [world-hiv.md](world-hiv.md) | World HIV/AIDS **over time** (2000–2024) — new-infection rate by sex + prevalence among key populations (WHO SDGHIV + UNAIDS KP Atlas), year slider. |

## HIV by transmission route (time slider)

| Spec | What it covers |
|------|----------------|
| [hiv-transmission.md](hiv-transmission.md) | The per-geography gay/straight split the world map can't do — Europe per country (ECDC Surveillance Atlas) and the US per state (CDC AtlasPlus undocumented backend), route dropdown + year slider. |

## Other US time-series maps

| Spec | What it covers |
|------|----------------|
| [respiratory-nhsn.md](respiratory-nhsn.md) | **Flagship.** Five US-state respiratory-virus maps (admissions / bed strain / ICU severity / children-vs-adults / tripledemic) off the shared NHSN HRD engine, month slider (~5 yrs). |
| [us-autism.md](us-autism.md) | US-state autism **identification in schools** over 20 years (IDEA §618 Part B Child Count) — count + per-1,000 special-ed, header-based parser for 20 years of schema drift. |

---

*See also the repo [`README.md`](../README.md) (map gallery + honest-scope notes)
and each facet's FFL `/** … */` docstring in
[`src/health/ffl/health.ffl`](../src/health/ffl/health.ffl) — the source of truth.
The live/queryable interface is the MCP `fw_capabilities` / `fw_describe_handler`
tools.*
