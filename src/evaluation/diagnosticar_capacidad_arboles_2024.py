"""Capacity diagnosis for the fixed 15-leaf boosted-tree model, using 2024 only."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.baselines.weekday_period_mean import predict_one
from src.evaluation.benchmark_policy import cutoff_date, eligible_history
from src.models.arboles_potenciados import (
    feature_matrix,
    fit_tree_state,
    predict_from_tree_state,
)

DEFAULT_INPUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
DEFAULT_OUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/diagnostico-capacidad-arboles-2024"
MODEL_SOURCE = REPO_ROOT / "src/models/arboles_potenciados.py"
VALIDATION_SOURCE = REPO_ROOT / "src/evaluation/validar_arboles_potenciados_2024.py"
PROTOCOL = REPO_ROOT / "docs/protocol/protocolo-evaluacion-v1.2.md"
START = date(2024, 4, 6)
END = date(2024, 10, 31)
LAG_DAYS = 60
FIXED_PARAMS = {
    "max_leaf_nodes": 15,
    "lag_days": LAG_DAYS,
    "min_samples_leaf": 20,
    "max_iter": 30,
    "learning_rate": 0.05,
    "l2_regularization": 1.0,
}
ITERATIONS = 30


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
            day = date.fromisoformat(raw["fecha"])
            if day.year != 2024:
                raise ValueError("El diagnóstico de capacidad solo admite datos de 2024.")
            rows.append({"date": day, "hour": int(raw["hora"]), "value": Decimal(raw["demanda"])})
    if len({(row["date"], row["hour"]) for row in rows}) != len(rows):
        raise ValueError("La entrada contiene claves (fecha, hora) duplicadas.")
    return sorted(rows, key=lambda row: (row["date"], row["hour"]))


def metrics(predictions: list[float], observations: list[float]) -> dict:
    error = np.asarray(predictions, dtype=float) - np.asarray(observations, dtype=float)
    return {
        "n": int(len(error)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "bias_prediction_minus_observed": float(np.mean(error)),
    }


def profile_metrics(groups: list[dict], prefix: str) -> dict:
    actual = np.asarray([row["observed_mean"] for row in groups], dtype=float)
    prediction = np.asarray([row[f"{prefix}_mean"] for row in groups], dtype=float)
    weights = np.asarray([row["n"] for row in groups], dtype=float)
    centered_actual = actual - np.average(actual, weights=weights)
    centered_prediction = prediction - np.average(prediction, weights=weights)
    corr = float(np.corrcoef(actual, prediction)[0, 1]) if np.std(actual) and np.std(prediction) else None
    return {
        "groups": len(groups),
        "weighted_group_mean_mae": float(np.average(np.abs(prediction - actual), weights=weights)),
        "weighted_group_mean_rmse": float(np.sqrt(np.average((prediction - actual) ** 2, weights=weights))),
        "weighted_global_level_bias": float(np.average(prediction - actual, weights=weights)),
        "centered_profile_rmse": float(np.sqrt(np.average((centered_prediction - centered_actual) ** 2, weights=weights))),
        "profile_correlation": corr,
        "prediction_to_observed_profile_sd_ratio": float(np.std(prediction) / np.std(actual)) if np.std(actual) else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    input_path = args.input.resolve()
    rows = load_rows(input_path)
    by_date: dict[date, list[dict]] = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)
    target_dates = [day for day in sorted(by_date) if START <= day <= END]
    if len(target_dates) != (END - START).days + 1:
        raise ValueError("La ventana de desarrollo 2024 está incompleta.")

    # Per-origin learning curves are aggregated without storing each training row at each stage.
    train_abs_sum = np.zeros(ITERATIONS)
    train_sq_sum = np.zeros(ITERATIONS)
    train_n = np.zeros(ITERATIONS, dtype=np.int64)
    dev_abs_sum = np.zeros(ITERATIONS)
    dev_sq_sum = np.zeros(ITERATIONS)
    dev_bias_sum = np.zeros(ITERATIONS)
    dev_n = np.zeros(ITERATIONS, dtype=np.int64)
    per_origin_rows = []
    final_predictions = []
    last_state = None
    last_train_rows = None

    for origin_index, target_date in enumerate(target_dates):
        issue_date = target_date - timedelta(days=1)
        cutoff = cutoff_date(issue_date, LAG_DAYS)
        history = eligible_history(rows, issue_date, LAG_DAYS)
        if not history or any(row["date"] >= cutoff or row["date"] >= issue_date for row in history):
            raise AssertionError(f"Historia no elegible en origen {issue_date}.")
        targets = by_date[target_date]
        base_results = [
            predict_one(weekday=target_date.weekday(), period_index=row["hour"], history=history)
            for row in targets
        ]
        state = fit_tree_state(history=history, issue_date=issue_date, **FIXED_PARAMS)
        train_rows = [row for row in history if 1 <= int(row["hour"]) <= 24]
        train_x = feature_matrix(train_rows)
        train_y = np.asarray([float(row["value"]) for row in train_rows], dtype=float)
        model_target_indices = [
            i for i, row in enumerate(targets)
            if 1 <= int(row["hour"]) <= 24
            and state["support"][(target_date.weekday(), int(row["hour"]))] >= 5
        ]
        model_targets = [targets[i] for i in model_target_indices]
        target_x = feature_matrix(model_targets) if model_targets else np.empty((0, train_x.shape[1]))
        target_stage = state["estimator"].staged_predict(target_x) if model_targets else iter([np.array([])] * ITERATIONS)
        train_stage = state["estimator"].staged_predict(train_x)

        origin_train = []
        origin_dev = []
        for iteration, (train_prediction, model_prediction) in enumerate(zip(train_stage, target_stage), start=1):
            train_error = np.asarray(train_prediction, dtype=float) - train_y
            train_abs_sum[iteration - 1] += float(np.abs(train_error).sum())
            train_sq_sum[iteration - 1] += float(np.square(train_error).sum())
            train_n[iteration - 1] += len(train_error)
            origin_train.append((iteration, float(np.mean(np.abs(train_error))), float(np.sqrt(np.mean(train_error ** 2)))))

            model_values = {index: float(value) for index, value in zip(model_target_indices, model_prediction)}
            day_predictions = []
            day_observed = []
            for index, (target, base) in enumerate(zip(targets, base_results)):
                if base["prediction"] is None:
                    raise AssertionError("Benchmark sin soporte en objetivo común.")
                value = model_values.get(index, float(base["prediction"]))
                day_predictions.append(value)
                day_observed.append(float(target["value"]))
            errors = np.asarray(day_predictions) - np.asarray(day_observed)
            dev_abs_sum[iteration - 1] += float(np.abs(errors).sum())
            dev_sq_sum[iteration - 1] += float(np.square(errors).sum())
            dev_bias_sum[iteration - 1] += float(errors.sum())
            dev_n[iteration - 1] += len(errors)
            origin_dev.append((iteration, float(np.mean(np.abs(errors))), float(np.sqrt(np.mean(errors ** 2)))))

            if iteration == ITERATIONS:
                frozen_prediction_rows = predict_from_tree_state(
                    state=state, targets=targets, issue_date=issue_date
                )
                if any(
                    abs(day_predictions[i] - float(row["prediction"])) > 1e-8
                    for i, row in enumerate(frozen_prediction_rows)
                ):
                    raise AssertionError("La etapa 30 staged_predict no coincide con la predicción final.")
                for target, base, prediction in zip(
                    targets, base_results, frozen_prediction_rows,
                ):
                    final_predictions.append({
                        "target_date": target_date.isoformat(),
                        "issue_date": issue_date.isoformat(),
                        "target_weekday": target_date.weekday(),
                        "period_index": int(target["hour"]),
                        "observed": float(target["value"]),
                        "benchmark_prediction": float(base["prediction"]),
                        "tree_prediction": float(prediction["prediction"]),
                        "prediction_source": prediction["prediction_source"],
                        "fallback_level": prediction["fallback_level"],
                    })
        if len(origin_train) != ITERATIONS or len(origin_dev) != ITERATIONS:
            raise AssertionError("La curva staged_predict no generó 30 etapas.")
        for (iteration, train_mae, train_rmse), (_, target_mae, target_rmse) in zip(origin_train, origin_dev):
            per_origin_rows.append({
                "origin_index": origin_index,
                "target_date": target_date.isoformat(),
                "issue_date": issue_date.isoformat(),
                "cutoff_exclusive": cutoff.isoformat(),
                "history_start_date": state["history_start_date"].isoformat(),
                "history_end_date": state["history_end_date"].isoformat(),
                "history_dates": len({row["date"] for row in history}),
                "history_rows": state["history_count"],
                "iteration": iteration,
                "train_rows_ordinary_periods": len(train_rows),
                "train_mae": train_mae,
                "train_rmse": train_rmse,
                "development_target_mae": target_mae,
                "development_target_rmse": target_rmse,
            })
        last_state = state
        last_train_rows = train_rows

    learning_rows = []
    for iteration in range(1, ITERATIONS + 1):
        i = iteration - 1
        learning_rows.append({
            "iteration": iteration,
            "train_rows_across_origins": int(train_n[i]),
            "mean_train_mae_weighted_by_rows": train_abs_sum[i] / train_n[i],
            "mean_train_rmse_weighted_by_rows": math.sqrt(train_sq_sum[i] / train_n[i]),
            "validation_targets": int(dev_n[i]),
            "development_mae": dev_abs_sum[i] / dev_n[i],
            "development_rmse": math.sqrt(dev_sq_sum[i] / dev_n[i]),
            "development_bias": dev_bias_sum[i] / dev_n[i],
        })

    # Final-origin in-sample profile (history ends at 2024-08-30 under the 60-day rule).
    final_fit_values = last_state["estimator"].predict(feature_matrix(last_train_rows))
    train_profile_acc = defaultdict(lambda: {"observed": [], "tree": []})
    for row, prediction in zip(last_train_rows, final_fit_values):
        key = (row["date"].weekday(), int(row["hour"]))
        train_profile_acc[key]["observed"].append(float(row["value"]))
        train_profile_acc[key]["tree"].append(float(prediction))
    train_profile = []
    train_means = {}
    for key, values in sorted(train_profile_acc.items()):
        actual_mean = float(np.mean(values["observed"]))
        tree_mean = float(np.mean(values["tree"]))
        base_mean = actual_mean
        row = {"weekday": key[0], "period_index": key[1], "n": len(values["observed"]),
               "observed_mean": actual_mean, "benchmark_mean": base_mean, "tree_mean": tree_mean}
        train_profile.append(row)
        train_means[key] = row

    validation_profile_acc = defaultdict(lambda: {"observed": [], "tree": [], "benchmark": [], "tree_abs_error": [], "base_abs_error": []})
    for row in final_predictions:
        key = (row["target_weekday"], row["period_index"])
        cell = validation_profile_acc[key]
        cell["observed"].append(row["observed"])
        cell["tree"].append(row["tree_prediction"])
        cell["benchmark"].append(row["benchmark_prediction"])
        cell["tree_abs_error"].append(abs(row["tree_prediction"] - row["observed"]))
        cell["base_abs_error"].append(abs(row["benchmark_prediction"] - row["observed"]))
    validation_profile = []
    for key, values in sorted(validation_profile_acc.items()):
        validation_profile.append({
            "weekday": key[0], "period_index": key[1], "n": len(values["observed"]),
            "observed_mean": float(np.mean(values["observed"])),
            "tree_mean": float(np.mean(values["tree"])),
            "benchmark_mean": float(np.mean(values["benchmark"])),
            "tree_mae": float(np.mean(values["tree_abs_error"])),
            "benchmark_mae": float(np.mean(values["base_abs_error"])),
        })

    final_iteration = learning_rows[-1]
    profiles = {
        "validation_tree": profile_metrics(validation_profile, "tree"),
        "validation_benchmark": profile_metrics(validation_profile, "benchmark"),
        "training_final_origin_tree": profile_metrics(train_profile, "tree"),
        "training_final_origin_benchmark": profile_metrics(train_profile, "benchmark"),
    }
    overall_final = {
        "development_targets": len(final_predictions),
        "development_mae_iteration_30": final_iteration["development_mae"],
        "development_rmse_iteration_30": final_iteration["development_rmse"],
        "development_bias_iteration_30": final_iteration["development_bias"],
        "benchmark_mae_same_targets": float(np.mean([
            abs(row["benchmark_prediction"] - row["observed"]) for row in final_predictions
        ])),
        "training_mae_iteration_30_weighted": final_iteration["mean_train_mae_weighted_by_rows"],
        "training_rmse_iteration_30_weighted": final_iteration["mean_train_rmse_weighted_by_rows"],
        "profiles": profiles,
    }

    # Summarize the largest group-level validation gaps for inspection.
    group_gaps = sorted(
        validation_profile,
        key=lambda row: abs(row["tree_mean"] - row["observed_mean"]),
        reverse=True,
    )[:10]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_paths = {
        "learning_curve": args.output_dir / "curva-aprendizaje-arboles-2024.csv",
        "origin_learning": args.output_dir / "curva-arboles-por-origen-2024.csv",
        "validation_predictions": args.output_dir / "predicciones-finales-arboles-2024.csv",
        "validation_profile": args.output_dir / "perfil-validacion-dia-periodo-arboles-2024.csv",
        "training_profile": args.output_dir / "perfil-ajuste-origen-final-arboles-2024.csv",
    }
    for key, records in (
        ("learning_curve", learning_rows), ("origin_learning", per_origin_rows),
        ("validation_predictions", final_predictions), ("validation_profile", validation_profile),
        ("training_profile", train_profile),
    ):
        with out_paths[key].open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)

    summary = {
        "scope": "fixed 15-leaf model capacity diagnosis; 2024 only; no hyperparameter search",
        "target_window": {"start": START.isoformat(), "end": END.isoformat()},
        "model_parameters": FIXED_PARAMS,
        "iteration_diagnostic": learning_rows,
        "overall_iteration_30": overall_final,
        "validation_profile_groups": len(validation_profile),
        "training_profile_groups_final_origin": len(train_profile),
        "largest_validation_profile_gaps": group_gaps,
        "outputs": {key: path.name for key, path in out_paths.items()},
        "hashes": {
            "input_2024_csv": sha256(input_path),
            "protocol_v1_2": sha256(PROTOCOL),
            "tree_model": sha256(MODEL_SOURCE),
            "tree_validation_script": sha256(VALIDATION_SOURCE),
            "diagnostic_script": sha256(Path(__file__).resolve()),
        },
        "limits": [
            "Training histories differ by origin and are repeated across rolling fits; pooled training error is descriptive.",
            "Training size and target date advance together, so this diagnostic cannot identify the causal effect of history length.",
            "Group profile comparisons summarize the single 2024 development window and are not an independent evaluation.",
            "2025 was not read or used.",
        ],
    }
    summary_path = args.output_dir / "resumen-diagnostico-capacidad-arboles-2024.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target_dates": len(target_dates), "learning_curve_rows": len(learning_rows),
                      "origin_iteration_rows": len(per_origin_rows), "final": overall_final,
                      "summary": str(summary_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
