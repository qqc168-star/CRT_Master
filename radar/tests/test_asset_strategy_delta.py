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

    def test_historical_derived_cannot_qualify_current_income(self):
        result = build_asset_strategy_delta(
            btc_entry_gate={"transition_state": "TRANSITION_UNRESOLVED", "decision_eligibility": "WAIT"},
            assumption_watch={"state": "VALID"},
            private_context=self.private_context,
        )
        income = result["income_engine"]
        self.assertIsNone(income["coverage_ratio"])
        self.assertEqual(income["legacy_strc_derived"]["six_month_cash_usd"], 1643.4)
        self.assertEqual(result["assets"]["STRC"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")
        self.assertEqual(result["assets"]["SATA"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")

    def test_bull_probe_strengthens_growth_direction_but_mstr_and_asst_remain_blocked(self):
        result = build_asset_strategy_delta(
            btc_entry_gate={
                "transition_state": "BULL_ACCEPTANCE_STRENGTHENED",
                "decision_eligibility": "PROBE_ELIGIBLE",
                "control_transfer_validation": {
                    "control_transfer_loop_closed": True,
                },
            },
            assumption_watch={"state": "CHALLENGED"},
            private_context=self.private_context,
        )
        self.assertEqual(result["assets"]["BTC"]["decision_support"], "PROBE_ELIGIBLE")
        self.assertEqual(result["assets"]["MSTR"]["decision_support"], "BLOCKED")
        self.assertEqual(result["assets"]["ASST"]["decision_support"], "BLOCKED")
        self.assertIn("MNAV", " ".join(result["assets"]["MSTR"]["blocked_reasons"]))
        self.assertIn("DILUTION", " ".join(result["assets"]["ASST"]["blocked_reasons"]))

    def test_probe_without_closed_control_transfer_loop_is_downgraded(self):
        result = build_asset_strategy_delta(
            btc_entry_gate={
                "transition_state": "BULL_ACCEPTANCE_STRENGTHENED",
                "decision_eligibility": "PROBE_ELIGIBLE",
            },
            assumption_watch={"state": "CHALLENGED"},
            private_context=self.private_context,
        )
        self.assertEqual(result["raw_btc_decision_eligibility"], "PROBE_ELIGIBLE")
        self.assertEqual(result["btc_decision_eligibility"], "WATCH")
        self.assertEqual(result["assets"]["BTC"]["decision_support"], "WATCH")
        self.assertEqual(result["assets"]["BTC"]["strategy_delta"], "STRENGTHEN_WATCH")

    def test_bear_rejection_weakens_growth_direction(self):
        result = build_asset_strategy_delta(
            btc_entry_gate={"transition_state": "BEAR_REJECTION_STRENGTHENED", "decision_eligibility": "WAIT"},
            assumption_watch={"state": "VALID"},
            private_context=self.private_context,
        )
        self.assertEqual(result["assets"]["MSTR"]["strategy_delta"], "WEAKEN")
        self.assertEqual(result["assets"]["ASST"]["strategy_delta"], "WEAKEN")

    def test_historical_goal_cannot_create_current_gap_or_trade(self):
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
        self.assertIsNone(result["income_engine"]["income_goal"]["gap_usd"])
        self.assertEqual(result["assets"]["STRC"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")
        self.assertEqual(result["assets"]["SATA"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
