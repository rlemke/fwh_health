# fwh_health — disease-burden maps (Facetwork domain)

Choropleth maps of chronic- and infectious-disease burden (cancer / diabetes /
Alzheimer's / stroke plus COVID / flu / HIV / measles), built from open
public-health data and published to
[facetwork-maps](https://rlemke.github.io/facetwork-maps/health/index.html).
Each map carries a metric dropdown and an amber **"where data is missing"** note
explaining the grey (no-data) areas.

## Maps

| Map | Source | Metrics |
|-----|--------|---------|
| [US mortality by state](https://rlemke.github.io/facetwork-maps/health/us-mortality/) | CDC NCHS + CDC COVID + CDC FluView | age-adjusted death rates (cancer, stroke, diabetes, Alzheimer's) + COVID deaths/100k + peak flu (ILINet) activity |
| [US prevalence by county](https://rlemke.github.io/facetwork-maps/health/us-prevalence/) | CDC PLACES | adult prevalence — cancer, diabetes, stroke (2,956 counties) |
| [World NCD + infectious burden](https://rlemke.github.io/facetwork-maps/health/world-ncd/) | WHO GHO + World Bank/OWID | diabetes prevalence, premature-NCD + NCD mortality, COVID deaths/100k, HIV prevalence, measles incidence |

Geometry is reused from the Facetwork ecosystem: US Census TIGER state/county
GeoJSON (cached in MinIO by the `census-us` domain) and Natural Earth country
polygons.

## Data-availability constraints (honest scope)

Public-health data is fragmented; the maps reflect what's openly redistributable:

- **US is well-covered.** County-level *prevalence* (cases) for cancer/diabetes/
  stroke from CDC PLACES; state-level *deaths* for all four chronic causes incl.
  Alzheimer's from NCHS, plus state COVID deaths/100k (CDC) and peak flu (ILINet)
  activity (CDC FluView). County-level deaths are suppressed for small counties;
  **Alzheimer's has no prevalence estimate anywhere**, so it appears deaths-only.
  In the **county prevalence** map, **Kentucky & Pennsylvania are blank** for all
  three conditions — CDC PLACES (2025 release) models them from 2023 BRFSS, and
  KY & PA have no usable 2023 BRFSS sample. This is stated in the map's note.
- **Worldwide is thin.** Current, openly-redistributable, country-level data for
  these specific diseases barely exists — IHME/OWID cause series are license-
  blocked, WHO's cause-specific death series are empty or frozen at 2004, and
  IARC's cancer API isn't cleanly fetchable. The world map therefore shows the
  **non-communicable-disease burden** (diabetes prevalence + WHO premature-NCD
  and NCD mortality) **plus the infectious metrics that *are* openly current** —
  COVID deaths/100k (WHO), HIV prevalence and measles incidence (WHO GHO) —
  rather than per-cause cancer/stroke cases. Measles/smallpox/ebola/STDs were
  requested but most lack a clean current country-level open series, so the map
  carries only the ones with redistributable data and the note says so.

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
