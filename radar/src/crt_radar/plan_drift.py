from __future__ import annotations

import math
from typing import Any


SUPPORTED_OPERATORS = {
    "LT",
    "LTE",
    "GT",
    "GTE",
    "EQ",
    "NE",
}


def _authority() -> dict[str, Any]:
    return {
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }


def _market_candidates(
    layers: dict[str, Any],
    field: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    if not isinstance(layers, dict):
        return candidates

    for layer_name in sorted(layers):
        layer = layers.get(layer_name)

        if not isinstance(layer, dict):
            continue

        metrics = layer.get("metrics")

        if not isinstance(metrics, dict):
            continue

        metric = metrics.get(field)

        if not isinstance(metric, dict):
            continue

        candidates.append(
            {
                "source_kind": "MARKET_METRIC",
                "source_path": (
                    f"layers.{layer_name}.metrics.{field}.value"
                ),
                "value": metric.get("value"),
            }
        )

    return candidates


def resolve_condition_source(
    *,
    field: str,
    profile: dict[str, Any],
    layers: dict[str, Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    capital_state = profile.get("capital_state")

    if (
        isinstance(capital_state, dict)
        and field in capital_state
    ):
        candidates.append(
            {
                "source_kind": "CAPITAL_STATE",
                "source_path": (
                    f"private_context.profile.capital_state.{field}"
                ),
                "value": capital_state[field],
            }
        )

    candidates.extend(
        _market_candidates(
            layers,
            field,
        )
    )

    if not candidates:
        return {
            "state": "UNBOUND",
            "candidates": [],
        }

    if len(candidates) > 1:
        return {
            "state": "AMBIGUOUS",
            "candidates": candidates,
        }

    candidate = candidates[0]

    return {
        "state": "BOUND",
        "source_kind": candidate["source_kind"],
        "source_path": candidate["source_path"],
        "value": candidate["value"],
        "candidates": candidates,
    }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def evaluate_condition(
    *,
    current: Any,
    operator: str,
    target: Any,
) -> str:
    operator = str(operator).upper()

    if operator not in SUPPORTED_OPERATORS:
        return "BLOCKED_OPERATOR_UNSUPPORTED"

    if operator == "EQ":
        return "SATISFIED" if current == target else "VIOLATED"

    if operator == "NE":
        return "SATISFIED" if current != target else "VIOLATED"

    left = _finite_number(current)
    right = _finite_number(target)

    if left is None or right is None:
        return "BLOCKED_NOT_COMPARABLE"

    if operator == "LT":
        matched = left < right
    elif operator == "LTE":
        matched = left <= right
    elif operator == "GT":
        matched = left > right
    else:
        matched = left >= right

    return "SATISFIED" if matched else "VIOLATED"


def evaluate_plan_drift(
    *,
    private_context: dict[str, Any] | None,
    layers: dict[str, Any],
) -> dict[str, Any]:
    base = _authority()

    if (
        not isinstance(private_context, dict)
        or private_context.get("state") != "AVAILABLE"
    ):
        return {
            **base,
            "state": "BLOCKED",
            "reason": "PRIVATE_CONTEXT_UNAVAILABLE",
            "reanalysis_required": None,
            "active_plan_count": 0,
            "pending_tranche_count": 0,
            "condition_count": 0,
            "satisfied_condition_count": 0,
            "violated_condition_count": 0,
            "blocked_condition_count": 0,
            "plans": [],
        }

    profile = private_context.get("profile")

    if not isinstance(profile, dict):
        return {
            **base,
            "state": "BLOCKED",
            "reason": "PRIVATE_PROFILE_UNAVAILABLE",
            "reanalysis_required": None,
            "active_plan_count": 0,
            "pending_tranche_count": 0,
            "condition_count": 0,
            "satisfied_condition_count": 0,
            "violated_condition_count": 0,
            "blocked_condition_count": 0,
            "plans": [],
        }

    active_plans = [
        plan
        for plan in profile.get("plans", [])
        if (
            isinstance(plan, dict)
            and plan.get("status") == "ACTIVE"
        )
    ]

    if not active_plans:
        return {
            **base,
            "state": "NO_ACTIVE_PLAN",
            "reason": "NO_ACTIVE_CAPITAL_PLAN",
            "reanalysis_required": False,
            "active_plan_count": 0,
            "pending_tranche_count": 0,
            "condition_count": 0,
            "satisfied_condition_count": 0,
            "violated_condition_count": 0,
            "blocked_condition_count": 0,
            "plans": [],
        }

    plan_results: list[dict[str, Any]] = []

    pending_total = 0
    condition_total = 0
    satisfied_total = 0
    violated_total = 0
    blocked_total = 0

    for plan in active_plans:
        plan_pending = 0
        plan_satisfied = 0
        plan_violated = 0
        plan_blocked = 0
        condition_results: list[dict[str, Any]] = []

        for tranche in plan.get("tranches", []):
            if not isinstance(tranche, dict):
                continue

            if tranche.get("status") != "PENDING":
                continue

            plan_pending += 1
            pending_total += 1

            for condition in tranche.get(
                "validity_conditions",
                [],
            ):
                if not isinstance(condition, dict):
                    continue

                condition_total += 1

                field = str(condition.get("field"))
                operator = str(condition.get("operator")).upper()
                target = condition.get("value")

                source = resolve_condition_source(
                    field=field,
                    profile=profile,
                    layers=layers,
                )

                result: dict[str, Any] = {
                    "tranche_id": tranche.get("tranche_id"),
                    "field": field,
                    "operator": operator,
                    "target_value": target,
                    "source_state": source["state"],
                }

                if source["state"] == "UNBOUND":
                    evaluation = "BLOCKED_UNBOUND_SOURCE"

                elif source["state"] == "AMBIGUOUS":
                    evaluation = "BLOCKED_AMBIGUOUS_SOURCE"
                    result["source_candidates"] = source["candidates"]

                else:
                    result["source_kind"] = source["source_kind"]
                    result["source_path"] = source["source_path"]
                    result["current_value"] = source["value"]

                    evaluation = evaluate_condition(
                        current=source["value"],
                        operator=operator,
                        target=target,
                    )

                result["evaluation"] = evaluation

                if evaluation == "SATISFIED":
                    satisfied_total += 1
                    plan_satisfied += 1

                elif evaluation == "VIOLATED":
                    violated_total += 1
                    plan_violated += 1

                else:
                    blocked_total += 1
                    plan_blocked += 1

                condition_results.append(result)

        if plan_violated > 0:
            plan_state = "DRIFT_DETECTED"
            plan_reanalysis: bool | None = True

        elif plan_blocked > 0:
            plan_state = "BLOCKED"
            plan_reanalysis = None

        else:
            plan_state = "VALID"
            plan_reanalysis = False

        plan_results.append(
            {
                "plan_id": plan.get("plan_id"),
                "asset": plan.get("asset"),
                "side": plan.get("side"),
                "state": plan_state,
                "reanalysis_required": plan_reanalysis,
                "pending_tranche_count": plan_pending,
                "satisfied_condition_count": plan_satisfied,
                "violated_condition_count": plan_violated,
                "blocked_condition_count": plan_blocked,
                "conditions": condition_results,
            }
        )

    if condition_total == 0:
        state = "BLOCKED"
        reason = "ACTIVE_PLAN_HAS_NO_EVALUABLE_CONDITIONS"
        reanalysis_required: bool | None = None

    elif violated_total > 0:
        state = "REANALYSIS_REQUIRED"
        reason = "ACTIVE_PLAN_CONDITION_VIOLATED"
        reanalysis_required = True

    elif blocked_total > 0:
        state = "BLOCKED"
        reason = "ACTIVE_PLAN_CONDITION_EVALUATION_BLOCKED"
        reanalysis_required = None

    else:
        state = "STABLE"
        reason = "ACTIVE_PLAN_CONDITIONS_SATISFIED"
        reanalysis_required = False

    return {
        **base,
        "state": state,
        "reason": reason,
        "reanalysis_required": reanalysis_required,
        "active_plan_count": len(active_plans),
        "pending_tranche_count": pending_total,
        "condition_count": condition_total,
        "satisfied_condition_count": satisfied_total,
        "violated_condition_count": violated_total,
        "blocked_condition_count": blocked_total,
        "plans": plan_results,
    }
