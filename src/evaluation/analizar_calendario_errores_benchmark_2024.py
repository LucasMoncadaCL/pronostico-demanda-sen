from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/audits/2024-demanda-sistemica/benchmark-validacion-2024/predicciones-benchmark-2024.csv"
OUTPUT = ROOT / "data/audits/2024-demanda-sistemica/asociaciones-calendario-benchmark-2024"
START = date(2024, 4, 6)
END = date(2024, 10, 31)

# National holidays and election dates inside the benchmark development window.
# Dates and labels were cross-checked against Gob.cl's 2024 holiday list.
CALENDAR_DATES = {
    "2024-05-01": ("Día del Trabajador", "feriado_nacional"),
    "2024-05-21": ("Día de las Glorias Navales", "feriado_nacional"),
    "2024-06-09": ("Elecciones primarias", "elección_domingo"),
    "2024-06-20": ("Día Nacional de los Pueblos Indígenas", "feriado_nacional"),
    "2024-06-29": ("San Pedro y San Pablo", "feriado_nacional"),
    "2024-07-16": ("Día de la Virgen del Carmen", "feriado_nacional"),
    "2024-08-15": ("Asunción de la Virgen", "feriado_nacional"),
    "2024-09-18": ("Independencia Nacional", "feriado_nacional"),
    "2024-09-19": ("Día de las Glorias del Ejército", "feriado_nacional"),
    "2024-09-20": ("Feriado adicional de Fiestas Patrias", "feriado_nacional"),
    "2024-10-12": ("Encuentro de Dos Mundos", "feriado_nacional"),
    "2024-10-26": ("Jornada electoral regional y municipal", "evento_electoral_sábado"),
    "2024-10-27": ("Elecciones regionales y municipales", "elección_domingo"),
    "2024-10-31": ("Día de las Iglesias Evangélicas y Protestantes", "feriado_nacional"),
}
WEEKDAY_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def load_rows() -> list[dict]:
    rows = []
    with INPUT.open("r", encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
            target = date.fromisoformat(raw["target_date"])
            if not START <= target <= END or target.year != 2024:
                raise ValueError(f"Fecha fuera de la ventana autorizada: {target}")
            forecast = float(raw["prediction"])
            observed = float(raw["observed_ex_post"])
            error = float(raw["error_prediction_minus_observed"])
            if abs(error - (forecast - observed)) > 1e-8:
                raise ValueError(f"Error almacenado no coincide con pronóstico − observado en {target}")
            holiday_name, calendar_class = CALENDAR_DATES.get(target.isoformat(), ("", ""))
            rows.append({
                "target_date": target.isoformat(),
                "month": target.strftime("%Y-%m"),
                "weekday_monday0": target.weekday(),
                "weekday_name": WEEKDAY_ES[target.weekday()],
                "period_index": int(raw["target_period_index"]),
                "forecast": forecast,
                "observed": observed,
                "error_prediction_minus_observed": error,
                "absolute_error": abs(error),
                "holiday_name": holiday_name,
                "calendar_class": calendar_class,
            })
    keys = [(r["target_date"], r["period_index"]) for r in rows]
    if len(rows) != 5016 or len(set(keys)) != 5016:
        raise ValueError(f"Cobertura inesperada o duplicada: filas={len(rows)}, claves={len(set(keys))}")
    if any(r["forecast"] < 0 for r in rows):
        raise ValueError("Se encontraron pronósticos negativos")
    return rows


def score_rows(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "periods": n,
        "mae": sum(r["absolute_error"] for r in rows) / n if n else None,
        "rmse": (sum(r["error_prediction_minus_observed"] ** 2 for r in rows) / n) ** 0.5 if n else None,
        "bias_prediction_minus_observed": sum(r["error_prediction_minus_observed"] for r in rows) / n if n else None,
    }


def daily_summaries(rows: list[dict]) -> list[dict]:
    by_day = defaultdict(list)
    for row in rows:
        by_day[row["target_date"]].append(row)
    summaries = []
    for day, day_rows in sorted(by_day.items()):
        first = day_rows[0]
        summary = {
            "target_date": day,
            "month": first["month"],
            "weekday_monday0": first["weekday_monday0"],
            "weekday_name": first["weekday_name"],
            "holiday_name": first["holiday_name"],
            "calendar_class": first["calendar_class"],
            "periods": len(day_rows),
            "daily_mae": sum(r["absolute_error"] for r in day_rows) / len(day_rows),
            "daily_bias": sum(r["error_prediction_minus_observed"] for r in day_rows) / len(day_rows),
        }
        summaries.append(summary)
    return summaries


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    days = daily_summaries(rows)

    by_month = defaultdict(list)
    by_weekday = defaultdict(list)
    for row in rows:
        by_month[row["month"]].append(row)
        by_weekday[row["weekday_name"]].append(row)
    monthly = []
    for month, month_rows in sorted(by_month.items()):
        month_days = [d for d in days if d["month"] == month]
        monthly.append({
            "month": month,
            "days": len(month_days),
            **score_rows(month_rows),
            "mean_forecast": sum(r["forecast"] for r in month_rows) / len(month_rows),
            "mean_observed": sum(r["observed"] for r in month_rows) / len(month_rows),
            "mean_daily_mae": sum(d["daily_mae"] for d in month_days) / len(month_days),
        })
    weekday = []
    for name in WEEKDAY_ES:
        weekday_rows = by_weekday[name]
        weekday_days = [d for d in days if d["weekday_name"] == name]
        weekday.append({
            "weekday_name": name,
            "days": len(weekday_days),
            **score_rows(weekday_rows),
            "mean_daily_mae": sum(d["daily_mae"] for d in weekday_days) / len(weekday_days),
        })

    weekday_holidays = [
        d for d in days
        if d["calendar_class"] == "feriado_nacional" and d["weekday_monday0"] < 5
    ]
    ordinary_weekdays = [
        d for d in days
        if not d["calendar_class"] and d["weekday_monday0"] < 5
    ]
    holiday_rows = [r for r in rows if r["calendar_class"] == "feriado_nacional" and r["weekday_monday0"] < 5]
    ordinary_weekday_rows = [r for r in rows if not r["calendar_class"] and r["weekday_monday0"] < 5]

    holiday_day_comparison = []
    for holiday in weekday_holidays:
        controls = [
            d for d in ordinary_weekdays
            if d["weekday_monday0"] == holiday["weekday_monday0"]
        ]
        control_mae = statistics.median(d["daily_mae"] for d in controls)
        holiday_day_comparison.append({
            **holiday,
            "same_weekday_ordinary_control_days": len(controls),
            "same_weekday_control_median_daily_mae": control_mae,
            "daily_mae_minus_same_weekday_median": holiday["daily_mae"] - control_mae,
            "daily_mae_above_same_weekday_median": holiday["daily_mae"] > control_mae,
        })

    summary = {
        "scope": "2024 benchmark development window only; no supervised model fitting; no 2025 access",
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "input": "benchmark-validacion-2024/predicciones-benchmark-2024.csv",
        "calendar_sources": [
            "https://www.gob.cl/noticias/feriado-2024-chile-dias-festivos-irrenunciables/",
            "https://www.servel.cl/Ch/app/26-y-27-de-octubre-elecciones-regionales-y-municipales/noticias/",
        ],
        "coverage": {"dates": len(days), "prediction_rows": len(rows), "duplicate_date_period_keys": 0},
        "monthly_benchmark_errors": monthly,
        "weekday_benchmark_errors": weekday,
        "weekday_national_holiday_comparison": {
            "holiday_days": len(weekday_holidays),
            "holiday_rows": len(holiday_rows),
            "holiday_pooled_hourly_metrics": score_rows(holiday_rows),
            "holiday_mean_daily_mae": sum(d["daily_mae"] for d in weekday_holidays) / len(weekday_holidays),
            "ordinary_weekday_days": len(ordinary_weekdays),
            "ordinary_weekday_rows": len(ordinary_weekday_rows),
            "ordinary_weekday_pooled_hourly_metrics": score_rows(ordinary_weekday_rows),
            "ordinary_weekday_mean_daily_mae": sum(d["daily_mae"] for d in ordinary_weekdays) / len(ordinary_weekdays),
            "holiday_dates": holiday_day_comparison,
        },
        "election_sundays": [d for d in days if d["calendar_class"] == "elección_domingo"],
        "other_special_event_days": [d for d in days if d["calendar_class"] == "evento_electoral_sábado"],
        "interpretation_limits": [
            "Calendar comparisons are descriptive and do not establish causality.",
            "There are only nine weekday national-holiday dates in the window; three are consecutive Fiestas Patrias dates.",
            "The development interval contains less than one year and one instance of each seasonal cycle; monthly patterns are not evidence of repeatable interannual seasonality.",
            "Calendar classes do not encode region-specific holidays, school closures, bridge days, or actual commercial activity.",
            "The 60-day lag, rolling training history, evolving demand level, and month change together; their contributions are not separately identified.",
        ],
    }
    write_csv(OUTPUT / "errores-benchmark-periodo-calendario-2024.csv", rows)
    write_csv(OUTPUT / "errores-benchmark-por-dia-2024.csv", days)
    write_csv(OUTPUT / "errores-benchmark-por-mes-2024.csv", monthly)
    (OUTPUT / "resumen-asociaciones-calendario-2024.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "dates": len(days),
        "rows": len(rows),
        "weekday_holiday_days": len(weekday_holidays),
        "weekday_holiday_hourly_mae": summary["weekday_national_holiday_comparison"]["holiday_pooled_hourly_metrics"]["mae"],
        "ordinary_weekday_hourly_mae": summary["weekday_national_holiday_comparison"]["ordinary_weekday_pooled_hourly_metrics"]["mae"],
        "output": str(OUTPUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
