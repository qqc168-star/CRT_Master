"""Synthetic, isolated P2 pair tests; not a real-market prospective acceptance."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import test_daily_evidence_runner as existing
from crt_radar import daily_evidence_runner as runner
from crt_radar.observation_store import Observation, ObservationStore
from crt_radar.source_gate_runner import FetchResult


class LiquidationShadowPairTests(unittest.TestCase):
    """Preserve original Gate/Wake fixtures rather than inventing market rules."""

    def setUp(self):
        self.fixture = existing.LiquidationResearchWakeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.registry = self.fixture.fixture.registry
        self.cutoff = existing.NOW_MS
        self.store = ObservationStore(self.fixture.db)
        self.addCleanup(self.store.close)
        self.clock = patch.object(runner, "_shadow_now", return_value=self.cutoff - 3000)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.study = runner.start_liquidation_shadow(self.store, self.registry, mode="SYNTHETIC_TEST")
        self.now.return_value = self.cutoff
        self.baseline = self.fixture.run_pack(snapshot=self.fixture.snapshot, at=self.cutoff)
        self.candidate = self.fixture.candidate()
        self.captures = {}
        overrides = copy.deepcopy(self.fixture.fixture.overrides)
        aggregate = self.registry.by_input_family("LIQUIDATION_AGGREGATES")
        overrides[aggregate.source_id] = FetchResult(aggregate.source_id, "OK", payload=self.fixture.snapshot)
        for source_id, fetched in overrides.items():
            spec = self.registry.with_l6_candidate_sources().get(source_id)
            raw = fetched.payload if isinstance(fetched.payload, str) else json.dumps(fetched.payload, sort_keys=True)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            request = ("READ_LOCAL_PUBLIC_L4_SNAPSHOT:" + digest if source_id == aggregate.source_id
                       else "COMPOSE_REGISTERED_ENDPOINTS:" + runner._shadow_hash(spec.raw["endpoints"])
                       if spec.raw.get("endpoints") else "GET " + spec.endpoint)
            self.captures[source_id] = dict(raw_utf8=raw, sha256=digest,
                encoding="TEXT" if isinstance(fetched.payload, str) else "JSON", fetch=fetched,
                first_seen_at_ms=self.cutoff - 500, retrieved_at_ms=self.cutoff - 400,
                verified_at_ms=self.cutoff - 300, available_at_ms=self.cutoff - 600,
                request_identity=request, source_authority_hash=self.registry.with_l6_candidate_sources().hash,
                evidence_class="SYNTHETIC_FIXTURE")

    def capture(self, **changes):
        values = dict(baseline_pack=self.baseline, captures=self.captures, cutoff_ms=self.cutoff,
                      candidate=self.candidate, liquidation_snapshot=self.fixture.snapshot)
        values.update(changes)
        return runner.capture_liquidation_shadow(self.store, self.registry, **values)

    def judgments(self, inputs):
        shared = inputs["common"]["evidence_pack"]["evidence_pack_hash"]
        output = {}
        arms = ("A", "B") if inputs["B"]["state"] == "AVAILABLE_FOR_RESEARCH" else ("A",)
        for arm in arms:
            output[arm] = dict(input_hash=inputs[arm]["input_hash"], cutoff_ms=inputs["cutoff_ms"],
                formed_at_ms=self.cutoff + 1000, analyst_provenance="SYNTHETIC_ANALYST:" + arm,
                research_hypothesis="Forced deleveraging may explain a temporary move; sustained control remains unconfirmed",
                competing_hypotheses=["Transient forced deleveraging", "Sustained spot demand"],
                supporting_evidence_ids=[shared], strongest_counterevidence={
                    "statement": "Same-venue source observations do not prove causal independence",
                    "evidence_ids": [shared]}, capital_posture_research={"state": "BLOCKED",
                    "btc_capital_question": "Would more BTC purchasing power justify additional issuer risk?",
                    "conditional_direction": "WAIT pending independent confirmation and qualified capital",
                    "limitations": "No executable quantity, model, notification, or trading authority"},
                invalidation_conditions=["Frozen structure fails without recovery"],
                next_trigger_conditions=["A later independently visible research observation"],
                difference_reason="No demonstrated information advantage" if arm == "A"
                                  else "Review only the added liquidation timing; Q1 still pending")
        return output

    def freeze(self, inputs):
        self.now.return_value = self.cutoff + 1000
        return runner.freeze_liquidation_shadow_judgments(self.store, inputs["pair_id"], self.judgments(inputs))

    def rehash(self, pack):
        pack["evidence_pack_hash"] = runner._shadow_hash({k: v for k, v in pack.items() if k != "evidence_pack_hash"})
        return pack

    def new_study(self, *, mode, start_ms=None):
        # Copy only already recorded synthetic observations. Rebuilding an earlier
        # snapshot from a later heartbeat would fabricate historical coverage.
        rows = [Observation(**{key: row[key] for key in Observation.__annotations__})
                for row in self.store.conn.execute("SELECT * FROM observations").fetchall()]
        self.store.close()
        db = self.fixture.root / ("new-study-" + mode + ".sqlite3")
        self.store = ObservationStore(db)
        self.addCleanup(self.store.close)
        self.store.record(rows)
        self.now.return_value = self.cutoff - 3000 if start_ms is None else start_ms
        study = runner.start_liquidation_shadow(self.store, self.registry, mode=mode)
        self.now.return_value = self.cutoff
        self.baseline = self.fixture.run_pack(snapshot=self.fixture.snapshot, at=self.cutoff, db=db)
        return study

    def test_shared_input_and_additive_wake_are_immutable_research_only(self):
        with patch.object(runner, "run_gpt_handoff_gate", side_effect=AssertionError("external handoff")):
            inputs = self.capture()
            frozen = self.freeze(inputs)
        self.assertEqual(inputs["sample_state"], "AWAITING_JUDGMENTS")
        self.assertEqual(inputs["A"]["input_hash"], inputs["common_hash"])
        self.assertNotIn("liquidation_research", inputs["common"]["evidence_pack"].get("reanalysis_wake", {}))
        self.assertTrue(inputs["wake_comparison"]["B_requested"])
        self.assertEqual(frozen["sample_state"], "SYNTHETIC_PAIR_ONLY")
        self.assertIsNone(frozen["formal_season"])
        self.assertEqual(frozen["production"], "NOT_APPROVED")
        self.assertEqual(frozen["external_action_authority"], "NONE")
        self.assertEqual(frozen["capital_decision_authority"], "USER_ONLY")
        self.assertEqual(frozen["machine_execution"], "FORBIDDEN")
        self.assertEqual(frozen["reasoning_state"], "NOT_YET_PROVEN")
        self.assertEqual(list(self.fixture.root.glob("**/outbox")), [])
        self.assertEqual(list(self.fixture.root.glob("**/notifications")), [])

    def test_no_candidate_is_not_run_without_frozen_pair(self):
        self.assertEqual(self.capture(candidate=None)["state"], "NOT_RUN")
        self.assertIsNone(self.store.latest_research_event("LIQUIDATION_SHADOW_INPUTS"))

    def test_same_candidate_and_inputs_are_idempotent(self):
        first = self.capture()
        self.assertEqual(self.capture(), first)
        frozen = self.freeze(first)
        self.assertEqual(runner.freeze_liquidation_shadow_judgments(
            self.store, first["pair_id"], self.judgments(first)), frozen)

    def test_changed_frozen_input_is_rejected(self):
        original = self.capture()
        changed = copy.deepcopy(self.candidate)
        changed["classification_basis"] = "A rewritten retrospective interpretation"
        with self.assertRaisesRegex(ValueError, "SHADOW_FROZEN_INPUT_CONFLICT"):
            self.capture(candidate=changed)
        self.assertEqual(self.store.research_event(original["pair_id"], kind="LIQUIDATION_SHADOW_INPUTS"), original)

    def test_changed_frozen_judgment_is_rejected(self):
        inputs = self.capture()
        frozen = self.freeze(inputs)
        changed = self.judgments(inputs)
        changed["B"]["difference_reason"] = "Rewritten after seeing the outcome"
        with self.assertRaisesRegex(ValueError, "SHADOW_FROZEN_JUDGMENT_CONFLICT"):
            runner.freeze_liquidation_shadow_judgments(self.store, inputs["pair_id"], changed)
        self.assertEqual(self.store.research_event(inputs["pair_id"] + ":judgments",
                                                   kind="LIQUIDATION_SHADOW_JUDGMENTS"), frozen)

    def test_mismatched_shared_cutoff_is_rejected(self):
        pack = copy.deepcopy(self.baseline)
        pack["generated_at_ms"] -= 1
        with self.assertRaisesRegex(ValueError, "SHADOW_BASELINE_SOURCE_OR_CLOCK_MISMATCH"):
            self.capture(baseline_pack=self.rehash(pack))

    def test_changed_original_bytes_are_rejected(self):
        captures = copy.deepcopy(self.captures)
        captures[self.fixture.fixture.oi.source_id]["raw_utf8"] += " "
        with self.assertRaisesRegex(ValueError, "SHADOW_ORIGINAL_BYTES_MISMATCH"):
            self.capture(captures=captures)

    def test_unarchived_payload_is_rejected(self):
        captures = copy.deepcopy(self.captures)
        captures[self.fixture.fixture.oi.source_id]["fetch"].payload["openInterest"] = "999999"
        with self.assertRaisesRegex(ValueError, "SHADOW_PAYLOAD_MISMATCH"):
            self.capture(captures=captures)

    def test_future_receipt_or_verification_cannot_leak_to_shared_inputs(self):
        source = self.fixture.fixture.oi.source_id
        for field in ("first_seen_at_ms", "retrieved_at_ms", "available_at_ms", "verified_at_ms"):
            with self.subTest(field=field):
                captures = copy.deepcopy(self.captures)
                captures[source][field] = self.cutoff + 1
                with self.assertRaises(ValueError):
                    self.capture(captures=captures)
        self.assertIsNone(self.store.latest_research_event("LIQUIDATION_SHADOW_INPUTS"))

    def test_future_market_timestamp_cannot_use_source_gate_skew_to_enter_pair(self):
        source = self.fixture.fixture.oi.source_id
        self.fixture.fixture.overrides[source].payload["time"] = self.cutoff + 1
        pack = self.fixture.run_pack(snapshot=self.fixture.snapshot, at=self.cutoff)
        captures = copy.deepcopy(self.captures)
        captures[source]["fetch"] = copy.deepcopy(self.fixture.fixture.overrides[source])
        captures[source]["raw_utf8"] = json.dumps(captures[source]["fetch"].payload, sort_keys=True)
        captures[source]["sha256"] = hashlib.sha256(captures[source]["raw_utf8"].encode()).hexdigest()
        with self.assertRaises(ValueError):
            self.capture(baseline_pack=pack, captures=captures)

    def test_registry_and_request_provenance_cannot_be_self_assigned(self):
        source = self.fixture.fixture.oi.source_id
        for field, value in (("source_authority_hash", "f" * 64),
                             ("request_identity", "GET https://unregistered.invalid/data")):
            with self.subTest(field=field):
                captures = copy.deepcopy(self.captures)
                captures[source][field] = value
                with self.assertRaises(ValueError):
                    self.capture(captures=captures)

    def test_missing_or_malformed_capture_metadata_cannot_leave_partial_inputs(self):
        source = self.fixture.fixture.oi.source_id
        cases = [(key, None, True) for key in ("fetch", "raw_utf8", "verified_at_ms", "request_identity")]
        cases += [("encoding", "UNREGISTERED_FORMAT", False), ("fetch", {}, False),
                  ("raw_utf8", b"not a UTF-8 text capture", False), ("verified_at_ms", True, False)]
        for key, value, remove in cases:
            with self.subTest(key=key, value=value, remove=remove):
                captures = copy.deepcopy(self.captures)
                if remove:
                    captures[source].pop(key)
                else:
                    captures[source][key] = value
                with self.assertRaises((ValueError, TypeError)):
                    self.capture(captures=captures)
                self.assertIsNone(self.store.latest_research_event("LIQUIDATION_SHADOW_INPUTS"))

    def test_fetch_source_or_status_cannot_differ_from_baseline(self):
        source = self.fixture.fixture.oi.source_id
        for field, value in (("source_id", "UNREGISTERED_SOURCE"), ("status", "ERROR")):
            with self.subTest(field=field):
                captures = copy.deepcopy(self.captures)
                setattr(captures[source]["fetch"], field, value)
                with self.assertRaises(ValueError):
                    self.capture(captures=captures)

    def test_unrelated_source_failure_does_not_erase_independent_L4_research(self):
        source = self.fixture.fixture.oi.source_id
        self.fixture.fixture.overrides[source].status = "ERROR"
        self.fixture.fixture.overrides[source].error = "SYNTHETIC_UNAVAILABLE"
        pack = self.fixture.run_pack(snapshot=self.fixture.snapshot, at=self.cutoff)
        captures = copy.deepcopy(self.captures)
        captures[source]["fetch"] = copy.deepcopy(self.fixture.fixture.overrides[source])
        inputs = self.capture(baseline_pack=pack, captures=captures)
        self.assertEqual(inputs["B"]["state"], "AVAILABLE_FOR_RESEARCH")
        evidence = inputs["common"]["source_gate"]["evidence"]
        self.assertTrue(any(row["input_family"] == "OPEN_INTEREST" and
                            row["quality_state"] == "TRANSPORT_ERROR" for row in evidence))
        self.assertTrue(any(row["input_family"] == "LIQUIDATION_AGGREGATES" and
                            row["quality_state"].startswith("VALID") for row in evidence))
        self.assertEqual(inputs["external_action_authority"], "NONE")

    def test_atomic_related_research_rollback_and_duplicate_idempotency(self):
        from crt_radar.observation_store import ObservationRevisionConflict
        self.store.record_research_event("synthetic-existing", "SYNTHETIC", {"value": 1})
        with self.assertRaisesRegex(ObservationRevisionConflict, "FROZEN_RESEARCH_EVENT_CONFLICT"):
            self.store.record_research_events([
                ("synthetic-new", "SYNTHETIC", {"value": 2}),
                ("synthetic-existing", "SYNTHETIC", {"value": 3})])
        self.assertIsNone(self.store.research_event("synthetic-new", kind="SYNTHETIC"))
        self.assertEqual(self.store.research_event("synthetic-existing", kind="SYNTHETIC"), {"value": 1})
        repeated = [("synthetic-new", "SYNTHETIC", {"value": 2})] * 2
        self.assertEqual(self.store.record_research_events(repeated), 1)
        self.assertEqual(self.store.record_research_events(repeated), 0)

    def test_prospective_mode_requires_sealed_unchanged_code_and_current_capture_class(self):
        version = runner._shadow_code_version()
        version["working_tree_dirty"] = False
        with patch.object(runner, "_shadow_code_version", return_value=version) as code:
            self.new_study(mode="PROSPECTIVE")
            with self.assertRaisesRegex(ValueError, "SHADOW_EVIDENCE_CLASS_MISMATCH"):
                self.capture()  # Explicit synthetic captures never become real by mode alone.
            for value in self.captures.values():
                value["evidence_class"] = "CURRENT_FIRST_SEEN_CAPTURE"
            changed = copy.deepcopy(version)
            changed["module_sha256"]["daily_evidence_runner"] = "f" * 64
            code.return_value = changed
            with self.assertRaisesRegex(ValueError, "SHADOW_STUDY_CODE_CHANGED"):
                self.capture()
            code.return_value = {**version, "working_tree_dirty": True}
            with self.assertRaisesRegex(ValueError, "SHADOW_CODE_NOT_SEALED"):
                self.capture()
            code.return_value = version
            inputs = self.capture()
            self.assertEqual(inputs["B"]["state"], "AVAILABLE_FOR_RESEARCH", inputs["B"])
            self.assertEqual(inputs["analysis_execution"], {"A": "NOT_RUN", "B": "NOT_RUN"})
            self.now.return_value = self.cutoff + 1000
            frozen = runner.freeze_liquidation_shadow_judgments(self.store, inputs["pair_id"], self.judgments(inputs))
            self.assertEqual(frozen["sample_state"], "PROSPECTIVE_PAIR_FROZEN")
            # Patched version/clocks and synthetic sources exercise a code path, not real acceptance.
            self.assertEqual(frozen["judgment_quality"], "ANALYST_DECLARED_NOT_MACHINE_PROVEN")

    def test_expired_or_predating_study_cutoff_cannot_claim_prospective_capture(self):
        self.now.return_value = self.cutoff + 121_000
        with self.assertRaisesRegex(ValueError, "SHADOW_HISTORICAL_REPLAY_FORBIDDEN"):
            self.capture()
        self.now.return_value = self.cutoff
        with self.assertRaisesRegex(ValueError, "SHADOW_CUTOFF_INVALID"):
            self.capture(cutoff_ms=self.study["started_at_ms"] - 1)

    def test_dirty_tree_cannot_enroll_actual_prospective_study(self):
        version = runner._shadow_code_version()
        version["working_tree_dirty"] = True
        with patch.object(runner, "_shadow_code_version", return_value=version):
            with self.assertRaisesRegex(ValueError, "SHADOW_CODE_NOT_SEALED"):
                self.new_study(mode="PROSPECTIVE")

    def test_blocked_candidate_preserves_baseline_and_allows_only_A(self):
        invalid = copy.deepcopy(self.candidate)
        invalid["source_id"] = "UNREGISTERED_SOURCE"
        inputs = self.capture(candidate=invalid)
        self.assertEqual(inputs["sample_state"], "B_BLOCKED_A_RETAINED")
        self.assertEqual(inputs["A"]["state"], "AVAILABLE_FOR_RESEARCH")
        self.assertEqual(inputs["B"]["state"], "BLOCKED")
        frozen = self.freeze(inputs)
        self.assertFalse(frozen["paired"])
        self.assertEqual(set(frozen["judgments"]), {"A"})

    def test_invalid_liquidation_source_cannot_gain_B_research_qualification(self):
        from crt_radar.liquidation_aggregator import canonical_json_bytes, sha256_hex
        snapshot = copy.deepcopy(self.fixture.snapshot)
        snapshot["quality_state"] = "INSUFFICIENT_COVERAGE"
        snapshot["blocked_reasons"] = ["SYNTHETIC_CONNECTION_GAP"]
        snapshot["snapshot_hash"] = sha256_hex(canonical_json_bytes(
            {k: v for k, v in snapshot.items() if k != "snapshot_hash"}))
        pack = self.fixture.run_pack(snapshot=snapshot, at=self.cutoff)
        source = self.candidate["source_id"]
        captures = copy.deepcopy(self.captures)
        captures[source]["fetch"] = FetchResult(source, "OK", payload=snapshot)
        captures[source]["raw_utf8"] = json.dumps(snapshot, sort_keys=True)
        captures[source]["sha256"] = hashlib.sha256(captures[source]["raw_utf8"].encode()).hexdigest()
        captures[source]["request_identity"] = "READ_LOCAL_PUBLIC_L4_SNAPSHOT:" + captures[source]["sha256"]
        inputs = self.capture(baseline_pack=pack, captures=captures, liquidation_snapshot=snapshot)
        self.assertEqual(inputs["B"]["state"], "BLOCKED")
        self.assertEqual(inputs["A"]["state"], "AVAILABLE_FOR_RESEARCH")
        self.assertFalse(inputs["wake_comparison"]["B_requested"])

    def test_B_only_event_evidence_cannot_be_cited_by_A(self):
        inputs = self.capture()
        judgments = self.judgments(inputs)
        judgments["A"]["supporting_evidence_ids"] = inputs["B"]["evidence_ids"]
        self.now.return_value = self.cutoff + 1000
        with self.assertRaisesRegex(ValueError, "SHADOW_EVIDENCE_REFERENCE_INVALID"):
            runner.freeze_liquidation_shadow_judgments(self.store, inputs["pair_id"], judgments)

    def test_nested_B_increment_cannot_contaminate_A_diagnostic_or_wake(self):
        mutants = [
            {"wake": {"liquidation_research": {"event_id": "synthetic-B-event"}}},
            {"wake": {"wake_sources": ["LIQUIDATION_RESEARCH"]}},
            {"evidence_ids": [self.candidate["anchor_evidence_id"]]},
        ]
        for mutation in mutants:
            with self.subTest(mutation=mutation):
                pack = copy.deepcopy(self.baseline)
                pack["transition_diagnostic"] = mutation
                with self.assertRaisesRegex(ValueError, "SHADOW_A_ALREADY_CONTAINS_INCREMENT"):
                    self.capture(baseline_pack=self.rehash(pack))

    def test_late_formation_cannot_claim_synchronous_judgment(self):
        inputs = self.capture()
        self.now.return_value = self.cutoff + 121_000
        judgments = self.judgments(inputs)
        for arm in judgments.values():
            arm["formed_at_ms"] = self.now.return_value
        with self.assertRaises(ValueError):
            runner.freeze_liquidation_shadow_judgments(self.store, inputs["pair_id"], judgments)

    def test_capital_authority_cannot_be_added_to_judgments(self):
        inputs = self.capture()
        judgments = self.judgments(inputs)
        judgments["B"]["capital_posture_research"]["state"] = "BUY_APPROVED"
        self.now.return_value = self.cutoff + 1000
        with self.assertRaisesRegex(ValueError, "SHADOW_CAPITAL_LINK_MISSING"):
            runner.freeze_liquidation_shadow_judgments(self.store, inputs["pair_id"], judgments)

    def test_primary_research_hypothesis_must_be_explicit_and_nonempty(self):
        inputs = self.capture()
        self.now.return_value = self.cutoff + 1000
        for value in (None, "", " "):
            with self.subTest(value=value):
                judgments = self.judgments(inputs)
                if value is None:
                    judgments["B"].pop("research_hypothesis")
                else:
                    judgments["B"]["research_hypothesis"] = value
                with self.assertRaises(ValueError):
                    runner.freeze_liquidation_shadow_judgments(self.store, inputs["pair_id"], judgments)
                self.assertIsNone(self.store.research_event(inputs["pair_id"] + ":judgments",
                                                           kind="LIQUIDATION_SHADOW_JUDGMENTS"))

    def test_baseline_cannot_grant_external_actions(self):
        pack = copy.deepcopy(self.baseline)
        pack["authority"]["external_action_authority"] = "APPROVED"
        with self.assertRaises(ValueError):
            self.capture(baseline_pack=self.rehash(pack))

    def test_q1_confirmation_cannot_be_self_certified_in_baseline(self):
        pack = copy.deepcopy(self.baseline)
        pack["btc_control_transfer_validation"] = {
            "research_state": "CONTROL_TRANSFER_VALIDATED", "formal_season": "SPRING",
            "event_order": "AFTER_CANDIDATE", "distinct_event": True}
        with self.assertRaises(ValueError):
            self.capture(baseline_pack=self.rehash(pack))

    def test_nested_future_context_clock_cannot_hide_in_valid_pack_hash(self):
        pack = copy.deepcopy(self.baseline)
        pack["private_context"] = {"source_evidence": {"first_seen_at_ms": self.cutoff + 1}}
        with self.assertRaisesRegex(ValueError, "SHADOW_FUTURE_CONTEXT_OR_CLOCK_INVALID"):
            self.capture(baseline_pack=self.rehash(pack))

    def test_observation_before_enrollment_does_not_become_prospective(self):
        # Existing Gate/Wake remains valid, but the study began after this event.
        self.new_study(mode="SYNTHETIC_TEST", start_ms=self.cutoff - 500)
        result = self.capture()
        self.assertEqual(result["B"]["state"], "BLOCKED")
        self.assertEqual(result["B"]["reason"], "SHADOW_PRE_ENROLLMENT_EVENT")

    def test_followup_cannot_reuse_prefreeze_visible_archive_or_rewrite_judgments(self):
        inputs = self.capture()
        frozen = self.freeze(inputs)
        self.now.return_value = self.cutoff + 2 * 86_400_000
        with self.assertRaisesRegex(ValueError, "SHADOW_FOLLOWUP_ALREADY_VISIBLE_AT_FREEZE"):
            runner.record_liquidation_shadow_followup(self.store, inputs["pair_id"],
                archive_root=self.fixture.root, artifact={"first_seen_at_ms": self.cutoff},
                window_start_ms=self.cutoff + 2000, window_end_ms=self.cutoff + 3000,
                interpretation="SYNTHETIC outcome cannot revise the earlier hypothesis")
        self.assertEqual(self.store.research_event(inputs["pair_id"] + ":judgments",
                                                   kind="LIQUIDATION_SHADOW_JUDGMENTS"), frozen)

    def test_later_verified_outcome_is_append_only_not_judgment_quality_proof(self):
        inputs = self.capture()
        frozen = self.freeze(inputs)
        # Reuse GO4's existing synthetic archive builder and real archive validator.
        import test_btc_control_transfer_observed as observed
        archive = observed.ObservedControlTransferTests()
        archive.root = self.fixture.root
        day = 86_400_000
        end = (self.cutoff // day + 3) * day
        artifact = archive.capture(end)
        self.now.return_value = artifact["first_seen_at_ms"] + 1000
        parameters = dict(archive_root=self.fixture.root, artifact=artifact,
            window_start_ms=end - day, window_end_ms=end - 1,
            interpretation="Synthetic later outcome; investment reasoning remains independently unproven")
        result = runner.record_liquidation_shadow_followup(self.store, inputs["pair_id"], **parameters)
        self.assertTrue(result["market_outcome_not_decision_quality_proof"])
        self.assertEqual(result["paired_judgments_hash"], runner._shadow_hash(frozen))
        self.assertEqual(runner.record_liquidation_shadow_followup(self.store, inputs["pair_id"], **parameters), result)
        with self.assertRaisesRegex(ValueError, "SHADOW_FROZEN_OUTCOME_CONFLICT"):
            runner.record_liquidation_shadow_followup(self.store, inputs["pair_id"],
                **{**parameters, "interpretation": "Rewrite the old outcome"})
        self.assertEqual(self.store.research_event(inputs["pair_id"] + ":judgments",
                                                   kind="LIQUIDATION_SHADOW_JUDGMENTS"), frozen)


if __name__ == "__main__":
    unittest.main()
