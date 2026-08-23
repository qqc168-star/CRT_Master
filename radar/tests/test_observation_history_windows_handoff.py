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


if __name__ == "__main__":
    unittest.main()
