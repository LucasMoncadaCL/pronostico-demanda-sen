"""One-shot scorer for the frozen 2025 holiday-profile extension.

By design, this script refuses to score unless --execute-frozen-evaluation is
provided. Package verification is performed separately and does not compute
candidate 2025 metrics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.benchmark_policy import frozen_2024_snapshot
from src.models.holiday_profile_extension import predict_with_holiday_profile
from src.baselines.weekday_period_mean import predict_one

TRAIN_2024 = ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
BENCHMARK_2025 = ROOT / "data/audits/2025-demanda-sistemica/evaluacion-benchmark-congelada/predicciones-benchmark-2025-regimen-principal.csv"
BENCHMARK_SUMMARY = ROOT / "data/audits/2025-demanda-sistemica/evaluacion-benchmark-congelada/evaluacion-benchmark-2025.json"
CALENDAR_PATH = ROOT / "docs/protocol/calendario-feriados-nacionales-2025.json"
SPEC_PATH = ROOT / "docs/protocol/congelamiento-extension-feriados-2025.md"
MANIFEST_PATH = ROOT / "docs/protocol/manifest-congelamiento-extension-feriados-2025.json"
OUTPUT = ROOT / "data/audits/2025-demanda-sistemica/evaluacion-extension-feriados-congelada"
FIRST_ISSUE = date(2024, 12, 31)
LAG_DAYS = 60
EXPECTED_BENCHMARK_MAE = Decimal("488.9621")
EVENT_DATES = {date(2025, 2, 25), date(2025, 2, 26)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("status") != "frozen_before_candidate_2025_scoring":
        raise ValueError("No existe un manifiesto congelado para esta evaluación.")
    for relative, expected in manifest["sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"El artefacto congelado cambió o falta: {relative}")
    return manifest


def read_history(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
            day = date.fromisoformat(raw["fecha"])
            if day.year != 2024:
                raise ValueError("La historia congelada solo admite el año 2024.")
            records.append({"date": day, "hour": int(raw["hora"]), "value": Decimal(raw["demanda"])})
    keys = [(r["date"], r["hour"]) for r in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Historia 2024 con claves duplicadas.")
    return sorted(records, key=lambda r: (r["date"], r["hour"]))


def read_frozen_benchmark(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
            target = date.fromisoformat(raw["target_date"])
            if target.year != 2025:
                raise ValueError("El benchmark congelado contiene un objetivo fuera de 2025.")
            rows.append({
                "target_date": target,
                "period_index": int(raw["target_period_index"]),
                "benchmark_prediction": Decimal(raw["prediction"]),
                "observed": Decimal(raw["observed"]),
                "benchmark_fallback_level": raw["fallback_level"],
                "benchmark_n_support": int(raw["n_support"]),
                "event_window": target in EVENT_DATES,
            })
    keys = [(r["target_date"], r["period_index"]) for r in rows]
    if len(rows) != 8760 or len(set(keys)) != 8760:
        raise ValueError(f"Cobertura benchmark incorrecta: filas={len(rows)}, claves={len(set(keys))}")
    return sorted(rows, key=lambda r: (r["target_date"], r["period_index"]))


def load_candidate_calendar(path: Path) -> tuple[dict[date, str], dict]:
    calendar = json.loads(path.read_text(encoding="utf-8"))
    dates = {date.fromisoformat(item["date"]): item["name"]
             for item in calendar["national_holidays"] if item["class"] == "national_holiday"}
    mechanically_selected = {day: name for day, name in dates.items() if day.weekday() < 5}
    declared = {date.fromisoformat(value) for value in calendar["included_candidate_dates"]}
    if set(mechanically_selected) != declared or len(declared) != 12:
        raise ValueError("El calendario candidato no coincide con la regla mecánica congelada.")
    if any(day.weekday() >= 5 for day in declared):
        raise ValueError("El calendario candidato incluye un feriado que cae en fin de semana.")
    return mechanically_selected, calendar


def score(rows: list[dict], prediction_key: str) -> dict:
    if not rows:
        return {"n": 0, "mae": None, "rmse": None, "bias_prediction_minus_observed": None}
    errors = [row[prediction_key] - row["observed"] for row in rows]
    n = len(errors)
    return {
        "n": n,
        "mae": str(sum((abs(e) for e in errors), Decimal("0")) / Decimal(n)),
        "rmse": math.sqrt(sum(float(e * e) for e in errors) / n),
        "bias_prediction_minus_observed": str(sum(errors, Decimal("0")) / Decimal(n)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-frozen-evaluation", action="store_true",
        help="Run the single frozen candidate scoring pass on 2025; requires user approval of the package.",
    )
    args = parser.parse_args()
    if not args.execute_frozen_evaluation:
        print("Paquete de evaluación congelada. No se leyeron datos 2025 ni se calcularon métricas del candidato.")
        return 0

    manifest = verify_manifest()
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError("La evaluación congelada ya produjo artefactos; no se ejecutará por segunda vez.")
    snapshot = frozen_2024_snapshot(read_history(TRAIN_2024), FIRST_ISSUE, LAG_DAYS)
    if len(snapshot) != 7320 or min(r["date"] for r in snapshot) != date(2024, 1, 1) or max(r["date"] for r in snapshot) != date(2024, 10, 31):
        raise AssertionError("La historia fija no coincide con 7.320 registros 2024 hasta 31-oct.")
    if any(r["date"] >= date(2024, 11, 1) for r in snapshot):
        raise AssertionError("La historia fija viola el corte exclusivo de 2024-11-01.")
    candidate_dates, calendar = load_candidate_calendar(CALENDAR_PATH)
    baseline_rows = read_frozen_benchmark(BENCHMARK_2025)
    candidate_date_set = set(candidate_dates)

    # Verify the old frozen benchmark from its authorized fixed history before
    # altering any targets. The expected 488.9621 is the published baseline.
    candidate_rows = []
    for source_row in baseline_rows:
        target_date = source_row["target_date"]
        issue_date = target_date - timedelta(days=1)
        cutoff = issue_date - timedelta(days=LAG_DAYS)
        if max(r["date"] for r in snapshot) >= cutoff:
            raise AssertionError(f"Historia fija no elegible para emisión {issue_date}.")
        baseline_rebuilt = predict_one(
            weekday=target_date.weekday(), period_index=source_row["period_index"], history=snapshot
        )
        if baseline_rebuilt["prediction"] != source_row["benchmark_prediction"]:
            raise AssertionError(f"No se reproduce benchmark congelado para {target_date}, período {source_row['period_index']}.")
        holiday = target_date in candidate_dates
        result = predict_with_holiday_profile(
            target_date=target_date,
            period_index=source_row["period_index"],
            benchmark_prediction=source_row["benchmark_prediction"],
            fixed_history=snapshot,
            candidate_holiday_dates=candidate_date_set,
        )
        record = {
            **source_row,
            "issue_date_local": issue_date.isoformat(),
            "cutoff_exclusive": cutoff.isoformat(),
            "is_candidate_holiday": holiday,
            "holiday_name": candidate_dates.get(target_date, ""),
            "candidate_prediction": result["prediction"],
            "candidate_profile": result["profile"],
            "candidate_fallback_level": result["fallback_level"] or source_row["benchmark_fallback_level"],
            "candidate_n_support": result["n_support"] if result["n_support"] is not None else source_row["benchmark_n_support"],
            "candidate_error": result["prediction"] - source_row["observed"],
            "benchmark_error": source_row["benchmark_prediction"] - source_row["observed"],
        }
        candidate_rows.append(record)

    if len(candidate_rows) != 8760 or len({(r["target_date"], r["period_index"]) for r in candidate_rows}) != 8760:
        raise AssertionError("El candidato no cubre exactamente los 8.760 objetivos comunes.")
    holiday_rows = [r for r in candidate_rows if r["is_candidate_holiday"]]
    nonholiday_rows = [r for r in candidate_rows if not r["is_candidate_holiday"]]
    if len(holiday_rows) != 288 or len(nonholiday_rows) != 8472:
        raise AssertionError("La cobertura por feriado no coincide con 288 / 8.472 períodos.")
    if any(r["candidate_prediction"] != r["benchmark_prediction"] for r in nonholiday_rows):
        raise AssertionError("Se alteró una predicción que no pertenece a feriado hábil.")
    if any(r["event_window"] and r["candidate_prediction"] != r["benchmark_prediction"] for r in candidate_rows):
        raise AssertionError("El candidato alteró una fecha del apagón.")
    if any(r["candidate_prediction"] < 0 for r in candidate_rows):
        raise AssertionError("Se encontró una predicción candidata negativa.")
    if any(r["candidate_n_support"] < 5 for r in holiday_rows):
        raise AssertionError("Una predicción de feriado no cumple soporte mínimo n>=5.")

    expected_dates = {date.fromisoformat(x) for x in calendar["included_candidate_dates"]}
    realized_dates = {r["target_date"] for r in holiday_rows}
    if realized_dates != expected_dates:
        raise AssertionError("Las fechas modificadas no coinciden con el calendario congelado.")

    known_baseline_mae = Decimal(EXPECTED_BENCHMARK_MAE)
    benchmark_mae = Decimal(score(candidate_rows, "benchmark_prediction")["mae"])
    if abs(benchmark_mae - known_baseline_mae) > Decimal("0.0001"):
        raise AssertionError(f"El benchmark no reproduce el MAE publicado 488.9621: {benchmark_mae}")
    event_included = [r for r in candidate_rows if not r["event_window"]]
    by_holiday = []
    for day in sorted(realized_dates):
        day_rows = [r for r in holiday_rows if r["target_date"] == day]
        by_holiday.append({
            "target_date": day.isoformat(),
            "holiday_name": candidate_dates[day],
            "benchmark": score(day_rows, "benchmark_prediction"),
            "candidate": score(day_rows, "candidate_prediction"),
        })
    metrics = {
        "all_2025_targets_including_blackout": {
            "benchmark": score(candidate_rows, "benchmark_prediction"),
            "candidate": score(candidate_rows, "candidate_prediction"),
        },
        "excluding_full_blackout_dates_2025_02_25_and_2025_02_26": {
            "benchmark": score(event_included, "benchmark_prediction"),
            "candidate": score(event_included, "candidate_prediction"),
        },
        "candidate_holiday_dates_only": {
            "benchmark": score(holiday_rows, "benchmark_prediction"),
            "candidate": score(holiday_rows, "candidate_prediction"),
        },
        "remaining_targets": {
            "benchmark": score(nonholiday_rows, "benchmark_prediction"),
            "candidate": score(nonholiday_rows, "candidate_prediction"),
        },
        "blackout_date_diagnostics": {
            day.isoformat(): {
                "benchmark": score([r for r in candidate_rows if r["target_date"] == day], "benchmark_prediction"),
                "candidate": score([r for r in candidate_rows if r["target_date"] == day], "candidate_prediction"),
            }
            for day in sorted(EVENT_DATES)
        },
    }
    output = {
        "protocol": "v1.2 frozen; holiday candidate freeze package verified before scoring",
        "evaluation_scope": "One candidate, one execution; no tuning, alternative profiles, or post-hoc exceptions.",
        "manifest_sha256": sha256(MANIFEST_PATH),
        "candidate_calendar_sha256": sha256(CALENDAR_PATH),
        "history_2024_rows": len(snapshot),
        "coverage": {"target_rows": len(candidate_rows), "holiday_rows": len(holiday_rows), "unchanged_rows": len(nonholiday_rows)},
        "metrics": metrics,
        "metrics_by_holiday_date": by_holiday,
        "invariance": {
            "nonholiday_predictions_unchanged": True,
            "blackout_predictions_unchanged": True,
            "same_8760_target_keys": True,
            "negative_predictions": 0,
            "unsupported_predictions": 0,
        },
        "limitations": [
            "The 2025 benchmark result was already known; the holdout comparison is not fully blind.",
            "The candidate hypothesis was developed from 2024 errors; 2024 development results are not independent confirmation.",
            "The 60-day cutoff does not reconstruct historical data publication versions.",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=False)
    output_csv = OUTPUT / "predicciones-extension-feriados-2025.csv"
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = list(candidate_rows[0])
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{k: str(v) if isinstance(v, Decimal) else (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()} for r in candidate_rows])
    (OUTPUT / "evaluacion-extension-feriados-2025.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"metrics": metrics, "output": str(OUTPUT)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
