"""Backend-aware paths for the health domain.

⚠️ A THIN SHIM over ``facetwork.domains.storage``. This module was one of 21
near-copies across the fwh_* repos; the shared layer owns the behaviour now and
this file keeps the import path, the public names, and anything genuinely
specific to health.

⚠️ The arguments below pin where this domain's data ALREADY sits in the object
store. They are not style — changing one orphans that data rather than moving
it — and they were verified against the previous module across local, s3:// and
hdfs:// before the switch.
"""
from __future__ import annotations
import os
import tempfile
from facetwork.config import get_output_base
from facetwork.runtime import storage as _fws

from facetwork.domains.storage import domain_storage, is_remote, join  # noqa: F401

_S = domain_storage("health")


def data_root() -> str:
    return _S.data_root()


def maps_root() -> str:
    return _S.maps_root()


def exists(path: str) -> bool:
    return _S.exists(path)


def read_bytes(path: str) -> bytes:
    return _S.read_bytes(path)


def write_text(path: str, body: str) -> None:
    return _S.write_text(path, body)


def open_read(path: str, mode: str = "r", **kw):
    return _S.open_read(path, mode, **kw)


def open_write(path: str, mode: str = "w", **kw):
    return _S.open_write(path, mode, **kw)


def census_geom(rel: str) -> str:
    """Path to a census-domain TIGER GeoJSON we reuse, e.g.
    ``output/tiger/state/us_state.geojson``. Lives under the census cache prefix
    on the same backend."""
    r = data_root()
    if is_remote(r):
        return join(r, "cache", "census-us", rel)
    return join(r, "census-us-output", rel.split("output/", 1)[-1])
