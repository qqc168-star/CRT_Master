from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from crt_radar.gpt_notification_boundary import (
    _hash,
    ensure_pending,
    notification_id,
    notification_lock,
    present,
    windows_popup_presenter,
)


def receipt():
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
        "output_text": "CRT popup test",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "action_output": "NONE",
    }

    value["receipt_hash"] = _hash(value)

    return value


class NotificationWindowsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.receipt = receipt()

        created = ensure_pending(
            self.root,
            self.receipt,
        )

        self.notification_id = (
            created["notification_id"]
        )

        self.path = (
            self.root
            / f"{self.notification_id}.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_process_lock_blocks_second_presenter(self):
        presenter = Mock(return_value=1)

        with notification_lock(
            self.root,
            self.notification_id,
        ) as acquired:

            self.assertTrue(acquired)

            result = present(
                self.path,
                presenter,
            )

        self.assertEqual(
            result["state"],
            "BUSY",
        )

        self.assertFalse(
            result["presentation_performed"],
        )

        presenter.assert_not_called()

    def test_process_lock_blocks_second_creator(self):
        with notification_lock(
            self.root,
            self.notification_id,
        ) as acquired:

            self.assertTrue(acquired)

            result = ensure_pending(
                self.root,
                self.receipt,
            )

        self.assertEqual(
            result["state"],
            "BUSY",
        )

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_windows_popup_success(
        self,
        run,
        which,
    ):
        which.return_value = "powershell.exe"

        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="-1\n",
        )

        result = windows_popup_presenter(
            "CRT analysis",
        )

        self.assertEqual(result, -1)

        call = run.call_args

        self.assertEqual(
            call.kwargs["env"]["CRT_NOTIFICATION_TEXT"],
            "CRT analysis",
        )

        command = " ".join(call.args[0])

        self.assertNotIn(
            "CRT analysis",
            command,
        )

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_windows_popup_ambiguous_result_fails_closed(
        self,
        run,
        which,
    ):
        which.return_value = "powershell.exe"

        run.return_value = SimpleNamespace(
            returncode=2,
            stdout="",
        )

        with self.assertRaises(RuntimeError):
            windows_popup_presenter(
                "CRT analysis",
            )


if __name__ == "__main__":
    unittest.main()