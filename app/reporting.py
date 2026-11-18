"""Reproducible PDF rendering for immutable portfolio report snapshots."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _text(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return escape(str(value))


def _table(rows: list[list[object]], widths=None) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172554")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _allocation_group_rows(items: list[dict], label: str) -> list[list[object]]:
    """Build one explicit allocation dimension table from the frozen report payload."""
    rows: list[list[object]] = [[label, "Market value INR", "Portfolio weight"]]
    for item in items:
        rows.append([
            Paragraph(_text(item.get("name")), getSampleStyleSheet()["BodyText"]),
            _text(item.get("market_value_inr")),
            _text(item.get("portfolio_weight_pct")),
        ])
    if len(rows) == 1:
        rows.append(["No classified allocation rows", "—", "—"])
    return rows


def _source_reference_row(source: dict, note_style) -> list[object]:
    """Normalise the different provenance fields used by NAV and holdings sources."""
    source_type = str(source.get("source_type") or "SOURCE").replace("_", " ").title()
    source_label = source.get("title") or source.get("scheme_name") or source_type
    source_as_of = (
        source.get("as_of_date")
        or source.get("source_as_of_date")
        or source.get("max_nav_date")
        or source.get("effective_nav_date")
        or source.get("retrieved_at")
    )
    source_url = source.get("url") or source.get("source_url")
    if source.get("min_nav_date") or source.get("max_nav_date"):
        source_as_of = (
            str(source.get("min_nav_date") or "—")
            + " to "
            + str(source.get("max_nav_date") or "—")
        )
    return [
        Paragraph(_text(source_label), note_style),
        _text(source_as_of),
        Paragraph(_text(source_url), note_style),
    ]


def _monthly_comparison_rows(
    comparison: dict,
    section: str,
    value_field: str,
    weight_field: str,
    secondary_weight_field: str | None = None,
) -> list[list[object]]:
    """Flatten one frozen month-comparison section for PDF rendering."""
    headers = ["Item", "Previous INR", "Current INR", "Change INR", "Change pp A" if secondary_weight_field else "Change pp"]
    if secondary_weight_field:
        headers.append("Change pp B")
    headers.extend(["Presence", "Status"])
    rows: list[list[object]] = [headers]
    section_data = comparison.get("comparisons", {}).get(section) or {}
    empty_row = [section_data.get("status") or "NOT_AVAILABLE", "—", "—", "—", "—"]
    if secondary_weight_field:
        empty_row.append("—")
    empty_row.extend(["—", "Withheld"])
    if section_data.get("status") != "COMPARABLE":
        rows.append(empty_row)
        return rows
    for item in section_data.get("items") or []:
        metrics = item.get("metrics") or {}
        value = metrics.get(value_field) or {}
        weight = metrics.get(weight_field) or {}
        row = [
            Paragraph(_text(item.get("key")), getSampleStyleSheet()["BodyText"]),
            _text(value.get("previous")),
            _text(value.get("current")),
            _text(value.get("change_inr") if value.get("change_inr") is not None else value.get("change")),
            _text(weight.get("change_percentage_points")),
        ]
        if secondary_weight_field:
            secondary_weight = metrics.get(secondary_weight_field) or {}
            row.append(_text(secondary_weight.get("change_percentage_points")))
        row.extend([
            _text(item.get("presence_status")),
            _text(value.get("status")),
        ])
        rows.append(row)
    if len(rows) == 1:
        rows.append(["No comparable rows", *(["—"] * (len(headers) - 1))])
    return rows


def _monthly_target_drift_rows(comparison: dict) -> list[list[object]]:
    """Render policy-comparable allocation drift in percentage points, never INR."""
    section = comparison.get("comparisons", {}).get("target_drift") or {}
    rows: list[list[object]] = [[
        "Dimension / bucket", "Previous drift pp", "Current drift pp",
        "Change pp", "Previous actual %", "Current actual %", "Status",
    ]]
    if section.get("status") != "COMPARABLE":
        rows.append([
            Paragraph(_text(section.get("reason") or section.get("status") or "Target drift unavailable"), getSampleStyleSheet()["BodyText"]),
            "—", "—", "—", "—", "—", "Withheld",
        ])
        return rows
    for item in section.get("items") or []:
        metrics = item.get("metrics") or {}
        drift = metrics.get("drift_percentage_points") or {}
        actual = metrics.get("actual_weight_pct") or {}
        rows.append([
            Paragraph(_text(item.get("key")), getSampleStyleSheet()["BodyText"]),
            _text(drift.get("previous")),
            _text(drift.get("current")),
            _text(drift.get("change_percentage_points")),
            _text(actual.get("previous")),
            _text(actual.get("current")),
            _text(drift.get("status")),
        ])
    if len(rows) == 1:
        rows.append(["No comparable target buckets", "—", "—", "—", "—", "—", "—"])
    return rows


def build_portfolio_report_pdf(report: dict) -> bytes:
    """Render a compact, source-linked report; source values remain in the JSON snapshot."""
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Portfolio report — {report.get('portfolio_name', 'Portfolio')}",
        author="Mutual Fund Intelligence Terminal",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#172554"),
        fontSize=19,
        leading=23,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#172554"),
        fontSize=12,
        leading=15,
        spaceBefore=12,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="SmallNote",
        parent=styles["BodyText"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#475569"),
        wordWrap="CJK",
    ))

    story = [
        Paragraph("PORTFOLIO INTELLIGENCE REPORT", styles["ReportTitle"]),
        Paragraph(_text(report.get("portfolio_name", "Portfolio")), styles["Heading2"]),
        Paragraph(
            "Generated " + _text(report.get("generated_at"))
            + " · Version " + _text(report.get("report_version"))
            + " · Currency INR",
            styles["SmallNote"],
        ),
        Spacer(1, 8),
    ]

    snapshot_consistency = report.get("snapshot_consistency") or {}
    story.append(Paragraph(
        "Snapshot consistency: " + _text(snapshot_consistency.get("status"))
        + " · Baseline valuation: " + _text(snapshot_consistency.get("baseline_valuation_value_inr"))
        + " · As of: " + _text(snapshot_consistency.get("baseline_valuation_date")),
        styles["SmallNote"],
    ))

    valuation = report.get("valuation") or {}
    summary = [
        ["Portfolio metric", "Value"],
        ["Current market value", _text(valuation.get("current_value"))],
        ["Remaining cost basis", _text(valuation.get("remaining_cost_basis"))],
        ["Realized gain / loss", _text(valuation.get("realized_gain_loss"))],
        ["Unrealized gain / loss", _text(valuation.get("unrealized_gain_loss"))],
        ["Total gain / loss", _text(valuation.get("total_gain_loss"))],
        ["Portfolio XIRR", _text(valuation.get("xirr"))],
        ["Valuation as of", _text(valuation.get("valuation_date"))],
    ]
    story.extend([Paragraph("Portfolio summary", styles["SectionHeading"]), _table(summary, [70 * mm, 95 * mm])])

    holdings = valuation.get("holdings") or []
    holding_rows = [["Scheme", "Units", "Market value", "Weight", "NAV date", "Freshness"]]
    for item in holdings:
        holding_rows.append([
            Paragraph(_text(item.get("scheme_name")), styles["SmallNote"]),
            _text(item.get("units")),
            _text(item.get("market_value")),
            _text(item.get("weight_pct")),
            _text(item.get("nav_date")),
            _text(item.get("freshness_status")),
        ])
    story.extend([
        Paragraph("Holdings", styles["SectionHeading"]),
        _table(holding_rows, [57 * mm, 20 * mm, 27 * mm, 18 * mm, 24 * mm, 22 * mm]),
    ])

    risk = report.get("risk") or {}
    risk_metrics = risk.get("metrics") or {}
    risk_rows = [
        ["Historical risk metric", "Value"],
        ["Status", _text(risk.get("status"))],
        ["Annualised volatility", _text(risk_metrics.get("annualized_volatility"))],
        ["Downside deviation", _text(risk_metrics.get("downside_deviation"))],
        ["Historical VaR 95%", _text(risk_metrics.get("historical_var_95"))],
        ["Historical CVaR 95%", _text(risk_metrics.get("historical_cvar_95"))],
        ["Maximum drawdown", _text(risk_metrics.get("max_drawdown"))],
        ["Worst 1D / 5D / 21D", " / ".join(_text(risk_metrics.get(key)) for key in ("worst_1d_return", "worst_5d_return", "worst_21d_return"))],
        ["Lookback", _text(risk.get("lookback_days")) + " days"],
    ]
    story.extend([Paragraph("Historical risk", styles["SectionHeading"]), _table(risk_rows, [70 * mm, 95 * mm])])

    lookthrough = report.get("lookthrough") or {}
    lookthrough_securities = lookthrough.get("top_securities") or []
    security_rows = [["Underlying security", "ISIN / ID", "Sector", "Value", "Portfolio weight", "Funds"]]
    for item in lookthrough_securities[:20]:
        security_rows.append([
            Paragraph(_text(item.get("security_name")), styles["SmallNote"]),
            _text(item.get("security_id")),
            _text(item.get("sector")),
            _text(item.get("lookthrough_value")),
            _text(item.get("portfolio_weight_pct")),
            _text(item.get("scheme_count")),
        ])
    if len(security_rows) == 1:
        security_rows.append(["No verified look-through holdings", "—", "—", "—", "—", "—"])
    lookthrough_coverage = lookthrough.get("coverage") or {}
    nav_coverage = (report.get("allocation_intelligence") or {}).get("evidence", {}).get("nav_coverage") or {}
    story.extend([
        Paragraph("Underlying holdings look-through", styles["SectionHeading"]),
        Paragraph(
            "Disclosure coverage: " + _text(lookthrough_coverage.get("status"))
            + " · Covered value INR: " + _text(lookthrough_coverage.get("covered_market_value"))
            + " · Fresh covered value INR: " + _text(lookthrough_coverage.get("fresh_covered_market_value"))
            + " · Stale covered value INR: " + _text(lookthrough_coverage.get("stale_covered_market_value"))
            + " · Covered weight: " + _text(lookthrough_coverage.get("covered_weight_pct"))
            + " · Fresh covered weight: " + _text(lookthrough_coverage.get("fresh_covered_weight_pct")),
            styles["SmallNote"],
        ),
        Paragraph(
            "Disclosure gaps: missing " + _text(len(lookthrough_coverage.get("missing_disclosure_scheme_codes") or []))
            + " schemes · stale " + _text(len(lookthrough_coverage.get("stale_disclosure_scheme_codes") or []))
            + " schemes · missing NAV " + _text(len(lookthrough_coverage.get("missing_nav_scheme_codes") or []))
            + " schemes · stale NAV " + _text(len(lookthrough_coverage.get("stale_nav_scheme_codes") or []))
            + " schemes",
            styles["SmallNote"],
        ),
        Paragraph(
            "NAV freshness: " + _text(nav_coverage.get("fresh_nav_scheme_count"))
            + " / " + _text(nav_coverage.get("active_scheme_count"))
            + " active schemes fresh (" + _text(nav_coverage.get("fresh_nav_coverage_pct"))
            + "%) · Maximum allowed NAV age: " + _text(nav_coverage.get("maximum_allowed_nav_age_days")) + " days",
            styles["SmallNote"],
        ),
        _table(security_rows, [44 * mm, 25 * mm, 31 * mm, 24 * mm, 22 * mm, 12 * mm]),
    ])
    sector_rows = [["Sector", "Look-through value", "Portfolio weight"]]
    for item in lookthrough.get("sector_exposure") or []:
        sector_rows.append([
            _text(item.get("sector")),
            _text(item.get("lookthrough_value")),
            _text(item.get("portfolio_weight_pct")),
        ])
    if len(sector_rows) == 1:
        sector_rows.append(["No verified sector exposure", "—", "—"])
    story.extend([
        Paragraph("Sector exposure", styles["SectionHeading"]),
        _table(sector_rows, [70 * mm, 50 * mm, 38 * mm]),
    ])

    allocation_intelligence = report.get("allocation_intelligence") or {}
    allocation = allocation_intelligence.get("allocation") or {}
    allocation_rows = [["Scheme / allocation group", "Category", "AMC", "Value INR", "Portfolio %"]]
    for item in (allocation.get("schemes") or []):
        allocation_rows.append([
            Paragraph(_text(item.get("scheme_name")), styles["SmallNote"]),
            _text(item.get("category_group")),
            Paragraph(_text(item.get("amc")), styles["SmallNote"]),
            _text(item.get("market_value_inr")),
            _text(item.get("portfolio_weight_pct")),
        ])
    if len(allocation_rows) == 1:
        allocation_rows.append(["Allocation unavailable", "—", "—", "—", "—"])
    story.extend([
        Paragraph("Allocation and AMC concentration · Scheme breakdown", styles["SectionHeading"]),
        Paragraph(
            "Status: " + _text(allocation_intelligence.get("status"))
            + " · Valuation as of: " + _text(allocation_intelligence.get("valuation_date"))
            + " · Schemes: " + _text(allocation.get("scheme_count"))
            + " · Unclassified schemes: " + _text((allocation.get("data_quality") or {}).get("unclassified_scheme_count"))
            + " · Unclassified value INR: " + _text((allocation.get("data_quality") or {}).get("unclassified_market_value_inr"))
            + " · Unclassified weight: " + _text((allocation.get("data_quality") or {}).get("unclassified_weight_pct"))
            + " · Fresh NAV coverage: " + _text((allocation_intelligence.get("evidence") or {}).get("nav_coverage", {}).get("fresh_nav_coverage_pct")),
            styles["SmallNote"],
        ),
        _table(allocation_rows, [49 * mm, 34 * mm, 34 * mm, 25 * mm, 20 * mm]),
        Paragraph("Category allocation", styles["SectionHeading"]),
        _table(_allocation_group_rows(allocation.get("by_category") or [], "Category"), [75 * mm, 48 * mm, 39 * mm]),
        Paragraph("Sub-category allocation", styles["SectionHeading"]),
        _table(_allocation_group_rows(allocation.get("by_sub_category") or [], "Sub-category"), [75 * mm, 48 * mm, 39 * mm]),
        Paragraph("Asset-class allocation", styles["SectionHeading"]),
        _table(_allocation_group_rows(allocation.get("by_asset_class") or [], "Asset class"), [75 * mm, 48 * mm, 39 * mm]),
    ])
    amc = allocation_intelligence.get("amc_concentration") or {}
    amc_rows = [["AMC", "Portfolio value INR", "Portfolio weight"]]
    for item in amc.get("amcs") or []:
        amc_rows.append([
            Paragraph(_text(item.get("name")), styles["SmallNote"]),
            _text(item.get("market_value_inr")),
            _text(item.get("portfolio_weight_pct")),
        ])
    if len(amc_rows) == 1:
        amc_rows.append(["AMC concentration unavailable", "—", "—"])
    story.extend([
        Paragraph(
            "AMC HHI: " + _text(amc.get("hhi_points"))
            + " · Effective AMC count: " + _text(amc.get("effective_amc_count"))
            + " · Top 1 / 3 / 5 AMC share: " + _text(amc.get("top_1_amc_weight_pct"))
            + " / " + _text(amc.get("top_3_amc_weight_pct"))
            + " / " + _text(amc.get("top_5_amc_weight_pct")),
            styles["SmallNote"],
        ),
        _table(amc_rows, [75 * mm, 45 * mm, 42 * mm]),
    ])

    target_policy = report.get("target_policy_snapshot") or {}
    target_drift = report.get("target_drift_snapshot") or {}
    target_rows = [["Dimension", "Effective date", "Version", "Bucket", "Actual %", "Target band", "Drift pp", "Status"]]
    policy_by_dimension = {item.get("dimension"): item for item in target_policy.get("dimensions") or []}
    for dimension, drift in target_drift.items():
        policy = policy_by_dimension.get(dimension) or {}
        for item in drift.get("targets") or []:
            target_rows.append([
                _text(dimension),
                _text(policy.get("effective_from")),
                _text(policy.get("version")),
                Paragraph(_text(item.get("key")), styles["SmallNote"]),
                _text(item.get("actual_weight_pct")),
                _text(item.get("min_pct")) + "–" + _text(item.get("max_pct")) + " · target " + _text(item.get("target_pct")),
                _text(item.get("drift_percentage_points")),
                _text(item.get("status")),
            ])
    if len(target_rows) == 1:
        target_rows.append(["No saved target policy", "—", "—", "—", "—", "—", "—", "—"])
    story.extend([
        Paragraph("Target policy and allocation drift", styles["SectionHeading"]),
        Paragraph(
            "Saved policy dimensions: " + _text(len(policy_by_dimension))
            + " · Versions are immutable; drift is withheld when valuation does not reconcile.",
            styles["SmallNote"],
        ),
        _table(target_rows, [20 * mm, 20 * mm, 12 * mm, 38 * mm, 17 * mm, 31 * mm, 14 * mm, 20 * mm]),
    ])

    overlap = report.get("overlap_intelligence") or {}
    duplication = overlap.get("portfolio_duplication") or {}
    overlap_rows = [["Fund A", "Fund B", "Common ISINs", "Overlap INR", "% of A", "% of B", "Status"]]
    for item in overlap.get("pairs") or []:
        overlap_rows.append([
            Paragraph(_text(item.get("scheme_a_name")), styles["SmallNote"]),
            Paragraph(_text(item.get("scheme_b_name")), styles["SmallNote"]),
            _text(item.get("common_isin_count")),
            _text(item.get("overlap_inr")),
            _text(item.get("overlap_pct_of_scheme_a_nav")),
            _text(item.get("overlap_pct_of_scheme_b_nav")),
            _text(item.get("status")),
        ])
    if len(overlap_rows) == 1:
        overlap_rows.append(["No verified pairwise overlap", "—", "—", "—", "—", "—", _text(overlap.get("status"))])
    story.extend([
        Paragraph("Fund overlap and duplicated exposure", styles["SectionHeading"]),
        Paragraph(
            "Status: " + _text(overlap.get("status"))
            + " · Duplicated exposure: " + _text(duplication.get("duplicated_exposure_inr"))
            + " · Share of gross look-through: " + _text(duplication.get("duplicated_share_of_gross_positive_lookthrough_pct")),
            styles["SmallNote"],
        ),
        _table(overlap_rows, [34 * mm, 34 * mm, 17 * mm, 23 * mm, 18 * mm, 18 * mm, 18 * mm]),
    ])
    overlap_coverage_rows = [[
        "Fund A / disclosure date", "Fund B / disclosure date",
        "Coverage A %", "Coverage B %",
        "Matched exposure A INR", "Matched exposure B INR",
    ]]
    for item in overlap.get("pairs") or []:
        overlap_coverage_rows.append([
            Paragraph(_text(item.get("scheme_a_name")) + " · " + _text(item.get("disclosure_as_of_a")), styles["SmallNote"]),
            Paragraph(_text(item.get("scheme_b_name")) + " · " + _text(item.get("disclosure_as_of_b")), styles["SmallNote"]),
            _text(item.get("disclosure_coverage_a_pct")),
            _text(item.get("disclosure_coverage_b_pct")),
            _text(item.get("matched_isin_exposure_a_inr")),
            _text(item.get("matched_isin_exposure_b_inr")),
        ])
    if len(overlap_coverage_rows) == 1:
        overlap_coverage_rows.append(["No comparable fund pairs", "—", "—", "—", "—", "—"])
    story.append(_table(overlap_coverage_rows, [40 * mm, 40 * mm, 20 * mm, 20 * mm, 30 * mm, 30 * mm]))

    market_cap = report.get("market_cap_intelligence") or {}
    market_cap_rows = [["Classification", "Exposure INR", "Portfolio weight", "Look-through weight"]]
    for item in market_cap.get("classified_distribution") or []:
        market_cap_rows.append([
            _text(item.get("market_cap_bucket")),
            _text(item.get("exposure_inr")),
            _text(item.get("weight_of_total_portfolio_pct")),
            _text(item.get("weight_of_positive_lookthrough_pct")),
        ])
    for item in market_cap.get("unclassified_exposure") or []:
        market_cap_rows.append([
            Paragraph("Unclassified · " + _text(item.get("reason")), styles["SmallNote"]),
            _text(item.get("exposure_inr")),
            _text(item.get("weight_of_total_portfolio_pct")),
            _text(item.get("weight_of_positive_lookthrough_pct")),
        ])
    if len(market_cap_rows) == 1:
        market_cap_rows.append(["Market-cap analysis withheld", "—", "—", "—"])
    story.extend([
        Paragraph("Underlying market-cap allocation", styles["SectionHeading"]),
        Paragraph(
            "Status: " + _text(market_cap.get("status"))
            + " · Classified exposure INR: " + _text(market_cap.get("classified_exposure_inr"))
            + " / Positive look-through INR: " + _text(market_cap.get("positive_lookthrough_exposure_inr"))
            + " · Classified coverage: " + _text(market_cap.get("classified_coverage_of_positive_lookthrough_pct"))
            + " · Unclassified exposure INR: " + _text(market_cap.get("unclassified_exposure_inr"))
            + " · As of: " + _text(market_cap.get("as_of_date")),
            styles["SmallNote"],
        ),
        Paragraph(
            "Reconciliation: " + _text((market_cap.get("reconciliation") or {}).get("status"))
            + " · Difference INR: " + _text((market_cap.get("reconciliation") or {}).get("difference_inr")),
            styles["SmallNote"],
        ),
        _table(market_cap_rows, [58 * mm, 35 * mm, 35 * mm, 35 * mm]),
    ])

    monthly = report.get("monthly_comparison") or {}
    monthly_rows = [
        ["Monthly comparison metric", "Previous", "Current", "Change"],
        [
            "Portfolio value INR",
            _text(monthly.get("comparisons", {}).get("portfolio_value", {}).get("previous_inr")),
            _text(monthly.get("comparisons", {}).get("portfolio_value", {}).get("current_inr")),
            _text(monthly.get("comparisons", {}).get("portfolio_value", {}).get("change_inr")),
        ],
    ]
    story.extend([
        Paragraph("Monthly portfolio comparison", styles["SectionHeading"]),
        Paragraph(
            "Status: " + _text(monthly.get("status"))
            + " · Previous period: " + _text(monthly.get("previous_period"))
            + " · Current period: " + _text(monthly.get("current_period")),
            styles["SmallNote"],
        ),
        _table(monthly_rows, [55 * mm, 37 * mm, 37 * mm, 38 * mm]),
    ])
    for section, label, value_field, weight_field, secondary_weight_field in (
        ("scheme", "Scheme movement", "market_value_inr", "portfolio_weight_pct", None),
        ("category", "Category movement", "market_value_inr", "portfolio_weight_pct", None),
        ("sub_category", "Sub-category movement", "market_value_inr", "portfolio_weight_pct", None),
        ("asset_class", "Asset-class movement", "market_value_inr", "portfolio_weight_pct", None),
        ("amc", "AMC movement", "market_value_inr", "portfolio_weight_pct", None),
        ("market_cap", "Market-cap movement", "exposure_inr", "weight_of_total_portfolio_pct", None),
        ("sector", "Sector movement", "lookthrough_value", "portfolio_weight_pct", None),
        ("overlap_pairs", "Pairwise fund-overlap movement", "overlap_inr", "overlap_pct_of_scheme_a_nav", "overlap_pct_of_scheme_b_nav"),
    ):
        widths = (
            [31 * mm, 20 * mm, 20 * mm, 20 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm]
            if secondary_weight_field else
            [38 * mm, 24 * mm, 24 * mm, 24 * mm, 18 * mm, 22 * mm, 22 * mm]
        )
        story.extend([
            Paragraph(label, styles["Heading3"]),
            _table(
                _monthly_comparison_rows(monthly, section, value_field, weight_field, secondary_weight_field),
                widths,
            ),
        ])
    story.extend([
        Paragraph("Target allocation drift movement", styles["Heading3"]),
        _table(
            _monthly_target_drift_rows(monthly),
            [43 * mm, 20 * mm, 20 * mm, 18 * mm, 20 * mm, 20 * mm, 24 * mm],
        ),
    ])

    amc_metrics = monthly.get("comparisons", {}).get("amc_concentration_metrics") or {}
    amc_metric_rows = [["AMC concentration metric", "Previous", "Current", "Change"]]
    for key, item in amc_metrics.items():
        amc_metric_rows.append([
            _text(key.replace("_", " ").title()),
            _text(item.get("previous")),
            _text(item.get("current")),
            _text(item.get("change_percentage_points") if item.get("change_percentage_points") is not None else item.get("change")),
        ])
    if len(amc_metric_rows) == 1:
        amc_metric_rows.append(["AMC metrics unavailable", "—", "—", "—"])
    duplication = monthly.get("comparisons", {}).get("portfolio_duplication") or {}
    amc_metric_rows.append([
        "Portfolio duplicated exposure INR",
        _text(duplication.get("previous_inr")),
        _text(duplication.get("current_inr")),
        _text(duplication.get("change_inr")),
    ])
    story.extend([
        Paragraph("AMC concentration and duplication movement", styles["Heading3"]),
        _table(amc_metric_rows, [65 * mm, 38 * mm, 38 * mm, 35 * mm]),
    ])

    risk_changes = monthly.get("risk_changes") or {}
    risk_rows = [["Historical risk metric", "Previous", "Current", "Change", "Status"]]
    for key, item in risk_changes.items():
        risk_rows.append([
            _text(key.replace("_", " ").title()),
            _text(item.get("previous")),
            _text(item.get("current")),
            _text(item.get("change")),
            _text(item.get("status")),
        ])
    if len(risk_rows) == 1:
        risk_rows.append(["Risk comparison unavailable", "—", "—", "—", "—"])
    story.extend([
        Paragraph("Historical risk movement", styles["Heading3"]),
        _table(risk_rows, [48 * mm, 30 * mm, 30 * mm, 30 * mm, 36 * mm]),
    ])

    coverage = monthly.get("comparisons", {}).get("data_coverage") or {}
    coverage_rows = [["Coverage measure", "Previous %", "Current %", "Change pp", "Status"]]
    for key, item in coverage.items():
        coverage_rows.append([
            _text(key.replace("_", " ").title()),
            _text(item.get("previous_pct")),
            _text(item.get("current_pct")),
            _text(item.get("change_percentage_points")),
            _text(item.get("status")),
        ])
    if len(coverage_rows) == 1:
        coverage_rows.append(["Coverage comparison unavailable", "—", "—", "—", "—"])
    story.extend([
        Paragraph("Data coverage movement", styles["Heading3"]),
        _table(coverage_rows, [48 * mm, 27 * mm, 27 * mm, 30 * mm, 42 * mm]),
    ])
    if monthly.get("limitations"):
        for limitation in monthly.get("limitations") or []:
            story.append(Paragraph("• " + _text(limitation), styles["SmallNote"]))

    tax = report.get("fifo_tax_lots") or {}
    tax_rows = [
        ["FIFO capital gains metric", "Value"],
        ["Realized gain / loss", _text(tax.get("realized_gain_loss"))],
        ["Unrealized gain / loss", _text(tax.get("unrealized_gain_loss"))],
        ["Realized lot matches", _text(tax.get("realized_lot_count"))],
        ["Open acquisition lots", _text(tax.get("open_lot_count"))],
        ["Tax status", _text(tax.get("tax_status"))],
    ]
    story.extend([Paragraph("Capital gains ledger (pre-tax)", styles["SectionHeading"]), _table(tax_rows, [70 * mm, 95 * mm])])

    sources = report.get("sources") or []
    source_rows = [["Source", "As-of / retrieval", "Reference"]]
    for source in sources:
        source_rows.append(_source_reference_row(source, styles["SmallNote"]))
    story.extend([Paragraph("Source references", styles["SectionHeading"]), _table(source_rows, [55 * mm, 40 * mm, 70 * mm])])

    methodology = report.get("methodology") or {}
    methodology_rows = [["Methodology component", "Version / method"]]
    for key, value in methodology.items():
        methodology_rows.append([
            _text(key.replace("_", " ").title()),
            Paragraph(_text(value), styles["SmallNote"]),
        ])
    if len(methodology_rows) == 1:
        methodology_rows.append(["Methodology details", "Not recorded in this snapshot"])
    limitations = report.get("limitations") or []
    story.extend([
        Paragraph("Methodology and limitations", styles["SectionHeading"]),
        _table(methodology_rows, [48 * mm, 117 * mm]),
    ])
    for limitation in limitations:
        story.append(Paragraph("• " + _text(limitation), styles["SmallNote"]))
        story.append(Spacer(1, 2))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "For research and information only. Historical NAV-based metrics are not forecasts. "
        "The FIFO ledger is pre-tax; no tax liability is calculated. This report is not "
        "personalised investment or tax advice.",
        styles["SmallNote"],
    ))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(15 * mm, 9 * mm, "Mutual Fund Intelligence Terminal · Source-linked snapshot")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
