from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.liquidation_aggregator import (
    LiquidationStore,
    SnapshotCorruption,
    build_snapshot,
    load_verified_snapshot,
    verify_snapshot,
    write_snapshot,
)
from crt_radar.liquidation_collector import PersistentLiquidationCollector
from crt_radar.source_gate_runner import FetchResult, run_source_gate
from crt_radar.source_registry import SourceRegistry
from layer_fixtures import supplemental_overrides

NOW_MS = 1785549120000
REGISTRY_PATH = ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"


def event(*, event_ms: int, side: str, price: str = "64000", qty: str = "1"):
    return {
        "e": "forceOrder",
        "E": event_ms,
        "o": {
            "s": "BTCUSDT",
            "S": side,
            "o": "LIMIT",
            "f": "IOC",
            "q": qty,
            "p": price,
            "ap": price,
            "X": "FILLED",
            "l": qty,
            "z": qty,
            "T": event_ms,
        },
    }


class LiquidationAggregatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LiquidationStore(self.root)
        self.registry = SourceRegistry.load(REGISTRY_PATH)

    def tearDown(self):
        self.tmp.cleanup()

    def full_session(self):
        sid = self.store.begin_session(opened_ms=NOW_MS - 86400_000, session_id="full")
        self.store.end_session(sid, closed_ms=NOW_MS, close_reason="TEST")

    def test_duplicate_event_is_deduplicated_and_raw_is_append_only_once(self):
        payload = event(event_ms=NOW_MS - 1000, side="SELL")
        self.assertTrue(self.store.ingest_force_order(payload, received_ms=NOW_MS))
        self.assertFalse(self.store.ingest_force_order(payload, received_ms=NOW_MS + 1))
        raw_files = list((self.root / "raw" / "events").glob("*.jsonl"))
        self.assertEqual(len(raw_files), 1)
        self.assertEqual(len(raw_files[0].read_text().splitlines()), 1)

    def test_sell_maps_to_long_and_buy_maps_to_short(self):
        self.full_session()
        self.store.ingest_force_order(event(event_ms=NOW_MS - 2000, side="SELL", qty="2"), received_ms=NOW_MS)
        self.store.ingest_force_order(event(event_ms=NOW_MS - 1000, side="BUY", qty="3"), received_ms=NOW_MS)
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snap["windows"]["1h"]["long_liquidation_usd"], 128000.0)
        self.assertEqual(snap["windows"]["1h"]["short_liquidation_usd"], 192000.0)

    def test_out_of_order_event_is_retained_without_clock_failure(self):
        self.full_session()
        self.assertTrue(self.store.ingest_force_order(event(event_ms=NOW_MS - 1000, side="SELL"), received_ms=NOW_MS))
        self.assertTrue(self.store.ingest_force_order(event(event_ms=NOW_MS - 2000, side="BUY"), received_ms=NOW_MS))
        rows = self.store.events_between(NOW_MS - 3600_000, NOW_MS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(int(row["out_of_order"]) for row in rows), 1)
        self.assertEqual(build_snapshot(self.store, as_of_ms=NOW_MS)["quality_state"], "VALID_FRESH_COMPLETE_COVERAGE")

    def test_future_clock_skew_is_rejected_and_blocks_snapshot(self):
        self.full_session()
        accepted = self.store.ingest_force_order(
            event(event_ms=NOW_MS + 301_000, side="SELL"),
            received_ms=NOW_MS,
        )
        self.assertFalse(accepted)
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snap["quality_state"], "BLOCKED")
        self.assertIn("CLOCK_OR_SCHEMA_ANOMALY_WITHIN_24H", snap["blocked_reasons"])

    def test_quiet_window_is_valid_when_coverage_is_complete(self):
        self.full_session()
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snap["quality_state"], "VALID_FRESH_COMPLETE_COVERAGE")
        self.assertTrue(snap["windows"]["1h"]["quiet_window"])
        self.assertEqual(snap["windows"]["24h"]["total_liquidation_usd"], 0)

    def test_disconnection_gap_reduces_coverage_and_cannot_be_filled_with_zero(self):
        first = self.store.begin_session(opened_ms=NOW_MS - 86400_000, session_id="a")
        self.store.end_session(first, closed_ms=NOW_MS - 12 * 3600_000, close_reason="DROP")
        second = self.store.begin_session(opened_ms=NOW_MS - 10 * 3600_000, session_id="b", reconnect_index=1)
        self.store.end_session(second, closed_ms=NOW_MS, close_reason="TEST")
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snap["quality_state"], "BLOCKED")
        self.assertLess(snap["coverage_ratio"], 0.95)
        self.assertGreater(snap["windows"]["24h"]["gap_ms"], 0)


    def test_orphan_recovery_closes_at_last_heartbeat_not_restart_time(self):
        sid = self.store.begin_session(opened_ms=NOW_MS - 10_000, session_id="orphan")
        self.store.touch_session(sid, heartbeat_ms=NOW_MS - 5_000)
        self.assertEqual(self.store.recover_orphan_sessions(), 1)
        intervals = self.store.intervals_overlapping(NOW_MS - 20_000, NOW_MS)
        self.assertEqual(intervals, [(NOW_MS - 10_000, NOW_MS - 5_000, "orphan")])

    def test_restart_reconnect_intervals_merge_deterministically(self):
        a = self.store.begin_session(opened_ms=NOW_MS - 86400_000, session_id="a")
        self.store.end_session(a, closed_ms=NOW_MS - 1000, close_reason="RESTART")
        b = self.store.begin_session(opened_ms=NOW_MS - 1000, session_id="b", reconnect_index=1)
        self.store.end_session(b, closed_ms=NOW_MS, close_reason="TEST")
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snap["coverage_ratio"], 1.0)
        self.assertEqual(snap["quality_state"], "VALID_FRESH_COMPLETE_COVERAGE")

    def test_window_boundaries_are_start_exclusive_end_inclusive(self):
        self.full_session()
        self.store.ingest_force_order(event(event_ms=NOW_MS - 3600_000, side="SELL", qty="1"), received_ms=NOW_MS)
        self.store.ingest_force_order(event(event_ms=NOW_MS - 3599_999, side="BUY", qty="2"), received_ms=NOW_MS)
        self.store.ingest_force_order(event(event_ms=NOW_MS, side="SELL", qty="3"), received_ms=NOW_MS)
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snap["windows"]["1h"]["event_count"], 2)
        self.assertEqual(snap["windows"]["24h"]["event_count"], 3)

    def test_same_store_and_asof_produce_same_snapshot_hash(self):
        self.full_session()
        self.store.ingest_force_order(event(event_ms=NOW_MS - 1000, side="SELL"), received_ms=NOW_MS)
        a = build_snapshot(self.store, as_of_ms=NOW_MS)
        b = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(a["snapshot_hash"], b["snapshot_hash"])
        self.assertEqual(a["event_set_hash"], b["event_set_hash"])

    def test_snapshot_corruption_is_detected(self):
        self.full_session()
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        path = self.root / "snapshots" / "latest.json"
        write_snapshot(snap, path)
        loaded = json.loads(path.read_text())
        loaded["coverage_ratio"] = 0.123
        path.write_text(json.dumps(loaded))
        with self.assertRaises(SnapshotCorruption):
            load_verified_snapshot(path)

    def test_valid_snapshot_round_trip(self):
        self.full_session()
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        path = self.root / "snapshots" / "latest.json"
        write_snapshot(snap, path)
        loaded = load_verified_snapshot(path)
        verify_snapshot(loaded)
        self.assertEqual(loaded["snapshot_hash"], snap["snapshot_hash"])

    def test_source_gate_accepts_valid_aggregate_snapshot(self):
        self.full_session()
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        fred = self.registry.by_input_family("DOLLAR_STRENGTH_PROXY")
        oi = self.registry.by_input_family("OPEN_INTEREST")
        funding = self.registry.by_input_family("FUNDING_RATE")
        overrides = {
            fred.source_id: FetchResult(fred.source_id, "OK", payload="DATE,DTWEXBGS\n2026-07-31,120.5\n"),
            oi.source_id: FetchResult(oi.source_id, "OK", payload={"symbol":"BTCUSDT","openInterest":"100","time":NOW_MS-1000}),
            funding.source_id: FetchResult(funding.source_id, "OK", payload=[{"symbol":"BTCUSDT","fundingRate":"0.0001","fundingTime":NOW_MS-1000,"markPrice":"64000"}]),
        }
        overrides.update(supplemental_overrides(self.registry, NOW_MS))
        result = run_source_gate(
            self.registry,
            fetch_overrides=overrides,
            liquidation_aggregate_payload=snap,
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "OBSERVATION_ONLY")
        self.assertEqual(result["action_output"], "NONE")

    def test_collector_has_no_external_action_authority(self):
        collector = PersistentLiquidationCollector(
            self.registry,
            self.store,
            snapshot_path=self.root / "snapshots" / "latest.json",
        )
        self.assertEqual(collector.external_action_authority, "NONE")
        text = (ROOT / "src" / "crt_radar" / "liquidation_collector.py").read_text()
        for forbidden in ("place_order", "create_order", "cancel_order", "api_key", "secret_key"):
            self.assertNotIn(forbidden, text.lower())

    def test_registry_declares_live_shadow_harness_ready_not_run(self):
        aggregate = self.registry.by_input_family("LIQUIDATION_AGGREGATES")
        self.assertEqual(aggregate.raw["implementation_state"], "LIVE_SHADOW_HARNESS_READY_NOT_RUN")
        self.assertEqual(aggregate.raw["snapshot_schema"], "CRT_LIQ_AGGREGATE_SNAPSHOT_V1")

    def test_source_gate_rejects_aggregator_snapshot_with_blocked_quality(self):
        # Full coverage first, then inject a clock anomaly so the snapshot is internally BLOCKED.
        self.full_session()
        self.store.ingest_force_order(
            event(event_ms=NOW_MS + 301_000, side="SELL"),
            received_ms=NOW_MS,
        )
        snap = build_snapshot(self.store, as_of_ms=NOW_MS)
        self.assertEqual(snap["quality_state"], "BLOCKED")
        fred = self.registry.by_input_family("DOLLAR_STRENGTH_PROXY")
        oi = self.registry.by_input_family("OPEN_INTEREST")
        funding = self.registry.by_input_family("FUNDING_RATE")
        overrides = {
            fred.source_id: FetchResult(fred.source_id, "OK", payload="DATE,DTWEXBGS\n2026-07-31,120.5\n"),
            oi.source_id: FetchResult(oi.source_id, "OK", payload={"symbol":"BTCUSDT","openInterest":"100","time":NOW_MS-1000}),
            funding.source_id: FetchResult(funding.source_id, "OK", payload=[{"symbol":"BTCUSDT","fundingRate":"0.0001","fundingTime":NOW_MS-1000,"markPrice":"64000"}]),
        }
        overrides.update(supplemental_overrides(self.registry, NOW_MS))
        result = run_source_gate(
            self.registry,
            fetch_overrides=overrides,
            liquidation_aggregate_payload=snap,
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "BLOCKED")
        self.assertIn("LIQUIDATION_AGGREGATES_INVALID", result["blocked_reasons"])

    def test_connection_interval_starts_after_successful_websocket_open_in_source(self):
        text = (ROOT / "src" / "crt_radar" / "liquidation_collector.py").read_text()
        connect_pos = text.index("with connect(")
        begin_pos = text.index("self.store.begin_session", connect_pos)
        self.assertGreater(begin_pos, connect_pos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
