"""Calendar-only histogram gradient boosting for SEN demand forecasting."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Iterable

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from src.baselines.weekday_period_mean import MIN_GROUP_SUPPORT, predict_one
from src.evaluation.benchmark_policy import cutoff_date

PERIODS_PER_ORDINARY_DAY = 24
FEATURE_COUNT = 7 + PERIODS_PER_ORDINARY_DAY + 2


def _annual_fourier(day: date) -> tuple[float, float]:
    days_in_year = 366 if _is_leap_year(day.year) else 365
    phase = 2.0 * np.pi * (day.timetuple().tm_yday - 1) / days_in_year
    return float(np.sin(phase)), float(np.cos(phase))


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def feature_matrix(rows: Iterable[dict]) -> np.ndarray:
    """One-hot calendar categories and annual sine/cosine features."""
    records = list(rows)
    matrix = np.zeros((len(records), FEATURE_COUNT), dtype=np.float64)
    for i, row in enumerate(records):
        period = int(row["hour"])
        if not 1 <= period <= PERIODS_PER_ORDINARY_DAY:
            raise ValueError(f"El modelo no codifica el período no ordinario {period}.")
        matrix[i, row["date"].weekday()] = 1.0
        matrix[i, 7 + period - 1] = 1.0
        matrix[i, 31:33] = _annual_fourier(row["date"])
    return matrix


def fit_tree_state(
    *,
    history: Iterable[dict],
    issue_date: date,
    max_leaf_nodes: int,
    lag_days: int = 60,
    min_samples_leaf: int = 20,
    max_iter: int = 50,
    learning_rate: float = 0.05,
    l2_regularization: float = 1.0,
) -> dict:
    """Fit on eligible history; reject rows at or after the strict cutoff."""
    history_rows = list(history)
    cutoff = cutoff_date(issue_date, lag_days)
    if any(row["date"] >= cutoff for row in history_rows):
        raise ValueError(f"La historia debe ser estrictamente anterior al corte exclusivo {cutoff}.")
    if any(row["date"] >= issue_date for row in history_rows):
        raise ValueError("La historia contiene observaciones del día de emisión o posteriores.")
    if not history_rows:
        raise ValueError("Se requiere historia elegible para ajustar el modelo.")
    if max_leaf_nodes < 2:
        raise ValueError("max_leaf_nodes debe ser al menos 2.")

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
        raise ValueError("No hay períodos ordinarios elegibles para entrenar.")

    estimator = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=learning_rate,
        max_iter=max_iter,
        max_leaf_nodes=max_leaf_nodes,
        min_samples_leaf=min_samples_leaf,
        l2_regularization=l2_regularization,
        early_stopping=False,
        random_state=42,
    )
    estimator.fit(
        feature_matrix(train_rows),
        np.asarray([float(row["value"]) for row in train_rows], dtype=np.float64),
    )
    return {
        "estimator": estimator,
        "support": support,
        "eligible_history": tuple(history_rows),
        "history_count": len(history_rows),
        "history_start_date": min(row["date"] for row in history_rows),
        "history_end_date": max(row["date"] for row in history_rows),
        "issue_date": issue_date,
        "cutoff_exclusive": cutoff,
        "max_leaf_nodes": max_leaf_nodes,
        "min_samples_leaf": min_samples_leaf,
        "max_iter": max_iter,
        "learning_rate": learning_rate,
        "l2_regularization": l2_regularization,
    }


def predict_from_tree_state(
    *,
    state: dict,
    targets: Iterable[dict],
    issue_date: date,
    min_group_support: int = MIN_GROUP_SUPPORT,
) -> list[dict]:
    history_rows = list(state["eligible_history"])
    target_rows = list(targets)
    if state["issue_date"] != issue_date:
        raise ValueError("La fecha de emisión no coincide con la usada para ajustar el modelo.")
    if any(row["date"] >= state["cutoff_exclusive"] for row in history_rows):
        raise ValueError("El estado contiene historia posterior al corte exclusivo.")
    target_dates = {row["date"] for row in target_rows}
    if len(target_dates) > 1:
        raise ValueError("La función recibe objetivos de una sola fecha.")
    if not target_dates:
        return []
    target_date = next(iter(target_dates))
    if target_date != issue_date + timedelta(days=1):
        raise ValueError("Los objetivos deben corresponder al día calendario siguiente.")

    model_targets = [
        row for row in target_rows
        if 1 <= int(row["hour"]) <= PERIODS_PER_ORDINARY_DAY
        and state["support"][(target_date.weekday(), int(row["hour"]))] >= min_group_support
    ]
    model_predictions = {}
    if model_targets:
        values = state["estimator"].predict(feature_matrix(model_targets))
        model_predictions = {id(row): float(value) for row, value in zip(model_targets, values)}

    results = []
    for target in target_rows:
        period = int(target["hour"])
        if id(target) in model_predictions:
            results.append({
                "prediction": model_predictions[id(target)],
                "prediction_source": "hist_gradient_boosting",
                "fallback_level": "",
                "n_support": state["support"][(target_date.weekday(), period)],
            })
        else:
            fallback = predict_one(
                weekday=target_date.weekday(), period_index=period, history=history_rows
            )
            if fallback["prediction"] is None:
                raise ValueError(f"Sin soporte para {target_date}, período {period}.")
            results.append({
                "prediction": float(fallback["prediction"]),
                "prediction_source": "benchmark_fallback",
                "fallback_level": fallback["fallback_level"],
                "n_support": fallback["n_support"],
            })
    return results


def predict_date(
    *,
    history: Iterable[dict],
    targets: Iterable[dict],
    issue_date: date,
    max_leaf_nodes: int,
    lag_days: int = 60,
    min_samples_leaf: int = 20,
    max_iter: int = 50,
    learning_rate: float = 0.05,
    l2_regularization: float = 1.0,
) -> list[dict]:
    history_rows = list(history)
    state = fit_tree_state(
        history=history_rows,
        issue_date=issue_date,
        max_leaf_nodes=max_leaf_nodes,
        lag_days=lag_days,
        min_samples_leaf=min_samples_leaf,
        max_iter=max_iter,
        learning_rate=learning_rate,
        l2_regularization=l2_regularization,
    )
    return predict_from_tree_state(
        state=state, targets=targets, issue_date=issue_date
    )
