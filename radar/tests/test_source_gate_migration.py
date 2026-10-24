from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.source_gate_runner import (
    ContractViolation, FetchResult, parse_coinmetrics_caps, parse_funding,
    parse_price_structure, run_source_gate,
)
from crt_radar.liquidation_aggregator import canonical_json_bytes, sha256_hex
from crt_radar.source_registry import RegistryError, SourceRegistry
from layer_fixtures import DAY_MS, _price_rows, supplemental_overrides


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

        self.assertAlmostEqual(parsed["funding_3d_mean_bp"], 10_000 * sum(rates) / len(rates))
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

        self.assertNotIn("funding_3d_mean_bp", parsed)
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


class PriceStructureIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.rows = _price_rows(NOW_MS)[-201:]

    def parse(self, rows=None):
        return parse_price_structure(self.rows if rows is None else rows,
                                     captured_at_ms=NOW_MS, now_ms=NOW_MS)

    def test_complete_201_days_retains_research_scope(self):
        result = self.parse()
        self.assertEqual(result["as_of_ms"], self.rows[-1][6])
        self.assertEqual(result["source_scope"], "BINANCE_BTCUSDT_DIRECTIONAL_PROXY")
        self.assertEqual(result["formal_composite_authority"], "NONE")

    def test_missing_day_is_not_repaired_by_older_extra_bar(self):
        rows = _price_rows(NOW_MS)
        rows.pop(50)
        with self.assertRaisesRegex(ContractViolation, "consecutive"):
            self.parse(rows)

    def test_duplicate_date_is_not_counted_as_another_day(self):
        self.rows.append(deepcopy(self.rows[-1]))
        with self.assertRaisesRegex(ContractViolation, "duplicate"):
            self.parse()

    def test_original_time_order_must_be_strictly_ascending(self):
        self.rows[50], self.rows[51] = self.rows[51], self.rows[50]
        with self.assertRaisesRegex(ContractViolation, "ascending"):
            self.parse()

    def current_day_row(self, offset=0):
        row = deepcopy(self.rows[-1])
        row[0] = NOW_MS // DAY_MS * DAY_MS + offset * DAY_MS
        row[6] = row[0] + DAY_MS - 1
        return row

    def test_trailing_current_day_is_excluded_from_metrics(self):
        expected = self.parse()
        current = self.current_day_row()
        current[1:5] = ["999999", "999999", "999999", "999999"]
        self.assertEqual(self.parse(self.rows + [current]), expected)

    def test_unfinished_day_cannot_complete_a_201_day_window(self):
        with self.assertRaisesRegex(ContractViolation, "201 complete"):
            self.parse(self.rows[1:] + [self.current_day_row()])

    def test_replay_clock_cannot_complete_original_partial_bar(self):
        rows = self.rows + [self.current_day_row()]
        expected = self.parse(rows)
        for evaluation in (NOW_MS + DAY_MS, NOW_MS + 10 * DAY_MS):
            self.assertEqual(parse_price_structure(rows, captured_at_ms=NOW_MS,
                                                  now_ms=evaluation), expected)

    def test_missing_invalid_or_future_original_capture_blocks(self):
        for capture in (None, True, 0, "1785549120000", NOW_MS + 1):
            with self.subTest(capture=capture), self.assertRaises(ContractViolation):
                parse_price_structure(self.rows, captured_at_ms=capture, now_ms=NOW_MS)

    def test_gate_missing_capture_does_not_discard_independent_sources(self):
        registry = SourceRegistry.load(REGISTRY_PATH)
        spec = registry.by_input_family("PRICE_STRUCTURE_CONTEXT")
        overrides = supplemental_overrides(registry, NOW_MS)
        overrides[spec.source_id] = FetchResult(spec.source_id, "OK", payload=self.rows)
        result = run_source_gate(registry, fetch_overrides=overrides, now_ms=NOW_MS)
        evidence = next(row for row in result["evidence"] if row["source_id"] == spec.source_id)
        self.assertEqual(evidence["quality_state"], "INVALID")
        self.assertIn("capture time missing", evidence["quality_error"])
        self.assertNotIn("PRICE_STRUCTURE_CONTEXT", result["parsed"])
        self.assertIn("MACRO_CONTEXT", result["parsed"])

    def test_live_fetch_uses_actual_capture_not_run_start(self):
        registry = SourceRegistry.load(REGISTRY_PATH)
        spec = registry.by_input_family("PRICE_STRUCTURE_CONTEXT")
        def fetch(source):
            if source.source_id == spec.source_id:
                return FetchResult(source.source_id, "OK", payload=self.rows,
                                   captured_at_ms=NOW_MS + 1000)
            return FetchResult(source.source_id, "ERROR", error="ISOLATED_TEST")
        with patch("crt_radar.source_gate_runner._http_get", side_effect=fetch), \
             patch("crt_radar.source_gate_runner.time.time", side_effect=[NOW_MS / 1000] +
                   [(NOW_MS + 2000) / 1000] * 100):
            result = run_source_gate(registry)
        self.assertIn("PRICE_STRUCTURE_CONTEXT", result["parsed"])

    def test_real_oct22_archive_has_identical_completed_metrics_at_later_replay(self):
        # Public, unmodified GET /api/v3/klines?symbol=BTCUSDT&interval=1d&limit=210.
        # Sealed first_seen_at_ms == retrieved_at_ms, 2026-10-22 00:02:40.013 UTC.
        raw = (ROOT / "tests/fixtures/binance_btcusdt_20261022_capture.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "f524e37187de79df9b1004d320d9dcfa94c988edbb24079e75563e06b0696abd")
        capture = 1792627360013
        rows = json.loads(raw)
        original = parse_price_structure(rows, captured_at_ms=capture, now_ms=capture)
        complete_only = [row for row in rows if row[6] < capture]
        self.assertEqual(len(complete_only), 209)
        self.assertEqual(parse_price_structure(complete_only, captured_at_ms=capture,
                                              now_ms=capture), original)
        for delay in (DAY_MS, 3 * DAY_MS):
            self.assertEqual(parse_price_structure(rows, captured_at_ms=capture,
                                                  now_ms=capture + delay), original)
        self.assertEqual(original["as_of_ms"], 1792627199999)
        self.assertAlmostEqual(original["cvd_20d_share"], -0.009333586943610465)
        self.assertAlmostEqual(original["quote_volume_rvol20"], 1.1733621936636607)
        self.assertAlmostEqual(original["close_minus_sma200_over_atr20"], 5.475467915505541)
        self.assertAlmostEqual(original["sma50_minus_sma200_over_atr20"], 4.338353398890444)
        self.assertAlmostEqual(original["return_20d_over_atr_vol"], -0.0846890298282057)
        self.assertNotAlmostEqual(original["cvd_20d_share"], 0.002417606318939953)
        registry = SourceRegistry.load(REGISTRY_PATH)
        spec = registry.by_input_family("PRICE_STRUCTURE_CONTEXT")
        gate = run_source_gate(registry, now_ms=capture + 3 * DAY_MS,
            fetch_overrides={spec.source_id: FetchResult(spec.source_id, "OK", payload=rows,
                                                       captured_at_ms=capture)})
        evidence = next(row for row in gate["evidence"] if row["source_id"] == spec.source_id)
        self.assertEqual(evidence["quality_state"], "STALE")
        self.assertEqual(evidence["as_of_ms"], original["as_of_ms"])
        self.assertEqual(evidence["captured_at_ms"], capture)
        self.assertNotIn("PRICE_STRUCTURE_CONTEXT", gate["parsed"])

    def test_future_day_is_rejected(self):
        with self.assertRaisesRegex(ContractViolation, "future"):
            self.parse(self.rows + [self.current_day_row(offset=1)])

    def test_daily_timestamp_must_cover_one_utc_day(self):
        for field in (0, 6):
            rows = deepcopy(self.rows)
            rows[50][field] += 1
            with self.subTest(field=field), self.assertRaisesRegex(ContractViolation, "UTC day"):
                self.parse(rows)

    def test_malformed_or_fractional_timestamp_is_not_silently_dropped(self):
        for bad_row in ([self.rows[50][0]], [None] * 11):
            rows = deepcopy(self.rows)
            rows[50] = bad_row
            with self.subTest(row=bad_row), self.assertRaises(ContractViolation):
                self.parse(rows)
        self.rows[50][0] += 0.5
        with self.assertRaisesRegex(ContractViolation, "integer"):
            self.parse()

    def gate(self, rows, now_ms):
        registry = SourceRegistry.load(REGISTRY_PATH)
        spec = registry.by_input_family("PRICE_STRUCTURE_CONTEXT")
        with patch("crt_radar.source_gate_runner._http_get", side_effect=AssertionError("NO_NETWORK")):
            return run_source_gate(
                registry, now_ms=now_ms,
                fetch_overrides={spec.source_id: FetchResult(spec.source_id, "OK", payload=rows,
                                                            captured_at_ms=NOW_MS)},
            )

    def test_historical_complete_window_is_stale_not_invalid(self):
        result = self.gate(self.rows, NOW_MS + 3 * DAY_MS)
        evidence = next(row for row in result["evidence"] if row["input_family"] == "PRICE_STRUCTURE_CONTEXT")
        self.assertEqual(evidence["quality_state"], "STALE")
        self.assertEqual(evidence["as_of_ms"], self.rows[-1][6])
        self.assertNotIn("PRICE_STRUCTURE_CONTEXT", result["parsed"])

    def test_gate_uses_evaluation_clock_and_keeps_formal_l6_blocked(self):
        fresh = self.gate(self.rows + [self.current_day_row()], NOW_MS)
        self.assertIn("PRICE_STRUCTURE_CONTEXT", fresh["parsed"])
        self.assertEqual(fresh["l6_candidate_state"], "BLOCKED")
        future = self.gate(self.rows + [self.current_day_row(offset=1)], NOW_MS)
        evidence = next(row for row in future["evidence"] if row["input_family"] == "PRICE_STRUCTURE_CONTEXT")
        self.assertEqual(evidence["quality_state"], "INVALID")
        self.assertIn("future", evidence["quality_error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
