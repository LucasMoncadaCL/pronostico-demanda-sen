"""Independent audit of the 2024-only development predictions and issue cutoffs."""
from __future__ import annotations
import csv
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from src.baselines.weekday_period_mean import predict_one
from src.evaluation.benchmark_policy import eligible_history

DATA = REPO_ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
PRED = REPO_ROOT / "data/audits/2024-demanda-sistemica/benchmark-validacion-2024/predicciones-benchmark-2024.csv"
START, END = date(2024, 4, 6), date(2024, 10, 31)
LAG = 60


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    source = {}
    for row in read_csv(DATA):
        d = date.fromisoformat(row["fecha"])
        source[(d, int(row["hora"]))] = Decimal(row["demanda"])
    predictions = read_csv(PRED)
    keys = [(date.fromisoformat(r["target_date"]), int(r["target_period_index"])) for r in predictions]
    assert len(keys) == len(set(keys)), "Duplicate prediction target key."
    assert len(predictions) == len(source_keys := [k for k in source if START <= k[0] <= END]), "Prediction count differs from eligible target count."
    source_targets = {k: v for k, v in source.items() if START <= k[0] <= END}
    assert set(keys) == set(source_targets), "Predictions do not cover exactly the 2024 development target keys."
    by_date = {}
    for row in read_csv(DATA):
        d = date.fromisoformat(row["fecha"])
        by_date.setdefault(d, []).append({"date": d, "hour": int(row["hora"]), "value": Decimal(row["demanda"])})

    for row in predictions:
        target_date = date.fromisoformat(row["target_date"])
        issue_date = date.fromisoformat(row["issue_date_local"])
        cutoff = date.fromisoformat(row["cutoff_date_exclusive"])
        expected_issue = target_date - timedelta(days=1)
        expected_cutoff = expected_issue - timedelta(days=LAG)
        assert START <= target_date <= END
        assert issue_date == expected_issue
        assert row["issue_time_local"] == "18:00 America/Santiago"
        assert cutoff == expected_cutoff
        history = eligible_history([r for group in by_date.values() for r in group], issue_date, LAG)
        assert all(r["date"] < cutoff and r["date"] < issue_date for r in history)
        assert len(history) == int(row["history_rows"])
        assert max(r["date"] for r in history).isoformat() == row["max_history_observation_date"]
        target_key = (target_date, int(row["target_period_index"]))
        assert Decimal(row["observed_ex_post"]) == source_targets[target_key]
        result = predict_one(weekday=target_date.weekday(), period_index=target_key[1], history=history)
        assert result["prediction"] is not None
        assert Decimal(row["prediction"]) == result["prediction"]
        assert row["fallback_level"] == result["fallback_level"]
        assert int(row["n_support"]) == result["n_support"]

    print(f"PASS: {len(predictions)} predictions; exact target coverage; each issue/cutoff/history/fallback recomputed and matched; targets {START}..{END} only.")


if __name__ == "__main__":
    main()
