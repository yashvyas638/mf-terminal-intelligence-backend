from datetime import date
from decimal import Decimal

import pytest
import requests

from app.nav_history_client import (
    AMFI_HISTORY_URL,
    AmfiHistoryFetchError,
    fetch_amfi_history_window,
)

PAYLOAD = """Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date
Open Ended Schemes ( Growth Scheme - Equity Scheme );;;;;;;
119551;Example Equity Fund - Direct Growth;INF204K01K15;INF204K01K23;89.1234;85.0000;89.1234;05-Oct-2026
"""


class FakeResponse:
    def __init__(self, body=PAYLOAD, status=200, headers=None, url=None):
        self.body = body.encode() if isinstance(body, str) else body
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/plain"}
        self.url = url or AMFI_HISTORY_URL
        self.closed = False

    @property
    def content(self):
        return self.body

    def iter_content(self, chunk_size):
        yield self.body[:10]
        yield self.body[10:]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("http error", response=self)

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_fetches_and_validates_bounded_history_window():
    response = FakeResponse(url=AMFI_HISTORY_URL + "?tp=1&frmdt=01-Oct-2026&todt=07-Oct-2026")
    session = FakeSession([response])
    records, report = fetch_amfi_history_window(
        date(2026, 10, 1), date(2026, 10, 7), 1, session=session
    )
    assert len(records) == 1
    assert records[0].nav == Decimal("89.1234")
    assert report["requested_start_date"] == "2026-10-01"
    assert report["requested_end_date"] == "2026-10-07"
    assert report["scheme_type"] == 1
    assert report["bytes_received"] == len(PAYLOAD.encode())
    assert session.calls[0][0] == AMFI_HISTORY_URL
    assert session.calls[0][1]["params"] == {
        "tp": "1", "frmdt": "01-Oct-2026", "todt": "07-Oct-2026"
    }
    assert response.closed


@pytest.mark.parametrize(
    "start,end,scheme_type,message",
    [
        (date(2026, 1, 1), date(2026, 4, 1), 1, "90 inclusive"),
        (date(2026, 2, 2), date(2026, 2, 1), 1, "on or after"),
        (date(2026, 1, 1), date(2026, 1, 2), 4, "scheme_type"),
    ],
)
def test_rejects_invalid_request_windows(start, end, scheme_type, message):
    with pytest.raises(ValueError, match=message):
        fetch_amfi_history_window(start, end, scheme_type, session=FakeSession([]))


def test_rejects_success_status_with_html_stub_without_retrying_as_data():
    session = FakeSession([FakeResponse("<html>no data</html>")])
    with pytest.raises(ValueError, match="returned HTML"):
        fetch_amfi_history_window(
            date(2026, 10, 1), date(2026, 10, 7), 1, session=session
        )


def test_rejects_data_outside_requested_window():
    payload = PAYLOAD.replace("05-Oct-2026", "30-Sep-2026")
    session = FakeSession([FakeResponse(payload)])
    with pytest.raises(AmfiHistoryFetchError, match="outside the requested window"):
        fetch_amfi_history_window(
            date(2026, 10, 1), date(2026, 10, 7), 1, session=session
        )


def test_retries_transient_http_status_and_closes_each_response():
    transient = FakeResponse("temporary", status=503)
    good = FakeResponse()
    session = FakeSession([transient, good])
    records, report = fetch_amfi_history_window(
        date(2026, 10, 1), date(2026, 10, 7), 1, session=session
    )
    assert len(records) == 1
    assert report["attempt"] == 2
    assert transient.closed and good.closed


def test_rejects_oversized_response_from_content_length():
    response = FakeResponse(headers={"Content-Length": str(31_000_000)})
    session = FakeSession([response])
    with pytest.raises(AmfiHistoryFetchError, match="30 MB"):
        fetch_amfi_history_window(
            date(2026, 10, 1), date(2026, 10, 7), 1, session=session
        )
