"""Health domain — Facetwork workflows + handlers for disease-burden maps.

Builds three choropleths (with metric dropdowns) from open public-health data:
US state mortality (CDC NCHS), US county prevalence (CDC PLACES), and a world
non-communicable-disease burden map (WHO GHO + World Bank). Discovered by the
Facetwork runner via the ``facetwork.domains`` entry point in pyproject.toml::

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
