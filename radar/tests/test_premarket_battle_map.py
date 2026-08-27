from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from crt_radar.premarket_battle_map import (
    ANALYSIS_SECTION_IDS,
    ASSET_ORDER,
    FIRST_SCREEN_FIELDS,
    build_premarket_battle_map,
    validate_premarket_battle_map_contract,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "CONFIG" / "PREMARKET_BATTLE_MAP_CONTRACT_V0.1.json"


class PremarketBattleMapTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_locks_asset_field_and_analysis_order(self):
        locked = validate_premarket_battle_map_contract(self.contract)
        self.assertEqual(locked["asset_order"], ASSET_ORDER)
        self.assertEqual(
            [row["field"] for row in locked["first_screen_fields"]],
            FIRST_SCREEN_FIELDS,
        )
        self.assertEqual(
            [row["id"] for row in locked["analysis_sections"]],
            ANALYSIS_SECTION_IDS,
        )
        self.assertEqual(locked["analysis_sections"][0]["id"], "ISSUER_REFLEXIVITY")
        self.assertTrue(locked["governance"]["mnav_semantics_unchanged"])

    def test_first_screen_never_machine_fills_analyst_fields(self):
        result = build_premarket_battle_map(
            contract=self.contract,
            asset_facts={
                "MSTR": {
                    "premarket_price": {"state": "AVAILABLE", "value": 120.0},
                    "diluted_mnav": {"state": "AVAILABLE", "mnav": 0.91},
                }
            },
            issuer_reflexivity={
                "state": "VALID",
                "event_state": "NO_NEW_MATERIAL_ISSUER_EVENT",
            },
            as_of="2026-08-26T20:30:00+08:00",
            source_mode="MANUAL_WEB_SUPPLEMENT",
        )
        self.assertEqual([row["asset"] for row in result["first_screen"]], ASSET_ORDER)
        mstr = result["first_screen"][0]
        self.assertEqual(mstr["premarket_price"], 120.0)
        self.assertEqual(mstr["diluted_mnav"], 0.91)
        self.assertIsNone(mstr["light"])

        self.assertEqual(
            mstr["entry_condition"],
            {
                "asset_price_clause": None,
                "btc_price_clause": None,
                "confirmation_clause": None,
            },
        )

        self.assertIsNone(
            mstr["entry_shares_delta"]
        )

        self.assertEqual(
            mstr["exit_condition"],
            {
                "stop_loss": {
                    "asset_price_clause": None,
                    "btc_price_clause": None,
                    "confirmation_clause": None,
                },
                "take_profit": {
                    "asset_price_clause": None,
                    "btc_price_clause": None,
                    "confirmation_clause": None,
                },
            },
        )

        self.assertIsNone(
            mstr["exit_shares_delta"]
        )
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")

    def test_closed_loop_first_screen_field_order(self):
        self.assertEqual(
            FIRST_SCREEN_FIELDS,
            [
                "light",
                "asset",
                "premarket_price",
                "diluted_mnav",
                "entry_condition",
                "entry_shares_delta",
                "exit_condition",
                "exit_shares_delta",
            ],
        )

    def test_action_surface_requires_entry_and_exit_context(self):
        locked = validate_premarket_battle_map_contract(
            self.contract
        )

        policy = locked[
            "action_surface_policy"
        ]

        self.assertTrue(
            policy["entry_condition"][
                "asset_price_clause_required"
            ]
        )

        self.assertTrue(
            policy["entry_condition"][
                "btc_price_clause_required"
            ]
        )

        self.assertEqual(
            policy["exit_condition"][
                "required_channels"
            ],
            [
                "STOP_LOSS",
                "TAKE_PROFIT",
            ],
        )

        self.assertTrue(
            policy[
                "price_reaching_is_not_action_trigger"
            ]
        )

    def test_action_share_delta_signs_are_locked(self):
        locked = validate_premarket_battle_map_contract(
            self.contract
        )

        policy = locked[
            "action_surface_policy"
        ]

        self.assertEqual(
            policy["entry_shares_delta"]["sign"],
            "NONNEGATIVE",
        )

        self.assertTrue(
            policy["entry_shares_delta"][
                "zero_allowed"
            ]
        )

        self.assertEqual(
            policy["exit_shares_delta"]["sign"],
            "NONPOSITIVE",
        )

        self.assertTrue(
            policy["exit_shares_delta"][
                "zero_allowed"
            ]
        )

    def test_action_surface_cannot_grant_machine_execution(self):
        tampered = deepcopy(self.contract)

        tampered[
            "action_surface_policy"
        ][
            "machine_execution"
        ] = "ALLOWED"

        with self.assertRaises(ValueError):
            validate_premarket_battle_map_contract(
                tampered
            )

    def test_blocked_mnav_is_not_exposed_as_a_number(self):
        result = build_premarket_battle_map(
            contract=self.contract,
            asset_facts={
                "ASST": {
                    "diluted_mnav": {
                        "state": "BLOCKED",
                        "mnav": 0.84,
                        "reason": "INPUTS_NOT_CLOSED",
                    }
                }
            },
            issuer_reflexivity=None,
            as_of=None,
            source_mode="MACHINE_VERIFIED_ONLY",
        )
        asst = result["first_screen"][1]
        self.assertIsNone(asst["diluted_mnav"])
        self.assertIn(
            {"asset": "ASST", "field": "diluted_mnav", "state": "BLOCKED"},
            result["missing_evidence"],
        )

    def test_issuer_reflexivity_section_survives_when_evidence_missing(self):
        result = build_premarket_battle_map(
            contract=self.contract,
            asset_facts={},
            issuer_reflexivity=None,
            as_of=None,
            source_mode="MACHINE_VERIFIED_ONLY",
        )
        first = result["analysis_sections"][0]
        self.assertEqual(first["id"], "ISSUER_REFLEXIVITY")
        self.assertEqual(first["state"], "BLOCKED")
        self.assertEqual(
            first["machine_evidence"]["reason"],
            "ISSUER_REFLEXIVITY_EVIDENCE_MISSING",
        )

    def test_partial_real_evidence_remains_visible(self):
        result = build_premarket_battle_map(
            contract=self.contract,
            asset_facts={
                "STRC": {
                    "premarket_price": {"state": "AVAILABLE", "value": 95.0},
                    "latest_round": {"state": "AVAILABLE", "value": {"round_id": 6}},
                    "repurchase_rounds": {
                        "state": "PARTIAL",
                        "value": [{"round_id": 6}],
                    },
                }
            },
            issuer_reflexivity={
                "state": "VALID",
                "event_state": "NO_NEW_MATERIAL_ISSUER_EVENT",
            },
            as_of="2026-08-26",
            source_mode="MANUAL_WEB_SUPPLEMENT",
        )
        strc = result["first_screen"][2]
        self.assertEqual(strc["premarket_price"], 95.0)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertIn(
            {"asset": "STRC", "field": "repurchase_rounds", "state": "PARTIAL"},
            result["missing_evidence"],
        )

    def test_tampered_contract_fails_closed(self):
        tampered = deepcopy(self.contract)
        tampered["analysis_sections"][0], tampered["analysis_sections"][1] = (
            tampered["analysis_sections"][1],
            tampered["analysis_sections"][0],
        )
        with self.assertRaises(ValueError):
            validate_premarket_battle_map_contract(tampered)

    def test_source_mode_must_be_declared_by_contract(self):
        with self.assertRaises(ValueError):
            build_premarket_battle_map(
                contract=self.contract,
                asset_facts={},
                issuer_reflexivity=None,
                as_of=None,
                source_mode="SECRET_AUTO_WEB",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)