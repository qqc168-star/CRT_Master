from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

from crt_radar.btc_transition_research_eval import (
    evaluate_control_transfer_evidence,
)


DELTA = RADAR_ROOT / "research" / "CRT_SEASON_ROUTER_RESEARCH_DELTA_20260822.md"
CASES = RADAR_ROOT / "research" / "CRT_BTC_SEASON_RESEARCH_EVAL_CASES_V0.1.json"
DELTA_SHA256 = "d41675b072352e78e0facb0fff8893d401a60ac7e91c4aeb8858eb6133403db7"


class BtcTransitionResearchEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASES.read_text(encoding="utf-8"))

    def test_research_delta_is_received_byte_exact(self):
        self.assertEqual(hashlib.sha256(DELTA.read_bytes()).hexdigest(), DELTA_SHA256)
        self.assertEqual(self.cases["source_delta"]["sha256"], DELTA_SHA256)
        self.assertEqual(self.cases["status"], "RESEARCH_ONLY_NOT_APPROVED")

    def test_five_case_groups_match_expected_point_in_time_states(self):
        case_ids = {case["case_id"] for case in self.cases["cases"]}
        self.assertEqual(
            case_ids,
            {
                "2018_LOWER_HIGH_LADDER",
                "2019_FALSE_BULL",
                "2022_MOMENTUM_TRAP",
                "2023_SUCCESSFUL_RECLAIM",
                "2026_POINT_IN_TIME_LIVE",
            },
        )

        actual = {}
        for case in self.cases["cases"]:
            actual[case["case_id"]] = []
            for checkpoint in case["checkpoints"]:
                result = evaluate_control_transfer_evidence(checkpoint["evidence"])
                self.assertEqual(result["state"], "READY_FOR_ANALYST")
                self.assertEqual(
                    result["research_state"],
                    checkpoint["expected_research_state"],
                    checkpoint["checkpoint_id"],
                )
                self.assertIsNone(result["formal_season"])
                self.assertFalse(result["machine_may_determine_btc_season"])
                self.assertFalse(result["machine_may_confirm_bull_transition"])
                self.assertEqual(result["season_transition_authority"], "NONE")
                self.assertEqual(result["external_action_authority"], "NONE")
                self.assertEqual(result["action_output"], "NONE")
                actual[case["case_id"]].append(result["research_state"])

        self.assertEqual(
            actual["2019_FALSE_BULL"],
            ["ATTACK_STRENGTHENED_DEFENSE_PENDING", "FALSE_POSITIVE_REJECTED"],
        )
        self.assertEqual(
            actual["2022_MOMENTUM_TRAP"],
            ["ATTACK_STRENGTHENED_DEFENSE_PENDING", "FALSE_POSITIVE_REJECTED"],
        )
        self.assertEqual(
            actual["2023_SUCCESSFUL_RECLAIM"],
            ["CONTROL_TRANSFER_CANDIDATE"],
        )
        self.assertEqual(
            actual["2026_POINT_IN_TIME_LIVE"],
            ["ATTACK_STRENGTHENED_DEFENSE_PENDING"],
        )

    def test_sequence_contradiction_fails_closed(self):
        evidence = {
            "schema_version": "CRT_BTC_CONTROL_TRANSFER_EVIDENCE_V0.1",
            "authority": {
                "formal_model_authority": "NONE",
                "formal_weight_authority": "NONE",
                "formal_threshold_authority": "NONE",
                "season_transition_authority": "NONE",
                "external_action_authority": "NONE",
                "external_action_performed": False,
            },
            "observations": {
                "meaningful_breakout": "CONFIRMED",
                "meaningful_pullback": "NOT_OBSERVED",
                "higher_low": "CONFIRMED",
                "reattack": "NOT_OBSERVED",
                "prior_control_high_break": "NOT_OBSERVED",
                "invalidating_lower_low": "NOT_OBSERVED",
            },
        }
        result = evaluate_control_transfer_evidence(evidence)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("SEQUENCE_CONTRADICTION", result["reason"])
        self.assertFalse(result["machine_may_determine_btc_season"])

    def test_any_formal_authority_claim_fails_closed(self):
        evidence = self.cases["cases"][3]["checkpoints"][0]["evidence"]
        evidence = json.loads(json.dumps(evidence))
        evidence["authority"]["season_transition_authority"] = "YES"

        result = evaluate_control_transfer_evidence(evidence)

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["season_transition_authority"], "NONE")
        self.assertIsNone(result["formal_season"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
