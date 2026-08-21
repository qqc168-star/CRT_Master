from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "CRT_STRC_STRATEGY_REVIEW_V0.1"
STRATEGY_SCHEMA_VERSION = "CRT_STRC_Q3Q4_ROLLING_STRATEGY_V0.2"
EXTERNAL_ACTION_AUTHORITY = "NONE"

ISSUER_FACT_TYPES = frozenset(
    {
        "REPURCHASE_CASH_CONSIDERATION",
        "REPURCHASED_SHARES",
        "REPURCHASE_AVG_PRICE",
        "REMAINING_AUTHORIZATION",
        "BTC_NET_FLOW",
        "GROSS_ISSUANCE_RATIO",
        "NET_SHARE_COUNT_CHANGE",
        "LIQUIDATION_PREFERENCE_RETIRED",
        "DISTRIBUTION_RUN_RATE_REMOVED",
    }
)
MARKET_FACT_TYPES = frozenset(
    {
        "OPEN_MARKET_PARTICIPATION",
        "FIXED_WINDOW_RETURN",
        "BTC_EXCESS_RETURN",
        "VOLUME_MULTIPLE",
    }
)


class StrcStrategyContextError(ValueError):
    """Raised when the STRC research-only strategy context is invalid or unsafe."""


def default_strc_strategy_context_path() -> Path:
    return Path(__file__).resolve().parents[2] / "research" / "CRT_STRC_Q3Q4_ROLLING_STRATEGY_V0.2.json"


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise StrcStrategyContextError(f"{field} missing or invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StrcStrategyContextError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise StrcStrategyContextError(f"{field} must be finite")
    if positive and result <= 0:
        raise StrcStrategyContextError(f"{field} must be positive")
    return result


def _weighted_tranches(rows: Any, field: str, price_field: str) -> float:
    if not isinstance(rows, list) or len(rows) != 3:
        raise StrcStrategyContextError(f"{field} must contain exactly three tranches")
    weight_sum = 0.0
    weighted_price = 0.0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise StrcStrategyContextError(f"{field}[{index}] must be an object")
        weight = _number(row.get("weight"), f"{field}[{index}].weight", positive=True)
        price = _number(row.get(price_field), f"{field}[{index}].{price_field}", positive=True)
        weight_sum += weight
        weighted_price += weight * price
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise StrcStrategyContextError(f"{field} weights must sum to 1")
    return weighted_price


def validate_strc_strategy_context(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StrcStrategyContextError("strategy context must be an object")
    if payload.get("schema_version") != STRATEGY_SCHEMA_VERSION:
        raise StrcStrategyContextError(f"schema_version must be {STRATEGY_SCHEMA_VERSION}")
    if payload.get("artifact_status") != "USER_APPROVED":
        raise StrcStrategyContextError("artifact_status must be USER_APPROVED")
    if payload.get("strategy_status") != "ACTIVE_STRATEGY_HYPOTHESIS":
        raise StrcStrategyContextError("strategy_status must be ACTIVE_STRATEGY_HYPOTHESIS")
    if payload.get("formal_model_status") != "NON_FORMAL":
        raise StrcStrategyContextError("formal_model_status must remain NON_FORMAL")

    authority = payload.get("authority")
    if not isinstance(authority, dict):
        raise StrcStrategyContextError("authority must be an object")
    if authority.get("production") != "NOT_APPROVED":
        raise StrcStrategyContextError("authority.production must remain NOT_APPROVED")
    if authority.get("external_action_authority") != EXTERNAL_ACTION_AUTHORITY:
        raise StrcStrategyContextError("external_action_authority must remain NONE")
    if authority.get("external_action_performed") is not False:
        raise StrcStrategyContextError("external_action_performed must be false")
    if authority.get("action_output") != "NONE":
        raise StrcStrategyContextError("action_output must remain NONE")

    weighted_sell = _weighted_tranches(
        payload.get("q3_sell_tranches"),
        "q3_sell_tranches",
        "target_price_usd",
    )
    weighted_reentry = _weighted_tranches(
        payload.get("q4_reentry_tranches"),
        "q4_reentry_tranches",
        "max_price_usd",
    )
    declared_sell = _number(
        payload.get("target_weighted_sell_price_usd"),
        "target_weighted_sell_price_usd",
        positive=True,
    )
    declared_reentry = _number(
        payload.get("target_weighted_reentry_price_usd"),
        "target_weighted_reentry_price_usd",
        positive=True,
    )
    if not math.isclose(weighted_sell, declared_sell, rel_tol=0.0, abs_tol=0.01):
        raise StrcStrategyContextError("declared weighted sell price does not match tranches")
    if not math.isclose(weighted_reentry, declared_reentry, rel_tol=0.0, abs_tol=0.01):
        raise StrcStrategyContextError("declared weighted reentry price does not match tranches")

    spread = payload.get("net_spread_contract")
    if not isinstance(spread, dict):
        raise StrcStrategyContextError("net_spread_contract must be an object")
    if spread.get("formula") != "G_net = S - B - D - C":
        raise StrcStrategyContextError("net_spread_contract formula is not the approved STRC contract")
    spread_floor = _number(
        spread.get("minimum_usd_per_share"),
        "net_spread_contract.minimum_usd_per_share",
        positive=True,
    )

    guideposts = payload.get("analyst_guideposts")
    if not isinstance(guideposts, dict) or guideposts.get("formal_threshold") is not False:
        raise StrcStrategyContextError("analyst guideposts must remain explicitly non-formal")

    gross_gap = declared_sell - declared_reentry
    budget = gross_gap - spread_floor
    if budget < 0:
        raise StrcStrategyContextError("reference gross gap is below the approved net spread floor")

    result = deepcopy(payload)
    result["derived"] = {
        "weighted_q3_sell_price_usd": round(weighted_sell, 4),
        "weighted_q4_reentry_price_usd": round(weighted_reentry, 4),
        "reference_gross_gap_usd_per_share": round(gross_gap, 4),
        "max_distribution_plus_friction_budget_usd_per_share": round(budget, 4),
        "net_spread_floor_usd_per_share": round(spread_floor, 4),
    }
    return result


def load_strc_strategy_context(path: str | Path | None = None) -> dict[str, Any]:
    target = default_strc_strategy_context_path() if path is None else Path(path)
    if not target.exists():
        return {
            "state": "BLOCKED",
            "reason": "STRC_STRATEGY_CONTEXT_MISSING",
            "path": str(target),
            "action_output": "NONE",
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
            "external_action_performed": False,
        }
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
        context = validate_strc_strategy_context(payload)
    except (OSError, json.JSONDecodeError, StrcStrategyContextError) as exc:
        return {
            "state": "BLOCKED",
            "reason": "STRC_STRATEGY_CONTEXT_INVALID",
            "error": f"{type(exc).__name__}: {exc}",
            "path": str(target),
            "action_output": "NONE",
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
            "external_action_performed": False,
        }
    return {
        "state": "AVAILABLE",
        "path": str(target),
        "context": context,
        "action_output": "NONE",
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
    }


def _blocked(reason: str, *, strategy_context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "BLOCKED",
        "reason": reason,
        "strategy_context_state": strategy_context.get("state") if isinstance(strategy_context, dict) else None,
        "reference_spread": None,
        "issuer_evidence": {"state": "BLOCKED", "items": []},
        "market_handoff_evidence": {"state": "BLOCKED", "items": []},
        "guidepost_evaluation": {
            "state": "BLOCKED",
            "reason": "VERIFIED_ISSUER_AND_MARKET_EVIDENCE_REQUIRED",
        },
        "action_output": "NONE",
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
        "capital_decision_authority": "USER_ONLY",
        "analyst_judgment_required": True,
    }


def _fact_subset(asset_facts: dict[str, Any], fact_types: frozenset[str]) -> list[dict[str, Any]]:
    rows = asset_facts.get("items")
    if not isinstance(rows, list):
        return []
    return [
        deepcopy(row)
        for row in rows
        if isinstance(row, dict) and row.get("fact_type") in fact_types
    ]


def build_strc_strategy_review(
    strategy_context: dict[str, Any] | None,
    reflexivity_overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(strategy_context, dict) or strategy_context.get("state") != "AVAILABLE":
        reason = "STRC_STRATEGY_CONTEXT_UNAVAILABLE"
        if isinstance(strategy_context, dict):
            reason = str(strategy_context.get("reason", reason))
        return _blocked(reason, strategy_context=strategy_context)

    context = strategy_context.get("context")
    if not isinstance(context, dict):
        return _blocked("STRC_STRATEGY_CONTEXT_PAYLOAD_MISSING", strategy_context=strategy_context)

    try:
        context = validate_strc_strategy_context(context)
    except StrcStrategyContextError as exc:
        result = _blocked("STRC_STRATEGY_CONTEXT_INVALID_AT_REVIEW", strategy_context=strategy_context)
        result["error"] = str(exc)
        return result

    if not isinstance(reflexivity_overlay, dict):
        return _blocked("REFLEXIVITY_OVERLAY_UNAVAILABLE", strategy_context=strategy_context)

    asset_facts = reflexivity_overlay.get("asset_facts")
    events = reflexivity_overlay.get("decision_relevant_events")
    blockers = reflexivity_overlay.get("blockers")
    if not isinstance(asset_facts, dict) or not isinstance(events, dict) or not isinstance(blockers, dict):
        return _blocked("REFLEXIVITY_OVERLAY_SURFACE_INVALID", strategy_context=strategy_context)

    issuer_items = _fact_subset(asset_facts, ISSUER_FACT_TYPES)
    market_items = _fact_subset(asset_facts, MARKET_FACT_TYPES)
    blocker_items = blockers.get("items") if isinstance(blockers.get("items"), list) else []
    blocker_codes = sorted(
        {
            str(item.get("reason_code"))
            for item in blocker_items
            if isinstance(item, dict) and item.get("reason_code")
        }
    )

    if issuer_items:
        issuer_state = "AVAILABLE"
    elif asset_facts.get("section_state") == "READY" and asset_facts.get("empty_reason") == "VERIFIED_NO_MATCH":
        issuer_state = "VERIFIED_NO_MATCH"
    else:
        issuer_state = "BLOCKED"

    market_state = "AVAILABLE" if market_items else "BLOCKED"
    if not issuer_items and blocker_items:
        state = "BLOCKED"
    elif blocker_items or asset_facts.get("section_state") != "READY" or events.get("section_state") != "READY":
        state = "PARTIAL_FOR_ANALYST"
    else:
        state = "READY_FOR_ANALYST"

    derived = context["derived"]
    reference_spread = {
        "weighted_q3_sell_price_usd": derived["weighted_q3_sell_price_usd"],
        "weighted_q4_reentry_price_usd": derived["weighted_q4_reentry_price_usd"],
        "reference_gross_gap_usd_per_share": derived["reference_gross_gap_usd_per_share"],
        "net_spread_floor_usd_per_share": derived["net_spread_floor_usd_per_share"],
        "max_distribution_plus_friction_budget_usd_per_share": derived[
            "max_distribution_plus_friction_budget_usd_per_share"
        ],
        "status": "REFERENCE_ONLY",
        "note": "No BUY/SELL action is produced; realized execution prices and opportunity cost remain user/GPT judgment inputs.",
    }

    guidepost_state = "READY_FOR_GPT_JUDGMENT" if issuer_items and market_items else "BLOCKED"
    guidepost_reason = (
        "VERIFIED_ISSUER_AND_MARKET_EVIDENCE_AVAILABLE"
        if guidepost_state == "READY_FOR_GPT_JUDGMENT"
        else "VERIFIED_MARKET_REACTION_EVIDENCE_REQUIRED"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "strategy_context_state": "AVAILABLE",
        "strategy_schema_version": context["schema_version"],
        "strategy_status": context["strategy_status"],
        "formal_model_status": context["formal_model_status"],
        "reference_spread": reference_spread,
        "issuer_evidence": {
            "state": issuer_state,
            "items": issuer_items,
        },
        "market_handoff_evidence": {
            "state": market_state,
            "items": market_items,
            "reason": None if market_items else "CURRENT_REFLEXIVITY_MARKET_EVIDENCE_NOT_AVAILABLE",
        },
        "decision_relevant_events": deepcopy(events.get("items", [])) if isinstance(events.get("items"), list) else [],
        "reflexivity_blocker_codes": blocker_codes,
        "guidepost_evaluation": {
            "state": guidepost_state,
            "reason": guidepost_reason,
            "formal_threshold": False,
            "automatic_trade_signal": False,
        },
        "action_output": "NONE",
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
        "capital_decision_authority": "USER_ONLY",
        "analyst_judgment_required": True,
    }
