from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "CRT_PRIVATE_PORTFOLIO_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"


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
