from datetime import date
from decimal import Decimal

import pytest

from app.nav_ingest import AMFI_NAV_URL, parse_amfi_nav_text

SAMPLE = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
Open Ended Schemes ( Growth Scheme - Equity Scheme );;;;;
119551;INF204K01K15;INF204K01K23;Nippon India Large Cap Fund - Direct Plan - Growth;89.1234;21-Oct-2026
120503;INF204K01K31;;Nippon India Liquid Fund - Direct Plan - Growth;1000.1234;21-Oct-2026
"""


def test_uses_canonical_amfi_portal_feed():
    assert AMFI_NAV_URL == "https://portal.amfiindia.com/spages/NAVAll.txt"


def test_parses_valid_rows_and_dates():
    records, report = parse_amfi_nav_text(SAMPLE)
    assert len(records) == 2
    assert records[0].scheme_code == 119551
    assert records[0].nav == Decimal("89.1234")
    assert records[0].nav_date == date(2026, 10, 21)
    assert report["unique_scheme_codes"] == 2
    assert report["quality_status"] == "PASS"
    assert report["source_url"] == AMFI_NAV_URL


def test_normalizes_amfi_missing_isin_marker_to_null():
    records, _ = parse_amfi_nav_text(
        "119551;-;-;Example Fund;12.3456;21-Oct-2026\n"
    )
    assert records[0].isin_growth is None
    assert records[0].isin_dividend_reinvestment is None


def test_skips_duplicate_scheme_date_and_reports_it():
    records, report = parse_amfi_nav_text(SAMPLE + "119551;INF204K01K15;INF204K01K23;Fund;89.1234;21-Oct-2026\n")
    assert len(records) == 2
    assert report["duplicate_rows_skipped"] == 1


def test_rejects_payload_without_valid_nav_rows():
    with pytest.raises(ValueError, match="no valid NAV records"):
        parse_amfi_nav_text("not an AMFI file\n")


def test_bad_row_is_reported_without_losing_good_rows():
    records, report = parse_amfi_nav_text(SAMPLE + "bad;row;format;name;not-a-nav;not-a-date\n")
    assert len(records) == 2
    assert report["invalid_rows"] == 1


def test_short_numeric_candidate_row_is_counted_as_invalid():
    records, report = parse_amfi_nav_text(SAMPLE + "119551;broken\n")
    assert len(records) == 2
    assert report["invalid_rows"] == 1
    assert report["candidate_data_lines"] == 3


def test_rejects_html_error_page_instead_of_nav_feed():
    with pytest.raises(ValueError, match="HTML instead of the NAV text feed"):
        parse_amfi_nav_text("<!doctype html><html><body>temporarily unavailable</body></html>")


def test_rejects_conflicting_duplicate_scheme_date_nav_values():
    conflicting = (
        "119551;INF204K01K15;INF204K01K23;Nippon India Large Cap Fund;89.1234;21-Oct-2026\n"
        "119551;INF204K01K15;INF204K01K23;Nippon India Large Cap Fund;90.1234;21-Oct-2026\n"
    )
    with pytest.raises(ValueError, match="conflicting duplicate NAV"):
        parse_amfi_nav_text(conflicting)


def test_parses_expanded_amfi_eight_column_rows():
    expanded = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
119551;INF204K01K15;INF204K01K23;Nippon India Large Cap Fund;Direct;Growth;89.1234;21-Oct-2026
120503;INF204K01K31;;Nippon India Liquid Fund;Regular;IDCW Payout;1000.1234;21-Oct-2026
"""
    records, report = parse_amfi_nav_text(expanded)
    assert len(records) == 2
    assert records[0].scheme_name == "Nippon India Large Cap Fund - Direct - Growth"
    assert records[0].nav == Decimal("89.1234")
    assert records[0].nav_date == date(2026, 10, 21)
    assert records[0].plan_type == "Direct"
    assert records[0].option_type == "Growth"
    assert records[1].plan_type == "Regular"
    assert records[1].option_type == "IDCW Payout"
    assert records[1].scheme_name == "Nippon India Liquid Fund - Regular - IDCW Payout"
    assert records[1].nav == Decimal("1000.1234")
    assert report["unique_scheme_codes"] == 2




def test_parses_official_amfi_amc_and_modern_category_headers():
    payload = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
HDFC Mutual Fund
Open Ended Schemes(Equity Scheme - Large Cap Fund)
120586;INF109K01480;-;HDFC Large Cap Fund - Direct Plan - Growth;123.4567;21-Oct-2026
"""
    records, _ = parse_amfi_nav_text(payload)
    record = records[0]
    assert record.amc == "HDFC Mutual Fund"
    assert record.structure == "Open Ended"
    assert record.category_group == "Equity Scheme"
    assert record.category == "Large Cap Fund"
    assert record.asset_class == "Equity"
    assert record.metadata_present is True


def test_maps_legacy_amfi_growth_header_to_broad_group_without_fake_subcategory():
    payload = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
HDFC Mutual Fund
Open Ended Schemes ( Growth )
120586;INF109K01480;-;HDFC Growth Fund - Direct Plan - Growth;123.4567;21-Oct-2026
"""
    records, _ = parse_amfi_nav_text(payload)
    record = records[0]
    assert record.category_group == "Equity Scheme"
    assert record.category is None
    assert record.asset_class == "Equity"


def test_maps_debt_and_hybrid_headers_without_using_scheme_marketing_names():
    debt, _ = parse_amfi_nav_text(
        "Open Ended Schemes(Debt Scheme - Short Term Fund)\n"
        "120586;INF109K01480;-;Power Select Opportunity Fund;123.4567;21-Oct-2026\n"
    )
    hybrid, _ = parse_amfi_nav_text(
        "Open Ended Schemes(Hybrid Scheme - Aggressive Hybrid Fund)\n"
        "120587;INF109K01498;-;PowerUp Growth Fund;23.4567;21-Oct-2026\n"
    )
    assert debt[0].category_group == "Debt Scheme"
    assert debt[0].category == "Short Term Fund"
    assert debt[0].asset_class == "Debt"
    assert hybrid[0].category_group == "Hybrid Scheme"
    assert hybrid[0].category == "Aggressive Hybrid Fund"
    assert hybrid[0].asset_class == "Hybrid"



def test_rejects_unknown_marketing_subcategory_even_when_broad_group_is_valid():
    payload = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
Open Ended Schemes(Equity Scheme - PowerUp)
120588;INF109K01480;-;PowerUp Growth Fund;23.4567;21-Oct-2026
"""
    records, _ = parse_amfi_nav_text(payload)
    assert records[0].category_group == "Equity Scheme"
    assert records[0].category is None
    assert records[0].asset_class == "Equity"


def test_maps_2026_life_cycle_group_separately_from_other_schemes():
    payload = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
Open Ended Schemes(Life Cycle Funds)
120589;INF109K01480;-;Life Cycle Fund 2036;23.4567;21-Oct-2026
"""
    records, _ = parse_amfi_nav_text(payload)
    assert records[0].category_group == "Life Cycle Funds"
    assert records[0].category is None
    assert records[0].asset_class is None



def test_maps_official_other_scheme_subcategories_and_does_not_guess_retired_groups():
    other, _ = parse_amfi_nav_text(
        "Open Ended Schemes(Other Schemes - FoFs (Overseas/Domestic))\n"
        "120590;INF109K01480;-;Domestic Fund of Funds;23.4567;21-Oct-2026\n"
    )
    retired, _ = parse_amfi_nav_text(
        "Open Ended Schemes(Solution Oriented Scheme)\n"
        "120591;INF109K01480;-;Retirement Goal Fund;23.4567;21-Oct-2026\n"
    )
    assert other[0].category_group == "Other Schemes"
    assert other[0].category == "FoFs (Overseas/Domestic)"
    assert other[0].asset_class == "Other"
    assert retired[0].category_group is None
    assert retired[0].category is None
    assert retired[0].asset_class is None



def test_unrecognized_legacy_group_does_not_inherit_previous_amfi_section():
    payload = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
Open Ended Schemes(Equity Scheme - Large Cap Fund)
120592;INF109K01480;-;Example Large Cap Fund;23.4567;21-Oct-2026
Open Ended Schemes(Solution Oriented Scheme)
120593;INF109K01480;-;Legacy Solution Oriented Fund;23.4567;21-Oct-2026
"""
    records, _ = parse_amfi_nav_text(payload)
    assert records[0].category_group == "Equity Scheme"
    assert records[0].category == "Large Cap Fund"
    assert records[1].category_group is None
    assert records[1].category is None
    assert records[1].asset_class is None
