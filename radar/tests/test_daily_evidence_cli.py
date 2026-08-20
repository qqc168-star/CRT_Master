from __future__ import annotations

import contextlib
import io
import unittest

from crt_radar.daily_evidence_runner import main


class DailyEvidenceCliSmokeTests(unittest.TestCase):
    def test_help_builds_parser_without_duplicate_option_conflict(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--assumption-context", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
