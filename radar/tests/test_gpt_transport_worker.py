from __future__ import annotations

import copy
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from crt_radar import gpt_transport_worker as worker
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload, _canonical_hash
from crt_radar.gpt_handoff import build_minimized_bridge_payload, run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.gpt_transport_boundary import (
    _read_json, _write_no_clobber, _seal_state, build_pending_state,
    claim_delivery, delivery_lock, persist_boundary_state,
)
from crt_radar.openai_responses_adapter_contract import build_request_envelope, SMOKE_MODEL
from test_gpt_handoff import bridge_pack, pack
from test_openai_responses_adapter_contract import response


def hold_lock(root, event_id, ready, release):
    with delivery_lock(Path(root), event_id) as acquired:
        ready.put(acquired)
        release.wait(20)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        evidence = bridge_pack(pack(evidence_hash="a" * 64, requested=True))
        handoff = run_gpt_handoff_gate(evidence, build_plain_language_notice(evidence),
                                       ledger_path=self.root / "ledger.jsonl")
        self.payload = build_minimized_bridge_payload(evidence, handoff)
        self.event = self.payload["event"]["event_id"]
        self.outbox = self.root / "outbox"
        enqueue_bridge_payload(self.outbox, self.payload)
        self.path = self.outbox / f"{self.event}.json"
        self.states = self.root / "states"
        self.states.mkdir()
        self.transport = Mock(return_value=response())

    def run_event(self, **kw):
        return worker.deliver_event(self.path, self.states, transport=self.transport, **kw)

    def stored(self):
        return _read_json(self.states / f"{self.event}.json")

    def claim(self):
        state = claim_delivery(build_pending_state(self.payload), adapter_id=worker.ADAPTER_ID,
                               now_ms=100, lease_ms=100, adapter_selected=True)
        persist_boundary_state(self.states, state)
        return state

    def test_pending_claimed_delivered_and_duplicate_suppressed(self):
        observed = []
        def send(envelope):
            observed.append(self.stored()["state"])
            self.assertEqual(json.loads(envelope["request_body"]["input"]), self.payload)
            self.assertEqual(set(envelope["request_body"]),
                             {"model", "input", "instructions", "store", "background", "max_output_tokens"})
            return response()
        self.transport.side_effect = send
        first = self.run_event()
        self.assertEqual(first["state"], "DELIVERED")
        self.assertTrue(first["notification_eligible"])
        self.assertEqual(observed, ["CLAIMED"])
        self.assertEqual(self.stored()["state"], "DELIVERED")
        second = self.run_event()
        self.assertEqual(second["state"], "ALREADY_DELIVERED")
        self.assertFalse(second["notification_eligible"])
        self.transport.assert_called_once()

    def test_lease_blocks_second_worker_and_expired_presend_recovers(self):
        self.claim()
        self.assertEqual(self.run_event(now_ms=199)["state"], "CLAIMED")
        self.transport.assert_not_called()
        self.assertEqual(self.run_event(now_ms=200)["state"], "DELIVERED")

    def test_os_lock_blocks_even_after_lease_and_releases_on_death(self):
        ctx = multiprocessing.get_context("spawn")
        ready, release = ctx.Queue(), ctx.Event()
        process = ctx.Process(target=hold_lock, args=(str(self.states), self.event, ready, release))
        process.start()
        try:
            self.assertTrue(ready.get(timeout=10))
            self.assertEqual(self.run_event(now_ms=999999)["state"], "BUSY")
            self.transport.assert_not_called()
        finally:
            process.terminate()
            process.join(timeout=10)
            ready.close()
        self.assertEqual(self.run_event()["state"], "DELIVERED")

    def test_provider_failure_never_delivers_or_replays(self):
        self.transport.side_effect = TimeoutError("secret exception must not persist")
        self.assertEqual(self.run_event()["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(self.stored()["state"], "RETRYABLE")
        self.assertIsNone(self.stored()["receipt"])
        self.assertNotIn("secret exception", json.dumps(self.stored()))
        self.run_event()
        self.transport.assert_called_once()

    def test_noncompleted_no_receipt(self):
        self.transport.return_value = {**response(), "status": "incomplete"}
        self.assertEqual(self.run_event()["state"], "RECONCILIATION_REQUIRED")
        self.assertIsNone(self.stored()["receipt"])

    def test_death_after_send_intent_never_resends(self):
        state = self.claim()
        envelope = build_request_envelope(self.payload, model=SMOKE_MODEL)
        persist_boundary_state(self.states, _seal_state({**state, "request_hash": envelope["request_hash"]}))
        self.assertEqual(self.run_event(now_ms=200)["state"], "RECONCILIATION_REQUIRED")
        self.transport.assert_not_called()

    def test_death_after_response_persistence_finalizes_without_network(self):
        state = self.claim()
        envelope = build_request_envelope(self.payload, model=SMOKE_MODEL)
        persist_boundary_state(self.states, _seal_state({**state, "request_hash": envelope["request_hash"]}))
        _write_no_clobber(self.states / "responses" / f"{self.event}.json",
                          {"request": envelope, "response": response()})
        result = self.run_event(now_ms=200)
        self.assertEqual(result["state"], "DELIVERED")
        self.assertFalse(result["transport_performed"])
        self.transport.assert_not_called()
        receipt = self.stored()["receipt"]
        self.assertEqual(receipt["event_id"], self.event)
        self.assertEqual(receipt["bridge_payload_hash"], self.payload["bridge_payload_hash"])
        self.assertEqual(receipt["request_hash"], envelope["request_hash"])
        self.assertEqual(receipt["response_hash"], _canonical_hash(response()))
        unhashed = dict(receipt)
        receipt_hash = unhashed.pop("receipt_hash")
        self.assertEqual(receipt_hash, _canonical_hash(unhashed))

    def test_payload_hash_and_boundary_identity_fail_closed(self):
        self.claim()
        state = self.stored()
        persist_boundary_state(self.states, _seal_state({**state, "bridge_payload_hash": "f" * 64}))
        with self.assertRaises(ValueError):
            self.run_event(now_ms=200)
        self.payload["event"]["event_id"] = "f" * 64
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_event()
        self.transport.assert_not_called()

    def test_privacy_and_authority_reject_even_with_recomputed_hash(self):
        for section, key, value in [
            ("market_context", "broker_account", "12345"),
            ("market_context", "comment", r"C:\Users\owner\portfolio.json"),
            ("market_context", "comment", "sk-project-secret123456789"),
            ("capital_state", "api_key", "anything"),
            ("authority", "capital_decision_authority", "MACHINE"),
            ("authority", "machine_may_execute_trade", True),
        ]:
            with self.subTest(key=key, value=value):
                candidate = copy.deepcopy(self.payload)
                candidate[section][key] = value
                candidate.pop("bridge_payload_hash")
                candidate["bridge_payload_hash"] = _canonical_hash(candidate)
                with self.assertRaises(ValueError):
                    worker.validate_transport_payload(candidate)

    def test_no_credentials_no_claim_or_send(self):
        with patch.dict("os.environ", {}, clear=True):
            result = worker.deliver_event(self.path, self.states)
        self.assertEqual(result["state"], "CREDENTIAL_UNAVAILABLE")
        self.assertEqual(self.stored()["state"], "PENDING")

    def test_public_https_provenance_is_not_a_windows_drive_path(self):
        candidate = copy.deepcopy(self.payload)
        candidate["market_context"]["dvol_regime_watch"] = {
            "provenance": {"endpoint": "https://www.deribit.com/api/v2/public/get_volatility_index_data"}
        }
        candidate.pop("bridge_payload_hash")
        candidate["bridge_payload_hash"] = _canonical_hash(candidate)
        self.assertEqual(worker.validate_transport_payload(candidate)[0], self.event)
        for text in [r"C:\Users\owner\portfolio.json", "C:/private/file.json",
                     "stored at D:/secrets/key", "file:///C:/secrets/key",
                     "https://example.com/Users/private/key"]:
            with self.subTest(text=text):
                self.assertIsNotNone(worker._SENSITIVE_TEXT.search(text))

    def test_oversized_builder_preserves_facts_locks_lineage_and_declares_omissions(self):
        evidence = bridge_pack(pack(evidence_hash="b" * 64, requested=True))
        evidence["changes"] = {"historical_detail": "x" * 20000}
        evidence["layers"] = {"L1": {
            "status": "BLOCKED", "missing_required_metrics": ["unavailable"],
            "required_metrics": ["actual", "unavailable"],
            "metrics": {"actual": {"value": 12.5, "as_of_ms": 12345,
                                    "quality_state": "VALID_FRESH", "evidence_hash": "c" * 64}},
        }}
        evidence["reanalysis_wake"]["current_value"] = 12.5
        original = copy.deepcopy(evidence)
        handoff = run_gpt_handoff_gate(evidence, build_plain_language_notice(evidence),
                                      ledger_path=self.root / "large.jsonl")
        with patch("crt_radar.gpt_handoff._bound_bridge_detail"):
            full = build_minimized_bridge_payload(evidence, handoff)
        minimized = build_minimized_bridge_payload(evidence, handoff)
        self.assertEqual(evidence, original)
        for key in ("capital_state", "analysis_contract", "authority", "privacy", "event"):
            self.assertEqual(minimized[key], full[key])
        market = minimized["market_context"]
        self.assertEqual(market["minimization"]["source_market_context_hash"],
                         _canonical_hash(full["market_context"]))
        self.assertIn("Omitted is not absent", market["minimization"]["omitted_detail"])
        self.assertEqual(market["layers"]["L1"]["status"], "BLOCKED")
        self.assertEqual(market["layers"]["L1"]["missing_required_metrics"], ["unavailable"])
        self.assertEqual(market["layers"]["L1"]["metrics"]["actual"],
                         {"value": 12.5, "as_of_ms": 12345, "quality_state": "VALID_FRESH"})
        self.assertEqual(market["wake_observation"]["current_value"], 12.5)
        envelope = build_request_envelope(minimized, model=SMOKE_MODEL)
        self.assertLessEqual(len(envelope["request_body"]["input"].encode()), 16384)

    def test_required_analysis_is_never_truncated_to_force_size_acceptance(self):
        evidence = bridge_pack(pack(evidence_hash="b" * 64, requested=True))
        handoff = run_gpt_handoff_gate(evidence, build_plain_language_notice(evidence),
                                      ledger_path=self.root / "required.jsonl")
        handoff["instruction_for_gpt"] = "x" * 20000
        candidate = build_minimized_bridge_payload(evidence, handoff)
        self.assertEqual(candidate["analysis_contract"]["instruction_for_gpt"], "x" * 20000)
        with self.assertRaisesRegex(ValueError, "byte ceiling"):
            build_request_envelope(candidate, model=SMOKE_MODEL)

    def test_receipt_tampering_rejected_on_replay(self):
        self.run_event()
        state = self.stored()
        state["receipt"]["response_id"] = "forged"
        persist_boundary_state(self.states, _seal_state(state))
        with self.assertRaises(ValueError):
            self.run_event()
        self.transport.assert_called_once()

    def test_provider_wire_uses_fixed_url_body_and_no_redirects(self):
        envelope = build_request_envelope(self.payload, model=SMOKE_MODEL)
        http = Mock()
        http.status = 200
        http.read.return_value = json.dumps(response()).encode()
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=http)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}), \
             patch.object(worker.urlrequest, "build_opener", return_value=opener):
            self.assertEqual(worker.send_response(envelope), response())
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(json.loads(request.data), envelope["request_body"])
        self.assertNotIn("test-only", request.data.decode())
        with self.assertRaises(ValueError):
            worker._NoRedirect().redirect_request(None)


if __name__ == "__main__":
    unittest.main()
