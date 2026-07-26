# Choropleth Rendering — static + time-slider MapLibre

**Namespace(s):** cross-cutting (no facet) ·
**Renderers:** `src/health/choropleth.py` (`render`), `src/health/choropleth_time.py` (`render_timeseries`) ·
**Consumed by:** every `build_*` in `src/health/_lib.py`

## Overview

Every health map is one self-contained MapLibre HTML string produced by one of two
sibling renderers. There is no map server, no tile pipeline, no external JS bundle
beyond MapLibre GL from a CDN and a keyless CARTO raster basemap — the output works
from `file://`. This spec documents the two renderers as the shared visualization
layer the domain's maps all funnel through.

## How it works

Both take a GeoJSON FeatureCollection whose features carry numeric properties, plus
a list of selectable dimensions, and return a full `<!DOCTYPE html>` page.

- **`choropleth.render(fc, metrics, …)`** — the **static** renderer. `metrics` is
  `[{"key": "m_cancer", "label": "…"}]`; a `<select>` switches the fill between
  metric property keys. Used by [us-mortality](us-mortality.md),
  [us-prevalence](us-prevalence.md), [world-ncd](world-ncd.md).
- **`choropleth_time.render_timeseries(fc, series, months, …)`** — the
  **time-slider** renderer. `series` is `[{"key": "covid", "label": "…", "unit"?:
  "…"}]` and each feature carries one property per `<series>_<month>` **cell**. A
  series `<select>` picks the dimension; a range **slider** + **play/pause** button
  animates over `months` (which may be `YYYY-MM` months or `YYYY` year buckets).
  Used by the [respiratory-nhsn](respiratory-nhsn.md) family, [world-hiv](world-hiv.md),
  [hiv-transmission](hiv-transmission.md), [us-autism](us-autism.md).

Both use the same six-stop ramp `RAMP = ['#ffffcc','#c7e9b4','#7fcdbb','#41b6c4',
'#2c7fb8','#253494']` (light→dark) with `NODATA = '#e0e0e0'` grey, MapLibre GL
**4.7.1**, and the CARTO `light_all` basemap.

## Fan-out

Not applicable — pure in-process string rendering (no I/O, no tasks).

## Data & fields

Key rendering rules, grounded in the code:

- **Quantile breaks, deduped to strictly ascending.** `breaks(k)` samples quantiles
  (static `[0.1,0.27,0.45,0.63,0.81]`; time `[0.1,0.27,0.45,0.63,0.81,0.93]`) and
  drops equal adjacent values — because a discrete/skewed metric (e.g. flu activity
  0–13) otherwise produces equal breaks, which makes MapLibre's `step` expression
  invalid and the fill stops updating. This is a real bug fix, per the code comment.
- **Fixed scale per series (time only).** `render_timeseries` computes each series'
  breaks **once across all months** (cached in `BREAKS`), so the slider shows a wave
  rise/fall against a stable legend instead of a per-frame re-quantise. This is the
  single most important difference between the two renderers.
- **Missing = grey.** The `step` expression coalesces a missing value to `-1` → the
  `NODATA` colour; real values (`≥ 0`) span the ramp.
- **Per-series units (time only).** A series may carry its own `unit`
  (`unitFor(s)`), so a map mixing a rate and a percentage (e.g. [world-hiv](world-hiv.md))
  labels each legend correctly; otherwise the map-wide `value_label` is used.
- **"About this data" note.** Both accept `note` + `note_popup`: `note_popup=True`
  renders a dismissible modal (opens on load, reopened via an ℹ️ button); otherwise
  an always-on amber box. The static box reads *"Where data is missing (grey):"*,
  the time box *"Reading this map:"*.
- Popups on click list every metric/series value for the clicked feature (at the
  current month for the time map).

## External libraries / binaries

- **None server-side beyond stdlib `json`.** All map behaviour is inlined JS. The
  browser loads **MapLibre GL 4.7.1** (unpkg CDN) and CARTO raster tiles (no API
  key). No `folium`, no `shapely` here — geometry is already simplified upstream in
  `_lib.py`.

## Facets & workflows

None — these are plain Python functions, not facets. They are called from the
`build_*` handlers, never dispatched directly.

## Cache / output

No I/O of their own: they return an HTML **string**. The `build_*` caller writes it
via `storage.write_text(...)` (see [storage-and-geometry](storage-and-geometry.md)).

## Gotchas & notes

- **Don't remove the strictly-ascending break dedup** — it silently breaks the fill
  for discrete metrics.
- **Feature properties must be pre-simplified.** The renderers embed the whole
  FeatureCollection inline; `_lib.py` does `shapely.simplify` + coordinate rounding
  first so the HTML stays a reasonable size. Rendering raw geometry would bloat the
  page.
- **Series keys may contain `_`.** Cell keys are `<series>_<month>`; upstream code
  that splits them must split the **month** off as the last segment (see the NHSN
  engine), not the first.
- `test_choropleth_renders_self_contained_html` pins that the output is
  self-contained (`"maplibre-gl" in html`), starts with `<!DOCTYPE html>`, and
  contains the feature name.

## Related specs

- All map specs consume these renderers — see [respiratory-nhsn](respiratory-nhsn.md)
  (time) and [us-mortality](us-mortality.md) (static) as the canonical callers.
- [storage-and-geometry](storage-and-geometry.md) — where the returned HTML is written.
