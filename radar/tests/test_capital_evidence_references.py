"""Bound model reference vocabulary; all provider responses here are offline.

The failing response below is a small derived reference-only counterexample from
the one-shot real failure. The original provider object remains outside Git and
is replayed separately without modifying its bytes or repairing its references.
"""
from copy import deepcopy
import json
import unittest

from crt_radar import capital_decision_closure as capital
from crt_radar.openai_responses_adapter_contract import validate_request_envelope
from scripts import run_controlled_capital_acceptance as controlled
from tests.test_capital_decision_closure import item, leg, provider_response, recommendation

MAIN = "4bee34d0d674da785516809cb103ccef9645eee7"
NOW = 1790930000000


def evidence_enum(envelope):
    return envelope["request_body"]["text"]["format"]["schema"]["properties"][
        "items"]["items"]["properties"]["supporting_evidence"]["items"]["enum"]


class CapitalEvidenceReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = controlled.synthetic_case(at_ms=NOW, source_main_sha=MAIN)

    def setUp(self):
        self.source = deepcopy(self.case["source"])
        self.envelope = deepcopy(self.case["envelope"])

    def build(self, source=None):
        return capital.build_envelope(self.case["payload"], source or self.source,
                                      at_ms=NOW, full_decision=True)

    def rec(self):
        return json.loads(controlled.simulated_response(self.case)["output"][0]["content"][0]["text"])

    def test_current_source_defines_enum_and_reference_meanings(self):
        self.source["qualification"]["source_ref"] = "synthetic:qualification-only"
        envelope = self.build()
        self.assertEqual(set(evidence_enum(envelope)), {
            "bridge", "posture", "synthetic:fee-bound", "synthetic:qualified-account-facts"})
        self.assertEqual(envelope["evidence_reference_contract"], capital.EVIDENCE_REFERENCE_CONTRACT_VERSION)
        catalog = capital.evidence_reference_catalog(self.source)
        instructions = envelope["request_body"]["instructions"]
        self.assertEqual(json.loads(instructions.split("(code: meanings):\n", 1)[1]), catalog)
        self.assertIn("formal valuation", " ".join(catalog["bridge"]))
        self.assertIn("execution facts, not an investment rationale", " ".join(catalog["synthetic:fee-bound"]))
        self.assertIn("execution facts, not an investment rationale", " ".join(catalog["synthetic:qualified-account-facts"]))
        self.assertNotIn("synthetic:qualification-only", catalog)
        self.assertNotIn(self.source["evidence_validity"]["source_ref"], catalog)
        self.assertEqual(validate_request_envelope(envelope), envelope)

    def test_missing_optional_sources_do_not_create_allowed_codes(self):
        self.source.update(posture=None, fees=[], instruments=[])
        envelope = self.build()
        self.assertEqual(evidence_enum(envelope), ["bridge"])
        self.assertEqual(set(capital.evidence_reference_catalog(self.source)), {"bridge"})
        self.assertEqual(validate_request_envelope(envelope), envelope)

    def test_vocabulary_is_deterministic_and_actual_source_specific(self):
        first = self.build()
        self.source["fees"].reverse()
        self.source["instruments"].reverse()
        self.assertEqual(self.build(), first)
        for row in self.source["fees"]:
            row["source_ref"] = "synthetic:replacement-fee-proof"
        changed = self.build()
        self.assertNotIn("synthetic:fee-bound", evidence_enum(changed))
        self.assertIn("synthetic:replacement-fee-proof", evidence_enum(changed))
        self.assertNotEqual(changed["request_hash"], first["request_hash"])

    def test_legal_references_pass_independent_source_check(self):
        rec = self.rec()
        rec["items"][0]["supporting_evidence"] = evidence_enum(self.envelope)
        validated = capital.validate_recommendation(rec, self.source, at_ms=NOW)
        self.assertEqual(validated["items"][0]["validation_state"], "VALIDATED_NON_TRADING_WAIT")
        receipt = capital.validated_receipt(provider_response(rec), self.envelope, at_ms=NOW)
        self.assertIn("capital_validation", receipt)

    def test_derived_real_failure_references_remain_invalid_and_unchanged(self):
        # Only the decision scopes/actions/reference defects are retained here.
        # Do not normalize field paths or descriptive labels into legal codes.
        rec = recommendation(
            item("WAIT", supporting_evidence=[
                "market_context.treasury_valuation_context.MSTR.evidence_authority=BLOCKED",
                "capital.spending_cap.amount_usd=700.00", "user_intent.reserved_usd=100"]),
            item("HOLD", scope="MSTR-existing", supporting_evidence=[
                "capital.holdings：MSTR數量12.0",
                "posture.formal_season=NOT_DETERMINED且rail=RESEARCH_ONLY"]),
            item("WAIT", asset="STRC", scope="STRC-addition", supporting_evidence=[
                "capital.holdings：STRC數量75.0",
                "market_context.distillation.note：資料為合成市場與合成資本"]))
        response = provider_response(rec)
        before = deepcopy(response)
        with self.assertRaisesRegex(ValueError, "RESPONSE_ENUM_MISMATCH"):
            capital._check_shape(rec, self.envelope["request_body"]["text"]["format"]["schema"])
        with self.assertRaisesRegex(ValueError, "EVIDENCE_REFERENCE_UNKNOWN"):
            capital.validated_receipt(response, self.envelope, at_ms=NOW)
        self.assertEqual(response, before)
        for entry in rec["items"]:
            isolated = self.rec()
            target = next(row for row in isolated["items"] if row["decision_scope"] == entry["decision_scope"])
            target["supporting_evidence"] = entry["supporting_evidence"]
            with self.subTest(scope=entry["decision_scope"]), self.assertRaisesRegex(ValueError, "EVIDENCE_REFERENCE_UNKNOWN"):
                capital.validate_recommendation(isolated, self.source, at_ms=NOW)

    def test_legal_reference_does_not_qualify_invalid_transaction(self):
        for defect in ("missing_cash_qualification", "missing_fee", "blocked_valuation", "quantity_step"):
            with self.subTest(defect=defect):
                source = deepcopy(self.source)
                rec = self.rec()
                target = next(row for row in rec["items"] if row["asset"] == "STRC")
                if defect == "missing_cash_qualification":
                    source["qualification"] = None
                elif defect == "missing_fee":
                    source["fees"] = []
                elif defect == "blocked_valuation":
                    target = next(row for row in rec["items"] if row["decision_scope"] == "MSTR-addition")
                    target.update(action="BUY", wait_kind=None, blockers=[], legs=[leg()])
                else:
                    target["legs"][0]["quantity"] = 1.5
                self.assertEqual(target["supporting_evidence"], ["bridge"])
                envelope = self.build(source)
                with self.assertRaises(ValueError):
                    capital.validated_receipt(provider_response(rec), envelope, at_ms=NOW)
                # A fee/specification code is permitted by the wire vocabulary,
                # but does not satisfy the independent investment evidence rule.
                rec = self.rec()
                rec["items"][1]["supporting_evidence"] = [self.source["fees"][0]["source_ref"]]
                with self.assertRaisesRegex(ValueError, "INVESTMENT_EVIDENCE_REQUIRED"):
                    capital.validate_recommendation(rec, self.source, at_ms=NOW)

    def test_strict_saved_legacy_envelope_replay_preserves_failure_and_hash(self):
        legacy = capital._build_envelope(self.case["payload"], self.source,
            at_ms=NOW, full_decision=True, legacy_references=True)
        self.assertNotIn("evidence_reference_contract", legacy)
        self.assertEqual(legacy["request_body"]["instructions"], capital.LEGACY_INSTRUCTIONS)
        self.assertEqual(legacy["request_body"]["text"]["format"], capital.response_format())
        before = deepcopy(legacy)
        self.assertEqual(validate_request_envelope(legacy), legacy)
        rec = self.rec()
        rec["items"][0]["supporting_evidence"] = ["capital.spending_cap.amount_usd=700.00"]
        with self.assertRaisesRegex(ValueError, "EVIDENCE_REFERENCE_UNKNOWN"):
            capital.validated_receipt(provider_response(rec), legacy, at_ms=NOW)
        self.assertEqual(legacy, before)
        # New bodies cannot masquerade as saved legacy requests after resealing.
        for defect in ("remove_marker", "wrong_marker", "unknown_enum"):
            changed = deepcopy(self.envelope)
            if defect == "remove_marker":
                changed.pop("evidence_reference_contract")
            elif defect == "wrong_marker":
                changed["evidence_reference_contract"] = "unknown-reference-contract"
            else:
                evidence_enum(changed).append("fake")
            changed["request_hash"] = capital.digest({key: value for key, value in changed.items() if key != "request_hash"})
            with self.subTest(defect=defect), self.assertRaisesRegex(ValueError, "CAPITAL_ENVELOPE_MISMATCH"):
                validate_request_envelope(changed)


if __name__ == "__main__":
    unittest.main()
