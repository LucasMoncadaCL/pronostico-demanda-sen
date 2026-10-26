import unittest
from datetime import date

from src.evaluation.benchmark_policy import cutoff_date, eligible_history, frozen_2024_snapshot


class BenchmarkPolicyTests(unittest.TestCase):
    def test_cutoff_is_calendar_date_and_exclusive(self):
        issue = date(2024, 4, 5)
        self.assertEqual(cutoff_date(issue, 60), date(2024, 2, 5))
        rows = [{"date": date(2024, 2, d)} for d in (4, 5, 6)]
        self.assertEqual([r["date"] for r in eligible_history(rows, issue, 60)], [date(2024, 2, 4)])

    def test_no_lag_still_excludes_observations_on_issue_date(self):
        issue = date(2025, 4, 4)
        rows = [{"date": date(2025, 4, d)} for d in (3, 4, 5)]
        self.assertEqual([r["date"] for r in eligible_history(rows, issue, 0)], [date(2025, 4, 3)])

    def test_frozen_first_2025_snapshot_ends_october_31(self):
        rows = [{"date": date(2024, 10, 31)}, {"date": date(2024, 11, 1)}, {"date": date(2024, 12, 30)}, {"date": date(2025, 1, 1)}]
        snapshot = frozen_2024_snapshot(rows, date(2024, 12, 31), 60)
        self.assertEqual([r["date"] for r in snapshot], [date(2024, 10, 31)])


if __name__ == "__main__":
    unittest.main()
