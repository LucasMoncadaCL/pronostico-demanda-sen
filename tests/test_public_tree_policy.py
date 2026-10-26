import unittest

from scripts.verify_public_tree import find_policy_violations, tracked_paths


class PublicTreePolicyTests(unittest.TestCase):
    def test_current_tracked_public_tree_passes(self):
        self.assertEqual(find_policy_violations(tracked_paths()), [])

    def test_rejects_data_files_and_reserved_locations(self):
        paths = [
            "data/raw/demand.json",
            "data/audits/2025/metrics.csv",
            "archive/source-data.zip",
            "src/evaluation/observations.parquet",
            "reports/paired-predictions.xlsx",
        ]
        violations = find_policy_violations(paths)
        self.assertTrue(all(path in " ".join(violations) for path in paths))
        self.assertTrue(all(path in " ".join(violations) for path in paths))

    def test_allows_documented_protocol_json_and_code(self):
        paths = [
            "data/README.md",
            "docs/protocol/calendar.json",
            "src/models/example.py",
        ]
        self.assertEqual(find_policy_violations(paths), [])


if __name__ == "__main__":
    unittest.main()
