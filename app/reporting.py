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
    story.extend([
        Paragraph("Underlying holdings look-through", styles["SectionHeading"]),
        Paragraph(
            "Coverage: " + _text((lookthrough.get("coverage") or {}).get("status"))
            + " · Fresh covered weight: " + _text((lookthrough.get("coverage") or {}).get("fresh_covered_weight_pct")),
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
    for item in (allocation.get("schemes") or [])[:40]:
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
        Paragraph("Allocation and AMC concentration", styles["SectionHeading"]),
        Paragraph(
            "Status: " + _text(allocation_intelligence.get("status"))
            + " · Valuation as of: " + _text(allocation_intelligence.get("valuation_date")),
            styles["SmallNote"],
        ),
        _table(allocation_rows, [49 * mm, 34 * mm, 34 * mm, 25 * mm, 20 * mm]),
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
            + " · Top 3 AMC share: " + _text(amc.get("top_3_amc_weight_pct")),
            styles["SmallNote"],
        ),
        _table(amc_rows, [75 * mm, 45 * mm, 42 * mm]),
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
            + " · Classified coverage: " + _text(market_cap.get("classified_coverage_of_positive_lookthrough_pct"))
            + " · As of: " + _text(market_cap.get("as_of_date")),
            styles["SmallNote"],
        ),
        _table(market_cap_rows, [58 * mm, 35 * mm, 35 * mm, 35 * mm]),
    ])

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
        source_rows.append([
            Paragraph(_text(source.get("title")), styles["SmallNote"]),
            _text(source.get("as_of_date") or source.get("effective_nav_date") or source.get("retrieved_at")),
            Paragraph(_text(source.get("url")), styles["SmallNote"]),
        ])
    story.extend([Paragraph("Source references", styles["SectionHeading"]), _table(source_rows, [55 * mm, 40 * mm, 70 * mm])])

    limitations = report.get("limitations") or []
    story.append(Paragraph("Methodology and limitations", styles["SectionHeading"]))
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
