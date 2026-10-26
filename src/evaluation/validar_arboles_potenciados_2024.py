"""2024-only rolling-origin validation for a calendar boosted-tree model."""
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
from src.models.arboles_potenciados import fit_tree_state, predict_from_tree_state

DEFAULT_INPUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
DEFAULT_OUT = REPO_ROOT / "data/audits/2024-demanda-sistemica/arboles-potenciados-validacion-2024"
PROTOCOL = REPO_ROOT / "docs/protocol/protocolo-evaluacion-v1.2.md"
MODEL_SOURCE = REPO_ROOT / "src/models/arboles_potenciados.py"
START = date(2024, 4, 6)
END = date(2024, 10, 31)
LAG_DAYS = 60
MAX_LEAF_GRID = (7, 15)
FIXED_PARAMS = {
    "min_samples_leaf": 20,
    "max_iter": 30,
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
                raise ValueError("La validación de desarrollo solo admite datos de 2024.")
            rows.append({"date": day, "hour": int(raw["hora"]), "value": Decimal(raw["demanda"])})
    if len({(r["date"], r["hour"]) for r in rows}) != len(rows):
        raise ValueError("La serie contiene claves (fecha, hora) duplicadas.")
    return sorted(rows, key=lambda r: (r["date"], r["hour"]))


def metrics(records: list[dict], prediction_field: str) -> dict:
    errors = [float(row[prediction_field]) - float(row["observed_ex_post"]) for row in records]
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
    target_dates = [d for d in sorted(by_date) if START <= d <= END]
    if len(target_dates) != (END - START).days + 1:
        raise ValueError("La ventana 2024-04-06..2024-10-31 está incompleta.")

    records_by_leaves: dict[int, list[dict]] = {leaf: [] for leaf in MAX_LEAF_GRID}
    origin_audit = []
    for target_date in target_dates:
        issue_date = target_date - timedelta(days=1)
        cutoff = cutoff_date(issue_date, LAG_DAYS)
        history = eligible_history(rows, issue_date, LAG_DAYS)
        if not history or any(row["date"] >= cutoff or row["date"] >= issue_date for row in history):
            raise AssertionError(f"Historia no elegible para la emisión {issue_date}.")
        targets = by_date[target_date]
        base_results = [
            predict_one(weekday=target_date.weekday(), period_index=row["hour"], history=history)
            for row in targets
        ]
        for max_leaf_nodes in MAX_LEAF_GRID:
            state = fit_tree_state(
                history=history,
                issue_date=issue_date,
                max_leaf_nodes=max_leaf_nodes,
                lag_days=LAG_DAYS,
                **FIXED_PARAMS,
            )
            predictions = predict_from_tree_state(
                state=state, targets=targets, issue_date=issue_date
            )
            if len(predictions) != len(targets):
                raise AssertionError("El modelo no produjo una fila por objetivo.")
            for target, base, prediction in zip(targets, base_results, predictions):
                if base["prediction"] is None:
                    raise AssertionError("Benchmark sin soporte en un objetivo común.")
                records_by_leaves[max_leaf_nodes].append({
                    "max_leaf_nodes": max_leaf_nodes,
                    "issue_date_local": issue_date.isoformat(),
                    "issue_time_local": "18:00 America/Santiago",
                    "cutoff_exclusive": cutoff.isoformat(),
                    "history_start_date": state["history_start_date"].isoformat(),
                    "history_end_date": state["history_end_date"].isoformat(),
                    "history_rows": state["history_count"],
                    "target_date": target_date.isoformat(),
                    "target_weekday_monday0": target_date.weekday(),
                    "target_period_index": int(target["hour"]),
                    "prediction": prediction["prediction"],
                    "prediction_source": prediction["prediction_source"],
                    "fallback_level": prediction["fallback_level"],
                    "n_support": prediction["n_support"],
                    "benchmark_prediction": str(base["prediction"]),
                    "benchmark_fallback_level": base["fallback_level"],
                    "observed_ex_post": str(target["value"]),
                })
        origin_audit.append({
            "target_date": target_date.isoformat(),
            "issue_date": issue_date.isoformat(),
            "cutoff_exclusive": cutoff.isoformat(),
            "max_history_date": max(row["date"] for row in history).isoformat(),
            "history_rows": len(history),
            "target_periods": len(targets),
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_records = [row for leaf in MAX_LEAF_GRID for row in records_by_leaves[leaf]]
    csv_path = args.output_dir / "predicciones-arboles-potenciados-2024.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_records[0]))
        writer.writeheader()
        writer.writerows(all_records)

    summaries = {}
    for leaves, result_rows in records_by_leaves.items():
        model_metrics = metrics(result_rows, "prediction")
        base_metrics = metrics(result_rows, "benchmark_prediction")
        fallbacks = sum(row["prediction_source"] == "benchmark_fallback" for row in result_rows)
        summaries[str(leaves)] = {
            "tree_model": model_metrics,
            "benchmark_same_targets": base_metrics,
            "mae_delta_model_minus_benchmark": model_metrics["mae"] - base_metrics["mae"],
            "fallback_predictions": fallbacks,
        }
    # Lower MAE wins; ties prefer fewer leaves.
    selected_leaves = min(MAX_LEAF_GRID, key=lambda leaves: (summaries[str(leaves)]["tree_model"]["mae"], leaves))
    model_csv_hash = sha256(MODEL_SOURCE)
    validation_hash = sha256(Path(__file__).resolve())
    summary = {
        "scope": "2024-only development selection; no 2025 read or scoring",
        "target_window": {"start": START.isoformat(), "end": END.isoformat()},
        "issue_time_local": "18:00 America/Santiago on target_date - 1 calendar day",
        "cutoff": "observation_date < issue_date - 60 calendar days; strict date comparison",
        "features": ["one-hot weekday", "one-hot period index 1..24", "annual Fourier sine/cosine first harmonic"],
        "excluded_inputs": ["recent demand lags", "weather", "future observations"],
        "model": "HistGradientBoostingRegressor, squared error, early stopping disabled, random_state=42",
        "max_leaf_grid": list(MAX_LEAF_GRID),
        "fixed_parameters": FIXED_PARAMS,
        "selection_rule": "minimum 2024 development MAE; exact ties prefer fewer leaves",
        "selected_max_leaf_nodes": selected_leaves,
        "development_metrics": summaries,
        "coverage": {
            "target_dates": len(target_dates),
            "target_periods_per_configuration": sum(len(by_date[d]) for d in target_dates),
            "missing_predictions_per_configuration": 0,
            "origins": len(origin_audit),
        },
        "origin_audit": origin_audit,
        "output": {"predictions_csv": csv_path.name},
        "hashes": {
            "input_2024_csv": sha256(input_path),
            "protocol_v1_2": sha256(PROTOCOL),
            "model_implementation": model_csv_hash,
            "validation_script": validation_hash,
        },
        "interpretation": [
            "All metrics are development and model-selection results, not independent performance estimates.",
            "The benchmark is recomputed on exactly the same objectives for each configuration.",
            "No 2025 results were consulted; a predictive improvement does not establish operational acceptability.",
        ],
    }
    summary_path = args.output_dir / "resumen-validacion-arboles-2024.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target_dates": len(target_dates),
        "target_periods_per_configuration": sum(len(by_date[d]) for d in target_dates),
        "selected_max_leaf_nodes": selected_leaves,
        "scores": summaries,
        "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
