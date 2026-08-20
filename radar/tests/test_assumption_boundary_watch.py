from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crt_radar.assumption_boundary_watch import evaluate_assumption_watch, load_assumption_watch_context


class AssumptionBoundaryWatchTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "state": "AVAILABLE",
            "context": {
                "schema_version": "CRT_ASSUMPTION_RESEARCH_CONTEXT_V0.1",
                "valid_until_ms": 9999999999999,
                "formal_model_modification_authority": "NONE",
                "external_action_authority": "NONE",
                "btc_q4_lower_entry_hypothesis": {
                    "state": "ACTIVE_RESEARCH_HYPOTHESIS",
                    "reference_target_usd": 57000,
                },
            },
        }

    def gate(self, transition: str, eligibility: str, constructive: bool = True):
        return {
            "state": "READY_FOR_ANALYST",
            "transition_state": transition,
            "decision_eligibility": eligibility,
            "research_corridor": {"formal_threshold_authority": "NONE"},
            "mechanism_support": {"constructive": constructive},
        }

    def test_bull_acceptance_challenges_lower_entry_base_case(self):
        result = evaluate_assumption_watch(
            btc_entry_gate=self.gate("BULL_ACCEPTANCE_STRENGTHENED", "PROBE_ELIGIBLE", True),
            research_context=self.context,
        )
        rows = {row["id"]: row for row in result["assumptions"]}
        self.assertEqual(result["state"], "CHALLENGED")
        self.assertEqual(rows["BTC_Q4_LOWER_ENTRY_HYPOTHESIS"]["status"], "CHALLENGED")
        self.assertEqual(rows["BTC_Q4_LOWER_ENTRY_HYPOTHESIS"]["reference_target_usd"], 57000)

    def test_bear_rejection_keeps_lower_entry_hypothesis_active(self):
        result = evaluate_assumption_watch(
            btc_entry_gate=self.gate("BEAR_REJECTION_STRENGTHENED", "WAIT", False),
            research_context=self.context,
        )
        rows = {row["id"]: row for row in result["assumptions"]}
        self.assertEqual(rows["BTC_Q4_LOWER_ENTRY_HYPOTHESIS"]["status"], "VALID")
        self.assertIn("BEAR_REJECTION", rows["BTC_Q4_LOWER_ENTRY_HYPOTHESIS"]["evidence"])

    def test_probe_without_constructive_mechanism_challenges_decision_boundary(self):
        result = evaluate_assumption_watch(
            btc_entry_gate=self.gate("BULL_ACCEPTANCE_STRENGTHENED", "PROBE_ELIGIBLE", False),
            research_context=self.context,
        )
        rows = {row["id"]: row for row in result["assumptions"]}
        self.assertEqual(rows["PRICE_ONLY_CANNOT_PROMOTE_ENTRY"]["status"], "CHALLENGED")

    def test_formal_corridor_authority_blocks_boundary(self):
        gate = self.gate("TRANSITION_UNRESOLVED", "WAIT", False)
        gate["research_corridor"]["formal_threshold_authority"] = "YES"
        result = evaluate_assumption_watch(btc_entry_gate=gate, research_context=self.context)
        rows = {row["id"]: row for row in result["assumptions"]}
        self.assertEqual(rows["EVENT_CORRIDOR_IS_RESEARCH_ONLY"]["status"], "BLOCKED")

    def test_expired_local_context_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "assumptions.json"
            path.write_text(
                '{"schema_version":"CRT_ASSUMPTION_RESEARCH_CONTEXT_V0.1","valid_until_ms":1,"formal_model_modification_authority":"NONE","external_action_authority":"NONE"}',
                encoding="utf-8",
            )
            loaded = load_assumption_watch_context(path, now_ms=2)
            self.assertEqual(loaded["state"], "BLOCKED")
            self.assertEqual(loaded["reason"], "ASSUMPTION_RESEARCH_CONTEXT_EXPIRED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
