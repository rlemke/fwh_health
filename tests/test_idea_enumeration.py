"""IDEA child-count CSVs are enumerated through data.ed.gov's PDPS API.

data.ed.gov retired its CKAN API in 2026 (/api/3/action/* serves the SPA shell)
and gave every dataset a new id, one dataset per year. The download URLs
survived, so the map is unchanged once enumeration follows the new catalog.
"""
import sys

import pytest

sys.path.insert(0, "src")
from health import _lib

ORG = "b3NlcA"


def _api(pages):
    def get(path, **params):
        if path == "/organizations":
            return {"data": [{"id": "x", "name": "Other"}, {"id": ORG, "name": _lib.IDEA_ORG_NAME}]}
        if path == f"/organizations/{ORG}/datasets":
            return pages[params.get("cursor")]
        return {"data": DISTS[path.split("/")[2]]}
    return get


DISTS = {
    "a": [{"DownloadURL": "https://h/download/bchildcount2005.csv"},
          {"DownloadURL": "https://h/download/benvironment2005.csv"}],
    "b": [{"DownloadURL": "https://h/download/bchildcountandedenvironments2016.csv"}],
    "c": [{"DownloadURL": "https://h/download/bchildcountandedenvironment2023-24.csv"}],
    "lea": [{"DownloadURL": "https://h/download/bchildcountdisabilitycategorylea2022-23.csv"}],
    "static": [{"DownloadURL": "https://h/download/1617-bchildcountandedenvironment-1.xlsx"}],
}


def test_enumerates_every_year_across_pages_and_title_variants(monkeypatch):
    pages = {
        None: {"data": [
            {"Identifier": "a", "Title": "2005 State Level Data File and Supporting Documentation (Part B Child Count & Educational Environments)"},
            {"Identifier": "b", "Title": "2016 State Level Data File and Supporting Documentation"},
            {"Identifier": "lea", "Title": "2022-23 Local Level Data File and Supporting Documentation (Part B Child Count & Educational Environments)"},
        ], "pagination": {"hasMore": True, "nextCursor": "p2"}},
        "p2": {"data": [
            {"Identifier": "static", "Title": "2016-17 Static Tables (Part B Child Count & Educational Environments)"},
            {"Identifier": "c", "Title": "2023-24 State Level Data File and Supporting Documentation (Part B Child Count & Educational Environments)"},
        ], "pagination": {"hasMore": False, "nextCursor": None}},
    }
    monkeypatch.setattr(_lib, "_idea_get", _api(pages))
    urls = _lib._idea_year_urls()
    assert sorted(urls) == [2005, 2016, 2023]
    assert urls[2005].endswith("bchildcount2005.csv")


def test_an_empty_catalog_fails_loudly(monkeypatch):
    monkeypatch.setattr(_lib, "_idea_get", _api({None: {"data": [], "pagination": {}}}))
    with pytest.raises(RuntimeError, match="no Part B child count CSVs"):
        _lib._idea_year_urls()
