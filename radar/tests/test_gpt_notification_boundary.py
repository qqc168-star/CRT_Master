from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from crt_radar.gpt_notification_boundary import (
    _hash,
    ensure_pending,
    notification_id,
    present,
)


def receipt(text: str = "CRT analysis complete"):
    value = {
        "contract_version":
            "CRT_OPENAI_RESPONSES_ADAPTER_CONTRACT_V0.1",
        "state":
            "RESPONSES_DELIVERY_RECEIPT_READY",
        "event_id": "a" * 64,
        "bridge_payload_hash": "b" * 64,
        "request_hash": "c" * 64,
        "response_id": "resp_test",
        "response_status": "completed",
        "model": "gpt-5.6-luna",
        "response_hash": "d" * 64,
        "output_text": text,
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "action_output": "NONE",
    }

    value["receipt_hash"] = _hash(value)

    return value


class NotificationBoundaryTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.receipt = receipt()

    def tearDown(self):
        self.tmp.cleanup()

    def path(self):
        nid = notification_id(
            self.receipt["event_id"],
            self.receipt["receipt_hash"],
        )
        return self.root / f"{nid}.json"

    def test_create_is_idempotent(self):
        first = ensure_pending(
            self.root,
            self.receipt,
        )

        second = ensure_pending(
            self.root,
            self.receipt,
        )

        self.assertEqual(first["state"], "CREATED")
        self.assertEqual(second["state"], "EXISTS")
        self.assertEqual(
            first["notification_id"],
            second["notification_id"],
        )

    def test_successful_popup_only_once(self):
        ensure_pending(
            self.root,
            self.receipt,
        )

        presenter = Mock(return_value=-1)

        first = present(
            self.path(),
            presenter,
            now_ms=1234,
        )

        second = present(
            self.path(),
            presenter,
            now_ms=5678,
        )

        self.assertEqual(
            first["state"],
            "DELIVERED",
        )

        self.assertEqual(
            second["state"],
            "ALREADY_DELIVERED",
        )

        presenter.assert_called_once()

    def test_failure_never_auto_retries(self):
        ensure_pending(
            self.root,
            self.receipt,
        )

        presenter = Mock(
            side_effect=RuntimeError("synthetic")
        )

        first = present(
            self.path(),
            presenter,
        )

        second = present(
            self.path(),
            presenter,
        )

        self.assertEqual(
            first["state"],
            "RECONCILIATION_REQUIRED",
        )

        self.assertEqual(
            second["state"],
            "RECONCILIATION_REQUIRED",
        )

        presenter.assert_called_once()

    def test_tampered_receipt_rejected(self):
        broken = receipt()
        broken["output_text"] = "tampered"

        with self.assertRaises(ValueError):
            ensure_pending(
                self.root,
                broken,
            )


if __name__ == "__main__":
    unittest.main()