"""Calendar-date availability rules shared by development and evaluation."""
from __future__ import annotations
from datetime import date, timedelta
from typing import Iterable


def cutoff_date(issue_date: date, lag_days: int) -> date:
    if lag_days < 0:
        raise ValueError("lag_days must be non-negative")
    return issue_date - timedelta(days=lag_days)


def eligible_history(rows: Iterable[dict], issue_date: date, lag_days: int) -> list[dict]:
    """Strict date comparison: observation_date < issue_date - lag_days."""
    cutoff = cutoff_date(issue_date, lag_days)
    return [row for row in rows if row["date"] < cutoff]


def frozen_2024_snapshot(rows: Iterable[dict], first_issue_date: date, lag_days: int = 60) -> list[dict]:
    """Return the 2024 history eligible at the first 2025 issue date."""
    return [row for row in eligible_history(rows, first_issue_date, lag_days) if row["date"].year == 2024]
