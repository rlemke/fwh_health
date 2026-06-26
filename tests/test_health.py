"""Offline tests for the health domain — package wiring + pure rendering.

The build_* functions hit external APIs (CDC/WHO/OWID) so they're exercised by
the live FFL workflows, not here. These tests pin the parts that must not drift:
the domain entry point, the facet/handler dispatch wiring, the choropleth
renderer, and the storage path layout.
"""
from __future__ import annotations


def test_domain_package():
    import health
    assert health.domain.name == "health"
    assert (health.domain.ffl_dir / "health.ffl").exists()


def test_handler_dispatch_covers_all_facets():
    from health.handlers import health_handlers as h
    facets = set(h._DISPATCH)
    assert facets == {
        "health.maps.BuildUSMortalityMap",
        "health.maps.BuildUSPrevalenceMap",
        "health.maps.BuildWorldNCDMap",
    }
    # the RegistryRunner entrypoint resolves each facet
    for f in facets:
        assert callable(h._DISPATCH[f])


def test_choropleth_renders_self_contained_html():
    from health import choropleth
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
         "properties": {"name": "Testland", "m_a": 5.0, "m_b": None}}]}
    html = choropleth.render(fc, [{"key": "m_a", "label": "A — x"}, {"key": "m_b", "label": "B — y"}],
                             title="T", subtitle="s", attribution_html="attr",
                             center=[0, 0], zoom=2)
    assert "maplibre-gl" in html and "Testland" in html and "LAYER" not in html
    assert html.strip().startswith("<!DOCTYPE html>")


def test_storage_paths_remote_and_local(monkeypatch):
    from health import storage
    monkeypatch.setenv("AFL_DATA_ROOT", "s3://afl-cache")
    assert storage.maps_root() == "s3://afl-cache/cache/health/maps"
    assert storage.census_geom("output/tiger/state/us_state.geojson") == \
        "s3://afl-cache/cache/census-us/output/tiger/state/us_state.geojson"
    assert storage.is_remote("s3://x") and not storage.is_remote("/tmp/x")
