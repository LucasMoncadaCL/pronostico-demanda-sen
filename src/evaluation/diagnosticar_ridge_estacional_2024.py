"""Diagnose the seasonal correction using only the 2024 development window."""
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

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.baselines.weekday_period_mean import predict_one
from src.evaluation.benchmark_policy import cutoff_date, eligible_history
from src.models.ridge_estacional import fit_ridge_state, predict_from_state

DEFAULT_INPUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
DEFAULT_OUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/diagnostico-ridge-estacional-2024"
MODEL_SOURCE = REPO_ROOT / "src/models/ridge_estacional.py"
VALIDATION_SOURCE = REPO_ROOT / "src/evaluation/validar_ridge_estacional_2024.py"
PROTOCOL = REPO_ROOT / "docs/protocol/protocolo-evaluacion-v1.2.md"
START = date(2024, 4, 6)
END = date(2024, 10, 31)
LAG_DAYS = 60
ALPHAS = (0.1, 1.0, 10.0, 100.0)
SELECTED_ALPHA = 100.0


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
                raise ValueError("El diagnóstico solo admite observaciones de 2024.")
            rows.append({"date": day, "hour": int(raw["hora"]), "value": Decimal(raw["demanda"])})
    if len({(r["date"], r["hour"]) for r in rows}) != len(rows):
        raise ValueError("La entrada contiene claves (fecha, hora) duplicadas.")
    return sorted(rows, key=lambda r: (r["date"], r["hour"]))


def score(records: list[dict], prediction_key: str) -> dict:
    errors = [float(row[prediction_key]) - float(row["observed"]) for row in records]
    absolute = [abs(value) for value in errors]
    return {
        "n": len(errors),
        "mae": sum(absolute) / len(absolute),
        "rmse": math.sqrt(sum(value * value for value in errors) / len(errors)),
        "bias_prediction_minus_observed": sum(errors) / len(errors),
    }


def summarize_records(records: list[dict], alpha: float) -> dict:
    selected = [row for row in records if row["alpha"] == alpha]
    ridge = score(selected, "ridge_prediction")
    benchmark = score(selected, "benchmark_prediction")
    deteriorations = [row["absolute_error_delta"] for row in selected]
    corrections = [abs(row["correction"]) for row in selected]
    base_levels = [abs(row["benchmark_prediction"]) for row in selected]
    improved = sum(delta < -1e-10 for delta in deteriorations)
    worsened = sum(delta > 1e-10 for delta in deteriorations)
    unchanged = len(deteriorations) - improved - worsened
    return {
        "n": len(selected),
        "ridge": ridge,
        "benchmark_same_targets": benchmark,
        "mae_delta_ridge_minus_benchmark": ridge["mae"] - benchmark["mae"],
        "periods_improved_by_correction": improved,
        "periods_worsened_by_correction": worsened,
        "periods_effectively_unchanged": unchanged,
        "mean_absolute_correction": sum(corrections) / len(corrections),
        "p90_absolute_correction": sorted(corrections)[math.ceil(0.9 * len(corrections)) - 1],
        "mean_absolute_correction_as_percent_of_base":
            100 * sum(corrections) / sum(base_levels),
        "mean_signed_correction": sum(row["correction"] for row in selected) / len(selected),
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
    target_dates = [d for d in sorted(by_date) if START <= d <= END]
    if len(target_dates) != (END - START).days + 1:
        raise ValueError("La ventana de desarrollo 2024 está incompleta.")
    target_period_count = sum(len(by_date[d]) for d in target_dates)

    point_rows: list[dict] = []
    origin_rows: list[dict] = []
    for origin_index, target_date in enumerate(target_dates):
        issue_date = target_date - timedelta(days=1)
        cutoff = cutoff_date(issue_date, LAG_DAYS)
        history = eligible_history(rows, issue_date, LAG_DAYS)
        if not history or any(row["date"] >= cutoff for row in history):
            raise AssertionError(f"Historia inválida para origen {issue_date}.")
        targets = by_date[target_date]
        bases = [
            predict_one(weekday=target_date.weekday(), period_index=row["hour"], history=history)
            for row in targets
        ]
        for alpha in ALPHAS:
            state = fit_ridge_state(
                history=history, alpha=alpha, issue_date=issue_date, lag_days=LAG_DAYS
            )
            predictions = predict_from_state(
                state=state, history=history, targets=targets, issue_date=issue_date
            )
            date_records = []
            for target, baseline, prediction in zip(targets, bases, predictions):
                if baseline["prediction"] is None:
                    raise AssertionError("El benchmark no cubre un objetivo común.")
                benchmark_value = float(baseline["prediction"])
                predicted_value = float(prediction["prediction"])
                observed = float(target["value"])
                record = {
                    "alpha": alpha,
                    "target_date": target_date.isoformat(),
                    "issue_date": issue_date.isoformat(),
                    "cutoff_exclusive": cutoff.isoformat(),
                    "history_start_date": state["history_start_date"].isoformat(),
                    "history_end_date": state["history_end_date"].isoformat(),
                    "history_rows": state["history_rows"],
                    "history_days": len({row["date"] for row in history}),
                    "target_period_index": int(target["hour"]),
                    "coefficient_sin": float(state["coefficients"][0]),
                    "coefficient_cos": float(state["coefficients"][1]),
                    "coefficient_norm": float(math.sqrt(sum(c * c for c in state["coefficients"]))),
                    "benchmark_prediction": benchmark_value,
                    "ridge_prediction": predicted_value,
                    "correction": predicted_value - benchmark_value,
                    "prediction_source": prediction["prediction_source"],
                    "observed": observed,
                    "benchmark_absolute_error": abs(benchmark_value - observed),
                    "ridge_absolute_error": abs(predicted_value - observed),
                    "absolute_error_delta": abs(predicted_value - observed) - abs(benchmark_value - observed),
                }
                date_records.append(record)
                point_rows.append(record)

            date_benchmark_mae = sum(r["benchmark_absolute_error"] for r in date_records) / len(date_records)
            date_ridge_mae = sum(r["ridge_absolute_error"] for r in date_records) / len(date_records)
            abs_corrections = [abs(r["correction"]) for r in date_records]
            base_mae = sum(abs(r["benchmark_prediction"]) for r in date_records) / len(date_records)
            origin_rows.append({
                "alpha": alpha,
                "origin_index": origin_index,
                "target_date": target_date.isoformat(),
                "issue_date": issue_date.isoformat(),
                "cutoff_exclusive": cutoff.isoformat(),
                "history_start_date": state["history_start_date"].isoformat(),
                "history_end_date": state["history_end_date"].isoformat(),
                "history_days": len({row["date"] for row in history}),
                "history_rows": state["history_rows"],
                "coefficient_sin": float(state["coefficients"][0]),
                "coefficient_cos": float(state["coefficients"][1]),
                "coefficient_norm": float(math.sqrt(sum(c * c for c in state["coefficients"]))),
                "mean_absolute_correction": sum(abs_corrections) / len(abs_corrections),
                "max_absolute_correction": max(abs_corrections),
                "mean_absolute_correction_pct_of_mean_base":
                    100 * sum(abs_corrections) / (sum(abs(r["benchmark_prediction"]) for r in date_records)),
                "benchmark_mae": date_benchmark_mae,
                "ridge_mae": date_ridge_mae,
                "mae_delta_ridge_minus_benchmark": date_ridge_mae - date_benchmark_mae,
                "periods_improved": sum(r["absolute_error_delta"] < -1e-10 for r in date_records),
                "periods_worsened": sum(r["absolute_error_delta"] > 1e-10 for r in date_records),
            })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    point_path = args.output_dir / "diagnostico-ridge-2024-por-periodo.csv"
    origin_path = args.output_dir / "diagnostico-ridge-2024-por-origen.csv"
    for path, data in ((point_path, point_rows), (origin_path, origin_rows)):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)

    alpha_summaries = {}
    month_summaries = {}
    stage_summaries = {}
    for alpha in ALPHAS:
        alpha_summaries[str(alpha)] = summarize_records(point_rows, alpha)
        month_summaries[str(alpha)] = {}
        for month in range(4, 11):
            month_rows = [r for r in point_rows if r["alpha"] == alpha and int(r["target_date"][5:7]) == month]
            month_summaries[str(alpha)][f"2024-{month:02d}"] = {
                "ridge": score(month_rows, "ridge_prediction"),
                "benchmark": score(month_rows, "benchmark_prediction"),
                "mae_delta_ridge_minus_benchmark":
                    score(month_rows, "ridge_prediction")["mae"] - score(month_rows, "benchmark_prediction")["mae"],
            }
        ordered_origins = sorted(
            [r for r in origin_rows if r["alpha"] == alpha], key=lambda r: r["origin_index"]
        )
        blocks = {"early": [], "middle": [], "late": []}
        count = len(ordered_origins)
        for i, origin in enumerate(ordered_origins):
            bucket = min(2, (i * 3) // count)
            blocks[("early", "middle", "late")[bucket]].append(origin)
        stage_summaries[str(alpha)] = {}
        for label, block in blocks.items():
            target_set = {row["target_date"] for row in block}
            block_points = [r for r in point_rows if r["alpha"] == alpha and r["target_date"] in target_set]
            coeff_sin = [r["coefficient_sin"] for r in block]
            coeff_cos = [r["coefficient_cos"] for r in block]
            stage_summaries[str(alpha)][label] = {
                "target_start": block[0]["target_date"],
                "target_end": block[-1]["target_date"],
                "origins": len(block),
                "mean_history_days": sum(r["history_days"] for r in block) / len(block),
                "mean_history_rows": sum(r["history_rows"] for r in block) / len(block),
                "coefficient_sin_mean": sum(coeff_sin) / len(coeff_sin),
                "coefficient_sin_min": min(coeff_sin),
                "coefficient_sin_max": max(coeff_sin),
                "coefficient_cos_mean": sum(coeff_cos) / len(coeff_cos),
                "coefficient_cos_min": min(coeff_cos),
                "coefficient_cos_max": max(coeff_cos),
                "mean_absolute_correction_pct_of_mean_base":
                    sum(r["mean_absolute_correction_pct_of_mean_base"] for r in block) / len(block),
                "ridge": score(block_points, "ridge_prediction"),
                "benchmark": score(block_points, "benchmark_prediction"),
            }

    selected_origins = sorted(
        [r for r in origin_rows if r["alpha"] == SELECTED_ALPHA],
        key=lambda r: r["mae_delta_ridge_minus_benchmark"], reverse=True,
    )
    worsened_top = [
        {"target_date": r["target_date"], "daily_mae_delta": r["mae_delta_ridge_minus_benchmark"],
         "history_days": r["history_days"], "mean_absolute_correction_pct_of_mean_base": r["mean_absolute_correction_pct_of_mean_base"]}
        for r in selected_origins[:10]
    ]
    summary = {
        "scope": "2024 only; diagnostic of the already tested Ridge specification; no alpha search expansion",
        "target_window": {"start": START.isoformat(), "end": END.isoformat()},
        "issue_time_local": "18:00 America/Santiago on target_date - 1 calendar day",
        "cutoff": "observation_date < issue_date - 60 calendar days; strict date comparison",
        "alpha_values_reexamined": list(ALPHAS),
        "selected_alpha_from_prior_2024_selection": SELECTED_ALPHA,
        "overall_by_alpha": alpha_summaries,
        "monthly_by_alpha": month_summaries,
        "history_stage_by_alpha": stage_summaries,
        "top_10_daily_deteriorations_at_alpha_100": worsened_top,
        "coverage": {"target_dates": len(target_dates), "targets_per_alpha": target_period_count,
                     "point_rows": len(point_rows), "origin_rows": len(origin_rows),
                     "missing_target_predictions": 0},
        "outputs": {"per_period_csv": point_path.name, "per_origin_csv": origin_path.name},
        "hashes": {
            "input_2024_csv": sha256(input_path),
            "protocol_v1_2": sha256(PROTOCOL),
            "ridge_model": sha256(MODEL_SOURCE),
            "ridge_validation_script": sha256(VALIDATION_SOURCE),
            "diagnostic_script": sha256(Path(__file__).resolve()),
        },
        "interpretation_limits": [
            "Monthly and early/middle/late results are descriptive decompositions of the 2024 development window.",
            "They are not independent estimates and must not guide tuning on 2025.",
            "Coefficient instability or error association is diagnostic evidence, not proof of causal mechanism.",
        ],
    }
    summary_path = args.output_dir / "resumen-diagnostico-ridge-2024.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target_dates": len(target_dates), "point_rows": len(point_rows),
        "origin_rows": len(origin_rows), "summary": str(summary_path),
        "alpha_100_overall": alpha_summaries[str(SELECTED_ALPHA)],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
