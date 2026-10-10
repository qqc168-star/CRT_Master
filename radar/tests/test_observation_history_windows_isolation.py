from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest


WINDOWS_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "windows"
SCRIPT = WINDOWS_SCRIPTS / "run_observation_history_windows.ps1"
STANDBY = [
    "ISOLATED_ALIGNMENT_STANDBY",
    "NO_OBSERVATION_CYCLE",
    "NO_CAPITAL_REFRESH",
    "NO_GPT_DELIVERY",
    "NO_NOTIFICATION_DELIVERY",
]


def snapshot(root: Path) -> dict[str, str | None]:
    return {
        str(path.relative_to(root)): (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        for path in root.rglob("*")
    }


class WindowsObservers:
    """Observe test files and OS process ancestry outside the tested shell.

    ReadDirectoryChangesW records writes even if content is subsequently restored.
    Process snapshots independently observe descendants; short-lived processes can
    escape polling, so calibrated command traps additionally fail closed before
    the daily entry can resolve paths, write files, or launch a process.
    """

    def __init__(self, root: Path):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.ReadDirectoryChangesW.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        self.handle = self.kernel.CreateFileW(str(root), 1, 7, None, 3, 0x02000000, None)
        if self.handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.file_events: list[tuple[int, str]] = []
        self.process_parents: dict[int, int] = {}
        self.process_names: dict[int, str] = {}
        self.errors: list[int] = []
        self.file_thread = threading.Thread(target=self._files, daemon=True)
        self.process_thread = threading.Thread(target=self._processes, daemon=True)
        self.file_thread.start()
        self.process_thread.start()
        if not self.ready.wait(2):
            raise RuntimeError("Windows file observer did not start")

    def _files(self):
        buffer = ctypes.create_string_buffer(65536)
        count = wintypes.DWORD()
        self.ready.set()
        while not self.stop.is_set():
            ok = self.kernel.ReadDirectoryChangesW(
                self.handle, buffer, len(buffer), True, 0x0000011F,
                ctypes.byref(count), None, None,
            )
            if not ok:
                if not self.stop.is_set():
                    self.errors.append(ctypes.get_last_error())
                return
            if not count.value:
                self.errors.append(1022)  # ERROR_NOTIFY_ENUM_DIR: event buffer overflow.
                return
            offset = 0
            while offset < count.value:
                following, action, length = struct.unpack_from("III", buffer.raw, offset)
                name = buffer.raw[offset + 12:offset + 12 + length].decode("utf-16-le")
                self.file_events.append((action, name))
                if not following:
                    break
                offset += following

    def _processes(self):
        class Entry(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 260),
            ]
        self.kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        while not self.stop.is_set():
            handle = self.kernel.CreateToolhelp32Snapshot(2, 0)
            if handle == wintypes.HANDLE(-1).value:
                self.errors.append(ctypes.get_last_error())
                return
            entry = Entry()
            entry.size = ctypes.sizeof(entry)
            more = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            while more:
                self.process_parents[entry.pid] = entry.parent
                self.process_names[entry.pid] = entry.name
                more = self.kernel.Process32NextW(handle, ctypes.byref(entry))
            self.kernel.CloseHandle(handle)
            self.stop.wait(0.01)

    def descendants(self, root_pid: int) -> set[int]:
        result = {root_pid}
        while True:
            enlarged = result | {
                pid for pid, parent in self.process_parents.copy().items()
                if parent in result
            }
            if enlarged == result:
                return result - {root_pid}
            result = enlarged

    def close(self):
        self.stop.set()
        self.kernel.CancelIoEx(self.handle, None)
        self.file_thread.join(2)
        self.process_thread.join(2)
        self.kernel.CloseHandle(self.handle)


def ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class ObservationHistoryIsolationContractTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_only_explicit_observation_mode_can_select_normal_body(self):
        self.assertIn('[ValidateSet("ISOLATION_ONLY", "OBSERVATION")]', self.text)
        self.assertIn('[string]$RunMode = "ISOLATION_ONLY"', self.text)
        guard = self.text.index('if ($RunMode -eq "ISOLATION_ONLY")')
        first_path = self.text.index('$RadarRoot = Join-Path')
        self.assertLess(guard, first_path)
        self.assertLess(self.text.index("exit 0", guard), first_path)
        self.assertNotIn("$env:", self.text[guard:first_path])

    def test_standby_explicitly_excludes_each_live_cycle_and_override(self):
        guard = self.text[self.text.index('if ($RunMode -eq "ISOLATION_ONLY")'):
                          self.text.index('if ($null -ne $AcceptanceWakePercentile)')]
        for status in STANDBY:
            self.assertIn(f'Write-Output "{status}"', guard)
        for parameter in ("AcceptanceWakePercentile", "ConfirmAcceptanceWakeOverride"):
            self.assertIn(f'$PSBoundParameters.ContainsKey("{parameter}")', guard)
        self.assertIn("throw", guard)

    def test_normal_external_entry_contracts_are_retained(self):
        for original in (
            '"--observe-broker-capital"', "crt_radar.gpt_transport_worker",
            "crt_radar.gpt_notification_boundary", "deliver-pending",
            "crt_radar.issuer_announcement_runner", "$CollectorRunner", "$EtpCaptureIfDue",
            "crt_radar.daily_evidence_runner", "--capital-state $EvidenceOutput",
            "--capital-source-dir $CapitalSourceDir",
        ):
            self.assertIn(original, self.text)

    def test_existing_callers_choose_modes_explicitly_without_task_change(self):
        acceptance = (WINDOWS_SCRIPTS / "run_one_gpt_acceptance_override_windows.ps1").read_text(encoding="utf-8")
        installer = (WINDOWS_SCRIPTS / "install_observation_history_task_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("-RunMode OBSERVATION", acceptance)
        self.assertNotIn("-RunMode OBSERVATION", installer)
        self.assertNotIn("-RunMode", installer)


@unittest.skipUnless(os.name == "nt", "Windows dynamic entry isolation requires Windows")
class ObservationHistoryIsolationDynamicTests(unittest.TestCase):
    def setUp(self):
        self.powershell = shutil.which("powershell.exe")
        if not self.powershell:
            self.fail("Windows PowerShell is required for dynamic entry verification")
        self.temp = tempfile.TemporaryDirectory(prefix="crt-entry-isolation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "observed"
        self.root.mkdir()
        self.repo = self.root / "synthetic-repo"
        self.runtime = self.root / "synthetic-runtime"
        for index in range(27):
            event = f"synthetic-event-{index:02d}"
            for folder, payload in (
                ("outbox", {"event_id": event, "synthetic": True}),
                ("transport_boundary", {"event_id": event, "state": "PENDING" if index < 25 else "DELIVERED"}),
            ):
                path = self.runtime / "gpt_bridge" / folder / f"{event}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
            if index >= 25:
                receipt = self.runtime / "gpt_bridge" / "transport_boundary" / f"{event}.response.json"
                receipt.write_text(json.dumps({"synthetic": True, "event_id": event, "receipt": "preserved"}), encoding="utf-8")
        self.marker = self.root / "forbidden-operation.marker"
        self.script_hash = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        self.before = snapshot(self.root)
        self.observers = WindowsObservers(self.root)
        self.addCleanup(self.observers.close)
        self._calibrate_observers_and_traps()

    def _shell(self, body: str, *, parameters: dict[str, str] | None = None):
        assignments = "\n".join(
            f"$Invocation.{name} = {value}" for name, value in (parameters or {}).items()
        )
        code = f"""
$ErrorActionPreference = 'Stop'
$Marker = {ps_literal(self.marker)}
function global:Forbidden-Operation {{
    [System.IO.File]::AppendAllText($Marker, 'ATTEMPTED_OPERATION' + [Environment]::NewLine)
    throw 'ISOLATION_TEST_FORBIDDEN_OPERATION'
}}
foreach ($CommandName in @('Join-Path','Test-Path','New-Item','Set-Content','Add-Content',
    'Out-File','Remove-Item','Move-Item','Copy-Item','Start-Process','Get-CimInstance',
    'Invoke-WebRequest','Invoke-RestMethod','python','python.exe','git','cmd.exe')) {{
    Set-Item -LiteralPath ('function:global:' + $CommandName) -Value ${{function:Forbidden-Operation}}
}}
$Invocation = @{{ RepoRoot = {ps_literal(self.repo)}; RuntimeRoot = {ps_literal(self.runtime)} }}
{assignments}
{body}
"""
        encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
        env = os.environ.copy()
        env["CRT_GPT_TRANSPORT_ENABLED"] = "1"
        process = subprocess.Popen(
            [self.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            stdout, stderr = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
            raise
        time.sleep(0.15)
        return process, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    def _calibrate_observers_and_traps(self):
        process, _, stderr = self._shell("Start-Process -FilePath 'must-not-launch.exe'")
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("ISOLATION_TEST_FORBIDDEN_OPERATION", stderr)
        self.assertTrue(self.marker.is_file(), "Operation trap must leave independently observed evidence")
        self.assertTrue(any(name == self.marker.name for _, name in self.observers.file_events))
        self.marker.unlink()
        calibration = subprocess.Popen(
            [sys.executable, "-c", "import subprocess,sys;subprocess.run([sys.executable,'-c','import time;time.sleep(.4)'])"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        calibration.wait(timeout=10)
        time.sleep(0.15)
        self.assertIn(
            Path(sys.executable).name.lower(),
            [self.observers.process_names[pid].lower()
             for pid in self.observers.descendants(calibration.pid)],
            "OS observer must detect the real harmless Python child, beyond its console host",
        )
        host, _, _ = self._shell("Write-Output 'HOST_CALIBRATION_ONLY'")
        self.host_children = sorted(
            self.observers.process_names[pid]
            for pid in self.observers.descendants(host.pid)
        )
        self.assertTrue(
            all(name.lower() == "conhost.exe" for name in self.host_children),
            "Empty PowerShell host may only create its Windows console host",
        )
        self.assertEqual(self.observers.errors, [])
        self.observers.file_events.clear()

    def _assert_isolated(self, parameters=None, *, expected_success=True):
        process, stdout, stderr = self._shell(f"& {ps_literal(SCRIPT)} @Invocation", parameters=parameters)
        if expected_success:
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout.splitlines(), STANDBY)
        else:
            self.assertNotEqual(process.returncode, 0)
            self.assertNotIn("ISOLATED_ALIGNMENT_STANDBY", stdout)
        self.assertFalse(self.marker.exists(), "No normal-path operation may be attempted")
        self.assertEqual(
            sorted(self.observers.process_names[pid] for pid in self.observers.descendants(process.pid)),
            self.host_children,
            "Daily entry must create no subprocess beyond the calibrated Windows console host",
        )
        self.assertEqual(self.observers.file_events, [], "OS file observer saw a write, create, delete, or rename")
        self.assertEqual(self.observers.errors, [])
        self.assertEqual(snapshot(self.root), self.before)
        self.assertEqual(hashlib.sha256(SCRIPT.read_bytes()).hexdigest(), self.script_hash)
        self.assertFalse(self.repo.exists())
        self.assertFalse((self.runtime / "evidence").exists())
        self.assertFalse((self.runtime / "gpt_bridge" / "notifications").exists())

    def test_default_mode_with_provider_enabled_preserves_all_historical_events(self):
        self._assert_isolated()

    def test_explicit_isolation_with_provider_enabled_preserves_all_historical_events(self):
        self._assert_isolated({"RunMode": "'ISOLATION_ONLY'"})

    def test_missing_runtime_and_repo_do_not_create_directories(self):
        self._assert_isolated({"RuntimeRoot": ps_literal(self.root / "missing-runtime")})
        self.assertFalse((self.root / "missing-runtime").exists())

    def test_isolation_rejects_acceptance_percentile(self):
        self._assert_isolated({"AcceptanceWakePercentile": "95"}, expected_success=False)

    def test_isolation_rejects_explicit_null_acceptance_percentile(self):
        self._assert_isolated({"AcceptanceWakePercentile": "$null"}, expected_success=False)

    def test_isolation_rejects_acceptance_confirmation(self):
        self._assert_isolated({"ConfirmAcceptanceWakeOverride": "$true"}, expected_success=False)

    def test_isolation_rejects_explicit_false_acceptance_confirmation(self):
        self._assert_isolated({"ConfirmAcceptanceWakeOverride": "$false"}, expected_success=False)

    def test_invalid_mode_fails_closed(self):
        self._assert_isolated({"RunMode": "'INVALID_MODE'"}, expected_success=False)


if __name__ == "__main__":
    unittest.main()
