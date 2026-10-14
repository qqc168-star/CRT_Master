"""Q0 full-analysis publication tests; fixtures are synthetic, not investment evidence."""
from __future__ import annotations

from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path

from crt_radar.analysis_360_delivery import (digest, review_360_delivery,
    initialize_360_manifest, main)
from test_analysis_coverage_gate import fixture


def sample(*, multi_scope=False):
    pack, report = fixture()
    rows = [{"decision_scope": f"{asset}-existing", "asset": asset, "action": "WAIT"}
            for asset in ("MSTR", "ASST", "STRC", "SATA")]
    if multi_scope:
        rows += [{"decision_scope": "MSTR-addition", "asset": "MSTR", "action": "BUY"}]
    validation = {"evidence_lineage": pack["evidence_pack_hash"],
                  "evaluated_at_ms": pack["generated_at_ms"] + 1000,
                  "recommendation": {"items": deepcopy(rows)},
                  "items": [{**item, "validation_state": "VALIDATED"} for item in rows]}
    validation["validation_hash"] = digest(validation)
    receipt = {"state": "RESPONSES_DELIVERY_RECEIPT_READY", "event_id": "synthetic-test-event",
               "production": "NOT_APPROVED", "external_action_authority": "NONE",
               "action_output": "NONE", "capital_validation": validation}
    receipt["receipt_hash"] = digest(receipt)
    report["event_id"] = receipt["event_id"]
    report["capital_receipt_hash"] = receipt["receipt_hash"]
    report["action_scopes"] = deepcopy(rows)
    return pack, report, receipt


class Q0PublicationWiringTests(unittest.TestCase):
    def test_real_linkage_with_blocked_organs_is_only_q5_pending(self):
        pack, report, receipt = sample()
        result = review_360_delivery(report, pack, receipt)
        self.assertEqual(result["publication_state"], "REVIEWED_WITH_BLOCKERS_Q5_PENDING")
        self.assertEqual(result["problems"], [])
        self.assertEqual(len(result["validated_action_scopes"]), 4)
        self.assertEqual(result["reasoning_state"], "NOT_YET_PROVEN")
        self.assertFalse(result["may_claim_crt_360_complete"])
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertEqual(result["review_receipt_hash"], digest({k:v for k,v in result.items() if k != "review_receipt_hash"}))

    def test_wrong_market_pack_is_rejected_even_with_structurally_complete_report(self):
        pack, report, receipt = sample()
        receipt["capital_validation"]["evidence_lineage"] = "0" * 64
        receipt["capital_validation"]["validation_hash"] = digest({
            k:v for k,v in receipt["capital_validation"].items() if k != "validation_hash"})
        receipt["receipt_hash"] = digest({k:v for k,v in receipt.items() if k != "receipt_hash"})
        report["capital_receipt_hash"] = receipt["receipt_hash"]
        result = review_360_delivery(report, pack, receipt)
        self.assertIn("CAPITAL_PACK_LINEAGE_MISMATCH", result["problems"])
        self.assertEqual(result["publication_state"], "REJECTED")

    def test_broken_receipt_or_validation_hash_is_rejected(self):
        pack, report, receipt = sample()
        receipt["capital_validation"]["evaluated_at_ms"] += 1
        result = review_360_delivery(report, pack, receipt)
        self.assertIn("CAPITAL_RECEIPT_HASH_INVALID", result["problems"])
        self.assertIn("CAPITAL_VALIDATION_HASH_INVALID", result["problems"])

    def test_one_missing_or_changed_action_scope_is_rejected(self):
        pack, report, receipt = sample()
        report["action_scopes"].pop()
        result = review_360_delivery(report, pack, receipt)
        self.assertIn("REPORT_CAPITAL_ACTION_SCOPES_MISMATCH", result["problems"])
        pack, report, receipt = sample()
        report["action_scopes"][0]["action"] = "SELL"
        result = review_360_delivery(report, pack, receipt)
        self.assertIn("REPORT_CAPITAL_ACTION_SCOPES_MISMATCH", result["problems"])

    def test_multi_scope_hold_and_wait_can_be_distinguished(self):
        pack, report, receipt = sample(multi_scope=True)
        result = review_360_delivery(report, pack, receipt)
        self.assertEqual(result["problems"], [])
        self.assertEqual(len(result["validated_action_scopes"]), 5)
        report["actions"]["MSTR"]["action"] = "SELL"
        self.assertIn("REPORT_PRIMARY_ACTION_MISMATCH:MSTR",
                      review_360_delivery(report, pack, receipt)["problems"])

    def test_broker_validation_blocked_does_not_get_360_receipt(self):
        pack, report, receipt = sample()
        receipt["capital_validation"]["items"][1]["validation_state"] = "BLOCKED"
        receipt["capital_validation"]["validation_hash"] = digest({
            k:v for k,v in receipt["capital_validation"].items() if k != "validation_hash"})
        receipt["receipt_hash"] = digest({k:v for k,v in receipt.items() if k != "receipt_hash"})
        report["capital_receipt_hash"] = receipt["receipt_hash"]
        result = review_360_delivery(report, pack, receipt)
        self.assertIn("CAPITAL_SCOPE_NOT_QUALIFIED", result["problems"])

    def test_no_receipt_no_360(self):
        pack, report, _ = sample()
        self.assertIn("CAPITAL_RECEIPT_MISSING", review_360_delivery(report, pack, None)["problems"])

    def test_missing_organ_fails_after_capital_receipt(self):
        pack, report, receipt = sample()
        del report["organs"]["MSTR"]["company_health"]
        self.assertIn("ORGAN_MISSING:MSTR.company_health",
                      review_360_delivery(report, pack, receipt)["problems"])

    def test_not_run_never_becomes_blocked_evidence(self):
        pack, report, receipt = sample()
        report["organs"]["BTC"]["q1_control_transfer"]["state"] = "NOT_RUN"
        result = review_360_delivery(report, pack, receipt)
        self.assertIn("ORGAN_NOT_RUN:BTC.q1_control_transfer", result["problems"])

    def test_out_of_order_clock_or_wrong_event_fails(self):
        pack, report, receipt = sample()
        report["analysis_as_of_ms"] = pack["generated_at_ms"]
        self.assertIn("REPORT_PRECEDES_CAPITAL_ASSESSMENT",
                      review_360_delivery(report, pack, receipt)["problems"])
        pack, report, receipt = sample()
        report["event_id"] = "a-different-event"
        self.assertIn("REPORT_EVENT_ID_MISMATCH", review_360_delivery(report, pack, receipt)["problems"])

    def test_auto_manifest_lists_all_organs_as_not_run_without_faking_analysis(self):
        pack, report, receipt = sample(multi_scope=True)
        manifest = initialize_360_manifest(pack, receipt)
        self.assertEqual(manifest["event_id"], receipt["event_id"])
        self.assertEqual(manifest["capital_receipt_hash"], receipt["receipt_hash"])
        self.assertEqual(len(manifest["action_scopes"]), 5)
        self.assertTrue(all(row["state"] == "NOT_RUN" for organs in manifest["organs"].values()
                            for row in organs.values()))
        evaluated = review_360_delivery(manifest, pack, receipt)
        self.assertEqual(evaluated["publication_state"], "REJECTED")
        self.assertIn("ORGAN_NOT_RUN:BTC.L1", evaluated["problems"])

    def test_auto_manifest_rejects_unqualified_capital(self):
        pack, report, receipt = sample()
        receipt["capital_validation"]["items"][0]["validation_state"] = "BLOCKED"
        receipt["capital_validation"]["validation_hash"] = digest({
            k:v for k,v in receipt["capital_validation"].items() if k != "validation_hash"})
        receipt["receipt_hash"] = digest({k:v for k,v in receipt.items() if k != "receipt_hash"})
        with self.assertRaisesRegex(ValueError, "CAPITAL_SCOPES_NOT_VALIDATED"):
            initialize_360_manifest(pack, receipt)

    def test_cli_writes_companion_only_and_refuses_overwrite(self):
        pack, report, receipt = sample()
        with tempfile.TemporaryDirectory() as path:
            path = Path(path)
            for name, value in (("pack", pack), ("report", report), ("capital", receipt)):
                (path / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            args = ["--report", str(path/"report.json"), "--evidence-pack", str(path/"pack.json"),
                    "--capital-receipt", str(path/"capital.json"), "--output", str(path/"publication.json")]
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 2)
            published = json.loads((path/"publication.json").read_text(encoding="utf-8"))
            self.assertEqual(published["publication_state"], "REVIEWED_WITH_BLOCKERS_Q5_PENDING")
            self.assertNotIn("broker_observation", json.dumps(published))
            self.assertEqual(receipt["receipt_hash"], published["capital_receipt_hash"])

    def test_cli_rejected_report_leaves_refusal_receipt(self):
        pack, report, receipt = sample()
        del report["actions"]["SATA"]
        with tempfile.TemporaryDirectory() as path:
            path = Path(path)
            for name, value in (("pack", pack), ("report", report), ("capital", receipt)):
                (path / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            args = ["--report", str(path/"report.json"), "--evidence-pack", str(path/"pack.json"),
                    "--capital-receipt", str(path/"capital.json"), "--output", str(path/"publication.json")]
            self.assertEqual(main(args), 2)
            refused = json.loads((path/"publication.json").read_text(encoding="utf-8"))
            self.assertEqual(refused["publication_state"], "REJECTED")
            self.assertIn("ACTION_MISSING:SATA", refused["problems"])

if __name__ == "__main__":
    unittest.main()
