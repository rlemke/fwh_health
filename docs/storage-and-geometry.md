# Storage backend & geometry reuse

**Namespace(s):** cross-cutting (no facet) ·
**Module:** `src/health/storage.py` ·
**Consumed by:** every `build_*` in `src/health/_lib.py`

## Overview

Two responsibilities sit in one small module: (1) resolve **where map HTML is
written** on whichever backend the fleet uses (local disk vs MinIO/S3), and (2)
resolve **where the reused geometry lives** — the census-us domain's TIGER GeoJSON
and (fetched live) Natural Earth. The health domain builds **no geometry of its
own**; it joins open health data onto polygons another domain already cached.

## How it works

`storage.py` is a thin wrapper over `facetwork.runtime.storage` (`_fws`) and
`facetwork.config.get_output_base`:

- **`data_root()`** = `FW_DATA_ROOT` or `get_output_base()`. `is_remote(path)` is
  simply `"://" in path`.
- **`maps_root()`** — output root for rendered bundles: remote
  `<root>/cache/health/maps`, local `<root>/health-maps`.
- **`census_geom(rel)`** — resolves a reused census-us TIGER artifact: remote
  `<root>/cache/census-us/<rel>`, local `<root>/census-us-output/<rel after
  "output/">`. E.g. `census_geom("output/tiger/state/us_state.geojson")`.
- **`read_bytes(path)`** — local `open`, or `_fws.localize(path)` then read for a
  remote URI.
- **`write_text(path, text)`** — local: `makedirs` + write; remote: **stage to a
  tempfile then finalize** into the backend via `_fws.get_storage_backend(path).open(...)`
  (object stores don't do partial writes — the atomic stage+finalize pattern the
  whole platform uses).
- **`exists(path)`** — `_fws.get_storage_backend(path).exists(path)` (used by
  [us-prevalence](us-prevalence.md) to skip absent per-state county files).

## Fan-out

Not applicable — path resolution + single read/write helpers.

## Data & fields

- **Geometry consumed (never produced):**
  - Census TIGER **state** `output/tiger/state/us_state.geojson` — used by every US
    map (join on `STUSPS` / `NAME` / `STATEFP`).
  - Census TIGER **county** `output/tiger/county/<FIPS>_county.geojson` per state —
    used by [us-prevalence](us-prevalence.md) (join on `GEOID`), iterated over
    `STATE_FIPS` (`01`–`56` + `72`).
  - **Natural Earth** `ne_110m_admin_0_countries.geojson` (`NE_URL`, `_lib.py`) —
    fetched **live over HTTP** by the world/Europe maps (join on `ISO_A3` / `ISO_A2`,
    with `-99` → `*_EH`/`ADM0_A3` fallbacks). Not routed through this module.
- **Output artifact:** one `index.html` per map under `maps_root()/<name>/`.

## External libraries / binaries

- **`facetwork.runtime.storage` / `facetwork.config`** — the platform storage
  backend + output-base config (the same layer census-us / conflict use).
- **`os` / `tempfile`** (stdlib) — local writes and the remote stage+finalize.
- No third-party deps here (`requests`/`shapely` live in `_lib.py`).

## Facets & workflows

None — plain module functions called from the handlers.

## Cache / output

This *is* the output/cache path layer. On the fleet (`FW_STORAGE=s3`,
`FW_DATA_ROOT=s3://afl-cache`) maps land in MinIO at
`s3://afl-cache/cache/health/maps/<name>/index.html` — the same path they're
published from; locally they land under `<root>/health-maps/<name>/`.

## Gotchas & notes

- **The census-us cache is a hard dependency.** Health reads TIGER GeoJSON census-us
  produced; if it isn't seeded on the same backend, US maps come back with few/no
  features (county files are skipped silently via `exists`; a missing state file
  would raise on `read_bytes`). Populate census-us first.
- **Remote writes must stage+finalize.** Don't switch `write_text` to a direct
  streaming write — object stores can't do partial writes, and a crash mid-write
  would leave a truncated `index.html`.
- **Natural Earth is fetched live, not cached** — the world/Europe maps depend on
  GitHub raw availability at build time (unlike the census-backed US maps).
- `test_storage_paths_remote_and_local` pins `maps_root()` and `census_geom(...)`
  for the `s3://afl-cache` root.

## Related specs

- [us-prevalence](us-prevalence.md) — the heaviest geometry consumer (per-state
  county files + `exists` guard).
- [rendering](rendering.md) — produces the HTML this module writes.
- [domain-package](domain-package.md) — how the maps are wired into the runtime.
