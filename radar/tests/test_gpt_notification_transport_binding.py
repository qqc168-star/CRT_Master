from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crt_radar.gpt_bridge_outbox import (
    BRIDGE_PRIVACY_CONTRACT_VERSION,
    BRIDGE_SCHEMA_VERSION,
)
from crt_radar.gpt_notification_boundary import (
    ensure_from_transport,
)
from crt_radar.gpt_transport_boundary import (
    BOUNDARY_SCHEMA_VERSION,
    _seal_state,
    build_pending_state,
    persist_boundary_state,
)
from crt_radar.openai_responses_adapter_contract import (
    SMOKE_MODEL,
    build_delivery_receipt,
    build_request_envelope,
)


def _hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def payload() -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "privacy_contract_version":
            BRIDGE_PRIVACY_CONTRACT_VERSION,
        "state": "BRIDGE_PAYLOAD_READY_LOCAL_ONLY",
        "event": {"event_id": "a" * 64},
        "analysis": {"marker": "notification-binding-test"},
        "authority": {
            "production": "NOT_APPROVED",
            "trading_authority": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "transport_authority": "NONE",
            "transport_performed": False,
            "action_output": "NONE",
        },
        "privacy": {
            "mode": "MINIMIZED_ALLOWLIST_ONLY",
            "raw_private_context_included": False,
            "full_private_profile_included": False,
            "filesystem_paths_included": False,
            "broker_or_account_identifiers_included": False,
            "credentials_or_secrets_included": False,
            "transport_selected": False,
        },
    }

    result["bridge_payload_hash"] = _hash(result)
    return result


def response() -> dict[str, object]:
    return {
        "id": "resp_notification_test",
        "status": "completed",
        "model": SMOKE_MODEL,
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Synthetic CRT notification analysis.",
                    }
                ],
            }
        ],
    }


class NotificationTransportBindingTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.transport = self.root / "transport"
        self.notifications = self.root / "notifications"

        self.transport.mkdir()
        (self.transport / "responses").mkdir()

        self.payload = payload()
        self.event_id = self.payload["event"]["event_id"]

        self.envelope = build_request_envelope(
            self.payload,
            model=SMOKE_MODEL,
        )

        self.response = response()

        self.receipt = build_delivery_receipt(
            self.response,
            event_id=self.envelope["event_id"],
            bridge_payload_hash=
                self.envelope["bridge_payload_hash"],
            request_hash=self.envelope["request_hash"],
        )

        delivered = _seal_state({
            "schema_version": BOUNDARY_SCHEMA_VERSION,
            "state": "DELIVERED",
            "reason": "DELIVERY_RECEIPT_RECORDED",
            "event_id": self.event_id,
            "bridge_payload_hash":
                self.envelope["bridge_payload_hash"],
            "request_hash":
                self.envelope["request_hash"],
            "attempt_count": 1,
            "claim": None,
            "receipt": self.receipt,
            "adapter_selected": True,
            "production": "NOT_APPROVED",
            "external_action_authority": "NONE",
            "action_output": "NONE",
        })

        persist_boundary_state(
            self.transport,
            delivered,
        )

        evidence = {
            "request": self.envelope,
            "response": self.response,
        }

        (
            self.transport
            / "responses"
            / f"{self.event_id}.json"
        ).write_text(
            json.dumps(evidence),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_delivered_transport_creates_notification_once(self):
        first = ensure_from_transport(
            self.transport,
            self.notifications,
            self.event_id,
        )

        second = ensure_from_transport(
            self.transport,
            self.notifications,
            self.event_id,
        )

        self.assertEqual(first["state"], "CREATED")
        self.assertEqual(second["state"], "EXISTS")

        self.assertEqual(
            len(list(self.notifications.glob("*.json"))),
            1,
        )

    def test_tampered_provider_response_is_rejected(self):
        path = (
            self.transport
            / "responses"
            / f"{self.event_id}.json"
        )

        evidence = json.loads(
            path.read_text(encoding="utf-8")
        )

        evidence["response"]["output"][0]["content"][0][
            "text"
        ] = "tampered"

        path.write_text(
            json.dumps(evidence),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            ensure_from_transport(
                self.transport,
                self.notifications,
                self.event_id,
            )

    def test_tampered_request_is_rejected(self):
        path = (
            self.transport
            / "responses"
            / f"{self.event_id}.json"
        )

        evidence = json.loads(
            path.read_text(encoding="utf-8")
        )

        evidence["request"]["request_body"]["store"] = True

        path.write_text(
            json.dumps(evidence),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            ensure_from_transport(
                self.transport,
                self.notifications,
                self.event_id,
            )

    def test_non_delivered_transport_is_rejected(self):
        pending = build_pending_state(
            self.payload
        )

        persist_boundary_state(
            self.transport,
            pending,
        )

        with self.assertRaises(ValueError):
            ensure_from_transport(
                self.transport,
                self.notifications,
                self.event_id,
            )


if __name__ == "__main__":
    unittest.main()