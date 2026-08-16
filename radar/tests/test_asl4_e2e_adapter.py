from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.asl4_e2e_adapter import AdapterError, build_asl4_layer, inject_asl4_layer
from crt_radar.e2e_bridge import build_bridge_payload
from crt_radar.liquidation_aggregator import canonical_json_bytes, sha256_hex
from crt_radar.source_gate_runner import FetchResult, run_source_gate
from crt_radar.source_registry import SourceRegistry
from layer_fixtures import supplemental_overrides


REGISTRY_PATH = ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"
NOW_MS = 1785549120000


class ASL4AdapterTests(unittest.TestCase):
    def setUp(self):
        self.registry = SourceRegistry.load(REGISTRY_PATH)
        self.fred = self.registry.by_input_family("DOLLAR_STRENGTH_PROXY")
        self.oi = self.registry.by_input_family("OPEN_INTEREST")
        self.funding = self.registry.by_input_family("FUNDING_RATE")
        self.probe = self.registry.by_input_family("LIQUIDATION_CONNECTIVITY_PROBE")
        self.overrides = {
            self.fred.source_id: FetchResult(
                self.fred.source_id,
                "OK",
                payload="DATE,DTWEXBGS\n2026-07-31,120.50\n",
            ),
            self.oi.source_id: FetchResult(
                self.oi.source_id,
                "OK",
                payload={"symbol": "BTCUSDT", "openInterest": "10000", "time": NOW_MS - 30_000},
            ),
            self.funding.source_id: FetchResult(
                self.funding.source_id,
                "OK",
                payload=[{
                    "symbol": "BTCUSDT",
                    "fundingRate": "0.0001",
                    "fundingTime": NOW_MS - 60_000,
                    "markPrice": "64000",
                }],
            ),
            self.probe.source_id: FetchResult(
                self.probe.source_id,
                "PROBE_ONLY",
                payload={"connected": True, "message_count": 0, "metric_authority": "NONE"},
            ),
        }
        self.overrides.update(supplemental_overrides(self.registry, NOW_MS))

    def aggregate(self, *, coverage=1.0, as_of_ms=NOW_MS - 30_000):
        blocked = [] if coverage >= 0.95 else ["COVERAGE_BELOW_0.95"]
        base = {
            "schema_version": "CRT_LIQ_AGGREGATE_SNAPSHOT_V1",
            "store_schema_version": "CRT_LIQ_STORE_V1",
            "symbol": "BTCUSDT",
            "as_of_ms": as_of_ms,
            "generated_at_ms": as_of_ms,
            "minimum_coverage_ratio": 0.95,
            "coverage_ratio": coverage,
            "quality_state": "VALID_FRESH_COMPLETE_COVERAGE" if not blocked else "BLOCKED",
            "blocked_reasons": blocked,
            "windows": {
                "1h": {
                    "window_start_ms": as_of_ms - 3_600_000,
                    "window_end_ms": as_of_ms,
                    "long_liquidation_usd": 100.0,
                    "short_liquidation_usd": 50.0,
                    "total_liquidation_usd": 150.0,
                    "event_count": 2,
                    "coverage_ratio": coverage,
                    "covered_ms": int(3_600_000 * coverage),
                    "gap_ms": int(3_600_000 * (1 - coverage)),
                    "quiet_window": False,
                },
                "24h": {
                    "window_start_ms": as_of_ms - 86_400_000,
                    "window_end_ms": as_of_ms,
                    "long_liquidation_usd": 1000.0,
                    "short_liquidation_usd": 500.0,
                    "total_liquidation_usd": 1500.0,
                    "event_count": 20,
                    "coverage_ratio": coverage,
                    "covered_ms": int(86_400_000 * coverage),
                    "gap_ms": int(86_400_000 * (1 - coverage)),
                    "quiet_window": False,
                },
            },
            "event_set_hash": "0" * 64,
            "connection_set_hash": "1" * 64,
            "event_count_24h": 20,
            "anomaly_count_24h": 0,
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
        base["snapshot_id"] = sha256_hex(canonical_json_bytes(base))
        base["snapshot_hash"] = sha256_hex(canonical_json_bytes(base))
        return base

    def source_gate(self, aggregate=None):
        return run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate() if aggregate is None else aggregate,
            now_ms=NOW_MS,
        )

    def test_valid_source_gate_maps_to_valid_asl4_without_score(self):
        layer = build_asl4_layer(self.source_gate())
        self.assertEqual(layer["layer_id"], "AS-L4")
        self.assertEqual(layer["status"], "VALID")
        self.assertIsNone(layer["score"])
        self.assertEqual(layer["score_origin"], "UPSTREAM_LOCKED_MODEL_REQUIRED")
        self.assertEqual([x["input_family"] for x in layer["evidence"]], [
            "OPEN_INTEREST", "FUNDING_RATE", "LIQUIDATION_AGGREGATES"
        ])
        self.assertEqual(layer["blocked_reasons"], [])
        self.assertEqual(layer["external_action_authority"], "NONE")
        self.assertEqual(len(layer["layer_input_hash"]), 64)

    def test_missing_liquidation_maps_to_missing_and_blocks_bridge(self):
        gate = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=None,
            now_ms=NOW_MS,
        )
        layer = build_asl4_layer(gate)
        self.assertEqual(layer["status"], "MISSING")
        self.assertIn("LIQUIDATION_AGGREGATOR_REQUIRED", layer["blocked_reasons"])
        bridge = build_bridge_payload(gate)
        self.assertEqual(bridge["formal_state"], "BLOCKED")
        self.assertEqual(bridge["data_status"], "BLOCKED")
        self.assertEqual(bridge["action_output"], "NONE")

    def test_stale_liquidation_maps_to_stale(self):
        gate = self.source_gate(self.aggregate(as_of_ms=NOW_MS - 3_600_000))
        layer = build_asl4_layer(gate)
        self.assertEqual(layer["status"], "STALE")
        self.assertIn("LIQUIDATION_AGGREGATES_STALE", layer["blocked_reasons"])

    def test_invalid_coverage_maps_to_invalid(self):
        gate = self.source_gate(self.aggregate(coverage=0.70))
        layer = build_asl4_layer(gate)
        self.assertEqual(layer["status"], "INVALID")
        self.assertIn("LIQUIDATION_AGGREGATES_INVALID", layer["blocked_reasons"])

    def test_same_input_yields_same_layer_and_bridge_idempotency(self):
        a = self.source_gate()
        b = self.source_gate()
        layer_a = build_asl4_layer(a)
        layer_b = build_asl4_layer(b)
        self.assertEqual(layer_a["layer_input_hash"], layer_b["layer_input_hash"])
        bridge_a = build_bridge_payload(a)
        bridge_b = build_bridge_payload(b)
        self.assertEqual(bridge_a["idempotency_key"], bridge_b["idempotency_key"])
        self.assertNotEqual(a["run_id"], b["run_id"])

    def test_inject_requires_explicit_overwrite(self):
        layer = build_asl4_layer(self.source_gate())
        snapshot = {"layers": {"AS-L4": {"status": "OLD"}}}
        with self.assertRaises(AdapterError):
            inject_asl4_layer(snapshot, layer)
        updated = inject_asl4_layer(snapshot, layer, overwrite=True)
        self.assertEqual(updated["layers"]["AS-L4"]["status"], "VALID")
        self.assertEqual(updated["external_operation_authority"], "NONE")

    def test_adapter_rejects_external_action_authority(self):
        gate = self.source_gate()
        gate["external_action_authority"] = "TRADE"
        with self.assertRaises(AdapterError):
            build_asl4_layer(gate)

    def test_bridge_preserves_semantic_locks(self):
        bridge = build_bridge_payload(self.source_gate())
        self.assertEqual(bridge["semantic_locks"]["mnav"], "diluted_equity_mnav")
        self.assertEqual(bridge["semantic_locks"]["q4_window"], "2026-Q4")
        self.assertEqual(bridge["external_operation_authority"], "NONE")
        self.assertFalse(bridge["external_action_performed"])

    def test_bridge_can_inject_into_upstream_snapshot(self):
        upstream = {
            "run_mode": "CONTROLLED_SNAPSHOT",
            "layers": {"AS-L1": {"status": "VALID"}},
        }
        bridge = build_bridge_payload(self.source_gate(), upstream_snapshot=deepcopy(upstream))
        snapshot = bridge["e2e_snapshot"]
        self.assertEqual(snapshot["layers"]["AS-L1"]["status"], "VALID")
        self.assertEqual(snapshot["layers"]["AS-L4"]["status"], "VALID")
        self.assertIsNone(snapshot["layers"]["AS-L4"]["score"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
