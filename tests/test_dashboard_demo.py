import unittest

from dashboard.data_access import daily_metrics, load_demo_data


class DashboardDemoTests(unittest.TestCase):
    def test_demo_is_deterministic_and_has_full_synthetic_calendar(self):
        first = load_demo_data()
        second = load_demo_data()

        self.assertEqual(len(first), 365 * 24)
        self.assertEqual(first["target_date"].min().strftime("%Y-%m-%d"), "2030-01-01")
        self.assertEqual(first["target_date"].max().strftime("%Y-%m-%d"), "2030-12-31")
        self.assertTrue(first.equals(second))

    def test_daily_summary_uses_only_fictional_demo_rows(self):
        data = load_demo_data()
        summary = daily_metrics(data)

        self.assertEqual(len(summary), 365)
        self.assertEqual(summary["target_date"].nunique(), 365)
        self.assertTrue(summary[["benchmark_mae", "candidate_mae"]].notna().all().all())


if __name__ == "__main__":
    unittest.main()
