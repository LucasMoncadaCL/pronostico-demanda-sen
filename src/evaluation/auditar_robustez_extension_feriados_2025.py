"""Auditoría descriptiva de la extensión congelada, basada solo en predicciones archivadas.

Este módulo no calcula predicciones ni cambia los artefactos congelados.
Ejecutar desde la raíz: py src/evaluation/auditar_robustez_extension_feriados_2025.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/audits/2025-demanda-sistemica/evaluacion-extension-feriados-congelada/predicciones-extension-feriados-2025.csv"
OUTPUT_DIR = ROOT / "data/audits/2025-demanda-sistemica/auditoria-robustez-extension"
FIESTAS_PATRIAS = {"2025-09-18", "2025-09-19"}
BOOTSTRAP_REPLICATES = 20_000
BOOTSTRAP_BLOCK_DAYS = 7
BOOTSTRAP_SEED = 20261026


def quantile(values: list[float], probability: float) -> float:
    """Percentil lineal tipo 7, usando posiciones inclusivas [0, n - 1]."""
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summary_metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if not rows:
        return {"n": 0}
    abs_b = [abs(r["benchmark_error"]) for r in rows]
    abs_c = [abs(r["candidate_error"]) for r in rows]
    signed_b = [r["benchmark_error"] for r in rows]
    signed_c = [r["candidate_error"] for r in rows]
    return {
        "n": len(rows),
        "benchmark_mae": mean(abs_b),
        "candidate_mae": mean(abs_c),
        "mae_improvement": mean(abs_b) - mean(abs_c),
        "mae_improvement_pct": (mean(abs_b) - mean(abs_c)) / mean(abs_b) * 100,
        "benchmark_rmse": math.sqrt(mean(x * x for x in signed_b)),
        "candidate_rmse": math.sqrt(mean(x * x for x in signed_c)),
        "benchmark_bias": mean(signed_b),
        "candidate_bias": mean(signed_c),
        "benchmark_abs_error_p50": quantile(abs_b, 0.50),
        "candidate_abs_error_p50": quantile(abs_c, 0.50),
        "benchmark_abs_error_p75": quantile(abs_b, 0.75),
        "candidate_abs_error_p75": quantile(abs_c, 0.75),
        "benchmark_abs_error_p90": quantile(abs_b, 0.90),
        "candidate_abs_error_p90": quantile(abs_c, 0.90),
        "benchmark_abs_error_p95": quantile(abs_b, 0.95),
        "candidate_abs_error_p95": quantile(abs_c, 0.95),
        "benchmark_abs_error_p99": quantile(abs_b, 0.99),
        "candidate_abs_error_p99": quantile(abs_c, 0.99),
        "benchmark_abs_error_max": max(abs_b),
        "candidate_abs_error_max": max(abs_c),
        "benchmark_abs_error_over_1000": sum(x > 1000 for x in abs_b),
        "candidate_abs_error_over_1000": sum(x > 1000 for x in abs_c),
        "benchmark_abs_error_over_1500": sum(x > 1500 for x in abs_b),
        "candidate_abs_error_over_1500": sum(x > 1500 for x in abs_c),
    }


def paired_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distribución de diferencias emparejadas; positiva favorece al candidato."""
    if not rows:
        return {"n": 0}
    daily_savings = [r["benchmark_mae"] - r["candidate_mae"] for r in rows]
    return {
        "n_dates": len(rows),
        "candidate_better_dates": sum(x > 1e-12 for x in daily_savings),
        "candidate_worse_dates": sum(x < -1e-12 for x in daily_savings),
        "tied_dates": sum(abs(x) <= 1e-12 for x in daily_savings),
        "mean_daily_mae_improvement": mean(daily_savings),
        "median_daily_mae_improvement": median(daily_savings),
        "p10_daily_mae_improvement": quantile(daily_savings, 0.10),
        "p90_daily_mae_improvement": quantile(daily_savings, 0.90),
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            observed = float(item["observed"])
            benchmark = float(item["benchmark_prediction"])
            candidate = float(item["candidate_prediction"])
            rows.append(
                {
                    "target_date": item["target_date"],
                    "period_index": int(item["period_index"]),
                    "observed": observed,
                    "benchmark_prediction": benchmark,
                    "candidate_prediction": candidate,
                    "benchmark_error": benchmark - observed,
                    "candidate_error": candidate - observed,
                    "is_holiday": item["is_candidate_holiday"].strip().lower() == "true",
                    "holiday_name": item["holiday_name"],
                    "event_window": item["event_window"].strip().lower() == "true",
                }
            )
    return rows


def by_date(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["target_date"]].append(row)
    result = []
    for day, group in sorted(grouped.items()):
        b = mean(abs(r["benchmark_error"]) for r in group)
        c = mean(abs(r["candidate_error"]) for r in group)
        holidays = {r["holiday_name"] for r in group if r["is_holiday"]}
        result.append(
            {
                "target_date": day,
                "day_of_week": date.fromisoformat(day).strftime("%A"),
                "n_periods": len(group),
                "holiday_name": "; ".join(sorted(holidays)),
                "benchmark_mae": b,
                "candidate_mae": c,
                "mae_improvement": b - c,
                "absolute_error_savings": sum(
                    abs(r["benchmark_error"]) - abs(r["candidate_error"]) for r in group
                ),
            }
        )
    return result


def leave_out(rows: list[dict[str, Any]], removed_dates: set[str]) -> dict[str, Any]:
    remaining = [row for row in rows if row["target_date"] not in removed_dates]
    return {"omitted_dates": sorted(removed_dates), **summary_metrics(remaining)}


def bootstrap_by_quarter(
    date_rows: list[dict[str, Any]],
    replicates: int = BOOTSTRAP_REPLICATES,
    block_days: int = BOOTSTRAP_BLOCK_DAYS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Circular moving-block bootstrap, resampling within quarter to retain season strata."""
    quarter_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in date_rows:
        quarter = (date.fromisoformat(row["target_date"]).month - 1) // 3 + 1
        quarter_groups[quarter].append(row)

    rng = random.Random(seed)
    gains = []
    for _ in range(replicates):
        savings = 0.0
        n_periods = 0
        for quarter in range(1, 5):
            days = quarter_groups[quarter]
            selected: list[dict[str, Any]] = []
            while len(selected) < len(days):
                start = rng.randrange(len(days))
                selected.extend(days[(start + offset) % len(days)] for offset in range(block_days))
            selected = selected[: len(days)]
            savings += sum(day["absolute_error_savings"] for day in selected)
            n_periods += sum(day["n_periods"] for day in selected)
        gains.append(savings / n_periods)
    return {
        "method": "circular moving-block bootstrap within calendar quarter",
        "block_days": block_days,
        "replicates": replicates,
        "seed": seed,
        "mae_improvement_p2_5": quantile(gains, 0.025),
        "mae_improvement_median": quantile(gains, 0.50),
        "mae_improvement_p97_5": quantile(gains, 0.975),
        "interpretation": (
            "Descriptive percentile interval of the block bootstrap, conditional on 2025; "
            "not a forecast interval, not a confidence guarantee across years, "
            "and not independent validation."
        ),
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    raw_hash_before = hashlib.sha256(INPUT.read_bytes()).hexdigest()
    rows = load_rows(INPUT)
    if len(rows) != 8760:
        raise ValueError(f"Se esperaban 8.760 filas archivadas; se encontraron {len(rows)}")
    if len({(r["target_date"], r["period_index"]) for r in rows}) != len(rows):
        raise ValueError("La clave (target_date, period_index) no es única")
    if sum(r["is_holiday"] for r in rows) != 288:
        raise ValueError("La cobertura de períodos feriados no coincide con los 288 congelados")
    if any(
        r["benchmark_prediction"] != r["candidate_prediction"]
        for r in rows
        if not r["is_holiday"]
    ):
        raise ValueError("Se encontró una diferencia fuera de los períodos feriados")

    dates = by_date(rows)
    holidays = [r for r in dates if r["holiday_name"]]
    total_savings = sum(row["absolute_error_savings"] for row in dates)
    holiday_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    month_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    quarter_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        holiday_rows[row["target_date"]].append(row)
        month_rows[row["target_date"][:7]].append(row)
        quarter = (date.fromisoformat(row["target_date"]).month - 1) // 3 + 1
        quarter_rows[f"2025-Q{quarter}"].append(row)

    holiday_contributions = []
    for daily in holidays:
        holiday_detail = holiday_rows[daily["target_date"]]
        detail = summary_metrics(holiday_detail)
        holiday_contributions.append(
            {
                "target_date": daily["target_date"],
                "holiday_name": daily["holiday_name"],
                "n_periods": daily["n_periods"],
                "benchmark_mae": detail["benchmark_mae"],
                "candidate_mae": detail["candidate_mae"],
                "mae_improvement": detail["mae_improvement"],
                "absolute_error_savings": daily["absolute_error_savings"],
                "share_of_net_absolute_error_savings_pct": 100 * daily["absolute_error_savings"] / total_savings,
                "periods_candidate_better": sum(
                    abs(row["candidate_error"]) < abs(row["benchmark_error"])
                    for row in holiday_detail
                ),
                "periods_candidate_worse": sum(
                    abs(row["candidate_error"]) > abs(row["benchmark_error"])
                    for row in holiday_detail
                ),
                "periods_tied": sum(
                    abs(row["candidate_error"]) == abs(row["benchmark_error"])
                    for row in holiday_detail
                ),
            }
        )

    leave_holiday_out = []
    for daily in holidays:
        leave_holiday_out.append(
            {
                "omitted_block": daily["target_date"],
                **leave_out(rows, {daily["target_date"]}),
            }
        )
    leave_holiday_out.append(
        {
            "omitted_block": "Fiestas Patrias (18–19 septiembre)",
            **leave_out(rows, FIESTAS_PATRIAS),
        }
    )

    by_month = []
    for month, subset in sorted(month_rows.items()):
        by_month.append({"block": month, **summary_metrics(subset)})
    by_quarter = []
    for quarter, subset in sorted(quarter_rows.items()):
        by_quarter.append({"block": quarter, **summary_metrics(subset)})
    leave_month_out = [
        {"omitted_block": month, **leave_out(rows, {r["target_date"] for r in subset})}
        for month, subset in sorted(month_rows.items())
    ]
    leave_quarter_out = [
        {
            "omitted_block": quarter,
            **leave_out(rows, {r["target_date"] for r in subset}),
        }
        for quarter, subset in sorted(quarter_rows.items())
    ]

    ordinary = [row for row in rows if not row["is_holiday"]]
    treated = [row for row in rows if row["is_holiday"]]
    largest_errors = []
    for method, field in (
        ("benchmark", "benchmark_error"),
        ("candidate", "candidate_error"),
    ):
        for row in sorted(rows, key=lambda item: abs(item[field]), reverse=True)[:10]:
            largest_errors.append(
                {
                    "method": method,
                    "target_date": row["target_date"],
                    "period_index": row["period_index"],
                    "event_window": row["event_window"],
                    "is_candidate_holiday": row["is_holiday"],
                    "signed_error": row[field],
                    "absolute_error": abs(row[field]),
                }
            )
    summary = {
        "source_file": str(INPUT.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": raw_hash_before,
        "rows": len(rows),
        "unique_target_dates": len(dates),
        "holiday_dates": len(holidays),
        "treated_periods": len(treated),
        "ordinary_periods": len(ordinary),
        "overall": summary_metrics(rows),
        "ordinary_days": summary_metrics(ordinary),
        "treated_holidays": summary_metrics(treated),
        "per_date_paired": paired_summary(dates),
        "per_holiday_contributions": sorted(
            holiday_contributions,
            key=lambda item: item["absolute_error_savings"],
        ),
        "leave_one_holiday_out": leave_holiday_out,
        "leave_fiestas_patrias_out": leave_out(rows, FIESTAS_PATRIAS),
        "per_month": by_month,
        "per_quarter": by_quarter,
        "leave_one_month_out": leave_month_out,
        "leave_one_quarter_out": leave_quarter_out,
        "largest_absolute_errors_top_10_by_method": largest_errors,
        "seven_day_block_bootstrap": bootstrap_by_quarter(dates),
        "limitations": [
            "Solo hay un año de evaluación y los errores se condicionan a esa serie.",
            "La hipótesis de feriados se originó al inspeccionar errores de desarrollo 2024.",
            "El bootstrap de bloques describe sensibilidad temporal dentro de 2025; no estima generalización interanual.",
            "Los doce feriados son fechas, no 288 observaciones independientes.",
            "No se modificaron ni regeneraron predicciones.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "resumen-robustez-extension-2025.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(OUTPUT_DIR / "contribucion-por-feriado-2025.csv", summary["per_holiday_contributions"])
    write_csv(OUTPUT_DIR / "diferencias-por-dia-2025.csv", dates)
    write_csv(OUTPUT_DIR / "sensibilidad-por-mes-2025.csv", by_month)
    write_csv(OUTPUT_DIR / "sensibilidad-por-trimestre-2025.csv", by_quarter)
    write_csv(OUTPUT_DIR / "omision-de-bloques-2025.csv", leave_month_out + leave_quarter_out)

    raw_hash_after = hashlib.sha256(INPUT.read_bytes()).hexdigest()
    if raw_hash_before != raw_hash_after:
        raise RuntimeError("El CSV fuente cambió durante la auditoría")
    print(json.dumps({
        "result": "PASS",
        "source_sha256_unchanged": raw_hash_before == raw_hash_after,
        "rows": len(rows),
        "overall": summary["overall"],
        "holiday_dates": len(holidays),
        "output_dir": str(OUTPUT_DIR),
        "bootstrap": summary["seven_day_block_bootstrap"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
