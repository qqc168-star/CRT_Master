from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crt_radar.liquidation_aggregator import LiquidationStore, build_snapshot
from crt_radar.live_shadow_evidence import archive_snapshot
from crt_radar.run_ledger import GENESIS_HASH, RunLedger, RunLedgerError


NOW_MS = 1_800_000_000_000


class RunLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = RunLedger(self.root / "ledger" / "run_ledger.jsonl")

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        store = LiquidationStore(self.root / "runtime")
        sid = store.begin_session(opened_ms=NOW_MS - 86_400_000, session_id="full")
        store.end_session(sid, closed_ms=NOW_MS, close_reason="TEST")
        return build_snapshot(store, as_of_ms=NOW_MS)

    def test_empty_ledger_is_valid(self):
        report = self.ledger.validate()
        self.assertTrue(report.valid)
        self.assertEqual(report.record_count, 0)
        self.assertEqual(report.head_hash, GENESIS_HASH)

    def test_hash_chain_is_contiguous_and_append_only(self):
        a = self.ledger.append_process_event(
            "PROCESS_START",
            process_run_id="p1",
            observed_ms=NOW_MS - 1000,
        )
        b = self.ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id="p1",
            observed_ms=NOW_MS,
        )
        self.assertEqual(b["prev_record_hash"], a["record_hash"])
        report = self.ledger.validate(expected_head_hash=b["record_hash"])
        self.assertTrue(report.valid)
        self.assertEqual(report.record_count, 2)

    def test_tamper_is_detected_and_future_append_is_refused(self):
        self.ledger.append_process_event("PROCESS_START", process_run_id="p1", observed_ms=NOW_MS)
        rows = self.ledger.records()
        rows[0]["payload"]["event"] = "TAMPERED"
        self.ledger.path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
        self.assertFalse(self.ledger.validate().valid)
        with self.assertRaises(RunLedgerError):
            self.ledger.append_process_event("PROCESS_STOP", process_run_id="p1")

    def test_torn_tail_is_detected(self):
        self.ledger.path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.path.write_bytes(b'{"partial":true}')
        report = self.ledger.validate()
        self.assertFalse(report.valid)
        self.assertIn("torn append", report.errors[0])

    def test_snapshot_is_archived_and_duplicate_append_is_skipped(self):
        snapshot = self.snapshot()
        archive = archive_snapshot(snapshot, self.root / "runtime" / "snapshots" / "archive")
        first = self.ledger.append_snapshot(
            snapshot,
            registry_hash="a" * 64,
            archive_path=archive.relative_to(self.root / "runtime").as_posix(),
            elapsed_ms=3,
            process_run_id="p1",
        )
        second = self.ledger.append_snapshot(
            snapshot,
            registry_hash="a" * 64,
            archive_path=archive.relative_to(self.root / "runtime").as_posix(),
            elapsed_ms=3,
            process_run_id="p1",
        )
        self.assertEqual(first["append_status"], "APPENDED")
        self.assertEqual(second["append_status"], "DUPLICATE_SKIPPED")
        self.assertEqual(self.ledger.validate().record_count, 1)

    def test_external_action_authority_is_always_none(self):
        row = self.ledger.append_process_event("PROCESS_START", process_run_id="p1")
        self.assertEqual(row["external_action_authority"], "NONE")
        self.assertFalse(row["external_action_performed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
