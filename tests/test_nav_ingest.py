from datetime import date
from decimal import Decimal

import pytest

from app.nav_ingest import parse_amfi_nav_text

SAMPLE = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
Open Ended Schemes ( Growth Scheme - Equity Scheme );;;;;
119551;INF204K01K15;INF204K01K23;Nippon India Large Cap Fund - Direct Plan - Growth;89.1234;21-Oct-2026
120503;INF204K01K31;;Nippon India Liquid Fund - Direct Plan - Growth;1000.1234;21-Oct-2026
"""


def test_parses_valid_rows_and_dates():
    records, report = parse_amfi_nav_text(SAMPLE)
    assert len(records) == 2
    assert records[0].scheme_code == 119551
    assert records[0].nav == Decimal("89.1234")
    assert records[0].nav_date == date(2026, 10, 21)
    assert report["unique_scheme_codes"] == 2
    assert report["quality_status"] == "PASS"


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
    records, report = parse_amfi_nav_text(SAMPLE + "119551;broken\\n")
    assert len(records) == 2
    assert report["invalid_rows"] == 1
    assert report["candidate_data_lines"] == 3
