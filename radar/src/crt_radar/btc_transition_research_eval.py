from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "CRT_BTC_CONTROL_TRANSFER_EVIDENCE_V0.1"
RESULT_SCHEMA_VERSION = "CRT_BTC_CONTROL_TRANSFER_RESEARCH_EVAL_V0.1"

OBSERVATION_STATES = {
    "CONFIRMED",
    "NOT_CONFIRMED",
    "NOT_OBSERVED",
    "REJECTED",
    "UNAVAILABLE",
}

SEQUENCE = (
    "meaningful_breakout",
    "meaningful_pullback",
    "higher_low",
    "reattack",
    "prior_control_high_break",
)

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
    observations: dict[str, str] | None = None,
) -> dict[str, Any]:
    observations = observations or {}
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "state": state,
        "reason": reason,
        "research_state": research_state,
        "observations": observations,
        "control_transfer_loop_closed": (
            research_state == "CONTROL_TRANSFER_CANDIDATE"
        ),
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


def unavailable_control_transfer_evidence(reason: str) -> dict[str, Any]:
    return _result(
        state="NOT_AVAILABLE",
        reason=reason,
        research_state="TRANSITION_UNRESOLVED",
    )


def _blocked(reason: str) -> dict[str, Any]:
    return _result(
        state="BLOCKED",
        reason=reason,
        research_state="TRANSITION_UNRESOLVED",
    )


def evaluate_control_transfer_evidence(
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate a pre-classified research evidence vector without detecting pivots.

    This function deliberately does not decide whether a price move is
    "meaningful", discover swing points, or create a formal season state. Those
    classifications must arrive as explicit research evidence and remain under
    analyst review.
    """

    if not isinstance(evidence, dict):
        return unavailable_control_transfer_evidence(
            "CONTROL_TRANSFER_EVIDENCE_NOT_AVAILABLE"
        )
    if evidence.get("schema_version") != SCHEMA_VERSION:
        return _blocked("CONTROL_TRANSFER_EVIDENCE_SCHEMA_MISMATCH")

    authority = evidence.get("authority")
    if not isinstance(authority, dict):
        return _blocked("CONTROL_TRANSFER_AUTHORITY_MISSING")
    for field in AUTHORITY_FIELDS:
        if authority.get(field) != "NONE":
            return _blocked(f"CONTROL_TRANSFER_{field.upper()}_MUST_BE_NONE")
    if authority.get("external_action_performed") is not False:
        return _blocked("CONTROL_TRANSFER_EXTERNAL_ACTION_PERFORMED_MUST_BE_FALSE")

    raw_observations = evidence.get("observations")
    if not isinstance(raw_observations, dict):
        return _blocked("CONTROL_TRANSFER_OBSERVATIONS_MISSING")

    observations: dict[str, str] = {}
    for field in SEQUENCE:
        value = raw_observations.get(field)
        if value not in OBSERVATION_STATES:
            return _blocked(f"CONTROL_TRANSFER_OBSERVATION_INVALID:{field}")
        observations[field] = str(value)

    invalidating_lower_low = raw_observations.get("invalidating_lower_low")
    if invalidating_lower_low not in {
        "OBSERVED",
        "NOT_OBSERVED",
        "UNAVAILABLE",
    }:
        return _blocked(
            "CONTROL_TRANSFER_OBSERVATION_INVALID:invalidating_lower_low"
        )
    observations["invalidating_lower_low"] = str(invalidating_lower_low)

    for index, field in enumerate(SEQUENCE[1:], start=1):
        if observations[field] == "CONFIRMED":
            prerequisite = SEQUENCE[index - 1]
            if observations[prerequisite] != "CONFIRMED":
                return _blocked(
                    "CONTROL_TRANSFER_SEQUENCE_CONTRADICTION:"
                    f"{field}_BEFORE_{prerequisite}"
                )

    invalidating_lower_low = observations["invalidating_lower_low"]
    breakout = observations["meaningful_breakout"]

    if invalidating_lower_low == "OBSERVED":
        if breakout == "CONFIRMED":
            return _result(
                state="READY_FOR_ANALYST",
                reason="POST_BREAKOUT_LOWER_LOW_REJECTED_CONTROL_TRANSFER",
                research_state="FALSE_POSITIVE_REJECTED",
                observations=observations,
            )
        return _result(
            state="READY_FOR_ANALYST",
            reason="LOWER_LOW_WITHOUT_CONFIRMED_CONTROL_TRANSFER_BREAKOUT",
            research_state="BEAR_CONTROL_RETAINED",
            observations=observations,
        )

    if breakout != "CONFIRMED":
        return _result(
            state="READY_FOR_ANALYST",
            reason="MEANINGFUL_BREAKOUT_NOT_CONFIRMED",
            research_state="TRANSITION_UNRESOLVED",
            observations=observations,
        )

    if observations["meaningful_pullback"] != "CONFIRMED":
        return _result(
            state="READY_FOR_ANALYST",
            reason="BREAKOUT_OBSERVED_BUT_DEFENSIVE_PULLBACK_NOT_TESTED",
            research_state="ATTACK_STRENGTHENED_DEFENSE_PENDING",
            observations=observations,
        )

    if observations["higher_low"] != "CONFIRMED":
        return _result(
            state="READY_FOR_ANALYST",
            reason="PULLBACK_OBSERVED_BUT_HIGHER_LOW_NOT_CONFIRMED",
            research_state="DEFENSE_UNRESOLVED",
            observations=observations,
        )

    if (
        observations["reattack"] != "CONFIRMED"
        or observations["prior_control_high_break"] != "CONFIRMED"
    ):
        return _result(
            state="READY_FOR_ANALYST",
            reason="HIGHER_LOW_HELD_BUT_REATTACK_CONTROL_BREAK_PENDING",
            research_state="DEFENSE_HELD_REATTACK_PENDING",
            observations=observations,
        )

    return _result(
        state="READY_FOR_ANALYST",
        reason="BREAKOUT_PULLBACK_HIGHER_LOW_REATTACK_LOOP_CLOSED",
        research_state="CONTROL_TRANSFER_CANDIDATE",
        observations=observations,
    )
