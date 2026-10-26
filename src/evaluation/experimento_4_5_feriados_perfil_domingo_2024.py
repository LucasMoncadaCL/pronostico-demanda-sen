from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.baselines.weekday_period_mean import predict_one
from src.evaluation.benchmark_policy import cutoff_date, eligible_history

INPUT_SERIES = ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
INPUT_BENCHMARK = ROOT / "data/audits/2024-demanda-sistemica/benchmark-validacion-2024/predicciones-benchmark-2024.csv"
FROZEN_SPEC = ROOT / "docs/protocol/experimento-4.5-feriados-habiles-perfil-domingo.json"
MODEL_SOURCE = ROOT / "src/baselines/weekday_period_mean.py"
DEFAULT_OUTPUT = ROOT / "data/audits/2024-demanda-sistemica/experimento-4.5-perfil-domingo-feriados-habiles"
WINDOW_START = date(2024, 4, 6)
WINDOW_END = date(2024, 10, 31)
LAG_DAYS = 60


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_series(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
            day = date.fromisoformat(raw["fecha"])
            if day.year != 2024:
                raise ValueError("El experimento solo admite la serie 2024.")
            rows.append({"date": day, "hour": int(raw["hora"]), "value": Decimal(raw["demanda"])})
    keys = [(row["date"], row["hour"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("La serie contiene claves (fecha, hora) duplicadas.")
    return sorted(rows, key=lambda row: (row["date"], row["hour"]))


def load_benchmark(path: Path) -> dict[tuple[date, int], dict]:
    result = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
            target_date = date.fromisoformat(raw["target_date"])
            if not WINDOW_START <= target_date <= WINDOW_END:
                raise ValueError(f"Predicción benchmark fuera de ventana: {target_date}")
            key = (target_date, int(raw["target_period_index"]))
            if key in result:
                raise ValueError(f"Objetivo benchmark duplicado: {key}")
            result[key] = raw
    if len(result) != 5016:
        raise ValueError(f"Se esperaban 5.016 predicciones benchmark, se encontraron {len(result)}")
    return result


def metrics(rows: list[dict], prediction_key: str) -> dict:
    if not rows:
        return {"n": 0, "mae": None, "rmse": None, "bias_prediction_minus_observed": None}
    errors = [float(row[prediction_key] - row["observed"]) for row in rows]
    return {
        "n": len(errors),
        "mae": sum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias_prediction_minus_observed": sum(errors) / len(errors),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"No hay registros para escribir: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    spec = json.loads(FROZEN_SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment") != "4.5" or spec.get("status") != "frozen_before_execution":
        raise ValueError("La especificación 4.5 debe estar congelada antes de ejecutar.")
    if spec.get("protocol_v1_2_modified") is not False:
        raise ValueError("Este experimento no puede modificar el protocolo v1.2.")
    frozen_dates = {
        item["date"]: item["name"]
        for item in spec["calendar_definition"]["included_dates"]
    }
    dates = {date.fromisoformat(value): name for value, name in frozen_dates.items()}
    if len(dates) != 9:
        raise ValueError("El manifiesto debe incluir exactamente los nueve feriados definidos.")
    for day in dates:
        if not WINDOW_START <= day <= WINDOW_END or day.weekday() >= 5:
            raise ValueError(f"Fecha de feriado fuera de alcance o no hábil: {day}")

    series = load_series(INPUT_SERIES)
    benchmark = load_benchmark(INPUT_BENCHMARK)
    series_by_date: dict[date, list[dict]] = defaultdict(list)
    for row in series:
        series_by_date[row["date"]].append(row)

    predictions = []
    origin_audit = []
    for target_date in sorted(series_by_date):
        if not WINDOW_START <= target_date <= WINDOW_END:
            continue
        issue_date = target_date - timedelta(days=1)
        cutoff = cutoff_date(issue_date, LAG_DAYS)
        history = eligible_history(series, issue_date, LAG_DAYS)
        if not history or any(row["date"] >= cutoff for row in history):
            raise AssertionError(f"Historia vacía o posterior al corte para {issue_date}")
        max_history_date = max(row["date"] for row in history)
        if not max_history_date < cutoff:
            raise AssertionError(f"La historia no precede el corte exclusivo para {issue_date}")

        baseline_date_rows = []
        for target in series_by_date[target_date]:
            key = (target_date, target["hour"])
            raw_benchmark = benchmark.get(key)
            if raw_benchmark is None:
                raise AssertionError(f"Falta benchmark para {key}")
            baseline = Decimal(raw_benchmark["prediction"])
            observed = target["value"]
            if Decimal(raw_benchmark["observed_ex_post"]) != observed:
                raise AssertionError(f"Observado distinto entre fuentes para {key}")

            # Rebuild both published benchmark and Sunday-profile candidate using
            # exactly the same issue-specific eligible history.
            baseline_rebuilt = predict_one(
                weekday=target_date.weekday(), period_index=target["hour"], history=history
            )
            if baseline_rebuilt["prediction"] is None or baseline_rebuilt["prediction"] != baseline:
                raise AssertionError(f"No se reproduce benchmark congelado para {key}")

            is_weekday_holiday = target_date in dates
            if is_weekday_holiday:
                sunday_profile = predict_one(weekday=6, period_index=target["hour"], history=history)
                candidate = sunday_profile["prediction"]
                if candidate is None:
                    raise AssertionError(f"Candidato sin respaldo; no se fabricará predicción: {key}")
                candidate_fallback = sunday_profile["fallback_level"]
                candidate_support = sunday_profile["n_support"]
            else:
                candidate = baseline
                candidate_fallback = raw_benchmark["fallback_level"]
                candidate_support = int(raw_benchmark["n_support"])
                if candidate != baseline:
                    raise AssertionError(f"La predicción no feriado fue alterada: {key}")

            prediction = {
                "issue_date_local": issue_date.isoformat(),
                "issue_time_local": "18:00 America/Santiago",
                "cutoff_exclusive": cutoff.isoformat(),
                "max_history_date": max_history_date.isoformat(),
                "history_rows": len(history),
                "target_date": target_date.isoformat(),
                "target_weekday_monday0": target_date.weekday(),
                "target_period_index": target["hour"],
                "is_weekday_national_holiday": is_weekday_holiday,
                "holiday_name": dates.get(target_date, ""),
                "observed_ex_post": str(observed),
                "benchmark_prediction": str(baseline),
                "benchmark_fallback_level": raw_benchmark["fallback_level"],
                "benchmark_n_support": int(raw_benchmark["n_support"]),
                "candidate_prediction": str(candidate),
                "candidate_profile": "sunday_x_period" if is_weekday_holiday else "unchanged_benchmark",
                "candidate_fallback_level": candidate_fallback,
                "candidate_n_support": candidate_support,
                "benchmark_error": str(baseline - observed),
                "benchmark_absolute_error": str(abs(baseline - observed)),
                "candidate_error": str(candidate - observed),
                "candidate_absolute_error": str(abs(candidate - observed)),
                "candidate_delta_absolute_error": str(abs(candidate - observed) - abs(baseline - observed)),
            }
            predictions.append(prediction)
            baseline_date_rows.append(prediction)
        origin_audit.append({
            "target_date": target_date.isoformat(),
            "issue_date": issue_date.isoformat(),
            "cutoff_exclusive": cutoff.isoformat(),
            "max_history_date": max_history_date.isoformat(),
            "history_rows": len(history),
            "target_periods": len(baseline_date_rows),
        })

    if len(predictions) != 5016:
        raise AssertionError(f"Cobertura candidate incorrecta: {len(predictions)}")
    targets = [(r["target_date"], r["target_period_index"]) for r in predictions]
    if len(set(targets)) != len(targets):
        raise AssertionError("Se generaron predicciones objetivo duplicadas.")
    if any(Decimal(r["candidate_prediction"]) < 0 for r in predictions):
        raise AssertionError("Se encontraron predicciones candidate negativas.")
    nonholiday_rows = [r for r in predictions if not r["is_weekday_national_holiday"]]
    if any(Decimal(r["candidate_prediction"]) != Decimal(r["benchmark_prediction"]) for r in nonholiday_rows):
        raise AssertionError("El candidato cambió una predicción fuera de feriados hábiles.")
    holiday_rows = [r for r in predictions if r["is_weekday_national_holiday"]]
    if len(holiday_rows) != 216:
        raise AssertionError(f"Se esperaban 216 períodos feriados, se encontraron {len(holiday_rows)}")

    metric_rows = [
        {"observed": Decimal(r["observed_ex_post"]), "benchmark": Decimal(r["benchmark_prediction"]), "candidate": Decimal(r["candidate_prediction"])}
        for r in predictions
    ]
    holiday_metric_rows = [row for row, p in zip(metric_rows, predictions) if p["is_weekday_national_holiday"]]
    nonholiday_metric_rows = [row for row, p in zip(metric_rows, predictions) if not p["is_weekday_national_holiday"]]
    all_mae = lambda rows, key: sum(abs(float(r[key] - r["observed"])) for r in rows) / len(rows)
    all_bias = lambda rows, key: sum(float(r[key] - r["observed"]) for r in rows) / len(rows)
    all_rmse = lambda rows, key: math.sqrt(sum(float(r[key] - r["observed"]) ** 2 for r in rows) / len(rows))

    by_holiday_date = defaultdict(list)
    by_all_date = defaultdict(list)
    for prediction in predictions:
        by_all_date[prediction["target_date"]].append(prediction)
        if prediction["is_weekday_national_holiday"]:
            by_holiday_date[prediction["target_date"]].append(prediction)
    date_metrics = []
    for target_date, day_rows in sorted(by_holiday_date.items()):
        date_metrics.append({
            "target_date": target_date,
            "holiday_name": dates[date.fromisoformat(target_date)],
            "periods": len(day_rows),
            "benchmark_mae": sum(abs(float(r["benchmark_error"])) for r in day_rows) / len(day_rows),
            "candidate_mae": sum(abs(float(r["candidate_error"])) for r in day_rows) / len(day_rows),
            "benchmark_bias": sum(float(r["benchmark_error"]) for r in day_rows) / len(day_rows),
            "candidate_bias": sum(float(r["candidate_error"]) for r in day_rows) / len(day_rows),
            "candidate_abs_error_change": sum(float(r["candidate_delta_absolute_error"]) for r in day_rows),
            "candidate_fallback_counts": dict(__import__("collections").Counter(r["candidate_fallback_level"] for r in day_rows)),
        })

    baseline_total_abs = sum(abs(float(r["benchmark_error"])) for r in predictions)
    baseline_holiday_abs = sum(abs(float(r["benchmark_error"])) for r in holiday_rows)
    candidate_total_abs = sum(abs(float(r["candidate_error"])) for r in predictions)
    candidate_holiday_abs = sum(abs(float(r["candidate_error"])) for r in holiday_rows)
    summary = {
        "experiment": "4.5",
        "scope": "Frozen development comparison on 2024; no 2025 data read or scored.",
        "frozen_spec_sha256": sha256(FROZEN_SPEC),
        "input_series_sha256": sha256(INPUT_SERIES),
        "benchmark_predictions_sha256": sha256(INPUT_BENCHMARK),
        "baseline_implementation_sha256": sha256(MODEL_SOURCE),
        "experiment_script_sha256": sha256(Path(__file__).resolve()),
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "rule": "On frozen weekday national-holiday dates, replace benchmark profile with eligible-history Sunday x same source period index using the existing n>=5 fallback hierarchy; preserve every other benchmark prediction.",
        "selection_metric": "global MAE over the 5,016 common hourly targets",
        "coverage": {
            "dates": len(origin_audit),
            "targets": len(predictions),
            "duplicate_targets": 0,
            "missing_targets": 0,
            "weekday_holiday_dates": len(by_holiday_date),
            "weekday_holiday_periods": len(holiday_rows),
            "nonholiday_predictions_unchanged": len(nonholiday_rows),
            "candidate_negative_predictions": 0,
            "targets_without_candidate_support": 0,
        },
        "overall_metrics": {
            "benchmark": {"n": len(predictions), "mae": all_mae(metric_rows, "benchmark"), "rmse": all_rmse(metric_rows, "benchmark"), "bias_prediction_minus_observed": all_bias(metric_rows, "benchmark")},
            "candidate": {"n": len(predictions), "mae": all_mae(metric_rows, "candidate"), "rmse": all_rmse(metric_rows, "candidate"), "bias_prediction_minus_observed": all_bias(metric_rows, "candidate")},
            "mae_delta_candidate_minus_benchmark": all_mae(metric_rows, "candidate") - all_mae(metric_rows, "benchmark"),
            "relative_mae_change_percent": 100 * (all_mae(metric_rows, "candidate") / all_mae(metric_rows, "benchmark") - 1),
        },
        "weekday_holiday_secondary_metrics": {
            "benchmark": {"n": len(holiday_rows), "mae": all_mae(holiday_metric_rows, "benchmark"), "rmse": all_rmse(holiday_metric_rows, "benchmark"), "bias_prediction_minus_observed": all_bias(holiday_metric_rows, "benchmark")},
            "candidate": {"n": len(holiday_rows), "mae": all_mae(holiday_metric_rows, "candidate"), "rmse": all_rmse(holiday_metric_rows, "candidate"), "bias_prediction_minus_observed": all_bias(holiday_metric_rows, "candidate")},
            "mae_delta_candidate_minus_benchmark": all_mae(holiday_metric_rows, "candidate") - all_mae(holiday_metric_rows, "benchmark"),
            "baseline_holiday_share_of_periods_percent": 100 * len(holiday_rows) / len(predictions),
            "baseline_holiday_share_of_total_absolute_error_percent": 100 * baseline_holiday_abs / baseline_total_abs,
            "candidate_holiday_share_of_total_absolute_error_percent": 100 * candidate_holiday_abs / candidate_total_abs,
        },
        "nonholiday_secondary_metrics": {
            "n": len(nonholiday_rows),
            "benchmark_mae": all_mae(nonholiday_metric_rows, "benchmark"),
            "candidate_mae": all_mae(nonholiday_metric_rows, "candidate"),
        },
        "per_holiday_date": date_metrics,
        "origin_audit": origin_audit,
        "interpretation_limits": [
            "The rule was motivated after viewing 2024 development errors; this is not independent confirmation.",
            "The nine holiday days are few, and three are consecutive Fiestas Patrias dates.",
            "The 60-day information cutoff is an experimental rule, not proof that definitive historical observations were actually available by then.",
            "No causal or operational claim follows from this development comparison.",
            "The holiday-only MAE is diagnostic and was not the selection metric.",
            "2025 was not read or scored.",
        ],
        "outputs": {
            "predictions": "predicciones-experimento-4-5-2024.csv",
            "holiday_metrics": "metricas-por-feriado-4-5-2024.csv",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "predicciones-experimento-4-5-2024.csv", predictions)
    write_csv(output_dir / "metricas-por-feriado-4-5-2024.csv", date_metrics)
    (output_dir / "resumen-experimento-4-5-2024.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "overall_mae_benchmark": summary["overall_metrics"]["benchmark"]["mae"],
        "overall_mae_candidate": summary["overall_metrics"]["candidate"]["mae"],
        "holiday_mae_benchmark": summary["weekday_holiday_secondary_metrics"]["benchmark"]["mae"],
        "holiday_mae_candidate": summary["weekday_holiday_secondary_metrics"]["candidate"]["mae"],
        "targets": len(predictions),
        "output": str(output_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
