from datetime import date
from decimal import Decimal

import pytest

from app.nav_history import (
    AMFI_HISTORY_URL,
    ConflictingHistoricalNavError,
    parse_amfi_history_text,
)

SAMPLE = """Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date
Open Ended Schemes ( Growth Scheme - Equity Scheme );;;;;;;
119551;Example Equity Fund - Direct Growth;INF204K01K15;INF204K01K23;89.1234;85.0000;89.1234;21-Oct-2026
120503;Example Liquid Fund - Regular Growth;-;;1000.1234;999.0000;1000.1234;21-Oct-2026
"""


def test_parses_historical_eight_column_layout_without_misreading_nav():
    records, report = parse_amfi_history_text(SAMPLE)
    assert [record.scheme_code for record in records] == [119551, 120503]
    assert records[0].scheme_name == "Example Equity Fund - Direct Growth"
    assert records[0].nav == Decimal("89.1234")
    assert records[0].nav_date == date(2026, 10, 21)
    assert records[0].plan_type is None
    assert records[1].isin_growth is None
    assert report["source_url"] == AMFI_HISTORY_URL
    assert report["records_valid"] == 2
    assert report["quality_status"] == "PASS"


def test_supports_bom_and_alternate_numeric_date_format():
    payload = "\ufeff" + SAMPLE.replace("21-Oct-2026", "21/10/2026")
    records, _ = parse_amfi_history_text(payload)
    assert records[0].nav_date == date(2026, 10, 21)


def test_skips_identical_duplicate_and_reports_it():
    duplicate = SAMPLE + "119551;Example Equity Fund;INF204K01K15;INF204K01K23;89.1234;85;89;21-Oct-2026\n"
    records, report = parse_amfi_history_text(duplicate)
    assert len(records) == 2
    assert report["duplicate_rows_skipped"] == 1


def test_rejects_conflicting_duplicate_navs():
    duplicate = SAMPLE + "119551;Example Equity Fund;INF204K01K15;INF204K01K23;90.1234;85;90;21-Oct-2026\n"
    with pytest.raises(ConflictingHistoricalNavError, match="conflicting historical NAV"):
        parse_amfi_history_text(duplicate)


@pytest.mark.parametrize("payload, message", [
    ("", "is empty"),
    ("<!doctype html><html>error</html>", "returned HTML"),
    ("Scheme Code;wrong;header", "unrecognised"),
    ("not an archive", "no valid NAV records"),
])
def test_rejects_empty_html_wrong_header_and_non_data(payload, message):
    with pytest.raises(ValueError, match=message):
        parse_amfi_history_text(payload)


def test_reports_malformed_numeric_candidate_without_dropping_valid_rows():
    payload = SAMPLE + "119551;Broken;ISIN;;not-a-nav;0;0;21-Oct-2026\n"
    records, report = parse_amfi_history_text(payload)
    assert len(records) == 2
    assert report["invalid_rows"] == 1
