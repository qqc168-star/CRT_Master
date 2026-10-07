from __future__ import annotations

import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "windows"
    / "run_observation_history_windows.ps1"
)


class ObservationHistoryWindowsNotificationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(
            encoding="utf-8"
        )

    def test_declares_post_gpt_notification_root(self):
        self.assertIn(
            '$PostGptNotifications = Join-Path '
            '$RuntimeRoot "gpt_bridge\\notifications"',
            self.text,
        )

    def test_creates_post_gpt_notification_directory(self):
        self.assertIn(
            'New-Item -ItemType Directory -Force '
            '$PostGptNotifications | Out-Null',
            self.text,
        )

    def test_transport_worker_receives_notification_root(self):
        self.assertIn(
            '--notification-state-dir $PostGptNotifications',
            self.text,
        )

    def test_notification_sweep_uses_transport_and_notification_roots(self):
        self.assertIn(
            '-m crt_radar.gpt_notification_boundary',
            self.text,
        )

        self.assertIn(
            '--transport-state-dir $TransportBoundary',
            self.text,
        )

        self.assertIn(
            '--notification-state-dir $PostGptNotifications',
            self.text,
        )

    def test_notification_sweep_runs_after_gpt_transport_section(self):
        transport_index = self.text.index(
            '-m crt_radar.gpt_transport_worker'
        )

        notification_index = self.text.index(
            '-m crt_radar.gpt_notification_boundary'
        )

        self.assertLess(
            transport_index,
            notification_index,
        )

    def test_does_not_add_external_notification_transport(self):
        lowered = self.text.lower()

        for forbidden in (
            "send-mailmessage",
            "telegram",
            "slack",
            "discord",
        ):
            self.assertNotIn(
                forbidden,
                lowered,
            )


if __name__ == "__main__":
    unittest.main()