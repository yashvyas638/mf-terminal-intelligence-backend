"""Strict parser for official NSE Indices historical TRI/NTR CSV exports.

The supported ingestion contract is the CSV export exposed by the official
Nifty Indices Historical Data page. No undocumented HTTP endpoint is assumed.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO


NIFTY_HISTORICAL_DATA_URL = "https://www.niftyindices.com/reports/historical-data"
MAX_CSV_BYTES = 5_000_000
MAX_CSV_ROWS = 20_000


@dataclass(frozen=True)
class BenchmarkPoint:
    observation_date: date
    index_value: Decimal


def _normalise_header(value: str) -> str:
    return "".join(character.lower() for character in value.strip().lstrip("\ufeff") if character.isalnum())


def _parse_date(value: str) -> date:
    cleaned = value.strip()
    for pattern in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported benchmark date format: {cleaned!r}")


def _parse_value(value: str) -> Decimal:
    cleaned = value.strip().replace(",", "")
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid benchmark index value: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("benchmark index values must be finite and positive")
    quantized = parsed.quantize(Decimal("0.00000001"))
    if quantized != parsed or quantized <= 0:
        raise ValueError("benchmark index values must be exactly representable to eight decimal places")
    return quantized


def parse_nifty_tri_csv(csv_text: str, variant: str) -> tuple[list[BenchmarkPoint], dict]:
    """Parse TRI or NTR CSV output and reject ambiguous/malformed source data."""
    if variant not in {"TRI", "NTR"}:
        raise ValueError("only TRI and NTR benchmark variants are accepted")
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("benchmark CSV is empty")
    if len(csv_text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("benchmark CSV exceeds the 5 MB safety limit")

    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("benchmark CSV header is missing")
    headers = {_normalise_header(name): name for name in reader.fieldnames if name}
    date_header = headers.get("date")
    value_header = headers.get("totalreturnsindex" if variant == "TRI" else "nettotalreturnindex")
    name_header = headers.get("indexname") or headers.get("index")
    if not date_header or not value_header:
        expected = "Total Returns Index" if variant == "TRI" else "Net Total Return Index"
        raise ValueError(f"benchmark CSV must contain Date and {expected} columns")
    if not name_header:
        raise ValueError("official benchmark CSV must contain an IndexName column")

    points_by_date: dict[date, Decimal] = {}
    source_names: set[str] = set()
    rows_seen = 0
    duplicate_rows = 0
    for row_number, row in enumerate(reader, start=2):
        if not row or not any((value or "").strip() for value in row.values()):
            continue
        rows_seen += 1
        if rows_seen > MAX_CSV_ROWS:
            raise ValueError("benchmark CSV exceeds the 20,000-row safety limit")
        try:
            observed_date = _parse_date(row.get(date_header) or "")
            if observed_date > date.today():
                raise ValueError("benchmark observation date cannot be in the future")
            index_value = _parse_value(row.get(value_header) or "")
        except ValueError as exc:
            raise ValueError(f"invalid benchmark CSV row {row_number}: {exc}") from exc
        if name_header and (row.get(name_header) or "").strip():
            source_names.add((row.get(name_header) or "").strip())
        previous = points_by_date.get(observed_date)
        if previous is not None:
            if previous != index_value:
                raise ValueError(
                    f"conflicting duplicate benchmark values for {observed_date.isoformat()}"
                )
            duplicate_rows += 1
            continue
        points_by_date[observed_date] = index_value

    if not points_by_date:
        raise ValueError("benchmark CSV contains no valid observations")
    if not source_names:
        raise ValueError("benchmark CSV contains no IndexName values")
    if len(source_names) > 1:
        raise ValueError("benchmark CSV contains multiple index names")
    points = [
        BenchmarkPoint(observation_date=observed_date, index_value=value)
        for observed_date, value in sorted(points_by_date.items())
    ]
    return points, {
        "rows_seen": rows_seen,
        "observations": len(points),
        "duplicate_rows_skipped": duplicate_rows,
        "min_date": points[0].observation_date.isoformat(),
        "max_date": points[-1].observation_date.isoformat(),
        "source_index_name": next(iter(source_names)) if source_names else None,
        "variant": variant,
    }
