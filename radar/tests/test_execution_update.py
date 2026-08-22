from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crt_radar.execution_update import (
    ExecutionUpdateError,
    apply_execution_update_file,
    apply_user_confirmed_execution,
)


def profile_payload(
    *,
    asset: str = "MSTR",
    side: str = "BUY",
) -> dict:
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
            "as_of": "2026-08-23T00:30:00+08:00",
            "source": "USER_CONFIRMED",
            "base_currency": "USD",
        },
        "holdings": [
            {
                "asset": "STRC",
                "quantity": 100,
            },
            {
                "asset": "MSTR",
                "quantity": 10,
            },
        ],
        "cash": {
            "available_usd": 4500,
            "reserved_usd": 180,
            "exact_amount_confirmed": False,
        },
        "asset_roles": {
            "STRC": "INCOME_ENGINE",
            "MSTR": "ATTACK_CAPITAL",
            "USD": "ATTACK_CAPITAL_RESERVE",
        },
        "plans": [
            {
                "plan_id": "PLAN_1",
                "asset": asset,
                "side": side,
                "status": "ACTIVE",
                "tranches": [
                    {
                        "tranche_id": "T1",
                        "budget_usd": 1500,
                        "status": "PENDING",
                        "validity_conditions": [
                            {
                                "field": "user_execution",
                                "operator": "EQ",
                                "value": "CONFIRMED",
                            }
                        ],
                    },
                    {
                        "tranche_id": "T2",
                        "budget_usd": 1500,
                        "status": "PENDING",
                        "validity_conditions": [
                            {
                                "field": "user_execution",
                                "operator": "EQ",
                                "value": "CONFIRMED",
                            }
                        ],
                    },
                    {
                        "tranche_id": "T3",
                        "budget_usd": 1500,
                        "status": "PENDING",
                        "validity_conditions": [
                            {
                                "field": "user_execution",
                                "operator": "EQ",
                                "value": "CONFIRMED",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def buy_update() -> dict:
    return {
        "schema_version": "CRT_EXECUTION_UPDATE_V0.1",
        "confirmation": "USER_CONFIRMED",
        "execution_id": "EXEC-001",
        "executed_at": "2026-08-23T00:40:00+08:00",
        "plan_id": "PLAN_1",
        "tranche_id": "T1",
        "asset": "MSTR",
        "side": "BUY",
        "executed_quantity": 2,
        "execution_price_usd": 120,
        "expected_holding_quantity_before": 10,
        "holding_quantity_after": 12,
        "expected_available_cash_usd_before": 4500,
        "available_cash_usd_after": 4255,
        "expected_reserved_cash_usd_before": 180,
        "reserved_cash_usd_after": 180,
        "cash_exact_confirmed": True,
    }


class ExecutionUpdateTest(unittest.TestCase):
    def test_user_confirmed_buy_updates_holding_cash_and_tranche(self) -> None:
        result = apply_user_confirmed_execution(
            profile_payload(),
            buy_update(),
        )

        holdings = {
            row["asset"]: row["quantity"]
            for row in result["holdings"]
        }

        self.assertEqual(
            holdings["MSTR"],
            12,
        )
        self.assertEqual(
            result["cash"]["available_usd"],
            4255,
        )
        self.assertTrue(
            result["cash"]["exact_amount_confirmed"]
        )
        self.assertEqual(
            result["plans"][0]["tranches"][0]["status"],
            "USER_CONFIRMED_EXECUTED",
        )
        self.assertEqual(
            result["plans"][0]["tranches"][0]["execution"]["execution_id"],
            "EXEC-001",
        )
        self.assertEqual(
            result["external_action_authority"],
            "NONE",
        )
        self.assertEqual(
            result["action_output"],
            "NONE",
        )

    def test_strc_sell_updates_legacy_share_mirror(self) -> None:
        profile = profile_payload(
            asset="STRC",
            side="SELL",
        )

        update = buy_update()
        update.update(
            {
                "execution_id": "EXEC-STRC-SELL",
                "asset": "STRC",
                "side": "SELL",
                "executed_quantity": 10,
                "execution_price_usd": 96,
                "expected_holding_quantity_before": 100,
                "holding_quantity_after": 90,
                "available_cash_usd_after": 5460,
            }
        )

        result = apply_user_confirmed_execution(
            profile,
            update,
        )

        holdings = {
            row["asset"]: row["quantity"]
            for row in result["holdings"]
        }

        self.assertEqual(
            holdings["STRC"],
            90,
        )
        self.assertEqual(
            result["strc"]["shares"],
            90,
        )
        self.assertEqual(
            result["cash"]["available_usd"],
            5460,
        )

    def test_missing_user_confirmation_is_blocked(self) -> None:
        update = buy_update()
        update["confirmation"] = "INFERRED"

        with self.assertRaises(
            ExecutionUpdateError
        ):
            apply_user_confirmed_execution(
                profile_payload(),
                update,
            )

    def test_wait_plan_cannot_be_marked_executed(self) -> None:
        profile = profile_payload(
            asset="MSTR",
            side="WAIT",
        )

        with self.assertRaisesRegex(
            ExecutionUpdateError,
            "WAIT plan",
        ):
            apply_user_confirmed_execution(
                profile,
                buy_update(),
            )

    def test_stale_pre_execution_state_is_blocked(self) -> None:
        update = buy_update()
        update[
            "expected_holding_quantity_before"
        ] = 11

        with self.assertRaisesRegex(
            ExecutionUpdateError,
            "precondition mismatch",
        ):
            apply_user_confirmed_execution(
                profile_payload(),
                update,
            )

    def test_cash_must_be_exactly_user_confirmed(self) -> None:
        update = buy_update()
        update["cash_exact_confirmed"] = False

        with self.assertRaisesRegex(
            ExecutionUpdateError,
            "exact post-execution cash",
        ):
            apply_user_confirmed_execution(
                profile_payload(),
                update,
            )

    def test_same_tranche_cannot_be_applied_twice(self) -> None:
        first = apply_user_confirmed_execution(
            profile_payload(),
            buy_update(),
        )

        second_update = buy_update()
        second_update[
            "expected_holding_quantity_before"
        ] = 12
        second_update[
            "holding_quantity_after"
        ] = 14
        second_update[
            "expected_available_cash_usd_before"
        ] = 4255
        second_update[
            "available_cash_usd_after"
        ] = 4010

        with self.assertRaises(
            ExecutionUpdateError
        ):
            apply_user_confirmed_execution(
                first,
                second_update,
            )

    def test_file_update_is_atomic_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "portfolio.json"

            profile_path.write_text(
                json.dumps(
                    profile_payload(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = apply_execution_update_file(
                profile_path,
                buy_update(),
            )

            self.assertEqual(
                result["state"],
                "EXECUTION_UPDATE_APPLIED",
            )
            self.assertEqual(
                result["external_action_authority"],
                "NONE",
            )
            self.assertEqual(
                result["action_output"],
                "NONE",
            )

            backup = Path(
                result["backup_path"]
            )

            self.assertTrue(
                backup.exists()
            )

            persisted = json.loads(
                profile_path.read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                persisted["plans"][0]["tranches"][0]["status"],
                "USER_CONFIRMED_EXECUTED",
            )
            self.assertEqual(
                persisted["holdings"][1]["quantity"],
                12,
            )


if __name__ == "__main__":
    unittest.main()
