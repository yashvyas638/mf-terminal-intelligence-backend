"""Bounded HTTP adapter for AMFI historical NAV downloads.

The URL shape is based on independently observed AMFI portal requests. Keep
this adapter out of scheduled/production ingestion until a live response has
been checked against the official History form and its selected type/date range.
"""
from __future__ import annotations

from datetime import date, datetime
import time
from typing import Any
from urllib.parse import urlencode

import requests

from app.nav_backfill import AMFI_MAX_HISTORY_WINDOW_DAYS, HistoryWindow
from app.nav_history import AMFI_HISTORY_URL, parse_amfi_history_text

MAX_HISTORY_RESPONSE_BYTES = 30_000_000
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


def _amfi_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def build_amfi_history_url(window: HistoryWindow, scheme_type: int) -> str:
    """Build a bounded all-AMC history URL for one AMFI scheme type."""
    if not isinstance(window, HistoryWindow):
        raise TypeError("window must be a HistoryWindow")
    if window.day_count > AMFI_MAX_HISTORY_WINDOW_DAYS:
        raise ValueError("AMFI history requests cannot exceed 90 calendar days")
    if scheme_type not in {1, 2, 3}:
        raise ValueError("scheme_type must be 1 (open), 2 (close), or 3 (interval)")
    query = urlencode({
        "tp": scheme_type,
        "frmdt": _amfi_date(window.start_date),
        "todt": _amfi_date(window.end_date),
    })
    return f"{AMFI_HISTORY_URL}?{query}"


def _read_response(response: Any, max_bytes: int = MAX_HISTORY_RESPONSE_BYTES) -> bytes:
    headers = getattr(response, "headers", {}) or {}
    declared = headers.get("Content-Length")
    if declared:
        try:
            if int(declared) > max_bytes:
                raise ValueError("AMFI history response exceeds the 30 MB safety limit")
        except ValueError as exc:
            if "exceeds" in str(exc):
                raise
    chunks: list[bytes] = []
    total = 0
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("AMFI history response exceeds the 30 MB safety limit")
            chunks.append(chunk)
        return b"".join(chunks)
    body = response.content
    if len(body) > max_bytes:
        raise ValueError("AMFI history response exceeds the 30 MB safety limit")
    return body


def fetch_amfi_history_window(
    window: HistoryWindow,
    scheme_type: int,
    *,
    max_attempts: int = 3,
    timeout: tuple[int, int] = (8, 60),
) -> tuple[list[Any], dict[str, Any]]:
    """Fetch and strictly validate one AMFI history window; never persists data."""
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be an integer between 1 and 5")
    url = build_amfi_history_url(window, scheme_type)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        response = None
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": "MF-Terminal-Intelligence/0.4 (+historical NAV data service)",
                    "Accept": "text/plain, application/octet-stream;q=0.9, */*;q=0.5",
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=timeout,
                stream=True,
            )
            status = int(response.status_code)
            if status in TRANSIENT_STATUSES:
                raise requests.HTTPError(f"transient AMFI history HTTP status {status}", response=response)
            response.raise_for_status()
            payload = _read_response(response).decode("utf-8-sig")
            records, report = parse_amfi_history_text(payload)
            outside = [
                record for record in records
                if record.nav_date < window.start_date or record.nav_date > window.end_date
            ]
            if outside:
                raise ValueError("AMFI history response contains records outside the requested date window")
            report.update({
                "source_url": url,
                "scheme_type": scheme_type,
                "requested_start_date": window.start_date.isoformat(),
                "requested_end_date": window.end_date.isoformat(),
                "http_status": status,
                "bytes_received": len(payload.encode("utf-8")),
                "attempt": attempt,
            })
            return records, report
        except requests.HTTPError as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in TRANSIENT_STATUSES or attempt >= max_attempts:
                raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

        time.sleep(min(2 ** (attempt - 1), 8))

    raise requests.RequestException(
        f"AMFI history request failed after retries: {type(last_error).__name__ if last_error else 'unknown'}"
    )
