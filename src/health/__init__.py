"""Health domain — Facetwork workflows + handlers for disease-burden maps.

Builds choropleths from open public-health data: three static metric-dropdown
maps (US state mortality — CDC NCHS, US county prevalence — CDC PLACES, world NCD
burden — WHO GHO / World Bank) plus a five-map NHSN respiratory family with a
month slider (COVID/flu/RSV admissions, bed strain, ICU severity, children-vs-
adults, "tripledemic"). Discovered by the Facetwork runner via the
``facetwork.domains`` entry point in pyproject.toml::

    [project.entry-points."facetwork.domains"]
    health = "health:domain"
"""

from __future__ import annotations

from pathlib import Path

from facetwork.domains import DomainPackage

from .handlers import register_all_registry_handlers

domain = DomainPackage(
    name="health",
    ffl_dir=Path(__file__).parent / "ffl",
    register_handlers=register_all_registry_handlers,
)
