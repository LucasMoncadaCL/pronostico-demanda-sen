import unittest
from datetime import date, timedelta
from decimal import Decimal

from src.baselines.weekday_period_mean import predict_one
from src.models.arboles_potenciados import (
    feature_matrix,
    fit_tree_state,
    predict_date,
    predict_from_tree_state,
)


def row(day: date, hour: int, value: str = "100") -> dict:
    return {"date": day, "hour": hour, "value": Decimal(value)}


class BoostedTreeTests(unittest.TestCase):
    def test_calendar_features_are_fixed_width_and_categorical(self):
        rows = [row(date(2024, 1, 1), 1), row(date(2024, 1, 2), 24)]
        matrix = feature_matrix(rows)
        self.assertEqual(matrix.shape, (2, 7 + 24 + 2))
        self.assertEqual(matrix[0, :7].sum(), 1.0)
        self.assertEqual(matrix[0, 7:31].sum(), 1.0)

    def test_period_25_uses_benchmark_fallback(self):
        history = [
            row(date(2024, 1, 6) + timedelta(days=7 * week), hour, str(100 + hour))
            for week in range(8) for hour in range(1, 25)
        ]
        history.append(row(date(2024, 2, 24), 25, "999"))
        target = row(date(2024, 5, 4), 25, "0")
        result = predict_date(
            history=history, targets=[target], issue_date=date(2024, 5, 3), max_leaf_nodes=7
        )[0]
        self.assertEqual(result["prediction_source"], "benchmark_fallback")

    def test_fallback_uses_exact_eligible_history_that_fit_model(self):
        history = [
            row(date(2024, 1, 6) + timedelta(days=7 * week), hour, str(100 + hour + week))
            for week in range(8) for hour in range(1, 25)
        ]
        target = row(date(2024, 5, 4), 25, "0")
        issue_date = date(2024, 5, 3)
        state = fit_tree_state(
            history=history, issue_date=issue_date, max_leaf_nodes=7, max_iter=2
        )
        result = predict_from_tree_state(state=state, targets=[target], issue_date=issue_date)[0]
        expected = predict_one(weekday=5, period_index=25, history=history)["prediction"]
        self.assertEqual(result["prediction"], float(expected))
        self.assertEqual(list(state["eligible_history"]), history)

    def test_rejects_history_on_or_after_exclusive_cutoff(self):
        history = [row(date(2024, 3, 6), hour) for hour in range(1, 25)]
        target = row(date(2024, 5, 6), 10)
        with self.assertRaisesRegex(ValueError, "corte exclusivo"):
            predict_date(
                history=history, targets=[target], issue_date=date(2024, 5, 5), max_leaf_nodes=7
            )

    def test_target_observed_value_does_not_change_prediction(self):
        history = [
            row(date(2024, 1, 1) + timedelta(days=i), hour, str(100 + hour + i % 5))
            for i in range(60) for hour in range(1, 25)
        ]
        target_a = row(date(2024, 5, 6), 10, "0")
        target_b = row(date(2024, 5, 6), 10, "999999")
        p_a = predict_date(
            history=history, targets=[target_a], issue_date=date(2024, 5, 5), max_leaf_nodes=7
        )[0]["prediction"]
        p_b = predict_date(
            history=history, targets=[target_b], issue_date=date(2024, 5, 5), max_leaf_nodes=7
        )[0]["prediction"]
        self.assertAlmostEqual(p_a, p_b, places=10)


if __name__ == "__main__":
    unittest.main()
