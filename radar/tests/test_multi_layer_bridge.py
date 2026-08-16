from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from crt_radar.as_evidence_adapter import build_asl2_layer, build_asl5_layer
from crt_radar.liquidation_aggregator import canonical_json_bytes, sha256_hex
from crt_radar.multi_layer_bridge import build_multi_layer_bridge
from crt_radar.source_gate_runner import FetchResult, run_source_gate
from crt_radar.source_registry import SourceRegistry
from layer_fixtures import supplemental_overrides


ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1785549120000


class MultiLayerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.registry = SourceRegistry.load(ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json")
        self.fred = self.registry.by_input_family("DOLLAR_STRENGTH_PROXY")
        self.oi = self.registry.by_input_family("OPEN_INTEREST")
        self.funding = self.registry.by_input_family("FUNDING_RATE")
        self.probe = self.registry.by_input_family("LIQUIDATION_CONNECTIVITY_PROBE")
        self.onchain = self.registry.by_input_family("ONCHAIN_VALUE")
        self.overrides = {
            self.fred.source_id: FetchResult(
                self.fred.source_id, "OK", payload="DATE,DTWEXBGS\n2026-07-31,120.50\n"
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
            self.onchain.source_id: FetchResult(
                self.onchain.source_id,
                "OK",
                payload={
                    "data": [{
                        "asset": "btc",
                        "time": "2026-08-01T00:00:00.000000000Z",
                        "CapMrktCurUSD": "1260000000000",
                        "CapRealUSD": "630000000000",
                    }]
                },
            ),
        }
        self.overrides.update(supplemental_overrides(self.registry, NOW_MS))

    def aggregate(self):
        as_of_ms = NOW_MS - 30_000
        base = {
            "schema_version": "CRT_LIQ_AGGREGATE_SNAPSHOT_V1",
            "store_schema_version": "CRT_LIQ_STORE_V1",
            "symbol": "BTCUSDT",
            "as_of_ms": as_of_ms,
            "generated_at_ms": as_of_ms,
            "minimum_coverage_ratio": 0.95,
            "coverage_ratio": 1.0,
            "quality_state": "VALID_FRESH_COMPLETE_COVERAGE",
            "blocked_reasons": [],
            "windows": {
                "1h": {
                    "window_start_ms": as_of_ms - 3_600_000,
                    "window_end_ms": as_of_ms,
                    "long_liquidation_usd": 100.0,
                    "short_liquidation_usd": 50.0,
                    "total_liquidation_usd": 150.0,
                    "event_count": 2,
                    "coverage_ratio": 1.0,
                    "covered_ms": 3_600_000,
                    "gap_ms": 0,
                    "quiet_window": False,
                },
                "24h": {
                    "window_start_ms": as_of_ms - 86_400_000,
                    "window_end_ms": as_of_ms,
                    "long_liquidation_usd": 1000.0,
                    "short_liquidation_usd": 500.0,
                    "total_liquidation_usd": 1500.0,
                    "event_count": 20,
                    "coverage_ratio": 1.0,
                    "covered_ms": 86_400_000,
                    "gap_ms": 0,
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

    def gate(self):
        return run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )

    def test_valid_source_gate_maps_to_l2_l4_l5_without_scoring(self):
        gate = self.gate()
        l2 = build_asl2_layer(gate)
        l5 = build_asl5_layer(gate)
        bridge = build_multi_layer_bridge(gate)
        self.assertEqual(l2["status"], "VALID")
        self.assertEqual(l5["status"], "VALID")
        self.assertAlmostEqual(l5["values"]["ONCHAIN_VALUE"]["mvrv"], 2.0)
        self.assertEqual(bridge["formal_state"], "OBSERVATION_ONLY")
        self.assertEqual(set(bridge["layers"]), {"AS-L2", "AS-L4", "AS-L5"})
        self.assertTrue(all(layer["score"] is None for layer in bridge["layers"].values()))
        self.assertEqual(bridge["score_authority"], "NONE")

    def test_noncritical_l5_missing_is_disclosed_without_blocking_bridge(self):
        self.overrides[self.onchain.source_id] = FetchResult(
            self.onchain.source_id, "ERROR", error="synthetic outage"
        )
        bridge = build_multi_layer_bridge(self.gate())
        self.assertEqual(bridge["formal_state"], "OBSERVATION_ONLY")
        self.assertEqual(bridge["noncritical_missing_layers"], ["AS-L5"])
        self.assertEqual(bridge["layers"]["AS-L5"]["status"], "INVALID")

    def test_critical_l2_failure_blocks_bridge(self):
        self.overrides[self.fred.source_id] = FetchResult(
            self.fred.source_id, "ERROR", error="synthetic outage"
        )
        bridge = build_multi_layer_bridge(self.gate())
        self.assertEqual(bridge["formal_state"], "BLOCKED")
        self.assertIn("AS-L2", bridge["critical_invalid_layers"])

    def test_bridge_is_deterministic_and_can_inject_upstream_snapshot(self):
        gate_a = self.gate()
        gate_b = self.gate()
        upstream = {"layers": {"AS-L1": {"status": "VALID"}}}
        a = build_multi_layer_bridge(gate_a, upstream_snapshot=deepcopy(upstream))
        b = build_multi_layer_bridge(gate_b, upstream_snapshot=deepcopy(upstream))
        self.assertEqual(a["idempotency_key"], b["idempotency_key"])
        self.assertEqual(a["e2e_snapshot"]["layers"]["AS-L1"]["status"], "VALID")
        self.assertEqual(a["e2e_snapshot"]["layers"]["AS-L5"]["status"], "VALID")
        self.assertEqual(a["external_operation_authority"], "NONE")
        self.assertFalse(a["external_action_performed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
