"""Research-only posture translation; deliberately disconnected from runtime.

Work A measurements require analyst classification and the existing research
evaluator before reaching this boundary. Candidates are never capital eligibility.
No capital state or plan binding is accepted, so this module cannot assert an
existing scout, invalidate a plan, or authorize an independent tactical deployment.
"""

from __future__ import annotations

from typing import Any

from .btc_transition_research_eval import (
    AUTHORITY_FIELDS,
    RESULT_SCHEMA_VERSION,
    SCHEMA_VERSION as EVIDENCE_SCHEMA_VERSION,
    evaluate_control_transfer_evidence,
)


SCHEMA_VERSION = "CRT_DEPLOYMENT_POSTURE_RESEARCH_GATE_V0.1"

_POSTURES = {
    "TRANSITION_UNRESOLVED": ("NONE", "NO_UPGRADE_FROM_TRANSITION_RESEARCH"),
    "ATTACK_STRENGTHENED_DEFENSE_PENDING": ("SCOUT", "REVIEW_CANDIDATE"),
    "DEFENSE_UNRESOLVED": ("SCOUT", "HOLD_OR_REVIEW_ONLY_NO_UPGRADE"),
    "DEFENSE_HELD_REATTACK_PENDING": ("BRIDGEHEAD", "REVIEW_CANDIDATE"),
    "CONTROL_TRANSFER_CANDIDATE": (
        "REINFORCEMENT", "REVIEW_CANDIDATE_TRANSITION_PREREQUISITE_MET"
    ),
    "FALSE_POSITIVE_REJECTED": ("NONE", "FREEZE_UPGRADES_AND_REANALYZE"),
    "BEAR_CONTROL_RETAINED": ("NONE", "BLOCK_TRANSITION_JUSTIFIED_UPGRADE"),
}

# These are requirements for downstream review, never checks passed by this gate.
_DOWNSTREAM_GATES = (
    "EXISTING_BTC_DECISION_SUPPORT",
    "QUALIFIED_COMMANDER_ATTACK_AND_DEFENSE_LINES",
    "LATEST_CAPITAL_STATE",
    "ACTIVE_CAPITAL_PLAN_AND_AVAILABLE_TRANCHE",
    "BULL_FOUNDATION",
    "INDEPENDENT_EVIDENCE",
    "ASSET_ROLE_INTEGRITY",
    "DECISION_ASYMMETRY",
    "ASSET_SPECIFIC_FACTS",
    "GPT_ANALYST_JUDGMENT",
    "USER_DECISION",
)


def _result(
    reason: str, research_state: str | None = None
) -> dict[str, Any]:
    candidate, effect = _POSTURES.get(
        research_state, ("NONE", "POSTURE_TRANSLATION_BLOCKED")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "state": (
            "POSTURE_TRANSLATION_BLOCKED"
            if research_state is None else "READY_FOR_ANALYST"
        ),
        "reason": reason,
        "research_state": research_state,
        "scope": "TRANSITION_RESEARCH_ONLY",
        "eligibility_level": "RESEARCH_POSTURE_CANDIDATE",
        "posture_candidate": candidate,
        "posture_effect": effect,
        "required_downstream_gates": list(_DOWNSTREAM_GATES),
        "final_eligibility": "NOT_DETERMINED",
        "plan_invalidation": "UNRESOLVED",
        "formal_season": None,
        **{field: "NONE" for field in AUTHORITY_FIELDS},
        "action_output": "NONE",
        "external_action_performed": False,
        "capital_decision_authority": "USER_ONLY",
        "machine_execution": "FORBIDDEN",
        "machine_may_execute_trade": False,
        "machine_may_determine_btc_season": False,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
        "production": "NOT_APPROVED",
    }


def translate_research_state_to_posture_constraints(
    research_evaluation: object,
) -> dict[str, Any]:
    """Translate a canonical V0.1 evaluator result into review constraints.

    Fail closed on malformed, unavailable, contradictory or authority-bearing
    input. Reuse the existing evaluator solely to check the supplied classified
    observations against its result; do not infer classifications from price data.
    Unknown fields fail closed as schema extensions, including attempted plan or
    eligibility overrides. HOLD_OR_REVIEW is a review constraint, not HOLD_SCOUT:
    downstream must bind current posture, plan ID/SHA, tranche and drift/invalidation.
    """
    if not isinstance(research_evaluation, dict):
        return _result("RESEARCH_EVALUATION_NOT_OBJECT")
    if research_evaluation.get("schema_version") != RESULT_SCHEMA_VERSION:
        return _result("RESEARCH_EVALUATION_SCHEMA_MISMATCH")
    if research_evaluation.get("state") != "READY_FOR_ANALYST":
        return _result("RESEARCH_EVALUATION_NOT_READY")

    for field in (*AUTHORITY_FIELDS, "action_output"):
        if research_evaluation.get(field) != "NONE":
            return _result(f"AUTHORITY_VIOLATION:{field}")
    for field, expected in (
        ("formal_season", None),
        ("external_action_performed", False),
        ("machine_may_determine_btc_season", False),
        ("machine_may_confirm_bull_transition", False),
        ("analyst_judgment_required", True),
    ):
        if field not in research_evaluation or research_evaluation[field] is not expected:
            return _result(f"AUTHORITY_VIOLATION:{field}")

    research_state = research_evaluation.get("research_state")
    if not isinstance(research_state, str) or research_state not in _POSTURES:
        return _result("UNKNOWN_RESEARCH_STATE")
    if research_evaluation.get("control_transfer_loop_closed") is not (
        research_state == "CONTROL_TRANSFER_CANDIDATE"
    ):
        return _result("CONTROL_TRANSFER_LOOP_CONTRADICTION")

    observations = research_evaluation.get("observations")
    if not isinstance(observations, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in observations.items()
    ):
        return _result("INVALID_CLASSIFIED_OBSERVATIONS")
    canonical = evaluate_control_transfer_evidence({
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "authority": {
            **{field: "NONE" for field in AUTHORITY_FIELDS},
            "external_action_performed": False,
        },
        "observations": observations,
    })
    if canonical != research_evaluation:
        return _result("RESEARCH_EVALUATION_CONTRACT_MISMATCH")
    return _result("RESEARCH_POSTURE_REQUIRES_DOWNSTREAM_REVIEW", research_state)
