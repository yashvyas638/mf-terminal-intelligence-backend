from __future__ import annotations

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


def test_parse_official_amfi_summary_decodes_double_escaped_ampersands():
    result = parse_scheme_summary_category(
        _spreadsheetml(
            "HDFC Banking &amp;amp; Financial Services Fund",
            "Sectoral Fund",
            "An open ended equity scheme investing in Banking and Financial Services Sector.",
        ),
        expected_scheme_name="HDFC Banking & Financial Services Fund",
    )
    assert result == {
        "category_group": "Equity Scheme",
        "category": "Sectoral Fund",
        "asset_class": "Equity",
    }


def test_parse_official_amfi_summary_resolves_theme_descriptor_using_official_group_hint():
    result = parse_scheme_summary_category(
        _spreadsheetml(
            "UTI - ESG Theme Fund",
            "Thematic Fund-\u2011 ESG Theme",
            "An open ended equity scheme.",
        ),
        expected_scheme_name="UTI - ESG Theme Fund",
    )
    assert result == {
        "category_group": "Equity Scheme",
        "category": "Thematic Fund",
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


def test_scheme_summary_parser_exposes_unmapped_legacy_category_fields():
    from app.amfi_scheme_summary_taxonomy import (
        _extract_scheme_summary_fields,
        _scheme_summary_category_fields,
    )

    fields = _extract_scheme_summary_fields(
        _spreadsheetml(
            "Legacy Children's Solution Fund",
            "Solution Oriented Scheme",
            "An open ended solution oriented scheme.",
        )
    )
    raw_category, fund_type = _scheme_summary_category_fields(fields)
    assert raw_category == "Solution Oriented Scheme"
    assert fund_type == "An open ended solution oriented scheme."
    assert parse_scheme_summary_category(
        _spreadsheetml(
            "Legacy Children's Solution Fund",
            "Solution Oriented Scheme",
            "An open ended solution oriented scheme.",
        ),
        expected_scheme_name="Legacy Children's Solution Fund",
    ) is None


def test_scheme_details_category_fallback_maps_exact_allowlisted_current_categories():
    from app.fund_taxonomy import classify_amfi_category

    assert classify_amfi_category("Equity Scheme - ELSS") == (
        "Equity Scheme",
        "ELSS Tax Saver Fund",
        "Equity",
    )
    assert classify_amfi_category("Debt Scheme - Short Duration Fund") == (
        "Debt Scheme",
        "Short Term Fund",
        "Debt",
    )
    assert classify_amfi_category(
        "Overseas Fund of Funds - Fund of Funds investing overseas"
    ) == (
        "Other Schemes",
        "FoFs (Overseas/Domestic)",
        "Other",
    )


def test_scheme_details_fallback_resolves_bare_categories_only_when_unique():
    from app.amfi_scheme_summary_taxonomy import classify_amfi_scheme_details_category

    assert classify_amfi_scheme_details_category("ELSS") == (
        "Equity Scheme",
        "ELSS Tax Saver Fund",
        "Equity",
    )
    assert classify_amfi_scheme_details_category("Thematic Fund- ESG Theme") == (
        "Equity Scheme",
        "Thematic Fund",
        "Equity",
    )
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212", "\u00ad"):
        assert classify_amfi_scheme_details_category(f"Thematic Fund{dash} ESG Theme") == (
            "Equity Scheme",
            "Thematic Fund",
            "Equity",
        )
    assert classify_amfi_scheme_details_category("Sectoral/Thematic Funds") == (
        "Equity Scheme",
        "Sectoral/Thematic Fund",
        "Equity",
    )
    assert classify_amfi_scheme_details_category("Short Duration Fund") == (
        "Debt Scheme",
        "Short Term Fund",
        "Debt",
    )
    assert classify_amfi_scheme_details_category("Index Fund") == (
        "Other Schemes",
        "Index Funds / ETFs",
        "Other",
    )
    assert classify_amfi_scheme_details_category("Index Funds - Equity Funds") == (
        "Other Schemes",
        "Index Funds / ETFs",
        "Other",
    )
    assert classify_amfi_scheme_details_category("Equity - Thematic") == (
        "Equity Scheme",
        "Thematic Fund",
        "Equity",
    )
    assert classify_amfi_scheme_details_category("Equity Scheme Sectoral/Thematic Fund") == (
        "Equity Scheme",
        "Sectoral/Thematic Fund",
        "Equity",
    )
    assert classify_amfi_scheme_details_category("Equity Schemes – Thematic Fund") == (
        "Equity Scheme",
        "Thematic Fund",
        "Equity",
    )
    assert classify_amfi_scheme_details_category("Equity: Thematic Funds") == (
        "Equity Scheme",
        "Thematic Fund",
        "Equity",
    )


def test_discontinued_solution_oriented_and_fmp_labels_stay_unclassified():
    from app.fund_taxonomy import classify_amfi_category

    assert classify_amfi_category("Solution Oriented - Retirement Fund") == (None, None, None)
    fmp_group, fmp_category, fmp_asset = classify_amfi_category("Income - Fixed Maturity Plan")
    assert fmp_group == "Debt Scheme"
    assert fmp_category is None
    assert fmp_asset == "Debt"


def test_fetch_uses_scheme_details_only_when_summary_has_no_mappable_category():
    class DetailsFallbackSession(_FakeSession):
        def get(self, url, *, params=None, timeout=None):
            if url.endswith("/api/scheme-details"):
                assert params == {"MF_ID": 28, "scheme_id": "1134"}
                return _FakeResponse(payload=[{
                    "Scheme_Name": "UTI - Banking and Financial Services Fund",
                    "SchemeCat_Desc": "Thematic Fund\u2011 ESG Theme",
                    "SchemeType_Desc": "Open Ended",
                }])
            return super().get(url, params=params, timeout=timeout)

    session = DetailsFallbackSession(
        _spreadsheetml(
            "UTI - Banking and Financial Services Fund",
            "",
            "An open ended equity scheme.",
        )
    )
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
            "category": "Thematic Fund",
            "asset_class": "Equity",
        }
    }
    assert result["source_names_matched"] == 1
    assert result["requests_made"] == 5


def test_amfi_source_request_retries_transient_disconnect(monkeypatch):
    import requests
    import app.amfi_scheme_summary_taxonomy as taxonomy

    class FlakySession:
        def __init__(self):
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise requests.exceptions.ConnectionError("temporary remote disconnect")
            return _FakeResponse(payload=[])

    monkeypatch.setattr(taxonomy.time, "sleep", lambda _: None)
    session = FlakySession()
    response, attempts = taxonomy._get_with_retries(session, "https://amfi.example.test")

    assert response.status_code == 200
    assert attempts == 2
    assert session.calls == 2


def test_amfi_source_request_retries_transient_gateway_status(monkeypatch):
    import app.amfi_scheme_summary_taxonomy as taxonomy

    class FlakySession:
        def __init__(self):
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            return _FakeResponse(payload=[], status_code=503 if self.calls == 1 else 200)

    monkeypatch.setattr(taxonomy.time, "sleep", lambda _: None)
    session = FlakySession()
    response, attempts = taxonomy._get_with_retries(session, "https://amfi.example.test")

    assert response.status_code == 200
    assert attempts == 2
    assert session.calls == 2
