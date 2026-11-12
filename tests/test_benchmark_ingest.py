from decimal import Decimal

import pytest

from app.benchmark_ingest import parse_nifty_tri_csv


TRI_CSV = """IndexName,Date,Total Returns Index,Net Total Return Index
NIFTY 50,02-Jan-2026,25100.12345678,25050.12345678
NIFTY 50,01-Jan-2026,25000.00000000,24950.00000000
NIFTY 50,05-Jan-2026,25200.50000000,25150.50000000
"""


def test_nifty_tri_csv_parser_sorts_rows_and_preserves_decimal_precision():
    points, report = parse_nifty_tri_csv(TRI_CSV, "TRI")
    assert [point.observation_date.isoformat() for point in points] == [
        "2026-01-01", "2026-01-02", "2026-01-05"
    ]
    assert points[0].index_value == Decimal("25000.00000000")
    assert report["observations"] == 3
    assert report["source_index_name"] == "NIFTY 50"
    assert report["variant"] == "TRI"


def test_nifty_ntr_parser_requires_net_total_return_column():
    points, report = parse_nifty_tri_csv(TRI_CSV, "NTR")
    assert points[0].index_value == Decimal("24950.00000000")
    assert report["variant"] == "NTR"


def test_nifty_parser_deduplicates_identical_dates_but_rejects_conflicts():
    duplicate = TRI_CSV + "NIFTY 50,02-Jan-2026,25100.12345678,25050.12345678\n"
    points, report = parse_nifty_tri_csv(duplicate, "TRI")
    assert len(points) == 3
    assert report["duplicate_rows_skipped"] == 1

    conflicting = TRI_CSV + "NIFTY 50,02-Jan-2026,25101.00,25051.00\n"
    with pytest.raises(ValueError, match="conflicting duplicate"):
        parse_nifty_tri_csv(conflicting, "TRI")


def test_nifty_parser_rejects_price_return_or_wrong_variant_data():
    with pytest.raises(ValueError, match="only TRI and NTR"):
        parse_nifty_tri_csv(TRI_CSV, "PRI")
    with pytest.raises(ValueError, match="Net Total Return Index"):
        parse_nifty_tri_csv("Date,Total Returns Index\n01-Jan-2026,100\n", "NTR")


def test_nifty_parser_rejects_invalid_values_dates_and_multiple_index_names():
    with pytest.raises(ValueError, match="invalid benchmark CSV row"):
        parse_nifty_tri_csv("Date,Total Returns Index\n01-Jan-2026,-1\n", "TRI")
    with pytest.raises(ValueError, match="unsupported benchmark date"):
        parse_nifty_tri_csv("Date,Total Returns Index\nnot-a-date,100\n", "TRI")
    multi = TRI_CSV + "NIFTY NEXT 50,06-Jan-2026,25300,25250\n"
    with pytest.raises(ValueError, match="multiple index names"):
        parse_nifty_tri_csv(multi, "TRI")


def test_nifty_parser_rejects_empty_and_oversized_files():
    with pytest.raises(ValueError, match="empty"):
        parse_nifty_tri_csv("", "TRI")
    with pytest.raises(ValueError, match="5 MB"):
        parse_nifty_tri_csv("x" * 5_000_001, "TRI")


def test_nifty_parser_requires_index_identity_and_rejects_future_dates():
    with pytest.raises(ValueError, match="IndexName column"):
        parse_nifty_tri_csv("Date,Total Returns Index\\n01-Jan-2026,100\\n", "TRI")
    with pytest.raises(ValueError, match="cannot be in the future"):
        parse_nifty_tri_csv(
            "IndexName,Date,Total Returns Index\\nNIFTY 50,01-Jan-2027,100\\n",
            "TRI",
        )


def test_nifty_parser_rejects_silent_precision_rounding():
    with pytest.raises(ValueError, match="eight decimal places"):
        parse_nifty_tri_csv(
            "IndexName,Date,Total Returns Index\\nNIFTY 50,01-Jan-2026,100.000000001\\n",
            "TRI",
        )
