from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.reflexivity_overlay import (
    EMPTY_REASON,
    EXTERNAL_ACTION_AUTHORITY,
    OVERLAY_ID,
    OVERLAY_TYPE,
    build_reflexivity_overlay,
)
from test_first_evidence_slice import BASE_MS, gate


ISSUER_ID = "CIK-0001050446"
SECURITY_ID = "SEC-STRC-PERP"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_ref(label: str = "filing") -> dict:
    return {
        "source_id": f"SRC-{label.upper()}",
        "document_id": f"DOC-{label.upper()}",
        "source_as_of_ms": BASE_MS,
        "evidence_hash": digest(label),
    }


def empty_section(*, issuer_scope: bool = True, security_scope: bool = True) -> dict:
    scope = {}
    if issuer_scope:
        scope["issuer_ids"] = [ISSUER_ID]
    if security_scope:
        scope["security_ids"] = [SECURITY_ID]
    return {
        "coverage_state": "COMPLETE",
        "scope": scope,
        "items": [],
        "empty_reason": EMPTY_REASON,
    }


def valid_payload() -> dict:
    return {
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "action_output": "NONE",
        "issuer_facts": {
            "coverage_state": "COMPLETE",
            "scope": {
                "issuer_ids": [ISSUER_ID],
                "security_ids": [SECURITY_ID],
                "start_ms": BASE_MS - 86_400_000,
                "end_ms": BASE_MS,
            },
            "items": [
                {
                    "fact_id": "FACT-REPURCHASED-SHARES",
                    "issuer_id": ISSUER_ID,
                    "security_id": SECURITY_ID,
                    "fact_type": "REPURCHASED_SHARES",
                    "value": 100.0,
                    "unit": "SHARES",
                    "effective_at_ms": BASE_MS,
                    "origin": "REPORTED",
                    "source_ref": source_ref(),
                    "quality_state": "VALID_REPORTED",
                },
                {
                    "fact_id": "FACT-REPURCHASE-CASH",
                    "issuer_id": ISSUER_ID,
                    "security_id": SECURITY_ID,
                    "fact_type": "REPURCHASE_CASH_CONSIDERATION",
                    "value": 9_500.0,
                    "unit": "USD",
                    "effective_at_ms": BASE_MS,
                    "origin": "REPORTED",
                    "source_ref": source_ref(),
                    "quality_state": "VALID_REPORTED",
                }
            ],
        },
        "issuer_events": {
            "coverage_state": "COMPLETE",
            "scope": {
                "issuer_ids": [ISSUER_ID],
                "security_ids": [SECURITY_ID],
                "start_ms": BASE_MS - 86_400_000,
                "end_ms": BASE_MS,
            },
            "items": [
                {
                    "event_id": "EVENT-REPURCHASE-1",
                    "issuer_id": ISSUER_ID,
                    "security_id": SECURITY_ID,
                    "event_type": "SECURITY_REPURCHASE",
                    "execution_window": {
                        "kind": "EXECUTION",
                        "start_ms": BASE_MS - 86_400_000,
                        "end_ms": BASE_MS - 3_600_000,
                        "precision": "RANGE",
                    },
                    "disclosure_window": {
                        "kind": "DISCLOSURE",
                        "start_ms": BASE_MS,
                        "end_ms": BASE_MS,
                        "precision": "SECOND",
                    },
                    "reported_values": [
                        {"fact_id": "FACT-REPURCHASED-SHARES", "value": 100.0, "unit": "SHARES"}
                    ],
                    "source_ref": source_ref(),
                    "supersession": {
                        "state": "ACTIVE",
                        "superseded_by_event_id": None,
                    },
                }
            ],
        },
        "market_reaction_facts": empty_section(issuer_scope=False),
        "reflexivity_blockers": {
            "coverage_state": "COMPLETE",
            "scope": {"overlay_id": OVERLAY_ID},
            "items": [],
            "empty_reason": EMPTY_REASON,
        },
        "calculation_requests": [
            {
                "calculation_id": "CALC-REPURCHASE-AVG-PRICE",
                "calculation_spec_id": "REPURCHASE_AVG_PRICE",
                "issuer_id": ISSUER_ID,
                "security_id": SECURITY_ID,
                "inputs": {
                    "eligible_cash_consideration": 9_500.0,
                    "repurchased_shares": 100.0,
                },
                "input_fact_ids": ["FACT-REPURCHASED-SHARES", "FACT-REPURCHASE-CASH"],
                "input_event_ids": ["EVENT-REPURCHASE-1"],
                "output_unit": "USD_PER_SHARE",
                "prerequisites": {"same_event": True, "same_currency": True},
                "source_refs": [source_ref()],
            }
        ],
    }


def blocker_codes(overlay: dict) -> set[str]:
    return {item["reason_code"] for item in overlay["blockers"]["items"]}


class ReflexivityOverlayTests(unittest.TestCase):
    def test_missing_input_fails_closed_and_empty_is_not_normal(self):
        overlay = build_reflexivity_overlay(None)
        self.assertEqual(overlay["asset_facts"]["section_state"], "BLOCKED")
        self.assertEqual(overlay["decision_relevant_events"]["section_state"], "BLOCKED")
        self.assertEqual(overlay["asset_facts"]["items"], [])
        self.assertNotIn("empty_reason", overlay["asset_facts"])
        self.assertIn("REFLEXIVITY_INPUT_MISSING", blocker_codes(overlay))

    def test_complete_verified_empty_is_ready(self):
        payload = {
            "external_action_authority": "NONE",
            "action_output": "NONE",
            "issuer_facts": empty_section(),
            "issuer_events": empty_section(),
            "market_reaction_facts": empty_section(issuer_scope=False),
            "reflexivity_blockers": {
                "coverage_state": "COMPLETE",
                "scope": {"overlay_id": OVERLAY_ID},
                "items": [],
                "empty_reason": EMPTY_REASON,
            },
        }
        overlay = build_reflexivity_overlay(payload)
        self.assertEqual(overlay["asset_facts"]["section_state"], "READY")
        self.assertEqual(overlay["decision_relevant_events"]["section_state"], "READY")
        self.assertEqual(overlay["blockers"]["section_state"], "READY")
        self.assertEqual(overlay["asset_facts"]["empty_reason"], EMPTY_REASON)
        self.assertEqual(overlay["blockers"]["empty_reason"], EMPTY_REASON)

    def test_valid_fact_event_and_formula_enter_existing_generic_sections(self):
        overlay = build_reflexivity_overlay(valid_payload())
        self.assertEqual(overlay["asset_facts"]["section_state"], "READY")
        self.assertEqual(overlay["decision_relevant_events"]["section_state"], "READY")
        self.assertEqual(overlay["blockers"]["items"], [])
        self.assertEqual(overlay["asset_facts"]["overlay_type"], OVERLAY_TYPE)
        facts = {item["asset_fact_id"]: item for item in overlay["asset_facts"]["items"]}
        self.assertEqual(facts["FACT-REPURCHASED-SHARES"]["fact_kind"], "ISSUER_FACT")
        self.assertEqual(facts["CALC-REPURCHASE-AVG-PRICE"]["value"], 95.0)
        self.assertFalse(facts["CALC-REPURCHASE-AVG-PRICE"]["causal_interpretation"])
        self.assertEqual(overlay["decision_relevant_events"]["items"][0]["active_for_calculation"], True)

    def test_identity_mismatch_blocks_and_omits_unverified_fact(self):
        payload = valid_payload()
        payload["issuer_facts"]["items"][0]["issuer_id"] = "CIK-WRONG"
        overlay = build_reflexivity_overlay(payload)
        self.assertIn("ISSUER_IDENTITY_UNRESOLVED", blocker_codes(overlay))
        facts = {item["asset_fact_id"] for item in overlay["asset_facts"]["items"]}
        self.assertNotIn("FACT-REPURCHASED-SHARES", facts)
        self.assertEqual(overlay["asset_facts"]["section_state"], "BLOCKED")

    def test_execution_and_disclosure_windows_cannot_be_mixed(self):
        payload = valid_payload()
        payload["issuer_events"]["items"][0]["execution_window"]["kind"] = "DISCLOSURE"
        overlay = build_reflexivity_overlay(payload)
        self.assertIn("EXECUTION_DISCLOSURE_MIXED", blocker_codes(overlay))
        self.assertEqual(overlay["decision_relevant_events"]["items"], [])

    def test_superseded_event_is_retained_but_inactive(self):
        payload = valid_payload()
        event = payload["issuer_events"]["items"][0]
        event["supersession"] = {
            "state": "SUPERSEDED",
            "superseded_by_event_id": "EVENT-REPURCHASE-2",
        }
        overlay = build_reflexivity_overlay(payload)
        output_event = overlay["decision_relevant_events"]["items"][0]
        self.assertEqual(output_event["supersession"]["state"], "SUPERSEDED")
        self.assertFalse(output_event["active_for_calculation"])
        self.assertIn("SUPERSESSION_UNRESOLVED", blocker_codes(overlay))
        self.assertNotIn(
            "CALC-REPURCHASE-AVG-PRICE",
            {item["asset_fact_id"] for item in overlay["asset_facts"]["items"]},
        )

    def test_unresolved_supersession_blocks_event(self):
        payload = valid_payload()
        payload["issuer_events"]["items"][0]["supersession"] = {
            "state": "UNKNOWN",
            "superseded_by_event_id": None,
        }
        overlay = build_reflexivity_overlay(payload)
        self.assertIn("SUPERSESSION_UNRESOLVED", blocker_codes(overlay))
        self.assertEqual(overlay["decision_relevant_events"]["items"], [])

    def test_reported_zero_requires_verified_zero_semantics(self):
        payload = valid_payload()
        payload["issuer_facts"]["items"][0]["value"] = 0
        overlay = build_reflexivity_overlay(payload)
        self.assertIn("VERIFIED_ZERO_NOT_ESTABLISHED", blocker_codes(overlay))
        self.assertNotIn("FACT-REPURCHASED-SHARES", {item["asset_fact_id"] for item in overlay["asset_facts"]["items"]})

    def test_empty_array_without_complete_verification_is_blocked(self):
        payload = valid_payload()
        payload["issuer_facts"] = empty_section()
        payload["issuer_facts"].pop("empty_reason")
        payload["calculation_requests"] = []
        overlay = build_reflexivity_overlay(payload)
        self.assertIn("EMPTY_STATE_UNVERIFIED", blocker_codes(overlay))
        self.assertEqual(overlay["asset_facts"]["section_state"], "BLOCKED")

    def test_share_basis_mismatch_blocks_calculation(self):
        payload = valid_payload()
        payload["calculation_requests"][0] = {
            "calculation_id": "CALC-NET-SHARES",
            "calculation_spec_id": "NET_SHARE_COUNT_CHANGE",
            "issuer_id": ISSUER_ID,
            "security_id": SECURITY_ID,
            "inputs": {"pre_basic_shares": 100.0, "post_basic_shares": 110.0},
            "input_fact_ids": ["FACT-REPURCHASED-SHARES", "FACT-REPURCHASE-CASH"],
            "input_event_ids": ["EVENT-REPURCHASE-1"],
            "output_unit": "RATIO",
            "prerequisites": {
                "same_security_class": True,
                "pre_share_count_basis": "CLASS_BASIC",
                "post_share_count_basis": "DILUTED",
            },
            "source_refs": [source_ref()],
        }
        overlay = build_reflexivity_overlay(payload)
        self.assertIn("SHARE_COUNT_BASIS_MISMATCH", blocker_codes(overlay))
        self.assertNotIn("CALC-NET-SHARES", {item["asset_fact_id"] for item in overlay["asset_facts"]["items"]})

    def test_market_dependent_calculation_is_blocked_without_formal_locks(self):
        payload = valid_payload()
        payload["calculation_requests"][0] = {
            "calculation_id": "CALC-MARKET-PARTICIPATION",
            "calculation_spec_id": "OPEN_MARKET_PARTICIPATION",
            "issuer_id": ISSUER_ID,
            "security_id": SECURITY_ID,
            "inputs": {
                "verified_open_market_repurchased_shares": 100.0,
                "comparable_consolidated_volume": 1000.0,
            },
            "input_fact_ids": ["FACT-REPURCHASED-SHARES", "FACT-REPURCHASE-CASH"],
            "input_event_ids": ["EVENT-REPURCHASE-1"],
            "output_unit": "RATIO",
            "prerequisites": {
                "same_security": True,
                "same_execution_window": True,
                "open_market_channel_verified": False,
                "volume_scope_comparable": False,
            },
            "source_refs": [source_ref()],
        }
        overlay = build_reflexivity_overlay(payload)
        codes = blocker_codes(overlay)
        self.assertIn("WINDOW_SPEC_NOT_APPROVED", codes)
        self.assertIn("PRICE_OR_VOLUME_UNVERIFIABLE", codes)
        self.assertIn("ACTION_CHANNEL_UNKNOWN", codes)
        self.assertIn("MARKET_VOLUME_SCOPE_MISMATCH", codes)

    def test_market_reaction_fact_is_blocked_until_source_and_window_are_approved(self):
        payload = valid_payload()
        payload["market_reaction_facts"] = {
            "coverage_state": "COMPLETE",
            "scope": {"security_ids": [SECURITY_ID]},
            "items": [
                {
                    "reaction_fact_id": "REACTION-1",
                    "event_id": "EVENT-REPURCHASE-1",
                    "security_id": SECURITY_ID,
                    "metric": "FIXED_WINDOW_RETURN",
                    "value": 0.05,
                    "unit": "RATIO",
                    "window_type": "REACTION",
                    "window": {
                        "window_spec_id": "UNAPPROVED-WINDOW",
                        "start_ms": BASE_MS,
                        "end_ms": BASE_MS + 86_400_000,
                    },
                    "source_refs": [source_ref("market")],
                }
            ],
        }
        overlay = build_reflexivity_overlay(payload)
        self.assertIn("WINDOW_SPEC_NOT_APPROVED", blocker_codes(overlay))
        self.assertIn("PRICE_OR_VOLUME_UNVERIFIABLE", blocker_codes(overlay))
        self.assertNotIn("REACTION-1", {item["asset_fact_id"] for item in overlay["asset_facts"]["items"]})

    def test_all_non_market_formula_locked_calculations_are_deterministic(self):
        cases = [
            ("REPURCHASE_AVG_PRICE", {"eligible_cash_consideration": 9500, "repurchased_shares": 100}, {"same_event": True, "same_currency": True}, 95.0),
            ("REPURCHASE_SHARE_RATIO", {"repurchased_class_shares": 10, "pre_event_class_basic_shares": 100}, {"same_security_class": True, "share_count_basis": "CLASS_BASIC"}, 0.1),
            ("GROSS_ISSUANCE_RATIO", {"gross_issued_class_shares": 20, "pre_event_class_basic_shares": 100}, {"same_security_class": True, "share_count_basis": "CLASS_BASIC", "gross_issuance_not_net": True}, 0.2),
            ("NET_SHARE_COUNT_CHANGE", {"pre_basic_shares": 100, "post_basic_shares": 90}, {"same_security_class": True, "pre_share_count_basis": "CLASS_BASIC", "post_share_count_basis": "CLASS_BASIC"}, -0.1),
            ("REMAINING_AUTHORIZATION", {"active_authorization": 1000, "cumulative_eligible_spend": 250}, {"same_authorization": True, "same_currency": True, "authorization_scope_known": True, "supersession_state": "ACTIVE"}, 750.0),
            ("REMAINING_ATM_CAPACITY", {"active_program_capacity": 1000, "cumulative_program_usage": 400}, {"same_program": True, "same_unit": True, "supersession_state": "ACTIVE"}, 600.0),
            ("BTC_NET_FLOW", {"btc_bought": 20, "btc_sold": 3}, {"same_period": True}, 17.0),
            ("LIQUIDATION_PREFERENCE_RETIRED", {"retired_shares": 10, "liquidation_preference_per_share": 100}, {"same_security_class": True, "terms_current": True}, 1000.0),
            ("DISTRIBUTION_RUN_RATE_REMOVED", {"retired_shares": 10, "current_annual_distribution_per_share": 8}, {"same_security_class": True, "terms_current": True, "output_semantics": "CURRENT_RUN_RATE_ONLY"}, 80.0),
        ]
        for index, (spec_id, inputs, prerequisites, expected) in enumerate(cases):
            with self.subTest(spec_id=spec_id):
                payload = valid_payload()
                payload["calculation_requests"] = [
                    {
                        "calculation_id": f"CALC-{index}",
                        "calculation_spec_id": spec_id,
                        "issuer_id": ISSUER_ID,
                        "security_id": SECURITY_ID,
                        "inputs": inputs,
                        "input_fact_ids": ["FACT-REPURCHASED-SHARES", "FACT-REPURCHASE-CASH"],
                        "input_event_ids": ["EVENT-REPURCHASE-1"],
                        "output_unit": "TEST_UNIT",
                        "prerequisites": prerequisites,
                        "source_refs": [source_ref(str(index))],
                    }
                ]
                overlay = build_reflexivity_overlay(payload)
                calculation = next(item for item in overlay["asset_facts"]["items"] if item["asset_fact_id"] == f"CALC-{index}")
                self.assertAlmostEqual(calculation["value"], expected)
                self.assertEqual(overlay["blockers"]["items"], [])

    def test_prohibited_analyst_fields_and_action_are_blocked_and_not_emitted(self):
        payload = valid_payload()
        payload["reflexivity_score"] = 99
        payload["capital_strategy"] = "BUY"
        payload["action_output"] = "BUY"
        overlay = build_reflexivity_overlay(payload)
        codes = blocker_codes(overlay)
        self.assertIn("PROHIBITED_ANALYST_OUTPUT", codes)
        self.assertIn("ACTION_OUTPUT_NOT_NONE", codes)
        self.assertNotIn("reflexivity_score", overlay)
        self.assertNotIn("capital_strategy", overlay)
        for item in overlay["asset_facts"]["items"]:
            self.assertNotIn("reflexivity_score", item)
            self.assertNotIn("capital_strategy", item)

    def test_same_input_produces_same_overlay_hash(self):
        payload = valid_payload()
        first = build_reflexivity_overlay(payload)
        second = build_reflexivity_overlay(deepcopy(payload))
        self.assertEqual(first["asset_facts"]["overlay_hash"], second["asset_facts"]["overlay_hash"])
        self.assertEqual(first, second)

    def test_evidence_pack_integration_preserves_authority_and_market_model_state(self):
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(
                gate(0),
                observation_db=Path(td) / "obs.sqlite3",
                generated_at_ms=BASE_MS,
                reflexivity_input=valid_payload(),
            )
        self.assertEqual(pack["schema_version"], "CRT_EVIDENCE_PACK_V0.2")
        self.assertEqual(pack["action_output"], "NONE")
        self.assertEqual(pack["pack_state"], "PARTIAL_FOR_ANALYST")
        self.assertEqual(pack["authority"]["external_action_authority"], "NONE")
        self.assertTrue(all(value is None for value in pack["analyst_output"].values()))
        self.assertEqual(pack["asset_facts"]["section_state"], "READY")
        self.assertEqual(pack["decision_relevant_events"]["section_state"], "READY")

    def test_source_gate_blocker_is_retained_without_changing_overlay_authority(self):
        overlay = build_reflexivity_overlay(
            valid_payload(),
            source_gate_blocked_reasons=["OPEN_INTEREST_TRANSPORT_ERROR"],
        )
        source_items = [item for item in overlay["blockers"]["items"] if item["scope"] == "SOURCE_GATE"]
        self.assertEqual([item["reason_code"] for item in source_items], ["OPEN_INTEREST_TRANSPORT_ERROR"])
        self.assertEqual(EXTERNAL_ACTION_AUTHORITY, "NONE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
