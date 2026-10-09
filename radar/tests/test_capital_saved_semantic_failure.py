"""Replay the exact all-synthetic second real output, with no provider request.

The fixture is a byte-for-byte copy of output_text plus its saved newline. The
full immutable provider record and consumed approval remain outside the repo.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from crt_radar import capital_decision_closure as capital
from crt_radar import gpt_transport_worker as worker
from scripts import run_controlled_capital_acceptance as controlled

MAIN = "4bee34d0d674da785516809cb103ccef9645eee7"
NOW = 1790930000000
FIXTURE = Path(__file__).parent / "fixtures" / "capital_second_real_output.json"
FIXTURE_SHA = "0eb2c120755bbc1d017b32fa9cce0f2443a295b1d9d7ae2d66e7d0c9c6cd3291"


class SavedSecondRealSemanticFailureTests(unittest.TestCase):
    def setUp(self):
        self.original = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(self.original).hexdigest(), FIXTURE_SHA)
        self.case = controlled.synthetic_case(at_ms=NOW, source_main_sha=MAIN)
        self.response = {"id": "resp_saved_synthetic_output", "model": "gpt-5.6-luna",
            "status": "completed", "output": [{"type": "message", "status": "completed",
                "content": [{"type": "output_text", "text": self.original.decode("utf-8")}]}]}

    def tearDown(self):
        self.assertEqual(FIXTURE.read_bytes(), self.original)

    def historical_envelope(self):
        return capital._build_envelope(self.case["payload"], self.case["source"],
            at_ms=NOW, full_decision=True, legacy_semantics=True)

    def test_exact_saved_hold_remains_blocked_and_disclosed_without_qualified_receipt(self):
        historical = self.historical_envelope()
        assessment = capital.assess_response(self.response, historical, at_ms=NOW)
        hold = next(row for row in assessment["items"] if row["decision_scope"] == "MSTR-existing")
        self.assertEqual((hold["action"], hold["validation_state"]), ("HOLD", "BLOCKED"))
        original = json.loads(self.original)
        original_hold = next(row for row in original["items"] if row["decision_scope"] == "MSTR-existing")
        self.assertEqual(hold["blockers"], original_hold["blockers"])
        with self.assertRaisesRegex(ValueError, "CAPITAL_RECOMMENDATION_NOT_VALIDATED"):
            capital.validated_receipt(self.response, historical, at_ms=NOW)
        review = worker._capital_blocked_review(self.response, historical, at_ms=NOW,
            failure=ValueError("CAPITAL_RECOMMENDATION_NOT_VALIDATED"))
        self.assertFalse(review["qualified"])
        self.assertTrue(review["assessment_available"])
        self.assertIn("正式估值資料不足", review["message"])
        self.assertIn("續抱", review["message"])

    def test_new_contract_rejects_original_output_without_repairing_it(self):
        before = deepcopy(self.response)
        self.assertNotIn("reasoning_contract", json.loads(self.original))
        with self.assertRaises(ValueError):
            capital.validated_receipt(self.response, self.case["envelope"], at_ms=NOW)
        self.assertEqual(self.response, before)
        self.assertIn("BTC一日變動為負", self.original.decode("utf-8"))

    def test_negative_market_change_has_neither_btc_attribution_nor_invented_clock(self):
        projection = json.loads(self.case["envelope"]["request_body"]["input"])
        catalog = capital.semantic_evidence_catalog(projection)
        path = "/market_context/changes/synthetic_market_direction/horizons/1d/percent_change"
        fact = catalog[path]
        self.assertEqual(fact["subject_asset"], "UNATTRIBUTED")
        self.assertEqual(json.loads(fact["value_json"]), -2.5)
        self.assertIsNone(fact["source_time_ms"])
        # The event's BTC wake is a trigger, never the missing metric identity.
        self.assertIn("BTC_INTRADAY", self.case["payload"]["event"]["wake"]["wake_sources"])


if __name__ == "__main__":
    unittest.main()
