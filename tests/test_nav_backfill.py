from datetime import date

import pytest

from app.nav_backfill import (
    AMFI_MAX_HISTORY_WINDOW_DAYS,
    AMFI_RECOMMENDED_HISTORY_WINDOW_DAYS,
    HistoryWindow,
    pending_history_windows,
    plan_history_windows,
)


def test_history_windows_are_contiguous_and_maximum_90_days_when_requested():
    start = date(2026, 1, 1)
    end = date(2026, 7, 1)
    windows = plan_history_windows(start, end, max_window_days=90)
    # The inclusive range contains 182 calendar days: 90 + 90 + 2.
    assert [window.day_count for window in windows] == [90, 90, 2]
    assert windows[0].start_date == start
    assert windows[-1].start_date == date(2026, 6, 30)
    assert windows[-1].end_date == end
    assert sum(window.day_count for window in windows) == (end - start).days + 1
    for previous, current in zip(windows, windows[1:], strict=False):
        assert current.start_date == date.fromordinal(previous.end_date.toordinal() + 1)
    assert all(window.day_count <= AMFI_MAX_HISTORY_WINDOW_DAYS for window in windows)


def test_default_window_is_conservative_seven_days():
    assert AMFI_RECOMMENDED_HISTORY_WINDOW_DAYS == 7
    windows = plan_history_windows(date(2026, 1, 1), date(2026, 1, 16))
    assert [window.day_count for window in windows] == [7, 7, 2]


def test_single_day_range_produces_one_single_day_window():
    assert plan_history_windows(date(2026, 2, 3), date(2026, 2, 3)) == [
        HistoryWindow(date(2026, 2, 3), date(2026, 2, 3))
    ]


def test_leap_day_is_included_without_gaps():
    windows = plan_history_windows(date(2024, 2, 28), date(2024, 3, 1))
    assert sum(window.day_count for window in windows) == 3
    assert windows[0].end_date == date(2024, 3, 1)


def test_custom_smaller_window_is_supported():
    windows = plan_history_windows(
        date(2026, 1, 1), date(2026, 1, 7), max_window_days=3
    )
    assert [window.day_count for window in windows] == [3, 3, 1]


def test_reversed_date_range_is_rejected():
    with pytest.raises(ValueError, match="on or after"):
        plan_history_windows(date(2026, 2, 2), date(2026, 2, 1))


@pytest.mark.parametrize("size", [0, 91, -1])
def test_window_size_outside_supported_bounds_is_rejected(size):
    with pytest.raises(ValueError, match="between 1 and 90"):
        plan_history_windows(date(2026, 1, 1), date(2026, 1, 2), max_window_days=size)


def test_window_key_is_stable_and_checkpoint_resume_skips_completed():
    windows = plan_history_windows(date(2026, 1, 1), date(2026, 4, 1))
    completed = {windows[0].key}
    assert windows[0].key == plan_history_windows(
        date(2026, 1, 1), date(2026, 3, 31)
    )[0].key
    assert pending_history_windows(windows, completed) == windows[1:]


def test_window_key_differs_for_different_ranges():
    first = HistoryWindow(date(2026, 1, 1), date(2026, 3, 31))
    second = HistoryWindow(date(2026, 1, 2), date(2026, 4, 1))
    assert first.key != second.key
