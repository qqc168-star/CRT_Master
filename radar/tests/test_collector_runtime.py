from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from crt_radar.liquidation_aggregator import LiquidationStore
from crt_radar.liquidation_collector import PersistentLiquidationCollector
from crt_radar.source_registry import SourceRegistry


ROOT = Path(__file__).resolve().parents[1]


def force_order(now_ms: int) -> str:
    return json.dumps(
        {
            "e": "forceOrder",
            "E": now_ms,
            "o": {
                "s": "BTCUSDT",
                "S": "SELL",
                "T": now_ms,
                "ap": "60000",
                "z": "0.25",
            },
        }
    )


class FakeWebSocket:
    def __init__(self, messages: list[str | bytes | None]):
        self.messages = list(messages)

    def recv(self, timeout: float):
        if self.messages:
            value = self.messages.pop(0)
            if value is None:
                raise ConnectionError("synthetic stream close")
            return value
        time.sleep(min(timeout, 0.002))
        raise TimeoutError


class FakeConnection:
    def __init__(self, websocket: FakeWebSocket):
        self.websocket = websocket

    def __enter__(self):
        return self.websocket

    def __exit__(self, exc_type, exc, tb):
        return False


class CollectorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = SourceRegistry.load(ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json")
        self.store = LiquidationStore(self.root)
        self.snapshots: list[dict] = []
        self.collector = PersistentLiquidationCollector(
            self.registry,
            self.store,
            snapshot_path=self.root / "snapshots" / "latest.json",
            snapshot_interval_s=0.01,
            snapshot_callback=lambda snapshot, elapsed: self.snapshots.append(snapshot),
        )

    def tearDown(self):
        self.temp.cleanup()

    def _counts(self):
        with closing(sqlite3.connect(self.store.db_path)) as db:
            events = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            anomalies = int(db.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0])
            sessions = int(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
            open_sessions = int(
                db.execute("SELECT COUNT(*) FROM sessions WHERE closed_ms IS NULL").fetchone()[0]
            )
        return events, anomalies, sessions, open_sessions

    def test_actual_run_loop_ingests_event_closes_session_and_emits_snapshots(self):
        ws = FakeWebSocket([force_order(int(time.time() * 1000))])
        with patch("websockets.sync.client.connect", return_value=FakeConnection(ws)):
            self.collector.run_forever(max_runtime_s=0.04, base_backoff_s=0.001)
        events, anomalies, sessions, open_sessions = self._counts()
        self.assertEqual(events, 1)
        self.assertEqual(anomalies, 0)
        self.assertEqual(sessions, 1)
        self.assertEqual(open_sessions, 0)
        self.assertGreaterEqual(len(self.snapshots), 2)
        self.assertTrue((self.root / "snapshots" / "latest.json").exists())

    def test_malformed_json_is_audited_and_blocks_snapshot(self):
        ws = FakeWebSocket(["not-json"])
        with patch("websockets.sync.client.connect", return_value=FakeConnection(ws)):
            self.collector.run_forever(max_runtime_s=0.03, base_backoff_s=0.001)
        events, anomalies, _, open_sessions = self._counts()
        self.assertEqual(events, 0)
        self.assertEqual(anomalies, 1)
        self.assertEqual(open_sessions, 0)
        self.assertTrue(self.snapshots)
        self.assertEqual(self.snapshots[-1]["quality_state"], "BLOCKED")
        self.assertIn("CLOCK_OR_SCHEMA_ANOMALY_WITHIN_24H", self.snapshots[-1]["blocked_reasons"])

    def test_connection_failures_reconnect_and_do_not_oversleep_runtime(self):
        calls = {"count": 0}

        def connect_side_effect(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("synthetic connect failure")
            return FakeConnection(FakeWebSocket([]))

        started = time.monotonic()
        with patch("websockets.sync.client.connect", side_effect=connect_side_effect), patch(
            "crt_radar.liquidation_collector.random.random", return_value=0.0
        ):
            self.collector.run_forever(
                max_runtime_s=0.04,
                base_backoff_s=10.0,
                max_backoff_s=10.0,
            )
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(calls["count"], 1)
        self.assertLess(elapsed, 0.25)
        self.assertEqual(self._counts()[3], 0)

    def test_outage_still_emits_periodic_blocked_snapshots(self):
        with patch("websockets.sync.client.connect", side_effect=OSError("offline")), patch(
            "crt_radar.liquidation_collector.random.random", return_value=0.0
        ):
            self.collector.run_forever(
                max_runtime_s=0.04,
                base_backoff_s=0.02,
                max_backoff_s=0.02,
            )
        self.assertGreaterEqual(len(self.snapshots), 2)
        self.assertTrue(all(row["quality_state"] == "BLOCKED" for row in self.snapshots))
        self.assertEqual(self._counts()[3], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
