"""Ridge estacional para el pronóstico diario de demanda del SEN.

Conserva como base la media elegible por día-de-semana × período. Ridge aprende
una corrección suave, basada en el primer armónico anual, sobre los residuos de
esa base. La selección de filas elegibles corresponde al llamador.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Iterable

import numpy as np
from sklearn.linear_model import Ridge

from src.baselines.weekday_period_mean import MIN_GROUP_SUPPORT, predict_one
from src.evaluation.benchmark_policy import cutoff_date

PERIODS_PER_ORDINARY_DAY = 24
ANNUAL_HARMONICS = 1


def annual_fourier(day: date) -> tuple[float, float]:
    """Return the first annual sine/cosine pair, with Jan 1 at phase zero."""
    days_in_year = 366 if _is_leap_year(day.year) else 365
    phase = 2.0 * np.pi * (day.timetuple().tm_yday - 1) / days_in_year
    return float(np.sin(phase)), float(np.cos(phase))


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def design_matrix(rows: Iterable[dict]) -> np.ndarray:
    """Build the annual Fourier correction features for ordinary periods."""
    records = list(rows)
    n = len(records)
    fourier = np.empty((n, 2 * ANNUAL_HARMONICS), dtype=np.float64)

    for i, row in enumerate(records):
        day = row["date"]
        period = int(row["hour"])
        if not 1 <= period <= PERIODS_PER_ORDINARY_DAY:
            raise ValueError(f"Ridge estacional no ajusta períodos no ordinarios: {period}.")
        fourier[i, :] = annual_fourier(day)
    return fourier


def fit_ridge_state(
    *,
    history: Iterable[dict],
    alpha: float,
    issue_date: date,
    lag_days: int = 60,
) -> dict:
    """Fit the seasonal correction after enforcing the issue-date cutoff."""
    history_rows = list(history)
    if alpha <= 0:
        raise ValueError("alpha debe ser positivo.")
    cutoff = cutoff_date(issue_date, lag_days)
    if any(row["date"] >= cutoff for row in history_rows):
        raise ValueError(
            f"La historia debe ser estrictamente anterior al corte exclusivo {cutoff}."
        )
    if any(row["date"] >= issue_date for row in history_rows):
        raise ValueError("La historia contiene observaciones del día de emisión o posteriores.")
    if not history_rows:
        raise ValueError("Se requiere historia elegible para ajustar Ridge.")

    support = Counter(
        (row["date"].weekday(), int(row["hour"]))
        for row in history_rows
        if 1 <= int(row["hour"]) <= PERIODS_PER_ORDINARY_DAY
    )
    train_rows = [
        row for row in history_rows
        if 1 <= int(row["hour"]) <= PERIODS_PER_ORDINARY_DAY
    ]
    if not train_rows:
        raise ValueError("No hay períodos ordinarios elegibles para entrenar Ridge.")

    group_values: dict[tuple[int, int], list[float]] = {}
    group_fourier: dict[tuple[int, int], list[np.ndarray]] = {}
    for row in train_rows:
        key = (row["date"].weekday(), int(row["hour"]))
        group_values.setdefault(key, []).append(float(row["value"]))
        group_fourier.setdefault(key, []).append(np.asarray(annual_fourier(row["date"])))
    group_means = {key: float(np.mean(values)) for key, values in group_values.items()}
    group_fourier_means = {
        key: np.mean(values, axis=0) for key, values in group_fourier.items()
    }
    raw_features = design_matrix(train_rows)
    residual_features = np.vstack([
        raw_features[i] - group_fourier_means[(row["date"].weekday(), int(row["hour"]))]
        for i, row in enumerate(train_rows)
    ])
    residuals = np.asarray([
        float(row["value"]) - group_means[(row["date"].weekday(), int(row["hour"]))]
        for row in train_rows
    ])
    estimator = Ridge(alpha=float(alpha), fit_intercept=False, solver="lsqr", tol=1e-8)
    estimator.fit(residual_features, residuals)
    return {
        "estimator": estimator,
        "group_means": group_means,
        "group_fourier_means": group_fourier_means,
        "support": support,
        "history_rows": len(history_rows),
        "history_start_date": min(row["date"] for row in history_rows),
        "history_end_date": max(row["date"] for row in history_rows),
        "coefficients": np.asarray(estimator.coef_, dtype=float),
    }


def predict_from_state(
    *,
    state: dict,
    history: Iterable[dict],
    targets: Iterable[dict],
    issue_date: date,
    min_group_support: int = MIN_GROUP_SUPPORT,
) -> list[dict]:
    """Predict the next calendar date from an already fitted state.

    The benchmark profile is the unpenalized base. Ridge fits only the residual
    seasonal correction. A target's weekday×period group must have at least
    ``min_group_support`` eligible examples to receive that correction;
    otherwise the benchmark hierarchy supplies its prediction. No future
    labels are accepted.
    """
    target_rows = list(targets)
    history_rows = list(history)
    target_dates = {r["date"] for r in target_rows}
    if len(target_dates) > 1:
        raise ValueError("predict_date recibe objetivos de una sola fecha.")

    target_date = next(iter(target_dates), None)
    if target_date is None:
        return []
    if target_date != issue_date + timedelta(days=1):
        raise ValueError("predict_date solo admite objetivos del día calendario siguiente.")
    support = state["support"]
    group_fourier_means = state["group_fourier_means"]
    estimator = state["estimator"]

    supported_targets = [
        r for r in target_rows
        if 1 <= int(r["hour"]) <= PERIODS_PER_ORDINARY_DAY
        and support[(target_date.weekday(), int(r["hour"]))] >= min_group_support
    ]
    supported_target_ids: set[int] = set()
    if supported_targets:
        supported_target_ids = {id(row) for row in supported_targets}

    output = []
    for target in target_rows:
        period = int(target["hour"])
        n_specific = support[(target_date.weekday(), period)]
        baseline = predict_one(
            weekday=target_date.weekday(), period_index=period, history=history_rows
        )
        if baseline["prediction"] is None:
            raise ValueError(
                f"Benchmark sin soporte para {target_date}, período {period}."
            )
        if id(target) in supported_target_ids:
            key = (target_date.weekday(), period)
            centered_features = np.asarray(annual_fourier(target_date)) - group_fourier_means[key]
            output.append({
                "prediction": float(baseline["prediction"]) + float(centered_features @ estimator.coef_),
                "prediction_source": "ridge_seasonal",
                "fallback_level": baseline["fallback_level"],
                "n_support": n_specific,
            })
        else:
            output.append({
                "prediction": float(baseline["prediction"]),
                "prediction_source": "benchmark_fallback",
                "fallback_level": baseline["fallback_level"],
                "n_support": baseline["n_support"],
            })
    return output


def predict_date(
    *,
    history: Iterable[dict],
    targets: Iterable[dict],
    alpha: float,
    issue_date: date,
    lag_days: int = 60,
    min_group_support: int = MIN_GROUP_SUPPORT,
) -> list[dict]:
    """Fit Ridge on cutoff-eligible history and predict the next calendar day."""
    history_rows = list(history)
    state = fit_ridge_state(history=history_rows, alpha=alpha, issue_date=issue_date, lag_days=lag_days)
    return predict_from_state(
        state=state,
        history=history_rows,
        targets=targets,
        issue_date=issue_date,
        min_group_support=min_group_support,
    )
