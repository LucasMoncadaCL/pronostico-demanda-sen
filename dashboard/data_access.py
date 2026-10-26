"""Generate deterministic synthetic examples for the public dashboard demo."""

from __future__ import annotations

import numpy as np
import pandas as pd


def load_demo_data() -> pd.DataFrame:
    """Return fictional hourly profiles; no CEN observations or predictions are used."""
    dates = pd.date_range("2030-01-01", "2030-12-31", freq="D")
    rows = []
    for day_number, date in enumerate(dates):
        weekday = date.weekday()
        for period in range(1, 25):
            hour_profile = 7200 + 1800 * np.sin((period - 7) * np.pi / 12) + 700 * np.sin(period * np.pi / 4)
            weekend = -850 if weekday >= 5 else 0
            seasonal = 500 * np.cos(2 * np.pi * day_number / 365)
            # Deterministic pseudo-variation, intentionally unrelated to real demand.
            noise = 120 * np.sin(day_number * 1.7 + period * 2.3)
            observed = hour_profile + weekend + seasonal + noise
            benchmark = hour_profile + weekend + 0.35 * seasonal
            demo_event = date.day == 15 and date.month in {2, 5, 8, 11}
            candidate = benchmark - (550 if demo_event and weekday < 5 else 0)
            rows.append(
                {
                    "target_date": date,
                    "period_index": period,
                    "observed": observed,
                    "benchmark_prediction": benchmark,
                    "candidate_prediction": candidate,
                    "is_demo_event": demo_event and weekday < 5,
                    "weekday": weekday,
                }
            )
    return pd.DataFrame(rows)


def daily_metrics(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, group in data.groupby("target_date", sort=True):
        benchmark_error = group["benchmark_prediction"] - group["observed"]
        candidate_error = group["candidate_prediction"] - group["observed"]
        rows.append(
            {
                "target_date": date,
                "benchmark_mae": benchmark_error.abs().mean(),
                "candidate_mae": candidate_error.abs().mean(),
                "benchmark_rmse": np.sqrt((benchmark_error**2).mean()),
                "candidate_rmse": np.sqrt((candidate_error**2).mean()),
                "is_demo_event": bool(group["is_demo_event"].any()),
            }
        )
    return pd.DataFrame(rows)
