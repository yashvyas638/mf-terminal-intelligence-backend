"""Strict parser for AMFI historical NAV archive layouts.

AMFI's live archive currently uses an eight-column scheme/plan/option layout.
Older archive responses use a different eight-column layout with repurchase
and sale prices. We identify the schema from its header and never guess column
positions from an unlabelled row.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.nav_ingest import NavRecord, _clean

AMFI_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
MAX_HISTORY_PAYLOAD_BYTES = 30_000_000

_SCHEMA_CURRENT = "scheme_plan_option_nav_date"
_SCHEMA_LEGACY = "scheme_isin_nav_price_date"


class ConflictingHistoricalNavError(ValueError):
    """Raised when the archive contains different NAVs for one scheme/date."""


def _parse_history_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("unsupported historical NAV date format")


def _history_schema(parts: list[str]) -> tuple[str, dict[str, int]] | None:
    """Recognise only explicitly supported AMFI eight-column header variants."""
    header = [part.strip().lower() for part in parts]
    if len(header) != 8 or header[0] not in {"scheme code", "scheme_code"}:
        return None

    if (
        header[1] in {"nav name", "scheme name"}
        and header[2] == "plan"
        and header[3] == "option"
        and "net asset value" in header[6]
        and header[7] == "date"
    ):
        return _SCHEMA_CURRENT, {
            "code": 0,
            "name": 1,
            "plan": 2,
            "option": 3,
            "isin_growth": 4,
            "isin_reinvestment": 5,
            "nav": 6,
            "date": 7,
        }

    if (
        header[1] == "scheme name"
        and "net asset value" in header[4]
        and header[5] == "repurchase price"
        and header[6] == "sale price"
        and header[7] == "date"
    ):
        return _SCHEMA_LEGACY, {
            "code": 0,
            "name": 1,
            "isin_growth": 2,
            "isin_reinvestment": 3,
            "nav": 4,
            "date": 7,
        }

    return None


def parse_amfi_history_text(payload: str) -> tuple[list[NavRecord], dict[str, Any]]:
    """Parse a recognised AMFI archive header and its eight-column NAV rows."""
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("AMFI historical response is empty")
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_HISTORY_PAYLOAD_BYTES:
        raise ValueError("AMFI historical response exceeds the 30 MB safety limit")
    prefix = payload.lstrip("\ufeff \t\r\n")[:512].lower()
    if "<html" in prefix or prefix.startswith("<!doctype"):
        raise ValueError("AMFI historical endpoint returned HTML instead of NAV text")

    records: list[NavRecord] = []
    issues: list[dict[str, Any]] = []
    seen: dict[tuple[int, date], Decimal] = {}
    lines = payload.lstrip("\ufeff").splitlines()
    candidates = 0
    header_seen = False
    schema_variant: str | None = None
    columns: dict[str, int] | None = None

    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(";")]
        first = parts[0].lower()

        if first in {"scheme code", "scheme_code"}:
            recognised = _history_schema(parts)
            if recognised is None:
                raise ValueError("AMFI historical response has an unrecognised eight-column header")
            variant, mapping = recognised
            if schema_variant is not None and schema_variant != variant:
                raise ValueError("AMFI historical response changes archive schema within one payload")
            schema_variant = variant
            columns = mapping
            header_seen = True
            continue

        if not parts[0].isdigit():
            # AMC and scheme-category section labels are not NAV records.
            continue

        candidates += 1
        if columns is None:
            issues.append({
                "line": line_number,
                "type": "invalid_nav_row",
                "detail": "data row appeared before a recognised archive header",
            })
            continue
        if len(parts) != 8:
            issues.append({
                "line": line_number,
                "type": "invalid_nav_row",
                "detail": "expected exactly eight historical fields",
            })
            continue

        try:
            code = int(parts[columns["code"]])
            name = parts[columns["name"]]
            isin_growth = _clean(parts[columns["isin_growth"]])
            isin_reinvestment = _clean(parts[columns["isin_reinvestment"]])
            nav = Decimal(parts[columns["nav"]].replace(",", ""))
            nav_date = _parse_history_date(parts[columns["date"]])
            plan_type = _clean(parts[columns["plan"]]) if "plan" in columns else None
            option_type = _clean(parts[columns["option"]]) if "option" in columns else None

            if code <= 0 or not name or not nav.is_finite() or nav <= 0:
                raise ValueError("scheme code, name and positive NAV are required")
            if nav_date > date.today():
                raise ValueError("NAV date cannot be in the future")

            key = (code, nav_date)
            if key in seen:
                if seen[key] != nav:
                    raise ConflictingHistoricalNavError(
                        f"conflicting historical NAV for scheme {code} on {nav_date.isoformat()}"
                    )
                issues.append({
                    "line": line_number,
                    "type": "duplicate_scheme_date",
                    "scheme_code": code,
                    "date": nav_date.isoformat(),
                })
                continue
            seen[key] = nav
            records.append(NavRecord(
                code,
                isin_growth,
                isin_reinvestment,
                name,
                nav,
                nav_date,
                plan_type=plan_type,
                option_type=option_type,
            ))
        except ConflictingHistoricalNavError:
            raise
        except (ValueError, InvalidOperation, IndexError) as exc:
            issues.append({
                "line": line_number,
                "type": "invalid_nav_row",
                "detail": str(exc)[:180],
            })

    if not header_seen or columns is None or schema_variant is None:
        raise ValueError("AMFI historical response is missing a recognised eight-column header")
    if not records:
        raise ValueError("AMFI historical response contained no valid NAV records")

    dates = [record.nav_date for record in records]
    invalid_issue_counts: dict[str, int] = {}
    for issue in issues:
        if issue["type"] == "invalid_nav_row":
            detail = str(issue.get("detail", "unknown"))
            invalid_issue_counts[detail] = invalid_issue_counts.get(detail, 0) + 1
    report = {
        "source_url": AMFI_HISTORY_URL,
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "lines_total": len(lines),
        "candidate_data_lines": candidates,
        "records_valid": len(records),
        "unique_scheme_codes": len({record.scheme_code for record in records}),
        "min_nav_date": min(dates).isoformat(),
        "max_nav_date": max(dates).isoformat(),
        "duplicate_rows_skipped": sum(item["type"] == "duplicate_scheme_date" for item in issues),
        "invalid_rows": sum(item["type"] == "invalid_nav_row" for item in issues),
        "invalid_issue_counts": invalid_issue_counts,
        "issues_sample": issues[:25],
        "header_verified": header_seen,
        "schema_variant": schema_variant,
        "quality_status": "PASS_WITH_WARNINGS" if issues else "PASS",
    }
    return records, report
