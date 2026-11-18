"""Refresh the shared AMFI scheme master without writing NAV observations."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from sqlalchemy import select

from app.db import NavObservation, Scheme, SessionLocal
from app.fund_taxonomy import canonical_asset_class, canonical_group, canonical_subcategory
from app.amfi_performance_taxonomy import canonical_scheme_name


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



def refresh_scheme_taxonomy(
    mappings: dict[int | str, dict[str, str]],
    now: datetime,
    *,
    session_factory: Callable = SessionLocal,
    active_days: int = 14,
    allow_verified_refinements: bool = False,
) -> dict[str, int]:
    """Fill only active missing categories using explicit AMFI code/name matches.

    AMFI's performance API currently returns base scheme names rather than
    scheme codes. Name matches are exact after removing only explicit Direct
    Plan / Regular Plan suffixes from the NAV scheme master. Every matching
    plan/option variant receives the same source category; no fuzzy matching
    or marketing-name inference is used.
    """
    if not mappings:
        raise ValueError("AMFI taxonomy refresh contains no validated scheme mappings")
    normalized_codes: dict[int, dict[str, str]] = {}
    normalized_names: dict[str, dict[str, str]] = {}
    for raw_identifier, item in mappings.items():
        group = canonical_group(item.get("category_group"))
        category = canonical_subcategory(group, item.get("category"))
        asset = canonical_asset_class(group, item.get("asset_class")) if item.get("asset_class") else (
            {"Equity Scheme": "Equity", "Debt Scheme": "Debt", "Hybrid Scheme": "Hybrid", "Other Schemes": "Other"}.get(group)
        )
        if not group or not category:
            continue
        if group != "Life Cycle Funds" and not asset:
            continue
        source = {
            "category_group": group,
            "category": category,
            "asset_class": asset,
        }
        identifier = str(raw_identifier)
        if identifier.startswith("name:"):
            base_name = canonical_scheme_name(identifier[5:])
            if base_name:
                previous = normalized_names.get(base_name)
                if previous and previous != source:
                    raise ValueError(f"AMFI taxonomy source returned conflicting categories for scheme name {base_name}")
                normalized_names[base_name] = source
            continue
        try:
            code = int(raw_identifier)
        except (TypeError, ValueError):
            continue
        if code > 0:
            previous = normalized_codes.get(code)
            if previous and previous != source:
                raise ValueError(f"AMFI taxonomy source returned conflicting categories for scheme code {code}")
            normalized_codes[code] = source

    if not normalized_codes and not normalized_names:
        raise ValueError("AMFI taxonomy mappings contain no current SEBI-allow-listed categories")

    cutoff = now.date() - timedelta(days=active_days)
    scanned = updated = already_valid = conflict = missing_scheme = inactive = 0
    unmatched_names = 0
    ambiguous_names = 0
    with session_factory() as db:
        with db.begin():
            active_codes = set(
                db.execute(
                    select(NavObservation.scheme_code)
                    .where(NavObservation.nav_date >= cutoff)
                    .distinct()
                ).scalars().all()
            )
            active_scheme_rows = [
                row
                for offset in range(0, len(active_codes), 500)
                for row in db.execute(
                    select(Scheme).where(
                        Scheme.scheme_code.in_(sorted(active_codes)[offset:offset + 500])
                    )
                ).scalars()
            ] if active_codes else []
            active_schemes = {row.scheme_code: row for row in active_scheme_rows}
            schemes_by_base_name: dict[str, list[Scheme]] = {}
            for scheme in active_scheme_rows:
                base_name = canonical_scheme_name(scheme.scheme_name)
                if base_name:
                    schemes_by_base_name.setdefault(base_name, []).append(scheme)

            def apply_source(scheme: Scheme, source: dict[str, str]) -> None:
                nonlocal scanned, updated, already_valid, conflict
                scanned += 1
                current_group = canonical_group(scheme.category_group)
                current_category = canonical_subcategory(current_group, scheme.category)
                if current_group and current_group != source["category_group"]:
                    conflict += 1
                    return
                if current_category and current_category != source["category"]:
                    verified_sectoral_refinement = (
                        allow_verified_refinements
                        and current_group == source["category_group"]
                        and current_category == "Sectoral/Thematic Fund"
                        and source["category"] in {"Sectoral Fund", "Thematic Fund"}
                    )
                    if not verified_sectoral_refinement:
                        conflict += 1
                        return
                    scheme.category = source["category"]
                    scheme.asset_class = source["asset_class"]
                    updated += 1
                    return
                if current_group and current_category:
                    already_valid += 1
                    return
                scheme.category_group = source["category_group"]
                scheme.category = source["category"]
                scheme.asset_class = source["asset_class"]
                updated += 1

            for code, source in normalized_codes.items():
                scheme = active_schemes.get(code)
                if scheme is None:
                    if code in active_codes:
                        continue
                    exists = db.get(Scheme, code)
                    if exists is None:
                        missing_scheme += 1
                    else:
                        inactive += 1
                    continue
                apply_source(scheme, source)

            for base_name, source in normalized_names.items():
                matches = schemes_by_base_name.get(base_name, [])
                if not matches:
                    unmatched_names += 1
                    continue
                matched_amcs = {((scheme.amc or "").strip().casefold()) for scheme in matches}
                if len(matched_amcs) > 1:
                    # If an exact base name is shared across AMCs, the source
                    # record is ambiguous because it does not expose AMC ID.
                    ambiguous_names += 1
                    continue
                for scheme in matches:
                    apply_source(scheme, source)

    return {
        "source_mappings": len(normalized_codes) + len(normalized_names),
        "active_schemes_scanned": scanned,
        "category_rows_updated": updated,
        "already_valid": already_valid,
        "source_conflicts": conflict,
        "scheme_codes_not_in_master": missing_scheme,
        "not_active_in_nav_window": inactive,
        "source_names_unmatched": unmatched_names,
        "source_names_ambiguous": ambiguous_names,
    }
