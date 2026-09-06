from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

from crt_radar.btc_control_transfer_validation import (
    evaluate_control_transfer_validation,
)


CONTRACT = (
    RADAR_ROOT
    / "research"
    / "CRT_CONTROL_TRANSFER_VALIDATION_CONTRACT_V0.1.md"
)
CASES = (
    RADAR_ROOT
    / "research"
    / "CRT_BTC_CONTROL_TRANSFER_VALIDATION_CASES_V0.1.json"
)
CONTRACT_SHA256 = "32e640991984bcfe876cc438669173f745a3be3c33d2d52e5baef4782ec5dbb1"


class BtcControlTransferValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASES.read_text(encoding="utf-8"))

    def test_contract_is_hash_bound_and_research_only(self):
        self.assertEqual(
            hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
            CONTRACT_SHA256,
        )
        self.assertEqual(
            self.cases["source_contract"]["sha256"],
            CONTRACT_SHA256,
        )
        self.assertEqual(
            self.cases["status"],
            "RESEARCH_ONLY_NOT_APPROVED",
        )

    def test_red_team_cases(self):
        actual = {}

        for case in self.cases["cases"]:
            if not case.get("eligible_for_acceptance"):
                continue

            result = evaluate_control_transfer_validation(
                copy.deepcopy(case["evidence"])
            )
            actual[case["case_id"]] = (
                result["research_state"],
                result["current_validation_status"],
            )

            self.assertEqual(
                result["research_state"],
                case["expected_research_state"],
                case["case_id"],
            )
            self.assertEqual(
                result["current_validation_status"],
                case["expected_current_validation_status"],
                case["case_id"],
            )
            self.assertIsNone(result["formal_season"])
            self.assertEqual(
                result["season_transition_authority"],
                "NONE",
            )
            self.assertFalse(
                result["machine_may_determine_btc_season"]
            )
            self.assertFalse(
                result["machine_may_confirm_bull_transition"]
            )
            self.assertEqual(result["action_output"], "NONE")
            self.assertEqual(
                result["external_action_authority"],
                "NONE",
            )
            self.assertFalse(
                result["external_action_performed"]
            )

        self.assertEqual(
            actual["2015_SUCCESSFUL_RECLAIM"],
            ("CONTROL_TRANSFER_VALIDATED", "ACTIVE"),
        )
        self.assertEqual(
            actual["2020_Q4_SUCCESSFUL"],
            ("CONTROL_TRANSFER_VALIDATED", "ACTIVE"),
        )
        self.assertEqual(
            actual["2023_MAR_SUCCESSFUL"],
            ("CONTROL_TRANSFER_VALIDATED", "ACTIVE"),
        )
        self.assertEqual(
            actual["2022_MAR_FAILED"],
            ("CONTROL_TRANSFER_CANDIDATE_FAILED", None),
        )
        self.assertEqual(
            actual["2021_Q4_VALIDATED_THEN_REVERSED"],
            ("CONTROL_TRANSFER_VALIDATED", "REVERSED"),
        )

    def test_2020_feb_remains_provisional_only(self):
        row = next(
            case
            for case in self.cases["cases"]
            if case["case_id"] == "2020_FEB_PROVISIONAL"
        )
        self.assertFalse(row["eligible_for_acceptance"])
        self.assertNotIn("evidence", row)

    def test_new_local_control_high_break_is_not_a_gate(self):
        case = next(
            row
            for row in self.cases["cases"]
            if row["case_id"] == "2015_SUCCESSFUL_RECLAIM"
        )
        evidence = copy.deepcopy(case["evidence"])
        evidence["post_c_test"][
            "new_local_control_high_break"
        ] = "NOT_CONFIRMED"

        result = evaluate_control_transfer_validation(evidence)

        self.assertEqual(
            result["research_state"],
            "CONTROL_TRANSFER_VALIDATED",
        )
        self.assertFalse(
            result["strengthening_evidence"]["mandatory_gate"]
        )

    def test_same_event_cannot_self_validate(self):
        case = next(
            row
            for row in self.cases["cases"]
            if row["case_id"] == "2023_MAR_SUCCESSFUL"
        )
        evidence = copy.deepcopy(case["evidence"])
        evidence["post_c_test"]["event_id"] = evidence[
            "candidate"
        ]["event_id"]

        result = evaluate_control_transfer_validation(evidence)

        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn(
            "EVENT_ID_CONTRADICTION",
            result["reason"],
        )

    def test_non_distinct_later_test_remains_pending(self):
        case = next(
            row
            for row in self.cases["cases"]
            if row["case_id"] == "2023_MAR_SUCCESSFUL"
        )
        evidence = copy.deepcopy(case["evidence"])
        evidence["post_c_test"]["distinct_event"] = False

        result = evaluate_control_transfer_validation(evidence)

        self.assertEqual(
            result["research_state"],
            "VALIDATION_PENDING",
        )
        self.assertIsNone(result["formal_season"])

    def test_unresolved_reexpansion_remains_pending(self):
        case = next(
            row
            for row in self.cases["cases"]
            if row["case_id"] == "2020_Q4_SUCCESSFUL"
        )
        evidence = copy.deepcopy(case["evidence"])
        evidence["post_c_test"][
            "renewed_expansion"
        ] = "UNRESOLVED"

        result = evaluate_control_transfer_validation(evidence)

        self.assertEqual(
            result["research_state"],
            "VALIDATION_PENDING",
        )

    def test_review_can_move_validated_state_under_review(self):
        case = next(
            row
            for row in self.cases["cases"]
            if row["case_id"] == "2023_MAR_SUCCESSFUL"
        )
        evidence = copy.deepcopy(case["evidence"])
        evidence["post_validation_review"] = {
            "state": "UNDER_REVIEW",
            "event_id": "2023MAR-R1",
            "timestamp": "2023MAR-R1",
            "event_order": "AFTER_VALIDATION",
            "distinct_event": True,
        }

        result = evaluate_control_transfer_validation(evidence)

        self.assertEqual(
            result["research_state"],
            "CONTROL_TRANSFER_VALIDATED",
        )
        self.assertEqual(
            result["current_validation_status"],
            "UNDER_REVIEW",
        )

    def test_any_formal_authority_claim_fails_closed(self):
        case = next(
            row
            for row in self.cases["cases"]
            if row["case_id"] == "2023_MAR_SUCCESSFUL"
        )
        evidence = copy.deepcopy(case["evidence"])
        evidence["authority"][
            "season_transition_authority"
        ] = "YES"

        result = evaluate_control_transfer_validation(evidence)

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(
            result["season_transition_authority"],
            "NONE",
        )
        self.assertIsNone(result["formal_season"])

    def test_non_candidate_cannot_enter_d(self):
        case = next(
            row
            for row in self.cases["cases"]
            if row["case_id"] == "2023_MAR_SUCCESSFUL"
        )
        evidence = copy.deepcopy(case["evidence"])
        evidence["candidate"]["state"] = (
            "ATTACK_STRENGTHENED_DEFENSE_PENDING"
        )

        result = evaluate_control_transfer_validation(evidence)

        self.assertEqual(
            result["research_state"],
            "INCONCLUSIVE",
        )
        self.assertEqual(result["state"], "NOT_AVAILABLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
