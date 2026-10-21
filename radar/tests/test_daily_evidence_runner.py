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


    def test_dvol_overlay_can_wake_analysis_without_touching_formal_locks(self):
        dvol_payload = {
            "schema_version": "CRT_DVOL_REGIME_WATCH_V0.1",
            "scope": "NON_WEIGHTED_RESEARCH_OVERLAY",
            "state": "EXPANSION_ACTIVATED",
            "reason": "TEST",
            "direction": "UNKNOWN",
            "current_dvol": 42.0,
            "dvol_30d_low": 34.0,
            "rebound_from_30d_low_pct": 23.5294117647,
            "level_percentile_1y": 8.0,
            "baseline_count": 365,
            "recommended_wake_operational_percentile": 90.0,
            "formal_model_authority": "NONE",
            "formal_weight_authority": "NONE",
            "formal_threshold_authority": "NONE",
            "season_transition_authority": "NONE",
            "investment_threshold_authority": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
            "machine_may_confirm_bull_transition": False,
            "analyst_judgment_required": True,
        }

        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(
                self.registry,
                observation_db=Path(td) / "observations.sqlite3",
                fetch_overrides=self.overrides,
                liquidation_aggregate_payload=self.aggregate(),
                now_ms=NOW_MS,
                generated_at_ms=NOW_MS,
                dvol_regime_runner=lambda **_: dvol_payload,
            )

        self.assertEqual(
            pack["dvol_regime_watch"]["state"],
            "EXPANSION_ACTIVATED",
        )
        self.assertEqual(
            pack["reanalysis_wake"]["state"],
            "REANALYSIS_REQUESTED",
        )
        self.assertEqual(
            pack["reanalysis_wake"]["reason"],
            "DVOL_EXPANSION_ACTIVATED",
        )
        self.assertEqual(
            pack["reanalysis_wake"]["operational_percentile"],
            90.0,
        )
        self.assertEqual(
            pack["model_status"]["locked_formal_scoring"][
                "layer_weights_percent"
            ],
            {
                "L1": 20,
                "L2": 20,
                "L3": 17,
                "L4": 25,
                "L5": 13,
                "L6": 5,
            },
        )
        self.assertEqual(
            pack["model_status"]["locked_formal_scoring"][
                "light_thresholds"
            ],
            [-60, -35, 35, 60],
        )
        self.assertFalse(
            pack["btc_bull_validation"][
                "machine_may_confirm_bull_transition"
            ]
        )


class LiquidationResearchWakeTests(unittest.TestCase):
    """Synthetic explicit classifications, not a real-market detection rule."""

    def setUp(self):
        from crt_radar.liquidation_aggregator import LiquidationStore, build_snapshot
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fixture = DailyEvidenceRunnerTests()
        self.fixture.setUp()
        self.db = self.root / "observations.sqlite3"
        self.raw = LiquidationStore(self.root / "synthetic-collector")
        self.session = self.raw.begin_session(opened_ms=NOW_MS - 2 * 86400_000)
        self.raw.touch_session(self.session, heartbeat_ms=NOW_MS - 60_000)
        self.run_pack(snapshot=build_snapshot(self.raw, as_of_ms=NOW_MS - 60_000), at=NOW_MS - 60_000)
        self.records = []
        self.add_event("SELL", NOW_MS - 2000, NOW_MS - 1000)
        self.raw.touch_session(self.session, heartbeat_ms=NOW_MS - 1000)
        self.snapshot = build_snapshot(self.raw, as_of_ms=NOW_MS - 1000)
        self.diagnostics = []

    def tearDown(self):
        self.tmp.cleanup()

    def add_event(self, side, event_at, received):
        from crt_radar.liquidation_aggregator import normalize_force_order
        from crt_radar.reanalysis_wake import liquidation_evidence_identity
        payload = {"e": "forceOrder", "E": event_at, "o": {
            "s": "BTCUSDT", "S": side, "T": event_at, "q": "10",
            "z": "2", "l": "2", "ap": "64000", "p": "65000", "X": "FILLED"}}
        normalized = normalize_force_order(payload, received_ms=received)
        self.raw.ingest_force_order(payload, received_ms=received)
        record = normalized.as_record()
        self.records.append(record)
        return liquidation_evidence_identity(normalized, "CRT-CONN-BTC-DERIV-LIQ-AGGREGATOR-001")

    def candidate(self, *, direction="LONG", index=0):
        from crt_radar.liquidation_aggregator import normalize_force_order
        from crt_radar.reanalysis_wake import liquidation_evidence_identity
        record = self.records[index]
        event = normalize_force_order(record["raw_payload"], received_ms=record["received_ms"])
        source = "CRT-CONN-BTC-DERIV-LIQ-AGGREGATOR-001"
        identity = liquidation_evidence_identity(event, source)
        return {"source_id": source, "symbol": "BTCUSDT", "direction": direction,
                "anchor_evidence_id": identity, "supporting_evidence_ids": [identity],
                "candidate_rule_version": "SYNTHETIC_EXPLICIT_CLASSIFICATION_V1",
                "revision": 1, "event_records": json.loads(json.dumps(self.records))}

    def run_pack(self, candidate=None, *, snapshot=None, at=NOW_MS, db=None, fail_oi=False):
        from copy import deepcopy
        from unittest.mock import patch
        from crt_radar.btc_transition_diagnostics import blocked_transition_diagnostic
        def diagnostic(**kwargs):
            self.diagnostics.append(deepcopy(kwargs["wake"]))
            return {**blocked_transition_diagnostic("SYNTHETIC_LOCAL_DIAGNOSTIC"),
                    "wake": deepcopy(kwargs["wake"])}
        overrides = deepcopy(self.fixture.overrides)
        if fail_oi:
            spec = self.fixture.oi
            overrides[spec.source_id] = FetchResult(spec.source_id, "ERROR", error="synthetic timeout")
        with patch("crt_radar.daily_evidence_runner.run_gpt_handoff_gate") as handoff:
            pack = run_daily_evidence(self.fixture.registry, observation_db=db or self.db,
                fetch_overrides=overrides, liquidation_aggregate_payload=snapshot or self.snapshot,
                now_ms=at, generated_at_ms=at, transition_diagnostic_runner=diagnostic,
                liquidation_research_candidate=candidate)
            handoff.assert_not_called()
        return pack

    def test_explicit_qualified_candidate_wakes_before_diagnostic_and_pack_agrees(self):
        pack = self.run_pack(self.candidate())
        wake = pack["reanalysis_wake"]
        self.assertEqual(wake["state"], "REANALYSIS_REQUESTED")
        self.assertEqual(wake["input_family"], "LIQUIDATION_RESEARCH")
        self.assertIn("LIQUIDATION_RESEARCH", wake["wake_sources"])
        event = wake["liquidation_research"]
        self.assertEqual(event["first_qualified_at_ms"], NOW_MS)
        self.assertEqual(self.diagnostics[-1]["liquidation_research"]["event_id"], event["event_id"])
        self.assertEqual(pack["transition_diagnostic"]["wake"]["liquidation_research"]["event_id"], event["event_id"])
        self.assertIsNone(event["formal_season"])
        self.assertEqual(pack["authority"]["external_action_authority"], "NONE")
        self.assertFalse(pack["authority"]["external_action_performed"])
        self.assertEqual(list(self.root.glob("**/outbox")), [])

    def test_restart_and_snapshot_clock_refresh_do_not_wake_again(self):
        from crt_radar.liquidation_aggregator import build_snapshot
        original = self.run_pack(self.candidate())["reanalysis_wake"]["liquidation_research"]
        self.raw.touch_session(self.session, heartbeat_ms=NOW_MS)
        updated = build_snapshot(self.raw, as_of_ms=NOW_MS)
        self.assertNotEqual(updated["snapshot_hash"], self.snapshot["snapshot_hash"])
        wake = self.run_pack(self.candidate(), snapshot=updated, at=NOW_MS + 1)["reanalysis_wake"]
        self.assertEqual(wake["state"], "NO_WAKE")
        self.assertEqual(wake["liquidation_research"]["event_id"], original["event_id"])
        self.assertEqual(wake["liquidation_research"]["first_qualified_at_ms"], NOW_MS)
        self.assertEqual(len(self.diagnostics), 1)

    def test_same_evidence_does_not_qualify_as_material_upgrade(self):
        self.run_pack(self.candidate())
        candidate = self.candidate()
        candidate.update(revision=2, upgrade_basis="Synthetic proposed upgrade")
        outcome = self.run_pack(candidate)["reanalysis_wake"]
        self.assertEqual(outcome["state"], "NO_WAKE")
        self.assertEqual(outcome["liquidation_research"]["reason"], "UPGRADE_HAS_NO_NEW_EXECUTION_EVIDENCE")

    def test_republished_execution_cannot_become_new_evidence_or_new_event(self):
        from copy import deepcopy
        from crt_radar.liquidation_aggregator import LiquidationStore, build_snapshot, normalize_force_order
        from crt_radar.reanalysis_wake import liquidation_evidence_identity
        original = self.run_pack(self.candidate())["reanalysis_wake"]["liquidation_research"]
        alternate = deepcopy(self.records[0])
        alternate["raw_payload"]["E"] += 1  # Publication/capture changes, same executed trade time.
        alternate["raw_payload"]["o"]["X"] = "EXPIRED"
        normalized = normalize_force_order(alternate["raw_payload"], received_ms=NOW_MS)
        self.assertEqual(liquidation_evidence_identity(normalized, self.candidate()["source_id"]),
                         self.candidate()["anchor_evidence_id"])
        replacement = LiquidationStore(self.root / "republication")
        sid = replacement.begin_session(opened_ms=NOW_MS - 2 * 86400_000)
        replacement.end_session(sid, closed_ms=NOW_MS)
        replacement.ingest_force_order(alternate["raw_payload"], received_ms=NOW_MS)
        snap = build_snapshot(replacement, as_of_ms=NOW_MS)
        candidate = self.candidate()
        candidate["event_records"] = [normalized.as_record()]
        pack = self.run_pack(candidate, snapshot=snap, at=NOW_MS + 1)
        self.assertEqual(pack["reanalysis_wake"]["state"], "NO_WAKE")
        self.assertEqual(pack["reanalysis_wake"]["liquidation_research"]["event_id"], original["event_id"])

    def test_material_revision_requires_new_visible_execution_and_explicit_basis(self):
        from crt_radar.liquidation_aggregator import build_snapshot
        first = self.run_pack(self.candidate())["reanalysis_wake"]["liquidation_research"]
        new_id = self.add_event("SELL", NOW_MS + 1000, NOW_MS + 2000)
        self.raw.touch_session(self.session, heartbeat_ms=NOW_MS + 2000)
        snap = build_snapshot(self.raw, as_of_ms=NOW_MS + 2000)
        candidate = self.candidate()
        candidate["supporting_evidence_ids"].append(new_id)
        candidate["revision"] = 2
        blocked = self.run_pack(candidate, snapshot=snap, at=NOW_MS + 3000)["reanalysis_wake"]
        self.assertEqual(blocked["liquidation_research"]["reason"], "UPGRADE_CLASSIFICATION_MISSING")
        candidate["upgrade_basis"] = "Synthetic later execution supports an explicit research revision"
        upgraded = self.run_pack(candidate, snapshot=snap, at=NOW_MS + 3000)["reanalysis_wake"]
        self.assertEqual(upgraded["state"], "REANALYSIS_REQUESTED")
        self.assertEqual(upgraded["liquidation_research"]["event_id"], first["event_id"])
        self.assertEqual(self.run_pack(candidate, snapshot=snap, at=NOW_MS + 3001)["reanalysis_wake"]["state"], "NO_WAKE")

    def test_opposite_direction_new_event_is_not_deduplicated(self):
        from crt_radar.liquidation_aggregator import build_snapshot
        first = self.run_pack(self.candidate())["reanalysis_wake"]["liquidation_research"]
        self.add_event("BUY", NOW_MS + 1000, NOW_MS + 2000)
        self.raw.touch_session(self.session, heartbeat_ms=NOW_MS + 2000)
        snap = build_snapshot(self.raw, as_of_ms=NOW_MS + 2000)
        second = self.run_pack(self.candidate(direction="SHORT", index=1), snapshot=snap,
                               at=NOW_MS + 3000)["reanalysis_wake"]
        self.assertEqual(second["state"], "REANALYSIS_REQUESTED")
        self.assertNotEqual(second["liquidation_research"]["event_id"], first["event_id"])

    def test_renaming_anchor_cannot_reuse_already_claimed_execution(self):
        from crt_radar.liquidation_aggregator import build_snapshot
        extra = self.add_event("SELL", NOW_MS - 1500, NOW_MS - 1000)
        self.snapshot = build_snapshot(self.raw, as_of_ms=NOW_MS - 1000)
        original = self.candidate()
        original["supporting_evidence_ids"].append(extra)
        first = self.run_pack(original)["reanalysis_wake"]
        self.assertEqual(first["state"], "REANALYSIS_REQUESTED")
        renamed = self.candidate(index=1)
        second = self.run_pack(renamed)["reanalysis_wake"]
        self.assertEqual(second["state"], "NO_WAKE")
        self.assertEqual(second["liquidation_research"]["reason"], "EXECUTION_ALREADY_CLAIMED")

    def test_aggregate_only_or_window_rolloff_cannot_create_event(self):
        from crt_radar.liquidation_aggregator import build_snapshot
        self.assertEqual(self.run_pack()["reanalysis_wake"]["state"], "NO_WAKE")
        self.run_pack(self.candidate())
        later = NOW_MS + 86400_000
        self.raw.touch_session(self.session, heartbeat_ms=later)
        snap = build_snapshot(self.raw, as_of_ms=later)
        pack = self.run_pack(self.candidate(), snapshot=snap, at=later)
        self.assertEqual(pack["reanalysis_wake"]["liquidation_research"]["state"], "BLOCKED")
        self.assertEqual(len(self.diagnostics), 1)

    def test_missing_baseline_and_invalid_source_clock_or_raw_proof_do_not_wake(self):
        from copy import deepcopy
        pack = self.run_pack(self.candidate(), db=self.root / "no-baseline.sqlite3")
        self.assertEqual(pack["reanalysis_wake"]["liquidation_research"]["reason"], "LIQUIDATION_HISTORY_BASELINE_MISSING")
        for modification in ("source", "clock", "raw", "stale"):
            with self.subTest(modification=modification):
                candidate = self.candidate()
                snap = deepcopy(self.snapshot)
                at = NOW_MS
                if modification == "source":
                    candidate["source_id"] = "UNVERIFIED_SOURCE"
                elif modification == "clock":
                    candidate["event_records"][0]["received_ms"] = NOW_MS + 1
                elif modification == "raw":
                    candidate["event_records"][0]["event_hash"] = "f" * 64
                else:
                    at += 121_000
                wake = self.run_pack(candidate, snapshot=snap, at=at)["reanalysis_wake"]
                self.assertNotEqual(wake["state"], "REANALYSIS_REQUESTED")
                self.assertEqual(wake["liquidation_research"]["state"], "BLOCKED")

    def test_independent_l4_research_survives_other_source_failure_without_capital_release(self):
        pack = self.run_pack(self.candidate(), fail_oi=True)
        self.assertEqual(pack["pack_state"], "BLOCKED")
        self.assertEqual(pack["reanalysis_wake"]["state"], "REANALYSIS_REQUESTED")
        self.assertEqual(pack["reanalysis_wake"]["liquidation_research"]["state"], "REANALYSIS_REQUESTED")
        self.assertIsNone(pack["analyst_output"]["capital_strategy"])
        self.assertEqual(pack["action_output"], "NONE")

    def test_unqualified_snapshot_and_mutated_frozen_rule_cannot_wake(self):
        from copy import deepcopy
        from crt_radar.liquidation_aggregator import canonical_json_bytes, sha256_hex
        snapshot = deepcopy(self.snapshot)
        snapshot.update(quality_state="BLOCKED", blocked_reasons=["SYNTHETIC_SOURCE_FAILURE"])
        snapshot.pop("snapshot_hash")
        snapshot["snapshot_hash"] = sha256_hex(canonical_json_bytes(snapshot))
        wake = self.run_pack(self.candidate(), snapshot=snapshot)["reanalysis_wake"]
        self.assertEqual(wake["state"], "NO_WAKE")
        self.assertEqual(wake["liquidation_research"]["state"], "BLOCKED")
        self.run_pack(self.candidate())
        candidate = self.candidate()
        candidate["candidate_rule_version"] = "RENAMED_RULE_IS_NOT_A_NEW_EVENT"
        wake = self.run_pack(candidate)["reanalysis_wake"]
        self.assertEqual(wake["state"], "NO_WAKE")
        self.assertEqual(wake["liquidation_research"]["reason"], "FROZEN_CANDIDATE_RULE_CONFLICT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
