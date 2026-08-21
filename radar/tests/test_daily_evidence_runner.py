from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.daily_evidence_runner import run_daily_evidence, write_json_atomic
from crt_radar.liquidation_aggregator import canonical_json_bytes, sha256_hex
from crt_radar.source_gate_runner import FetchResult
from crt_radar.source_registry import SourceRegistry
from layer_fixtures import supplemental_overrides


REGISTRY_PATH = ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"
NOW_MS = 1785549120000


class DailyEvidenceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.registry = SourceRegistry.load(REGISTRY_PATH)
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

    def aggregate(self) -> dict:
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

    def test_gate_to_pack_first_run_is_partial_and_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(
                self.registry,
                observation_db=Path(td) / "observations.sqlite3",
                fetch_overrides=self.overrides,
                liquidation_aggregate_payload=self.aggregate(),
                now_ms=NOW_MS,
                generated_at_ms=NOW_MS,
            )
        self.assertEqual(pack["pack_state"], "PARTIAL_FOR_ANALYST")
        self.assertEqual(pack["authority"]["external_action_authority"], "NONE")
        self.assertFalse(pack["authority"]["external_action_performed"])
        self.assertTrue(pack["authority"]["analyst_judgment_required"])
        self.assertIn("L2", pack["layers"])
        self.assertIn("L4", pack["layers"])
        self.assertIn("L5", pack["layers"])
        self.assertIsNone(pack["analyst_output"]["season"])
        self.assertIsNone(pack["analyst_output"]["capital_strategy"])
        self.assertIn("btc_bull_validation", pack)
        self.assertEqual(
            pack["btc_bull_validation"]["authority"]["external_action_authority"],
            "NONE",
        )
        self.assertFalse(
            pack["btc_bull_validation"]["machine_may_confirm_bull_transition"]
        )
        candidate = pack["formal_candidate"]
        self.assertEqual(candidate["candidate_status"], "FORMAL_CANDIDATE_NOT_APPROVED")
        self.assertEqual(candidate["model_state"], "BLOCKED")
        self.assertIsNone(candidate["formal_score"])
        self.assertEqual(candidate["formal_model"], "NOT_APPROVED")
        self.assertEqual(candidate["production"], "NOT_APPROVED")
        self.assertEqual(candidate["action_output"], "NONE")
        self.assertEqual(candidate["external_action_authority"], "NONE")
        self.assertFalse(candidate["external_action_performed"])
        scoring = pack["model_status"]["locked_formal_scoring"]
        self.assertEqual(scoring["state"], "CANDIDATE_BLOCKED")
        self.assertIsNone(scoring["score"])
        self.assertEqual(scoring["formal_model"], "NOT_APPROVED")
        router = pack["model_status"]["btc_season_router"]
        self.assertEqual(router["state"], "CANDIDATE_BLOCKED")
        self.assertEqual(router["reason"], "V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED")
        self.assertIsNone(router["season"])

    def test_critical_source_failure_propagates_blocked(self):
        self.overrides[self.oi.source_id] = FetchResult(self.oi.source_id, "ERROR", error="timeout")
        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(
                self.registry,
                observation_db=Path(td) / "observations.sqlite3",
                fetch_overrides=self.overrides,
                liquidation_aggregate_payload=self.aggregate(),
                now_ms=NOW_MS,
                generated_at_ms=NOW_MS,
            )
        self.assertEqual(pack["pack_state"], "BLOCKED")
        self.assertIn("OPEN_INTEREST_TRANSPORT_ERROR", pack["data_health"]["critical_blockers"])
        l4 = pack["layers"].get("L4", {}).get("metrics", {})
        self.assertNotIn("open_interest_contracts", l4)

    def test_atomic_writer_round_trips_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested" / "latest.json"
            payload = {"pack_state": "PARTIAL_FOR_ANALYST", "authority": {"external_action_authority": "NONE"}}
            write_json_atomic(path, payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
