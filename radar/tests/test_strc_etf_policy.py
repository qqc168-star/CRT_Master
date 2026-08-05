from datetime import datetime
from pathlib import Path
import unittest

from devtools.strc_etf_policy import (
    assess_snapshot,
    load_policy,
    schedule_action,
    validate_policy,
)


class StrcEtfPolicyTests(unittest.TestCase):
    @staticmethod
    def policy():
        return load_policy(
            Path(__file__).resolve().parents[1]
            / "config"
            / "strc_etf_holdings_policy.json"
        )

    @staticmethod
    def aligned_snapshot():
        return {
            "aggregate_requested": True,
            "new_material_change": False,
            "funds": {
                fund: {
                    "as_of_date": "2026-08-04",
                    "usable_source_count": 2,
                    "trading_day_lag": 1,
                    "identity_method": "EXACT_TICKER",
                    "same_date_source_conflict": False,
                }
                for fund in ("PFF", "PFFA", "PFXF")
            },
        }

    def test_policy_validates(self):
        validate_policy(self.policy())

    def test_primary_scan_runs_at_0830(self):
        self.assertEqual(
            schedule_action(
                datetime(2026, 8, 6, 8, 30),
                is_us_trading_day=True,
                primary_scan_has_new_usable_data=False,
            ),
            "RUN_PRIMARY",
        )

    def test_1300_retry_is_conditional(self):
        self.assertEqual(
            schedule_action(
                datetime(2026, 8, 6, 13, 0),
                is_us_trading_day=True,
                primary_scan_has_new_usable_data=True,
            ),
            "SKIP_RETRY_ALREADY_COMPLETE",
        )

        self.assertEqual(
            schedule_action(
                datetime(2026, 8, 6, 13, 0),
                is_us_trading_day=True,
                primary_scan_has_new_usable_data=False,
            ),
            "RUN_CONDITIONAL_RETRY",
        )

    def test_non_trading_day_is_skipped(self):
        self.assertEqual(
            schedule_action(
                datetime(2026, 8, 8, 8, 30),
                is_us_trading_day=False,
                primary_scan_has_new_usable_data=False,
            ),
            "SKIP_NON_TRADING_DAY",
        )

    def test_one_trading_day_delay_is_silent(self):
        snapshot = self.aligned_snapshot()
        snapshot["funds"]["PFF"]["usable_source_count"] = 0
        snapshot["funds"]["PFF"]["trading_day_lag"] = 1

        result = assess_snapshot(snapshot)

        self.assertEqual(result.status, "NO_ALERT")
        self.assertFalse(result.notify)

    def test_over_two_trading_days_is_blocked(self):
        snapshot = self.aligned_snapshot()
        snapshot["funds"]["PFF"]["usable_source_count"] = 0
        snapshot["funds"]["PFF"]["trading_day_lag"] = 3

        result = assess_snapshot(snapshot)

        self.assertEqual(result.status, "BLOCKED_ALERT")
        self.assertTrue(result.notify)

    def test_issuer_only_identity_is_blocked(self):
        snapshot = self.aligned_snapshot()
        snapshot["funds"]["PFFA"]["identity_method"] = "ISSUER_ONLY"

        self.assertEqual(
            assess_snapshot(snapshot).status,
            "BLOCKED_ALERT",
        )

    def test_different_dates_cannot_be_aggregated(self):
        snapshot = self.aligned_snapshot()
        snapshot["funds"]["PFXF"]["as_of_date"] = "2026-08-01"

        result = assess_snapshot(snapshot)

        self.assertEqual(result.status, "BLOCKED_ALERT")
        self.assertFalse(result.aggregate_allowed)

    def test_same_date_source_conflict_is_blocked(self):
        snapshot = self.aligned_snapshot()
        snapshot["funds"]["PFF"]["same_date_source_conflict"] = True

        self.assertEqual(
            assess_snapshot(snapshot).status,
            "BLOCKED_ALERT",
        )

    def test_material_change_notifies(self):
        snapshot = self.aligned_snapshot()
        snapshot["new_material_change"] = True

        result = assess_snapshot(snapshot)

        self.assertEqual(result.status, "MATERIAL_CHANGE")
        self.assertTrue(result.notify)


if __name__ == "__main__":
    unittest.main()
