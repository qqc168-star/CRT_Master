from __future__ import annotations

import unittest

from crt_radar.asset_strategy_delta import build_asset_strategy_delta


class AssetStrategyDeltaTests(unittest.TestCase):
    def setUp(self):
        self.private_context = {
            "state": "AVAILABLE",
            "profile": {
                "cash_goal": {"six_month_target_usd": 1500.0},
                "derived": {
                    "six_month_cash_usd": 1643.4,
                    "goal_covered_at_current_rate": True,
                },
            },
        }

    def test_income_engine_quantifies_coverage(self):
        result = build_asset_strategy_delta(
            btc_entry_gate={"transition_state": "TRANSITION_UNRESOLVED", "decision_eligibility": "WAIT"},
            assumption_watch={"state": "VALID"},
            private_context=self.private_context,
        )
        income = result["income_engine"]
        self.assertAlmostEqual(income["coverage_ratio"], 1643.4 / 1500.0)
        self.assertEqual(result["assets"]["STRC"]["strategy_delta"], "KEEP_INCOME_CORE")
        self.assertEqual(result["assets"]["SATA"]["strategy_delta"], "WAIT_AS_INCOME_BACKUP")

    def test_bull_probe_strengthens_growth_direction_but_mstr_and_asst_remain_blocked(self):
        result = build_asset_strategy_delta(
            btc_entry_gate={"transition_state": "BULL_ACCEPTANCE_STRENGTHENED", "decision_eligibility": "PROBE_ELIGIBLE"},
            assumption_watch={"state": "CHALLENGED"},
            private_context=self.private_context,
        )
        self.assertEqual(result["assets"]["BTC"]["decision_support"], "PROBE_ELIGIBLE")
        self.assertEqual(result["assets"]["MSTR"]["decision_support"], "BLOCKED")
        self.assertEqual(result["assets"]["ASST"]["decision_support"], "BLOCKED")
        self.assertIn("MNAV", " ".join(result["assets"]["MSTR"]["blocked_reasons"]))
        self.assertIn("DILUTION", " ".join(result["assets"]["ASST"]["blocked_reasons"]))

    def test_bear_rejection_weakens_growth_direction(self):
        result = build_asset_strategy_delta(
            btc_entry_gate={"transition_state": "BEAR_REJECTION_STRENGTHENED", "decision_eligibility": "WAIT"},
            assumption_watch={"state": "VALID"},
            private_context=self.private_context,
        )
        self.assertEqual(result["assets"]["MSTR"]["strategy_delta"], "WEAKEN")
        self.assertEqual(result["assets"]["ASST"]["strategy_delta"], "WEAKEN")

    def test_income_gap_routes_to_review_not_trade(self):
        private = {
            "state": "AVAILABLE",
            "profile": {
                "cash_goal": {"six_month_target_usd": 1500.0},
                "derived": {"six_month_cash_usd": 1200.0, "goal_covered_at_current_rate": False},
            },
        }
        result = build_asset_strategy_delta(
            btc_entry_gate={"transition_state": "TRANSITION_UNRESOLVED", "decision_eligibility": "WAIT"},
            assumption_watch={"state": "VALID"},
            private_context=private,
        )
        self.assertEqual(result["assets"]["STRC"]["strategy_delta"], "INCOME_GAP_REVIEW")
        self.assertEqual(result["assets"]["SATA"]["strategy_delta"], "INCOME_BACKUP_REVIEW")
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
