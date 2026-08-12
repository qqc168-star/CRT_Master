from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
RUNNER_PATH = RESEARCH / "prospective_capture.py"
AUDIT_PATH = RESEARCH / "etp_capture_audit.py"
RUN_SCRIPT = ROOT / "scripts" / "windows" / "run_etp_prospective_capture_windows.ps1"
VERIFY_SCRIPT = ROOT / "scripts" / "windows" / "verify_etp_prospective_capture_windows.ps1"
CONTRACT_PATH = RESEARCH / "CRT_ETP_PROSPECTIVE_CAPTURE_CONTRACT_V0.1.json"
ADAPTER_CONTRACT_PATH = RESEARCH / "CRT_ETP_ISSUER_ADAPTER_CONTRACT_V0.1.json"
ACQUISITION_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_ACQUISITION_CONTRACT_V0.1.json"
AUTHORITY_PATH = RESEARCH / "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json"
SOURCE_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2.json"
PROTOCOL_PATH = RESEARCH / "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2.json"
VECTORS_PATH = ROOT / "tests" / "fixtures" / "etp_issuer_adapter_vectors_v0.1.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(RESEARCH))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(RESEARCH))
    return module


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1_000)


class ResearchEtpCaptureCommissioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = _load_module("prospective_capture_commissioning_runner", RUNNER_PATH)
        cls.audit = _load_module("etp_capture_audit_tests", AUDIT_PATH)
        cls.capture_contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.adapter_contract = json.loads(ADAPTER_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.acquisition_contract = json.loads(
            ACQUISITION_CONTRACT_PATH.read_text(encoding="utf-8")
        )
        cls.authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
        cls.source_contract = json.loads(SOURCE_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        cls.vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))

    def _fetcher(self, *, mutate=None):
        def fetcher(*, ticker, url, timeout_s, max_bytes):
            del timeout_s, max_bytes
            raw = self.vectors["complete_visible_text"][ticker].encode("utf-8")
            if mutate is not None:
                raw = mutate(ticker, raw)
            return {
                "status_code": 200,
                "final_url": url,
                "content_type": "text/plain",
                "body": raw,
                "retrieved_at_ms": _ms("2026-08-11T00:30:00+00:00"),
            }

        return fetcher

    def _run(self, root: Path, *, mutate=None):
        now_ms = _ms("2026-08-11T00:30:00+00:00")
        with patch.object(self.runner.time, "time", return_value=now_ms / 1_000), patch.object(
            self.runner,
            "fetch_official_bytes",
            side_effect=self._fetcher(mutate=mutate),
        ):
            return self.runner.run_capture_cycle(
                root,
                capture_contract=self.capture_contract,
                adapter_contract=self.adapter_contract,
                acquisition_contract=self.acquisition_contract,
                public_source_authority=self.authority,
                source_contract=self.source_contract,
                walk_forward_protocol=self.protocol,
            )

    def test_complete_capture_archive_replays_and_audits_all_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._run(root)
            report = self.audit.audit_capture_archive(root)

        self.assertEqual(report["state"], "SHADOW_CAPTURE_AUDIT_PASS")
        self.assertEqual(report["run_report_count"], 1)
        self.assertEqual(report["receipt_count"], 6)
        self.assertEqual(report["manifest_count"], 1)
        self.assertEqual(report["raw_artifact_count"], 6)
        self.assertEqual(report["identity_metadata_count"], 6)
        self.assertEqual(report["replayed_snapshot_count"], 6)
        self.assertEqual(report["captured_observation_count"], 6)
        self.assertEqual(report["complete_capture_run_count"], 1)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["mode"], "SHADOW_ONLY")
        self.assertEqual(report["formal_model"], "NOT_APPROVED")
        self.assertEqual(report["production"], "NOT_APPROVED")
        self.assertEqual(report["external_action_authority"], "NONE")
        self.assertFalse(report["historical_dataset_ready"])

    def test_non_capture_run_passes_integrity_without_claiming_commissioning(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            closed_ms = _ms("2026-08-16T00:30:00+00:00")
            with patch.object(self.runner.time, "time", return_value=closed_ms / 1_000):
                result = self.runner.run_capture_cycle(
                    root,
                    capture_contract=self.capture_contract,
                    adapter_contract=self.adapter_contract,
                    acquisition_contract=self.acquisition_contract,
                    public_source_authority=self.authority,
                    source_contract=self.source_contract,
                    walk_forward_protocol=self.protocol,
                )
            self.assertEqual(result["state"], "MARKET_CLOSED_NO_CAPTURE")
            report = self.audit.audit_capture_archive(root)
            self.assertEqual(report["state"], "INTEGRITY_PASS_NO_CAPTURE")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.audit.main(["--archive-root", str(root)]), 0)
                self.assertEqual(
                    self.audit.main(
                        ["--archive-root", str(root), "--require-complete-capture"]
                    ),
                    3,
                )

    def test_empty_archive_is_not_misreported_as_commissioned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self.audit.audit_capture_archive(root)
            self.assertEqual(report["state"], "EMPTY_ARCHIVE")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.audit.main(["--archive-root", str(root)]), 3)

    def test_tampering_and_orphan_evidence_fail_closed(self):
        tamper_cases = ("run", "receipt", "manifest", "raw", "identity")
        for kind in tamper_cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                run = self._run(root)
                paths = {
                    "run": next(root.glob("capture_runs/sha256/*/*.json")),
                    "receipt": next(root.glob("capture_receipts/sha256/*/*.json")),
                    "manifest": root / run["manifest"]["relpath"],
                    "raw": next(root.glob("artifacts/sha256/*/*")),
                    "identity": next(root.glob("metadata/identities/*/*.json")),
                }
                paths[kind].write_bytes(paths[kind].read_bytes() + b" ")
                audit = self.audit.audit_capture_archive(root)
                self.assertEqual(audit["state"], "BLOCKED")
                self.assertTrue(audit["errors"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._run(root)
            next(root.glob("capture_runs/sha256/*/*.json")).unlink()
            audit = self.audit.audit_capture_archive(root)
            self.assertEqual(audit["state"], "BLOCKED")
            self.assertTrue(any("UNREFERENCED_" in error for error in audit["errors"]))

    def test_rehashed_semantic_forgery_and_unexpected_alias_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            closed_ms = _ms("2026-08-16T00:30:00+00:00")
            with patch.object(self.runner.time, "time", return_value=closed_ms / 1_000):
                self.runner.run_capture_cycle(
                    root,
                    capture_contract=self.capture_contract,
                    adapter_contract=self.adapter_contract,
                    acquisition_contract=self.acquisition_contract,
                    public_source_authority=self.authority,
                    source_contract=self.source_contract,
                    walk_forward_protocol=self.protocol,
                )
            old_path = next(root.glob("capture_runs/sha256/*/*.json"))
            forged = json.loads(old_path.read_text(encoding="utf-8"))
            forged["state"] = "COMPLETE_SHADOW_CAPTURE"
            raw = self.runner.canonical_bytes(forged) + b"\n"
            digest = self.runner.sha256_bytes(raw)
            new_path = root / f"capture_runs/sha256/{digest[:2]}/{digest}.json"
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_bytes(raw)
            old_path.unlink()

            audit = self.audit.audit_capture_archive(root)
            self.assertEqual(audit["state"], "BLOCKED")
            self.assertTrue(any("RUN_REPORT_STATE_MISMATCH" in error for error in audit["errors"]))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._run(root)
            alias = root / "capture_runs" / "alias.json"
            alias.write_text("{}\n", encoding="utf-8")
            audit = self.audit.audit_capture_archive(root)
            self.assertEqual(audit["state"], "BLOCKED")
            self.assertTrue(any("UNEXPECTED_MANAGED_FILE" in error for error in audit["errors"]))

    def test_rehashed_extreme_timestamp_and_malformed_identity_return_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            closed_ms = _ms("2026-08-16T00:30:00+00:00")
            with patch.object(self.runner.time, "time", return_value=closed_ms / 1_000):
                self.runner.run_capture_cycle(
                    root,
                    capture_contract=self.capture_contract,
                    adapter_contract=self.adapter_contract,
                    acquisition_contract=self.acquisition_contract,
                    public_source_authority=self.authority,
                    source_contract=self.source_contract,
                    walk_forward_protocol=self.protocol,
                )
            old_path = next(root.glob("capture_runs/sha256/*/*.json"))
            forged = json.loads(old_path.read_text(encoding="utf-8"))
            forged["run_at_ms"] = 10**30
            raw = self.runner.canonical_bytes(forged) + b"\n"
            digest = self.runner.sha256_bytes(raw)
            new_path = root / f"capture_runs/sha256/{digest[:2]}/{digest}.json"
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_bytes(raw)
            old_path.unlink()
            audit = self.audit.audit_capture_archive(root)
            self.assertEqual(audit["state"], "BLOCKED")
            self.assertTrue(any("RUN_AT_OUT_OF_RANGE" in error for error in audit["errors"]))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._run(root)
            identity_path = next(root.glob("metadata/identities/*/*.json"))
            record = json.loads(identity_path.read_text(encoding="utf-8"))
            record["artifact"].pop("request_identity")
            record["record_sha256"] = self.runner.candidate_acquisition._record_hash(record)
            identity_path.write_bytes(self.runner.canonical_bytes(record) + b"\n")
            audit = self.audit.audit_capture_archive(root)
            self.assertEqual(audit["state"], "BLOCKED")
            self.assertTrue(
                any("IDENTITY_FIELDS_INVALID" in error for error in audit["errors"])
            )

    def test_partial_retry_archive_retains_and_audits_staged_raw(self):
        def stale_ibit(ticker, raw):
            return raw.replace(b"Aug 10, 2026", b"Aug 07, 2026") if ticker == "IBIT" else raw

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self._run(root, mutate=stale_ibit)
            self.assertEqual(run["state"], "PARTIAL_RETRY_REQUIRED")
            audit = self.audit.audit_capture_archive(root)

        self.assertEqual(audit["state"], "INTEGRITY_PASS_PARTIAL_CAPTURE")
        self.assertEqual(audit["run_report_count"], 1)
        self.assertEqual(audit["receipt_count"], 5)
        self.assertEqual(audit["raw_artifact_count"], 6)
        self.assertEqual(audit["captured_observation_count"], 5)
        self.assertEqual(audit["replayed_snapshot_count"], 5)
        self.assertEqual(audit["complete_capture_run_count"], 0)

    def test_audit_and_windows_operator_surface_remain_read_only_and_unscheduled(self):
        source = AUDIT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue({"argparse", "json", "pathlib"}.issubset(imports))
        self.assertTrue(
            {"urllib", "requests", "httpx", "aiohttp", "socket", "subprocess"}.isdisjoint(
                imports
            )
        )
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            {
                "write_bytes",
                "write_text",
                "mkdir",
                "unlink",
                "rename",
                "replace",
            }.isdisjoint(called_attributes)
        )
        for forbidden in (
            "fetch_official_bytes(",
            "run_capture_cycle(",
            "place_order",
            "create_order",
            "external_action_authority\": \"TRADE",
        ):
            self.assertNotIn(forbidden, source)

        run_text = RUN_SCRIPT.read_text(encoding="utf-8-sig")
        verify_text = VERIFY_SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("research\\prospective_capture.py", run_text)
        self.assertIn("research\\etp_capture_audit.py", run_text)
        self.assertIn("research\\etp_capture_audit.py", verify_text)
        self.assertIn("--require-complete-capture", verify_text)
        self.assertIn("runtime\\etp_prospective_capture", run_text)
        self.assertLess(run_text.index("$RunnerExit"), run_text.index("$AuditExit"))
        self.assertLess(run_text.index("$AuditExit"), run_text.index("$RunnerExit -ne 0"))
        for text in (run_text, verify_text):
            for forbidden in (
                "Register-ScheduledTask",
                "Start-Job",
                "Start-Process",
                "while (",
                "Invoke-WebRequest",
                "Remove-Item",
                "Set-Content",
                "Add-Content",
                "place_order",
                "create_order",
                "api_key",
            ):
                self.assertNotIn(forbidden, text)

        runtime_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("etp_capture_audit", runtime_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
