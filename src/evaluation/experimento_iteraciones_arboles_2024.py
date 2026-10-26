"""Controlled 2024 experiment varying only boosting iterations: 30, 60, 120."""
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
from src.models.arboles_potenciados import feature_matrix, fit_tree_state

DEFAULT_INPUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
DEFAULT_OUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/experimento-iteraciones-arboles-2024"
PROTOCOL = REPO_ROOT / "docs/protocol/protocolo-evaluacion-v1.2.md"
MODEL_SOURCE = REPO_ROOT / "src/models/arboles_potenciados.py"
START = date(2024, 4, 6)
END = date(2024, 10, 31)
LAG_DAYS = 60
ITERATION_CHECKPOINTS = (30, 60, 120)
FIXED_PARAMS = {
    "max_leaf_nodes": 15,
    "min_samples_leaf": 20,
    "learning_rate": 0.05,
    "l2_regularization": 1.0,
}


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
                raise ValueError("El experimento solo admite registros de 2024.")
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


def group_profile_metrics(profile_rows: list[dict], prediction_field: str) -> dict:
    observed = np.asarray([row["observed_mean"] for row in profile_rows], dtype=float)
    predicted = np.asarray([row[prediction_field] for row in profile_rows], dtype=float)
    weights = np.asarray([row["n"] for row in profile_rows], dtype=float)
    observed_centered = observed - np.average(observed, weights=weights)
    predicted_centered = predicted - np.average(predicted, weights=weights)
    correlation = float(np.corrcoef(observed, predicted)[0, 1]) if np.std(observed) and np.std(predicted) else None
    return {
        "groups": len(profile_rows),
        "weighted_group_mean_mae": float(np.average(np.abs(predicted - observed), weights=weights)),
        "weighted_group_mean_rmse": float(np.sqrt(np.average((predicted - observed) ** 2, weights=weights))),
        "weighted_global_level_bias": float(np.average(predicted - observed, weights=weights)),
        "centered_profile_rmse": float(np.sqrt(np.average((predicted_centered - observed_centered) ** 2, weights=weights))),
        "unweighted_profile_correlation": correlation,
        "unweighted_predicted_to_observed_profile_sd_ratio": float(np.std(predicted) / np.std(observed)) if np.std(observed) else None,
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

    predictions_by_iteration = {iteration: [] for iteration in ITERATION_CHECKPOINTS}
    learning_rows = []
    final_origin_training_profile = []

    for origin_index, target_date in enumerate(target_dates):
        issue_date = target_date - timedelta(days=1)
        cutoff = cutoff_date(issue_date, LAG_DAYS)
        history = eligible_history(rows, issue_date, LAG_DAYS)
        if not history or any(row["date"] >= cutoff or row["date"] >= issue_date for row in history):
            raise AssertionError(f"Historia no elegible en origen {issue_date}.")
        targets = by_date[target_date]
        benchmark_results = [
            predict_one(weekday=target_date.weekday(), period_index=row["hour"], history=history)
            for row in targets
        ]
        if any(result["prediction"] is None for result in benchmark_results):
            raise AssertionError("El benchmark no cubre un objetivo común.")

        # Fit one 120-stage model. Its staged predictions at 30 and 60 are the
        # exact prefixes of this same deterministic boosting sequence.
        state = fit_tree_state(
            history=history,
            issue_date=issue_date,
            max_iter=120,
            lag_days=LAG_DAYS,
            **FIXED_PARAMS,
        )
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
        train_stages = state["estimator"].staged_predict(train_x)
        target_stages = state["estimator"].staged_predict(target_x) if model_targets else None
        train_at_checkpoints = {}
        target_at_checkpoints = {}
        target_stage_iter = iter(target_stages) if target_stages is not None else None

        for iteration, train_values in enumerate(train_stages, start=1):
            train_values = np.asarray(train_values, dtype=float)
            target_values = np.asarray(next(target_stage_iter), dtype=float) if target_stage_iter is not None else np.array([])
            if iteration not in ITERATION_CHECKPOINTS:
                continue
            train_at_checkpoints[iteration] = train_values
            target_at_checkpoints[iteration] = target_values

        if tuple(sorted(train_at_checkpoints)) != ITERATION_CHECKPOINTS:
            raise AssertionError("No se generaron todos los puntos 30/60/120.")

        for iteration in ITERATION_CHECKPOINTS:
            train_prediction = train_at_checkpoints[iteration]
            train_metric = metrics(train_prediction.tolist(), train_y.tolist())
            target_model_values = {
                index: float(value)
                for index, value in zip(model_target_indices, target_at_checkpoints[iteration])
            }
            day_predictions = []
            day_observed = []
            rows_for_day = []
            for index, (target, base) in enumerate(zip(targets, benchmark_results)):
                prediction = target_model_values.get(index, float(base["prediction"]))
                observed = float(target["value"])
                day_predictions.append(prediction)
                day_observed.append(observed)
                rows_for_day.append({
                    "max_iter": iteration,
                    "issue_date_local": issue_date.isoformat(),
                    "issue_time_local": "18:00 America/Santiago",
                    "cutoff_exclusive": cutoff.isoformat(),
                    "history_start_date": state["history_start_date"].isoformat(),
                    "history_end_date": state["history_end_date"].isoformat(),
                    "history_dates": len({row["date"] for row in history}),
                    "history_rows": state["history_count"],
                    "target_date": target_date.isoformat(),
                    "target_weekday_monday0": target_date.weekday(),
                    "target_period_index": int(target["hour"]),
                    "prediction": prediction,
                    "prediction_source": "tree" if index in target_model_values else "benchmark_fallback",
                    "observed_ex_post": str(target["value"]),
                    "benchmark_prediction": str(base["prediction"]),
                })
            day_metric = metrics(day_predictions, day_observed)
            learning_rows.append({
                "origin_index": origin_index,
                "target_date": target_date.isoformat(),
                "issue_date": issue_date.isoformat(),
                "cutoff_exclusive": cutoff.isoformat(),
                "history_rows": state["history_count"],
                "history_dates": len({row["date"] for row in history}),
                "max_iter": iteration,
                "train_rows": train_metric["n"],
                "train_mae": train_metric["mae"],
                "train_rmse": train_metric["rmse"],
                "development_periods": day_metric["n"],
                "development_mae": day_metric["mae"],
                "development_rmse": day_metric["rmse"],
                "development_bias": day_metric["bias_prediction_minus_observed"],
            })
            predictions_by_iteration[iteration].extend(rows_for_day)

            if target_date == END:
                last_train_values = train_at_checkpoints[iteration]
                profile_acc = defaultdict(lambda: {"observed": [], "tree": []})
                for row, prediction in zip(train_rows, last_train_values):
                    key = (row["date"].weekday(), int(row["hour"]))
                    profile_acc[key]["observed"].append(float(row["value"]))
                    profile_acc[key]["tree"].append(float(prediction))
                for key, values in sorted(profile_acc.items()):
                    actual_mean = float(np.mean(values["observed"]))
                    final_origin_training_profile.append({
                        "max_iter": iteration,
                        "weekday": key[0],
                        "period_index": key[1],
                        "n": len(values["observed"]),
                        "observed_mean": actual_mean,
                        "benchmark_mean": actual_mean,
                        "tree_mean": float(np.mean(values["tree"])),
                    })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = args.output_dir / "predicciones-arboles-iteraciones-2024.csv"
    origin_path = args.output_dir / "metricas-por-origen-iteraciones-2024.csv"
    training_profile_path = args.output_dir / "perfil-entrenamiento-iteraciones-2024.csv"
    profile_path = args.output_dir / "perfil-validacion-iteraciones-2024.csv"

    all_predictions = [row for iteration in ITERATION_CHECKPOINTS for row in predictions_by_iteration[iteration]]
    previous_csv = REPO_ROOT / "data/audits/2024-demanda-sistemica/arboles-potenciados-validacion-2024/predicciones-arboles-potenciados-2024.csv"
    with previous_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        previous_predictions = {
            (row["target_date"], int(row["target_period_index"])): float(row["prediction"])
            for row in csv.DictReader(stream)
            if int(row["max_leaf_nodes"]) == 15
        }
    stage30 = {
        (row["target_date"], int(row["target_period_index"])): float(row["prediction"])
        for row in predictions_by_iteration[30]
    }
    if set(previous_predictions) != set(stage30):
        raise AssertionError("La etapa 30 no cubre los mismos objetivos que la validación previa.")
    max_abs_diff_stage30 = max(abs(previous_predictions[key] - stage30[key]) for key in stage30)
    if max_abs_diff_stage30 > 1e-8:
        raise AssertionError("La etapa 30 no reproduce el modelo de 30 iteraciones previamente validado.")
    with prediction_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_predictions[0]))
        writer.writeheader()
        writer.writerows(all_predictions)
    with origin_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(learning_rows[0]))
        writer.writeheader()
        writer.writerows(learning_rows)
    with training_profile_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(final_origin_training_profile[0]))
        writer.writeheader()
        writer.writerows(final_origin_training_profile)

    overall = {}
    monthly = {}
    validation_profiles = []
    for iteration in ITERATION_CHECKPOINTS:
        records = predictions_by_iteration[iteration]
        model_metrics = metrics([float(row["prediction"]) for row in records],
                                [float(row["observed_ex_post"]) for row in records])
        benchmark_metrics = metrics([float(row["benchmark_prediction"]) for row in records],
                                    [float(row["observed_ex_post"]) for row in records])
        overall[str(iteration)] = {
            "tree": model_metrics,
            "benchmark_same_targets": benchmark_metrics,
            "mae_delta_vs_benchmark": model_metrics["mae"] - benchmark_metrics["mae"],
            "fallback_predictions": sum(row["prediction_source"] == "benchmark_fallback" for row in records),
        }
        monthly[str(iteration)] = {}
        profile_acc = defaultdict(lambda: {"observed": [], "tree": [], "benchmark": [], "tree_ae": [], "benchmark_ae": []})
        for row in records:
            month = row["target_date"][:7]
            monthly[str(iteration)].setdefault(month, []).append(row)
            key = (int(row["target_weekday_monday0"]), int(row["target_period_index"]))
            cell = profile_acc[key]
            observed = float(row["observed_ex_post"])
            prediction = float(row["prediction"])
            benchmark = float(row["benchmark_prediction"])
            cell["observed"].append(observed)
            cell["tree"].append(prediction)
            cell["benchmark"].append(benchmark)
            cell["tree_ae"].append(abs(prediction - observed))
            cell["benchmark_ae"].append(abs(benchmark - observed))
        for month, month_rows in monthly[str(iteration)].items():
            monthly[str(iteration)][month] = {
                "tree": metrics([float(r["prediction"]) for r in month_rows], [float(r["observed_ex_post"]) for r in month_rows]),
                "benchmark": metrics([float(r["benchmark_prediction"]) for r in month_rows], [float(r["observed_ex_post"]) for r in month_rows]),
            }
        for key, cell in sorted(profile_acc.items()):
            validation_profiles.append({
                "max_iter": iteration, "weekday": key[0], "period_index": key[1], "n": len(cell["observed"]),
                "observed_mean": float(np.mean(cell["observed"])),
                "tree_mean": float(np.mean(cell["tree"])),
                "benchmark_mean": float(np.mean(cell["benchmark"])),
                "tree_mae": float(np.mean(cell["tree_ae"])),
                "benchmark_mae": float(np.mean(cell["benchmark_ae"])),
            })
    with profile_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(validation_profiles[0]))
        writer.writeheader()
        writer.writerows(validation_profiles)

    train_curve = {}
    for iteration in ITERATION_CHECKPOINTS:
        per_origin = [row for row in learning_rows if row["max_iter"] == iteration]
        train_n = sum(row["train_rows"] for row in per_origin)
        train_abs = sum(row["train_mae"] * row["train_rows"] for row in per_origin)
        train_sq = sum((row["train_rmse"] ** 2) * row["train_rows"] for row in per_origin)
        train_curve[str(iteration)] = {
            "origins": len(per_origin),
            "mean_train_mae_weighted_by_rows": train_abs / train_n,
            "mean_train_rmse_weighted_by_rows": math.sqrt(train_sq / train_n),
            "mean_development_mae_per_origin": float(np.mean([row["development_mae"] for row in per_origin])),
            "mean_development_rmse_per_origin": float(np.mean([row["development_rmse"] for row in per_origin])),
        }

    final_train_profile_rows = [row for row in final_origin_training_profile if row["max_iter"] == 120]
    profile_summary = {}
    for iteration in ITERATION_CHECKPOINTS:
        validation_rows = [row for row in validation_profiles if row["max_iter"] == iteration]
        training_rows = [row for row in final_origin_training_profile if row["max_iter"] == iteration]
        profile_summary[str(iteration)] = {
            "validation_tree": group_profile_metrics(validation_rows, "tree_mean"),
            "validation_benchmark": group_profile_metrics(validation_rows, "benchmark_mean"),
            "final_origin_training_tree": group_profile_metrics(training_rows, "tree_mean"),
            "final_origin_training_benchmark": group_profile_metrics(training_rows, "benchmark_mean"),
        }

    selected_iteration = min(
        ITERATION_CHECKPOINTS,
        key=lambda iteration: (overall[str(iteration)]["tree"]["mae"], iteration),
    )
    summary = {
        "scope": "controlled 2024 development experiment; only max_iter varies; no 2025 data read",
        "target_window": {"start": START.isoformat(), "end": END.isoformat()},
        "fixed_parameters": {**FIXED_PARAMS, "early_stopping": False, "random_state": 42},
        "iteration_values": list(ITERATION_CHECKPOINTS),
        "implementation_note": "Fit one deterministic 120-stage model per origin; staged predictions at 30 and 60 are prefixes of the same sequence, with early stopping disabled.",
        "stage_30_reproduction": {"matched_predictions": len(stage30), "maximum_absolute_difference": max_abs_diff_stage30},
        "selection_rule": "minimum 2024 development MAE; exact ties prefer fewer iterations",
        "best_iteration_in_tested_set": selected_iteration,
        "overall_metrics": overall,
        "monthly_metrics": monthly,
        "training_and_development_curve": train_curve,
        "profile_metrics": profile_summary,
        "coverage": {
            "origins": len(target_dates),
            "targets_per_iteration": sum(len(by_date[day]) for day in target_dates),
            "prediction_rows": len(all_predictions),
            "missing_predictions_per_iteration": 0,
        },
        "outputs": {
            "predictions": prediction_path.name,
            "origin_metrics": origin_path.name,
            "validation_profiles": profile_path.name,
            "final_origin_training_profiles": training_profile_path.name,
        },
        "hashes": {
            "input_2024_csv": sha256(input_path),
            "protocol_v1_2": sha256(PROTOCOL),
            "model_implementation": sha256(MODEL_SOURCE),
            "experiment_script": sha256(Path(__file__).resolve()),
            "previous_30_iteration_predictions": sha256(previous_csv),
        },
        "limits": [
            "The iteration comparison is on the already-used 2024 development window and is not independent performance estimation.",
            "Training histories differ by rolling origin; pooled train error repeats observations across fits.",
            "The 120-iteration result does not establish what would happen beyond 120 iterations.",
            "2025 was not read or scored.",
        ],
    }
    summary_path = args.output_dir / "resumen-experimento-iteraciones-arboles-2024.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"iteration_values": list(ITERATION_CHECKPOINTS), "selected_iteration": selected_iteration,
                      "overall_metrics": overall, "training_curve": train_curve,
                      "profile_metrics": profile_summary, "summary": str(summary_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
