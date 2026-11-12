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
