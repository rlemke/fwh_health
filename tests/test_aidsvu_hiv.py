"""US HIV transmission map reads AIDSVu, after CDC withdrew the AtlasPlus backend.

On 2026-08-25 every path under gis.cdc.gov/grasp/AtlasPlus/ began returning 404
while the tool page still served 200 — CDC moved or withdrew the undocumented
JSON backend this map depended on. AIDSVu (Emory) republishes the same CDC
surveillance data as documented per-year workbooks, which is the fallback the
handler had already named.
"""
import io
import sys

import pytest

sys.path.insert(0, "src")
openpyxl = pytest.importorskip("openpyxl")
from health import _lib  # noqa: E402


DATASETS_HTML = """
<a href="https://aidsvu.org/wp-content/uploads/2025/08/AIDSVu_State_NewDX_2008-20250726.xlsx">2008</a>
<a href="https://aidsvu.org/wp-content/uploads/2025/08/AIDSVu_State_NewDX_2023-20250726.xlsx">2023</a>
<a href="https://aidsvu.org/wp-content/uploads/2020/04/2012_AIDSVu_State_PrEP_6.27.19.xlsx">unrelated</a>
"""


def test_urls_are_scraped_not_constructed(monkeypatch):
    """Filenames carry a publication datestamp, so a built URL is a future 404."""
    monkeypatch.setattr(_lib.requests, "get",
                        lambda *a, **k: type("R", (), {"text": DATASETS_HTML})())
    urls = _lib._aidsvu_state_newdx_urls()
    assert set(urls) == {2008, 2023}
    assert urls[2023].endswith("AIDSVu_State_NewDX_2023-20250726.xlsx")
    assert all("PrEP" not in u for u in urls.values()), "PrEP files are a different dataset"


def test_a_layout_change_fails_loudly(monkeypatch):
    """Silently returning {} would render an empty map that looks fine."""
    monkeypatch.setattr(_lib.requests, "get",
                        lambda *a, **k: type("R", (), {"text": "<html>nothing here</html>"})())
    with pytest.raises(RuntimeError, match="no AIDSVu State_NewDX workbooks"):
        _lib._aidsvu_state_newdx_urls()


@pytest.mark.parametrize("cell,expected", [
    (None, None), ("", None), ("   ", None),
    (17, 17), (17.0, 17), ("1,603", 1603), ("710", 710),
    ("*", None), ("Data suppressed", None), ("N/A", None),
])
def test_suppressed_cells_are_none_not_zero(cell, expected):
    """Zero would invent zero diagnoses where the count was merely withheld."""
    assert _lib._aidsvu_int(cell) == expected


def _workbook(header_offset: int) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    for _ in range(header_offset):
        ws.append(["preamble"])
    cols = ["Year", "GEO ID", "State Abbreviation", "State",
            "New Diagnoses State Cases", "New Diagnoses MSM Cases",
            "New Diagnoses Heterosexual Contact Cases", "New Diagnoses IDU Cases",
            "New Diagnoses MSM/IDU Cases", "New Diagnoses Other Transmission Category Cases"]
    ws.append(cols)
    ws.append(["2023", 4, "AZ", "Arizona", 100, 60, 20, 10, 5, 5])
    ws.append(["2023", 6, "CA", "California", 200, 150, 30, 10, 5, None])   # suppressed
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return buf


@pytest.mark.parametrize("offset", [0, 3, 5])
def test_header_is_found_by_content_not_a_fixed_row(offset):
    wb = openpyxl.load_workbook(_workbook(offset), read_only=True)
    row, hdr = _lib._aidsvu_header(wb["Data"])
    assert row == offset + 1
    assert "GEO ID" in hdr


def test_geo_id_is_fips_and_is_zero_padded(monkeypatch):
    """AZ is 4 (not 3) and CA is 6 — FIPS has gaps, so this is NOT a sequence.
    Reading it as an index would mis-attribute every state after Arizona."""
    monkeypatch.setattr(_lib, "US_HIV_YEAR_FROM", 2023)
    monkeypatch.setattr(_lib, "_aidsvu_state_newdx_urls", lambda: {2023: "http://x/f.xlsx"})
    monkeypatch.setattr(_lib.requests, "get",
                        lambda *a, **k: type("R", (), {"content": _workbook(3).getvalue()})())
    data = _lib._fetch_aidsvu_hiv_transmission()
    assert set(data) == {"04", "06"}, "GEO ID must be zero-padded FIPS"
    assert data["04"]["tx_msm"]["2023"] == 60
    # the suppressed cell is absent entirely, not recorded as 0
    assert "tx_other" not in data["06"]


def test_missing_column_fails_loudly(monkeypatch):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Data"
    ws.append(["Year", "GEO ID", "State", "New Diagnoses State Cases"])
    ws.append(["2023", 4, "Arizona", 100])
    buf = io.BytesIO(); wb.save(buf)
    monkeypatch.setattr(_lib, "US_HIV_YEAR_FROM", 2023)
    monkeypatch.setattr(_lib, "_aidsvu_state_newdx_urls", lambda: {2023: "http://x/f.xlsx"})
    monkeypatch.setattr(_lib.requests, "get",
                        lambda *a, **k: type("R", (), {"content": buf.getvalue()})())
    with pytest.raises(RuntimeError, match="missing column"):
        _lib._fetch_aidsvu_hiv_transmission()
