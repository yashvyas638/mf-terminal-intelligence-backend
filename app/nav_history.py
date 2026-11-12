"""Strict parser for AMFI's historical eight-column NAV text layout.

This parser is intentionally separate from NAVAll.txt parsing. It validates
field positions rather than guessing between the latest-feed and archive
formats. It does not make HTTP requests or persist financial data.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.nav_ingest import NavRecord, _clean

AMFI_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
MAX_HISTORY_PAYLOAD_BYTES = 30_000_000


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


def parse_amfi_history_text(payload: str) -> tuple[list[NavRecord], dict[str, Any]]:
    """Parse code;name;ISIN1;ISIN2;NAV;repurchase;sale;date rows."""
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

    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(";")]
        first = parts[0].lower()
        if first in {"scheme code", "scheme_code"}:
            # Require the archive's distinctive eight-column header.
            header = ";".join(parts).lower()
            if "scheme name" not in header or "net asset value" not in header or "date" not in header:
                raise ValueError("unrecognised AMFI historical header")
            header_seen = True
            continue
        if len(parts) < 8:
            if parts[0] and parts[0][0].isdigit():
                candidates += 1
                issues.append({"line": line_number, "type": "invalid_nav_row", "detail": "expected eight historical fields"})
            continue
        if not parts[0].isdigit():
            # AMFI inserts human-readable scheme-type headings between blocks.
            continue
        candidates += 1
        try:
            code = int(parts[0])
            name = parts[1]
            isin_growth = _clean(parts[2])
            isin_reinvestment = _clean(parts[3])
            nav = Decimal(parts[4].replace(",", ""))
            nav_date = _parse_history_date(parts[7])
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
                issues.append({"line": line_number, "type": "duplicate_scheme_date", "scheme_code": code, "date": nav_date.isoformat()})
                continue
            seen[key] = nav
            records.append(NavRecord(code, isin_growth, isin_reinvestment, name, nav, nav_date))
        except ConflictingHistoricalNavError:
            raise
        except (ValueError, InvalidOperation, IndexError) as exc:
            issues.append({"line": line_number, "type": "invalid_nav_row", "detail": str(exc)[:180]})

    if not records:
        raise ValueError("AMFI historical response contained no valid NAV records")
    if not header_seen:
        raise ValueError("AMFI historical response is missing the recognised eight-column header")
    dates = [record.nav_date for record in records]
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
        "issues_sample": issues[:25],
        "header_verified": header_seen,
        "quality_status": "PASS_WITH_WARNINGS" if issues else "PASS",
    }
    return records, report
