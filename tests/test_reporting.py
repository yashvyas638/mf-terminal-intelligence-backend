from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph

from app.reporting import (
    _allocation_group_rows,
    _source_reference_row,
    _monthly_comparison_rows,
    build_portfolio_report_pdf,
)


def test_allocation_group_rows_render_each_frozen_bucket_without_renormalising():
    rows = _allocation_group_rows(
        [
            {
                "name": "Equity",
                "market_value_inr": "75000.00",
                "portfolio_weight_pct": "75.0000",
            },
            {
                "name": "UNCLASSIFIED",
                "market_value_inr": "25000.00",
                "portfolio_weight_pct": "25.0000",
            },
        ],
        "Category",
    )

    assert rows[0] == ["Category", "Market value INR", "Portfolio weight"]
    assert isinstance(rows[1][0], Paragraph)
    assert rows[1][0].text == "Equity"
    assert rows[1][1:] == ["75000.00", "75.0000"]
    assert rows[2][0].text == "UNCLASSIFIED"
    assert rows[2][1:] == ["25000.00", "25.0000"]


def test_allocation_group_rows_show_explicit_empty_state():
    rows = _allocation_group_rows([], "Asset class")

    assert rows == [
        ["Asset class", "Market value INR", "Portfolio weight"],
        ["No classified allocation rows", "—", "—"],
    ]


def test_nav_source_provenance_uses_source_url_and_nav_date_range():
    row = _source_reference_row(
        {
            "source_type": "AMFI_NAV_INGESTION",
            "source_url": "https://www.amfiindia.com/",
            "min_nav_date": "2026-10-01",
            "max_nav_date": "2026-10-31",
            "retrieved_at": "2026-11-01T00:00:00+00:00",
        },
        getSampleStyleSheet()["BodyText"],
    )

    assert row[0].text == "Amfi Nav Ingestion"
    assert row[1] == "2026-10-01 to 2026-10-31"
    assert row[2].text == "https://www.amfiindia.com/"


def test_twt_report_pdf_builds_from_saved_snapshot_payload():
    pdf = build_portfolio_report_pdf(
        {
            "portfolio_name": "Test portfolio",
            "report_version": "portfolio-report-v1",
            "generated_at": "2026-11-18T00:00:00+00:00",
            "valuation": {"current_value": "100000", "holdings": []},
            "allocation_intelligence": {
                "status": "AVAILABLE",
                "valuation_date": "2026-11-17",
                "allocation": {
                    "scheme_count": 1,
                    "schemes": [],
                    "by_category": [
                        {
                            "name": "Equity",
                            "market_value_inr": "100000",
                            "portfolio_weight_pct": "100.0000",
                        }
                    ],
                    "by_sub_category": [],
                    "by_asset_class": [
                        {
                            "name": "Equity",
                            "market_value_inr": "100000",
                            "portfolio_weight_pct": "100.0000",
                        }
                    ],
                    "data_quality": {"unclassified_scheme_count": 0},
                },
                "amc_concentration": {},
            },
        }
    )

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000



def test_monthly_comparison_rows_render_frozen_inr_and_percentage_point_changes():
    rows = _monthly_comparison_rows(
        {
            "comparisons": {
                "category": {
                    "status": "COMPARABLE",
                    "items": [
                        {
                            "key": "Equity",
                            "presence_status": "CONTINUING",
                            "metrics": {
                                "market_value_inr": {
                                    "previous": "70000",
                                    "current": "75000",
                                    "change": "5000",
                                    "change_inr": "5000",
                                    "status": "COMPARABLE",
                                },
                                "portfolio_weight_pct": {
                                    "previous": "70",
                                    "current": "75",
                                    "change": "5",
                                    "change_percentage_points": "5",
                                    "status": "COMPARABLE",
                                },
                            },
                        }
                    ],
                }
            }
        },
        "category",
        "market_value_inr",
        "portfolio_weight_pct",
    )

    assert rows[0] == ["Item", "Previous INR", "Current INR", "Change INR", "Change pp", "Presence", "Status"]
    assert rows[1][0].text == "Equity"
    assert rows[1][1:] == ["70000", "75000", "5000", "5", "CONTINUING", "COMPARABLE"]


def test_monthly_comparison_rows_show_withheld_status_without_fabricating_values():
    rows = _monthly_comparison_rows(
        {"comparisons": {"market_cap": {"status": "WITHHELD_OR_NOT_COMPARABLE", "items": []}}},
        "market_cap",
        "exposure_inr",
        "weight_of_total_portfolio_pct",
    )

    assert rows[1] == ["WITHHELD_OR_NOT_COMPARABLE", "—", "—", "—", "—", "—", "Withheld"]
