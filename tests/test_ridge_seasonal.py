import unittest
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from src.models.ridge_estacional import annual_fourier, design_matrix, predict_date


def row(day: date, hour: int, value: str = "100") -> dict:
    return {"date": day, "hour": hour, "value": Decimal(value)}


class SeasonalRidgeTests(unittest.TestCase):
    def test_january_first_has_same_annual_phase_in_leap_and_common_years(self):
        leap = annual_fourier(date(2024, 1, 1))
        common = annual_fourier(date(2025, 1, 1))
        np.testing.assert_allclose(leap, common)
        self.assertAlmostEqual(leap[0], 0.0)
        self.assertAlmostEqual(leap[1], 1.0)

    def test_design_matrix_contains_two_annual_correction_features(self):
        matrix = design_matrix([row(date(2024, 1, 1), 1), row(date(2024, 1, 2), 24)])
        self.assertEqual(matrix.shape, (2, 2))

    def test_period_25_uses_same_history_benchmark_fallback(self):
        history = []
        for week in range(8):
            day = date(2024, 1, 6) + timedelta(days=7 * week)
            for hour in range(1, 25):
                history.append(row(day, hour, str(100 + hour)))
        history.append(row(date(2024, 2, 24), 25, "999"))
        target = row(date(2024, 5, 4), 25, "0")
        result = predict_date(
            history=history, targets=[target], alpha=1.0, issue_date=date(2024, 5, 3)
        )[0]
        self.assertEqual(result["prediction_source"], "benchmark_fallback")
        self.assertEqual(result["fallback_level"], "weekday_all_periods")
        self.assertNotEqual(result["prediction"], 999.0)

    def test_known_weekday_period_group_uses_ridge(self):
        history = []
        start = date(2024, 1, 1)
        for week in range(8):
            day = start + timedelta(days=7 * week)
            history.extend(row(day, hour, str(100 + hour)) for hour in range(1, 25))
        target = row(date(2024, 5, 6), 10, "0")  # Monday, period 10
        result = predict_date(
            history=history, targets=[target], alpha=1.0, issue_date=date(2024, 5, 5)
        )[0]
        self.assertEqual(result["prediction_source"], "ridge_seasonal")
        self.assertGreaterEqual(result["n_support"], 5)
        self.assertAlmostEqual(result["prediction"], 110.0, delta=10.0)

    def test_target_observed_value_does_not_change_prediction(self):
        history = []
        start = date(2024, 1, 1)
        for week in range(8):
            day = start + timedelta(days=7 * week)
            history.extend(row(day, hour, str(100 + hour + week)) for hour in range(1, 25))
        target_a = row(date(2024, 5, 6), 10, "0")
        target_b = row(date(2024, 5, 6), 10, "999999")
        pred_a = predict_date(
            history=history, targets=[target_a], alpha=10.0, issue_date=date(2024, 5, 5)
        )[0]["prediction"]
        pred_b = predict_date(
            history=history, targets=[target_b], alpha=10.0, issue_date=date(2024, 5, 5)
        )[0]["prediction"]
        self.assertAlmostEqual(pred_a, pred_b, places=10)

    def test_rejects_history_on_or_after_exclusive_cutoff(self):
        history = [row(date(2024, 3, 6), hour) for hour in range(1, 25)]
        target = row(date(2024, 5, 6), 10)
        with self.assertRaisesRegex(ValueError, "corte exclusivo"):
            predict_date(
                history=history, targets=[target], alpha=10.0, issue_date=date(2024, 5, 5)
            )

    def test_rejects_target_other_than_next_calendar_day(self):
        history = [row(date(2024, 1, 1) + timedelta(days=7 * week), hour)
                   for week in range(8) for hour in range(1, 25)]
        target = row(date(2024, 5, 7), 10)
        with self.assertRaisesRegex(ValueError, "día calendario siguiente"):
            predict_date(
                history=history, targets=[target], alpha=10.0, issue_date=date(2024, 5, 5)
            )


if __name__ == "__main__":
    unittest.main()
