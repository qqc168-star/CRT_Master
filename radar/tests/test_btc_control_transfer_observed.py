"""Synthetic chronology/integrity tests; these do not prove analyst accuracy."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from l6_public_capture import archive_structure_observation, proxy_source
from crt_radar.btc_control_transfer_validation import (
    OBSERVED_SCHEMA_VERSION, freeze_control_transfer_candidate,
    evaluate_control_transfer_validation, _iso_ms,
)
from crt_radar.observation_store import ObservationStore, ObservationRevisionConflict
from crt_radar.btc_transition_replay_evidence import build_structure_measurements
from crt_radar.season_transition_warning_overlay import _historical_replay
from crt_radar.evidence_pack import build_evidence_pack
from test_first_evidence_slice import gate

DAY = 86_400_000
END = 1791676800000  # Synthetic fixture clock, not a real forecast.
AUTHORITY = {key: "NONE" for key in ("formal_model_authority", "formal_weight_authority",
    "formal_threshold_authority", "season_transition_authority", "external_action_authority")}
AUTHORITY["external_action_performed"] = False


class ObservedControlTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "observations.sqlite3"
        self.store = ObservationStore(self.db)
        self.addCleanup(self.store.close)
        self.artifact = self.capture(END)
        self.observation = archive_structure_observation(self.root, self.artifact, self.store,
            recorded_at_ms=self.artifact["first_seen_at_ms"])
        self.formed = self.artifact["first_seen_at_ms"]
        self.references = {"old_control_high": 103.0, "old_control_zone_lower": 95.0,
            "old_control_zone_upper": 100.0, "candidate_invalidation_anchor": 90.0,
            "references_frozen_at": _iso_ms(self.formed),
            "reference_provenance": self.observation["observation_id"]}
        self.candidate = freeze_control_transfer_candidate(self.store,
            observation_id=self.observation["observation_id"], formed_at_ms=self.formed,
            references=self.references, classification_provenance="SYNTHETIC_ANALYST_CLASSIFICATION")
        self.next_artifact = self.capture(END + 2 * DAY)
        self.followup = archive_structure_observation(self.root, self.next_artifact, self.store,
            recorded_at_ms=self.next_artifact["first_seen_at_ms"], window_start_ms=END+DAY)
        self.cutoff = self.next_artifact["first_seen_at_ms"]
        self.evidence = {"schema_version": OBSERVED_SCHEMA_VERSION, "authority": AUTHORITY,
            "candidate_event_id": self.candidate["event_id"], "post_c_test": {
                "observation_id": self.followup["observation_id"],
                "frozen_reference_hash": self.candidate["reference_hash"],
                "event_id": "UNTRUSTED_CALLER_ID", "event_order": "AFTER_CANDIDATE", "distinct_event": True,
                "old_control_zone_result": "HELD", "candidate_structure_result": "PRESERVED",
                "renewed_expansion": "CONFIRMED", "new_local_control_high_break": "NOT_CONFIRMED"}}

    def capture(self, end):
        registry, spec = proxy_source()
        rows = [[end-(201-index)*DAY, "100", "105", "95", "102", "10",
                 end-(200-index)*DAY-1, "1020", 5, "5", "510", "0"] for index in range(201)]
        raw = json.dumps(rows).encode()
        sha = hashlib.sha256(raw).hexdigest()
        relpath = f"artifacts/sha256/{sha[:2]}/{sha}"
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        first = end+3_600_000
        return {"source_contract_id": "PRICE_STRUCTURE_CONTEXT", "request_identity": "GET "+spec.endpoint,
            "retrieved_at_ms": first, "first_seen_at_ms": first, "available_at_coverage_start_ms": first,
            "available_at_coverage_end_ms": first, "sha256": sha, "size_bytes": len(raw),
            "archive_relpath": relpath, "source_authority_hash": registry.hash,
            "source_id": spec.source_id, "source_documentation": spec.raw["documentation"],
            "formal_composite_authority": "NONE", "replay_eligible": False,
            "evidence_class": "CURRENT_FIRST_SEEN_CAPTURE",
            "license_classification": "TERMS_REVIEW_REQUIRED_LOCAL_RESEARCH_ONLY"}

    def evaluate(self, evidence=None, cutoff=None):
        return evaluate_control_transfer_validation(evidence or self.evidence,
            observation_store=self.store, evaluated_at_ms=cutoff or self.cutoff)

    def test_later_visible_event_can_confirm_research_only(self):
        result = self.evaluate()
        self.assertEqual(result["research_state"], "CONTROL_TRANSFER_VALIDATED")
        self.assertEqual(result["temporal_verification"], "VERIFIED")
        self.assertEqual(result["causal_source_independence"], "NOT_PROVEN")
        self.assertIsNone(result["formal_season"])
        self.assertEqual(result["action_output"], "NONE")
        self.assertNotEqual(result["validation_event_id"], "UNTRUSTED_CALLER_ID")

    def test_caller_order_flags_cannot_deny_or_manufacture_chronology(self):
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"].update(event_order="BEFORE_CANDIDATE", distinct_event=False)
        self.assertEqual(self.evaluate(supplied)["research_state"], "CONTROL_TRANSFER_VALIDATED")

    def test_earlier_followup_rejected(self):
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"]["observation_id"] = self.observation["observation_id"]
        self.assertIn("NOT_INDEPENDENT", self.evaluate(supplied)["reason"])

    def test_distinct_earlier_market_window_cannot_confirm(self):
        earlier_artifact = self.capture(END-DAY)
        earlier = archive_structure_observation(self.root, earlier_artifact, self.store,
            recorded_at_ms=earlier_artifact["first_seen_at_ms"], window_start_ms=END-2*DAY)
        self.assertNotEqual(earlier["observation_id"], self.observation["observation_id"])
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"]["observation_id"] = earlier["observation_id"]
        self.assertIn("NOT_INDEPENDENT", self.evaluate(supplied)["reason"])

    def test_unseen_followup_rejected(self):
        self.assertIn("NOT_VISIBLE", self.evaluate(cutoff=self.cutoff-1)["reason"])

    def test_renaming_underlying_observation_cannot_confirm(self):
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"]["observation_id"] = "new-name-for-old-observation"
        self.assertEqual(self.evaluate(supplied)["reason"], "UNDERLYING_OBSERVATION_MISSING")

    def test_same_underlying_window_stored_under_another_id_cannot_confirm(self):
        self.store.record_research_event("renamed-observation", "structure_observation", self.observation)
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"]["observation_id"] = "renamed-observation"
        self.assertEqual(self.evaluate(supplied)["reason"], "UNDERLYING_OBSERVATION_IDENTITY_INVALID")

    def test_candidate_alias_cannot_create_another_qualified_hypothesis(self):
        self.store.record_research_event("candidate-alias", "control_transfer_candidate", self.candidate)
        supplied = {**self.evidence, "candidate_event_id": "candidate-alias"}
        self.assertEqual(self.evaluate(supplied)["reason"], "FROZEN_CANDIDATE_IDENTITY_OR_CLOCK_INVALID")

    def test_repeat_evaluation_is_deduplicated_across_restart(self):
        self.evaluate()
        before = self.store.conn.execute("SELECT COUNT(*) FROM btc_research_events WHERE kind='control_transfer_assessment'").fetchone()[0]
        with ObservationStore(self.db) as reopened:
            result = evaluate_control_transfer_validation(self.evidence, observation_store=reopened,
                                                         evaluated_at_ms=self.cutoff+1000)
            self.assertEqual(result["research_state"], "CONTROL_TRANSFER_VALIDATED")
        after = self.store.conn.execute("SELECT COUNT(*) FROM btc_research_events WHERE kind='control_transfer_assessment'").fetchone()[0]
        self.assertEqual(before, after)

    def test_redownload_does_not_change_identity_or_first_visibility(self):
        redownload = copy.deepcopy(self.artifact)
        raw = (self.root/redownload["archive_relpath"]).read_bytes()+b"\n"
        sha = hashlib.sha256(raw).hexdigest()
        path = self.root/f"artifacts/sha256/{sha[:2]}/{sha}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        redownload.update(sha256=sha, size_bytes=len(raw), archive_relpath=str(path.relative_to(self.root)).replace("\\", "/"))
        for field in ("retrieved_at_ms", "first_seen_at_ms", "available_at_coverage_start_ms", "available_at_coverage_end_ms"):
            redownload[field] += 1000
        again = archive_structure_observation(self.root, redownload, self.store, recorded_at_ms=self.formed+1000)
        self.assertEqual(again, self.observation)

    def test_reference_redraw_cannot_overwrite_candidate(self):
        refs = {**self.references, "old_control_high": 999.0}
        with self.assertRaises(ObservationRevisionConflict):
            freeze_control_transfer_candidate(self.store, observation_id=self.observation["observation_id"],
                formed_at_ms=self.formed, references=refs, classification_provenance="SYNTHETIC_ANALYST_CLASSIFICATION")
        self.assertEqual(self.store.research_event(self.candidate["event_id"], kind="control_transfer_candidate"), self.candidate)

    def test_followup_cannot_redraw_reference(self):
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"]["frozen_reference_hash"] = "f"*64
        self.assertEqual(self.evaluate(supplied)["reason"], "POST_C_FROZEN_REFERENCE_MISMATCH")

    def test_missing_followup_stays_pending(self):
        supplied = copy.deepcopy(self.evidence)
        supplied.pop("post_c_test")
        self.assertEqual(self.evaluate(supplied)["research_state"], "VALIDATION_PENDING")

    def test_known_negative_classification_preserved(self):
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"]["candidate_structure_result"] = "INVALIDATED"
        self.assertEqual(self.evaluate(supplied)["research_state"], "CONTROL_TRANSFER_CANDIDATE_FAILED")

    def test_unresolved_classification_stays_pending(self):
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"]["renewed_expansion"] = "UNRESOLVED"
        self.assertEqual(self.evaluate(supplied)["research_state"], "VALIDATION_PENDING")

    def test_backfill_cannot_claim_historical_visibility(self):
        measurement = build_structure_measurements(self.observation["bars"],
            as_of=_iso_ms(END-1), **{**self.references, "references_frozen_at": _iso_ms(END-2)})
        self.assertEqual(measurement["reason"], "NO_VISIBLE_STRUCTURE_BARS")
        self.assertEqual(self.observation["availability_scope"], "ACTUAL_FIRST_SEEN_NOT_HISTORICAL_FORECAST")

    def test_common_first_seen_clock_does_not_duplicate_market_bars(self):
        self.assertEqual(self.candidate["measurements"]["visible_bar_count"], 201)

    def test_mutated_future_archive_does_not_rewrite_frozen_candidate(self):
        frozen = copy.deepcopy(self.candidate)
        raw_path = self.root/self.next_artifact["archive_relpath"]
        raw_path.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            archive_structure_observation(self.root, self.next_artifact, self.store, recorded_at_ms=self.cutoff)
        self.assertEqual(self.store.research_event(frozen["event_id"], kind="control_transfer_candidate"), frozen)

    def test_actual_evidence_requires_store(self):
        self.assertEqual(evaluate_control_transfer_validation(self.evidence)["state"], "BLOCKED")

    def test_unclassified_real_shape_preserves_observation_without_candidate(self):
        result = self.evaluate({"schema_version": OBSERVED_SCHEMA_VERSION, "authority": AUTHORITY,
                                "observation_id": self.observation["observation_id"]})
        self.assertEqual(result["research_state"], "INCONCLUSIVE")
        self.assertEqual(result["structure_observation"]["raw_sha256"], self.artifact["sha256"])
        self.assertNotIn("archive_root", result["structure_observation"])
        self.assertEqual(result["structure_measurements"]["state"], "BLOCKED")

    def test_archive_tampering_after_ingestion_blocks_validation(self):
        (self.root/self.next_artifact["archive_relpath"]).write_bytes(b"tampered")
        self.assertEqual(self.evaluate()["reason"], "L6_ARTIFACT_BYTES_MISMATCH")

    def test_claimed_source_without_raw_archive_cannot_confirm(self):
        changed = copy.deepcopy(self.followup)
        changed["archive_root"] = str(self.root / "missing")
        self.store.conn.execute("DELETE FROM btc_research_events WHERE event_id=?", (changed["observation_id"],))
        self.store.conn.commit()
        self.store.record_research_event(changed["observation_id"], "structure_observation", changed)
        self.assertEqual(self.evaluate()["state"], "BLOCKED")

    def test_reference_source_not_yet_visible_blocks_freezing(self):
        references = {**self.references, "references_frozen_at": _iso_ms(END-1)}
        with self.assertRaisesRegex(ValueError, "NOT_VISIBLE"):
            freeze_control_transfer_candidate(self.store, observation_id=self.observation["observation_id"],
                formed_at_ms=self.formed, references=references,
                classification_provenance="SYNTHETIC_ANALYST_CLASSIFICATION")

    def test_reversal_review_requires_another_later_observation(self):
        self.evaluate()
        supplied = copy.deepcopy(self.evidence)
        supplied["post_validation_review"] = {"state": "REVERSAL_CONFIRMED", "event_id": "renamed",
            "event_order": "AFTER_VALIDATION", "distinct_event": True,
            "observation_id": self.followup["observation_id"], "frozen_reference_hash": self.candidate["reference_hash"]}
        self.assertEqual(self.evaluate(supplied)["reason"], "REVIEW_EVENT_NOT_INDEPENDENT_OR_REFERENCE_CHANGED")

    def test_replay_ignores_caller_renaming_and_extra_metadata(self):
        first = self.evaluate()
        supplied = copy.deepcopy(self.evidence)
        supplied["post_c_test"].update(event_id="another-name", filename="renamed.json")
        second = self.evaluate(supplied, cutoff=self.cutoff+1000)
        self.assertEqual(first["validation_event_id"], second["validation_event_id"])
        self.assertEqual(first["control_transfer_validated_at"], second["control_transfer_validated_at"])
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM btc_research_events WHERE kind='control_transfer_assessment'").fetchone()[0], 1)

    def test_lifecycle_survives_database_restart(self):
        context = {"historical_case_id": "synthetic-case"}
        started = _historical_replay(generated_at_ms=self.formed, scenario_id="SCENARIO_1", previous=None, replay_context=context)
        for event in started["warning_lifecycle"]:
            self.store.record_research_event(event["event_id"], "warning_lifecycle", event)
        self.store.record_research_event("snapshot", "warning_snapshot", {"historical_replay": started})
        with ObservationStore(self.db) as reopened:
            previous = reopened.latest_research_event("warning_snapshot")
            withdrawn = _historical_replay(generated_at_ms=self.cutoff, scenario_id="SCENARIO_0", previous=previous,
                replay_context={**context, "ground_truth_outcome": "NO_TRANSITION"})
        self.assertEqual(withdrawn["warning_episode_count"], 1)
        self.assertTrue(withdrawn["false_positive"])

    def test_legacy_classification_cannot_be_promoted_by_evidence_pack(self):
        # The legacy case IDs/timestamps remain classification fixtures only.
        legacy = {"schema_version": "CRT_BTC_CONTROL_TRANSFER_VALIDATION_EVIDENCE_V0.1"}
        self.assertEqual(evaluate_control_transfer_validation(legacy, require_observed_evidence=True)["reason"],
                         "OBSERVED_EVENT_LINEAGE_REQUIRED")

    def test_observed_chain_enters_pack_without_formal_season(self):
        pack = build_evidence_pack(gate(0, blocked=True), observation_db=self.db,
            generated_at_ms=self.cutoff, btc_control_transfer_validation_evidence=self.evidence)
        self.assertEqual(pack["btc_control_transfer_validation"]["research_state"], "CONTROL_TRANSFER_VALIDATED")
        self.assertIsNone(pack["season_transition_warning_overlay"]["formal_season"])

    def test_withdrawn_warning_remains_a_false_positive(self):
        context = {"historical_case_id": "synthetic-case", "ground_truth_outcome": "NO_TRANSITION"}
        first = _historical_replay(generated_at_ms=self.formed, scenario_id="SCENARIO_1", previous=None, replay_context=context)
        withdrawn = _historical_replay(generated_at_ms=self.cutoff, scenario_id="SCENARIO_0",
            previous={"historical_replay": first}, replay_context=context)
        replayed = _historical_replay(generated_at_ms=self.cutoff, scenario_id="SCENARIO_0",
            previous={"historical_replay": withdrawn}, replay_context=context)
        self.assertTrue(withdrawn["false_positive"])
        self.assertEqual([event["kind"] for event in withdrawn["warning_lifecycle"]], ["WARNING_STARTED", "WARNING_WITHDRAWN"])
        self.assertEqual(replayed, withdrawn)


if __name__ == "__main__":
    unittest.main()
