from datetime import date
from decimal import Decimal
from app.nav_ingest import AMFI_NAV_URL, parse_amfi_nav_text

def test_parses_official_amfi_six_column_feed_excerpt():
    payload = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
119551;INF209KA12Z1;INF209KA13Z9;Aditya Birla Sun Life Banking & PSU Debt Fund - DIRECT - IDCW;107.0971;07-Aug-2026
119552;INF209K01YM2;-;Aditya Birla Sun Life Banking & PSU Debt Fund - DIRECT - MONTHLY IDCW;117.4164;07-Aug-2026
"""
    records, report = parse_amfi_nav_text(payload)
    assert AMFI_NAV_URL == "https://portal.amfiindia.com/spages/NAVAll.txt"
    assert [record.scheme_code for record in records] == [119551, 119552]
    assert records[0].nav == Decimal("107.0971")
    assert records[0].nav_date == date(2026, 8, 7)
    assert records[1].isin_dividend_reinvestment is None
    assert report["records_valid"] == 2
    assert report["invalid_rows"] == 0
    assert report["quality_status"] == "PASS"

def test_accepts_utf8_bom_with_official_feed_shape():
    payload = "\ufeffScheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n119551;INF209KA12Z1;INF209KA13Z9;Aditya Birla Sun Life Banking & PSU Debt Fund - DIRECT - IDCW;107.0971;07-Aug-2026\n"
    records, report = parse_amfi_nav_text(payload)
    assert len(records) == 1
    assert report["records_valid"] == 1
