"""Exercise the daily entry with synthetic paths and a trapped Python boundary."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_four_asset_daily_integration import daily_proof


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/windows/run_observation_history_windows.ps1"


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class QualifiedEquityDailyEntryContractTests(unittest.TestCase):
    def test_source_resolution_and_read_remain_after_standby_exit(self):
        text = SCRIPT.read_text(encoding="utf-8")
        guard = text.index('if ($RunMode -eq "ISOLATION_ONLY")')
        self.assertLess(text.index("exit 0", guard), text.index('if ([string]::IsNullOrWhiteSpace($QualifiedEquityDailySource))'))
        self.assertIn('"market-health\\sources\\four-asset-daily-proof.json"', text)
        self.assertIn('Test-Path -LiteralPath $QualifiedEquityDailySource -PathType Leaf', text)
        self.assertEqual(text.count('"--qualified-equity-daily-source"'), 1)

    def test_missing_source_never_adds_an_equity_capture(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("crt_radar.ibkr_market_health_sources", text)
        self.assertNotIn('"--four-asset-prices"', text)
        self.assertIn("FOUR_ASSET_DAILY_SOURCE_MISSING_PRICES_BLOCKED", text)
        self.assertIn("FOUR_ASSET_DAILY_SOURCE_PRESENT_REQUIRES_VALIDATION", text)


@unittest.skipUnless(os.name == "nt", "Daily PowerShell entry requires Windows")
class QualifiedEquityDailyEntryDynamicTests(unittest.TestCase):
    def setUp(self):
        self.powershell = shutil.which("powershell.exe")
        self.assertIsNotNone(self.powershell)
        self.temp = tempfile.TemporaryDirectory(prefix="crt-q2-equity-entry-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "synthetic-repo"
        self.runtime = self.root / "synthetic-runtime"
        registry = self.repo / "radar/CONFIG/SOURCE_REGISTRY_V1.2.json"
        registry.parent.mkdir(parents=True)
        registry.write_text("{}", encoding="utf-8")
        self.trace = self.root / "daily-arguments.json"
        self.source = self.runtime / "market-health/sources/four-asset-daily-proof.json"

    def write_proof(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(daily_proof()), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def invoke(self, *, source=None):
        # Execute the actual entry, stopping at the first Python invocation.
        # No collector/issuer/ETP executables exist in this synthetic repo.
        # All other external commands are trapped before they can run.
        source_argument = "" if source is None else f"-QualifiedEquityDailySource {ps_literal(source)}"
        code = f"""
$ErrorActionPreference = 'Stop'
function global:Get-Command {{
    param($Name, $ErrorAction)
    if ($Name -ne 'python') {{ throw 'UNEXPECTED_COMMAND_RESOLUTION' }}
    [pscustomobject]@{{ Source = 'Q2-SyntheticPython' }}
}}
function global:Q2-SyntheticPython {{
    [System.IO.File]::WriteAllText({ps_literal(self.trace)}, (ConvertTo-Json -InputObject @($args) -Compress))
    throw 'Q2_TEST_STOP_AT_DAILY_RUNNER'
}}
foreach ($CommandName in @('Start-Process','Get-CimInstance','Invoke-WebRequest',
    'Invoke-RestMethod','python.exe','git')) {{
    Set-Item -LiteralPath ('function:global:' + $CommandName) -Value {{ throw 'Q2_FORBIDDEN_EXTERNAL_COMMAND' }}
}}
& {ps_literal(SCRIPT)} -RepoRoot {ps_literal(self.repo)} -RuntimeRoot {ps_literal(self.runtime)} -RunMode OBSERVATION {source_argument}
"""
        encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
        process = subprocess.run(
            [self.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stderr = process.stderr.decode("utf-8", errors="replace")
        stdout = process.stdout.decode("utf-8", errors="replace")
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("Q2_TEST_STOP_AT_DAILY_RUNNER", stderr)
        self.assertNotIn("Q2_FORBIDDEN_EXTERNAL_COMMAND", stderr)
        arguments = json.loads(self.trace.read_text(encoding="utf-8"))
        self.assertEqual(arguments[:2], ["-m", "crt_radar.daily_evidence_runner"])
        self.assertFalse((self.runtime / "evidence/latest.json").exists())
        self.assertFalse((self.runtime / "observations.sqlite3").exists())
        self.assertEqual(list((self.runtime / "gpt_bridge/outbox").iterdir()), [])
        return arguments, stdout

    def test_default_retained_proof_is_passed_once_without_rewriting(self):
        before = self.write_proof(self.source)
        arguments, stdout = self.invoke()
        index = arguments.index("--qualified-equity-daily-source")
        self.assertEqual(arguments[index + 1], str(self.source))
        self.assertEqual(arguments.count("--qualified-equity-daily-source"), 1)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        self.assertIn("SOURCE_PRESENT_REQUIRES_VALIDATION", stdout)

    def test_explicit_source_overrides_default_and_preserves_both(self):
        original = self.write_proof(self.source)
        explicit = self.root / "retained [four asset] proof.json"
        selected = self.write_proof(explicit)
        arguments, _ = self.invoke(source=explicit)
        self.assertEqual(arguments[arguments.index("--qualified-equity-daily-source") + 1], str(explicit))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)
        self.assertEqual(hashlib.sha256(explicit.read_bytes()).hexdigest(), selected)

    def test_missing_source_does_not_reuse_legacy_two_asset_file(self):
        legacy = self.source.with_name("equity-daily-proof.json")
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"synthetic_legacy_two_asset":true}', encoding="utf-8")
        before = legacy.read_bytes()
        arguments, stdout = self.invoke()
        self.assertNotIn("--qualified-equity-daily-source", arguments)
        self.assertFalse(self.source.exists())
        self.assertEqual(legacy.read_bytes(), before)
        self.assertIn("SOURCE_MISSING_PRICES_BLOCKED", stdout)

    def test_directory_is_not_promoted_to_a_source_file(self):
        self.source.mkdir(parents=True)
        arguments, stdout = self.invoke()
        self.assertNotIn("--qualified-equity-daily-source", arguments)
        self.assertIn("SOURCE_MISSING_PRICES_BLOCKED", stdout)


if __name__ == "__main__":
    unittest.main()
