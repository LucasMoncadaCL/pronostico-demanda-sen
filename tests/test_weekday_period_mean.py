import unittest
from datetime import date, timedelta
from decimal import Decimal

from src.baselines.weekday_period_mean import predict_one


def row(day: date, hour: int, value: str = "100") -> dict:
    return {"date": day, "hour": hour, "value": Decimal(value)}


class WeeklyPeriodMeanTests(unittest.TestCase):
    def test_primary_weekday_period_mean_requires_five(self):
        history = [row(date(2024, 1, 1) + timedelta(days=7*i), 10, str(100+i)) for i in range(5)]
        result = predict_one(weekday=0, period_index=10, history=history)
        self.assertEqual(result["fallback_level"], "weekday_x_period")
        self.assertEqual(result["n_support"], 5)
        self.assertEqual(result["prediction"], Decimal("102"))

    def test_falls_back_to_period_across_weekdays(self):
        history = [
            row(date(2024, 1, 1) + timedelta(days=i), 10, str(100+i))
            for i in range(5)
        ]
        result = predict_one(weekday=6, period_index=10, history=history)
        self.assertEqual(result["fallback_level"], "period_all_weekdays")
        self.assertEqual(result["n_support"], 5)

    def test_period_25_falls_back_to_weekday_profile(self):
        history = [row(date(2024, 4, 6), 25, "999")]
        history.extend(row(date(2024, 4, 6) - timedelta(days=7*i), h, str(h)) for i in range(1, 6) for h in range(1, 25))
        result = predict_one(weekday=5, period_index=25, history=history)
        self.assertEqual(result["fallback_level"], "weekday_all_periods")
        self.assertGreaterEqual(result["n_support"], 5)
        self.assertNotEqual(result["prediction"], Decimal("999"))

    def test_returns_no_support_when_all_groups_are_small(self):
        history = [row(date(2024, 1, 1), 25, "1"), row(date(2024, 1, 2), 24, "2")]
        result = predict_one(weekday=5, period_index=25, history=history)
        self.assertIsNone(result["prediction"])
        self.assertEqual(result["fallback_level"], "no_support")


if __name__ == "__main__":
    unittest.main()
