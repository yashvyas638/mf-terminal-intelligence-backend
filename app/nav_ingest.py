"""AMFI NAV snapshot parser and validation helpers.

Source: AMFI's public all-schemes NAV text file. This module parses a downloaded
snapshot; it does not claim the endpoint is always available or that every record
has been independently reconciled against an AMC disclosure.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"


@dataclass(frozen=True)
class NavRecord:
    scheme_code: int
    isin_growth: str | None
    isin_dividend_reinvestment: str | None
    scheme_name: str
    nav: Decimal
    nav_date: date

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["nav"] = str(self.nav)
        result["nav_date"] = self.nav_date.isoformat()
        return result


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_amfi_nav_text(payload: str) -> tuple[list[NavRecord], dict[str, Any]]:
    """Parse AMFI's semicolon-delimited NAVAll.txt response and return QA metrics."""
    records: list[NavRecord] = []
    issues: list[dict[str, Any]] = []
    seen_codes_dates: set[tuple[int, date]] = set()
    lines = payload.lstrip("\ufeff").splitlines()
    data_lines = 0

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("Scheme Code") or line.startswith("Open Ended Schemes") or line.startswith("Close Ended Schemes") or line.startswith("Interval Fund"):
            continue
        parts = [part.strip() for part in line.split(";")]
        # AMFI file also contains headings and category labels that are not NAV rows.
        if len(parts) < 6:
            continue
        data_lines += 1
        try:
            code = int(parts[0])
            name = parts[3].strip()
            nav = Decimal(parts[4].replace(",", ""))
            nav_date = datetime.strptime(parts[5], "%d-%b-%Y").date()
            if code <= 0 or not name or not nav.is_finite() or nav <= 0:
                raise ValueError("scheme code, name, and NAV must be valid and NAV must be positive")
            key = (code, nav_date)
            if key in seen_codes_dates:
                issues.append({"line": line_number, "type": "duplicate_scheme_date", "scheme_code": code, "date": nav_date.isoformat()})
                continue
            seen_codes_dates.add(key)
            records.append(NavRecord(code, _clean(parts[1]), _clean(parts[2]), name, nav, nav_date))
        except (ValueError, InvalidOperation, IndexError) as exc:
            issues.append({"line": line_number, "type": "invalid_nav_row", "detail": str(exc)[:180]})

    if not records:
        raise ValueError("AMFI response contained no valid NAV records; refusing to ingest an empty snapshot")
    codes = {r.scheme_code for r in records}
    dates = [r.nav_date for r in records]
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    report = {
        "source_url": AMFI_NAV_URL,
        "payload_sha256": digest,
        "lines_total": len(lines),
        "candidate_data_lines": data_lines,
        "records_valid": len(records),
        "unique_scheme_codes": len(codes),
        "min_nav_date": min(dates).isoformat(),
        "max_nav_date": max(dates).isoformat(),
        "duplicate_rows_skipped": sum(i["type"] == "duplicate_scheme_date" for i in issues),
        "invalid_rows": sum(i["type"] == "invalid_nav_row" for i in issues),
        "issues_sample": issues[:25],
        "quality_status": "PASS_WITH_WARNINGS" if issues else "PASS",
    }
    return records, report
