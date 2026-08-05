from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crt_radar.liquidation_aggregator import LiquidationStore, build_snapshot
from crt_radar.live_shadow_evidence import (
    archive_snapshot,
    build_evidence_summary,
)
from crt_radar.live_shadow_runner import ShadowSnapshotRecorder, preflight_report
from crt_radar.run_ledger import RunLedger


NOW_MS = 1_800_000_000_000
ROOT = Path(__file__).resolve().parents[1]


class LiveShadowEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.store = LiquidationStore(self.runtime)
        self.ledger = RunLedger(self.runtime / "ledger" / "run_ledger.jsonl")
        self.process_run_id = "process-1"

    def tearDown(self):
        self.temp.cleanup()

    def full_snapshot(self):
        sid = self.store.begin_session(opened_ms=NOW_MS - 86_400_000, session_id="full")
        self.store.end_session(sid, closed_ms=NOW_MS, close_reason="TEST")
        return build_snapshot(self.store, as_of_ms=NOW_MS)

    def populate_pass_case(self):
        self.ledger.append_process_event(
            "PROCESS_START",
            process_run_id=self.process_run_id,
            observed_ms=NOW_MS - 10_000,
        )
        self.ledger.append_process_event(
            "CONTROLLED_RESTART",
            process_run_id=self.process_run_id,
            observed_ms=NOW_MS - 5_000,
        )
        snapshot = self.full_snapshot()
        recorder = ShadowSnapshotRecorder(
            runtime_root=self.runtime,
            ledger=self.ledger,
            registry_hash="b" * 64,
            process_run_id=self.process_run_id,
        )
        recorder(snapshot, 4)
        self.ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id=self.process_run_id,
            details={"outcome": "COMPLETED", "elapsed_s": 10.0},
            observed_ms=NOW_MS,
        )

    def test_summary_passes_when_policy_evidence_is_met(self):
        self.populate_pass_case()
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
            minimum_coverage_ratio=0.95,
            required_controlled_restarts=1,
        )
        self.assertEqual(summary["decision"], "LIVE_SHADOW_PASS")
        self.assertEqual(summary["snapshot_count"], 1)
        self.assertEqual(summary["controlled_restart_count"], 1)
        self.assertFalse(summary["acceptance_failures"])

    def test_default_24h_policy_cannot_be_faked_by_short_fixture(self):
        self.populate_pass_case()
        summary = build_evidence_summary(self.runtime, self.ledger.path)
        self.assertEqual(summary["decision"], "LIVE_SHADOW_NOT_YET_PASSED")
        self.assertIn("LIVE_DURATION_BELOW_POLICY", summary["acceptance_failures"])

    def test_archive_corruption_blocks_acceptance(self):
        self.populate_pass_case()
        archive = next((self.runtime / "snapshots" / "archive").glob("*.json"))
        row = json.loads(archive.read_text())
        row["coverage_ratio"] = 0.1
        archive.write_text(json.dumps(row), encoding="utf-8")
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
        )
        self.assertIn("SNAPSHOT_ARCHIVE_INVALID", summary["acceptance_failures"])

    def test_preflight_checks_registry_route_store_and_ledger(self):
        report = preflight_report(
            registry_path=ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json",
            runtime_root=self.runtime,
            ledger_path=self.ledger.path,
        )
        self.assertEqual(report["decision"], "PREFLIGHT_PASS")
        self.assertTrue(report["checks"]["market_route"])
        self.assertTrue(report["checks"]["public_route_forbidden"])
        self.assertEqual(report["checks"]["external_action_authority"], "NONE")

    def test_missing_restart_is_not_accepted(self):
        snapshot = self.full_snapshot()
        archive = archive_snapshot(snapshot, self.runtime / "snapshots" / "archive")
        self.ledger.append_process_event(
            "PROCESS_START", process_run_id=self.process_run_id, observed_ms=NOW_MS - 10_000
        )
        self.ledger.append_snapshot(
            snapshot,
            registry_hash="b" * 64,
            archive_path=archive.relative_to(self.runtime).as_posix(),
            elapsed_ms=1,
            process_run_id=self.process_run_id,
        )
        self.ledger.append_process_event(
            "PROCESS_STOP", process_run_id=self.process_run_id, details={"outcome": "COMPLETED", "elapsed_s": 10.0}, observed_ms=NOW_MS
        )
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
            required_controlled_restarts=1,
        )
        self.assertIn("CONTROLLED_RESTART_MISSING", summary["acceptance_failures"])

    def test_blocked_snapshot_is_preserved_and_fails_acceptance(self):
        sid = self.store.begin_session(opened_ms=NOW_MS - 86_400_000, session_id="partial")
        self.store.end_session(sid, closed_ms=NOW_MS - 10_000_000, close_reason="DROP")
        snapshot = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snapshot["quality_state"], "BLOCKED")
        archive = archive_snapshot(snapshot, self.runtime / "snapshots" / "archive")
        self.ledger.append_process_event(
            "PROCESS_START", process_run_id=self.process_run_id, observed_ms=NOW_MS - 10_000
        )
        self.ledger.append_process_event(
            "CONTROLLED_RESTART", process_run_id=self.process_run_id, observed_ms=NOW_MS - 5_000
        )
        self.ledger.append_snapshot(
            snapshot,
            registry_hash="b" * 64,
            archive_path=archive.relative_to(self.runtime).as_posix(),
            elapsed_ms=1,
            process_run_id=self.process_run_id,
        )
        self.ledger.append_process_event(
            "PROCESS_STOP", process_run_id=self.process_run_id, details={"outcome": "COMPLETED", "elapsed_s": 10.0}, observed_ms=NOW_MS
        )
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
        )
        self.assertIn("BLOCKED_SNAPSHOT_PRESENT", summary["acceptance_failures"])


    def _record_snapshot(self, snapshot, *, process_run_id=None, registry_hash="b" * 64, archive_path=None):
        process_run_id = process_run_id or self.process_run_id
        if archive_path is None:
            archive = archive_snapshot(snapshot, self.runtime / "snapshots" / "archive")
            archive_path = archive.relative_to(self.runtime).as_posix()
        return self.ledger.append_snapshot(
            snapshot,
            registry_hash=registry_hash,
            archive_path=archive_path,
            elapsed_ms=1,
            process_run_id=process_run_id,
        )

    def test_future_snapshot_cannot_fake_required_duration(self):
        future_ms = NOW_MS + 86_400_000
        store = LiquidationStore(self.runtime)
        sid = store.begin_session(opened_ms=future_ms - 86_400_000, session_id="future-full")
        store.end_session(sid, closed_ms=future_ms, close_reason="TEST")
        snapshot = build_snapshot(store, as_of_ms=future_ms)
        self.ledger.append_process_event(
            "PROCESS_START", process_run_id=self.process_run_id, observed_ms=NOW_MS - 10_000
        )
        self.ledger.append_process_event(
            "CONTROLLED_RESTART", process_run_id=self.process_run_id, observed_ms=NOW_MS - 5_000
        )
        self._record_snapshot(snapshot)
        self.ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id=self.process_run_id,
            details={"outcome": "COMPLETED", "elapsed_s": 10.0},
            observed_ms=NOW_MS,
        )
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=86_400,
            maximum_snapshot_clock_skew_s=300,
        )
        self.assertIn("LIVE_DURATION_BELOW_POLICY", summary["acceptance_failures"])
        self.assertIn("PROCESS_ELAPSED_BELOW_POLICY", summary["acceptance_failures"])
        self.assertIn("SNAPSHOT_CLOCK_OUTSIDE_PROCESS_WINDOW", summary["acceptance_failures"])

    def test_previous_run_restart_does_not_satisfy_latest_run(self):
        self.populate_pass_case()
        latest_run = "process-2"
        later_ms = NOW_MS + 20_000
        self.ledger.append_process_event(
            "PROCESS_START", process_run_id=latest_run, observed_ms=later_ms - 10_000
        )
        snapshot = build_snapshot(self.store, as_of_ms=later_ms - 1_000)
        self._record_snapshot(snapshot, process_run_id=latest_run)
        self.ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id=latest_run,
            details={"outcome": "COMPLETED", "elapsed_s": 10.0},
            observed_ms=later_ms,
        )
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
            required_controlled_restarts=1,
        )
        self.assertEqual(summary["process_run_id"], latest_run)
        self.assertIn("CONTROLLED_RESTART_MISSING", summary["acceptance_failures"])

    def test_archive_path_escape_is_blocked(self):
        snapshot = self.full_snapshot()
        outside = self.root / "outside.json"
        from crt_radar.liquidation_aggregator import write_snapshot
        write_snapshot(snapshot, outside)
        self.ledger.append_process_event(
            "PROCESS_START", process_run_id=self.process_run_id, observed_ms=NOW_MS - 10_000
        )
        self.ledger.append_process_event(
            "CONTROLLED_RESTART", process_run_id=self.process_run_id, observed_ms=NOW_MS - 5_000
        )
        self._record_snapshot(snapshot, archive_path="../../outside.json")
        self.ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id=self.process_run_id,
            details={"outcome": "COMPLETED", "elapsed_s": 10.0},
            observed_ms=NOW_MS,
        )
        summary = build_evidence_summary(self.runtime, self.ledger.path, minimum_duration_s=10)
        self.assertIn("SNAPSHOT_ARCHIVE_INVALID", summary["acceptance_failures"])

    def test_registry_hash_mismatch_is_blocked(self):
        self.populate_pass_case()
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
            expected_registry_hash="c" * 64,
        )
        self.assertIn("SOURCE_REGISTRY_HASH_MISMATCH", summary["acceptance_failures"])

    def test_snapshot_delivery_ratio_and_gap_are_enforced(self):
        self.populate_pass_case()
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
            snapshot_interval_s=2,
            minimum_snapshot_delivery_ratio=0.95,
            maximum_snapshot_gap_s=3,
        )
        self.assertIn("SNAPSHOT_DELIVERY_RATIO_BELOW_POLICY", summary["acceptance_failures"])
        self.assertIn("SNAPSHOT_GAP_ABOVE_POLICY", summary["acceptance_failures"])

    def test_reported_elapsed_time_must_cover_policy_duration(self):
        snapshot = self.full_snapshot()
        self.ledger.append_process_event(
            "PROCESS_START", process_run_id=self.process_run_id, observed_ms=NOW_MS - 10_000
        )
        self.ledger.append_process_event(
            "CONTROLLED_RESTART", process_run_id=self.process_run_id, observed_ms=NOW_MS - 5_000
        )
        self._record_snapshot(snapshot)
        self.ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id=self.process_run_id,
            details={"outcome": "COMPLETED", "elapsed_s": 1.0},
            observed_ms=NOW_MS,
        )
        summary = build_evidence_summary(
            self.runtime,
            self.ledger.path,
            minimum_duration_s=10,
            elapsed_duration_tolerance_s=0.0,
        )
        self.assertIn("PROCESS_ELAPSED_BELOW_POLICY", summary["acceptance_failures"])

    def test_unpaired_segment_events_are_blocked(self):
        snapshot = self.full_snapshot()
        self.ledger.append_process_event(
            "PROCESS_START", process_run_id=self.process_run_id, observed_ms=NOW_MS - 10_000
        )
        self.ledger.append_process_event(
            "SEGMENT_START",
            process_run_id=self.process_run_id,
            details={"segment_index": 0},
            observed_ms=NOW_MS - 9_000,
        )
        self.ledger.append_process_event(
            "CONTROLLED_RESTART", process_run_id=self.process_run_id, observed_ms=NOW_MS - 5_000
        )
        self._record_snapshot(snapshot)
        self.ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id=self.process_run_id,
            details={"outcome": "COMPLETED", "elapsed_s": 10.0},
            observed_ms=NOW_MS,
        )
        summary = build_evidence_summary(self.runtime, self.ledger.path, minimum_duration_s=10)
        self.assertIn("SEGMENT_PAIR_MISMATCH", summary["acceptance_failures"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
