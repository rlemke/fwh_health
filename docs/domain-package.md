# Domain package, handler wiring & FFL workflows

**Namespace(s):** `health.maps` / `health.workflows` ·
**Package:** `src/health/__init__.py` (`domain`) ·
**Handlers:** `src/health/handlers/{__init__,health_handlers}.py` ·
**FFL:** `src/health/ffl/health.ffl` ·
**Tests:** `tests/test_health.py`

## Overview

This spec is the domain's **wiring and boundaries** document (the fwh_osm
`boundaries.md` analogue): how the `health` package is discovered by the runtime,
how each map facet is dispatched to a Python builder, how the FFL facets/workflows
relate to the handlers, and — honestly — where the repo's own test is **stale**.
Every map facet is a **thin** event facet: the FFL declares the capability surface,
the handler is a two-line wrapper over a `build_*` function in `_lib.py`.

## How it works

- **Discovery.** `pyproject.toml` declares
  `[project.entry-points."facetwork.domains"] health = "health:domain"`. `health.domain`
  is a `DomainPackage(name="health", ffl_dir=…/ffl, register_handlers=
  register_all_registry_handlers)`. The runner auto-loads it via the entry point
  (`fw runner start --domain health`, `fw ffl seed`).
- **FFL surface.** `health.ffl` declares **12** event facets in `namespace
  health.maps` and **12** matching one-step workflows in `namespace
  health.workflows` (each `use health.maps`, calls its facet, yields
  `(status="completed", html_path, detail)`).
- **Handler dispatch.** `health_handlers._DISPATCH` maps each
  `health.maps.Build*Map` facet name to `_wrap(build_*, label)`. `_wrap` calls the
  **zero-arg** builder, logs `res.detail -> res.html_path` via the optional
  `_step_log`, and returns `{region, html_path, feature_count, detail}` (re-raising
  on error with an error-level log — never a silent empty default). `handle(payload)`
  looks up `payload["_facet_name"]`; unknown facets raise `ValueError`.
- **Registration.** `register_handlers(runner)` registers every facet against
  `module_uri=file://…/health_handlers.py`, `entrypoint="handle"` (RegistryRunner);
  `register_poller(poller)` registers the same for the AgentPoller path.
  `handlers/__init__.py` exposes `register_all_registry_handlers` /
  `register_all_handlers`.

## Fan-out

Not applicable at the wiring layer. Each facet is a single-task builder (see the
per-map specs); the runtime fans out *maps across runners*, not features.

## Data & fields

The 12 facets and their builders (all in `_lib.py`):

| Facet (`health.maps.`) | Builder | Spec |
|---|---|---|
| `BuildUSMortalityMap` | `build_us_mortality` | [us-mortality](us-mortality.md) |
| `BuildUSPrevalenceMap` | `build_us_prevalence` | [us-prevalence](us-prevalence.md) |
| `BuildWorldNCDMap` | `build_world_ncd` | [world-ncd](world-ncd.md) |
| `BuildWorldHIVMap` | `build_world_hiv` | [world-hiv](world-hiv.md) |
| `BuildEuropeHIVTransmissionMap` | `build_europe_hiv_transmission` | [hiv-transmission](hiv-transmission.md) |
| `BuildUSHIVTransmissionMap` | `build_us_hiv_transmission` | [hiv-transmission](hiv-transmission.md) |
| `BuildUSAutismMap` | `build_us_autism` | [us-autism](us-autism.md) |
| `BuildUSRespiratoryMap` | `build_us_respiratory` | [respiratory-nhsn](respiratory-nhsn.md) |
| `BuildUSHospitalStrainMap` | `build_us_hospital_strain` | [respiratory-nhsn](respiratory-nhsn.md) |
| `BuildUSICUSeverityMap` | `build_us_icu_severity` | [respiratory-nhsn](respiratory-nhsn.md) |
| `BuildUSPedVsAdultMap` | `build_us_ped_vs_adult` | [respiratory-nhsn](respiratory-nhsn.md) |
| `BuildUSTripledemicMap` | `build_us_tripledemic` | [respiratory-nhsn](respiratory-nhsn.md) |

Every facet returns `(region: String, html_path: String, feature_count: Int, detail:
String)` and carries `with Effect(kind="external") with Cost(tier="moderate") with
Timeout(minutes=…)` (15 for all except `BuildUSPrevalenceMap` at 20). All are
**event** facets — there are no pure facets in this domain.

## External libraries / binaries

- **`facetwork.domains.DomainPackage`** — the entry-point contract.
- The handlers themselves import only from `.._lib`; the heavy deps (`requests`,
  `shapely`) live in `_lib.py`.

## Facets & workflows

All 12 workflows are structurally identical one-step pipelines, e.g.:

```
workflow USMortalityMap() => (status, html_path, detail) andThen {
    map = BuildUSMortalityMap()
    yield USMortalityMap(status = "completed", html_path = map.html_path, detail = map.detail)
}
```

Run them with `fw ffl run --workflow health.workflows.<Name> --task-list health`
(the task list is the `health.*` namespace).

## Cache / output

No output of its own; each dispatched builder writes via `storage` (see
[storage-and-geometry](storage-and-geometry.md)).

## Gotchas & notes

- **The dispatch-coverage test is STALE — flagged honestly.**
  `tests/test_health.py::test_handler_dispatch_covers_all_facets` asserts
  `set(_DISPATCH) == {BuildUSMortalityMap, BuildUSPrevalenceMap, BuildWorldNCDMap}`
  — only **3** facets. The code has since grown to **12** facets in `_DISPATCH`
  (HIV world/Europe/US, autism, and the five NHSN maps were added), so this equality
  assertion is **out of date and would fail** as written. The other three tests
  (`test_domain_package`, `test_choropleth_renders_self_contained_html`,
  `test_storage_paths_remote_and_local`) are current. This is a test bug, not a
  wiring bug — the FFL, `_DISPATCH`, and builders are all consistent at 12. *(Docs
  are read-only; this is reported, not fixed.)*
- **The repo README lists 8 maps**, but the FFL/handlers expose **12** facets — the
  HIV (world/Europe/US) and autism maps aren't in the README's map table yet. The
  FFL docstrings + `_DISPATCH` are the source of truth for what exists.
- **Builders take no parameters.** Every facet is zero-arg; all configuration
  (sources, years, columns) is baked into `_lib.py` constants. There is no
  per-run parameterization surface.
- **Errors are never swallowed.** `_wrap` logs and re-raises, so a failed fetch
  surfaces as a failed step (correct for retry/repair), not a blank map.

## Related specs

- Every per-map spec (linked in the table above).
- [rendering](rendering.md) — the renderers the builders call.
- [storage-and-geometry](storage-and-geometry.md) — discovery of reused geometry +
  output paths.
