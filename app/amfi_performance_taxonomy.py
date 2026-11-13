"""Source-backed scheme taxonomy from AMFI's official Fund Performance service.

Only explicit AMFI scheme codes and allow-listed SEBI categories are returned.
Legacy solution-oriented categories and unknown labels fail closed.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

import requests

from app.fund_taxonomy import canonical_subcategory

AMFI_PERFORMANCE_BASE_URL = "https://www.amfiindia.com/gateway/pollingsebi"
FILTERS_PATH = "/api/amfi/fundperformancefilters"
SUBCATEGORIES_PATH = "/api/amfi/getsubcategory"
PERFORMANCE_PATH = "/api/amfi/fundperformance"
REFERER = "https://www.amfiindia.com/otherdata/fund-performance"

CATEGORY_GROUPS = {
    1: "Equity Scheme",
    2: "Debt Scheme",
    3: "Hybrid Scheme",
    # SEBI's February 2026 taxonomy superseded the old Solution Oriented group.
    # AMFI's legacy category ID 4 is intentionally excluded.
    5: "Other Schemes",
}
MATURITY_TYPES = (1, 2)


def _field(row: dict[str, Any], *names: str) -> Any:
    normalized = {
        "".join(ch for ch in str(key).casefold() if ch.isalnum()): value
        for key, value in row.items()
    }
    for name in names:
        key = "".join(ch for ch in name.casefold() if ch.isalnum())
        if key in normalized:
            return normalized[key]
    return None


def canonicalize_performance_rows(
    rows: list[dict[str, Any]],
    *,
    category_group: str,
    subcategory: str,
) -> tuple[dict[int, dict[str, str]], int]:
    """Validate explicit AMFI scheme-code/category rows against SEBI allowlists."""
    canonical_category = canonical_subcategory(category_group, subcategory)
    if canonical_category is None:
        return {}, len(rows)

    result: dict[int, dict[str, str]] = {}
    rejected = 0
    for row in rows:
        if not isinstance(row, dict):
            rejected += 1
            continue
        raw_code = _field(row, "Scheme_Code", "SchemeCode", "scheme_code")
        try:
            code = int(str(raw_code).strip())
        except (TypeError, ValueError):
            rejected += 1
            continue
        if code <= 0:
            rejected += 1
            continue
        candidate = {
            "category_group": category_group,
            "category": canonical_category,
        }
        previous = result.get(code)
        if previous and previous != candidate:
            raise ValueError(
                f"AMFI performance source assigned conflicting categories to scheme {code}"
            )
        result[code] = candidate
    return result, rejected


def _response_data(response: requests.Response) -> list[dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("AMFI Fund Performance endpoint returned invalid JSON") from None
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        # A few AMFI gateway responses wrap lists in a named collection.
        for key in ("items", "records", "result"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise RuntimeError("AMFI Fund Performance endpoint returned an unexpected payload shape")
    if any(not isinstance(item, dict) for item in data):
        raise RuntimeError("AMFI Fund Performance endpoint returned a non-object record")
    return data


def _post(session: requests.Session, path: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    url = AMFI_PERFORMANCE_BASE_URL + path
    transient = {429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = session.post(url, json=body, timeout=(8, 45))
            if response.status_code in transient and attempt < 3:
                response.close()
                time.sleep(min(2 ** (attempt - 1), 4))
                continue
            response.raise_for_status()
            return _response_data(response)
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status not in transient:
                break
            if attempt < 3:
                time.sleep(min(2 ** (attempt - 1), 4))
    status = getattr(getattr(last_error, "response", None), "status_code", None)
    raise RuntimeError(
        f"AMFI Fund Performance request failed: {type(last_error).__name__ if last_error else 'unknown'}"
        + (f" (HTTP {status})" if status is not None else "")
    ) from None


def _recent_business_dates(count: int = 5) -> list[str]:
    report_day = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    while report_day.weekday() >= 5:
        report_day -= timedelta(days=1)
    dates = []
    while len(dates) < count:
        dates.append(report_day.strftime("%d-%b-%Y"))
        report_day -= timedelta(days=1)
        while report_day.weekday() >= 5:
            report_day -= timedelta(days=1)
    return dates


def _last_business_date() -> str:
    return _recent_business_dates(1)[0]


def fetch_amfi_performance_taxonomy(
    *,
    session: requests.Session | None = None,
    max_requests: int = 120,
) -> dict[str, Any]:
    """Fetch all allow-listed current SEBI subcategories for open/close-ended funds."""
    own_session = session is None
    client = session or requests.Session()
    client.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.amfiindia.com",
        "Referer": REFERER,
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })
    try:
        # Establish the same first-party session as the AMFI Fund Performance page.
        if hasattr(client, "get"):
            landing = client.get(REFERER, timeout=(8, 45))
            landing.raise_for_status()

        mappings: dict[int, dict[str, str]] = {}
        rejected = 0
        requests_made = 0
        subcategory_queries = 0
        performance_rows = 0
        entries: list[tuple[int, str, int, str, str]] = []

        for category_id, group in CATEGORY_GROUPS.items():
            if requests_made >= max_requests:
                raise RuntimeError("AMFI Fund Performance request safety limit exceeded")
            subcategories = _post(client, SUBCATEGORIES_PATH, {"category": category_id})
            requests_made += 1
            for item in subcategories:
                subcategory_id = _field(item, "id", "subCategoryId")
                subcategory_name = _field(item, "name", "subCategory", "subCategoryName")
                if subcategory_id is None or not isinstance(subcategory_name, str):
                    raise RuntimeError("AMFI subcategory filter contains an invalid item")
                canonical = canonical_subcategory(group, subcategory_name)
                if canonical is None:
                    rejected += 1
                    continue
                entries.append((
                    category_id,
                    group,
                    int(subcategory_id),
                    subcategory_name,
                    canonical,
                ))

        if not entries:
            raise RuntimeError("AMFI Fund Performance source exposed no current SEBI-allow-listed subcategories")

        # AMFI requires reportDate. Probe recent business dates until the service
        # returns a populated category; reuse that exact date for every peer group.
        probe = next((entry for entry in entries if entry[0] == 1), entries[0])
        selected_report_date = None
        probe_rows: list[dict[str, Any]] = []
        for report_date in _recent_business_dates(5):
            if requests_made >= max_requests:
                raise RuntimeError("AMFI Fund Performance request safety limit exceeded")
            rows = _post(client, PERFORMANCE_PATH, {
                "maturityType": 1,
                "category": probe[0],
                "subCategory": probe[2],
                "mfid": 0,
                "reportDate": report_date,
            })
            requests_made += 1
            subcategory_queries += 1
            if rows:
                probe_rows = rows
                selected_report_date = report_date
                break
        if selected_report_date is None:
            raise RuntimeError("AMFI Fund Performance returned no rows for the five most recent business dates")

        for category_id, group, subcategory_id, _subcategory_name, canonical in entries:
            for maturity_type in MATURITY_TYPES:
                if requests_made >= max_requests:
                    raise RuntimeError("AMFI Fund Performance request safety limit exceeded")
                if (
                    category_id == probe[0]
                    and subcategory_id == probe[2]
                    and maturity_type == 1
                ):
                    rows = probe_rows
                else:
                    rows = _post(client, PERFORMANCE_PATH, {
                        "maturityType": maturity_type,
                        "category": category_id,
                        "subCategory": subcategory_id,
                        "mfid": 0,
                        "reportDate": selected_report_date,
                    })
                    requests_made += 1
                    subcategory_queries += 1
                performance_rows += len(rows)
                parsed, rejected_rows = canonicalize_performance_rows(
                    rows,
                    category_group=group,
                    subcategory=canonical,
                )
                rejected += rejected_rows
                for code, metadata in parsed.items():
                    previous = mappings.get(code)
                    if previous and previous != metadata:
                        raise ValueError(
                            f"AMFI Fund Performance source returned conflicting categories for scheme {code}"
                        )
                    mappings[code] = metadata

        if not mappings:
            raise RuntimeError("AMFI Fund Performance source returned no scheme-code records matching current SEBI categories")
        canonical_json = json.dumps(
            [{"scheme_code": code, **mappings[code]} for code in sorted(mappings)],
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "mappings": mappings,
            "source_url": AMFI_PERFORMANCE_BASE_URL,
            "payload_sha256": hashlib.sha256(canonical_json.encode()).hexdigest(),
            "scheme_codes": len(mappings),
            "performance_rows": performance_rows,
            "rejected_rows": rejected,
            "requests_made": requests_made,
            "subcategory_queries": subcategory_queries,
            "report_dates": [selected_report_date],
        }
    finally:
        if own_session:
            client.close()
