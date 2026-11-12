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
    expected["research_snapshot_refresh"] = {
        "status": "scheduled",
        "reason": "after_history_worker_completion",
    }
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
        "baseline_daily_windows_per_scheme_type": 2,
        "monthly_windows_per_scheme_type": 48,
        "daily_windows_per_scheme_type": 54,
        "checkpoints_paused": 782,
        "checkpoints_created": 309,
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


@pytest.mark.parametrize("max_windows", ["0", "201", "bad"])
def test_history_batch_startup_hook_rejects_unsafe_max_windows(monkeypatch, max_windows):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", max_windows)
    with pytest.raises(RuntimeError, match="max windows per start"):
        main._maybe_run_historical_backfill_batch_from_environment()



def test_history_batch_startup_hook_accepts_large_bounded_run(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "3")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", "200")
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"status": "idle", "selected": 0, "completed": 0, "failed": 0, "results": []}

    monkeypatch.setattr(main, "run_history_backfill_batch", fake_run)
    monkeypatch.setattr(
        main,
        "_maybe_refresh_research_after_history_completion",
        lambda: pytest.fail("snapshot refresh must be scheduled after the history worker returns"),
    )
    result = main._maybe_run_historical_backfill_batch_from_environment()
    assert result["status"] == "idle"
    assert result["research_snapshot_refresh"] == {
        "status": "scheduled",
        "reason": "after_history_worker_completion",
    }
    assert len(calls) == 1


def test_research_refresh_after_history_waits_for_nonpaused_checkpoints(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "history_backfill_status",
        lambda: {
            "groups": [
                {"checkpoint_status": "complete", "windows": 20},
                {"checkpoint_status": "paused", "windows": 782},
                {"checkpoint_status": "pending", "windows": 4},
            ]
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_research_snapshots_after_ingestion",
        lambda: calls.append("refresh") or {"status": "refreshed"},
    )
    result = main._maybe_refresh_research_after_history_completion()
    assert result == {"status": "deferred", "blocking_groups": 1}
    assert calls == []


def test_research_refresh_after_history_runs_when_only_complete_or_paused(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "history_backfill_status",
        lambda: {
            "groups": [
                {"checkpoint_status": "complete", "windows": 200},
                {"checkpoint_status": "paused", "windows": 782},
            ]
        },
    )
    monkeypatch.setattr(
        main,
        "_refresh_research_snapshots_after_ingestion",
        lambda: calls.append("refresh") or {"status": "refreshed", "schemes_processed": 100},
    )
    result = main._maybe_refresh_research_after_history_completion()
    assert result == {"status": "refreshed", "schemes_processed": 100}
    assert calls == ["refresh"]



def test_history_batch_schedules_research_refresh_after_queue_settles(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "1")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", "10")
    monkeypatch.setattr(
        main,
        "run_history_backfill_batch",
        lambda **kwargs: {
            "status": "completed",
            "selected": 1,
            "completed": 1,
            "failed": 0,
            "results": [],
        },
    )
    refresh_calls = []
    monkeypatch.setattr(
        main,
        "_maybe_refresh_research_after_history_completion",
        lambda: refresh_calls.append(True) or {"status": "refreshed", "snapshot_rows_written": 10},
    )

    result = main._maybe_run_historical_backfill_batch_from_environment()

    assert refresh_calls == []
    assert result["research_snapshot_refresh"] == {
        "status": "scheduled",
        "reason": "after_history_worker_completion",
    }


def test_history_batch_schedules_refresh_gate_while_checkpoints_remain(monkeypatch):
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "1")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", "10")
    monkeypatch.setattr(
        main,
        "run_history_backfill_batch",
        lambda **kwargs: {
            "status": "completed",
            "selected": 1,
            "completed": 1,
            "failed": 0,
            "results": [],
        },
    )
    refresh_calls = []
    monkeypatch.setattr(
        main,
        "_maybe_refresh_research_after_history_completion",
        lambda: refresh_calls.append(True) or {
            "status": "deferred",
            "blocking_groups": 1,
        },
    )

    result = main._maybe_run_historical_backfill_batch_from_environment()

    assert refresh_calls == []
    assert result["research_snapshot_refresh"] == {
        "status": "scheduled",
        "reason": "after_history_worker_completion",
    }


def test_research_refresh_waits_for_hybrid_five_year_baseline(monkeypatch):
    calls = []
    monkeypatch.setenv("AMFI_HISTORY_PLAN_MODE", "hybrid")
    monkeypatch.setattr(
        main,
        "history_backfill_status",
        lambda: {"groups": [{"checkpoint_status": "complete", "windows": 200}]},
    )
    monkeypatch.setattr(main, "_hybrid_baseline_buffer_complete", lambda: False)
    monkeypatch.setattr(
        main,
        "_refresh_research_snapshots_after_ingestion",
        lambda: calls.append("refresh") or {"status": "refreshed"},
    )
    result = main._maybe_refresh_research_after_history_completion()
    assert result == {"status": "deferred", "reason": "five_year_baseline_incomplete"}
    assert calls == []



def test_history_completion_callback_schedules_exactly_one_refresh_retry(monkeypatch):
    import asyncio

    calls = []

    async def fake_refresh_retry():
        calls.append("scheduled")
        return {"status": "refreshed", "snapshot_rows_written": 4}

    monkeypatch.setattr(
        main,
        "_refresh_research_snapshots_with_lock_retry",
        fake_refresh_retry,
    )

    async def exercise():
        task = asyncio.create_task(asyncio.sleep(0, result={
            "status": "idle",
            "selected": 0,
            "completed": 0,
            "failed": 0,
            "research_snapshot_refresh": {"status": "scheduled"},
        }))
        task.add_done_callback(main._log_history_backfill_task_result)
        await task
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(exercise())
    assert calls == ["scheduled"]


def test_snapshot_refresh_retries_lock_contention_until_peer_commit(monkeypatch):
    import asyncio

    results = iter([
        {"status": "in_progress"},
        {"status": "in_progress"},
        {"status": "refreshed", "snapshot_rows_written": 4},
    ])
    calls = []
    sleeps = []

    def fake_refresh():
        calls.append("attempt")
        return next(results)

    async def fake_to_thread(function):
        return function()

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(main.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_maybe_refresh_research_after_history_completion", fake_refresh)

    result = asyncio.run(main._refresh_research_snapshots_with_lock_retry())

    assert result == {"status": "refreshed", "snapshot_rows_written": 4}
    assert calls == ["attempt", "attempt", "attempt"]
    assert sleeps == [5, 10]


def test_history_refresh_skips_rebuild_when_current_four_window_snapshots_exist(monkeypatch):
    monkeypatch.setattr(main, "history_backfill_status", lambda: {"groups": []})
    monkeypatch.setattr(main, "_hybrid_baseline_buffer_complete", lambda: True)
    monkeypatch.setattr(main, "_research_snapshots_are_current", lambda: True)
    monkeypatch.setattr(
        main,
        "_refresh_research_snapshots_after_ingestion",
        lambda: pytest.fail("already-current snapshots must not be rebuilt"),
    )

    assert main._maybe_refresh_research_after_history_completion() == {
        "status": "already_current",
    }
