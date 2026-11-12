from datetime import date

import pytest
from fastapi import HTTPException

from app.nav_history_api import (
    HistoryBackfillPlanRequest,
    HistoryBackfillRunRequest,
    _execution_gates,
    _require_operator_key,
    run_nav_history_backfill,
)


def test_operator_key_is_required_and_constant_time_checked(monkeypatch):
    secret = "a-server-operator-key-with-at-least-32-characters"
    monkeypatch.setenv("API_KEY", secret)
    _require_operator_key(secret)
    with pytest.raises(HTTPException) as error:
        _require_operator_key("wrong")
    assert error.value.status_code == 401


def test_operator_auth_fails_closed_when_server_key_is_short(monkeypatch):
    monkeypatch.setenv("API_KEY", "short")
    with pytest.raises(HTTPException) as error:
        _require_operator_key("short")
    assert error.value.status_code == 503


def test_plan_payload_rejects_invalid_range_duplicate_and_boolean_types():
    with pytest.raises(ValueError, match="on or after"):
        HistoryBackfillPlanRequest(
            start_date=date(2026, 2, 2),
            end_date=date(2026, 2, 1),
        )
    with pytest.raises(ValueError, match="duplicates"):
        HistoryBackfillPlanRequest(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            scheme_types=[1, 1],
        )
    with pytest.raises(ValueError, match="only 1, 2, or 3"):
        HistoryBackfillPlanRequest(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            scheme_types=[True],
        )


def test_execution_gates_default_closed(monkeypatch):
    monkeypatch.delenv("AMFI_HISTORY_CONTRACT_VERIFIED", raising=False)
    monkeypatch.delenv("AMFI_HISTORY_BACKFILL_ENABLED", raising=False)
    assert _execution_gates() == {
        "source_contract_verified": False,
        "backfill_enabled": False,
    }


def test_run_endpoint_does_not_fetch_until_both_gates_are_true(monkeypatch):
    secret = "a-server-operator-key-with-at-least-32-characters"
    monkeypatch.setenv("API_KEY", secret)
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "false")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    with pytest.raises(HTTPException) as error:
        run_nav_history_backfill(HistoryBackfillRunRequest(limit=1), secret)
    assert error.value.status_code == 409
    assert error.value.detail["execution_gates"] == {
        "source_contract_verified": False,
        "backfill_enabled": True,
    }


def test_run_endpoint_rejects_missing_operator_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "a-server-operator-key-with-at-least-32-characters")
    with pytest.raises(HTTPException) as error:
        run_nav_history_backfill(HistoryBackfillRunRequest(), None)
    assert error.value.status_code == 401
