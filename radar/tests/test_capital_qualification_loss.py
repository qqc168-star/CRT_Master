"""Current observation qualification invalidates historical advice, offline only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from crt_radar import capital_decision_closure as c
from crt_radar.broker_capital_observation import reconcile_capital, seal_broker_observation
from crt_radar.gpt_handoff import build_minimized_bridge_payload
from crt_radar.gpt_notification_boundary import ensure_pending, present
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.private_profile import apply_broker_capital_state
from crt_radar.reanalysis_wake import apply_capital_reanalysis_wake
from tests.test_capital_decision_closure import (
    NOW, current_capital_pack, item, match_scopes, full_provider_response, recommendation, source_fixture,
)
from tests.test_full_bridge_budget import captured_pack, handoff_for


class CapitalQualificationLossTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        pack = captured_pack()
        self.payload = build_minimized_bridge_payload(pack, handoff_for(pack, self.root))
        self.source = source_fixture(self.payload)
        self.rec = recommendation(item("HOLD"))
        match_scopes(self.source, self.rec)
        self.envelope = c.build_envelope(self.payload, self.source, at_ms=NOW, full_decision=True)
        self.receipt = c.validated_receipt(full_provider_response(self.rec, self.envelope), self.envelope, at_ms=NOW)
        self.valid_pack = current_capital_pack(self.source)
        self.previous = self.valid_pack["private_context"]["profile"]["capital_reconciliation"]

    def loss_pack(self, state):
        facts = deepcopy(self.source)
        broker = deepcopy(facts["broker_observation"])
        if state == "BLOCKED":
            broker = {"capture_failed": True, "reason": "BROKER_CONNECT_UNAVAILABLE"}
        elif state == "PARTIAL":
            broker["scope"]["funds_complete"] = False
            broker = seal_broker_observation(broker)
        else:
            broker["observed_at_ms"] -= 400_000
            broker["started_at_ms"] -= 400_000
            broker = seal_broker_observation(broker)
        facts["broker_observation"] = broker
        return current_capital_pack(facts, at=NOW + 1)

    def path(self, directory):
        ensure_pending(directory, self.receipt)
        return next(directory.glob("*.json"))

    def test_qualified_to_blocked_partial_stale_blocks_unexpired_old_advice(self):
        for state in ("BLOCKED", "PARTIAL", "STALE"):
            with self.subTest(state=state):
                path = self.path(self.root / state)
                before_receipt = deepcopy(self.receipt)
                presenter = Mock(return_value=1)
                result = present(path, presenter, now_ms=NOW + 1,
                    current_capital_source=self.source, current_capital_state=self.loss_pack(state))
                self.assertEqual(result["state"], "CAPITAL_RECOMMENDATION_NOT_CURRENT")
                presenter.assert_not_called()
                stored = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(stored["current_qualification"]["state"], state)
                self.assertEqual(stored["current_qualification"]["recommendation_state"], "NOT_CURRENT")
                self.assertIn("不得作為當前合格建議", stored["current_qualification"]["message"])
                self.assertEqual(stored["output_text"], self.receipt["output_text"])
                self.assertEqual(self.receipt, before_receipt)
                self.assertLess(NOW + 1, self.receipt["capital_validation"]["valid_until_ms"])

    def test_failure_refresh_is_silent_and_recovery_does_not_resurrect_old_advice(self):
        path = self.path(self.root / "failure")
        presenter = Mock(return_value=1)
        partial = self.loss_pack("PARTIAL")
        present(path, presenter, now_ms=NOW + 1, current_capital_source=self.source,
                current_capital_state=partial)
        before = path.read_bytes()
        refreshed = deepcopy(partial)
        refreshed["generated_at_ms"] += 1
        refreshed["evidence_pack_hash"] = c.digest({k: v for k, v in refreshed.items() if k != "evidence_pack_hash"})
        present(path, presenter, now_ms=NOW + 2, current_capital_source=self.source,
                current_capital_state=refreshed)
        self.assertEqual(path.read_bytes(), before)
        recovered = current_capital_pack(self.source, at=NOW + 2)
        result = present(path, presenter, now_ms=NOW + 2, current_capital_source=self.source,
                         current_capital_state=recovered)
        self.assertEqual(result["reason"], "CAPITAL_RECOMMENDATION_REJUDGMENT_REQUIRED")
        # Even resupplying the original still-fresh pack cannot resurrect it.
        result = present(path, presenter, now_ms=NOW + 2, current_capital_source=self.source,
                         current_capital_state=self.valid_pack)
        self.assertEqual(result["reason"], "CAPITAL_RECOMMENDATION_REJUDGMENT_REQUIRED")
        presenter.assert_not_called()

    def test_delivered_advice_acquires_visible_loss_status_without_another_popup(self):
        path = self.path(self.root / "delivered")
        presenter = Mock(return_value=1)
        self.assertEqual(present(path, presenter, now_ms=NOW, current_capital_source=self.source,
            current_capital_state=self.valid_pack)["state"], "DELIVERED")
        historical = json.loads(path.read_text(encoding="utf-8"))
        result = present(path, presenter, now_ms=NOW + 1, current_capital_source=self.source,
                         current_capital_state=self.loss_pack("BLOCKED"))
        self.assertEqual(result["state"], "CAPITAL_RECOMMENDATION_NOT_CURRENT")
        stored = json.loads(path.read_text(encoding="utf-8"))
        for key in ("receipt_hash", "event_id", "capital_validation", "output_text", "presentation"):
            self.assertEqual(stored[key], historical[key])
        self.assertEqual(stored["current_qualification"]["recommendation_state"], "NOT_CURRENT")
        presenter.assert_called_once()

    def test_source_only_or_tampered_current_pack_cannot_bypass_loss_check(self):
        path = self.path(self.root / "proof")
        presenter = Mock(return_value=1)
        self.assertEqual(present(path, presenter, now_ms=NOW,
            current_capital_source=self.source)["state"], "CURRENT_CAPITAL_STATE_REQUIRED")
        tampered = deepcopy(self.valid_pack)
        tampered["private_context"]["profile"]["capital_reconciliation"]["analysis_cash_budget_usd"] = 99999
        result = present(path, presenter, now_ms=NOW, current_capital_source=self.source,
                         current_capital_state=tampered)
        self.assertEqual(result["reason"], "CURRENT_CAPITAL_EVIDENCE_HASH_INVALID")
        tampered["evidence_pack_hash"] = c.digest({k: v for k, v in tampered.items() if k != "evidence_pack_hash"})
        result = present(path, presenter, now_ms=NOW, current_capital_source=self.source,
                         current_capital_state=tampered)
        self.assertEqual(result["reason"], "CURRENT_CAPITAL_RECONCILIATION_MISMATCH")
        presenter.assert_not_called()

    def test_loss_status_is_visible_without_model_wake_and_recovery_rejudges(self):
        quiet = {"state": "NO_WAKE", "reason": "UNCHANGED_MARKET", "action_output": "NONE"}
        for state in ("BLOCKED", "PARTIAL", "STALE"):
            with self.subTest(state=state):
                pack = self.loss_pack(state)
                current = pack["private_context"]["profile"]["capital_reconciliation"]
                wake = apply_capital_reanalysis_wake(quiet, current, at_ms=NOW + 1,
                    previous_reconciliation=self.previous, previous_at_ms=NOW)
                self.assertEqual(wake["state"], "NO_WAKE")
                self.assertTrue(wake["capital_change"]["qualification_lost"])
                pack.update(reanalysis_wake=wake,
                    authority={"external_action_authority": "NONE", "external_action_performed": False})
                # Historical policy values must not hide the current failure.
                pack["private_context"]["profile"].update(strc={"shares": 75, "current_annual_distribution_rate": .10},
                                                         derived={"six_month_cash_usd": 375})
                with patch("crt_radar.gpt_transport_worker.send_response") as sender:
                    notice = build_plain_language_notice(pack)
                    sender.assert_not_called()
                self.assertEqual(notice["notification_state"], "NO_NOTIFICATION")
                self.assertEqual(notice["capital_qualification"]["state"], state)
                self.assertIn(current["reason"], notice["what_happened"])
                self.assertIn("不得視為當前合格建議", notice["position_context"])
                recovered = apply_capital_reanalysis_wake(quiet, self.previous, at_ms=NOW,
                    previous_reconciliation=current, previous_at_ms=NOW)
                self.assertEqual(recovered["state"], "REANALYSIS_REQUESTED")

    def test_new_same_partial_snapshot_hold_retains_scope_qualified_semantics(self):
        self.source["broker_observation"] = self.loss_pack("PARTIAL")["private_context"]["profile"]["capital_reconciliation"]["broker_observed"]
        self.source["qualification"]["observation_hash"] = self.source["broker_observation"]["observation_hash"]
        partial = current_capital_pack(self.source)
        self.payload["event"]["source_evidence_pack_hash"] = partial["evidence_pack_hash"]
        self.payload["bridge_payload_hash"] = c.digest({k: v for k, v in self.payload.items() if k != "bridge_payload_hash"})
        self.source.update(evidence_lineage=partial["evidence_pack_hash"], bridge_payload_hash=self.payload["bridge_payload_hash"])
        envelope = c.build_envelope(self.payload, self.source, at_ms=NOW, full_decision=True)
        receipt = c.validated_receipt(full_provider_response(self.rec, envelope), envelope, at_ms=NOW)
        ensure_pending(self.root / "new-partial", receipt)
        path = next((self.root / "new-partial").glob("*.json"))
        presenter = Mock(return_value=1)
        result = present(path, presenter, now_ms=NOW, current_capital_source=self.source,
                         current_capital_state=partial)
        self.assertEqual(result["state"], "DELIVERED")
        presenter.assert_called_once()

    def test_qualified_refresh_cannot_hide_changed_capital_or_intent(self):
        for change in ("funds", "holdings", "intent"):
            with self.subTest(change=change):
                changed = deepcopy(self.source)
                if change == "intent":
                    changed["user_intent"]["version"] = "synthetic-intent-2"
                else:
                    broker = changed["broker_observation"]
                    if change == "funds":
                        broker["funds"]["cash_usd"] += 1
                    else:
                        broker["holdings"][0]["quantity"] += 1
                    changed["broker_observation"] = seal_broker_observation(broker)
                path = self.path(self.root / change)
                presenter = Mock(return_value=1)
                result = present(path, presenter, now_ms=NOW + 1,
                    current_capital_source=self.source,
                    current_capital_state=current_capital_pack(changed, at=NOW + 1))
                self.assertEqual(result["reason"], "CAPITAL_RECOMMENDATION_SUPERSEDED")
                presenter.assert_not_called()

    def test_only_clock_refresh_preserves_still_fresh_advice_and_dedupe(self):
        refreshed = deepcopy(self.source)
        refreshed["broker_observation"]["observed_at_ms"] += 1
        refreshed["broker_observation"]["started_at_ms"] += 1
        refreshed["broker_observation"] = seal_broker_observation(refreshed["broker_observation"])
        refreshed["user_intent"]["confirmed_at_ms"] += 1
        pack = current_capital_pack(refreshed, at=NOW + 1)
        path = self.path(self.root / "clock-only")
        presenter = Mock(return_value=1)
        self.assertEqual(present(path, presenter, now_ms=NOW + 1,
            current_capital_source=self.source, current_capital_state=pack)["state"], "DELIVERED")
        self.assertEqual(present(path, presenter, now_ms=NOW + 2,
            current_capital_source=self.source, current_capital_state=pack)["state"], "ALREADY_DELIVERED")
        presenter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
