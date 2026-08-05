from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from crt_radar.live_shadow_runner import LiveShadowPolicy, run_live_shadow


ROOT = Path(__file__).resolve().parents[1]


class LiveShadowRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name) / "runtime"
        self.ledger = self.runtime / "ledger" / "run_ledger.jsonl"
        self.policy = LiveShadowPolicy(
            duration_s=1,
            snapshot_interval_s=1,
            minimum_coverage_ratio=0.95,
            required_controlled_restarts=1,
            controlled_restart_after_s=1,
            controlled_restart_gap_s=0.01,
            minimum_snapshot_delivery_ratio=0.95,
            maximum_snapshot_gap_s=3,
            maximum_snapshot_clock_skew_s=300,
            elapsed_duration_tolerance_s=0.1,
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def fake_collector_run(collector, *, max_runtime_s=None, **kwargs):
        duration = float(max_runtime_s or 0.0)
        now_ms = int(time.time() * 1000)
        sid = collector.store.begin_session(opened_ms=now_ms - 86_400_000)
        if duration:
            time.sleep(duration)
        end_ms = int(time.time() * 1000)
        collector.store.end_session(sid, closed_ms=end_ms, close_reason="SYNTHETIC_RUNNER_TEST")
        collector._emit_snapshot(end_ms)

    def test_orchestrator_can_pass_a_small_explicit_test_policy(self):
        with patch(
            "crt_radar.live_shadow_runner.PersistentLiquidationCollector.run_forever",
            new=self.fake_collector_run,
        ):
            summary = run_live_shadow(
                registry_path=ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json",
                runtime_root=self.runtime,
                ledger_path=self.ledger,
                policy=self.policy,
                duration_s=1.0,
                controlled_restart_after_s=0.5,
                controlled_restart_gap_s=0.01,
            )
        self.assertEqual(summary["decision"], "LIVE_SHADOW_PASS")
        self.assertEqual(summary["controlled_restart_count"], 1)
        self.assertEqual(summary["process_stop_outcomes"], ["COMPLETED"])
        self.assertGreaterEqual(summary["snapshot_count"], 2)
        self.assertFalse(summary["acceptance_failures"])

    def test_orchestrator_failure_is_preserved_as_evidence(self):
        def fail_run(collector, *, max_runtime_s=None, **kwargs):
            raise RuntimeError("synthetic collector failure")

        with patch(
            "crt_radar.live_shadow_runner.PersistentLiquidationCollector.run_forever",
            new=fail_run,
        ):
            summary = run_live_shadow(
                registry_path=ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json",
                runtime_root=self.runtime,
                ledger_path=self.ledger,
                policy=self.policy,
                duration_s=0.1,
                controlled_restart_after_s=0.05,
                controlled_restart_gap_s=0.0,
            )
        self.assertEqual(summary["decision"], "LIVE_SHADOW_NOT_YET_PASSED")
        self.assertIn("PROCESS_NOT_COMPLETED", summary["acceptance_failures"])
        self.assertIn("NO_SNAPSHOTS", summary["acceptance_failures"])
        self.assertEqual(summary["process_stop_outcomes"], ["ERROR"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
