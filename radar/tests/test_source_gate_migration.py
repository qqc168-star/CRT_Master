from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.source_gate_runner import FetchResult, parse_coinmetrics_caps, parse_funding, run_source_gate
from crt_radar.liquidation_aggregator import canonical_json_bytes, sha256_hex
from crt_radar.source_registry import RegistryError, SourceRegistry
from layer_fixtures import supplemental_overrides


REGISTRY_PATH = ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"
NOW_MS = 1785549120000


class SourceGateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = SourceRegistry.load(REGISTRY_PATH)
        self.fred = self.registry.by_input_family("DOLLAR_STRENGTH_PROXY")
        self.oi = self.registry.by_input_family("OPEN_INTEREST")
        self.funding = self.registry.by_input_family("FUNDING_RATE")
        self.probe = self.registry.by_input_family("LIQUIDATION_CONNECTIVITY_PROBE")
        self.onchain = self.registry.by_input_family("ONCHAIN_VALUE")
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
                    "markPrice": "64000"
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
                    "data": [
                        {
                            "asset": "btc",
                            "time": "2026-07-31T00:00:00.000000000Z",
                            "CapMrktCurUSD": "1200000000000",
                            "CapRealUSD": "600000000000",
                        },
                        {
                            "asset": "btc",
                            "time": "2026-08-01T00:00:00.000000000Z",
                            "CapMrktCurUSD": "1260000000000",
                            "CapRealUSD": "630000000000",
                        },
                    ]
                },
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

    def test_funding_three_day_mean_accepts_exchange_millisecond_jitter(self):
        start = NOW_MS - 8 * 28_800_000
        jitter_ms = [0, 0, 1, 1, 3, 2, 0, 0, 2]
        rates = [0.00001 * index for index in range(1, 10)]
        payload = [
            {
                "symbol": "BTCUSDT",
                "fundingRate": str(rate),
                "fundingTime": start + index * 28_800_000 + jitter_ms[index],
                "markPrice": "64000",
            }
            for index, rate in enumerate(rates)
        ]

        parsed = parse_funding(payload)

        self.assertAlmostEqual(parsed["abs_funding_3d_mean_bp"], 10_000 * sum(rates) / len(rates))

    def test_funding_three_day_mean_rejects_missing_interval(self):
        start = NOW_MS - 8 * 28_800_000
        payload = [
            {
                "symbol": "BTCUSDT",
                "fundingRate": "0.0001",
                "fundingTime": start + index * 28_800_000 + (60_000 if index >= 4 else 0),
                "markPrice": "64000",
            }
            for index in range(9)
        ]

        parsed = parse_funding(payload)

        self.assertNotIn("abs_funding_3d_mean_bp", parsed)

    def test_registry_uses_market_route_for_force_order(self):
        self.assertEqual(self.probe.raw["endpoint_category"], "MARKET")
        self.assertIn("/market/ws/btcusdt@forceOrder", self.probe.endpoint)
        self.assertNotIn("/public/", self.probe.endpoint)

    def test_registry_rejects_public_route_for_force_order(self):
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        item = next(x for x in payload["sources"] if x["input_family"] == "LIQUIDATION_CONNECTIVITY_PROBE")
        item["endpoint"] = "wss://fstream.binance.com/public/ws/btcusdt@forceOrder"
        item["endpoint_category"] = "PUBLIC"
        with self.assertRaises(RegistryError):
            SourceRegistry(payload)

    def test_registry_has_unique_ids_and_families(self):
        payload = self.registry.payload
        ids = [x["source_id"] for x in payload["sources"]]
        families = [x["input_family"] for x in payload["sources"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(families), len(set(families)))

    def test_active_runner_has_no_hardcoded_remote_endpoints(self):
        text = (ROOT / "src" / "crt_radar" / "source_gate_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("https://fapi.binance.com", text)
        self.assertNotIn("wss://fstream.binance.com", text)
        self.assertNotIn("https://fred.stlouisfed.org", text)

    def test_empty_connected_probe_cannot_complete_l4(self):
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "BLOCKED")
        self.assertIn("LIQUIDATION_AGGREGATOR_REQUIRED", result["blocked_reasons"])
        probe_evidence = next(x for x in result["evidence"] if x["input_family"] == "LIQUIDATION_CONNECTIVITY_PROBE")
        self.assertEqual(probe_evidence["quality_state"], "DIAGNOSTIC_ONLY")

    def test_even_probe_with_message_has_no_metric_authority(self):
        self.overrides[self.probe.source_id].payload["message_count"] = 1
        result = run_source_gate(self.registry, fetch_overrides=self.overrides, now_ms=NOW_MS)
        self.assertEqual(result["formal_state"], "BLOCKED")
        self.assertIn("LIQUIDATION_AGGREGATOR_REQUIRED", result["blocked_reasons"])

    def test_complete_aggregate_unlocks_read_only_observation(self):
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "OBSERVATION_ONLY")
        self.assertEqual(result["action_output"], "NONE")
        self.assertFalse(result["external_action_performed"])
        self.assertEqual(result["external_action_authority"], "NONE")

    def test_low_coverage_aggregate_blocks(self):
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(coverage=0.7),
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "BLOCKED")
        self.assertIn("LIQUIDATION_AGGREGATES_INVALID", result["blocked_reasons"])

    def test_stale_aggregate_blocks(self):
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(as_of_ms=NOW_MS - 3600_000),
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "BLOCKED")
        self.assertIn("LIQUIDATION_AGGREGATES_STALE", result["blocked_reasons"])

    def test_evidence_envelopes_have_hashes_and_namespaces(self):
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )
        for item in result["evidence"]:
            self.assertTrue(item["source_id"])
            self.assertTrue(item["namespace"].startswith("AS-L"))
            self.assertEqual(len(item["registry_hash"]), 64)
            self.assertEqual(len(item["evidence_hash"]), 64)
        self.assertEqual(len(result["source_registry_hash"]), 64)
        self.assertEqual(len(result["idempotency_key"]), 64)

    def test_same_snapshots_produce_same_idempotency_key(self):
        a = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )
        b = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )
        self.assertNotEqual(a["run_id"], b["run_id"])
        self.assertEqual(a["idempotency_key"], b["idempotency_key"])

    def test_missing_critical_transport_blocks(self):
        self.overrides[self.oi.source_id] = FetchResult(self.oi.source_id, "ERROR", error="timeout")
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "BLOCKED")
        self.assertIn("OPEN_INTEREST_TRANSPORT_ERROR", result["blocked_reasons"])


    def test_coinmetrics_registry_requests_latest_page(self):
        self.assertIn("paging_from=end", self.onchain.endpoint)

    def test_coinmetrics_parser_selects_latest_complete_row_and_recomputes_formulas(self):
        parsed = parse_coinmetrics_caps(self.overrides[self.onchain.source_id].payload)
        self.assertEqual(parsed["as_of_ms"], 1785542400000)
        self.assertEqual(parsed["market_cap_usd"], 1_260_000_000_000.0)
        self.assertEqual(parsed["realized_cap_usd"], 630_000_000_000.0)
        self.assertAlmostEqual(parsed["mvrv"], 2.0)
        self.assertAlmostEqual(parsed["nupl"], 0.5)

    def test_coinmetrics_missing_cap_field_is_rejected(self):
        payload = {"data": [{"asset": "btc", "time": "2026-08-01T00:00:00Z", "CapMrktCurUSD": "1"}]}
        with self.assertRaises(ValueError):
            parse_coinmetrics_caps(payload)

    def test_noncritical_onchain_failure_is_disclosed_but_does_not_block_l4(self):
        self.overrides[self.onchain.source_id] = FetchResult(
            self.onchain.source_id, "ERROR", error="synthetic outage"
        )
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )
        self.assertEqual(result["formal_state"], "OBSERVATION_ONLY")
        evidence = next(x for x in result["evidence"] if x["input_family"] == "ONCHAIN_VALUE")
        self.assertEqual(evidence["quality_state"], "TRANSPORT_ERROR")
        self.assertNotIn("ONCHAIN_VALUE_TRANSPORT_ERROR", result["blocked_reasons"])

    def test_valid_onchain_value_is_included_in_parsed_output(self):
        result = run_source_gate(
            self.registry,
            fetch_overrides=self.overrides,
            liquidation_aggregate_payload=self.aggregate(),
            now_ms=NOW_MS,
        )
        self.assertIn("ONCHAIN_VALUE", result["parsed"])
        self.assertAlmostEqual(result["parsed"]["ONCHAIN_VALUE"]["mvrv"], 2.0)
        self.assertAlmostEqual(result["parsed"]["ONCHAIN_VALUE"]["nupl"], 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
