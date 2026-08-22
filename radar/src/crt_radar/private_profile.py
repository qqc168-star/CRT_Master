from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "CRT_PRIVATE_PORTFOLIO_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"

CAPITAL_STATE_CONTRACT_VERSION = "CRT_CAPITAL_STATE_V0.1"
CAPITAL_STATE_SOURCE = "USER_CONFIRMED"

CAPITAL_STATE_SECTION_NAMES = (
    "capital_state",
    "holdings",
    "cash",
    "asset_roles",
    "plans",
)

PLAN_SIDES = {"BUY", "SELL", "WAIT"}
PLAN_STATUSES = {"ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"}
TRANCHE_STATUSES = {
    "PENDING",
    "USER_CONFIRMED_EXECUTED",
    "PAUSED",
    "CANCELLED",
}
CONDITION_OPERATORS = {"LT", "LTE", "GT", "GTE", "EQ", "NE"}


class PrivateProfileError(ValueError):
    """Raised when the local-only portfolio profile is missing or unsafe."""


def default_private_profile_path() -> Path:
    return Path.home() / "CRT_Runtime" / "private" / "portfolio.json"


def _finite(value: Any, field: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise PrivateProfileError(f"{field} missing or invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PrivateProfileError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise PrivateProfileError(f"{field} must be finite")
    if positive and number <= 0:
        raise PrivateProfileError(f"{field} must be positive")
    if nonnegative and number < 0:
        raise PrivateProfileError(f"{field} must be nonnegative")
    return number


def _validate_weighted_tranches(rows: Any, field: str, *, price_field: str) -> tuple[list[dict[str, float]], float]:
    if not isinstance(rows, list) or len(rows) != 3:
        raise PrivateProfileError(f"{field} must contain exactly three tranches")
    result: list[dict[str, float]] = []
    weight_sum = 0.0
    weighted_price = 0.0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PrivateProfileError(f"{field}[{index}] must be an object")
        weight = _finite(row.get("weight"), f"{field}[{index}].weight", positive=True)
        price = _finite(row.get(price_field), f"{field}[{index}].{price_field}", positive=True)
        weight_sum += weight
        weighted_price += weight * price
        result.append({"weight": weight, price_field: price})
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise PrivateProfileError(f"{field} weights must sum to 1")
    return result, weighted_price


def _validate_strc_tactical_strategy(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise PrivateProfileError("strc.tactical_strategy must be an object")
    if payload.get("strategy_status") != "ACTIVE_STRATEGY_HYPOTHESIS":
        raise PrivateProfileError("strc.tactical_strategy.strategy_status must be ACTIVE_STRATEGY_HYPOTHESIS")
    if payload.get("formal_model_status") != "NON_FORMAL":
        raise PrivateProfileError("strc.tactical_strategy.formal_model_status must be NON_FORMAL")
    q3_rows, weighted_sell = _validate_weighted_tranches(
        payload.get("q3_sell_tranches"),
        "strc.tactical_strategy.q3_sell_tranches",
        price_field="target_price_usd",
    )
    q4_rows, weighted_reentry = _validate_weighted_tranches(
        payload.get("q4_reentry_tranches"),
        "strc.tactical_strategy.q4_reentry_tranches",
        price_field="max_price_usd",
    )
    spread_floor = _finite(
        payload.get("net_spread_floor_usd"),
        "strc.tactical_strategy.net_spread_floor_usd",
        positive=True,
    )
    result = json.loads(json.dumps(payload))
    result["q3_sell_tranches"] = q3_rows
    result["q4_reentry_tranches"] = q4_rows
    result["derived"] = {
        "weighted_q3_sell_price_usd": round(weighted_sell, 4),
        "weighted_q4_reentry_price_usd": round(weighted_reentry, 4),
        "net_spread_floor_usd": spread_floor,
    }
    return result



def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrivateProfileError(f"{field} must be a non-empty string")
    return value.strip()


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PrivateProfileError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise PrivateProfileError(f"{field} must include timezone information")
    return text


def _asset_symbol(value: Any, field: str) -> str:
    symbol = _text(value, field).upper()
    if any(char.isspace() for char in symbol):
        raise PrivateProfileError(f"{field} must not contain whitespace")
    return symbol


def _validate_condition(payload: Any, field: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PrivateProfileError(f"{field} must be an object")

    condition_field = _text(payload.get("field"), f"{field}.field")
    operator = _text(payload.get("operator"), f"{field}.operator").upper()

    if operator not in CONDITION_OPERATORS:
        raise PrivateProfileError(
            f"{field}.operator must be one of {sorted(CONDITION_OPERATORS)}"
        )

    value = payload.get("value")

    if operator in {"LT", "LTE", "GT", "GTE"}:
        normalized_value: Any = _finite(value, f"{field}.value")
    elif isinstance(value, bool):
        normalized_value = value
    elif isinstance(value, (int, float)):
        normalized_value = _finite(value, f"{field}.value")
    elif isinstance(value, str) and value.strip():
        normalized_value = value.strip()
    else:
        raise PrivateProfileError(
            f"{field}.value must be a finite number, boolean, or non-empty string"
        )

    result = json.loads(json.dumps(payload))
    result["field"] = condition_field
    result["operator"] = operator
    result["value"] = normalized_value
    return result


def _validate_capital_state_contract(
    payload: dict[str, Any],
    *,
    strc_shares: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    present = {
        name: name in payload
        for name in CAPITAL_STATE_SECTION_NAMES
    }

    if not any(present.values()):
        return None, {
            "state": "BLOCKED",
            "reason": "CAPITAL_STATE_MISSING",
            "contract_version": CAPITAL_STATE_CONTRACT_VERSION,
        }

    missing = [
        name
        for name, is_present in present.items()
        if not is_present
    ]

    if missing:
        raise PrivateProfileError(
            "capital state sections must be supplied together; "
            f"missing={','.join(missing)}"
        )

    meta = payload.get("capital_state")
    if not isinstance(meta, dict):
        raise PrivateProfileError("capital_state must be an object")

    contract_version = _text(
        meta.get("contract_version"),
        "capital_state.contract_version",
    )
    if contract_version != CAPITAL_STATE_CONTRACT_VERSION:
        raise PrivateProfileError(
            f"capital_state.contract_version must be "
            f"{CAPITAL_STATE_CONTRACT_VERSION}"
        )

    source = _text(meta.get("source"), "capital_state.source")
    if source != CAPITAL_STATE_SOURCE:
        raise PrivateProfileError(
            f"capital_state.source must be {CAPITAL_STATE_SOURCE}"
        )

    as_of = _timestamp(meta.get("as_of"), "capital_state.as_of")

    base_currency = _text(
        meta.get("base_currency"),
        "capital_state.base_currency",
    ).upper()
    if base_currency != "USD":
        raise PrivateProfileError(
            "capital_state.base_currency must be USD"
        )

    holdings_raw = payload.get("holdings")
    if not isinstance(holdings_raw, list):
        raise PrivateProfileError("holdings must be a list")

    holdings: list[dict[str, Any]] = []
    holding_assets: set[str] = set()
    holding_quantity_by_asset: dict[str, float] = {}

    for index, row in enumerate(holdings_raw):
        field = f"holdings[{index}]"

        if not isinstance(row, dict):
            raise PrivateProfileError(f"{field} must be an object")

        asset = _asset_symbol(row.get("asset"), f"{field}.asset")

        if asset in holding_assets:
            raise PrivateProfileError(
                f"duplicate holding asset: {asset}"
            )

        quantity = _finite(
            row.get("quantity"),
            f"{field}.quantity",
            nonnegative=True,
        )

        normalized = json.loads(json.dumps(row))
        normalized["asset"] = asset
        normalized["quantity"] = quantity

        holdings.append(normalized)
        holding_assets.add(asset)
        holding_quantity_by_asset[asset] = quantity

    if "STRC" not in holding_quantity_by_asset:
        raise PrivateProfileError(
            "holdings must include STRC while legacy strc.shares remains required"
        )

    if not math.isclose(
        holding_quantity_by_asset["STRC"],
        strc_shares,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise PrivateProfileError(
            "holdings STRC quantity must match legacy strc.shares"
        )

    cash_raw = payload.get("cash")
    if not isinstance(cash_raw, dict):
        raise PrivateProfileError("cash must be an object")

    available_usd = _finite(
        cash_raw.get("available_usd"),
        "cash.available_usd",
        nonnegative=True,
    )

    reserved_usd = _finite(
        cash_raw.get("reserved_usd", 0.0),
        "cash.reserved_usd",
        nonnegative=True,
    )

    cash = json.loads(json.dumps(cash_raw))
    cash["available_usd"] = available_usd
    cash["reserved_usd"] = reserved_usd

    roles_raw = payload.get("asset_roles")
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise PrivateProfileError(
            "asset_roles must be a non-empty object"
        )

    asset_roles: dict[str, str] = {}

    for raw_asset, raw_role in roles_raw.items():
        asset = _asset_symbol(raw_asset, "asset_roles asset")

        if asset in asset_roles:
            raise PrivateProfileError(
                f"duplicate asset role after normalization: {asset}"
            )

        asset_roles[asset] = _text(
            raw_role,
            f"asset_roles.{asset}",
        )

    plans_raw = payload.get("plans")
    if not isinstance(plans_raw, list):
        raise PrivateProfileError("plans must be a list")

    plans: list[dict[str, Any]] = []
    plan_ids: set[str] = set()
    plan_assets: set[str] = set()

    pending_tranche_count = 0
    pending_budget_usd = 0.0

    for plan_index, plan_raw in enumerate(plans_raw):
        field = f"plans[{plan_index}]"

        if not isinstance(plan_raw, dict):
            raise PrivateProfileError(f"{field} must be an object")

        plan_id = _text(
            plan_raw.get("plan_id"),
            f"{field}.plan_id",
        )

        if plan_id in plan_ids:
            raise PrivateProfileError(
                f"duplicate plan_id: {plan_id}"
            )

        asset = _asset_symbol(
            plan_raw.get("asset"),
            f"{field}.asset",
        )

        side = _text(
            plan_raw.get("side"),
            f"{field}.side",
        ).upper()

        if side not in PLAN_SIDES:
            raise PrivateProfileError(
                f"{field}.side must be one of {sorted(PLAN_SIDES)}"
            )

        status = _text(
            plan_raw.get("status"),
            f"{field}.status",
        ).upper()

        if status not in PLAN_STATUSES:
            raise PrivateProfileError(
                f"{field}.status must be one of {sorted(PLAN_STATUSES)}"
            )

        tranches_raw = plan_raw.get("tranches")

        if not isinstance(tranches_raw, list) or len(tranches_raw) != 3:
            raise PrivateProfileError(
                f"{field}.tranches must contain exactly three tranches"
            )

        tranche_ids: set[str] = set()
        tranches: list[dict[str, Any]] = []

        for tranche_index, tranche_raw in enumerate(tranches_raw):
            tranche_field = (
                f"{field}.tranches[{tranche_index}]"
            )

            if not isinstance(tranche_raw, dict):
                raise PrivateProfileError(
                    f"{tranche_field} must be an object"
                )

            tranche_id = _text(
                tranche_raw.get("tranche_id"),
                f"{tranche_field}.tranche_id",
            )

            if tranche_id in tranche_ids:
                raise PrivateProfileError(
                    f"duplicate tranche_id in {plan_id}: {tranche_id}"
                )

            budget_usd = _finite(
                tranche_raw.get("budget_usd"),
                f"{tranche_field}.budget_usd",
                positive=True,
            )

            tranche_status = _text(
                tranche_raw.get("status"),
                f"{tranche_field}.status",
            ).upper()

            if tranche_status not in TRANCHE_STATUSES:
                raise PrivateProfileError(
                    f"{tranche_field}.status must be one of "
                    f"{sorted(TRANCHE_STATUSES)}"
                )

            conditions_raw = tranche_raw.get(
                "validity_conditions"
            )

            if (
                not isinstance(conditions_raw, list)
                or not conditions_raw
            ):
                raise PrivateProfileError(
                    f"{tranche_field}.validity_conditions "
                    "must be a non-empty list"
                )

            conditions = [
                _validate_condition(
                    condition,
                    f"{tranche_field}.validity_conditions[{condition_index}]",
                )
                for condition_index, condition in enumerate(
                    conditions_raw
                )
            ]

            tranche = json.loads(json.dumps(tranche_raw))
            tranche["tranche_id"] = tranche_id
            tranche["budget_usd"] = budget_usd
            tranche["status"] = tranche_status
            tranche["validity_conditions"] = conditions

            if tranche_status == "PENDING":
                pending_tranche_count += 1
                pending_budget_usd += budget_usd

            tranches.append(tranche)
            tranche_ids.add(tranche_id)

        plan = json.loads(json.dumps(plan_raw))
        plan["plan_id"] = plan_id
        plan["asset"] = asset
        plan["side"] = side
        plan["status"] = status
        plan["tranches"] = tranches

        plans.append(plan)
        plan_ids.add(plan_id)
        plan_assets.add(asset)

    referenced_assets = holding_assets | plan_assets
    missing_roles = sorted(
        referenced_assets - set(asset_roles)
    )

    if missing_roles:
        raise PrivateProfileError(
            "asset_roles missing referenced assets: "
            + ",".join(missing_roles)
        )

    capital_state = json.loads(json.dumps(meta))
    capital_state["contract_version"] = contract_version
    capital_state["source"] = source
    capital_state["as_of"] = as_of
    capital_state["base_currency"] = base_currency

    sections = {
        "capital_state": capital_state,
        "holdings": holdings,
        "cash": cash,
        "asset_roles": asset_roles,
        "plans": plans,
    }

    status = {
        "state": "AVAILABLE",
        "reason": "USER_CONFIRMED_CAPITAL_STATE_VALID",
        "contract_version": contract_version,
        "as_of": as_of,
        "holding_count": len(holdings),
        "plan_count": len(plans),
        "pending_tranche_count": pending_tranche_count,
        "pending_budget_usd": round(pending_budget_usd, 2),
        "available_cash_usd": round(available_usd, 2),
        "reserved_cash_usd": round(reserved_usd, 2),
        "execution_authority": "USER_ONLY",
    }

    return sections, status

def validate_private_profile(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PrivateProfileError("private profile must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise PrivateProfileError(f"schema_version must be {SCHEMA_VERSION}")
    if payload.get("external_action_authority") != EXTERNAL_ACTION_AUTHORITY:
        raise PrivateProfileError("external_action_authority must remain NONE")
    if payload.get("external_action_performed") is not False:
        raise PrivateProfileError("external_action_performed must be false")
    if payload.get("action_output") != "NONE":
        raise PrivateProfileError("action_output must be NONE")

    strc = payload.get("strc")
    if not isinstance(strc, dict):
        raise PrivateProfileError("strc must be an object")
    shares = _finite(strc.get("shares"), "strc.shares", positive=True)
    rate = _finite(strc.get("current_annual_distribution_rate"), "strc.current_annual_distribution_rate", positive=True)
    stated_amount = _finite(strc.get("stated_amount_usd"), "strc.stated_amount_usd", positive=True)
    withholding_rate = _finite(strc.get("withholding_rate"), "strc.withholding_rate", nonnegative=True)
    if rate > 1:
        raise PrivateProfileError("strc.current_annual_distribution_rate must be a decimal rate")
    if withholding_rate > 1:
        raise PrivateProfileError("strc.withholding_rate must be a decimal rate")
    if strc.get("distribution_rate_mode") != "DYNAMIC_LOCAL_VALUE":
        raise PrivateProfileError("strc.distribution_rate_mode must be DYNAMIC_LOCAL_VALUE")
    if strc.get("tax_treatment") != "RETURN_OF_CAPITAL":
        raise PrivateProfileError("strc.tax_treatment must be RETURN_OF_CAPITAL")
    tactical_strategy = _validate_strc_tactical_strategy(strc.get("tactical_strategy"))
    capital_state_sections, capital_state_status = _validate_capital_state_contract(
        payload,
        strc_shares=shares,
    )

    goal = payload.get("cash_goal")
    if not isinstance(goal, dict):
        raise PrivateProfileError("cash_goal must be an object")
    target = _finite(goal.get("six_month_target_usd"), "cash_goal.six_month_target_usd", positive=True)
    fixed_minimum = _finite(goal.get("fixed_minimum_shares"), "cash_goal.fixed_minimum_shares", positive=True)

    received_fraction = 1.0 - withholding_rate
    six_month_cash_per_share = stated_amount * rate * 0.5 * received_fraction
    if six_month_cash_per_share <= 0:
        raise PrivateProfileError("six-month cash per share must be positive")
    minimum_shares_for_target = math.ceil(target / six_month_cash_per_share)

    result = json.loads(json.dumps(payload))
    if tactical_strategy is not None:
        result["strc"]["tactical_strategy"] = tactical_strategy
    if capital_state_sections is not None:
        for section_name, section_value in capital_state_sections.items():
            result[section_name] = section_value
    result["capital_state_status"] = capital_state_status
    result["derived"] = {
        "annual_cash_usd": round(shares * stated_amount * rate * received_fraction, 2),
        "six_month_cash_usd": round(shares * six_month_cash_per_share, 2),
        "six_month_cash_per_share_usd": round(six_month_cash_per_share, 4),
        "minimum_shares_for_target": minimum_shares_for_target,
        "configured_fixed_minimum_shares": fixed_minimum,
        "shares_above_configured_minimum": round(shares - fixed_minimum, 4),
        "goal_covered_at_current_rate": shares >= minimum_shares_for_target,
    }
    return result


def load_private_profile(path: str | Path | None = None) -> dict[str, Any]:
    target = default_private_profile_path() if path is None else Path(path)
    if not target.exists():
        return {
            "state": "BLOCKED",
            "reason": "PRIVATE_PROFILE_MISSING",
            "path": str(target),
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
            "external_action_performed": False,
            "action_output": "NONE",
        }
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        validated = validate_private_profile(payload)
    except (OSError, json.JSONDecodeError, PrivateProfileError) as exc:
        return {
            "state": "BLOCKED",
            "reason": "PRIVATE_PROFILE_INVALID",
            "error": f"{type(exc).__name__}: {exc}",
            "path": str(target),
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
            "external_action_performed": False,
            "action_output": "NONE",
        }
    return {
        "state": "AVAILABLE",
        "path": str(target),
        "profile": validated,
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
        "action_output": "NONE",
    }
