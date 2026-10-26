"""Descripción de errores extremos y ventana excepcional de 2025.

Solo lee predicciones y observaciones congeladas; no entrena ni predice.
Ejecutar desde la raíz: py src/evaluation/auditar_errores_extremos_eventos_2025.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/audits/2025-demanda-sistemica/evaluacion-extension-feriados-congelada/predicciones-extension-feriados-2025.csv"
OUTPUT_DIR = ROOT / "data/audits/2025-demanda-sistemica/auditoria-errores-extremos"


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    pos = (len(ordered) - 1) * p
    lower, upper = math.floor(pos), math.ceil(pos)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - pos) + ordered[upper] * (pos - lower)


def error_metrics(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    errors = [row[f"{method}_error"] for row in rows]
    absolute = [abs(value) for value in errors]
    return {
        "n_periods": len(rows),
        "mae": mean(absolute) if rows else None,
        "rmse": math.sqrt(mean(value * value for value in errors)) if rows else None,
        "bias_prediction_minus_observed": mean(errors) if rows else None,
        "abs_error_p50": percentile(absolute, 0.50),
        "abs_error_p90": percentile(absolute, 0.90),
        "abs_error_p95": percentile(absolute, 0.95),
        "abs_error_p99": percentile(absolute, 0.99),
        "abs_error_max": max(absolute) if rows else None,
    }


def load_data() -> list[dict[str, Any]]:
    result = []
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            observed = float(item["observed"])
            benchmark = float(item["benchmark_prediction"])
            candidate = float(item["candidate_prediction"])
            result.append(
                {
                    "target_date": item["target_date"],
                    "period_index": int(item["period_index"]),
                    "observed": observed,
                    "benchmark_prediction": benchmark,
                    "candidate_prediction": candidate,
                    "benchmark_error": benchmark - observed,
                    "candidate_error": candidate - observed,
                    "event_window": item["event_window"].strip().lower() == "true",
                    "is_candidate_holiday": item["is_candidate_holiday"].strip().lower() == "true",
                    "holiday_name": item["holiday_name"],
                }
            )
    return result


def by_date(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["target_date"]].append(row)
    result = []
    for day, group in sorted(groups.items()):
        record: dict[str, Any] = {
            "target_date": day,
            "day_of_week": date.fromisoformat(day).strftime("%A"),
            "n_periods": len(group),
            "event_window": group[0]["event_window"],
            "is_candidate_holiday": any(r["is_candidate_holiday"] for r in group),
            "holiday_name": next((r["holiday_name"] for r in group if r["is_candidate_holiday"]), ""),
        }
        for method in ("benchmark", "candidate"):
            metrics = error_metrics(group, method)
            errors = [row[f"{method}_error"] for row in group]
            average_error = mean(errors)
            record[f"{method}_mae"] = metrics["mae"]
            record[f"{method}_rmse"] = metrics["rmse"]
            record[f"{method}_bias"] = metrics["bias_prediction_minus_observed"]
            record[f"{method}_absolute_error_sum"] = sum(abs(error) for error in errors)
            record[f"{method}_squared_error_sum"] = sum(error * error for error in errors)
            record[f"{method}_shape_rmse"] = math.sqrt(
                mean((error - average_error) ** 2 for error in errors)
            )
        result.append(record)
    return result


def top_k_contributions(
    dates: list[dict[str, Any]], rows: list[dict[str, Any]], k_values: tuple[int, ...]
) -> list[dict[str, Any]]:
    """Select dates by benchmark daily MAE once; score both methods on identical dates."""
    annual: dict[str, dict[str, float]] = {}
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row["target_date"]].append(row)
    for method in ("benchmark", "candidate"):
        errors = [row[f"{method}_error"] for row in rows]
        annual[method] = {
            "absolute_error_sum": sum(abs(error) for error in errors),
            "squared_error_sum": sum(error * error for error in errors),
        }
    ordered = sorted(dates, key=lambda row: (-row["benchmark_mae"], row["target_date"]))
    output = []
    for k in k_values:
        selected = ordered[:k]
        selected_dates = {row["target_date"] for row in selected}
        subset = [row for row in rows if row["target_date"] in selected_dates]
        record: dict[str, Any] = {
            "top_k": k,
            "selection_rule": "benchmark daily MAE descending, date ascending for ties",
            "selected_dates": ";".join(row["target_date"] for row in selected),
            "n_periods": len(subset),
        }
        for method in ("benchmark", "candidate"):
            errors = [row[f"{method}_error"] for row in subset]
            abs_sum = sum(abs(error) for error in errors)
            sq_sum = sum(error * error for error in errors)
            record[f"{method}_mean_daily_mae"] = mean(
                day[f"{method}_mae"] for day in selected
            )
            record[f"{method}_absolute_error_sum"] = abs_sum
            record[f"{method}_absolute_error_share_annual_pct"] = (
                abs_sum / annual[method]["absolute_error_sum"] * 100
            )
            record[f"{method}_squared_error_sum"] = sq_sum
            record[f"{method}_squared_error_share_annual_pct"] = (
                sq_sum / annual[method]["squared_error_sum"] * 100
            )
        output.append(record)
    return output


def top_periods(rows: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (-abs(row["benchmark_error"]), row["target_date"], row["period_index"]),
    )[:n]
    return [
        {
            "target_date": row["target_date"],
            "period_index": row["period_index"],
            "event_window": row["event_window"],
            "is_candidate_holiday": row["is_candidate_holiday"],
            "observed": row["observed"],
            "benchmark_prediction": row["benchmark_prediction"],
            "benchmark_error": row["benchmark_error"],
            "benchmark_absolute_error": abs(row["benchmark_error"]),
            "candidate_prediction": row["candidate_prediction"],
            "candidate_error": row["candidate_error"],
            "candidate_absolute_error": abs(row["candidate_error"]),
        }
        for row in ordered
    ]


def write_svg_profiles(
    rows: list[dict[str, Any]], daily: list[dict[str, Any]], output_path: Path
) -> list[str]:
    """Write a compact, dependency-free SVG of the event and top untreated dates."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["target_date"]].append(row)
    untreated_top = [
        row
        for row in sorted(daily, key=lambda item: (-item["benchmark_mae"], item["target_date"]))
        if not row["event_window"] and not row["is_candidate_holiday"]
    ][:3]
    selected = ["2025-02-25", "2025-02-26"] + [row["target_date"] for row in untreated_top]
    canvas_w, canvas_h = 1200, 900
    cell_w, cell_h = 570, 270
    plot_left, plot_right, plot_top, plot_bottom = 64, 20, 48, 42
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="600" y="30" text-anchor="middle" font-family="Arial" font-size="21" font-weight="bold">Perfiles observados y pronosticados en fechas de error elevado, 2025</text>',
    ]
    colors = {"observed": "#1f77b4", "benchmark": "#e67e22", "candidate": "#2ca02c"}
    y = 60
    for index, day in enumerate(selected):
        col, rownum = index % 2, index // 2
        x, y0 = 20 + col * 590, y + rownum * cell_h
        subset = sorted(grouped[day], key=lambda item: item["period_index"])
        all_values = [item[key] for item in subset for key in ("observed", "benchmark_prediction", "candidate_prediction")]
        low, high = min(all_values), max(all_values)
        pad = max((high - low) * 0.08, 1.0)
        low -= pad
        high += pad
        px0, px1 = x + plot_left, x + cell_w - plot_right
        py0, py1 = y0 + plot_top, y0 + cell_h - plot_bottom
        svg.append(f'<text x="{x + 8}" y="{y0 + 24}" font-family="Arial" font-size="16" font-weight="bold">{day} · {"ventana excepcional" if day.startswith("2025-02-") else "sin tratamiento feriado"}</text>')
        svg.append(f'<rect x="{px0}" y="{py0}" width="{px1-px0}" height="{py1-py0}" fill="#fafafa" stroke="#bbbbbb"/>')
        for tick in range(5):
            value = low + (high - low) * tick / 4
            ty = py1 - (py1 - py0) * tick / 4
            svg.append(f'<line x1="{px0}" y1="{ty:.1f}" x2="{px1}" y2="{ty:.1f}" stroke="#e5e5e5"/>')
            svg.append(f'<text x="{px0-6}" y="{ty+4:.1f}" text-anchor="end" font-family="Arial" font-size="10">{value:.0f}</text>')
        max_period = max(item["period_index"] for item in subset)
        for key, color, dash in (("observed", colors["observed"], ""), ("benchmark_prediction", colors["benchmark"], ""), ("candidate_prediction", colors["candidate"], "6,4")):
            points=[]
            for item in subset:
                cx = px0 + (item["period_index"] - 1) / max(max_period - 1, 1) * (px1 - px0)
                cy = py1 - (item[key] - low) / (high - low) * (py1 - py0)
                points.append(f'{cx:.1f},{cy:.1f}')
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ''
            svg.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"{dash_attr}/>')
        svg.append(f'<text x="{px0}" y="{py1+18}" font-family="Arial" font-size="10">Período 1</text>')
        svg.append(f'<text x="{px1}" y="{py1+18}" text-anchor="end" font-family="Arial" font-size="10">Período {max_period}</text>')
    legend_y = canvas_h - 12
    legend_items = [("Observado", colors["observed"]), ("Benchmark", colors["benchmark"]), ("Extensión", colors["candidate"])]
    legend_x = 420
    for label, color in legend_items:
        svg.append(f'<line x1="{legend_x}" y1="{legend_y-5}" x2="{legend_x+28}" y2="{legend_y-5}" stroke="{color}" stroke-width="3"/>')
        svg.append(f'<text x="{legend_x+35}" y="{legend_y}" font-family="Arial" font-size="12">{label}</text>')
        legend_x += 125
    svg.append('</svg>')
    output_path.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return selected


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    source_hash = hashlib.sha256(INPUT.read_bytes()).hexdigest()
    rows = load_data()
    if len(rows) != 8760:
        raise ValueError(f"Esperadas 8.760 filas; recibidas {len(rows)}")
    if len({(row["target_date"], row["period_index"]) for row in rows}) != len(rows):
        raise ValueError("Clave de período duplicada")
    event_rows = [row for row in rows if row["event_window"]]
    outside_event_rows = [row for row in rows if not row["event_window"]]
    if len(event_rows) != 48:
        raise ValueError(f"La ventana excepcional esperada contiene 48 períodos, no {len(event_rows)}")
    if any(row["is_candidate_holiday"] for row in event_rows):
        raise ValueError("La ventana de evento se superpone con un feriado tratado")
    if any(row["benchmark_prediction"] != row["candidate_prediction"] for row in event_rows):
        raise ValueError("Las predicciones archivadas difieren dentro de la ventana excepcional")

    dates = by_date(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["target_date"]].append(row)
    event_days = [dict(row) for row in dates if row["event_window"]]
    if sorted(row["target_date"] for row in event_days) != ["2025-02-25", "2025-02-26"]:
        raise ValueError("Las fechas marcadas como ventana excepcional no coinciden con el protocolo")

    annual_contributions = {}
    event_contributions = {}
    for method in ("benchmark", "candidate"):
        errors = [row[f"{method}_error"] for row in rows]
        event_errors = [row[f"{method}_error"] for row in event_rows]
        annual_contributions[method] = {
            "absolute_error_sum": sum(abs(error) for error in errors),
            "squared_error_sum": sum(error * error for error in errors),
        }
        event_contributions[method] = {
            "absolute_error_sum": sum(abs(error) for error in event_errors),
            "squared_error_sum": sum(error * error for error in event_errors),
            "absolute_error_share_annual_pct": (
                sum(abs(error) for error in event_errors)
                / annual_contributions[method]["absolute_error_sum"]
                * 100
            ),
            "squared_error_share_annual_pct": (
                sum(error * error for error in event_errors)
                / annual_contributions[method]["squared_error_sum"]
                * 100
            ),
        }
    for event_day in event_days:
        for method in ("benchmark", "candidate"):
            event_day[f"{method}_absolute_error_share_annual_pct"] = (
                event_day[f"{method}_absolute_error_sum"]
                / annual_contributions[method]["absolute_error_sum"]
                * 100
            )
            event_day[f"{method}_squared_error_share_annual_pct"] = (
                event_day[f"{method}_squared_error_sum"]
                / annual_contributions[method]["squared_error_sum"]
                * 100
            )

    top_daily = sorted(dates, key=lambda row: (-row["benchmark_mae"], row["target_date"]))
    top10_outside = [row for row in top_daily if not row["event_window"]][:10]
    top10_untreated = [
        row for row in top_daily
        if not row["event_window"] and not row["is_candidate_holiday"]
    ][:10]
    top10_all = top_daily[:10]
    top_k = top_k_contributions(dates, rows, (1, 5, 10))
    periods_all = top_periods(rows, 10)
    periods_outside = top_periods(outside_event_rows, 10)
    profile_fields = (
        "target_date", "period_index", "observed", "benchmark_prediction",
        "candidate_prediction", "benchmark_error", "candidate_error",
    )
    event_profiles = [{key: row[key] for key in profile_fields} for row in sorted(event_rows, key=lambda row: (row["target_date"], row["period_index"]))]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = OUTPUT_DIR / "perfiles-ventana-excepcional-y-dias-no-tratados.svg"
    selected_profile_dates = write_svg_profiles(rows, dates, svg_path)
    summary = {
        "source_file": str(INPUT.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": source_hash,
        "n_rows": len(rows),
        "n_dates": len(dates),
        "event_window": {
            "dates": sorted({row["target_date"] for row in event_rows}),
            "n_periods": len(event_rows),
            "share_of_annual_periods_pct": len(event_rows) / len(rows) * 100,
            "benchmark": error_metrics(event_rows, "benchmark"),
            "candidate": error_metrics(event_rows, "candidate"),
            "contribution": event_contributions,
            "predictions_identical": True,
        },
        "outside_event_window": {
            "n_periods": len(outside_event_rows),
            "benchmark": error_metrics(outside_event_rows, "benchmark"),
            "candidate": error_metrics(outside_event_rows, "candidate"),
        },
        "all_periods": {
            "benchmark": error_metrics(rows, "benchmark"),
            "candidate": error_metrics(rows, "candidate"),
        },
        "annual_error_contributions": annual_contributions,
        "top_k_days_selected_by_benchmark_daily_mae": top_k,
        "top_10_days_full_year_selected_by_benchmark_daily_mae": top10_all,
        "top_10_days_outside_event_selected_by_benchmark_daily_mae": top10_outside,
        "top_10_days_without_candidate_holiday_treatment_selected_by_benchmark_daily_mae": top10_untreated,
        "top_10_periods_full_year_selected_by_benchmark_absolute_error": periods_all,
        "top_10_periods_outside_event_selected_by_benchmark_absolute_error": periods_outside,
        "profile_dates_in_figure": selected_profile_dates,
        "interpretation_limits": [
            "La ventana de evento se toma del campo event_window ya archivado; no se estimó ni predijo el evento.",
            "Los residuos describen errores de estas predicciones en 2025; no identifican causalidad ni riesgo de red.",
            "La métrica diaria usa índices de período de la fuente, no una reconstrucción de horas civiles.",
            "Los 20 mayores errores describen esta muestra y no constituyen una distribución de cola generalizable.",
        ],
    }

    (OUTPUT_DIR / "resumen-errores-extremos-2025.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(OUTPUT_DIR / "metricas-diarias-2025.csv", dates)
    write_csv(OUTPUT_DIR / "metricas-dias-ventana-evento-2025.csv", event_days)
    write_csv(OUTPUT_DIR / "contribuciones-top-dias-2025.csv", top_k)
    write_csv(OUTPUT_DIR / "top10-dias-anual-2025.csv", top10_all)
    write_csv(OUTPUT_DIR / "top10-dias-fuera-evento-2025.csv", top10_outside)
    write_csv(OUTPUT_DIR / "top10-dias-no-tratados-2025.csv", top10_untreated)
    write_csv(OUTPUT_DIR / "top10-periodos-anual-2025.csv", periods_all)
    write_csv(OUTPUT_DIR / "top10-periodos-fuera-evento-2025.csv", periods_outside)
    write_csv(OUTPUT_DIR / "perfiles-48-periodos-ventana-excepcional-2025.csv", event_profiles)

    if hashlib.sha256(INPUT.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("El CSV de predicciones cambió durante el análisis")
    print(json.dumps({
        "result": "PASS",
        "source_sha256_unchanged": True,
        "n_rows": len(rows),
        "event_window": summary["event_window"],
        "outside_event_window": summary["outside_event_window"],
        "top_k_days": summary["top_k_days_selected_by_benchmark_daily_mae"],
        "outputs": str(OUTPUT_DIR),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
