"""Frozen 2025 evaluation of the registered weekly-profile benchmark.

Primary policy: fixed 2024-only training snapshot, eligible at issue 2024-12-31
under the strict 60-calendar-day cutoff. Sensitivity policy: revised history
through the calendar day before issue; benchmark means update per issue.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter, defaultdict
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
from src.evaluation.benchmark_policy import eligible_history, frozen_2024_snapshot

AUDIT_ROOT = REPO_ROOT / "data/audits"
TRAIN_PATH = AUDIT_ROOT / "2024-demanda-sistemica/serie_horaria_2024.csv"
TARGET_PATH = AUDIT_ROOT / "2025-demanda-sistemica/serie_horaria_2025.csv"
PROTOCOL_PATH = REPO_ROOT / "docs/protocol/protocolo-evaluacion-v1.2.md"
DEFAULT_OUTPUT = AUDIT_ROOT / "2025-demanda-sistemica/evaluacion-benchmark-congelada"
FIRST_ISSUE = date(2024, 12, 31)
LAG_DAYS = 60
EVENT_DATES = {date(2025, 2, 25), date(2025, 2, 26)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_series(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append({
                "date": date.fromisoformat(raw["fecha"]),
                "hour": int(raw["hora"]),
                "value": Decimal(raw["demanda"]),
            })
    keys = [(r["date"], r["hour"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Claves duplicadas en {path}.")
    return sorted(rows, key=lambda r: (r["date"], r["hour"]))


def score(records: list[dict]) -> dict:
    if not records:
        return {"n": 0, "mae": None, "rmse": None, "bias": None, "mape_percent": None}
    n = Decimal(len(records))
    errors = [r["prediction"] - r["observed"] for r in records]
    abs_errors = [abs(e) for e in errors]
    mae = sum(abs_errors, Decimal("0")) / n
    bias = sum(errors, Decimal("0")) / n
    rmse = math.sqrt(sum(float(e * e) for e in errors) / len(errors))
    mape = sum((abs(e) / r["observed"] for e, r in zip(errors, records)), Decimal("0")) * Decimal(100) / n
    return {"n": len(records), "mae": str(mae), "rmse": rmse, "bias_prediction_minus_observed": str(bias), "mape_percent": str(mape)}


def make_predictions(target_rows: list[dict], history_rows: list[dict], policy: str) -> list[dict]:
    targets_by_date: dict[date, list[dict]] = defaultdict(list)
    for row in target_rows:
        targets_by_date[row["date"]].append(row)
    records = []
    for target_date in sorted(targets_by_date):
        issue_date = target_date - timedelta(days=1)
        cutoff = issue_date - timedelta(days=LAG_DAYS if policy == "primary_60d_fixed_2024" else 0)
        if policy == "primary_60d_fixed_2024":
            history = history_rows
            if any(r["date"] >= cutoff for r in history):
                raise AssertionError(f"El snapshot fijo no cumple el corte el {issue_date}.")
        elif policy == "sensitivity_no_lag_updated_history":
            history = eligible_history(history_rows, issue_date, 0)
        else:
            raise ValueError(f"Política desconocida: {policy}")
        if not history:
            raise ValueError(f"No hay historia para {policy}, origen {issue_date}.")
        max_history_date = max(r["date"] for r in history)
        for target in targets_by_date[target_date]:
            result = predict_one(weekday=target_date.weekday(), period_index=target["hour"], history=history)
            if result["prediction"] is None:
                raise ValueError(f"Sin soporte {policy}, {target_date}, índice {target['hour']}.")
            records.append({
                "policy": policy,
                "issue_date_local": issue_date.isoformat(),
                "issue_time_local": "18:00 America/Santiago",
                "cutoff_date_exclusive": cutoff.isoformat(),
                "history_start_date": min(r["date"] for r in history).isoformat(),
                "history_end_date": max_history_date.isoformat(),
                "history_records": len(history),
                "target_date": target_date.isoformat(),
                "target_weekday_monday0": target_date.weekday(),
                "target_period_index": target["hour"],
                "fallback_level": result["fallback_level"],
                "n_support": result["n_support"],
                "prediction": result["prediction"],
                "observed": target["value"],
                "error_prediction_minus_observed": result["prediction"] - target["value"],
                "absolute_error": abs(result["prediction"] - target["value"]),
                "event_window_2025_02_25_26": target_date in EVENT_DATES,
            })
    return records


def encode_records(records: list[dict]) -> list[dict]:
    return [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in row.items()} for row in records]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    train2024 = [r for r in read_series(TRAIN_PATH) if r["date"].year == 2024]
    targets2025 = [r for r in read_series(TARGET_PATH) if r["date"].year == 2025]
    if len(targets2025) != 8760:
        raise ValueError(f"Se esperaban 8760 objetivos 2025 auditados; se recibieron {len(targets2025)}.")
    primary_history = frozen_2024_snapshot(train2024, FIRST_ISSUE, LAG_DAYS)
    if len(primary_history) != 7320 or max(r["date"] for r in primary_history) != date(2024, 10, 31):
        raise AssertionError("El snapshot primario no coincide con el conjunto fijado (2024-01-01..2024-10-31).")

    # Produce forecasts for the whole target window before calculating any score.
    primary = make_predictions(targets2025, primary_history, "primary_60d_fixed_2024")
    sensitivity = make_predictions(targets2025, train2024 + targets2025, "sensitivity_no_lag_updated_history")
    all_targets = {(r["date"], r["hour"]): r["value"] for r in targets2025}
    for label, rows in (("primary", primary), ("sensitivity", sensitivity)):
        keys = [(date.fromisoformat(r["target_date"]), int(r["target_period_index"])) for r in rows]
        if len(keys) != len(all_targets) or set(keys) != set(all_targets):
            raise AssertionError(f"{label}: la cobertura de objetivos no coincide con el conjunto auditado.")
        if any(r["observed"] != all_targets[(date.fromisoformat(r["target_date"]), int(r["target_period_index"]))] for r in rows):
            raise AssertionError(f"{label}: divergencia en el objetivo ex post.")

    metrics = {}
    for policy, records in (("primary_60d_fixed_2024", primary), ("sensitivity_no_lag_updated_history", sensitivity)):
        metrics[policy] = {
            "all_2025_targets_including_event": score(records),
            "excluding_full_dates_2025_02_25_and_2025_02_26": score([r for r in records if not r["event_window_2025_02_25_26"]]),
            "event_date_2025_02_25": score([r for r in records if r["target_date"] == "2025-02-25"]),
            "event_date_2025_02_26": score([r for r in records if r["target_date"] == "2025-02-26"]),
            "fallback_level_counts": dict(Counter(r["fallback_level"] for r in records)),
            "missing_predictions": sum(r["prediction"] is None for r in records),
        }

    primary_csv = output / "predicciones-benchmark-2025-regimen-principal.csv"
    sensitivity_csv = output / "predicciones-benchmark-2025-sensibilidad.csv"
    fields = list(encode_records(primary)[0])
    for path, records in ((primary_csv, primary), (sensitivity_csv, sensitivity)):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(encode_records(records))

    period25 = [r for r in primary if r["target_date"] == "2025-04-05" and r["target_period_index"] == 25]
    summary = {
        "protocol": "v1.2 frozen before 2025 scoring",
        "2025_is_non_blind_holdout": True,
        "evaluation_scope": "registered benchmark only; no ML model selection or tuning",
        "frozen_artifacts_sha256": {
            "protocol_v1_2": sha256(PROTOCOL_PATH),
            "evaluation_script": sha256(Path(__file__).resolve()),
            "baseline_implementation": sha256(REPO_ROOT / "src/baselines/weekday_period_mean.py"),
            "availability_policy_implementation": sha256(REPO_ROOT / "src/evaluation/benchmark_policy.py"),
            "2024_development_validation_script": sha256(REPO_ROOT / "src/evaluation/validar_benchmark_2024.py"),
            "2024_independent_verifier": sha256(REPO_ROOT / "src/evaluation/verify_benchmark_predictions_2024.py"),
            "unit_test_weekday_period": sha256(REPO_ROOT / "tests/test_weekday_period_mean.py"),
            "unit_test_availability_policy": sha256(REPO_ROOT / "tests/test_benchmark_policy.py"),
            "unit_test_frozen_evaluation": sha256(REPO_ROOT / "tests/test_frozen_evaluation.py"),
            "2024_validation_predictions": sha256(AUDIT_ROOT / "2024-demanda-sistemica/benchmark-validacion-2024/predicciones-benchmark-2024.csv"),
            "2024_validation_summary": sha256(AUDIT_ROOT / "2024-demanda-sistemica/benchmark-validacion-2024/resumen-validacion-benchmark-2024.json"),
        },
        "pre_holdout_checks": {
            "unit_tests": "10 passed",
            "independent_2024_validation": "5016/5016 targets verified; 0 missing; every issue cutoff and training set recomputed",
            "selection_target_window": "2024-04-06 through 2024-10-31 only",
        },
        "data": {
            "train_2024_csv_sha256": sha256(TRAIN_PATH),
            "target_2025_csv_sha256": sha256(TARGET_PATH),
            "protocol_sha256": sha256(PROTOCOL_PATH),
            "train_rows_primary": len(primary_history),
            "train_start_primary": min(r["date"] for r in primary_history).isoformat(),
            "train_end_primary": max(r["date"] for r in primary_history).isoformat(),
            "target_rows_2025": len(targets2025),
        },
        "policies": {
            "primary_60d_fixed_2024": "Frozen profile using 2024-01-01..2024-10-31; no 2025 observations enter the benchmark.",
            "sensitivity_no_lag_updated_history": "At each issue, use all revised historical observations with date < issue date, including eligible past 2025; this is a complete alternative policy, not an isolated 60-day ablation.",
        },
        "metrics": metrics,
        "primary_period_25_diagnostic": encode_records(period25),
        "outputs": {
            "primary_predictions_csv": primary_csv.name,
            "sensitivity_predictions_csv": sensitivity_csv.name,
        },
        "interpretation": [
            "The main result includes all 2025 periods, including the documented event window.",
            "The event-excluded summaries are diagnostics only and must not alter model selection or protocol rules.",
            "The weekday-wide Saturday fallback for the 2025-04-05 period 25 is explicitly flagged and is not a period-specific learned profile.",
            "No target records were modified or imputed; 2025 results are retrospective and use current revised values.",
        ],
    }
    summary_path = output / "evaluacion-benchmark-2025.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": metrics, "period25": encode_records(period25), "summary": str(summary_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
