"""Bounded client for AMFI's official historical NAV archive.

AMFI's public NAV Download page documents a maximum 90-day history request.
This client deliberately fetches one bounded window at a time; orchestration,
checkpointing and persistence remain separate concerns.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests

from app.nav_history import AMFI_HISTORY_URL, MAX_HISTORY_PAYLOAD_BYTES, parse_amfi_history_text

MAX_INCLUSIVE_DAYS = 90
CONNECT_TIMEOUT_SECONDS = 8
READ_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3


class AmfiHistoryFetchError(RuntimeError):
    """Raised when AMFI history cannot be fetched or validated safely."""


def _amfi_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _read_response(response: Any) -> bytes:
    headers = getattr(response, "headers", {}) or {}
    content_length = headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_HISTORY_PAYLOAD_BYTES:
                raise AmfiHistoryFetchError("AMFI history response exceeds the 30 MB safety limit")
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    iterator = response.iter_content(chunk_size=64 * 1024) if hasattr(response, "iter_content") else (response.content,)
    for chunk in iterator:
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_HISTORY_PAYLOAD_BYTES:
            raise AmfiHistoryFetchError("AMFI history response exceeds the 30 MB safety limit")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_amfi_history_window(
    start_date: date,
    end_date: date,
    scheme_type: int = 1,
    *,
    session: Any = requests,
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[list[Any], dict[str, Any]]:
    """Fetch and validate one inclusive date window from AMFI.

    scheme_type: 1=open-ended, 2=close-ended, 3=interval funds.
    A successful HTTP response is not sufficient: the body must parse into
    valid NAV observations wholly inside the requested date window.
    """
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise ValueError("start_date and end_date must be dates")
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if (end_date - start_date).days + 1 > MAX_INCLUSIVE_DAYS:
        raise ValueError("AMFI history requests are limited to 90 inclusive calendar days")
    if scheme_type not in (1, 2, 3):
        raise ValueError("scheme_type must be 1 (open-ended), 2 (close-ended), or 3 (interval)")
    if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")

    params = {
        "tp": str(scheme_type),
        "frmdt": _amfi_date(start_date),
        "todt": _amfi_date(end_date),
    }
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        response = None
        try:
            response = session.get(
                AMFI_HISTORY_URL,
                params=params,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                headers={
                    "User-Agent": "MF-Terminal-Intelligence/0.4 (historical NAV data client)",
                    "Accept": "text/plain, */*;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                },
                stream=True,
            )
            status = int(response.status_code)
            if status in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(f"transient AMFI HTTP status {status}", response=response)
            response.raise_for_status()
            raw = _read_response(response)
            if not raw:
                raise AmfiHistoryFetchError("AMFI history response is empty")
            try:
                payload = raw.decode("utf-8-sig", errors="strict")
            except UnicodeDecodeError as exc:
                raise AmfiHistoryFetchError("AMFI history response is not valid UTF-8") from exc

            records, report = parse_amfi_history_text(payload)
            outside_window = [
                record.nav_date.isoformat()
                for record in records
                if record.nav_date < start_date or record.nav_date > end_date
            ]
            if outside_window:
                raise AmfiHistoryFetchError(
                    "AMFI returned NAV dates outside the requested window; response rejected"
                )
            request_url = getattr(response, "url", None) or AMFI_HISTORY_URL
            report.update({
                "source_url": request_url,
                "requested_start_date": start_date.isoformat(),
                "requested_end_date": end_date.isoformat(),
                "scheme_type": scheme_type,
                "http_status": status,
                "content_type": (getattr(response, "headers", {}) or {}).get("Content-Type", "unknown"),
                "bytes_received": len(raw),
                "attempt": attempt,
            })
            return records, report
        except requests.RequestException as exc:
            last_error = exc
            retryable = not isinstance(exc, requests.HTTPError) or getattr(exc.response, "status_code", 0) in {429, 500, 502, 503, 504}
            if not retryable or attempt >= max_attempts:
                raise AmfiHistoryFetchError(
                    f"AMFI history request failed after {attempt} attempt(s): {type(exc).__name__}"
                ) from None
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

    raise AmfiHistoryFetchError(
        f"AMFI history request failed: {type(last_error).__name__ if last_error else 'unknown error'}"
    )
