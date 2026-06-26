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

## Build

Each map is a self-contained builder that fetches → joins geometry → renders a
MapLibre choropleth (shared `choropleth.py`) → writes HTML to the fleet object
store (MinIO, `s3://afl-cache/cache/health/maps/<name>/`):

```bash
AFL... python build_us_health_deaths.py       # US state mortality (NCHS)
python build_us_county_prevalence.py          # US county prevalence (PLACES)
python build_world_health.py                  # world NCD burden (WHO + OWID)
```

Then published to the `health/` section of facetwork-maps (HTML carries the
source attribution + a link back to the workflow).

## Status

The maps are live. Promoting these builders into first-class FFL
`health.*` facets + workflows on the runtime (like the other `fwh_*` domains —
entry point, `DomainPackage`, fleet deploy) is the remaining formalization step.
