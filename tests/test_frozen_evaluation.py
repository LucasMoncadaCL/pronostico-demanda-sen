import unittest
from datetime import date, timedelta
from decimal import Decimal

from src.evaluation.evaluar_benchmark_2025 import make_predictions, score


def row(d, h, v):
    return {"date": d, "hour": h, "value": Decimal(str(v))}


class FrozenEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.target_date = date(2024, 4, 6)  # Synthetic development-only fixture.
        self.issue_date = self.target_date - timedelta(days=1)
        self.history = [row(date(2024, 1, 6) + timedelta(days=7*i), 1, 100+i) for i in range(5)]
        # Additional period-25 examples are deliberately sparse; fallback must be flagged.
        self.history.append(row(date(2024, 1, 6), 25, 999))
        self.target = [row(self.target_date, 25, 125)]

    def test_fixed_2024_policy_uses_only_records_before_issue_cut(self):
        predictions = make_predictions(self.target, self.history, "primary_60d_fixed_2024")
        self.assertEqual(len(predictions), 1)
        p = predictions[0]
        self.assertEqual(p["fallback_level"], "weekday_all_periods")
        self.assertEqual(p["history_end_date"], "2024-02-03")
        self.assertEqual(p["cutoff_date_exclusive"], "2024-02-05")

    def test_sensitivity_policy_excludes_issue_date(self):
        history = self.history + [row(self.issue_date, 1, 5000)]
        predictions = make_predictions(self.target, history, "sensitivity_no_lag_updated_history")
        self.assertEqual(len(predictions), 1)
        self.assertLess(date.fromisoformat(predictions[0]["history_end_date"]), self.issue_date)

    def test_score_uses_prediction_minus_observed_convention(self):
        result = score([{"prediction": Decimal("12"), "observed": Decimal("10")}])
        self.assertEqual(result["mae"], "2")
        self.assertEqual(result["bias_prediction_minus_observed"], "2")


if __name__ == "__main__":
    unittest.main()
