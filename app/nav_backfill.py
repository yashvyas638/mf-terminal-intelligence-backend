"""Deterministic planning primitives for bounded AMFI NAV history backfills.

This module deliberately does not perform HTTP requests or database writes.
The AMFI history form's exact request contract must be validated separately
before a source adapter or production job is enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib


AMFI_MAX_HISTORY_WINDOW_DAYS = 90
# Conservative operational default to keep each all-scheme response bounded.
AMFI_RECOMMENDED_HISTORY_WINDOW_DAYS = 7


@dataclass(frozen=True, order=True)
class HistoryWindow:
    """An inclusive, bounded date range for one history request."""

    start_date: date
    end_date: date

    @property
    def day_count(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def key(self) -> str:
        """Stable idempotency key independent of process or execution order."""
        raw = f"amfi-nav-history|{self.start_date.isoformat()}|{self.end_date.isoformat()}"
        return hashlib.sha256(raw.encode("ascii")).hexdigest()


def plan_history_windows(
    start_date: date,
    end_date: date,
    *,
    max_window_days: int = AMFI_RECOMMENDED_HISTORY_WINDOW_DAYS,
) -> list[HistoryWindow]:
    """Split an inclusive date range into contiguous, gap-free AMFI windows."""
    if not isinstance(start_date, date) or isinstance(start_date, datetime):
        raise TypeError("start_date must be a datetime.date")
    if not isinstance(end_date, date) or isinstance(end_date, datetime):
        raise TypeError("end_date must be a datetime.date")
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if not isinstance(max_window_days, int) or isinstance(max_window_days, bool):
        raise TypeError("max_window_days must be an integer")
    if not 1 <= max_window_days <= AMFI_MAX_HISTORY_WINDOW_DAYS:
        raise ValueError("max_window_days must be between 1 and 90")

    windows: list[HistoryWindow] = []
    cursor = start_date
    while cursor <= end_date:
        window_end = min(end_date, cursor + timedelta(days=max_window_days - 1))
        windows.append(HistoryWindow(cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def pending_history_windows(
    windows: list[HistoryWindow],
    completed_keys: set[str] | frozenset[str],
) -> list[HistoryWindow]:
    """Return only windows not already checkpointed as complete."""
    return [window for window in windows if window.key not in completed_keys]
