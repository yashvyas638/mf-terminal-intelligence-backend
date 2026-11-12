"""Refresh the shared AMFI scheme master without writing NAV observations."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from sqlalchemy import select

from app.db import Scheme, SessionLocal


def refresh_scheme_metadata(
    records: Iterable[Any],
    now: datetime,
    *,
    session_factory: Callable = SessionLocal,
) -> dict[str, int]:
    """Upsert source-provided scheme metadata from a validated current AMFI feed.

    This operation deliberately does not create NAV observations or research
    snapshots. Category fields are updated only when the parser has seen an
    explicit AMFI category section; an explicitly unclassified section clears
    stale category values rather than inheriting a previous fund label.
    """
    latest_by_code: dict[int, Any] = {}
    for record in records:
        current = latest_by_code.get(record.scheme_code)
        if current is None or record.nav_date >= current.nav_date:
            latest_by_code[record.scheme_code] = record

    if not latest_by_code:
        raise ValueError("AMFI metadata refresh contains no unique scheme records")

    codes = sorted(latest_by_code)
    created = updated = category_metadata_seen = classified = unclassified = 0
    plan_populated = option_populated = amc_populated = 0

    with session_factory() as db:
        with db.begin():
            existing = {
                row.scheme_code: row
                for offset in range(0, len(codes), 500)
                for row in db.execute(
                    select(Scheme).where(Scheme.scheme_code.in_(codes[offset:offset + 500]))
                ).scalars()
            }

            for code, record in latest_by_code.items():
                scheme = existing.get(code)
                if scheme is None:
                    scheme = Scheme(
                        scheme_code=code,
                        scheme_name=record.scheme_name,
                        isin_growth=record.isin_growth,
                        isin_dividend_reinvestment=record.isin_dividend_reinvestment,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    db.add(scheme)
                    existing[code] = scheme
                    created += 1
                else:
                    updated += 1
                    scheme.scheme_name = record.scheme_name
                    scheme.isin_growth = record.isin_growth or scheme.isin_growth
                    scheme.isin_dividend_reinvestment = (
                        record.isin_dividend_reinvestment
                        or scheme.isin_dividend_reinvestment
                    )
                    scheme.last_seen_at = now

                if record.plan_type:
                    scheme.plan_type = record.plan_type
                    plan_populated += 1
                if record.option_type:
                    scheme.option_type = record.option_type
                    option_populated += 1
                if record.amc:
                    scheme.amc = record.amc
                    amc_populated += 1
                if record.metadata_present:
                    category_metadata_seen += 1
                    scheme.structure = record.structure
                    scheme.category_group = record.category_group
                    scheme.category = record.category
                    scheme.asset_class = record.asset_class
                    if record.category_group:
                        classified += 1
                    else:
                        unclassified += 1

            db.flush()

    return {
        "scheme_records_seen": len(latest_by_code),
        "scheme_rows_created": created,
        "scheme_rows_updated": updated,
        "category_metadata_seen": category_metadata_seen,
        "category_group_populated": classified,
        "category_unclassified": unclassified,
        "plan_type_populated": plan_populated,
        "option_type_populated": option_populated,
        "amc_populated": amc_populated,
    }
