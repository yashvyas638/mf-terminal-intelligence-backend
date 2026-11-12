from decimal import Decimal

import pytest

from app.holdings_ingest import parse_fund_holdings_csv


HOLDINGS_CSV = """ISIN,Name of Instrument,% to Net Assets,Asset Type,Sector
INE002A01018,Example Bank Ltd,5.25,Equity,Financial Services
INE002A01018,Example Bank Ltd,1.75,Equity,Financial Services
INE009A01021,Example Technology Ltd,3.50,Equity,Information Technology
,Net Current Assets,2.00,Cash,
"""


def test_holdings_parser_aggregates_duplicate_isins_and_tracks_non_isin_rows():
    points, report = parse_fund_holdings_csv(HOLDINGS_CSV)
    by_id = {point.security_id: point for point in points}
    assert by_id["INE002A01018"].weight_pct == Decimal("7.00000000")
    assert by_id["INE002A01018"].is_isin is True
    assert by_id["INE009A01021"].weight_pct == Decimal("3.50000000")
    non_isin = next(point for point in points if not point.is_isin)
    assert non_isin.security_name == "Net Current Assets"
    assert non_isin.security_id.startswith("NONISIN:")
    assert report["rows_seen"] == 4
    assert report["unique_holdings"] == 3
    assert report["isin_holdings"] == 2
    assert report["non_isin_holdings"] == 1
    assert Decimal(report["total_weight_pct"]) == Decimal("12.50000000")


def test_holdings_parser_rejects_missing_weight_or_security_name_columns():
    with pytest.raises(ValueError, match="security name and % to Net Assets"):
        parse_fund_holdings_csv("ISIN,Name of Instrument\nINE002A01018,Bank\n")


def test_holdings_parser_rejects_invalid_isins_and_non_finite_weights():
    with pytest.raises(ValueError, match="invalid ISIN"):
        parse_fund_holdings_csv(
            "ISIN,Name of Instrument,% to Net Assets\nBADISIN,Bank,5\n"
        )
    with pytest.raises(ValueError, match="finite"):
        parse_fund_holdings_csv(
            "ISIN,Name of Instrument,% to Net Assets\nINE002A01018,Bank,NaN\n"
        )


def test_holdings_parser_rejects_empty_and_oversized_files():
    with pytest.raises(ValueError, match="empty"):
        parse_fund_holdings_csv("")
    with pytest.raises(ValueError, match="5 MB"):
        parse_fund_holdings_csv("x" * 5_000_001)



def test_optional_blank_market_value_is_not_multiplied_or_rejected():
    points, report = parse_fund_holdings_csv(
        "ISIN,Name of Instrument,% to Net Assets,Market Value (Rs.)\n"
        "INE002A01018,Example Bank,5.25,\n"
    )
    assert points[0].market_value_inr is None
    assert report["unique_holdings"] == 1


def test_holdings_parser_rejects_precision_loss_in_weight_and_market_value():
    with pytest.raises(ValueError, match="more than 8 decimal places"):
        parse_fund_holdings_csv(
            "ISIN,Name of Instrument,% to Net Assets\n"
            "INE002A01018,Bank,5.123456789\n"
        )
    with pytest.raises(ValueError, match="more than 2 decimal places"):
        parse_fund_holdings_csv(
            "ISIN,Name of Instrument,% to Net Assets,Market Value (Rs.)\n"
            "INE002A01018,Bank,5,100.001\n"
        )


def test_holdings_parser_rejects_conflicting_security_classification():
    with pytest.raises(ValueError, match="conflicting sector"):
        parse_fund_holdings_csv(
            "ISIN,Name of Instrument,% to Net Assets,Sector\n"
            "INE002A01018,Bank,5,Financials\n"
            "INE002A01018,Bank,2,Industrials\n"
        )


def test_holdings_parser_rejects_duplicate_normalized_headers_and_extra_columns():
    with pytest.raises(ValueError, match="duplicate or ambiguous"):
        parse_fund_holdings_csv(
            "ISIN,Name of Instrument,Name-of-Instrument,% to Net Assets\n"
            "INE002A01018,Bank,Bank,5\n"
        )
    with pytest.raises(ValueError, match="more values"):
        parse_fund_holdings_csv(
            "ISIN,Name of Instrument,% to Net Assets\n"
            "INE002A01018,Bank,5,unexpected\n"
        )


def test_holdings_weight_reconciliation_is_explicit_not_silently_assumed():
    _, report = parse_fund_holdings_csv(HOLDINGS_CSV)
    assert report["weight_total_status"] == "REVIEW_REQUIRED"
    assert Decimal(report["weight_total_variance_from_100_pct"]) == Decimal("-87.50000000")
