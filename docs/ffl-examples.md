# FFL Examples — `health`

Every numbered scenario is a **complete, compilable FFL file**. Copy one into
`my.ffl` and run it:

```bash
fw ffl run --primary my.ffl \
  --library ~/fw_handlers/fwh_health/src/health/ffl/health.ffl \
  --workflow my.health.<WorkflowName>
```

A runner serving the `health` namespace must be up
(`fw runner start --domain health`). Every block below is compile-checked against
`src/health/ffl/health.ffl`.

New to the language? Start with the
[FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md)
and the [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical).

---

## The facets at a glance

Twelve map facets, each taking **no parameters** and returning the same shape
`(region, html_path, feature_count, detail)` — each wrapped by a same-named
workflow in `health.workflows`. A uniform return shape is what makes them trivially
composable: any of them can be dropped into the examples below by name.

| Facet (`health.maps.…`) | Map |
|---|---|
| `BuildUSMortalityMap` | US state age-adjusted death rates (CDC NCHS) |
| `BuildUSPrevalenceMap` | US county adult prevalence (CDC PLACES) |
| `BuildWorldNCDMap` | World non-communicable-disease burden (WHO / World Bank) |
| `BuildWorldHIVMap` | World HIV/AIDS, category dropdown + year slider |
| `BuildEuropeHIVTransmissionMap` | Europe HIV by transmission route (ECDC) |
| `BuildUSHIVTransmissionMap` | US HIV by transmission category (CDC AtlasPlus) |
| `BuildUSAutismMap` | US autism identification in schools (IDEA §618) |
| `BuildUSRespiratoryMap` | COVID / flu / RSV admission rates (CDC NHSN) |
| `BuildUSHospitalStrainMap` | Inpatient + ICU occupancy (CDC NHSN) |
| `BuildUSICUSeverityMap` | Share of hospitalized patients in ICU (CDC NHSN) |
| `BuildUSPedVsAdultMap` | Pediatric vs adult admissions (CDC NHSN) |
| `BuildUSTripledemicMap` | Combined COVID+flu+RSV admissions (CDC NHSN) |

Each is an `event facet` — it runs in a handler on a runner, not in the compiler —
and carries `with Effect(kind = "external")` / `with Cost(tier = "moderate")`, which
is what `fw_capabilities(effect=…, max_cost=…)` filters on.

---

## 1. Run what ships — no FFL to write

```bash
fw ffl seed --include health

fw ffl run --workflow health.workflows.USMortalityMap   --task-list health
fw ffl run --workflow health.workflows.WorldNCDMap      --task-list health
```

Write FFL when you want a different *shape* of run — several maps in one
submission, error handling that keeps the rest going, or publishing the family in
one commit.

## 2. The smallest workflow you can write

Every FFL workflow needs a `namespace`, a `use` per namespace it calls into, and a
`yield` back to itself.

```ffl
namespace my.health {

    use health.maps

    /** Build one map. */
    workflow MyMortalityMap() => (html_path: String, features: Int) andThen {

        map = health.maps.BuildUSMortalityMap()

        yield MyMortalityMap(html_path = map.html_path, features = map.feature_count)
    }
}
```

Rules visible above: `=>` sits on the **same line** as the closing `)` of the
parameter list; references are always `step.field` (never a bare step name); a
workflow ends by yielding to itself.

## 3. Build a whole family in one run — parallelism for free

Steps that reference nothing from each other are dispatched **concurrently**: five
runners can render five maps at once. You never write "in parallel" — you write
the dependencies (here, none) and the runtime derives the schedule.

```ffl
namespace my.health {

    use health.maps

    /** The NHSN respiratory family — five maps, rendered concurrently. */
    workflow RespiratoryFamily() => (built: Int, first: String) andThen {

        resp = health.maps.BuildUSRespiratoryMap()
        strain = health.maps.BuildUSHospitalStrainMap()
        icu = health.maps.BuildUSICUSeverityMap()
        ped = health.maps.BuildUSPedVsAdultMap()
        tri = health.maps.BuildUSTripledemicMap()

        yield RespiratoryFamily(built = 5, first = resp.html_path)
    }
}
```

## 4. Keep going when one source is down — `catch`

`catch` fires when its step errors after retries are exhausted. Public-health
sources go down independently, so catch each one and let the rest of the family
finish.

```ffl
namespace my.health {

    use health.maps

    /** Best-effort family build: a dead CDC endpoint doesn't sink the run. */
    workflow BestEffortFamily() => (status: String, html_path: String) andThen {

        resp = health.maps.BuildUSRespiratoryMap() catch {
            yield BestEffortFamily(status = "respiratory_failed", html_path = "")
        }

        strain = health.maps.BuildUSHospitalStrainMap() catch {
            yield BestEffortFamily(status = "strain_failed", html_path = "")
        }

        yield BestEffortFamily(status = "completed", html_path = resp.html_path)
    }
}
```

## 5. Call-time mixins — timeouts and retries

Each facet ships `with Timeout(minutes = 15)`. The **call site** can override for
one particular use — the PLACES county map is the heavy one.

```ffl
namespace my.health {

    use health.maps

    /** The county prevalence map moves a lot of geometry — give it room. */
    workflow PatientPrevalenceMap() => (html_path: String) andThen {

        map = health.maps.BuildUSPrevalenceMap() with Timeout(minutes = 60) with Retry(maxAttempts = 3, backoffSeconds = 90)

        yield PatientPrevalenceMap(html_path = map.html_path)
    }
}
```

## 6. Branch on a result — `when`

A `when` block hangs off the step it inspects: inside a case `$` is that step and
`$$` reaches the workflow's parameters. Every `when` needs a default case, last,
and conditions must be real `Boolean`s (no truthy coercion).

```ffl
namespace my.health {

    use health.maps

    /** A US state map should have ~51 features — flag a thin join. */
    workflow VerifiedStateMap(min_features: Int = 50) => (status: String, html_path: String) andThen {

        map = health.maps.BuildUSMortalityMap() andThen when {
            case $.feature_count >= $$.min_features => {
                yield VerifiedStateMap(status = "complete", html_path = $.html_path)
            }
            case _ => {
                yield VerifiedStateMap(status = "sparse_join", html_path = $.html_path)
            }
        }
    }
}
```

## 7. Reuse the shipped workflows

Workflows compose like facets — wrap them rather than forking them.

```ffl
namespace my.health {

    use health.workflows

    /** Chain two shipped workflows and summarise. */
    workflow TwoMaps() => (headline: String) andThen {

        us = health.workflows.USMortalityMap()
        world = health.workflows.WorldNCDMap()

        yield TwoMaps(headline = "built: " ++ us.status ++ " / " ++ world.status)
    }
}
```

## 8. Compose across domains — publish the family in one commit

Facets from different domains compose in one workflow as long as some runner in
the fleet serves each namespace. `census.Publish` is the generic publisher the map
domains share; one call can push several prefixes in a single commit.

```ffl
namespace my.health {

    use health.maps
    use census.Publish

    /** Render two maps, then publish both in one commit. */
    workflow BuildAndPublish(repo: String = "rlemke/facetwork-maps") => (pages_url: String, files: Long) andThen {

        us = health.maps.BuildUSMortalityMap()
        world = health.maps.BuildWorldNCDMap()

        published = census.Publish.PublishWebBundle(
            repo = $.repo,
            prefixes = ["health/maps/us_mortality", "health/maps/world_ncd"],
            dests = ["health/us-mortality", "health/world-ncd"],
            labels = ["US disease mortality", "World NCD burden"],
            landing_title = "Facetwork maps")

        yield BuildAndPublish(pages_url = published.pages_url, files = published.file_count)
    }
}
```

Compile that one with `--library ~/fw_handlers/fwh_census_us/src/census_us/ffl/census.ffl`
as well.

---

## Cheat sheet

| You want to… | Write |
|---|---|
| Read a workflow/step parameter | `$.name` (`$$.name` one level out) |
| Read a previous step's result | `stepname.field` |
| Run steps in parallel | write them with no reference between them |
| Force an order | reference a field of the first from the second |
| More time / retries for one call | `… with Timeout(minutes = 60) with Retry(maxAttempts = 3, backoffSeconds = 90)` |
| Handle a step failure | `step = Facet(…) catch { yield … }` |
| Branch | `step = Facet(…) andThen when { case <bool> => { … } case _ => { … } }` |
| Fan out over a list | `workflow W(items: Json) … andThen foreach i in $.items { … }` |
| Concatenate strings | `a ++ b` |

**Validate before you run:** `afl my.ffl --check` or MCP `fw_validate`. Every error
carries a `rule_id` — fetch `fw://docs/rules/{rule_id}` for a wrong/right pair.

## See also

- [`docs/README.md`](README.md) — per-feature specs, one per map family
- [FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md) ·
  [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical) ·
  [relative `$`-scoping](https://github.com/rlemke/facetwork/blob/main/docs/architecture/ffl-relative-scoping.md)
- `src/health/ffl/health.ffl` — the source of truth for every signature above
