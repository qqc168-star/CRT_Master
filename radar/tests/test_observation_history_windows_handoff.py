from __future__ import annotations

import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "windows"
    / "run_observation_history_windows.ps1"
)


class ObservationHistoryWindowsHandoffTests(
    unittest.TestCase
):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SCRIPT.read_text(
            encoding="utf-8"
        )

    def test_declares_runtime_handoff_paths(
        self,
    ) -> None:
        self.assertIn(
            '$HandoffOutput = Join-Path '
            '$RuntimeRoot '
            '"gpt_handoff\\latest.json"',
            self.text,
        )

        self.assertIn(
            '$HandoffLedger = Join-Path '
            '$RuntimeRoot '
            '"gpt_handoff\\ledger.jsonl"',
            self.text,
        )

    def test_creates_handoff_directory(
        self,
    ) -> None:
        self.assertIn(
            'New-Item -ItemType Directory '
            '-Force '
            '(Split-Path $HandoffOutput -Parent) '
            '| Out-Null',
            self.text,
        )

    def test_passes_handoff_pair_to_daily_runner(
        self,
    ) -> None:
        self.assertIn(
            '"--handoff-output", $HandoffOutput,',
            self.text,
        )

        self.assertIn(
            '"--handoff-ledger", $HandoffLedger,',
            self.text,
        )

        output_index = self.text.index(
            '"--handoff-output", $HandoffOutput,'
        )

        ledger_index = self.text.index(
            '"--handoff-ledger", $HandoffLedger,'
        )

        maturity_index = self.text.index(
            '"--maturity-ledger", $MaturityLedger,'
        )

        self.assertLess(
            output_index,
            ledger_index,
        )

        self.assertLess(
            ledger_index,
            maturity_index,
        )

    def test_does_not_add_external_transport(
        self,
    ) -> None:
        lowered = self.text.lower()

        self.assertNotIn(
            "api.openai.com",
            lowered,
        )

        self.assertNotIn(
            "invoke-restmethod",
            lowered,
        )

        self.assertNotIn(
            "invoke-webrequest",
            lowered,
        )

    def test_one_current_broker_capture_is_bound_to_explicit_private_decision_inputs(self):
        self.assertEqual(self.text.count('"--observe-broker-capital"'), 1)
        self.assertIn('"--user-capital-intent", $CapitalIntent', self.text)
        self.assertIn('"--capital-decision-inputs", $CapitalDecisionInputs', self.text)
        self.assertIn('"--capital-source-output", $CapitalSourceOutput', self.text)
        self.assertIn('"--source-main-sha", $EngineeringSourceSha', self.text)
        self.assertNotIn("crt_radar.broker_capital_observation", self.text)

    def test_full_decision_readiness_does_not_enable_daily_provider_delivery(self):
        self.assertIn('$env:CRT_GPT_TRANSPORT_ENABLED -eq "1" -and -not $FullCapitalDecisionRequested', self.text)
        self.assertIn('-and -not $CapitalWakeRequested', self.text)
        self.assertIn('$CapitalWakeRequested = @($CurrentHandoff.semantic_descriptor.wake_sources) -contains "BROKER_CAPITAL_STATE"', self.text)
        self.assertNotIn("OFFLINE_ONLY", self.text)

    def test_notification_checks_current_daily_capital_state(self):
        self.assertIn("--capital-state $EvidenceOutput", self.text)


if __name__ == "__main__":
    unittest.main()
