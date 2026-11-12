from datetime import date

import pytest

from app import main


def test_history_plan_startup_hook_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMFI_HISTORY_PLAN_ON_START", raising=False)
    monkeypatch.delenv("AMFI_HISTORY_CONTRACT_VERIFIED", raising=False)
    assert main._maybe_plan_historical_backfill_from_environment() is None


def test_history_plan_startup_hook_requires_verified_source(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_PLAN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "false")
    with pytest.raises(RuntimeError, match="CONTRACT_VERIFIED"):
        main._maybe_plan_historical_backfill_from_environment()


def test_history_plan_startup_hook_requires_explicit_date_range(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_PLAN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.delenv("AMFI_HISTORY_BACKFILL_START_DATE", raising=False)
    monkeypatch.delenv("AMFI_HISTORY_BACKFILL_END_DATE", raising=False)
    with pytest.raises(RuntimeError, match="START_DATE"):
        main._maybe_plan_historical_backfill_from_environment()


def test_history_plan_startup_hook_calls_idempotent_plan_with_safe_defaults(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_PLAN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_START_DATE", "2021-11-12")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_END_DATE", "2026-11-11")
    expected = {
        "status": "planned",
        "windows_per_scheme_type": 261,
        "scheme_types": [1, 2, 3],
        "checkpoints_created": 783,
        "checkpoints_already_present": 0,
        "network_requests_made": 0,
    }
    calls = []

    def fake_plan(start_date, end_date, scheme_types, *, max_window_days):
        calls.append((start_date, end_date, scheme_types, max_window_days))
        return expected

    monkeypatch.setattr(main, "create_history_backfill_plan", fake_plan)
    result = main._maybe_plan_historical_backfill_from_environment()

    assert result == expected
    assert calls == [
        (date(2021, 11, 12), date(2026, 11, 11), (1, 2, 3), 7)
    ]


def test_history_plan_startup_hook_rejects_reversed_dates(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_PLAN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_START_DATE", "2026-11-11")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_END_DATE", "2021-11-12")
    with pytest.raises(RuntimeError, match="on or after"):
        main._maybe_plan_historical_backfill_from_environment()
