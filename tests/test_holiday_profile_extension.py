import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from src.models.holiday_profile_extension import predict_with_holiday_profile


ROOT = Path(__file__).resolve().parents[1]


def history_row(day, hour, value):
    return {"date": day, "hour": hour, "value": Decimal(str(value))}


class HolidayProfileExtensionTests(unittest.TestCase):
    def setUp(self):
        first_sunday = date(2024, 1, 7)
        self.history = [
            history_row(first_sunday + timedelta(days=7 * i), 1, 80 + i)
            for i in range(5)
        ]
        first_wednesday = date(2024, 1, 3)
        self.history += [
            history_row(first_wednesday + timedelta(days=7 * i), 1, 100 + i)
            for i in range(5)
        ]
        self.candidate_dates = {date(2025, 1, 1)}

    def test_weekday_holiday_uses_sunday_same_period_with_existing_support_rule(self):
        result = predict_with_holiday_profile(
            target_date=date(2025, 1, 1),
            period_index=1,
            benchmark_prediction=Decimal("999"),
            fixed_history=self.history,
            candidate_holiday_dates=self.candidate_dates,
        )
        self.assertEqual(result["prediction"], Decimal("82"))
        self.assertEqual(result["profile"], "sunday_x_period")
        self.assertEqual(result["fallback_level"], "weekday_x_period")
        self.assertEqual(result["n_support"], 5)
        self.assertTrue(result["holiday_substitution_applied"])

    def test_nonholiday_prediction_is_returned_unchanged(self):
        benchmark = Decimal("123.456789")
        result = predict_with_holiday_profile(
            target_date=date(2025, 1, 2),
            period_index=1,
            benchmark_prediction=benchmark,
            fixed_history=self.history,
            candidate_holiday_dates=self.candidate_dates,
        )
        self.assertIs(result["prediction"], benchmark)
        self.assertFalse(result["holiday_substitution_applied"])

    def test_weekend_date_is_never_changed_even_if_erroneously_listed(self):
        benchmark = Decimal("321")
        result = predict_with_holiday_profile(
            target_date=date(2025, 1, 4),
            period_index=1,
            benchmark_prediction=benchmark,
            fixed_history=self.history,
            candidate_holiday_dates={date(2025, 1, 4)},
        )
        self.assertEqual(result["prediction"], benchmark)
        self.assertFalse(result["holiday_substitution_applied"])

    def test_regional_holiday_and_blackout_dates_remain_unchanged(self):
        for target in (date(2025, 6, 7), date(2025, 8, 20), date(2025, 2, 25), date(2025, 2, 26)):
            benchmark = Decimal("654.321")
            result = predict_with_holiday_profile(
                target_date=target,
                period_index=1,
                benchmark_prediction=benchmark,
                fixed_history=self.history,
                candidate_holiday_dates=self.candidate_dates,
            )
            self.assertEqual(result["prediction"], benchmark, target.isoformat())
            self.assertFalse(result["holiday_substitution_applied"], target.isoformat())

    def test_period_index_is_used_without_conversion(self):
        sunday = date(2024, 1, 7)
        h25 = [history_row(sunday + timedelta(days=7 * i), 25, 900 + i) for i in range(5)]
        result = predict_with_holiday_profile(
            target_date=date(2025, 1, 1),
            period_index=25,
            benchmark_prediction=Decimal("1"),
            fixed_history=h25,
            candidate_holiday_dates=self.candidate_dates,
        )
        self.assertEqual(result["prediction"], Decimal("902"))
        self.assertEqual(result["fallback_level"], "weekday_x_period")

    def test_holiday_without_any_supported_profile_fails_instead_of_fabricating(self):
        with self.assertRaises(ValueError):
            predict_with_holiday_profile(
                target_date=date(2025, 1, 1),
                period_index=25,
                benchmark_prediction=Decimal("1"),
                fixed_history=[history_row(date(2024, 1, 1), 25, 50)],
                candidate_holiday_dates=self.candidate_dates,
            )

    def test_frozen_calendar_is_mechanical_and_excludes_elections_and_regional_days(self):
        calendar_path = ROOT / "docs/protocol/calendario-feriados-nacionales-2025.json"
        calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
        national_weekdays = {
            date.fromisoformat(item["date"])
            for item in calendar["national_holidays"]
            if item["class"] == "national_holiday" and date.fromisoformat(item["date"]).weekday() < 5
        }
        frozen = {date.fromisoformat(value) for value in calendar["included_candidate_dates"]}
        self.assertEqual(national_weekdays, frozen)
        self.assertEqual(len(frozen), 12)
        self.assertNotIn(date(2025, 6, 29), frozen)
        self.assertNotIn(date(2025, 11, 16), frozen)
        self.assertNotIn(date(2025, 12, 14), frozen)
        self.assertNotIn(date(2025, 6, 7), frozen)
        self.assertNotIn(date(2025, 8, 20), frozen)


if __name__ == "__main__":
    unittest.main()
