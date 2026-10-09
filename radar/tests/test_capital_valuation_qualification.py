"""Claim-scoped formal valuation receipt gates; synthetic scenarios only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from crt_radar import capital_decision_closure as c
from crt_radar.gpt_handoff import build_minimized_bridge_payload, expand_bridge_field_names
from tests.test_full_bridge_budget import captured_pack, handoff_for
from tests.test_capital_decision_closure import (
    NOW, source_fixture, item, leg, recommendation, match_scopes, full_provider_response,
)


class FormalValuationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        pack = captured_pack()
        self.base = expand_bridge_field_names(build_minimized_bridge_payload(
            pack, handoff_for(pack, Path(self.temp.name))))

    def receipt(self, rec, section):
        payload = deepcopy(self.base)
        if section is None:
            payload["market_context"].pop("treasury_valuation_context", None)
        else:
            payload["market_context"]["treasury_valuation_context"] = section
        # Independent, explicitly attributed synthetic price facts let this
        # suite exercise the formal-valuation gate rather than fail the new
        # comparison schema first. They grant no formal mNAV qualification.
        buy_assets = {trade["asset"] for row in rec["items"] for trade in row["legs"]
                      if trade["action"] == "BUY"}
        payload["market_context"].setdefault("changes", {})["synthetic_investment_inputs"] = {
            asset: {"asset": asset, "price_usd": 100, "history_state": "AVAILABLE", "as_of_ms": NOW}
            for asset in sorted(buy_assets)}
        # New unpublished synthetic case, never rewrite an existing outbox event.
        payload["event"]["event_id"] = c.digest({"case": section, "recommendation": rec})
        payload["bridge_payload_hash"] = c.digest({k: v for k, v in payload.items() if k != "bridge_payload_hash"})
        source = source_fixture(payload)
        match_scopes(source, rec)
        envelope = c.build_envelope(payload, source, at_ms=NOW, full_decision=True)
        response = full_provider_response(rec, envelope)
        supplied = json.loads(response["output"][0]["content"][0]["text"])
        catalog = c.semantic_evidence_catalog(json.loads(envelope["request_body"]["input"]))
        for row in supplied["items"]:
            assets = {trade["asset"] for trade in row["legs"] if trade["action"] == "BUY"}
            if not assets:
                continue
            paths = ["/market_context/changes/synthetic_investment_inputs/" + asset + "/price_usd"
                     for asset in sorted(assets)] + ["/spending_cap"]
            row["reasoning_support"]["claim_bindings"] = [{"source_path": path,
                **{key: catalog[path][key] for key in ("subject_asset", "metric_basis", "value_json")}}
                for path in paths]
            row["reasoning_support"]["cash_comparison"] = {"state": "SOURCE_SUPPORTED",
                "evidence_paths": paths, "missing_evidence": [],
                "rationale": "僅核對已提供的合成價格與資金；不證明投資因果推理。"}
        response["output"][0]["content"][0]["text"] = json.dumps(supplied, ensure_ascii=False)
        return c.validated_receipt(response, envelope, at_ms=NOW)

    def test_mstr_asst_buy_missing_section_row_or_blocked_is_rejected(self):
        for asset in ("MSTR", "ASST"):
            other = "ASST" if asset == "MSTR" else "MSTR"
            for section in (None, {}, {other: {"formal_action_critical_state": "AVAILABLE"}},
                            {asset: {"formal_action_critical_state": "BLOCKED"}}):
                with self.subTest(asset=asset, section=section):
                    with self.assertRaisesRegex(ValueError, "VALUATION_EVIDENCE_UNQUALIFIED:" + asset):
                        self.receipt(recommendation(item(asset=asset, legs=[leg(asset=asset)])), section)

    def test_rotation_checks_its_mstr_asst_buy_leg(self):
        for asset in ("MSTR", "ASST"):
            rec = recommendation(item("ROTATE", asset="STRC", legs=[
                leg("SELL", asset="STRC", leg_id="sale"),
                leg("BUY", asset=asset, leg_id="purchase", dependent_legs=["sale"])]))
            for section in (None, {"STRC": {"formal_action_critical_state": "AVAILABLE"}},
                            {asset: {"formal_action_critical_state": "BLOCKED"}}):
                with self.subTest(asset=asset, section=section):
                    with self.assertRaisesRegex(ValueError, "VALUATION_EVIDENCE_UNQUALIFIED:" + asset):
                        self.receipt(rec, section)
            receipt = self.receipt(rec, {asset: {"formal_action_critical_state": "AVAILABLE"}})
            self.assertEqual(receipt["capital_validation"]["items"][0]["validation_state"], "VALIDATED")

    def test_strc_sata_buy_has_no_common_equity_mnav_requirement(self):
        for asset in ("STRC", "SATA"):
            for section in (None, {asset: {"formal_action_critical_state": "BLOCKED"}}):
                with self.subTest(asset=asset, section=section):
                    receipt = self.receipt(recommendation(item(asset=asset, legs=[leg(asset=asset)])), section)
                    self.assertEqual(receipt["capital_validation"]["items"][0]["validation_state"], "VALIDATED")

    def test_rotation_sell_source_valuation_does_not_block_strc_buy(self):
        rec = recommendation(item("ROTATE", legs=[leg("SELL", leg_id="sale"),
            leg("BUY", asset="STRC", leg_id="purchase", dependent_legs=["sale"])]))
        receipt = self.receipt(rec, {"MSTR": {"formal_action_critical_state": "BLOCKED"}})
        self.assertEqual(receipt["capital_validation"]["items"][0]["validation_state"], "VALIDATED")

    def test_available_common_equity_buy_and_independent_non_buy_claims_survive(self):
        for asset in ("MSTR", "ASST"):
            receipt = self.receipt(recommendation(item(asset=asset, legs=[leg(asset=asset)])),
                                   {asset: {"formal_action_critical_state": "AVAILABLE"}})
            self.assertEqual(receipt["capital_validation"]["items"][0]["validation_state"], "VALIDATED")
        for action in ("SELL", "HOLD", "WAIT"):
            with self.subTest(action=action):
                receipt = self.receipt(recommendation(item(action)), None)
                self.assertEqual(receipt["capital_validation"]["items"][0]["validation_state"], "VALIDATED")


if __name__ == "__main__":
    unittest.main()
