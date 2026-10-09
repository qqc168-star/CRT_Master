"""Rejected capital assessments remain visible without becoming advice receipts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from crt_radar import capital_decision_closure as capital
from crt_radar import gpt_transport_worker as worker
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_transport_boundary import _seal_state, _write_no_clobber, build_pending_state
from scripts import run_controlled_capital_acceptance as controlled
from tests.test_capital_decision_closure import leg

MAIN = "4bee34d0d674da785516809cb103ccef9645eee7"
NOW = 1790930000000


class CapitalBlockedDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        blocked_http = patch.object(worker.urlrequest, "build_opener",
            side_effect=AssertionError("No model or broker capture in blocked disclosure tests"))
        blocked_http.start()
        self.addCleanup(blocked_http.stop)
        blocked_sender = patch.object(worker, "_post_response",
            side_effect=AssertionError("No real model request"))
        blocked_sender.start()
        self.addCleanup(blocked_sender.stop)
        controlled.preflight(self.root, source_main_sha=MAIN, at_ms=NOW)
        self.case = controlled._read_json(self.root / "synthetic-case.json")
        enqueue_bridge_payload(self.root / "outbox", self.case["payload"])
        self.event = self.case["payload"]["event"]["event_id"]
        self.path = self.root / "outbox" / (self.event + ".json")

    def response(self, blockers=None):
        response = controlled.simulated_response(self.case)
        recommendation = json.loads(response["output"][0]["content"][0]["text"])
        hold = next(item for item in recommendation["items"] if item["decision_scope"] == "MSTR-existing")
        if blockers is not None:
            hold["blockers"] = blockers
        response["output"][0]["content"][0]["text"] = json.dumps(recommendation, ensure_ascii=False)
        return response

    def deliver(self, sender):
        return worker.deliver_event(self.path, self.root / "states", capital_source=self.case["source"],
            current_main_sha=MAIN, now_ms=NOW, transport=sender,
            notification_state_dir=self.root / "notifications")

    def test_genuine_hold_gap_is_disclosed_as_blocked_hold_without_receipt_or_notice(self):
        sender = Mock(return_value=self.response([
            "正式估值不足，無法支持本次續抱主張。", "續抱策略的失效條件仍不完整。"] ))
        result = self.deliver(sender)
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(result["notification_eligible"])
        review = result["capital_blocked_review"]
        self.assertFalse(review["qualified"])
        self.assertEqual(review["capital_decision_state"], "BLOCKED")
        self.assertTrue(review["assessment_available"])
        hold = next(item for item in review["items"] if item["decision_scope"] == "MSTR-existing")
        self.assertEqual((hold["action"], hold["validation_state"]), ("HOLD", "BLOCKED"))
        self.assertIn("正式估值不足", review["message"])
        self.assertIn("並非合格資本建議", review["message"])
        self.assertEqual(list((self.root / "notifications").glob("*.json")), [])
        self.assertEqual(list((self.root / "states").rglob("recommendations/*.json")), [])

    def test_saved_rejected_response_replay_discloses_without_send_or_rewriting(self):
        sender = Mock(return_value=self.response(["正式估值不足，續抱主張受阻。"]))
        first = self.deliver(sender)
        preserved = {path: path.read_bytes() for path in self.root.rglob("*.json")}
        second = self.deliver(sender)
        sender.assert_called_once()
        self.assertFalse(second["transport_performed"])
        self.assertEqual(second["capital_blocked_review"], first["capital_blocked_review"])
        self.assertEqual({path: path.read_bytes() for path in preserved}, preserved)
        self.assertFalse(second["notification_eligible"])

    def test_unvalidated_or_sensitive_model_fields_are_not_exposed_as_review(self):
        unknown = self.response(["正式估值不足。"])
        recommendation = json.loads(unknown["output"][0]["content"][0]["text"])
        recommendation["items"][0]["supporting_evidence"] = ["invented_source"]
        unknown["output"][0]["content"][0]["text"] = json.dumps(recommendation, ensure_ascii=False)
        sensitive = self.response(["sk-DO_NOT_DISCLOSE_THIS_SECRET_PLACEHOLDER"])
        for response in (unknown, sensitive):
            with self.subTest(response=response["id"]):
                review = worker._capital_blocked_review(response, self.case["envelope"],
                    at_ms=NOW, failure=ValueError("CAPITAL_RECOMMENDATION_NOT_VALIDATED"))
                self.assertFalse(review["assessment_available"])
                self.assertNotIn("items", review)
                self.assertNotIn("invented_source", json.dumps(review))
                self.assertNotIn("DO_NOT_DISCLOSE", json.dumps(review))

    def test_controlled_report_preserves_rejection_and_does_not_notify(self):
        response = self.response(["缺少正式估值，續抱主張受阻。"])
        original = deepcopy(response)
        report = controlled.execute(self.root, mode="OFFLINE_SIMULATION", offline_response=response)
        self.assertEqual(report["delivery"]["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(report["capital_blocked_review"], report["delivery"]["capital_blocked_review"])
        self.assertEqual(report["presented_text"], [])
        self.assertEqual(report["notification_results"], [])
        self.assertEqual(report["real_model_acceptance"], "NOT_MEASURED")
        self.assertEqual(response, original)

    def test_unnamespaced_enum_only_send_marker_cannot_be_sent_as_new_semantic_request(self):
        historical = capital._build_envelope(self.case["payload"], self.case["source"],
            at_ms=NOW, full_decision=True, legacy_semantics=True)
        marker = _seal_state({**build_pending_state(self.case["payload"]),
            "request_hash": historical["request_hash"]})
        path = self.root / "states" / (self.event + ".json")
        _write_no_clobber(path, marker)
        original = path.read_bytes()
        sender = Mock(return_value=self.response())
        result = self.deliver(sender)
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(result["reason"], "LEGACY_CAPITAL_STATE_REQUIRES_RECONCILIATION")
        self.assertFalse(result["notification_eligible"])
        sender.assert_not_called()
        self.assertEqual(path.read_bytes(), original)

    def test_valid_financial_buy_with_missing_investment_comparison_stays_visibly_blocked(self):
        response = self.response()
        recommendation = json.loads(response["output"][0]["content"][0]["text"])
        strc = next(item for item in recommendation["items"] if item["decision_scope"] == "STRC-addition")
        strc.update(action="BUY", wait_kind=None, blockers=[], legs=[leg(asset="STRC")],
            reason="反例：財務上可負擔，但沒有來源證明 STRC 優於現金。")
        response["output"][0]["content"][0]["text"] = json.dumps(recommendation, ensure_ascii=False)
        assessment = capital.assess_response(response, self.case["envelope"], at_ms=NOW)
        financial_buy = next(item for item in assessment["items"] if item["decision_scope"] == "STRC-addition")
        self.assertEqual(financial_buy["validation_state"], "VALIDATED")
        self.assertTrue(financial_buy["validated_legs"])
        with self.assertRaisesRegex(ValueError, "INVESTMENT_COMPARISON_NOT_SOURCE_SUPPORTED:STRC-addition"):
            capital.validated_receipt(response, self.case["envelope"], at_ms=NOW)
        result = self.deliver(Mock(return_value=response))
        review = result["capital_blocked_review"]
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(result["notification_eligible"])
        self.assertEqual(review["capital_decision_state"], "BLOCKED")
        self.assertEqual(review["reason"], "INVESTMENT_COMPARISON_NOT_SOURCE_SUPPORTED:STRC-addition")
        self.assertFalse(review["qualified"])
        visible_buy = next(item for item in review["items"] if item["decision_scope"] == "STRC-addition")
        self.assertEqual(visible_buy["validation_state"], "VALIDATED")
        self.assertEqual(visible_buy["capital_decision_state"], "BLOCKED")
        self.assertFalse(visible_buy["qualified"])
        self.assertIn("VALIDATED 僅表示原財務／來源檢查狀態", review["message"])
        self.assertIn("本次完整決策為 BLOCKED", review["message"])
        self.assertNotIn("美股範圍投資組合資本建議；", review["message"])
        self.assertEqual(list((self.root / "notifications").glob("*.json")), [])
        self.assertEqual(list((self.root / "states").rglob("recommendations/*.json")), [])


if __name__ == "__main__":
    unittest.main()
