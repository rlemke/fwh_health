"""Backend-aware paths for the health cache + outputs.

On the fleet (``AFL_STORAGE=s3`` / ``AFL_DATA_ROOT=s3://afl-cache``) the rendered
map HTML lands in the shared MinIO object store under
``$AFL_DATA_ROOT/cache/health/maps/<name>/index.html`` — the same path the maps
are published from. A thin wrapper over ``facetwork.runtime.storage`` (the shape
census-us / conflict use), so terminal use and fleet runs share one layout.
"""

from __future__ import annotations

import os
import tempfile

from facetwork.config import get_output_base
from facetwork.runtime import storage as _fws


def is_remote(path: str) -> bool:
    return "://" in (path or "")


def data_root() -> str:
    return os.environ.get("AFL_DATA_ROOT") or get_output_base()


def join(*parts: str) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    base = parts[0].rstrip("/")
    rest = [p.strip("/") for p in parts[1:]]
    return "/".join([base, *[p for p in rest if p]])


def maps_root() -> str:
    """Where rendered map bundles live: <root>/cache/health/maps."""
    r = data_root()
    return join(r, "cache", "health", "maps") if is_remote(r) else join(r, "health-maps")


def census_geom(rel: str) -> str:
    """Path to a census-domain TIGER GeoJSON we reuse, e.g.
    ``output/tiger/state/us_state.geojson``. Lives under the census cache prefix
    on the same backend."""
    r = data_root()
    if is_remote(r):
        return join(r, "cache", "census-us", rel)
    return join(r, "census-us-output", rel.split("output/", 1)[-1])


def exists(path: str) -> bool:
    return _fws.get_storage_backend(path).exists(path)


def read_bytes(path: str) -> bytes:
    """Read a (possibly remote) artifact's bytes via the storage backend."""
    if not is_remote(path):
        with open(path, "rb") as f:
            return f.read()
    local = _fws.localize(path)
    with open(local, "rb") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    """Write text to a local path or s3:// URI (atomic stage+finalize for remote)."""
    data = text.encode("utf-8")
    if not is_remote(path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return
    fd, tmp = tempfile.mkstemp(suffix="_" + os.path.basename(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        with open(tmp, "rb") as src, _fws.get_storage_backend(path).open(path, "wb") as dst:
            dst.write(src.read())
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
