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
