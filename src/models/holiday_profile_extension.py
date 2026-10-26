"""Deterministic holiday-profile substitution used by experiment 4.5."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from src.baselines.weekday_period_mean import predict_one


def predict_with_holiday_profile(
    *,
    target_date: date,
    period_index: int,
    benchmark_prediction: Decimal,
    fixed_history: Iterable[dict],
    candidate_holiday_dates: set[date],
) -> dict:
    """Use a frozen Sunday-by-period profile only on designated weekdays.

    The caller is responsible for constructing the fixed, issue-eligible 2024
    history and for deriving candidate_holiday_dates from the frozen calendar.
    Other dates return the supplied benchmark value unchanged.
    """
    if target_date.weekday() >= 5 or target_date not in candidate_holiday_dates:
        return {
            "prediction": benchmark_prediction,
            "profile": "unchanged_benchmark",
            "fallback_level": None,
            "n_support": None,
            "holiday_substitution_applied": False,
        }

    result = predict_one(weekday=6, period_index=period_index, history=fixed_history)
    if result["prediction"] is None:
        raise ValueError(
            f"No eligible support for Sunday profile at {target_date}, period {period_index}."
        )
    return {
        "prediction": result["prediction"],
        "profile": "sunday_x_period",
        "fallback_level": result["fallback_level"],
        "n_support": result["n_support"],
        "holiday_substitution_applied": True,
    }
