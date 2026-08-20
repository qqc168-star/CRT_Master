from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "CRT_ASSUMPTION_BOUNDARY_WATCH_V0.1"
CONTEXT_SCHEMA_VERSION = "CRT_ASSUMPTION_RESEARCH_CONTEXT_V0.1"


def default_assumption_watch_context_path() -> Path:
    return Path.home() / "CRT_Runtime" / "private" / "assumption_watch_research.json"


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "BLOCKED",
        "reason": reason,
        "assumptions": [],
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "formal_model_modification_authority": "NONE",
        "analyst_review_required": True,
    }


def load_assumption_watch_context(
    path: str | Path | None = None,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    target = default_assumption_watch_context_path() if path is None else Path(path)
    if not target.exists():
        return {"state": "BLOCKED", "reason": "ASSUMPTION_RESEARCH_CONTEXT_MISSING", "path": str(target)}
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "state": "BLOCKED",
            "reason": f"ASSUMPTION_RESEARCH_CONTEXT_INVALID:{type(exc).__name__}",
            "path": str(target),
        }
    if not isinstance(payload, dict):
        return {"state": "BLOCKED", "reason": "ASSUMPTION_RESEARCH_CONTEXT_NOT_OBJECT", "path": str(target)}
    if payload.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        return {"state": "BLOCKED", "reason": "ASSUMPTION_RESEARCH_CONTEXT_SCHEMA_MISMATCH", "path": str(target)}
    if payload.get("formal_model_modification_authority") != "NONE":
        return {"state": "BLOCKED", "reason": "FORMAL_MODEL_MODIFICATION_AUTHORITY_MUST_BE_NONE", "path": str(target)}
    if payload.get("external_action_authority") != "NONE":
        return {"state": "BLOCKED", "reason": "ASSUMPTION_EXTERNAL_ACTION_AUTHORITY_MUST_BE_NONE", "path": str(target)}
    valid_until_ms = payload.get("valid_until_ms")
    if not isinstance(valid_until_ms, int):
        return {"state": "BLOCKED", "reason": "ASSUMPTION_CONTEXT_VALID_UNTIL_INVALID", "path": str(target)}
    as_of_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if as_of_ms > valid_until_ms:
        return {"state": "BLOCKED", "reason": "ASSUMPTION_RESEARCH_CONTEXT_EXPIRED", "path": str(target)}
    return {"state": "AVAILABLE", "path": str(target), "context": payload}


def evaluate_assumption_watch(
    *,
    btc_entry_gate: dict[str, Any] | None,
    research_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(research_context, dict) or research_context.get("state") != "AVAILABLE":
        reason = "ASSUMPTION_RESEARCH_CONTEXT_UNAVAILABLE"
        if isinstance(research_context, dict):
            reason = str(research_context.get("reason", reason))
        return _blocked(reason)

    context = research_context.get("context")
    if not isinstance(context, dict):
        return _blocked("ASSUMPTION_RESEARCH_CONTEXT_PAYLOAD_MISSING")

    gate = btc_entry_gate if isinstance(btc_entry_gate, dict) else {}
    gate_state = str(gate.get("state", "BLOCKED"))
    transition_state = str(gate.get("transition_state", "TRANSITION_UNRESOLVED"))
    decision_eligibility = str(gate.get("decision_eligibility", "WAIT"))
    mechanism = gate.get("mechanism_support") if isinstance(gate.get("mechanism_support"), dict) else {}
    corridor = gate.get("research_corridor") if isinstance(gate.get("research_corridor"), dict) else {}

    assumptions: list[dict[str, Any]] = []

    # Governance/boundary invariant: an event corridor must never become a formal threshold by inference.
    corridor_status = "VALID"
    corridor_reason = "EVENT_CORRIDOR_REMAINS_RESEARCH_ONLY"
    if corridor and corridor.get("formal_threshold_authority") != "NONE":
        corridor_status = "BLOCKED"
        corridor_reason = "EVENT_CORRIDOR_FORMAL_AUTHORITY_VIOLATION"
    assumptions.append(
        {
            "id": "EVENT_CORRIDOR_IS_RESEARCH_ONLY",
            "kind": "BOUNDARY",
            "status": corridor_status,
            "evidence": corridor_reason,
            "response": "BLOCK_FORMAL_PROMOTION" if corridor_status != "VALID" else "NO_CHANGE",
        }
    )

    # Decision invariant: price/200D alone must not create probe eligibility.
    constructive = bool(mechanism.get("constructive"))
    price_only_status = "VALID"
    price_only_reason = "ENTRY_ELIGIBILITY_NOT_PROMOTED_BY_PRICE_ONLY"
    if decision_eligibility == "PROBE_ELIGIBLE" and not constructive:
        price_only_status = "CHALLENGED"
        price_only_reason = "PROBE_ELIGIBLE_WITHOUT_CONSTRUCTIVE_MECHANISM"
    assumptions.append(
        {
            "id": "PRICE_ONLY_CANNOT_PROMOTE_ENTRY",
            "kind": "DECISION_BOUNDARY",
            "status": price_only_status,
            "evidence": price_only_reason,
            "response": "FORCE_WAIT_AND_ANALYST_REVIEW" if price_only_status == "CHALLENGED" else "NO_CHANGE",
        }
    )

    # User strategy hypothesis is local/private and never a formal model assumption.
    strategy = context.get("btc_q4_lower_entry_hypothesis")
    if isinstance(strategy, dict) and strategy.get("state") == "ACTIVE_RESEARCH_HYPOTHESIS":
        target = strategy.get("reference_target_usd")
        status = "VALID"
        evidence = "TRANSITION_NOT_DECISIVE_AGAINST_LOWER_ENTRY_HYPOTHESIS"
        response = "KEEP_CONDITIONAL"
        if transition_state == "BULL_ACCEPTANCE_STRENGTHENED":
            status = "CHALLENGED"
            evidence = "BULL_ACCEPTANCE_STRENGTHENED_AT_CURRENT_TRANSITION_CORRIDOR"
            response = "DOWNGRADE_FROM_BASE_CASE_TO_CONDITIONAL"
        elif transition_state == "BEAR_REJECTION_STRENGTHENED":
            evidence = "BEAR_REJECTION_STRENGTHENED_AT_CURRENT_TRANSITION_CORRIDOR"
            response = "KEEP_OR_RESTORE_AS_ACTIVE_CONDITIONAL"
        elif gate_state == "BLOCKED":
            status = "BLOCKED"
            evidence = str(gate.get("reason", "BTC_ENTRY_GATE_BLOCKED"))
            response = "DO_NOT_UPDATE_STRATEGY_HYPOTHESIS"
        assumptions.append(
            {
                "id": "BTC_Q4_LOWER_ENTRY_HYPOTHESIS",
                "kind": "USER_STRATEGY_HYPOTHESIS",
                "status": status,
                "reference_target_usd": target,
                "evidence": evidence,
                "response": response,
                "formal_model_authority": "NONE",
            }
        )

    overall = "VALID"
    if any(row["status"] == "BLOCKED" for row in assumptions):
        overall = "BLOCKED"
    elif any(row["status"] == "CHALLENGED" for row in assumptions):
        overall = "CHALLENGED"

    return {
        "schema_version": SCHEMA_VERSION,
        "state": overall,
        "btc_transition_state": transition_state,
        "assumptions": assumptions,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "formal_model_modification_authority": "NONE",
        "analyst_review_required": overall != "VALID",
    }
