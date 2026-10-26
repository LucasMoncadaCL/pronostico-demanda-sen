"""Chronological development validation for the weekly-profile benchmark on 2024.

No 2025 data is read. Validation targets run 2024-04-06 through 2024-10-31.
At every issue, historical rows must satisfy:
    observation_date < (issue_date - 60 calendar days)
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from src.baselines.weekday_period_mean import predict_one
from src.evaluation.benchmark_policy import cutoff_date, eligible_history

DEFAULT_INPUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
DEFAULT_OUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/benchmark-validacion-2024"
VALIDATION_START = date(2024, 4, 6)
VALIDATION_END = date(2024, 10, 31)
LAG_DAYS = 60


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    rows = load_rows(args.input.resolve())
    by_date: dict[date, list[dict]] = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)

    target_dates = [d for d in sorted(by_date) if VALIDATION_START <= d <= VALIDATION_END]
    expected_dates = (VALIDATION_END - VALIDATION_START).days + 1
    if len(target_dates) != expected_dates:
        raise ValueError(f"Ventana incompleta: {len(target_dates)} fechas de {expected_dates}.")

    predictions = []
    metric_errors: list[Decimal] = []
    squared_errors: list[float] = []
    signed_errors: list[Decimal] = []
    fallback_counts = Counter()
    support_counts = []
    origin_audit = []

    for target_date in target_dates:
        issue_date = target_date - timedelta(days=1)
        cutoff_exclusive = cutoff_date(issue_date, LAG_DAYS)
        history = eligible_history(rows, issue_date, LAG_DAYS)
        if any(r["date"] >= cutoff_exclusive for r in history):
            raise AssertionError("Fuga: se encontró historia en/tras el corte exclusivo.")
        if any(r["date"] >= issue_date for r in history):
            raise AssertionError("Fuga: se encontró historia en/tras la fecha de emisión.")
        if not history:
            raise ValueError(f"No hay historia elegible para la emisión {issue_date}.")
        max_history_date = max(r["date"] for r in history)
        if not max_history_date < cutoff_exclusive:
            raise AssertionError("La fecha máxima de historia no precede el corte.")

        date_rows = by_date[target_date]
        for target in date_rows:
            result = predict_one(
                weekday=target_date.weekday(), period_index=target["hour"], history=history
            )
            if result["prediction"] is None:
                raise ValueError(
                    f"Benchmark sin soporte para {target_date}, índice {target['hour']}."
                )
            estimate = result["prediction"]
            error = estimate - target["value"]
            absolute_error = abs(error)
            metric_errors.append(absolute_error)
            squared_errors.append(float(error * error))
            signed_errors.append(error)
            fallback_counts[result["fallback_level"]] += 1
            support_counts.append(result["n_support"])
            predictions.append({
                "issue_date_local": issue_date.isoformat(),
                "issue_time_local": "18:00 America/Santiago",
                "cutoff_date_exclusive": cutoff_exclusive.isoformat(),
                "max_history_observation_date": max_history_date.isoformat(),
                "history_rows": len(history),
                "target_date": target_date.isoformat(),
                "target_weekday_monday0": target_date.weekday(),
                "target_period_index": target["hour"],
                "benchmark": "weekday_x_period_mean_with_fallback",
                "fallback_level": result["fallback_level"],
                "n_support": result["n_support"],
                "prediction": str(estimate),
                "observed_ex_post": str(target["value"]),
                "error_prediction_minus_observed": str(error),
                "absolute_error": str(absolute_error),
            })
        origin_audit.append({
            "target_date": target_date.isoformat(),
            "issue_date_local": issue_date.isoformat(),
            "cutoff_date_exclusive": cutoff_exclusive.isoformat(),
            "max_history_observation_date": max_history_date.isoformat(),
            "history_rows": len(history),
            "target_periods": len(date_rows),
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "predicciones-benchmark-2024.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)

    n = len(metric_errors)
    mae = sum(metric_errors, Decimal("0")) / Decimal(n)
    bias = sum(signed_errors, Decimal("0")) / Decimal(n)
    rmse = math.sqrt(sum(squared_errors) / n)
    summary = {
        "data_year": 2024,
        "validation_target_window": {"start": VALIDATION_START.isoformat(), "end": VALIDATION_END.isoformat()},
        "issue_time_local": "18:00 America/Santiago on target_date - 1 calendar day",
        "cutoff": "observation_date < issue_date - 60 calendar days; date-to-date comparison, strict",
        "development_only": True,
        "holdout_2025_read_or_scored": False,
        "benchmark": "mean by weekday x source period index; fallback hierarchy; minimum group support n>=5",
        "warmup_evidence": {
            "first_target_date": VALIDATION_START.isoformat(),
            "eligible_history_first_origin": origin_audit[0]["history_rows"],
            "max_history_date_first_origin": origin_audit[0]["max_history_observation_date"],
            "cutoff_first_origin_exclusive": origin_audit[0]["cutoff_date_exclusive"],
        },
        "prediction_coverage": {
            "target_dates": len(target_dates),
            "target_periods": n,
            "predictions": len(predictions),
            "missing_predictions": 0,
            "fallback_level_counts": dict(fallback_counts),
            "support_min": min(support_counts),
            "support_max": max(support_counts),
        },
        "metrics_development_only": {
            "mae": str(mae),
            "rmse": rmse,
            "bias_prediction_minus_observed": str(bias),
        },
        "origin_audit": origin_audit,
        "outputs": {"predictions_csv": csv_path.name},
        "interpretation": [
            "These are development metrics on 2024, not an independent evaluation.",
            "No target dates after 2024-10-31 are used for selection under the first 2025 issue cutoff.",
            "Every training record precedes the strict date cutoff for its own issue.",
            "The source-period index is preserved; no civil-hour or UTC mapping is inferred.",
        ],
    }
    summary_path = args.output_dir / "resumen-validacion-benchmark-2024.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "validation_dates": len(target_dates), "target_periods": n,
        "missing_predictions": 0, "fallbacks": dict(fallback_counts),
        "first_issue_cutoff": origin_audit[0]["cutoff_date_exclusive"],
        "first_issue_latest_history": origin_audit[0]["max_history_observation_date"],
        "last_validation_target": VALIDATION_END.isoformat(),
        "MAE_development_only": str(mae), "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
