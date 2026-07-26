<!-- SPEC TEMPLATE — every docs/<feature>.md follows this shape so the set reads
consistently. Delete this comment in real specs. Keep sections in this order;
omit a section only if it genuinely does not apply (say so in one line rather
than dropping the heading silently). Ground every claim in the actual FFL
docstrings / handler code / renderers — do not invent behaviour. -->

# <Feature Name>

**Namespace(s):** `health.maps` / `health.workflows` ·
**FFL:** `src/health/ffl/health.ffl` ·
**Builder:** `src/health/_lib.py` (`build_<name>` + its `_fetch_*` helpers) ·
**Renderer:** `src/health/choropleth.py` (static) / `src/health/choropleth_time.py` (time slider) ·
**Storage:** `src/health/storage.py`

## Overview
One or two paragraphs: what this map answers, its geographic scope (US state /
US county / world / Europe), and where it sits in the pipeline
(fetch open data → join geometry → render choropleth → write HTML).

## How it works
The data flow, step by step. Name the concrete `_fetch_*` helpers, the source
endpoint(s), the join key onto geometry, the shape of the data at each stage
(source JSON/CSV → `{code: value}` dict → GeoJSON FeatureCollection → HTML), and
the metric/series keys the renderer sees.

## Fan-out
Does it fan out across the fleet? These maps are **single-task builders** (one
`build_*` per facet, no `foreach`) — say so and why (each map is one atomic
fetch+render; fleet parallelism is one map per runner, not per feature).

## Data & fields
The metrics/series it renders and their real property keys (`m_cancer`,
`covid_2024-01`, `tx_msm`, …), the source dataset(s) and dataset ids, the join
key onto geometry (state `NAME`/`STUSPS`/`STATEFP`, county `GEOID`, country
`ISO_A3`/`ISO_A2`), units, and what is **missing / grey** and why (the honest-scope
caveat this map carries in its note).

## External libraries / binaries
Every non-stdlib dependency this feature relies on and what for. For this domain
that is almost always just **`requests`** (HTTP fetch) and **`shapely`** (geometry
simplify + `mapping`/`shape`) — both **pip**, no binaries. Note any per-source
header quirk (browser User-Agent, JSON POST body) or undocumented backend.

## Facets & workflows
The event facet + its workflow, with signatures and the one-line purpose from the
FFL docstring. All map facets are **event** facets (need the `health` handler),
carry `with Effect(kind="external")` + `with Cost(tier="moderate")` +
`with Timeout(minutes=…)`, and return `(region, html_path, feature_count, detail)`.

## Cache / output
The output path (`storage.maps_root()/<name>/index.html`) — local
`<root>/health-maps/<name>/` vs remote `<root>/cache/health/maps/<name>/` on the
fleet (MinIO) — and the artifact (a self-contained MapLibre HTML map). Note the
geometry it **reads** (census TIGER / Natural Earth) and from where.

## Gotchas & notes
Rate limits, undocumented endpoints, header requirements, data-availability
caveats, sensitivity (identification vs diagnosis, counts vs rates), and anything
a future maintainer would trip on (schema drift, id drift, suppressed cells).

## Related specs
Links to the specs this feature composes with (the renderer, storage/geometry,
sibling maps).
