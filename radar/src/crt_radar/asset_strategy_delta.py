from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "CRT_ASSET_STRATEGY_DELTA_V0.1"


def _private_profile(private_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(private_context, dict) or private_context.get("state") != "AVAILABLE":
        return None
    profile = private_context.get("profile")
    return profile if isinstance(profile, dict) else None


def build_asset_strategy_delta(
    *,
    btc_entry_gate: dict[str, Any] | None,
    assumption_watch: dict[str, Any] | None,
    private_context: dict[str, Any] | None,
) -> dict[str, Any]:
    gate = btc_entry_gate if isinstance(btc_entry_gate, dict) else {}
    transition = str(gate.get("transition_state", "TRANSITION_UNRESOLVED"))
    eligibility = str(gate.get("decision_eligibility", "WAIT"))
    watch = assumption_watch if isinstance(assumption_watch, dict) else {}
    profile = _private_profile(private_context)

    btc_delta = "KEEP_WAIT"
    if eligibility == "PROBE_ELIGIBLE":
        btc_delta = "STRENGTHEN_TO_PROBE_ELIGIBLE"
    elif transition.startswith("BEAR_REJECTION"):
        btc_delta = "WEAKEN_GROWTH_ENTRY"
    elif transition.startswith("BULL_ACCEPTANCE"):
        btc_delta = "STRENGTHEN_WATCH"

    income = {
        "state": "BLOCKED",
        "six_month_target_usd": None,
        "six_month_cash_usd": None,
        "coverage_ratio": None,
        "goal_covered": None,
        "reason": "PRIVATE_PROFILE_UNAVAILABLE",
    }
    if profile is not None:
        goal = profile.get("cash_goal") if isinstance(profile.get("cash_goal"), dict) else {}
        derived = profile.get("derived") if isinstance(profile.get("derived"), dict) else {}
        target = goal.get("six_month_target_usd")
        cash = derived.get("six_month_cash_usd")
        covered = derived.get("goal_covered_at_current_rate")
        if isinstance(target, (int, float)) and target > 0 and isinstance(cash, (int, float)):
            income = {
                "state": "AVAILABLE",
                "six_month_target_usd": float(target),
                "six_month_cash_usd": float(cash),
                "coverage_ratio": float(cash) / float(target),
                "goal_covered": bool(covered),
                "reason": "PRIVATE_PROFILE_DERIVED_CASH_FLOW",
            }

    strc_delta = "BLOCKED_INCOME_PROFILE"
    sata_delta = "BLOCKED_INCOME_PROFILE"
    if income["state"] == "AVAILABLE":
        if income["goal_covered"]:
            strc_delta = "KEEP_INCOME_CORE"
            sata_delta = "WAIT_AS_INCOME_BACKUP"
        else:
            strc_delta = "INCOME_GAP_REVIEW"
            sata_delta = "INCOME_BACKUP_REVIEW"

    # Growth engines inherit BTC direction, but asset-specific gates remain fail-closed.
    mstr_direction = "WAIT"
    asst_direction = "WAIT"
    if eligibility == "PROBE_ELIGIBLE":
        mstr_direction = "DIRECTION_STRENGTHENED_BUT_BLOCKED"
        asst_direction = "DIRECTION_STRENGTHENED_BUT_BLOCKED"
    elif transition.startswith("BEAR_REJECTION"):
        mstr_direction = "WEAKEN"
        asst_direction = "WEAKEN"
    elif transition.startswith("BULL_ACCEPTANCE"):
        mstr_direction = "WATCH_STRENGTHENED"
        asst_direction = "WATCH_STRENGTHENED"

    return {
        "schema_version": SCHEMA_VERSION,
        "state": "READY_FOR_ANALYST" if gate else "BLOCKED",
        "btc_transition_state": transition,
        "btc_decision_eligibility": eligibility,
        "assumption_watch_state": watch.get("state"),
        "income_engine": income,
        "assets": {
            "BTC": {
                "role": "CAPITAL_CORE_DIRECTION",
                "strategy_delta": btc_delta,
                "decision_support": eligibility,
            },
            "STRC": {
                "role": "INCOME_ENGINE",
                "strategy_delta": strc_delta,
                "decision_support": "HOLD_REVIEW_ONLY",
                "quantitative": income,
            },
            "SATA": {
                "role": "INCOME_BACKUP",
                "strategy_delta": sata_delta,
                "decision_support": "WAIT_OR_REVIEW_ONLY",
            },
            "MSTR": {
                "role": "GROWTH_ENGINE",
                "strategy_delta": mstr_direction,
                "decision_support": "BLOCKED",
                "blocked_reasons": [
                    "DILUTED_EQUITY_MNAV_NOT_VALIDATED_IN_THIS_SLICE",
                    "SAME_DAY_BTC_HOLDINGS_AND_DILUTED_SHARES_REQUIRED",
                ],
            },
            "ASST": {
                "role": "GROWTH_ENGINE",
                "strategy_delta": asst_direction,
                "decision_support": "BLOCKED",
                "blocked_reasons": [
                    "ISSUER_SHARE_COUNT_ATM_DILUTION_NOT_VALIDATED_IN_THIS_SLICE",
                    "PER_SHARE_BTC_OR_EQUIVALENT_ACCRETION_NOT_VALIDATED",
                ],
            },
        },
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
        "analyst_judgment_required": True,
    }
