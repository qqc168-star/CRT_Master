"""A reference-schema refinement must preserve immutable delivery history."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from crt_radar import capital_decision_closure as capital
from crt_radar import gpt_transport_worker as worker
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_transport_boundary import _seal_state, _write_no_clobber, build_pending_state
from scripts import run_controlled_capital_acceptance as controlled

MAIN = "4bee34d0d674da785516809cb103ccef9645eee7"
NOW = 1790930000000


class CapitalRequestReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.case = controlled.synthetic_case(at_ms=NOW, source_main_sha=MAIN)
        self.payload, self.source = self.case["payload"], self.case["source"]
        self.event = self.payload["event"]["event_id"]
        enqueue_bridge_payload(self.root / "outbox", self.payload)
        self.path = self.root / "outbox" / (self.event + ".json")
        self.legacy = capital._build_envelope(self.payload, self.source, at_ms=NOW,
                                             full_decision=True, legacy_references=True)
        self.sender = Mock(return_value=controlled.simulated_response(self.case))
        no_http = patch.object(worker.urlrequest, "build_opener", side_effect=AssertionError("Offline replay only"))
        no_http.start()
        self.addCleanup(no_http.stop)

    def deliver(self):
        return worker.deliver_event(self.path, self.root / "states", capital_source=self.source,
            current_main_sha=MAIN, now_ms=NOW, transport=self.sender,
            notification_state_dir=self.root / "notifications")

    def test_saved_legacy_success_replays_without_rewriting_or_resending(self):
        # Create historical shape only inside this disposable offline fixture.
        with patch.object(capital, "build_envelope", return_value=self.legacy):
            self.assertEqual(self.deliver()["state"], "DELIVERED")
        preserved = {path: path.read_bytes() for path in (self.root / "states").rglob("*.json")}
        self.assertNotEqual(self.legacy["request_hash"], self.case["envelope"]["request_hash"])
        self.assertEqual(self.deliver()["state"], "ALREADY_DELIVERED")
        self.sender.assert_called_once()
        self.assertEqual({path: path.read_bytes() for path in preserved}, preserved)

    def test_unanswered_legacy_send_marker_still_blocks_new_namespace_send(self):
        marker = _seal_state({**build_pending_state(self.payload), "request_hash": self.legacy["request_hash"]})
        _write_no_clobber(self.root / "states" / (self.event + ".json"), marker)
        result = self.deliver()
        self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(result["reason"], "LEGACY_CAPITAL_STATE_REQUIRES_RECONCILIATION")
        self.sender.assert_not_called()

    def test_valid_but_different_saved_source_is_not_rebound(self):
        changed = deepcopy(self.source)
        changed["user_intent"]["reserved_usd"] += 1
        foreign = capital._build_envelope(self.payload, changed, at_ms=NOW,
                                          full_decision=True, legacy_references=True)
        path = self.root / "states" / capital.FULL_REQUEST_VERSION / "responses" / (self.event + ".json")
        _write_no_clobber(path, {"request": foreign, "response": self.sender.return_value})
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Persisted capital request lineage mismatch"):
            self.deliver()
        self.sender.assert_not_called()
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
