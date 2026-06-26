"""Event-facet handlers for the health domain — thin layers over ``_lib``."""

from __future__ import annotations

import os
from typing import Any

from .._lib import build_us_mortality, build_us_prevalence, build_world_ncd

MAPS = "health.maps"


def _wrap(fn, label):
    def handler(params: dict[str, Any]) -> dict[str, Any]:
        step_log = params.get("_step_log")
        try:
            res = fn()
            if step_log:
                step_log(f"{label}: {res.detail} -> {res.html_path}", level="success")
            return {"region": res.region, "html_path": res.html_path,
                    "feature_count": res.feature_count, "detail": res.detail}
        except Exception as exc:
            if step_log:
                step_log(f"{label}: {exc}", level="error")
            raise
    return handler


_DISPATCH: dict[str, Any] = {
    f"{MAPS}.BuildUSMortalityMap": _wrap(build_us_mortality, "BuildUSMortalityMap"),
    f"{MAPS}.BuildUSPrevalenceMap": _wrap(build_us_prevalence, "BuildUSPrevalenceMap"),
    f"{MAPS}.BuildWorldNCDMap": _wrap(build_world_ncd, "BuildWorldNCDMap"),
}


def handle(payload: dict) -> dict:
    facet = payload["_facet_name"]
    handler = _DISPATCH.get(facet)
    if handler is None:
        raise ValueError(f"Unknown facet: {facet}")
    return handler(payload)


def register_handlers(runner) -> None:
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
        )


def register_poller(poller) -> None:
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
