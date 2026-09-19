from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from crt_radar.commander_plan_adapter import CommanderPlanBlocked, validate_commander_plan
from crt_radar.deployment_posture_research_gate import translate_research_state_to_posture_constraints
from crt_radar.gpt_commander_plan_closure import (
    AUTHORITY, JUDGMENT_SCHEMA, _hash, build_commander_source_bundle,
    build_candidate_commander_plan, validate_candidate_commander_plan,
    seal_candidate_commander_plan, run_gpt_commander_observation,
)
from crt_radar.gpt_handoff import run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.ibkr_live_market_data_intake import (
    build_ibkr_crt_outputs, build_ibkr_equity_live_snapshot,
    load_ibkr_source_registry, SOURCE_ID, IbkrIntakeConfig,
)
from crt_radar.premarket_equity_live_snapshot import build_equity_source_binding
from test_asset_fact_closure import envelope
from test_deployment_posture_research_gate import evaluation
from test_gpt_handoff import pack as wake_pack
from test_ibkr_live_market_data_intake import (
    _capture, _premarket_ms, REGISTRY_PATH, OVERLAY_PATH, CONTRACT_PATH,
)
from test_ibkr_commander_operator import FeedFactory, live_capture
from test_premarket_evidence_binding import _fact, _overlay

MAIN = "7" * 40
NOW = datetime.fromtimestamp((_premarket_ms() + 1000) / 1000, tz=timezone.utc)


def seal_field(value, field):
    value.pop(field, None)
    value[field] = _hash(value)


def source_inputs():
    registry = load_ibkr_source_registry(REGISTRY_PATH, OVERLAY_PATH)
    snapshot = build_ibkr_equity_live_snapshot(_capture(),
        source_binding=build_equity_source_binding(registry, source_id=SOURCE_ID),
        config=IbkrIntakeConfig(), retrieved_at_ms=_premarket_ms() + 1000)
    items = []
    for asset, issuer in [("MSTR", "CIK-0001050446"), ("ASST", "CIK-0001920406")]:
        items.extend([
            _fact(asset + "btc", issuer, asset, "BTC_HOLDINGS", 100, 1, "hash"),
            _fact(asset + "shares", issuer, asset, "DILUTED_SHARES", 10, 1, "hash"),
        ])
    pack = wake_pack(evidence_hash="", requested=True)
    pack.pop("evidence_pack_hash")
    pack.update(_overlay(items))
    pack.update(schema_version="CRT_EVIDENCE_PACK_V0.2", action_output="NONE",
                pack_state="PARTIAL_FOR_ANALYST", generated_at_ms=_premarket_ms())
    pack["authority"].update(production="NOT_APPROVED", capital_decision_authority="USER_ONLY")
    pack = build_ibkr_crt_outputs(snapshot, registry=registry,
        battle_map_contract=json.loads(CONTRACT_PATH.read_text(encoding="utf-8")),
        evidence_pack=pack, mnav_results={a: envelope(a) for a in ("MSTR", "ASST")})["evidence_pack"]
    with tempfile.TemporaryDirectory() as temp:
        handoff = run_gpt_handoff_gate(pack, build_plain_language_notice(pack),
                                       ledger_path=Path(temp) / "source.jsonl")
    research = evaluation()
    return dict(source_main_sha=MAIN, evidence_pack=pack, handoff=handoff,
                research_evaluation=research,
                posture_gate=translate_research_state_to_posture_constraints(research))


def judgment_for(bundle, asset="MSTR"):
    return dict(schema_version=JUDGMENT_SCHEMA, state="READY_FOR_VALIDATION",
        judgment_id="GPT-observation-001", asset=asset,
        generated_at=NOW.isoformat(), valid_until=(NOW + timedelta(hours=1)).isoformat(),
        source_main_sha=MAIN, source_bundle_hash=bundle["bundle_hash"],
        posture_candidate=bundle["posture_gate"]["posture_candidate"],
        governance=deepcopy(AUTHORITY), lines=[
            dict(line_id=kind.lower(), line_type=kind, price=price, direction=direction,
                 btc_condition="Reassess BTC structure at the observation",
                 confirmation_condition="GPT must review acceptance and contradictions",
                 rationale="Analyst-authored observation level; no trade trigger")
            for kind, price, direction in [("ATTACK", 126, "UP"),
                ("FIRST_DEFENSE", 124, "DOWN"), ("INVALIDATION", 120, "DOWN"),
                ("HARVEST", 130, "UP")]])


class GptCommanderPlanClosureTests(unittest.TestCase):
    def setUp(self):
        self.inputs = source_inputs()
        self.bundle = build_commander_source_bundle(**self.inputs)
        self.judgment = judgment_for(self.bundle)

    def candidate(self, judgment=None, bundle=None, now=NOW):
        return build_candidate_commander_plan(
            self.judgment if judgment is None else judgment,
            source_bundle=self.bundle if bundle is None else bundle,
            current_main_sha=MAIN, now=now)

    def assert_no_arm(self, judgment=None, bundle=None, now=NOW, main=MAIN):
        factory = Mock()
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "runtime"
            with self.assertRaises(CommanderPlanBlocked):
                run_gpt_commander_observation(
                    self.judgment if judgment is None else judgment,
                    source_bundle=self.bundle if bundle is None else bundle,
                    current_main_sha=main, now=now, config=IbkrIntakeConfig(),
                    ledger_path=runtime / "ledger.jsonl", dedupe_state_path=runtime / "state.json",
                    feed_factory=factory)
            factory.assert_not_called()
            self.assertFalse(runtime.exists())

    def test_candidate_validate_seal_preserves_lines_and_research_only_scope(self):
        candidate = self.candidate()
        self.assertNotIn("plan_sha", candidate)
        self.assertEqual(candidate["lines"], self.judgment["lines"])
        self.assertEqual(candidate["closure_lineage"]["final_eligibility"], "NOT_DETERMINED")
        self.assertEqual(candidate["closure_lineage"]["eligibility_level"], "RESEARCH_POSTURE_CANDIDATE")
        sealed = seal_candidate_commander_plan(candidate, self.judgment,
            source_bundle=self.bundle, current_main_sha=MAIN, now=NOW)
        self.assertEqual(validate_commander_plan(sealed, current_main_sha=MAIN, now=NOW), (True, []))
        self.assertEqual(sealed["governance"], {k: AUTHORITY[k] for k in (
            "action_output", "machine_execution", "external_action_authority", "capital_decision_authority")})

    def test_real_operator_reuses_existing_observation_and_handoff(self):
        ms = int(NOW.timestamp() * 1000)
        factory = FeedFactory(live_capture(), [("LAST", "MSTR", 125, ms),
                                              ("LAST", "MSTR", 127, ms + 1000)])
        with tempfile.TemporaryDirectory() as temp:
            result = run_gpt_commander_observation(self.judgment, source_bundle=self.bundle,
                current_main_sha=MAIN, now=NOW, config=IbkrIntakeConfig(),
                ledger_path=Path(temp) / "ledger.jsonl", dedupe_state_path=Path(temp) / "state.json",
                feed_factory=factory)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(result["state"], "OBSERVATION_EVENTS_HANDOFF_READY")
        self.assertTrue(result["handoffs"])
        for event in result["new_events"]:
            self.assertEqual(event["event_purpose"], "WAKE_GPT_REANALYSIS_ONLY")
            self.assertEqual(event["action_output"], "NONE")
            self.assertEqual(event["machine_execution"], "FORBIDDEN")
        for key, expected in AUTHORITY.items():
            self.assertEqual(result[key], expected)

    def test_all_required_judgment_fields_and_unknown_extensions_fail_closed(self):
        for key in self.judgment:
            with self.subTest(key=key):
                bad = deepcopy(self.judgment)
                del bad[key]
                self.assert_no_arm(judgment=bad)
        for key, value in [("schema_version", "UNKNOWN"), ("state", "BLOCKED"),
            ("state", "UNKNOWN"), ("extra", True), ("formal_season", "SPRING"),
            ("asset", "BTC"), ("posture_candidate", "SCOUT_ELIGIBLE")]:
            with self.subTest(key=key, value=value):
                self.assert_no_arm(judgment={**self.judgment, key: value})

    def test_line_shape_prices_and_context_fail_closed(self):
        for key, value in [("price", float("nan")), ("price", True), ("price", -1),
            ("line_type", "UNKNOWN"), ("direction", "UNKNOWN"), ("rationale", "BLOCKED"),
            ("btc_condition", ""), ("confirmation_condition", None), ("shares", 1)]:
            with self.subTest(key=key, value=value):
                bad = deepcopy(self.judgment)
                bad["lines"][0][key] = value
                self.assert_no_arm(judgment=bad)
        bad = deepcopy(self.judgment)
        bad["lines"].pop()
        self.assert_no_arm(judgment=bad)

    def test_authority_overrides_never_arm(self):
        for key in AUTHORITY:
            with self.subTest(key=key):
                bad = deepcopy(self.judgment)
                bad["governance"][key] = "GRANTED"
                self.assert_no_arm(judgment=bad)
        bad = deepcopy(self.bundle)
        bad["evidence_pack"]["authority"]["external_action_performed"] = 0
        seal_field(bad["evidence_pack"], "evidence_pack_hash")
        seal_field(bad, "bundle_hash")
        self.assert_no_arm(bundle=bad)

    def test_expired_future_naive_and_evidence_time_windows_fail_closed(self):
        self.assert_no_arm(now=NOW + timedelta(hours=1))
        self.assert_no_arm(now=NOW - timedelta(seconds=1))
        self.assert_no_arm(now=NOW.replace(tzinfo=None))
        for key, value in [("generated_at", "unknown"), ("valid_until", NOW.isoformat()),
                           ("generated_at", (NOW - timedelta(days=1)).isoformat())]:
            self.assert_no_arm(judgment={**self.judgment, key: value})

    def test_source_main_and_evidence_hash_mismatches_fail_closed(self):
        self.assert_no_arm(main="8" * 40)
        for field in ("source_main_sha", "source_bundle_hash"):
            self.assert_no_arm(judgment={**self.judgment, field: "0" * 64})
        bad = deepcopy(self.bundle)
        bad["evidence_pack"]["generated_at_ms"] += 1
        self.assert_no_arm(bundle=bad)
        seal_field(bad, "bundle_hash")
        self.assert_no_arm(bundle=bad)

    def test_work_b_recomputed_not_trusted_or_promoted(self):
        for field, value in [("final_eligibility", "REINFORCEMENT_ELIGIBLE"),
                             ("state", "UNKNOWN"), ("posture_candidate", "SCOUT")]:
            bad = deepcopy(self.inputs)
            bad["posture_gate"][field] = value
            with self.assertRaises(CommanderPlanBlocked):
                build_commander_source_bundle(**bad)
        for count in (0, 1, 2, 3, 5):
            inputs = deepcopy(self.inputs)
            inputs["research_evaluation"] = evaluation(count)
            inputs["posture_gate"] = translate_research_state_to_posture_constraints(inputs["research_evaluation"])
            bundle = build_commander_source_bundle(**inputs)
            judgment = judgment_for(bundle)
            if count == 0:
                self.assert_no_arm(judgment=judgment, bundle=bundle)
            else:
                candidate = self.candidate(judgment, bundle)
                self.assertEqual(candidate["closure_lineage"]["posture_effect"], inputs["posture_gate"]["posture_effect"])
                self.assertEqual(candidate["closure_lineage"]["final_eligibility"], "NOT_DETERMINED")

    def test_every_action_critical_fact_blocks_even_if_readiness_is_forged(self):
        fields = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["required_facts"]["MSTR"]
        for field in fields:
            with self.subTest(field=field):
                bad = deepcopy(self.bundle)
                fact = bad["evidence_pack"]["premarket_market_data"]["battle_map"]["asset_facts"]["MSTR"][field]
                fact["state"] = "BLOCKED"
                self.assert_no_arm(bundle=bad)
                # Re-hash all upstream envelopes: raw evidence reconciliation must still reject.
                pack = bad["evidence_pack"]
                seal_field(pack, "evidence_pack_hash")
                handoff = bad["handoff"]
                handoff.pop("append_status", None)
                handoff.pop("ledger_record_hash", None)
                handoff["source_evidence_pack_hash"] = pack["evidence_pack_hash"]
                seal_field(handoff, "handoff_hash")
                seal_field(bad, "bundle_hash")
                self.assert_no_arm(judgment=judgment_for(bad), bundle=bad)

    def test_candidate_mutation_cannot_be_sealed(self):
        for field, value in [("plan_id", "other"), ("extra", "override"),
                             ("governance", {}), ("lines", [])]:
            candidate = {**self.candidate(), field: value}
            valid, blockers = validate_candidate_commander_plan(candidate, self.judgment,
                source_bundle=self.bundle, current_main_sha=MAIN, now=NOW)
            self.assertFalse(valid)
            self.assertTrue(blockers)
            with self.assertRaises(CommanderPlanBlocked):
                seal_candidate_commander_plan(candidate, self.judgment,
                    source_bundle=self.bundle, current_main_sha=MAIN, now=NOW)

    def test_asst_uses_own_ready_facts_and_supporting_gaps_remain_visible(self):
        self.assertEqual(self.candidate(judgment_for(self.bundle, "ASST"))["asset"], "ASST")
        battle = self.bundle["evidence_pack"]["premarket_market_data"]["battle_map"]
        self.assertEqual(battle["supporting_fact_readiness"]["ASST"]["state"], "BLOCKED")
        self.assertEqual(battle["asset_fact_readiness"]["ASST"]["state"], "AVAILABLE")

    def test_input_snapshots_are_detached(self):
        before = deepcopy(self.bundle)
        candidate = self.candidate()
        candidate["lines"][0]["price"] = 1
        self.assertEqual(self.bundle, before)
        self.assertEqual(self.judgment["lines"][0]["price"], 126)

    def test_handoff_schema_hash_authority_and_pack_lineage_are_checked(self):
        for field, value in [("schema_version", "UNKNOWN"), ("state", "BLOCKED"),
            ("source_evidence_pack_hash", "b" * 64), ("handoff_hash", "c" * 64),
            ("external_action_authority", "GRANTED")]:
            with self.subTest(field=field):
                inputs = deepcopy(self.inputs)
                inputs["handoff"][field] = value
                with self.assertRaises(CommanderPlanBlocked):
                    build_commander_source_bundle(**inputs)
        inputs = deepcopy(self.inputs)
        handoff = inputs["handoff"]
        for key in ("append_status", "ledger_record_hash", "external_action_authority"):
            handoff.pop(key)
        seal_field(handoff, "handoff_hash")
        with self.assertRaises(CommanderPlanBlocked):
            build_commander_source_bundle(**inputs)

    def test_unknown_bundle_evidence_and_research_never_arm(self):
        for field, value in [("schema_version", "UNKNOWN"), ("extra", {}),
                             ("research_evaluation", None), ("posture_gate", []),
                             ("evidence_pack", None), ("handoff", []), ("governance", {})]:
            self.assert_no_arm(bundle={**self.bundle, field: value})
        for field, value in [("pack_state", "BLOCKED"), ("pack_state", "UNKNOWN"),
                             ("schema_version", "UNKNOWN"), ("data_health", {})]:
            inputs = deepcopy(self.inputs)
            inputs["evidence_pack"][field] = value
            seal_field(inputs["evidence_pack"], "evidence_pack_hash")
            with self.assertRaises(CommanderPlanBlocked):
                build_commander_source_bundle(**inputs)

    def test_expiry_and_current_main_rechecked_when_sealing_candidate(self):
        candidate = self.candidate()
        for current, now in [(MAIN, NOW + timedelta(hours=1)), ("9" * 40, NOW)]:
            with self.assertRaises(CommanderPlanBlocked):
                seal_candidate_commander_plan(candidate, self.judgment,
                    source_bundle=self.bundle, current_main_sha=current, now=now)

    def test_candidate_nan_cannot_escape_fail_closed_validation(self):
        candidate = self.candidate()
        candidate["lines"][0]["price"] = float("nan")
        self.assertFalse(validate_candidate_commander_plan(candidate, self.judgment,
            source_bundle=self.bundle, current_main_sha=MAIN, now=NOW)[0])

    def test_live_price_freshness_rechecked_at_arm_using_existing_source_policy(self):
        self.assert_no_arm(now=NOW + timedelta(minutes=3))

    def test_real_pack_state_field_is_required_not_an_invented_state_alias(self):
        inputs = deepcopy(self.inputs)
        pack = inputs["evidence_pack"]
        pack["state"] = pack.pop("pack_state")
        seal_field(pack, "evidence_pack_hash")
        with self.assertRaises(CommanderPlanBlocked):
            build_commander_source_bundle(**inputs)
