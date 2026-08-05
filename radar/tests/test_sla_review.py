from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.sla_review import build_sla_review


class SLAReviewTests(unittest.TestCase):
    @staticmethod
    def summary(index: int, *, passed=True):
        return {
            "run_id": f"run-{index:02d}",
            "duration_ms": 86_400_000 + index * 1000,
            "minimum_observed_coverage_ratio": 0.99,
            "blocked_snapshot_count": 0 if passed else 1,
            "acceptance_failures": [] if passed else ["BLOCKED_SNAPSHOT_PRESENT"],
            "process_stop_outcomes": ["COMPLETED"],
        }

    def test_review_pending_before_twenty_passed_runs(self):
        review = build_sla_review([self.summary(i) for i in range(10)])
        self.assertEqual(review["decision"], "MATURITY_REVIEW_PENDING")
        self.assertEqual(review["passed_runs"], 10)
        self.assertEqual(review["required_runs"], 20)
        self.assertEqual(review["external_action_authority"], "NONE")

    def test_ready_for_review_at_twenty_passed_runs(self):
        review = build_sla_review([self.summary(i) for i in range(20)])
        self.assertEqual(review["decision"], "READY_FOR_MATURITY_REVIEW")
        self.assertEqual(review["passed_runs"], 20)
        self.assertEqual(review["promotion_authority"], "USER_EXPLICIT_APPROVAL_REQUIRED")
        self.assertEqual(len(review["review_hash"]), 64)

    def test_failed_run_does_not_count_as_passed(self):
        rows = [self.summary(i) for i in range(20)] + [self.summary(20, passed=False)]
        review = build_sla_review(rows)
        self.assertEqual(review["observed_runs"], 21)
        self.assertEqual(review["passed_runs"], 20)
        self.assertEqual(review["failed_runs"], 1)
        self.assertIn("run-20", review["failed_run_ids"])

    def test_duplicate_run_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            build_sla_review([self.summary(1), self.summary(1)])

    def test_percentiles_are_reported(self):
        review = build_sla_review([self.summary(i) for i in range(5)])
        self.assertIsNotNone(review["elapsed_s"]["p50"])
        self.assertIsNotNone(review["elapsed_s"]["p90"])
        self.assertAlmostEqual(review["minimum_coverage_ratio"]["min"], 0.99)


if __name__ == "__main__":
    unittest.main(verbosity=2)
