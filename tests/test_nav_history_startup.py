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



def test_history_batch_startup_hook_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", raising=False)
    assert main._maybe_run_historical_backfill_batch_from_environment() is None


def test_history_batch_startup_hook_requires_verified_contract(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "false")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    with pytest.raises(RuntimeError, match="CONTRACT_VERIFIED"):
        main._maybe_run_historical_backfill_batch_from_environment()


def test_history_batch_startup_hook_requires_separate_execution_gate(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "false")
    with pytest.raises(RuntimeError, match="BACKFILL_ENABLED"):
        main._maybe_run_historical_backfill_batch_from_environment()


@pytest.mark.parametrize("limit", ["0", "6", "bad"])
def test_history_batch_startup_hook_rejects_unsafe_batch_limits(monkeypatch, limit):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", limit)
    with pytest.raises(RuntimeError, match="batch limit"):
        main._maybe_run_historical_backfill_batch_from_environment()


def test_history_batch_startup_hook_runs_only_bounded_batch(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "1")
    expected = {
        "status": "completed",
        "selected": 1,
        "completed": 1,
        "failed": 0,
        "results": [],
        "max_attempts": 3,
    }
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(main, "run_history_backfill_batch", fake_run)
    result = main._maybe_run_historical_backfill_batch_from_environment()

    assert result == expected
    assert calls == [{
        "limit": 1,
        "enabled": True,
        "source_contract_verified": True,
        "stale_after_minutes": 30,
    }]



def test_history_plan_startup_hook_supports_storage_optimized_hybrid_mode(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_PLAN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_PLAN_MODE", "hybrid")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_START_DATE", "2021-10-01")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_END_DATE", "2026-11-11")
    monkeypatch.setenv("AMFI_HISTORY_MONTHLY_START_DATE", "2021-11-19")
    monkeypatch.setenv("AMFI_HISTORY_DAILY_START_DATE", "2025-11-01")
    expected = {
        "status": "planned",
        "baseline_daily_windows_per_scheme_type": 7,
        "monthly_windows_per_scheme_type": 48,
        "daily_windows_per_scheme_type": 54,
        "checkpoints_paused": 782,
        "checkpoints_created": 324,
        "network_requests_made": 0,
    }
    calls = []

    def fake_plan(full_start, full_end, monthly_start, daily_start, scheme_types):
        calls.append((full_start, full_end, monthly_start, daily_start, scheme_types))
        return expected

    monkeypatch.setattr(main, "create_storage_optimized_history_plan", fake_plan)
    result = main._maybe_plan_historical_backfill_from_environment()

    assert result == expected
    assert calls == [(
        date(2021, 10, 1),
        date(2026, 11, 11),
        date(2021, 11, 19),
        date(2025, 11, 1),
        (1, 2, 3),
    )]



def test_history_background_task_does_not_block_async_startup():
    import asyncio
    import time

    async def exercise():
        started = asyncio.Event()
        finished = asyncio.Event()
        loop = asyncio.get_running_loop()

        def slow_worker():
            loop.call_soon_threadsafe(started.set)
            time.sleep(0.25)
            loop.call_soon_threadsafe(finished.set)
            return {"status": "completed", "selected": 1, "completed": 1, "failed": 0}

        task = asyncio.create_task(asyncio.to_thread(slow_worker))
        task.add_done_callback(main._log_history_backfill_task_result)

        # The event loop remains responsive while the synchronous AMFI worker runs.
        await asyncio.wait_for(started.wait(), timeout=0.1)
        assert not finished.is_set()
        await asyncio.wait_for(finished.wait(), timeout=1)
        assert (await task)["completed"] == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("threshold", ["0", "241", "bad"])
def test_history_batch_startup_hook_rejects_unsafe_stale_threshold(monkeypatch, threshold):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_STALE_AFTER_MINUTES", threshold)
    with pytest.raises(RuntimeError, match="stale-worker threshold"):
        main._maybe_run_historical_backfill_batch_from_environment()


def test_history_batch_startup_hook_passes_configured_stale_threshold(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "3")
    monkeypatch.setenv("AMFI_HISTORY_STALE_AFTER_MINUTES", "2")
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"status": "idle", "selected": 0, "completed": 0, "failed": 0, "results": []}

    monkeypatch.setattr(main, "run_history_backfill_batch", fake_run)
    main._maybe_run_historical_backfill_batch_from_environment()
    assert calls == [{
        "limit": 3,
        "enabled": True,
        "source_contract_verified": True,
        "stale_after_minutes": 15,
    }]



def test_history_batch_startup_hook_caps_multi_batch_run_and_stops_when_queue_drains(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "3")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", "8")
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        selected = 3 if len(calls) == 1 else 2
        return {
            "status": "completed",
            "selected": selected,
            "completed": selected,
            "failed": 0,
            "results": [{"status": "complete"}] * selected,
            "max_attempts": 3,
        }

    monkeypatch.setattr(main, "run_history_backfill_batch", fake_run)
    result = main._maybe_run_historical_backfill_batch_from_environment()

    assert result["selected"] == 5
    assert result["completed"] == 5
    assert result["failed"] == 0
    assert len(calls) == 2
    assert [call["limit"] for call in calls] == [3, 3]


@pytest.mark.parametrize("max_windows", ["0", "21", "bad"])
def test_history_batch_startup_hook_rejects_unsafe_max_windows(monkeypatch, max_windows):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", max_windows)
    with pytest.raises(RuntimeError, match="max windows per start"):
        main._maybe_run_historical_backfill_batch_from_environment()
