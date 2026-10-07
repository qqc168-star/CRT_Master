from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from crt_radar import gpt_transport_worker as worker
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_handoff import (
    build_minimized_bridge_payload,
    run_gpt_handoff_gate,
)
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.gpt_transport_boundary import _read_json
from test_gpt_handoff import bridge_pack, pack
from test_openai_responses_adapter_contract import response


class TransportNotificationIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)

        evidence = bridge_pack(
            pack(
                evidence_hash="a" * 64,
                requested=True,
            )
        )

        handoff = run_gpt_handoff_gate(
            evidence,
            build_plain_language_notice(evidence),
            ledger_path=self.root / "ledger.jsonl",
        )

        self.payload = build_minimized_bridge_payload(
            evidence,
            handoff,
        )

        self.event_id = self.payload["event"]["event_id"]

        self.outbox = self.root / "outbox"
        enqueue_bridge_payload(
            self.outbox,
            self.payload,
        )

        self.path = (
            self.outbox
            / f"{self.event_id}.json"
        )

        self.states = self.root / "transport"
        self.states.mkdir()

        self.notifications = self.root / "notifications"

        self.transport = Mock(
            return_value=response()
        )

    def run_event(self):
        return worker.deliver_event(
            self.path,
            self.states,
            notification_state_dir=self.notifications,
            transport=self.transport,
        )

    def test_new_delivery_creates_one_notification_and_replay_does_not_resend(self):
        first = self.run_event()

        self.assertEqual(
            first["state"],
            "DELIVERED",
        )

        state = _read_json(
            self.states / f"{self.event_id}.json"
        )

        self.assertIs(
            state.get("notification_required"),
            True,
        )

        notification_files = list(
            self.notifications.glob("*.json")
        )

        self.assertEqual(
            len(notification_files),
            1,
        )

        notification = json.loads(
            notification_files[0].read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            notification["state"],
            "PENDING",
        )

        self.assertEqual(
            notification["receipt_hash"],
            state["receipt"]["receipt_hash"],
        )

        second = self.run_event()

        self.assertEqual(
            second["state"],
            "ALREADY_DELIVERED",
        )

        self.assertEqual(
            len(list(self.notifications.glob("*.json"))),
            1,
        )

        self.transport.assert_called_once()

    def test_crash_after_delivered_state_recovers_notification_without_resending_provider(self):
        with patch.object(
            worker,
            "ensure_pending",
            side_effect=RuntimeError(
                "synthetic notification crash"
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.run_event()

        state = _read_json(
            self.states / f"{self.event_id}.json"
        )

        self.assertEqual(
            state["state"],
            "DELIVERED",
        )

        self.assertIs(
            state.get("notification_required"),
            True,
        )

        self.assertEqual(
            len(list(self.notifications.glob("*.json"))),
            0,
        )

        self.transport.assert_called_once()

        recovered = self.run_event()

        self.assertEqual(
            recovered["state"],
            "ALREADY_DELIVERED",
        )

        self.assertEqual(
            len(list(self.notifications.glob("*.json"))),
            1,
        )

        self.transport.assert_called_once()


if __name__ == "__main__":
    unittest.main()