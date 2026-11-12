"""Strict parser for dated AMC/AMFI portfolio disclosure CSV exports."""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO


MAX_HOLDINGS_CSV_BYTES = 5_000_000
MAX_HOLDING_ROWS = 20_000
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")


@dataclass(frozen=True)
class HoldingPoint:
    security_id: str
    security_name: str
    is_isin: bool
    weight_pct: Decimal
    market_value_inr: Decimal | None
    asset_type: str | None
    sector: str | None


def _header_key(value: str) -> str:
    return "".join(character.lower() for character in value.strip().lstrip("\ufeff") if character.isalnum())


def _decimal_value(value: str, field: str, *, required: bool = False) -> Decimal | None:
    cleaned = (value or "").strip().replace(",", "").replace("%", "").replace("₹", "")
    if not cleaned:
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _security_id(isin: str, name: str) -> tuple[str, bool]:
    candidate = (isin or "").strip().upper()
    if candidate:
        if not ISIN_PATTERN.fullmatch(candidate):
            raise ValueError(f"invalid ISIN value: {candidate!r}")
        return candidate, True
    normalized = _header_key(name)
    if not normalized:
        raise ValueError("security name is required when ISIN is absent")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"NONISIN:{digest}", False


def parse_fund_holdings_csv(csv_text: str) -> tuple[list[HoldingPoint], dict]:
    """Parse a clean downloadable spreadsheet CSV without inventing ISIN matches."""
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("holdings CSV is empty")
    if len(csv_text.encode("utf-8")) > MAX_HOLDINGS_CSV_BYTES:
        raise ValueError("holdings CSV exceeds the 5 MB safety limit")

    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("holdings CSV header is missing")
    normalized_headers = [_header_key(name) for name in reader.fieldnames if name]
    if len(normalized_headers) != len(set(normalized_headers)):
        raise ValueError("holdings CSV contains duplicate or ambiguous column headers")
    headers = {_header_key(name): name for name in reader.fieldnames if name}

    def pick(*candidates: str) -> str | None:
        return next((headers[key] for key in candidates if key in headers), None)

    isin_header = pick("isin", "isincode", "securityisin")
    name_header = pick("nameofinstrument", "nameofsecurity", "securityname", "instrumentname", "issuername", "issuer")
    # Accept both common AMC spreadsheet labels and SEBI Format 4C (% to NAV).
    weight_header = pick(
        "tonetassets", "percenttonetassets", "percentageofnetassets",
        "netassetpercentage", "percenttonav", "percentageofnav",
        "percentagenav", "tonav", "weightpercentage",
    )
    market_header = pick(
        "marketvalueinr", "marketvalueinrupees", "marketvalueinrs",
        "marketvalueinlakhs", "marketvaluerupeesinlakhs", "marketvaluersinlakhs",
        "mktvalueinrsinlakhs", "mktvaluerupeesinlakhs", "mktvalueinlakhs",
        "mktvalueinrs", "mktvaluerupees", "mktvalue",
    )
    market_header_key = _header_key(market_header) if market_header else ""
    market_multiplier = Decimal("100000") if "lakhs" in market_header_key else Decimal("1")
    asset_header = pick("assettype", "instrumenttype", "typeofinstrument", "securitytype")
    sector_header = pick("sector", "industry", "industrysector")

    if not name_header or not weight_header:
        raise ValueError("holdings CSV must contain a security name and % to Net Assets column")

    aggregated: dict[str, dict] = {}
    rows_seen = 0
    for row_number, row in enumerate(reader, start=2):
        if not row or not any((value or "").strip() for value in row.values()):
            continue
        if None in row:
            raise ValueError(f"row {row_number}: more values than the CSV header defines")
        rows_seen += 1
        if rows_seen > MAX_HOLDING_ROWS:
            raise ValueError("holdings CSV exceeds the 20,000-row safety limit")
        name = (row.get(name_header) or "").strip()
        if not name:
            raise ValueError(f"row {row_number}: security name is missing")
        try:
            security_id, is_isin = _security_id(row.get(isin_header) or "" if isin_header else "", name)
            weight = _decimal_value(row.get(weight_header) or "", "% to Net Assets", required=True)
            raw_market_value = _decimal_value(row.get(market_header) or "", "market value") if market_header else None
            market_value = raw_market_value * market_multiplier if raw_market_value is not None else None
        except ValueError as exc:
            raise ValueError(f"invalid holdings CSV row {row_number}: {exc}") from exc
        assert weight is not None
        if weight < Decimal("-1000") or weight > Decimal("1000"):
            raise ValueError(f"row {row_number}: holding weight is outside supported bounds")
        # Reject silent numeric precision loss before storing fixed-scale values.
        if weight.quantize(Decimal("0.00000001")) != weight:
            raise ValueError(f"row {row_number}: holding weight has more than 8 decimal places")
        if market_value is not None and market_value.quantize(Decimal("0.01")) != market_value:
            raise ValueError(f"row {row_number}: market value has more than 2 decimal places")
        existing = aggregated.get(security_id)
        if existing is None:
            aggregated[security_id] = {
                "security_id": security_id,
                "security_name": name,
                "is_isin": is_isin,
                "weight_pct": weight,
                "market_value_inr": market_value,
                "asset_type": (row.get(asset_header) or "").strip() or None if asset_header else None,
                "sector": (row.get(sector_header) or "").strip() or None if sector_header else None,
            }
        else:
            for field, label in (("asset_type", "asset type"), ("sector", "sector")):
                incoming = (row.get(asset_header) or "").strip() if field == "asset_type" and asset_header else (
                    (row.get(sector_header) or "").strip() if field == "sector" and sector_header else ""
                )
                previous = existing[field]
                if incoming and previous and incoming.casefold() != previous.casefold():
                    raise ValueError(
                        f"row {row_number}: conflicting {label} values for the same security identifier"
                    )
                if incoming and not previous:
                    existing[field] = incoming
            existing["weight_pct"] += weight
            if market_value is not None:
                existing["market_value_inr"] = (existing["market_value_inr"] or Decimal("0")) + market_value

    if not aggregated:
        raise ValueError("holdings CSV contains no valid holdings")
    points = [
        HoldingPoint(
            security_id=item["security_id"],
            security_name=item["security_name"],
            is_isin=item["is_isin"],
            weight_pct=item["weight_pct"].quantize(Decimal("0.00000001")),
            market_value_inr=item["market_value_inr"].quantize(Decimal("0.01")) if item["market_value_inr"] is not None else None,
            asset_type=item["asset_type"],
            sector=item["sector"],
        )
        for item in aggregated.values()
    ]
    points.sort(key=lambda item: (not item.is_isin, item.security_id))
    return points, {
        "rows_seen": rows_seen,
        "unique_holdings": len(points),
        "isin_holdings": sum(item.is_isin for item in points),
        "non_isin_holdings": sum(not item.is_isin for item in points),
        "total_weight_pct": str(sum((item.weight_pct for item in points), Decimal("0"))),
        "weight_total_variance_from_100_pct": str(
            sum((item.weight_pct for item in points), Decimal("0")) - Decimal("100")
        ),
        "weight_total_status": (
            "RECONCILED_WITHIN_0_10_PCT"
            if abs(sum((item.weight_pct for item in points), Decimal("0")) - Decimal("100")) <= Decimal("0.10")
            else "REVIEW_REQUIRED"
        ),
    }
