"""Select and validate seasonal Ridge using only the registered 2024 window."""
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
from src.models.ridge_estacional import predict_date

DEFAULT_INPUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
DEFAULT_OUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/ridge-estacional-validacion-2024"
PROTOCOL = REPO_ROOT / "docs/protocol/protocolo-evaluacion-v1.2.md"
START = date(2024, 4, 6)
END = date(2024, 10, 31)
LAG_DAYS = 60
ALPHAS = (0.1, 1.0, 10.0, 100.0)


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
            rows.append({
                "date": date.fromisoformat(raw["fecha"]),
                "hour": int(raw["hora"]),
                "value": Decimal(raw["demanda"]),
            })
    keys = [(r["date"], r["hour"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("La serie contiene claves (fecha, hora) duplicadas.")
    return sorted(rows, key=lambda r: (r["date"], r["hour"]))


def metric_summary(rows: list[dict], prediction_field: str) -> dict:
    errors = [float(r[prediction_field]) - float(r["observed_ex_post"]) for r in rows]
    return {
        "n": len(errors),
        "mae": sum(abs(e) for e in errors) / len(errors),
        "rmse": math.sqrt(sum(e * e for e in errors) / len(errors)),
        "bias_prediction_minus_observed": sum(errors) / len(errors),
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
    expected = (END - START).days + 1
    if len(target_dates) != expected:
        raise ValueError(f"Ventana incompleta: {len(target_dates)} fechas de {expected}.")

    predictions_by_alpha: dict[float, list[dict]] = {alpha: [] for alpha in ALPHAS}
    origins = []
    for target_date in target_dates:
        issue_date = target_date - timedelta(days=1)
        cutoff = cutoff_date(issue_date, LAG_DAYS)
        history = eligible_history(rows, issue_date, LAG_DAYS)
        if any(r["date"] >= cutoff or r["date"] >= issue_date for r in history):
            raise AssertionError(f"Fuga temporal en emisión {issue_date}.")
        if not history:
            raise ValueError(f"No hay historia elegible para {issue_date}.")
        targets = by_date[target_date]
        baseline_results = [
            predict_one(weekday=target_date.weekday(), period_index=r["hour"], history=history)
            for r in targets
        ]
        for alpha in ALPHAS:
            ridge_results = predict_date(
                history=history, targets=targets, alpha=alpha, issue_date=issue_date,
                lag_days=LAG_DAYS,
            )
            if len(ridge_results) != len(targets):
                raise AssertionError("Cobertura de Ridge no coincide con los objetivos.")
            for target, base, ridge in zip(targets, baseline_results, ridge_results):
                if base["prediction"] is None:
                    raise AssertionError("Benchmark sin soporte en objetivo común.")
                predictions_by_alpha[alpha].append({
                    "alpha": alpha,
                    "issue_date_local": issue_date.isoformat(),
                    "issue_time_local": "18:00 America/Santiago",
                    "cutoff_date_exclusive": cutoff.isoformat(),
                    "max_history_observation_date": max(r["date"] for r in history).isoformat(),
                    "history_rows": len(history),
                    "target_date": target_date.isoformat(),
                    "target_weekday_monday0": target_date.weekday(),
                    "target_period_index": target["hour"],
                    "prediction": ridge["prediction"],
                    "prediction_source": ridge["prediction_source"],
                    "fallback_level": ridge["fallback_level"],
                    "n_support": ridge["n_support"],
                    "benchmark_prediction": str(base["prediction"]),
                    "benchmark_fallback_level": base["fallback_level"],
                    "observed_ex_post": str(target["value"]),
                })
        origins.append({
            "target_date": target_date.isoformat(),
            "issue_date": issue_date.isoformat(),
            "cutoff_exclusive": cutoff.isoformat(),
            "max_history_date": max(r["date"] for r in history).isoformat(),
            "history_rows": len(history),
            "target_periods": len(targets),
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries = {}
    all_records = []
    for alpha, result_rows in predictions_by_alpha.items():
        model_metrics = metric_summary(result_rows, "prediction")
        benchmark_metrics = metric_summary(result_rows, "benchmark_prediction")
        fallback_count = sum(r["prediction_source"] == "benchmark_fallback" for r in result_rows)
        summaries[str(alpha)] = {
            "ridge": model_metrics,
            "benchmark_same_targets": benchmark_metrics,
            "mae_delta_vs_benchmark": model_metrics["mae"] - benchmark_metrics["mae"],
            "benchmark_fallback_predictions": fallback_count,
        }
        all_records.extend(result_rows)

    # Lower MAE wins; exact ties prefer the stronger regularization.
    selected_alpha = min(ALPHAS, key=lambda a: (summaries[str(a)]["ridge"]["mae"], -a))
    output_csv = args.output_dir / "predicciones-ridge-estacional-2024.csv"
    fields = list(all_records[0])
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_records)

    model_source = REPO_ROOT / "src/models/ridge_estacional.py"
    evaluation_source = Path(__file__).resolve()
    summary = {
        "experiment": "seasonal Ridge development validation; no 2025 data read",
        "target_window": {"start": START.isoformat(), "end": END.isoformat()},
        "issue_time_local": "18:00 America/Santiago on target_date - 1 calendar day",
        "cutoff": "observation_date < issue_date - 60 calendar days; strict date comparison",
        "model_structure": "eligible weekday_x_period mean as fixed base plus Ridge seasonal correction fitted to base residuals",
        "features": ["annual Fourier sine/cosine, first harmonic"],
        "excluded_inputs": ["recent demand lags", "weather", "future observations"],
        "period_25_policy": "if weekday x period support < 5, use frozen benchmark fallback from same eligible history",
        "alpha_grid": list(ALPHAS),
        "alpha_selection": "minimum development MAE; exact ties choose larger alpha",
        "selected_alpha": selected_alpha,
        "selection_scores_development_only": summaries,
        "coverage": {
            "target_dates": len(target_dates),
            "periods_per_alpha": len(target_dates) and len(predictions_by_alpha[ALPHAS[0]]) or 0,
            "missing_predictions_per_alpha": 0,
            "origins": len(origins),
        },
        "origin_audit": origins,
        "outputs": {"predictions_csv": output_csv.name},
        "sha256": {
            "input_2024_csv": sha256(input_path),
            "protocol_v1_2": sha256(PROTOCOL),
            "model_implementation": sha256(model_source),
            "evaluation_script": sha256(evaluation_source),
        },
        "interpretation": [
            "All scores are development and model-selection results, not independent performance estimates.",
            "2025 data and predictions were not read or scored.",
            "The benchmark in this report is recomputed on exactly the same target rows for each alpha.",
            "A lower MAE is a relative predictive improvement only; operational acceptability is unestablished.",
        ],
    }
    summary_path = args.output_dir / "resumen-validacion-ridge-2024.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target_dates": len(target_dates),
        "periods_per_alpha": len(predictions_by_alpha[ALPHAS[0]]),
        "selected_alpha": selected_alpha,
        "scores": summaries,
        "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
