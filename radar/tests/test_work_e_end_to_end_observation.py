"""Permanent A/B/D/C integration regression; synthetic inputs, NOT live acceptance.

Reuse source builders from Work C: IBKR capture -> evidence binding -> battle
map/readiness -> A research evaluator -> B posture -> C closure -> real operator
-> durable journal -> reanalysis handoff. Only the market transport is replaced.
The fixed analyst lines are test fixtures, never runtime-generated judgment.
"""
from copy import deepcopy
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from crt_radar.commander_plan_adapter import CommanderPlanBlocked, validate_commander_plan
from crt_radar.gpt_commander_plan_closure import (
    AUTHORITY, _hash, build_commander_source_bundle, build_candidate_commander_plan,
    seal_candidate_commander_plan, run_gpt_commander_observation,
)
from crt_radar.ibkr_live_market_data_intake import IbkrIntakeConfig
from crt_radar.ibkr_observation_journal import IbkrObservationJournal
from test_gpt_commander_plan_closure import MAIN, NOW, source_inputs, judgment_for, seal_field
from test_ibkr_commander_operator import FeedFactory, live_capture


class WorkEEndToEndObservationTests(unittest.TestCase):
    def setUp(self):
        self.bundle = build_commander_source_bundle(**source_inputs())
        self.judgment = judgment_for(self.bundle)

    def run_cycle(self, root, factory, *, bundle=None, judgment=None, now=NOW, main=MAIN):
        return run_gpt_commander_observation(
            self.judgment if judgment is None else judgment,
            source_bundle=self.bundle if bundle is None else bundle,
            current_main_sha=main, now=now,
            config=IbkrIntakeConfig(duration_seconds=5),
            ledger_path=root / "handoff.jsonl", dedupe_state_path=root / "state.json",
            observation_journal_path=root / "journal.sqlite", feed_factory=factory)

    def factory(self, asset="MSTR"):
        ms = int(NOW.timestamp() * 1000)
        return FeedFactory(live_capture(), [("LAST", asset, 125, ms),
                                           ("LAST", asset, 127, ms + 1000)])

    def test_complete_chain_lineage_seal_journal_and_reanalysis_for_both_assets(self):
        for asset in ("MSTR", "ASST"):
            with self.subTest(asset=asset), tempfile.TemporaryDirectory() as temp:
                judgment = judgment_for(self.bundle, asset)
                candidate = build_candidate_commander_plan(judgment,
                    source_bundle=self.bundle, current_main_sha=MAIN, now=NOW)
                plan = seal_candidate_commander_plan(candidate, judgment,
                    source_bundle=self.bundle, current_main_sha=MAIN, now=NOW)
                self.assertEqual(validate_commander_plan(plan, current_main_sha=MAIN, now=NOW), (True, []))
                self.assertEqual(plan["lines"], judgment["lines"])
                lineage = plan["closure_lineage"]
                pack = self.bundle["evidence_pack"]
                readiness = pack["premarket_market_data"]["battle_map"]["asset_fact_readiness"][asset]
                self.assertEqual(readiness["state"], "AVAILABLE")
                for field, expected in {
                    "source_bundle_hash": self.bundle["bundle_hash"],
                    "evidence_pack_hash": pack["evidence_pack_hash"],
                    "research_evaluation_hash": _hash(self.bundle["research_evaluation"]),
                    "posture_gate_hash": _hash(self.bundle["posture_gate"]),
                    "asset_readiness_hash": _hash(readiness),
                    "judgment_hash": _hash(judgment),
                }.items():
                    self.assertEqual(lineage[field], expected)
                root, factory = Path(temp), self.factory(asset)
                result = self.run_cycle(root, factory, judgment=judgment)
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(result["state"], "OBSERVATION_EVENTS_HANDOFF_READY")
                self.assertEqual(result["plan"]["plan_sha"], plan["plan_sha"])
                self.assertEqual(result["plan"]["source_main_sha"], MAIN)
                self.assertEqual(result["plan"]["valid_until"], plan["valid_until"])
                journal_result = result["observation_journal"]
                self.assertEqual(journal_result["state"], "DURABLE_REPLAY_READY")
                self.assertEqual(journal_result["appended_observation_count"], 2)
                with IbkrObservationJournal(root / "journal.sqlite", plan_sha=plan["plan_sha"], asset=asset) as journal:
                    journal.validate()
                    self.assertEqual(journal.head(), (2, journal_result["applied_hash"]))
                    records = journal.records_after(0)
                self.assertEqual(len(records), 2)
                for value in [result, journal_result, *records]:
                    for field, expected in AUTHORITY.items():
                        self.assertEqual(value[field], expected)
                self.assertTrue(result["new_events"])
                self.assertTrue(result["handoffs"])
                event_ids = {_hash(event) for event in result["new_events"]}
                for event in result["new_events"]:
                    self.assertEqual(event["event_purpose"], "WAKE_GPT_REANALYSIS_ONLY")
                for item in result["handoffs"]:
                    self.assertIn(item["commander_event_id"], event_ids)
                    handoff = item["handoff"]
                    self.assertEqual(handoff["state"], "GPT_HANDOFF_READY")
                    self.assertEqual(handoff["action_output"], "NONE")
                    self.assertFalse(handoff["transport_performed"])
                self.assertTrue((root / "handoff.jsonl").read_text(encoding="utf-8").strip())
                checkpoint = json.loads((root / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["journal_applied_hash"], journal_result["applied_hash"])

    def test_upstream_corruption_fails_before_transport_or_journal_creation(self):
        mutations = [
            lambda b: b.update(source_main_sha="8" * 40),
            lambda b: b["evidence_pack"].update(generated_at_ms=1),
            lambda b: b["posture_gate"].update(posture_candidate="SCOUT"),
            lambda b: b["research_evaluation"].update(state="UNKNOWN"),
            lambda b: b["evidence_pack"]["premarket_market_data"]["battle_map"]["asset_fact_readiness"]["MSTR"].update(state="BLOCKED"),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(stage=i), tempfile.TemporaryDirectory() as temp:
                bundle = deepcopy(self.bundle)
                mutate(bundle)
                if i == 4:
                    # Valid container seals must not hide forged Work D readiness.
                    seal_field(bundle["evidence_pack"], "evidence_pack_hash")
                    handoff = bundle["handoff"]
                    handoff["source_evidence_pack_hash"] = bundle["evidence_pack"]["evidence_pack_hash"]
                    handoff["handoff_hash"] = _hash({k: v for k, v in handoff.items()
                        if k not in ("handoff_hash", "append_status", "ledger_record_hash", "bridge_outbox")})
                # Reseal outer layer: inner lineage must still fail closed.
                seal_field(bundle, "bundle_hash")
                factory, root = Mock(), Path(temp) / "runtime"
                with self.assertRaises(CommanderPlanBlocked):
                    self.run_cycle(root, factory, bundle=bundle, judgment=judgment_for(bundle))
                factory.assert_not_called()
                self.assertFalse(root.exists())

    def test_missing_judgment_expiry_and_main_drift_never_arm(self):
        for kwargs in ({"judgment": {}}, {"now": NOW + timedelta(hours=1)},
                       {"main": "9" * 40}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as temp:
                root, factory = Path(temp) / "runtime", Mock()
                with self.assertRaises(CommanderPlanBlocked):
                    self.run_cycle(root, factory, **kwargs)
                factory.assert_not_called()
                self.assertFalse(root.exists())

    def test_journal_corruption_blocks_next_cycle_before_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.run_cycle(root, self.factory())
            with closing(sqlite3.connect(root / "journal.sqlite")) as db:
                db.execute("UPDATE observations SET price = price + 1 WHERE sequence = 1")
                db.commit()
            factory = Mock()
            with self.assertRaises(ValueError):
                self.run_cycle(root, factory)
            factory.assert_not_called()

    def test_authority_override_at_closure_never_reaches_transport(self):
        for field in AUTHORITY:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                judgment = deepcopy(self.judgment)
                judgment["governance"][field] = "GRANTED"
                root, factory = Path(temp) / "runtime", Mock()
                with self.assertRaises(CommanderPlanBlocked):
                    self.run_cycle(root, factory, judgment=judgment)
                factory.assert_not_called()
                self.assertFalse(root.exists())
