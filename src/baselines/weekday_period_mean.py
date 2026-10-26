"""Weekly-profile baseline: mean by weekday and source period index.

The function is deliberately small and deterministic. The caller supplies only
records allowed by the issue-date cutoff; target rows are not accepted here.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal
from typing import Iterable

MIN_GROUP_SUPPORT = 5


def predict_one(*, weekday: int, period_index: int, history: Iterable[dict]) -> dict:
    """Return a mean and its support using the pre-registered fallback order."""
    rows = list(history)
    levels = (
        ("weekday_x_period", [r for r in rows if r["date"].weekday() == weekday and r["hour"] == period_index]),
        ("period_all_weekdays", [r for r in rows if r["hour"] == period_index]),
        ("weekday_all_periods", [r for r in rows if r["date"].weekday() == weekday]),
        ("global_all_periods", rows),
    )
    for name, group in levels:
        if len(group) >= MIN_GROUP_SUPPORT:
            value = sum((r["value"] for r in group), Decimal("0")) / Decimal(len(group))
            return {"prediction": value, "fallback_level": name, "n_support": len(group)}
    return {"prediction": None, "fallback_level": "no_support", "n_support": len(rows)}
