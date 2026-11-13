from __future__ import annotations

import json

import pytest

from app.amfi_scheme_summary_taxonomy import (
    fetch_amfi_scheme_summary_taxonomy,
    parse_scheme_summary_category,
)


def _spreadsheetml(name: str, category: str, fund_type: str) -> bytes:
    rows = [
        ("1", "Fund Name", name),
        ("2", "Category_as_Per_SEBI_Categorization_Circular", category),
        ("3", "Fund_Type", fund_type),
    ]
    body = "".join(
        "<Row>" + "".join(
            f"<Cell><Data>{value}</Data></Cell>" for value in row
        ) + "</Row>"
        for row in rows
    )
    return (
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
        "<Worksheet><Table>" + body + "</Table></Worksheet></Workbook>"
    ).encode()


class _FakeResponse:
    def __init__(self, *, payload=None, content=b"", status_code=200):
        self._payload = payload
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, xml: bytes):
        self.headers = {}
        self.xml = xml
        self.closed = False

    def get(self, url, *, params=None, timeout=None):
        if url.endswith("/otherdata/scheme-details"):
            return _FakeResponse()
        if url.endswith("/api/populate-mf"):
            return _FakeResponse(payload=[{"mfId": 28, "mfName": "UTI Mutual Fund"}])
        if url.endswith("/api/populate-scheme"):
            assert params == {"MF_ID": 28}
            return _FakeResponse(payload=[{
                "scheme_id": "1134",
                "scheme_name": "UTI - Banking and Financial Services Fund",
            }])
        if url.endswith("/spages/SSD_1134.xml"):
            return _FakeResponse(content=self.xml)
        raise AssertionError(f"Unexpected AMFI URL: {url}")


def test_parse_official_amfi_summary_maps_explicit_sectoral_category():
    result = parse_scheme_summary_category(
        _spreadsheetml(
            "UTI - Banking and Financial Services Fund",
            "Sectoral",
            "An open ended equity scheme investing in Banking and Financial Services Sector.",
        ),
        expected_scheme_name="UTI - Banking and Financial Services Fund",
    )
    assert result == {
        "category_group": "Equity Scheme",
        "category": "Sectoral Fund",
        "asset_class": "Equity",
    }


def test_parse_official_amfi_summary_rejects_fmp_not_in_current_allowlist():
    result = parse_scheme_summary_category(
        _spreadsheetml(
            "HDFC Fixed Maturity Plan",
            "Fixed Maturity Plan",
            "A close ended debt scheme investing in fixed income securities.",
        ),
        expected_scheme_name="HDFC Fixed Maturity Plan",
    )
    assert result is None


def test_parse_official_amfi_summary_rejects_scheme_name_mismatch():
    with pytest.raises(ValueError, match="does not match"):
        parse_scheme_summary_category(
            _spreadsheetml(
                "Different Scheme",
                "Sectoral Fund",
                "An open ended equity scheme.",
            ),
            expected_scheme_name="UTI - Banking and Financial Services Fund",
        )


def test_parse_official_amfi_summary_rejects_doctype_and_entity():
    with pytest.raises(ValueError, match="forbidden declaration"):
        parse_scheme_summary_category(
            b'<!DOCTYPE x [<!ENTITY x "bad">]><SchemeSummaryDocument/>',
            expected_scheme_name="Any Fund",
        )


def test_fetch_amfi_summary_matches_exact_amc_and_base_scheme_name():
    xml = _spreadsheetml(
        "UTI - Banking and Financial Services Fund",
        "Sectoral",
        "An open ended equity scheme investing in Banking and Financial Services Sector.",
    )
    session = _FakeSession(xml)
    result = fetch_amfi_scheme_summary_taxonomy(
        [{
            "amc": "UTI Mutual Fund",
            "scheme_name": "UTI - Banking and Financial Services Fund - Direct Plan - Growth",
        }],
        session=session,
    )
    assert result["mappings"] == {
        "name:uti - banking and financial services fund": {
            "category_group": "Equity Scheme",
            "category": "Sectoral Fund",
            "asset_class": "Equity",
        }
    }
    assert result["source_names_matched"] == 1
    assert result["source_names_unmatched"] == 0
    assert result["requests_made"] == 4
    assert result["category_counts"] == {"Equity Scheme / Sectoral Fund": 1}
