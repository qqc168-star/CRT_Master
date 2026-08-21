import unittest

from crt_radar.private_profile import validate_private_profile


class PrivateProfileStrategyTest(unittest.TestCase):
    def test_strc_tactical_strategy_is_carried_as_non_formal_private_context(self) -> None:
        payload = {
            "schema_version": "CRT_PRIVATE_PORTFOLIO_V1",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
            "strc": {
                "shares": 100,
                "current_annual_distribution_rate": 0.12,
                "stated_amount_usd": 100,
                "withholding_rate": 0.0,
                "distribution_rate_mode": "DYNAMIC_LOCAL_VALUE",
                "tax_treatment": "RETURN_OF_CAPITAL",
                "tactical_strategy": {
                    "strategy_id": "CRT_STRC_Q3Q4_ROLLING_STRATEGY_V0.2",
                    "strategy_status": "ACTIVE_STRATEGY_HYPOTHESIS",
                    "formal_model_status": "NON_FORMAL",
                    "q3_sell_tranches": [
                        {"weight": 0.20, "target_price_usd": 97.50},
                        {"weight": 0.50, "target_price_usd": 98.90},
                        {"weight": 0.30, "target_price_usd": 99.80},
                    ],
                    "q4_reentry_tranches": [
                        {"weight": 0.20, "max_price_usd": 86.00},
                        {"weight": 0.30, "max_price_usd": 83.00},
                        {"weight": 0.50, "max_price_usd": 80.00},
                    ],
                    "net_spread_floor_usd": 10.0,
                },
            },
            "cash_goal": {"six_month_target_usd": 1500, "fixed_minimum_shares": 80},
        }

        result = validate_private_profile(payload)
        strategy = result["strc"]["tactical_strategy"]

        self.assertEqual(strategy["formal_model_status"], "NON_FORMAL")
        self.assertEqual(strategy["derived"]["weighted_q3_sell_price_usd"], 98.89)
        self.assertEqual(strategy["derived"]["weighted_q4_reentry_price_usd"], 82.1)
        self.assertEqual(strategy["derived"]["net_spread_floor_usd"], 10.0)
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertEqual(result["action_output"], "NONE")


if __name__ == "__main__":
    unittest.main()
