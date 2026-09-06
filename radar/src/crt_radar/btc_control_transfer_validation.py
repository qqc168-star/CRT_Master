from __future__ import annotations

from typing import Any


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


def evaluate_control_transfer_validation(
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
