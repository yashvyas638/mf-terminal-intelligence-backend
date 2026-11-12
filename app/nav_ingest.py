"""AMFI NAV snapshot parser and validation helpers."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# Use AMFI's portal host directly. The www host has historically redirected and
# can return a non-feed response to automated clients.
AMFI_NAV_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"


class ConflictingDuplicateNavError(ValueError):
    """Raised when one feed assigns different NAVs to the same scheme/date."""


@dataclass(frozen=True)
class NavRecord:
    scheme_code: int
    isin_growth: str | None
    isin_dividend_reinvestment: str | None
    scheme_name: str
    nav: Decimal
    nav_date: date
    plan_type: str | None = None
    option_type: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["nav"] = str(self.nav)
        result["nav_date"] = self.nav_date.isoformat()
        return result


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    # AMFI uses a literal hyphen when an ISIN is unavailable.
    return None if not value or value == "-" else value


def parse_amfi_nav_text(payload: str) -> tuple[list[NavRecord], dict[str, Any]]:
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("AMFI response is empty")
    if len(payload) > 30_000_000:
        raise ValueError("AMFI response exceeds the 30 MB safety limit")
    prefix = payload.lstrip("\ufeff \t\r\n")[:512].lower()
    if "<html" in prefix or prefix.startswith("<!doctype"):
        raise ValueError("AMFI endpoint returned HTML instead of the NAV text feed")
    records: list[NavRecord] = []
    issues: list[dict[str, Any]] = []
    seen: dict[tuple[int, date], Decimal] = {}
    lines = payload.lstrip("\ufeff").splitlines()
    data_lines = 0
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith(("Scheme Code", "Open Ended Schemes", "Close Ended Schemes", "Interval Fund")):
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 6:
            # Ignore section headings, but account for malformed candidate data rows.
            if parts[0] and parts[0][0].isdigit():
                data_lines += 1
                issues.append({"line": line_number, "type": "invalid_nav_row", "detail": "expected at least six semicolon-delimited fields"})
            continue
        data_lines += 1
        try:
            code = int(parts[0])
            # AMFI expanded NAVAll.txt from 6 to 8 columns by inserting
            # separate Plan and Option fields before NAV. Keep compatibility
            # with archived/legacy 6-column payloads.
            if len(parts) >= 8:
                plan, option = parts[4], parts[5]
                name_parts = [parts[3], plan, option]
                name = " - ".join(part for part in name_parts if part)
                nav_value, date_value = parts[6], parts[7]
            else:
                name = parts[3]
                nav_value, date_value = parts[4], parts[5]
            nav = Decimal(nav_value.replace(",", ""))
            nav_date = datetime.strptime(date_value, "%d-%b-%Y").date()
            if code <= 0 or not name or not nav.is_finite() or nav <= 0:
                raise ValueError("scheme code, name, and NAV must be valid and NAV must be positive")
            if nav_date > date.today():
                raise ValueError("NAV date cannot be in the future")
            key = (code, nav_date)
            if key in seen:
                if seen[key] != nav:
                    raise ConflictingDuplicateNavError(
                        f"conflicting duplicate NAV for scheme {code} on {nav_date.isoformat()}"
                    )
                issues.append({"line": line_number, "type": "duplicate_scheme_date", "scheme_code": code, "date": nav_date.isoformat()})
                continue
            seen[key] = nav
            plan_type = _clean(parts[4]) if len(parts) >= 8 else None
            option_type = _clean(parts[5]) if len(parts) >= 8 else None
            records.append(NavRecord(code, _clean(parts[1]), _clean(parts[2]), name, nav, nav_date, plan_type, option_type))
        except ConflictingDuplicateNavError:
            raise
        except (ValueError, InvalidOperation, IndexError) as exc:
            issues.append({"line": line_number, "type": "invalid_nav_row", "detail": str(exc)[:180]})
    if not records:
        raise ValueError("AMFI response contained no valid NAV records; refusing to ingest an empty snapshot")
    dates = [record.nav_date for record in records]
    report = {"source_url": AMFI_NAV_URL, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(), "lines_total": len(lines), "candidate_data_lines": data_lines, "records_valid": len(records), "unique_scheme_codes": len({record.scheme_code for record in records}), "min_nav_date": min(dates).isoformat(), "max_nav_date": max(dates).isoformat(), "duplicate_rows_skipped": sum(issue["type"] == "duplicate_scheme_date" for issue in issues), "invalid_rows": sum(issue["type"] == "invalid_nav_row" for issue in issues), "issues_sample": issues[:25], "quality_status": "PASS_WITH_WARNINGS" if issues else "PASS"}
    return records, report
