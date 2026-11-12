from datetime import date
from decimal import Decimal

import pytest

from app.nav_history import (
    AMFI_HISTORY_URL,
    ConflictingHistoricalNavError,
    parse_amfi_history_text,
)

LEGACY_SAMPLE = """Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date
Open Ended Schemes ( Growth Scheme - Equity Scheme )
119551;Example Equity Fund - Direct Growth;INF204K01K15;INF204K01K23;89.1234;85.0000;89.1234;21-Oct-2026
120503;Example Liquid Fund - Regular Growth;-;;1000.1234;999.0000;1000.1234;21-Oct-2026
"""

CURRENT_SAMPLE = """Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Date
Open Ended Schemes ( Equity Scheme - Multi Cap Fund )
Aditya Birla Sun Life Mutual Fund
148921;Aditya Birla Sun Life Multi-Cap Fund-Direct Growth;Direct Plan;GROWTH;INF209KB1Y49;;22.77;05-Nov-2026
148921;Aditya Birla Sun Life Multi-Cap Fund-Direct Growth;Direct Plan;GROWTH;INF209KB1Y49;;22.83;06-Nov-2026
148920;Aditya Birla Sun Life Multi-Cap Fund-Direct IDCW Payout;Direct Plan;IDCW Payout;INF209KB1Y56;;18.73;05-Nov-2026
"""


def test_parses_legacy_eight_column_archive_layout():
    records, report = parse_amfi_history_text(LEGACY_SAMPLE)
    assert [record.scheme_code for record in records] == [119551, 120503]
    assert records[0].scheme_name == "Example Equity Fund - Direct Growth"
    assert records[0].nav == Decimal("89.1234")
    assert records[0].nav_date == date(2026, 10, 21)
    assert records[0].plan_type is None
    assert records[1].isin_growth is None
    assert report["source_url"] == AMFI_HISTORY_URL
    assert report["records_valid"] == 2
    assert report["quality_status"] == "PASS"
    assert report["header_verified"] is True
    assert report["schema_variant"] == "scheme_isin_nav_price_date"


def test_parses_current_live_amfi_plan_option_layout():
    records, report = parse_amfi_history_text(CURRENT_SAMPLE)
    assert len(records) == 3
    assert records[0].scheme_code == 148921
    assert records[0].scheme_name == "Aditya Birla Sun Life Multi-Cap Fund-Direct Growth"
    assert records[0].plan_type == "Direct Plan"
    assert records[0].option_type == "GROWTH"
    assert records[0].isin_growth == "INF209KB1Y49"
    assert records[0].nav == Decimal("22.77")
    assert records[0].nav_date == date(2026, 11, 5)
    assert records[2].option_type == "IDCW Payout"
    assert report["records_valid"] == 3
    assert report["schema_variant"] == "scheme_plan_option_nav_date"


def test_rejects_data_rows_without_recognised_archive_header():
    payload = "119551;Example Equity Fund;INF204K01K15;INF204K01K23;89.1234;85;89;21-Oct-2026"
    with pytest.raises(ValueError, match="missing a recognised eight-column header"):
        parse_amfi_history_text(payload)


def test_supports_bom_and_alternate_numeric_date_format():
    payload = "\ufeff" + LEGACY_SAMPLE.replace("21-Oct-2026", "21/10/2026")
    records, _ = parse_amfi_history_text(payload)
    assert records[0].nav_date == date(2026, 10, 21)


def test_skips_identical_duplicate_and_reports_it():
    duplicate = LEGACY_SAMPLE + "119551;Example Equity Fund;INF204K01K15;INF204K01K23;89.1234;85;89;21-Oct-2026\n"
    records, report = parse_amfi_history_text(duplicate)
    assert len(records) == 2
    assert report["duplicate_rows_skipped"] == 1


def test_rejects_conflicting_duplicate_navs():
    duplicate = LEGACY_SAMPLE + "119551;Example Equity Fund;INF204K01K15;INF204K01K23;90.1234;85;90;21-Oct-2026\n"
    with pytest.raises(ConflictingHistoricalNavError, match="conflicting historical NAV"):
        parse_amfi_history_text(duplicate)


@pytest.mark.parametrize("payload, message", [
    ("", "is empty"),
    ("<!doctype html><html>error</html>", "returned HTML"),
    ("Scheme Code;wrong;header", "unrecognised"),
    ("not an archive", "missing a recognised eight-column header"),
])
def test_rejects_empty_html_wrong_header_and_non_data(payload, message):
    with pytest.raises(ValueError, match=message):
        parse_amfi_history_text(payload)


def test_reports_malformed_numeric_candidate_without_dropping_valid_rows():
    payload = LEGACY_SAMPLE + "119551;Broken;ISIN;;not-a-nav;0;0;21-Oct-2026\n"
    records, report = parse_amfi_history_text(payload)
    assert len(records) == 2
    assert report["invalid_rows"] == 1
    assert sum(report["invalid_issue_counts"].values()) == 1


def test_zero_nav_is_counted_with_explicit_reason_and_never_emitted():
    payload = LEGACY_SAMPLE + (
        "130001;Liquidated Fund;INF0000000001;;0.0000;0;0;21-Oct-2026\\n"
    )
    records, report = parse_amfi_history_text(payload)
    assert len(records) == 2
    assert report["invalid_rows"] == 1
    assert report["invalid_issue_counts"] == {
        "NAV must be positive for persistence (received '0.0000')": 1
    }
