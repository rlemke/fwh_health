# fwh_health — disease-burden maps (Facetwork domain)

Choropleth maps of cancer / diabetes / Alzheimer's / stroke burden, built from
open public-health data and published to
[facetwork-maps](https://rlemke.github.io/facetwork-maps/health/index.html).

## Maps

| Map | Source | Metrics |
|-----|--------|---------|
| [US mortality by state](https://rlemke.github.io/facetwork-maps/health/us-mortality/) | CDC NCHS | age-adjusted death rates — cancer, stroke, diabetes, Alzheimer's |
| [US prevalence by county](https://rlemke.github.io/facetwork-maps/health/us-prevalence/) | CDC PLACES | adult prevalence — cancer, diabetes, stroke (2,956 counties) |
| [World NCD burden](https://rlemke.github.io/facetwork-maps/health/world-ncd/) | WHO GHO + World Bank/OWID | diabetes prevalence, premature-NCD mortality, NCD mortality rate |

Geometry is reused from the Facetwork ecosystem: US Census TIGER state/county
GeoJSON (cached in MinIO by the `census-us` domain) and Natural Earth country
polygons.

## Data-availability constraints (honest scope)

Public-health data is fragmented; the maps reflect what's openly redistributable:

- **US is well-covered.** County-level *prevalence* (cases) for cancer/diabetes/
  stroke from CDC PLACES; state-level *deaths* for all four causes incl.
  Alzheimer's from NCHS. County-level deaths are suppressed for small counties;
  **Alzheimer's has no prevalence estimate anywhere**, so it appears deaths-only.
- **Worldwide is thin.** Current, openly-redistributable, country-level data for
  these specific diseases barely exists — IHME/OWID cause series are license-
  blocked, WHO's cause-specific death series are empty or frozen at 2004, and
  IARC's cancer API isn't cleanly fetchable. The world map therefore shows the
  **non-communicable-disease burden** (diabetes prevalence + WHO premature-NCD
  and NCD mortality), which covers the cancer / cardiovascular / diabetes space
  with current data, rather than per-cause cases.

## Build — FFL workflows on the runtime

This is a standard Facetwork **domain package** (`facetwork.domains` entry point,
`DomainPackage`), so the maps are first-class FFL workflows discovered + seeded by
the runner. Each fetches → joins geometry → renders a MapLibre choropleth (shared
`health/choropleth.py`) → writes HTML to the configured backend (MinIO on the
fleet, `cache/health/maps/<name>/`):

```bash
fw ffl run --workflow health.workflows.USMortalityMap   --task-list health
fw ffl run --workflow health.workflows.USPrevalenceMap  --task-list health
fw ffl run --workflow health.workflows.WorldNCDMap      --task-list health
```

Facets: `health.maps.BuildUSMortalityMap` / `BuildUSPrevalenceMap` /
`BuildWorldNCDMap`. The rendered HTML is then published to the `health/` section
of facetwork-maps (each carries its source attribution + a link back).

Install like any domain: `pip install -e .` (or `fw install domain health`); the
runner auto-discovers it via the entry point.
