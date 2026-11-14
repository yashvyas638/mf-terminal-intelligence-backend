from datetime import date
import requests
import pytest

import app.nav_history_source as source
from app.nav_backfill import HistoryWindow


HISTORY_FIXTURE = (
    "Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;"
    "ISIN Div Reinvestment;Net Asset Value;Date\n"
    "119551;Example Equity Fund - Direct Growth;Direct Plan;GROWTH;"
    "INF204K01K15;INF204K01K23;89.1234;21-Oct-2026\n"
)


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status_code = status
        self.headers = {"Content-Type": "text/plain", "Content-Length": str(len(self.body))}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def close(self):
        self.closed = True


def test_builds_bounded_amfi_history_url_with_official_form_date_format():
    window = HistoryWindow(date(2026, 1, 1), date(2026, 3, 31))
    url = source.build_amfi_history_url(window, 1)
    assert url.endswith("?tp=1&frmdt=01-Jan-2026&todt=31-Mar-2026")


def test_rejects_invalid_type_and_windows_over_90_days():
    with pytest.raises(ValueError, match="scheme_type"):
        source.build_amfi_history_url(HistoryWindow(date(2026, 1, 1), date(2026, 1, 2)), 4)
    with pytest.raises(ValueError, match="90 calendar days"):
        source.build_amfi_history_url(HistoryWindow(date(2026, 1, 1), date(2026, 4, 1)), 1)


def test_fetch_parses_history_and_records_request_provenance(monkeypatch):
    window = HistoryWindow(date(2026, 10, 20), date(2026, 10, 25))
    response = FakeResponse(HISTORY_FIXTURE)
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(source.requests, "get", fake_get)
    records, report = source.fetch_amfi_history_window(window, 1)
    assert len(records) == 1
    assert records[0].scheme_code == 119551
    assert records[0].plan_type == "Direct Plan"
    assert records[0].option_type == "GROWTH"
    assert report["scheme_type"] == 1
    assert report["requested_start_date"] == "2026-10-20"
    assert report["requested_end_date"] == "2026-10-25"
    assert report["http_status"] == 200
    assert report["attempt"] == 1
    assert calls[0][1]["stream"] is True
    assert calls[0][1]["timeout"] == (8, 60)
    assert response.closed is True


def test_retries_transient_status_then_succeeds(monkeypatch):
    window = HistoryWindow(date(2026, 10, 20), date(2026, 10, 25))
    responses = [FakeResponse("temporarily unavailable", 503), FakeResponse(HISTORY_FIXTURE)]
    sleeps = []

    def fake_get(url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(source.requests, "get", fake_get)
    monkeypatch.setattr(source.time, "sleep", sleeps.append)
    records, report = source.fetch_amfi_history_window(window, 1)
    assert len(records) == 1
    assert report["attempt"] == 2
    assert sleeps == [1]


def test_rejects_history_rows_outside_requested_window(monkeypatch):
    window = HistoryWindow(date(2026, 10, 22), date(2026, 10, 25))
    monkeypatch.setattr(source.requests, "get", lambda url, **kwargs: FakeResponse(HISTORY_FIXTURE))
    with pytest.raises(ValueError, match="outside the requested date window"):
        source.fetch_amfi_history_window(window, 1)


def test_rejects_html_response_and_does_not_return_empty_success(monkeypatch):
    window = HistoryWindow(date(2026, 10, 20), date(2026, 10, 25))
    monkeypatch.setattr(source.requests, "get", lambda url, **kwargs: FakeResponse("<!doctype html><html>blocked</html>"))
    with pytest.raises(ValueError, match="returned HTML"):
        source.fetch_amfi_history_window(window, 1)


def test_non_transient_http_error_is_not_retried(monkeypatch):
    window = HistoryWindow(date(2026, 10, 20), date(2026, 10, 25))
    response = FakeResponse("not found", 404)
    calls = []
    monkeypatch.setattr(source.requests, "get", lambda url, **kwargs: calls.append(url) or response)
    with pytest.raises(requests.HTTPError):
        source.fetch_amfi_history_window(window, 1)
    assert len(calls) == 1
