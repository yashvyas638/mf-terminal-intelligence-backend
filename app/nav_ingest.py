"""AMFI NAV snapshot parser and validation helpers."""
from __future__ import annotations

import hashlib
import re
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
    amc: str | None = None
    structure: str | None = None
    category_group: str | None = None
    category: str | None = None
    asset_class: str | None = None
    metadata_present: bool = False

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["nav"] = str(self.nav)
        result["nav_date"] = self.nav_date.isoformat()
        return result


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    # AMFI uses a literal hyphen when an ISIN is unavailable.
    return None if not value or value == "-" else value


def _classify_amfi_category(raw_category: str) -> tuple[str | None, str | None, str | None]:
    """Map AMFI section labels to broad SEBI group and optional sub-category."""
    raw = " ".join(raw_category.strip().split())
    group_raw, separator, subcategory = raw.partition(" - ")
    key = group_raw.casefold().replace("&", "and").strip()
    if any(token in key for token in ("equity", "growth", "elss")):
        group, asset = "Equity Scheme", "Equity"
    elif any(token in key for token in ("debt", "income", "liquid", "gilt", "money market", "floating rate")):
        group, asset = "Debt Scheme", "Debt"
    elif any(token in key for token in ("hybrid", "balanced")):
        group, asset = "Hybrid Scheme", "Hybrid"
    elif any(token in key for token in ("other", "index", "etf", "exchange traded", "fund of funds", "fof", "life cycle", "solution oriented", "capital protection", "children", "retirement")):
        group, asset = "Other Scheme", "Other"
    else:
        return None, None, None
    sub = " ".join(subcategory.split()) if separator and subcategory.strip() else None
    if sub and sub.casefold() in {
        "equity scheme", "debt scheme", "hybrid scheme", "other scheme",
        "equity schemes", "debt schemes", "hybrid schemes", "other schemes",
    }:
        sub = None
    return group, sub, asset


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
    current_amc: str | None = None
    current_structure: str | None = None
    current_category_group: str | None = None
    current_category: str | None = None
    current_asset_class: str | None = None
    metadata_present = False
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.casefold().startswith("scheme code;"):
            continue
        if ";" not in line:
            section = re.match(r"^(Open|Close|Interval)\s+Ended\s+Schemes?\s*\((.*?)\)\s*$", line, re.IGNORECASE)
            if section:
                current_structure = {"open": "Open Ended", "close": "Close Ended", "interval": "Interval"}[section.group(1).casefold()]
                current_category_group, current_category, current_asset_class = _classify_amfi_category(section.group(2))
                metadata_present = True
                continue
            if re.search(r"\b(schemes|funds|etfs)\b", line, re.IGNORECASE):
                group, sub, asset = _classify_amfi_category(line)
                if group:
                    current_category_group, current_category, current_asset_class = group, sub, asset
                    metadata_present = True
                # An unrecognized section heading must never become an AMC name.
                continue
            # AMFI AMC headers are plain text, usually ending in "Mutual Fund".
            if not line.startswith(("(", "<")) and len(line) <= 200:
                current_amc = line
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 6:
            if parts[0] and parts[0][0].isdigit():
                data_lines += 1
                issues.append({"line": line_number, "type": "invalid_nav_row", "detail": "expected at least six semicolon-delimited fields"})
            continue
        data_lines += 1
        try:
            code = int(parts[0])
            if len(parts) >= 8:
                plan, option = parts[4], parts[5]
                name = " - ".join(part for part in (parts[3], plan, option) if part)
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
                    raise ConflictingDuplicateNavError(f"conflicting duplicate NAV for scheme {code} on {nav_date.isoformat()}")
                issues.append({"line": line_number, "type": "duplicate_scheme_date", "scheme_code": code, "date": nav_date.isoformat()})
                continue
            seen[key] = nav
            plan_type = _clean(parts[4]) if len(parts) >= 8 else None
            option_type = _clean(parts[5]) if len(parts) >= 8 else None
            records.append(NavRecord(
                code, _clean(parts[1]), _clean(parts[2]), name, nav, nav_date,
                plan_type, option_type, current_amc, current_structure,
                current_category_group, current_category, current_asset_class,
                metadata_present,
            ))
        except ConflictingDuplicateNavError:
            raise
        except (ValueError, InvalidOperation, IndexError) as exc:
            issues.append({"line": line_number, "type": "invalid_nav_row", "detail": str(exc)[:180]})
    if not records:
        raise ValueError("AMFI response contained no valid NAV records; refusing to ingest an empty snapshot")
    dates = [record.nav_date for record in records]
    report = {"source_url": AMFI_NAV_URL, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(), "lines_total": len(lines), "candidate_data_lines": data_lines, "records_valid": len(records), "unique_scheme_codes": len({record.scheme_code for record in records}), "min_nav_date": min(dates).isoformat(), "max_nav_date": max(dates).isoformat(), "duplicate_rows_skipped": sum(issue["type"] == "duplicate_scheme_date" for issue in issues), "invalid_rows": sum(issue["type"] == "invalid_nav_row" for issue in issues), "issues_sample": issues[:25], "quality_status": "PASS_WITH_WARNINGS" if issues else "PASS"}
    return records, report
