from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

from crt_radar.btc_transition_research_eval import (
    AUTHORITY_FIELDS,
    SCHEMA_VERSION,
    SEQUENCE,
    evaluate_control_transfer_evidence,
)
from crt_radar.btc_transition_replay_evidence import build_transition_replay_snapshot
from crt_radar.deployment_posture_research_gate import (
    translate_research_state_to_posture_constraints as translate,
)


def evaluation(confirmed=5, lower_low="NOT_OBSERVED"):
    return evaluate_control_transfer_evidence({
        "schema_version": SCHEMA_VERSION,
        "authority": {
            **{field: "NONE" for field in AUTHORITY_FIELDS},
            "external_action_performed": False,
        },
        "observations": {
            **{field: "CONFIRMED" if i < confirmed else "NOT_OBSERVED"
               for i, field in enumerate(SEQUENCE)},
            "invalidating_lower_low": lower_low,
        },
    })


class DeploymentPostureResearchGateTests(unittest.TestCase):
    def assert_safe(self, result):
        for field in (*AUTHORITY_FIELDS, "action_output"):
            self.assertEqual(result[field], "NONE")
        for field in ("external_action_performed", "machine_may_execute_trade",
                      "machine_may_determine_btc_season",
                      "machine_may_confirm_bull_transition"):
            self.assertIs(result[field], False)
        self.assertIs(result["analyst_judgment_required"], True)
        self.assertIsNone(result["formal_season"])
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")
        self.assertEqual(result["machine_execution"], "FORBIDDEN")
        self.assertEqual(result["production"], "NOT_APPROVED")
        self.assertEqual(result["final_eligibility"], "NOT_DETERMINED")
        self.assertEqual(result["plan_invalidation"], "UNRESOLVED")
        self.assertEqual(result["scope"], "TRANSITION_RESEARCH_ONLY")
        self.assertEqual(result["eligibility_level"], "RESEARCH_POSTURE_CANDIDATE")
        self.assertIn("GPT_ANALYST_JUDGMENT", result["required_downstream_gates"])
        self.assertTrue({
            "EXISTING_BTC_DECISION_SUPPORT", "QUALIFIED_COMMANDER_ATTACK_AND_DEFENSE_LINES",
            "LATEST_CAPITAL_STATE", "ACTIVE_CAPITAL_PLAN_AND_AVAILABLE_TRANCHE",
            "BULL_FOUNDATION", "INDEPENDENT_EVIDENCE", "ASSET_ROLE_INTEGRITY",
            "DECISION_ASYMMETRY", "ASSET_SPECIFIC_FACTS", "USER_DECISION",
        }.issubset(result["required_downstream_gates"]))
        self.assertFalse({"price", "limit_price", "shares", "amount", "broker",
                          "execution", "plan_invalidated", "entry_condition",
                          "entry_shares_delta", "exit_condition"} & result.keys())
        for forbidden in ("BUY", "SELL", "SCOUT_ELIGIBLE", "BRIDGEHEAD_ELIGIBLE",
                          "REINFORCEMENT_ELIGIBLE", "HOLD_SCOUT",
                          "NO_NEW_DEPLOYMENT", "NO_BULL_DEPLOYMENT"):
            self.assertNotIn(forbidden, result.values())

    def assert_blocked(self, source):
        result = translate(source)
        self.assertEqual(result["state"], "POSTURE_TRANSLATION_BLOCKED")
        self.assertEqual(result["posture_candidate"], "NONE")
        self.assertEqual(result["posture_effect"], "POSTURE_TRANSLATION_BLOCKED")
        self.assertIsNone(result["research_state"])
        self.assert_safe(result)

    def test_seven_audited_mappings_from_real_evaluator(self):
        cases = [
            (0, "NOT_OBSERVED", "TRANSITION_UNRESOLVED", "NONE",
             "NO_UPGRADE_FROM_TRANSITION_RESEARCH"),
            (1, "NOT_OBSERVED", "ATTACK_STRENGTHENED_DEFENSE_PENDING", "SCOUT",
             "REVIEW_CANDIDATE"),
            (2, "NOT_OBSERVED", "DEFENSE_UNRESOLVED", "SCOUT",
             "HOLD_OR_REVIEW_ONLY_NO_UPGRADE"),
            (3, "NOT_OBSERVED", "DEFENSE_HELD_REATTACK_PENDING", "BRIDGEHEAD",
             "REVIEW_CANDIDATE"),
            (5, "NOT_OBSERVED", "CONTROL_TRANSFER_CANDIDATE", "REINFORCEMENT",
             "REVIEW_CANDIDATE_TRANSITION_PREREQUISITE_MET"),
            (1, "OBSERVED", "FALSE_POSITIVE_REJECTED", "NONE",
             "FREEZE_UPGRADES_AND_REANALYZE"),
            (0, "OBSERVED", "BEAR_CONTROL_RETAINED", "NONE",
             "BLOCK_TRANSITION_JUSTIFIED_UPGRADE"),
        ]
        for count, lower_low, state, candidate, effect in cases:
            with self.subTest(state=state):
                result = translate(evaluation(count, lower_low))
                self.assertEqual(result["state"], "READY_FOR_ANALYST")
                self.assertEqual(result["research_state"], state)
                self.assertEqual(result["posture_candidate"], candidate)
                self.assertEqual(result["posture_effect"], effect)
                self.assert_safe(result)

    def test_existing_research_cases_remain_candidates_only(self):
        cases = json.loads((RADAR_ROOT / "research" /
                           "CRT_BTC_SEASON_RESEARCH_EVAL_CASES_V0.1.json").read_text("utf-8"))
        for case in cases["cases"]:
            for checkpoint in case["checkpoints"]:
                with self.subTest(case=case["case_id"], checkpoint=checkpoint["checkpoint_id"]):
                    result = translate(evaluate_control_transfer_evidence(checkpoint["evidence"]))
                    self.assertEqual(result["state"], "READY_FOR_ANALYST")
                    self.assert_safe(result)

    def test_non_objects_and_upstream_unavailable_fail_closed(self):
        for source in (None, [], "CONTROL_TRANSFER_CANDIDATE", 1, {},
                       evaluate_control_transfer_evidence(None),
                       evaluate_control_transfer_evidence({})):
            with self.subTest(source=source):
                self.assert_blocked(source)

    def test_unknown_schema_state_and_malformed_values_fail_closed(self):
        for field, values in {
            "schema_version": [None, "UNKNOWN", [], {}],
            "state": [None, "BLOCKED", "NOT_AVAILABLE", "UNKNOWN", [], {}],
            "research_state": [None, "UNKNOWN", [], {}],
            "observations": [None, [], {}, {"higher_low": []}],
            "control_transfer_loop_closed": [False, 1, "true", None],
            "reason": [None, "OVERRIDDEN", {}],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    source = evaluation()
                    source[field] = value
                    self.assert_blocked(source)

    def test_every_required_field_is_required(self):
        for field in evaluation():
            with self.subTest(field=field):
                source = evaluation()
                del source[field]
                self.assert_blocked(source)

    def test_authority_violations_and_boolean_impostors_fail_closed(self):
        bad_values = {
            **{field: ["GRANTED", None, [], False] for field in (*AUTHORITY_FIELDS, "action_output")},
            "formal_season": ["SPRING", False, 0],
            "external_action_performed": [True, 0, "false"],
            "machine_may_determine_btc_season": [True, 0, "false"],
            "machine_may_confirm_bull_transition": [True, 0, "false"],
            "analyst_judgment_required": [False, 1, "true"],
        }
        for field, values in bad_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    source = evaluation()
                    source[field] = value
                    self.assert_blocked(source)

    def test_contradictory_observations_and_forged_research_state_fail_closed(self):
        source = evaluation()
        source["observations"]["higher_low"] = "NOT_OBSERVED"
        self.assert_blocked(source)
        source = evaluation()
        source["observations"]["invalidating_lower_low"] = "OBSERVED"
        self.assert_blocked(source)
        source = evaluation(1)
        source["research_state"] = "CONTROL_TRANSFER_CANDIDATE"
        source["control_transfer_loop_closed"] = True
        self.assert_blocked(source)
        source = evaluation()
        source["observations"]["unexpected"] = "CONFIRMED"
        self.assert_blocked(source)

    def test_schema_extensions_cannot_override_plan_or_eligibility(self):
        for field, value in {
            "final_eligibility": "REINFORCEMENT_ELIGIBLE",
            "plan_invalidated": True, "active_plan_id": "old-attack-plan",
            "capital_decision_authority": "MACHINE", "machine_execution": "ALLOWED",
            "production": "APPROVED", "authority": {"external_action_authority": "GRANTED"},
        }.items():
            with self.subTest(field=field):
                source = evaluation()
                source[field] = value
                self.assert_blocked(source)

    def test_work_a_snapshot_cannot_bypass_analyst_and_evaluator(self):
        snapshot = build_transition_replay_snapshot(
            structure_bars=[], weekly_bars=[], as_of="2026-09-19T00:00:00Z",
            old_control_high=100, old_control_zone_lower=90, old_control_zone_upper=100,
            candidate_invalidation_anchor=80, references_frozen_at="2026-09-01T00:00:00Z",
            reference_provenance="synthetic", weekly_provenance="synthetic",
        )
        self.assert_blocked(snapshot)
        # Even an asserted ready measurement snapshot has the wrong contract.
        snapshot["state"] = "READY_FOR_ANALYST"
        self.assert_blocked(snapshot)
        self.assert_blocked(snapshot["structure_measurements"])
        self.assert_blocked(snapshot["long_horizon_50wma_context"])

    def test_deterministic_non_mutating_and_no_shared_output_containers(self):
        for source in (evaluation(), evaluation(2), evaluation(1, "OBSERVED"), {}):
            original = deepcopy(source)
            first = translate(source)
            canonical = json.dumps(first, sort_keys=True, separators=(",", ":"))
            self.assertEqual(canonical, json.dumps(translate(source), sort_keys=True, separators=(",", ":")))
            first["required_downstream_gates"].clear()
            self.assertEqual(canonical, json.dumps(translate(source), sort_keys=True, separators=(",", ":")))
            self.assertEqual(source, original)


if __name__ == "__main__":
    unittest.main()
