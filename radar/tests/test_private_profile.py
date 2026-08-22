import copy
import unittest

from crt_radar.private_profile import (
    PrivateProfileError,
    validate_private_profile,
)


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


def capital_state_payload() -> dict:
    return {
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
        },
        "cash_goal": {
            "six_month_target_usd": 1500,
            "fixed_minimum_shares": 80,
        },
        "capital_state": {
            "contract_version": "CRT_CAPITAL_STATE_V0.1",
            "as_of": "2026-08-22T22:20:00+08:00",
            "source": "USER_CONFIRMED",
            "base_currency": "USD",
        },
        "holdings": [
            {"asset": "STRC", "quantity": 100},
            {"asset": "BTC", "quantity": 0.25},
        ],
        "cash": {
            "available_usd": 4500,
            "reserved_usd": 500,
        },
        "asset_roles": {
            "STRC": "INCOME_ENGINE",
            "BTC": "CAPITAL_CORE_DIRECTION",
        },
        "plans": [
            {
                "plan_id": "BTC_THREE_TRANCHE_ENTRY",
                "asset": "BTC",
                "side": "BUY",
                "status": "ACTIVE",
                "tranches": [
                    {
                        "tranche_id": "T1",
                        "budget_usd": 1000,
                        "status": "PENDING",
                        "validity_conditions": [
                            {
                                "field": "btc_spot_price_usd",
                                "operator": "LTE",
                                "value": 70000,
                            }
                        ],
                    },
                    {
                        "tranche_id": "T2",
                        "budget_usd": 1500,
                        "status": "PENDING",
                        "validity_conditions": [
                            {
                                "field": "btc_spot_price_usd",
                                "operator": "LTE",
                                "value": 65000,
                            }
                        ],
                    },
                    {
                        "tranche_id": "T3",
                        "budget_usd": 2000,
                        "status": "PENDING",
                        "validity_conditions": [
                            {
                                "field": "btc_spot_price_usd",
                                "operator": "LTE",
                                "value": 60000,
                            }
                        ],
                    },
                ],
            }
        ],
    }


class CapitalStateProfileContractTest(unittest.TestCase):
    def test_legacy_private_profile_remains_available_but_capital_state_is_blocked(self) -> None:
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
            },
            "cash_goal": {
                "six_month_target_usd": 1500,
                "fixed_minimum_shares": 80,
            },
        }

        result = validate_private_profile(payload)

        self.assertEqual(
            result["capital_state_status"]["state"],
            "BLOCKED",
        )
        self.assertEqual(
            result["capital_state_status"]["reason"],
            "CAPITAL_STATE_MISSING",
        )
        self.assertEqual(
            result["external_action_authority"],
            "NONE",
        )

    def test_user_confirmed_capital_state_is_validated_and_normalized(self) -> None:
        result = validate_private_profile(
            capital_state_payload()
        )

        status = result["capital_state_status"]

        self.assertEqual(status["state"], "AVAILABLE")
        self.assertEqual(
            status["contract_version"],
            "CRT_CAPITAL_STATE_V0.1",
        )
        self.assertEqual(status["holding_count"], 2)
        self.assertEqual(status["plan_count"], 1)
        self.assertEqual(status["pending_tranche_count"], 3)
        self.assertEqual(status["pending_budget_usd"], 4500.0)
        self.assertEqual(status["available_cash_usd"], 4500.0)
        self.assertEqual(
            result["plans"][0]["tranches"][0]["status"],
            "PENDING",
        )
        self.assertEqual(
            result["external_action_authority"],
            "NONE",
        )
        self.assertEqual(result["action_output"], "NONE")

    def test_partial_capital_state_is_rejected_fail_closed(self) -> None:
        payload = capital_state_payload()
        del payload["plans"]

        with self.assertRaises(PrivateProfileError):
            validate_private_profile(payload)

    def test_strc_holding_must_match_legacy_strc_shares(self) -> None:
        payload = capital_state_payload()
        payload["holdings"][0]["quantity"] = 99

        with self.assertRaises(PrivateProfileError):
            validate_private_profile(payload)

    def test_capital_state_source_must_be_user_confirmed(self) -> None:
        payload = capital_state_payload()
        payload["capital_state"]["source"] = "INFERRED"

        with self.assertRaises(PrivateProfileError):
            validate_private_profile(payload)

    def test_three_tranche_contract_is_required(self) -> None:
        payload = capital_state_payload()
        payload["plans"][0]["tranches"].pop()

        with self.assertRaises(PrivateProfileError):
            validate_private_profile(payload)



if __name__ == "__main__":
    unittest.main()
