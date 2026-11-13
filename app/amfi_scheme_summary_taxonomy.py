"""Read exact scheme categories from AMFI's official Scheme Summary Documents.

Matching is strict on AMC and normalized base scheme name. Unknown, missing,
legacy, or ambiguous categories are deliberately left unclassified.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

import requests

from app.amfi_performance_taxonomy import canonical_scheme_name
from app.fund_taxonomy import SCHEME_GROUP_ASSET_CLASS, canonical_subcategory, classify_amfi_category

AMFI_BASE = "https://www.amfiindia.com"
AMFI_SCHEME_SUMMARY_BASE = "https://portal.amfiindia.com/spages"
MAX_XML_BYTES = 3_000_000
VALID_GROUPS = tuple(SCHEME_GROUP_ASSET_CLASS)


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _exact_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", canonical_scheme_name(str(value or ""))).strip()


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for name in ("data", "Data", "result", "Result", "records", "Records"):
            value = payload.get(name)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [payload]
    return []


def _field(row: dict[str, Any], *names: str) -> Any:
    wanted = {_key(name) for name in names}
    for key, value in row.items():
        if _key(key) in wanted:
            return value
    return None


def _extract_scheme_summary_fields(xml_bytes: bytes) -> dict[str, str]:
    if not xml_bytes or len(xml_bytes) > MAX_XML_BYTES:
        raise ValueError("AMFI Scheme Summary XML is empty or exceeds the size limit")
    if re.search(br"<!\s*(DOCTYPE|ENTITY)", xml_bytes, re.IGNORECASE):
        raise ValueError("AMFI Scheme Summary XML contains a forbidden declaration")

    root = ET.fromstring(xml_bytes)
    fields: dict[str, str] = {}
    for row in root.iter():
        if row.tag.split("}")[-1] != "Row":
            continue
        cells = []
        for cell in row:
            if cell.tag.split("}")[-1] != "Cell":
                continue
            for data in cell:
                if data.tag.split("}")[-1] == "Data":
                    value = html.unescape(" ".join(data.itertext()).strip())
                    if value:
                        cells.append(value)
        if cells and re.fullmatch(r"\d+(?:\.0)?", cells[0]):
            cells = cells[1:]
        if len(cells) >= 2:
            fields[_key(cells[0])] = " ".join(cells[1:])

    if root.tag.split("}")[-1] == "SchemeSummaryDocument":
        for node in root.iter():
            if len(node) == 0 and node.text and node.text.strip():
                fields[_key(node.tag.split("}")[-1])] = html.unescape(node.text.strip())
    return fields


def _scheme_summary_category_fields(fields: dict[str, str]) -> tuple[str | None, str]:
    raw_category = next(
        (
            fields[key]
            for key in (
                "categoryaspersebicategorizationcircular",
                "categoryaspersebi",
                "categoryofscheme",
                "schemecategory",
            )
            if fields.get(key)
        ),
        None,
    )
    fund_type = fields.get("fundtype") or fields.get("typeofscheme") or ""
    return raw_category, fund_type


def parse_scheme_summary_category(
    xml_bytes: bytes,
    *,
    expected_scheme_name: str,
) -> dict[str, str | None] | None:
    """Parse the explicit SEBI category field from one AMFI Scheme Summary XML."""
    fields = _extract_scheme_summary_fields(xml_bytes)
    source_name = (
        fields.get("fundname")
        or fields.get("schemename")
        or fields.get("nameofthescheme")
    )
    if source_name and _exact_name(source_name) != _exact_name(expected_scheme_name):
        raise ValueError("AMFI Scheme Summary name does not match the requested scheme")

    raw_category, fund_type = _scheme_summary_category_fields(fields)
    if not raw_category:
        return None

    lowered_type = fund_type.casefold()
    if "equity scheme" in lowered_type:
        group_hint = "Equity Scheme"
    elif "debt scheme" in lowered_type:
        group_hint = "Debt Scheme"
    elif "hybrid scheme" in lowered_type:
        group_hint = "Hybrid Scheme"
    elif "life cycle" in lowered_type:
        group_hint = "Life Cycle Funds"
    elif "fund of fund" in lowered_type or "index fund" in lowered_type or "etf" in lowered_type:
        group_hint = "Other Schemes"
    else:
        group_hint = None

    if group_hint:
        category = canonical_subcategory(group_hint, raw_category)
        if not category:
            return None
        return {
            "category_group": group_hint,
            "category": category,
            "asset_class": SCHEME_GROUP_ASSET_CLASS[group_hint],
        }

    matches = [
        (group, category)
        for group in VALID_GROUPS
        if (category := canonical_subcategory(group, raw_category)) is not None
    ]
    if len(matches) != 1:
        return None
    group, category = matches[0]
    return {
        "category_group": group,
        "category": category,
        "asset_class": SCHEME_GROUP_ASSET_CLASS[group],
    }


def fetch_amfi_scheme_summary_taxonomy(
    schemes: list[dict[str, Any]],
    *,
    session: requests.Session | None = None,
    max_requests: int = 600,
) -> dict[str, Any]:
    """Fetch exact category evidence for active missing schemes, read-only."""
    if not schemes:
        return {
            "mappings": {},
            "source_names_matched": 0,
            "source_names_unmatched": 0,
            "source_documents_missing": 0,
            "source_names_ambiguous": 0,
            "requests_made": 0,
            "category_counts": {},
            "unclassified_category_labels": {},
            "unclassified_fund_types": {},
            "source_documents_without_category": 0,
        }

    own_session = session is None
    client = session or requests.Session()
    client.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": AMFI_BASE,
        "Referer": AMFI_BASE + "/otherdata/scheme-details",
        "X-Requested-With": "XMLHttpRequest",
    })
    requests_made = 0
    mappings: dict[str, dict[str, str | None]] = {}
    matched = unmatched = documents_missing = ambiguous = 0
    category_counts: Counter[str] = Counter()
    unclassified_category_labels: Counter[str] = Counter()
    unclassified_fund_types: Counter[str] = Counter()
    source_documents_without_category = 0

    try:
        if requests_made >= max_requests:
            raise RuntimeError("AMFI scheme-summary request safety limit exceeded")
        landing = client.get(AMFI_BASE + "/otherdata/scheme-details", timeout=(8, 30))
        requests_made += 1
        landing.raise_for_status()

        if requests_made >= max_requests:
            raise RuntimeError("AMFI scheme-summary request safety limit exceeded")
        amc_response = client.get(AMFI_BASE + "/api/populate-mf", timeout=(8, 30))
        requests_made += 1
        amc_response.raise_for_status()
        amc_rows = _rows(amc_response.json())

        amc_by_name: dict[str, list[dict[str, Any]]] = {}
        for row in amc_rows:
            name = _field(row, "mfName", "mfname", "name")
            mf_id = _field(row, "mfId", "mf_id", "id")
            if name and mf_id is not None:
                amc_by_name.setdefault(_exact_name(name), []).append(row)

        targets: dict[str, dict[str, Any]] = {}
        ambiguous_target_keys: set[str] = set()
        for scheme in schemes:
            amc = str(scheme.get("amc") or "").strip()
            scheme_name = str(scheme.get("scheme_name") or "").strip()
            base_name = canonical_scheme_name(scheme_name)
            if not amc or not base_name:
                unmatched += 1
                continue
            key = _exact_name(base_name)
            existing = targets.get(key)
            if existing and _exact_name(existing["amc"]) != _exact_name(amc):
                ambiguous_target_keys.add(key)
                targets.pop(key, None)
                continue
            if key not in ambiguous_target_keys:
                targets.setdefault(key, {"base_name": base_name, "amc": amc})
        ambiguous += len(ambiguous_target_keys)

        by_amc: dict[str, list[dict[str, Any]]] = {}
        for key, target in targets.items():
            if key not in ambiguous_target_keys:
                by_amc.setdefault(_exact_name(target["amc"]), []).append(target)

        for amc_key, amc_targets in by_amc.items():
            amc_matches = amc_by_name.get(amc_key, [])
            if len(amc_matches) != 1:
                unmatched += len(amc_targets)
                continue
            mf_id = _field(amc_matches[0], "mfId", "mf_id", "id")
            if requests_made >= max_requests:
                raise RuntimeError("AMFI scheme-summary request safety limit exceeded")
            listing_response = client.get(
                AMFI_BASE + "/api/populate-scheme",
                params={"MF_ID": mf_id},
                timeout=(8, 30),
            )
            requests_made += 1
            listing_response.raise_for_status()
            listing_rows = _rows(listing_response.json())
            listing_by_name: dict[str, list[dict[str, Any]]] = {}
            for row in listing_rows:
                name = _field(row, "scheme_name", "schemeName", "name")
                scheme_id = _field(row, "scheme_id", "schemeId", "id")
                if name and scheme_id is not None:
                    listing_by_name.setdefault(_exact_name(name), []).append(row)

            for target in amc_targets:
                source_matches = listing_by_name.get(_exact_name(target["base_name"]), [])
                if not source_matches:
                    unmatched += 1
                    continue
                if len(source_matches) > 4:
                    ambiguous += 1
                    continue
                source_categories: set[tuple[str, str, str | None]] = set()
                source_document_found = False
                for source_row in source_matches:
                    scheme_id = _field(source_row, "scheme_id", "schemeId", "id")
                    if not str(scheme_id).isdigit():
                        continue

                    # AMFI Scheme Details provides an official category descriptor
                    # even for some schemes whose summary XML omits the category.
                    if requests_made >= max_requests:
                        raise RuntimeError("AMFI scheme-summary request safety limit exceeded")
                    details_response = client.get(
                        AMFI_BASE + "/api/scheme-details",
                        params={"MF_ID": mf_id, "scheme_id": scheme_id},
                        timeout=(8, 30),
                    )
                    requests_made += 1
                    if details_response.status_code != 404:
                        details_response.raise_for_status()
                        details_rows = _rows(details_response.json())
                        if details_rows:
                            source_document_found = True
                        for detail in details_rows:
                            details_name = _field(detail, "Scheme_Name", "scheme_name", "schemeName")
                            if details_name and _exact_name(details_name) != _exact_name(target["base_name"]):
                                continue
                            raw_details_category = _field(detail, "SchemeCat_Desc", "Scheme_Category", "category")
                            if not raw_details_category:
                                continue
                            group, category, asset = classify_amfi_category(str(raw_details_category))
                            if group and category:
                                source_categories.add((group, category, asset))
                            else:
                                unclassified_category_labels[str(raw_details_category)] += 1

                    if requests_made >= max_requests:
                        raise RuntimeError("AMFI scheme-summary request safety limit exceeded")
                    xml_response = client.get(
                        f"{AMFI_SCHEME_SUMMARY_BASE}/SSD_{scheme_id}.xml",
                        timeout=(8, 30),
                    )
                    requests_made += 1
                    if xml_response.status_code == 404:
                        continue
                    xml_response.raise_for_status()
                    source_document_found = True
                    try:
                        classification = parse_scheme_summary_category(
                            xml_response.content,
                            expected_scheme_name=target["base_name"],
                        )
                    except (ET.ParseError, ValueError):
                        ambiguous += 1
                        continue
                    if classification:
                        source_categories.add((
                            classification["category_group"] or "",
                            classification["category"] or "",
                            classification["asset_class"],
                        ))
                    else:
                        fields = _extract_scheme_summary_fields(xml_response.content)
                        raw_category, raw_fund_type = _scheme_summary_category_fields(fields)
                        if raw_category:
                            unclassified_category_labels[raw_category] += 1
                        else:
                            source_documents_without_category += 1
                        if raw_fund_type:
                            unclassified_fund_types[raw_fund_type] += 1
                if not source_document_found:
                    documents_missing += 1
                    continue
                if len(source_categories) != 1:
                    if len(source_categories) > 1:
                        ambiguous += 1
                    else:
                        unmatched += 1
                    continue
                group, category, asset = next(iter(source_categories))
                mappings["name:" + target["base_name"]] = {
                    "category_group": group,
                    "category": category,
                    "asset_class": asset,
                }
                matched += 1
                category_counts[f"{group} / {category}"] += 1

        canonical_json = json.dumps(
            [{"scheme_name": name, **mappings[name]} for name in sorted(mappings)],
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "mappings": mappings,
            "source_names_matched": matched,
            "source_names_unmatched": unmatched,
            "source_documents_missing": documents_missing,
            "source_names_ambiguous": ambiguous,
            "requests_made": requests_made,
            "category_counts": dict(sorted(category_counts.items())),
            "unclassified_category_labels": dict(sorted(unclassified_category_labels.items())),
            "unclassified_fund_types": dict(sorted(unclassified_fund_types.items())),
            "source_documents_without_category": source_documents_without_category,
            "payload_sha256": hashlib.sha256(canonical_json.encode()).hexdigest(),
        }
    finally:
        if own_session:
            client.close()
