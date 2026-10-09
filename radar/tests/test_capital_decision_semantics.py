"""Offline factual-binding counterexamples; no claim of automatic thesis proof."""
from copy import deepcopy
import json
import unittest

from crt_radar import capital_decision_closure as capital
from crt_radar.openai_responses_adapter_contract import validate_request_envelope
from scripts import run_controlled_capital_acceptance as controlled
from tests.test_capital_decision_closure import leg, provider_response

NOW = 1791499626351
MAIN = "4bee34d0d674da785516809cb103ccef9645eee7"
UNATTRIBUTED_CHANGE = "/market_context/changes/synthetic_market_direction/horizons/1d/percent_change"


class CapitalDecisionSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = controlled.synthetic_case(at_ms=NOW, source_main_sha=MAIN)

    def setUp(self):
        self.case = deepcopy(type(self).case)
        self.envelope = self.case["envelope"]
        self.source = self.case["source"]
        self.rec = json.loads(controlled.simulated_response(self.case)["output"][0]["content"][0]["text"])
        self.catalog = capital.semantic_evidence_catalog(json.loads(self.envelope["request_body"]["input"]))

    def target(self, scope="STRC-addition"):
        return next(row for row in self.rec["items"] if row["decision_scope"] == scope)

    def binding(self, path, catalog=None):
        fact = (catalog or self.catalog)[path]
        return {"source_path": path, **{key: fact[key] for key in ("subject_asset", "metric_basis", "value_json")}}

    def assess(self, rec=None, envelope=None):
        return capital.assess_response(provider_response(rec or self.rec), envelope or self.envelope, at_ms=NOW)

    def bound_comparison(self, target, *paths, catalog=None):
        target["reasoning_support"]["claim_bindings"] = [self.binding(path, catalog) for path in paths]
        target["reasoning_support"]["cash_comparison"].update(state="SOURCE_SUPPORTED",
            evidence_paths=list(paths), missing_evidence=[], rationale="僅比較所提供的合成事實，因果判斷仍待審查。")

    def strc_observation(self, *, qualification=True):
        # A new explicitly attributed, sealed synthetic input. The saved real
        # case and its unassigned direction are never altered or normalized.
        payload = deepcopy(self.case["payload"])
        payload["market_context"]["changes"]["synthetic_strc_direction"] = {
            "asset": "STRC", "horizons": {"1d": {"percent_change": 2.5,
                "history_state": "AVAILABLE", "as_of_ms": NOW}}}
        payload["bridge_payload_hash"] = capital.digest({k: v for k, v in payload.items() if k != "bridge_payload_hash"})
        source = deepcopy(self.source)
        source["bridge_payload_hash"] = payload["bridge_payload_hash"]
        if not qualification:
            source["qualification"] = None
        envelope = capital.build_envelope(payload, source, at_ms=NOW, full_decision=True)
        catalog = capital.semantic_evidence_catalog(json.loads(envelope["request_body"]["input"]))
        path = "/market_context/changes/synthetic_strc_direction/horizons/1d/percent_change"
        return envelope, source, catalog, path

    def test_new_full_schema_binds_real_paths_and_preserves_unassigned_asset_clock(self):
        self.assertEqual(self.envelope["decision_semantics_contract"], capital.DECISION_SEMANTICS_CONTRACT_VERSION)
        schema = self.envelope["request_body"]["text"]["format"]["schema"]
        self.assertIn("reasoning_contract", schema["required"])
        properties = schema["properties"]["items"]["items"]["properties"]
        self.assertIn("reasoning_support", properties)
        paths = properties["reasoning_support"]["properties"]["claim_bindings"]["items"]["properties"]["source_path"]["enum"]
        self.assertEqual(paths, list(self.catalog))
        fact = self.catalog[UNATTRIBUTED_CHANGE]
        self.assertEqual(fact["subject_asset"], "UNATTRIBUTED")
        self.assertIsNone(fact["source_time_ms"])
        self.assertEqual(fact["value_json"], "-2.5")
        self.assertNotIn("/event/wake/wake_sources/0", self.catalog)
        self.assertNotIn("/source_main_sha", self.catalog)

    def test_false_btc_attribution_is_rejected_without_rewriting_response(self):
        target = self.target()
        binding = self.binding(UNATTRIBUTED_CHANGE)
        binding["subject_asset"] = "BTC"
        target["reasoning_support"]["claim_bindings"] = [binding]
        target["reasoning_support"]["cash_comparison"]["evidence_paths"] = [UNATTRIBUTED_CHANGE]
        response = provider_response(self.rec)
        original = deepcopy(response)
        with self.assertRaisesRegex(ValueError, "CLAIM_ASSET_ATTRIBUTION_MISMATCH"):
            capital.assess_response(response, self.envelope, at_ms=NOW)
        self.assertEqual(response, original)

    def test_exact_binding_does_not_prove_false_free_prose_investment_reasoning(self):
        target = self.target()
        target["contradictions"] = ["BTC一日變動為負，因此STRC優於現金。"]
        validation = self.assess()
        self.assertEqual(validation["reasoning_review"]["free_prose_reasoning"], "NOT_YET_PROVEN")
        self.assertTrue(all(row["investment_reasoning"] == "NOT_YET_PROVEN" for row in validation["reasoning_review"]["items"]))
        self.assertIn("投資因果推理仍為 NOT_YET_PROVEN", capital.render(validation))

    def test_altered_value_and_unbound_cash_comparison_are_rejected(self):
        for defect in ("value", "comparison"):
            with self.subTest(defect=defect):
                rec = deepcopy(self.rec)
                target = next(row for row in rec["items"] if row["asset"] == "STRC")
                if defect == "value":
                    target["reasoning_support"]["claim_bindings"][0]["value_json"] = "1000000"
                    error = "CLAIM_VALUE_MISMATCH"
                else:
                    target["reasoning_support"]["cash_comparison"]["evidence_paths"] = [UNATTRIBUTED_CHANGE]
                    error = "CASH_COMPARISON_UNBOUND_SOURCE"
                with self.assertRaisesRegex(ValueError, error):
                    self.assess(rec)

    def test_research_mnav_cannot_be_relabelled_as_formal(self):
        projection = json.loads(self.envelope["request_body"]["input"])
        # These are explicit helper-only synthetic inputs, not a requalification
        # of the saved blocked formal source or a modified production engine.
        valuation = projection["market_context"]["treasury_valuation_context"]
        valuation["MSTR"].update(diluted_mnav=1.4,
            source_semantic="STRATEGYTRACKER_DILUTED_MNAV_RESEARCH", formal_action_critical_state="BLOCKED")
        valuation["ASST"].update(diluted_mnav=1.2,
            source_semantic="CRT_FORMAL_DILUTED_EQUITY_MNAV", formal_action_critical_state="AVAILABLE")
        valuation["ASST"]["preferred_funding_attribution_summary"] = {"research_only": True,
            "nested": {"source_semantic": "CRT_FORMAL_DILUTED_EQUITY_MNAV", "diluted_mnav": 99}}
        catalog = capital.semantic_evidence_catalog(projection)
        research_path = "/market_context/treasury_valuation_context/MSTR/diluted_mnav"
        formal_path = "/market_context/treasury_valuation_context/ASST/diluted_mnav"
        self.assertEqual(catalog[research_path]["metric_basis"], "RESEARCH_SECONDARY")
        self.assertEqual(catalog[formal_path]["metric_basis"], "FORMAL_DILUTED_EQUITY_MNAV")
        nested = "/market_context/treasury_valuation_context/ASST/preferred_funding_attribution_summary/nested/diluted_mnav"
        self.assertEqual(catalog[nested]["metric_basis"], "RESEARCH_SECONDARY")
        rec = deepcopy(self.rec)
        target = next(row for row in rec["items"] if row["decision_scope"] == "MSTR-addition")
        target["reasoning_support"]["claim_bindings"] = [self.binding(research_path, catalog)]
        target["reasoning_support"]["cash_comparison"]["evidence_paths"] = [research_path]
        capital._reasoning_review(rec, catalog, self.source, at_ms=NOW)
        target["reasoning_support"]["claim_bindings"][0]["metric_basis"] = "FORMAL_DILUTED_EQUITY_MNAV"
        with self.assertRaisesRegex(ValueError, "CLAIM_METRIC_BASIS_MISMATCH"):
            capital._reasoning_review(rec, catalog, self.source, at_ms=NOW)

    def test_fees_specs_and_holdings_cannot_be_cash_alternative_investment_basis(self):
        for path in ("/capital/holdings/1/quantity", "/instruments/3/quantity_step", "/fees/6/upper_bound_usd"):
            with self.subTest(path=path):
                rec = deepcopy(self.rec)
                target = next(row for row in rec["items"] if row["asset"] == "STRC")
                target["supporting_evidence"] = list(capital.evidence_reference_catalog(self.source))
                self.bound_comparison(target, path, "/spending_cap")
                with self.assertRaisesRegex(ValueError, "CASH_COMPARISON_ASSET_EVIDENCE_REQUIRED"):
                    self.assess(rec)

    def test_qualified_asset_fact_and_cash_basis_can_be_bound_without_strc_mnav(self):
        envelope, source, catalog, path = self.strc_observation()
        target = self.target()
        target.update(action="BUY", wait_kind=None, blockers=[], legs=[leg(asset="STRC", quantity=1)])
        self.bound_comparison(target, path, "/spending_cap", catalog=catalog)
        receipt = capital.validated_receipt(provider_response(self.rec), envelope, at_ms=NOW)
        self.assertEqual(receipt["capital_validation"]["reasoning_review"]["free_prose_reasoning"], "NOT_YET_PROVEN")
        capital.assert_current(receipt["capital_validation"], source, at_ms=NOW)
        self.assertNotIn("STRC", json.loads(envelope["request_body"]["input"])["market_context"]["treasury_valuation_context"])

    def test_other_asset_or_unqualified_cash_does_not_support_strc_comparison(self):
        envelope, _, catalog, path = self.strc_observation(qualification=False)
        target = self.target()
        self.bound_comparison(target, path, "/spending_cap", catalog=catalog)
        with self.assertRaisesRegex(ValueError, "CASH_COMPARISON_QUALIFIED_CASH_REQUIRED"):
            self.assess(envelope=envelope)
        target["asset"] = "MSTR"
        with self.assertRaisesRegex(ValueError, "CASH_COMPARISON_ASSET_EVIDENCE_REQUIRED"):
            capital._reasoning_review(self.rec, catalog, self.source, at_ms=NOW)

    def test_insufficient_comparison_requires_named_gap_and_blocks_new_buy_or_rotate_receipt(self):
        target = self.target()
        target["reasoning_support"]["cash_comparison"]["missing_evidence"] = []
        with self.assertRaisesRegex(ValueError, "CASH_COMPARISON_MISSING_EVIDENCE_REQUIRED"):
            self.assess()
        target["reasoning_support"]["cash_comparison"]["missing_evidence"] = ["缺少STRC收益及風險比較來源。"]
        target.update(action="BUY", wait_kind=None, blockers=[], legs=[leg(asset="STRC", quantity=1)])
        with self.assertRaisesRegex(ValueError, "INVESTMENT_COMPARISON_NOT_SOURCE_SUPPORTED:STRC-addition"):
            capital.validated_receipt(provider_response(self.rec), self.envelope, at_ms=NOW)
        target.update(action="WAIT", wait_kind="EVIDENCE_BLOCKED", blockers=["缺少STRC比較證據。"], legs=[])
        existing = self.target("MSTR-existing")
        existing.update(action="ROTATE", legs=[leg("SELL", quantity=1, leg_id="sell"),
            leg("BUY", "STRC", quantity=1, leg_id="buy", dependent_legs=["sell"])])
        with self.assertRaisesRegex(ValueError, "INVESTMENT_COMPARISON_NOT_SOURCE_SUPPORTED:MSTR-existing"):
            capital.validated_receipt(provider_response(self.rec), self.envelope, at_ms=NOW)

    def test_hold_keeps_current_gaps_blocked_without_becoming_wait(self):
        existing = self.target("MSTR-existing")
        existing.update(blockers=["正式估值與策略条件不足以支持合格續抱。"],
            contradictions=["已確認的支持證據存在反向風險。"], invalidation="未來支持證據失效則重判。")
        validation = self.assess()
        row = next(row for row in validation["items"] if row["decision_scope"] == "MSTR-existing")
        self.assertEqual((row["action"], row["validation_state"]), ("HOLD", "BLOCKED"))
        self.assertEqual(row["blockers"], existing["blockers"])
        self.assertIn("沒有改寫為新增部位等待", capital.render(validation))
        with self.assertRaisesRegex(ValueError, "CAPITAL_RECOMMENDATION_NOT_VALIDATED"):
            capital.validated_receipt(provider_response(self.rec), self.envelope, at_ms=NOW)

    def test_governance_and_opposition_do_not_automatically_block_legal_hold(self):
        existing = self.target("MSTR-existing")
        existing.update(blockers=[], contradictions=["估值風險仍須持續核對。"], invalidation="未來估值證據惡化時重判。")
        validation = self.assess()
        row = next(row for row in validation["items"] if row["decision_scope"] == "MSTR-existing")
        self.assertEqual(row["validation_state"], "VALIDATED")
        self.assertEqual(validation["governance"], capital.LOCKS)
        instructions = self.envelope["request_body"]["instructions"]
        for phrase in ("not a HOLD blocker", "Never hide actual missing valuation", "EXISTING scope into WAIT",
                       "contradictions are opposing evidence", "invalidation describes future conditions"):
            self.assertIn(phrase, instructions)

    def test_historical_enum_and_pre_enum_envelopes_are_strict_and_no_semantics_downgrade(self):
        for args in ({"legacy_semantics": True}, {"legacy_references": True}):
            with self.subTest(args=args):
                envelope = capital._build_envelope(self.case["payload"], self.source, at_ms=NOW,
                    full_decision=True, **args)
                self.assertNotIn("decision_semantics_contract", envelope)
                self.assertNotIn("reasoning_contract", envelope["request_body"]["text"]["format"]["schema"]["properties"])
                self.assertEqual(validate_request_envelope(envelope), envelope)
                base = capital._base_recommendation(self.rec)
                result = self.assess(base, envelope)
                self.assertNotIn("reasoning_review", result)
        for defect in ("remove_marker", "wrong_marker"):
            changed = deepcopy(self.envelope)
            if defect == "remove_marker":
                changed.pop("decision_semantics_contract")
            else:
                changed["decision_semantics_contract"] = "unknown"
            changed["request_hash"] = capital.digest({k: v for k, v in changed.items() if k != "request_hash"})
            with self.subTest(defect=defect), self.assertRaisesRegex(ValueError, "CAPITAL_ENVELOPE_MISMATCH"):
                validate_request_envelope(changed)


if __name__ == "__main__":
    unittest.main()
