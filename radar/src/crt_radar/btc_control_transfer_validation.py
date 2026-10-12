from __future__ import annotations

from typing import Any
import hashlib
import json
from datetime import datetime, timezone

from .btc_transition_replay_evidence import build_structure_measurements, archived_structure_bars, _parse_timestamp


SCHEMA_VERSION = "CRT_BTC_CONTROL_TRANSFER_VALIDATION_EVIDENCE_V0.1"
RESULT_SCHEMA_VERSION = "CRT_BTC_CONTROL_TRANSFER_VALIDATION_RESEARCH_EVAL_V0.1"

ZONE_RESULTS = {
    "HELD",
    "BREACHED_AND_RECLAIMED",
    "LOST_NOT_RECLAIMED",
    "UNRESOLVED",
}

STRUCTURE_RESULTS = {
    "PRESERVED",
    "INVALIDATED",
    "UNRESOLVED",
}

EXPANSION_RESULTS = {
    "CONFIRMED",
    "NOT_CONFIRMED",
    "UNRESOLVED",
}

OPTIONAL_HIGH_BREAK_RESULTS = {
    "CONFIRMED",
    "NOT_CONFIRMED",
    "UNAVAILABLE",
}

REVIEW_STATES = {
    "NONE",
    "UNDER_REVIEW",
    "REVERSAL_CONFIRMED",
}

OBSERVED_SCHEMA_VERSION = "CRT_BTC_CONTROL_TRANSFER_OBSERVED_EVIDENCE_V0.1"


def research_identity(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _clock(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("RESEARCH_CLOCK_INVALID")
    return value


def _iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _observation(store, observation_id: str, cutoff: int) -> dict:
    observation = store.research_event(observation_id, kind="structure_observation")
    if not observation:
        raise ValueError("UNDERLYING_OBSERVATION_MISSING")
    identity = {key: observation[key] for key in
                ("source_id", "product", "window_start_ms", "window_end_ms", "event_definition")}
    if research_identity(identity) != observation_id:
        raise ValueError("UNDERLYING_OBSERVATION_IDENTITY_INVALID")
    start, end, available, first, recorded = [_clock(observation[key]) for key in
        ("window_start_ms", "window_end_ms", "source_available_at_ms", "first_seen_at_ms", "recorded_at_ms")]
    if not start <= end < available <= first <= recorded <= cutoff:
        raise ValueError("UNDERLYING_OBSERVATION_NOT_VISIBLE")
    if (observation.get("quality_state") != "RESEARCH_ARCHIVE_VERIFIED"
            or observation.get("formal_composite_authority") != "NONE"
            or observation["source_id"] != "CRT-CONN-BTC-SPOT-PRICE-STRUCTURE-PROXY-001"
            or observation["product"] != "BTCUSDT"):
        raise ValueError("UNDERLYING_OBSERVATION_SOURCE_INVALID")
    bars = observation.get("bars")
    if not isinstance(bars, list) or not bars:
        raise ValueError("UNDERLYING_OBSERVATION_BARS_MISSING")
    for bar in bars:
        market = int(_parse_timestamp(bar.get("observed_at"), "observed_at").timestamp()*1000)
        visible = int(_parse_timestamp(bar.get("available_at"), "available_at").timestamp()*1000)
        if not start <= market <= end or visible != first:
            raise ValueError("UNDERLYING_OBSERVATION_BAR_CLOCK_MISMATCH")
    if int(_parse_timestamp(bars[-1]["observed_at"], "observed_at").timestamp()*1000) != end:
        raise ValueError("UNDERLYING_OBSERVATION_WINDOW_MISMATCH")
    from .source_gate_runner import verified_price_structure_archive, parse_price_structure
    artifact = observation.get("artifact", {})
    payload = verified_price_structure_archive(observation["archive_root"], artifact, cutoff)
    parse_price_structure(payload, now_ms=artifact["retrieved_at_ms"])
    if (artifact.get("sha256") != observation.get("raw_sha256")
            or artifact.get("first_seen_at_ms") != first
            or artifact.get("retrieved_at_ms") != available
            or artifact.get("source_id") != observation["source_id"]
            or archived_structure_bars(payload, available_at_ms=first,
                    window_start_ms=start, window_end_ms=end) != bars):
        raise ValueError("UNDERLYING_OBSERVATION_ARCHIVE_MISMATCH")
    return observation


def freeze_control_transfer_candidate(store, *, observation_id: str, formed_at_ms: int,
                                     references: dict, classification_provenance: str) -> dict:
    """Freeze an analyst-classified candidate; never classify a measured breakout.

    Call only after analyst classification under the existing research contract.
    No archive, price coordinate, or raw crossing automatically calls this API.
    """
    formed = _clock(formed_at_ms)
    if not isinstance(classification_provenance, str) or not classification_provenance.strip():
        raise ValueError("ANALYST_CLASSIFICATION_PROVENANCE_REQUIRED")
    observation = _observation(store, observation_id, formed)
    measurements = build_structure_measurements(observation["bars"], as_of=_iso_ms(formed), **references)
    if measurements["state"] == "BLOCKED":
        raise ValueError(measurements["reason"])
    # The reference source and its first visibility must themselves be provable.
    reference_source = store.research_event(references["reference_provenance"], kind="structure_observation")
    if not reference_source:
        raise ValueError("REFERENCE_OBSERVATION_MISSING")
    frozen = int(_parse_timestamp(references["references_frozen_at"], "references_frozen_at").timestamp()*1000)
    _observation(store, references["reference_provenance"], frozen)
    reference_hash = research_identity(measurements["references"])
    # Same candidate observation/provenance cannot be redrawn under another hash.
    lock_id = research_identity({"candidate_observation": observation_id,
                                 "reference_provenance": references["reference_provenance"]})
    store.record_research_event("reference:"+lock_id, "reference_lock", measurements["references"])
    event_id = research_identity({"observation_id": observation_id, "event_definition": "CONTROL_TRANSFER_CANDIDATE",
                                  "frozen_reference_hash": reference_hash})
    candidate = {"event_id": event_id, "state": "CONTROL_TRANSFER_CANDIDATE",
        "observation_id": observation_id, "formed_at_ms": formed,
        "timestamp": _iso_ms(formed), "references": references,
        "reference_hash": reference_hash, "measurements": measurements,
        "classification_provenance": classification_provenance,
        "old_control_zone_ref": reference_hash, "candidate_invalidation_anchor_ref": reference_hash,
        "reference_provenance": references["reference_provenance"]}
    prior = store.research_event(event_id, kind="control_transfer_candidate")
    if prior:
        if prior["references"] != references or prior["classification_provenance"] != classification_provenance:
            raise ValueError("FROZEN_CANDIDATE_CONFLICT")
        return prior
    store.record_research_event(event_id, "control_transfer_candidate", candidate)
    return candidate

AUTHORITY_FIELDS = (
    "formal_model_authority",
    "formal_weight_authority",
    "formal_threshold_authority",
    "season_transition_authority",
    "external_action_authority",
)


def _result(
    *,
    state: str,
    reason: str,
    research_state: str,
    candidate_event_id: str | None = None,
    validation_event_id: str | None = None,
    control_transfer_validated_at: str | None = None,
    current_validation_status: str | None = None,
    strengthening_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "state": state,
        "reason": reason,
        "research_state": research_state,
        "candidate_event_id": candidate_event_id,
        "validation_event_id": validation_event_id,
        "control_transfer_validated_at": control_transfer_validated_at,
        "current_validation_status": current_validation_status,
        "strengthening_evidence": strengthening_evidence or {},
        "formal_season": None,
        "formal_model_authority": "NONE",
        "formal_weight_authority": "NONE",
        "formal_threshold_authority": "NONE",
        "season_transition_authority": "NONE",
        "machine_may_determine_btc_season": False,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def _blocked(reason: str) -> dict[str, Any]:
    return _result(
        state="BLOCKED",
        reason=reason,
        research_state="BLOCKED",
    )


def _pending(
    *,
    reason: str,
    candidate_event_id: str,
    validation_event_id: str | None,
    strengthening_evidence: dict[str, Any],
) -> dict[str, Any]:
    return _result(
        state="READY_FOR_ANALYST",
        reason=reason,
        research_state="VALIDATION_PENDING",
        candidate_event_id=candidate_event_id,
        validation_event_id=validation_event_id,
        strengthening_evidence=strengthening_evidence,
    )


def _evaluate_classified_control_transfer_validation(
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate pre-classified post-C validation evidence.

    This research-only evaluator does not detect pivots, invent thresholds,
    determine Formal Season, or create trade actions.
    """

    if not isinstance(evidence, dict):
        return _result(
            state="NOT_AVAILABLE",
            reason="CONTROL_TRANSFER_VALIDATION_EVIDENCE_NOT_AVAILABLE",
            research_state="INCONCLUSIVE",
        )

    if evidence.get("schema_version") != SCHEMA_VERSION:
        return _blocked("CONTROL_TRANSFER_VALIDATION_EVIDENCE_SCHEMA_MISMATCH")

    authority = evidence.get("authority")
    if not isinstance(authority, dict):
        return _blocked("CONTROL_TRANSFER_VALIDATION_AUTHORITY_MISSING")

    for field in AUTHORITY_FIELDS:
        if authority.get(field) != "NONE":
            return _blocked(
                f"CONTROL_TRANSFER_VALIDATION_{field.upper()}_MUST_BE_NONE"
            )

    if authority.get("external_action_performed") is not False:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_EXTERNAL_ACTION_PERFORMED_MUST_BE_FALSE"
        )

    candidate = evidence.get("candidate")
    if not isinstance(candidate, dict):
        return _blocked("CONTROL_TRANSFER_VALIDATION_CANDIDATE_MISSING")

    if candidate.get("state") != "CONTROL_TRANSFER_CANDIDATE":
        return _result(
            state="NOT_AVAILABLE",
            reason="CONTROL_TRANSFER_VALIDATION_REQUIRES_CANDIDATE",
            research_state="INCONCLUSIVE",
        )

    required_candidate_fields = (
        "event_id",
        "timestamp",
        "old_control_zone_ref",
        "candidate_invalidation_anchor_ref",
        "reference_provenance",
    )
    for field in required_candidate_fields:
        value = candidate.get(field)
        if not isinstance(value, str) or not value.strip():
            return _blocked(
                f"CONTROL_TRANSFER_VALIDATION_CANDIDATE_FIELD_INVALID:{field}"
            )

    candidate_event_id = str(candidate["event_id"])

    post_c = evidence.get("post_c_test")
    if not isinstance(post_c, dict):
        return _pending(
            reason="POST_C_INDEPENDENT_TEST_NOT_AVAILABLE",
            candidate_event_id=candidate_event_id,
            validation_event_id=None,
            strengthening_evidence={},
        )

    validation_event_id = post_c.get("event_id")
    if not isinstance(validation_event_id, str) or not validation_event_id.strip():
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_POST_C_EVENT_ID_INVALID"
        )

    timestamp = post_c.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_POST_C_TIMESTAMP_INVALID"
        )

    event_order = post_c.get("event_order")
    if event_order not in {"AFTER_CANDIDATE", "UNRESOLVED"}:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_POST_C_EVENT_ORDER_INVALID"
        )

    distinct_event = post_c.get("distinct_event")
    if distinct_event not in {True, False}:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_DISTINCT_EVENT_INVALID"
        )

    if (
        distinct_event is True
        and validation_event_id == candidate_event_id
    ):
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_EVENT_ID_CONTRADICTION"
        )

    high_break = post_c.get("new_local_control_high_break")
    if high_break not in OPTIONAL_HIGH_BREAK_RESULTS:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_HIGH_BREAK_EVIDENCE_INVALID"
        )

    strengthening_evidence = {
        "new_local_control_high_break": high_break,
        "mandatory_gate": False,
    }

    if event_order == "UNRESOLVED" or distinct_event is False:
        return _pending(
            reason="INDEPENDENT_LATER_VALIDATION_EVENT_NOT_CONFIRMED",
            candidate_event_id=candidate_event_id,
            validation_event_id=validation_event_id,
            strengthening_evidence=strengthening_evidence,
        )

    zone_result = post_c.get("old_control_zone_result")
    if zone_result not in ZONE_RESULTS:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_OLD_CONTROL_ZONE_RESULT_INVALID"
        )

    structure_result = post_c.get("candidate_structure_result")
    if structure_result not in STRUCTURE_RESULTS:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_STRUCTURE_RESULT_INVALID"
        )

    renewed_expansion = post_c.get("renewed_expansion")
    if renewed_expansion not in EXPANSION_RESULTS:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_RENEWED_EXPANSION_INVALID"
        )

    if (
        zone_result == "LOST_NOT_RECLAIMED"
        or structure_result == "INVALIDATED"
    ):
        return _result(
            state="READY_FOR_ANALYST",
            reason="POST_C_CONTROL_ZONE_OR_STRUCTURE_INVALIDATED",
            research_state="CONTROL_TRANSFER_CANDIDATE_FAILED",
            candidate_event_id=candidate_event_id,
            validation_event_id=validation_event_id,
            strengthening_evidence=strengthening_evidence,
        )

    if (
        zone_result == "UNRESOLVED"
        or structure_result == "UNRESOLVED"
        or renewed_expansion in {"NOT_CONFIRMED", "UNRESOLVED"}
    ):
        return _pending(
            reason="POST_C_VALIDATION_SEQUENCE_INCOMPLETE",
            candidate_event_id=candidate_event_id,
            validation_event_id=validation_event_id,
            strengthening_evidence=strengthening_evidence,
        )

    if zone_result not in {"HELD", "BREACHED_AND_RECLAIMED"}:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_CONTROL_ZONE_ACCEPTANCE_CONTRADICTION"
        )

    if structure_result != "PRESERVED":
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_STRUCTURE_PRESERVATION_CONTRADICTION"
        )

    if renewed_expansion != "CONFIRMED":
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_RENEWED_EXPANSION_CONTRADICTION"
        )

    review = evidence.get("post_validation_review", {"state": "NONE"})
    if not isinstance(review, dict):
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_POST_VALIDATION_REVIEW_INVALID"
        )

    review_state = review.get("state", "NONE")
    if review_state not in REVIEW_STATES:
        return _blocked(
            "CONTROL_TRANSFER_VALIDATION_REVIEW_STATE_INVALID"
        )

    current_status = "ACTIVE"

    if review_state != "NONE":
        review_event_id = review.get("event_id")
        review_timestamp = review.get("timestamp")
        review_order = review.get("event_order")
        review_distinct = review.get("distinct_event")

        if not isinstance(review_event_id, str) or not review_event_id.strip():
            return _blocked(
                "CONTROL_TRANSFER_VALIDATION_REVIEW_EVENT_ID_INVALID"
            )
        if not isinstance(review_timestamp, str) or not review_timestamp.strip():
            return _blocked(
                "CONTROL_TRANSFER_VALIDATION_REVIEW_TIMESTAMP_INVALID"
            )
        if review_order != "AFTER_VALIDATION":
            return _blocked(
                "CONTROL_TRANSFER_VALIDATION_REVIEW_EVENT_ORDER_INVALID"
            )
        if review_distinct is not True:
            return _blocked(
                "CONTROL_TRANSFER_VALIDATION_REVIEW_MUST_BE_DISTINCT"
            )
        if review_event_id in {
            candidate_event_id,
            validation_event_id,
        }:
            return _blocked(
                "CONTROL_TRANSFER_VALIDATION_REVIEW_EVENT_ID_CONTRADICTION"
            )

        if review_state == "UNDER_REVIEW":
            current_status = "UNDER_REVIEW"
        elif review_state == "REVERSAL_CONFIRMED":
            current_status = "REVERSED"

    return _result(
        state="READY_FOR_ANALYST",
        reason="POST_C_INDEPENDENT_VALIDATION_COMPLETE",
        research_state="CONTROL_TRANSFER_VALIDATED",
        candidate_event_id=candidate_event_id,
        validation_event_id=validation_event_id,
        control_transfer_validated_at=str(timestamp),
        current_validation_status=current_status,
        strengthening_evidence=strengthening_evidence,
    )


def evaluate_control_transfer_validation(evidence: dict | None, *, observation_store=None,
                                         evaluated_at_ms: int | None = None,
                                         require_observed_evidence: bool = False) -> dict:
    """Derive actual event chronology from immutable archive observations.

    Legacy cases retain classification regression coverage, explicitly without
    real-time proof. Evidence Pack cannot use those cases as observed validation.
    """
    if not isinstance(evidence, dict) or evidence.get("schema_version") != OBSERVED_SCHEMA_VERSION:
        if require_observed_evidence and isinstance(evidence, dict):
            result = _blocked("OBSERVED_EVENT_LINEAGE_REQUIRED")
        else:
            result = _evaluate_classified_control_transfer_validation(evidence)
        result.update(evidence_scope="CLASSIFICATION_ONLY", temporal_verification="NOT_PROVEN")
        return result
    if observation_store is None or evaluated_at_ms is None:
        return _blocked("OBSERVATION_STORE_AND_EVALUATION_CLOCK_REQUIRED")
    try:
        cutoff = _clock(evaluated_at_ms)
        authority = evidence.get("authority")
        if (not isinstance(authority, dict) or any(authority.get(key) != "NONE" for key in AUTHORITY_FIELDS)
                or authority.get("external_action_performed") is not False):
            raise ValueError("OBSERVED_EVIDENCE_AUTHORITY_INVALID")
        candidate = observation_store.research_event(evidence.get("candidate_event_id"), kind="control_transfer_candidate")
        if not candidate:
            if evidence.get("candidate_event_id") is not None:
                raise ValueError("FROZEN_CANDIDATE_NOT_FOUND")
            observation = _observation(observation_store, evidence.get("observation_id"), cutoff)
            result = _result(state="READY_FOR_ANALYST", research_state="INCONCLUSIVE",
                             reason="FROZEN_ANALYST_CANDIDATE_NOT_AVAILABLE")
            result.update(evidence_scope="ARCHIVED_RESEARCH_OBSERVATIONS", temporal_verification="VERIFIED",
                structure_observation={k:v for k,v in observation.items() if k != "archive_root"},
                structure_measurements={"state": "BLOCKED", "reason": "FROZEN_ANALYST_REFERENCES_NOT_AVAILABLE"},
                forecast_claim="NONE", evaluated_at_ms=cutoff)
            return result
        if _clock(candidate["formed_at_ms"]) > cutoff:
            raise ValueError("CANDIDATE_NOT_YET_VISIBLE")
        original = _observation(observation_store, candidate["observation_id"], candidate["formed_at_ms"])
        expected_candidate_id = research_identity({"observation_id": candidate["observation_id"],
            "event_definition": "CONTROL_TRANSFER_CANDIDATE", "frozen_reference_hash": candidate["reference_hash"]})
        if (expected_candidate_id != evidence["candidate_event_id"]
                or candidate["event_id"] != expected_candidate_id
                or candidate["timestamp"] != _iso_ms(candidate["formed_at_ms"])):
            raise ValueError("FROZEN_CANDIDATE_IDENTITY_OR_CLOCK_INVALID")
        measured = build_structure_measurements(original["bars"], as_of=candidate["timestamp"], **candidate["references"])
        if measured != candidate["measurements"] or research_identity(measured.get("references", {})) != candidate["reference_hash"]:
            raise ValueError("FROZEN_REFERENCE_OR_MEASUREMENT_CHANGED")
        frozen_at = int(_parse_timestamp(candidate["references"]["references_frozen_at"], "frozen_at").timestamp()*1000)
        _observation(observation_store, candidate["reference_provenance"], frozen_at)
        classified = {"schema_version": SCHEMA_VERSION, "authority": evidence.get("authority"),
                      "candidate": candidate}
        supplied = evidence.get("post_c_test")
        later = None
        followup_measurements = None
        if isinstance(supplied, dict):
            later = _observation(observation_store, supplied.get("observation_id"), cutoff)
            if supplied.get("frozen_reference_hash") != candidate["reference_hash"]:
                raise ValueError("POST_C_FROZEN_REFERENCE_MISMATCH")
            # Ignore caller event IDs, event_order and distinct_event claims.
            if (later["product"] != original["product"]
                    or later["window_start_ms"] <= original["window_end_ms"]
                    or later["window_start_ms"] <= candidate["formed_at_ms"]):
                raise ValueError("POST_C_EVENT_NOT_INDEPENDENT_OR_NOT_AFTER_CANDIDATE")
            followup_measurements = build_structure_measurements(later["bars"],
                as_of=_iso_ms(cutoff), **{**candidate["references"], "candidate_breakout_at": candidate["timestamp"]})
            if followup_measurements["state"] == "BLOCKED":
                raise ValueError(followup_measurements["reason"])
            post = {key: supplied.get(key) for key in ("observation_id", "frozen_reference_hash",
                "old_control_zone_result", "candidate_structure_result", "renewed_expansion", "new_local_control_high_break")}
            post.update(event_id=research_identity({"observation_id": later["observation_id"],
                        "event_definition": "POST_C_TEST", "reference_hash": candidate["reference_hash"]}),
                        timestamp=_iso_ms(later["window_end_ms"]), event_order="AFTER_CANDIDATE", distinct_event=True)
            classified["post_c_test"] = post
        review = evidence.get("post_validation_review")
        if isinstance(review, dict) and review.get("state") != "NONE":
            if later is None:
                raise ValueError("REVIEW_WITHOUT_VALIDATION")
            prior_validation = observation_store.research_event("assessment:"+research_identity(classified), kind="control_transfer_assessment")
            if not prior_validation or prior_validation.get("research_state") != "CONTROL_TRANSFER_VALIDATED":
                raise ValueError("REVIEW_WITHOUT_FROZEN_VALIDATION")
            validated_at = int(_parse_timestamp(prior_validation["control_transfer_validated_at"], "validated_at").timestamp()*1000)
            review_obs = _observation(observation_store, review.get("observation_id"), cutoff)
            if (review.get("frozen_reference_hash") != candidate["reference_hash"]
                    or review_obs["window_start_ms"] <= later["window_end_ms"]
                    or review_obs["window_start_ms"] <= validated_at):
                raise ValueError("REVIEW_EVENT_NOT_INDEPENDENT_OR_REFERENCE_CHANGED")
            classified["post_validation_review"] = {"state": review["state"], "event_id": review_obs["observation_id"],
                "timestamp": _iso_ms(review_obs["window_end_ms"]), "event_order": "AFTER_VALIDATION", "distinct_event": True}
        assessment_id = "assessment:"+research_identity(classified)
        prior = observation_store.research_event(assessment_id, kind="control_transfer_assessment")
        if prior:
            return {**prior, "evaluated_at_ms": cutoff}
        result = _evaluate_classified_control_transfer_validation(classified)
        if result.get("control_transfer_validated_at") is not None:
            result["control_transfer_validated_at"] = _iso_ms(cutoff)
        result.update(evidence_scope="ARCHIVED_RESEARCH_OBSERVATIONS", temporal_verification="VERIFIED",
            candidate_formed_at_ms=candidate["formed_at_ms"], evaluated_at_ms=cutoff,
            candidate_observation={k:v for k,v in original.items() if k != "archive_root"},
            followup_observation={k:v for k,v in later.items() if k != "archive_root"} if later else None,
            followup_measurements=followup_measurements,
            frozen_reference_hash=candidate["reference_hash"],
            causal_source_independence="NOT_PROVEN",
            classification_quality="ANALYST_JUDGMENT_NOT_MACHINE_PROVEN",
            forecast_claim="NONE")
        # Ignore refreshed evaluation clocks for deduplication; retain first result.
        immutable = {k:v for k,v in result.items() if k != "evaluated_at_ms"}
        observation_store.record_research_event(assessment_id, "control_transfer_assessment", immutable)
        return result
    except (ValueError, KeyError, TypeError, OverflowError, OSError) as exc:
        return _blocked(str(exc))
