from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
import test_gpt_transport_worker as fixtures
from test_openai_responses_adapter_contract import response

spec = importlib.util.spec_from_file_location(
    "accept_one_gpt_event", Path(__file__).resolve().parents[1] / "scripts/accept_one_gpt_event.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class OneEventRunnerTests(unittest.TestCase):
    setUp = fixtures.WorkerTests.setUp

    def test_new_event_only_single_send_and_verified_duplicate_replay(self):
        runtime = self.root / "runtime"
        outbox = runtime / "gpt_bridge/outbox"
        outbox.mkdir(parents=True)
        report = runtime / "acceptance.json"
        provider = Mock(return_value=response())

        def publish(_):
            enqueue_bridge_payload(outbox, self.payload)
            evidence = runtime / "evidence/latest.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps({
                "generated_at_ms": int(acceptance.time.time() * 1000) + 1,
                "evidence_pack_hash": self.payload["event"]["source_evidence_pack_hash"],
                "reanalysis_wake": {"state": "REANALYSIS_REQUESTED"},
            }), encoding="utf-8")

        argv = ["accept", "--runtime-root", str(runtime), "--output", str(report), "--wait-seconds", "10"]
        with patch("sys.argv", argv), patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}), \
             patch.object(acceptance.time, "sleep", side_effect=publish), \
             patch.object(acceptance, "send_response", provider):
            self.assertEqual(acceptance.main(), 0)
        result = json.loads(report.read_text())
        self.assertEqual(result["state"], "LIVE_ACCEPTANCE_PASS")
        self.assertEqual(result["generation_attempts"], 1)
        self.assertEqual(result["transition_states"], ["PENDING", "CLAIMED", "DELIVERED"])
        self.assertEqual(result["replay"]["state"], "ALREADY_DELIVERED")
        self.assertFalse(result["replay"]["transport_performed"])
        self.assertFalse(result["replay"]["notification_eligible"])
        provider.assert_called_once()

    def test_preexisting_event_is_not_republished_or_sent(self):
        runtime = self.root / "runtime"
        outbox = runtime / "gpt_bridge/outbox"
        enqueue_bridge_payload(outbox, self.payload)
        before = (outbox / self.path.name).read_bytes()
        report = runtime / "acceptance.json"
        argv = ["accept", "--runtime-root", str(runtime), "--output", str(report), "--wait-seconds", "0"]
        with patch("sys.argv", argv), patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}), \
             patch.object(acceptance, "send_response") as provider:
            self.assertEqual(acceptance.main(), 2)
        provider.assert_not_called()
        self.assertEqual((outbox / self.path.name).read_bytes(), before)
