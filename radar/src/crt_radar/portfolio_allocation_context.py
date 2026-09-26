
from __future__ import annotations

import math
from datetime import date
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "CRT_PORTFOLIO_ALLOCATION_CONTEXT_V0.1"
HEALTH_SCHEMA_VERSION = "CRT_COMMON_EQUITY_HEALTH_V0.1"
SUPPORTED_ASSETS = ("MSTR", "ASST")
SEASONS = ("WINTER", "SPRING", "SUMMER", "AUTUMN")
DEPLOYMENT_PHASES = ("RESERVE", "SCOUT", "BRIDGEHEAD", "REINFORCEMENT", "TREND_HOLD_HARVEST")
HEALTH_DIRECTIONS = ("IMPROVING", "STABLE", "DETERIORATING", "BLOCKED")
SIDE_JOB_STATES = ("EXECUTE", "SKIP", "EXIT_PENDING", "BLOCKED")

SEASON_POLICY = {
    "WINTER": {"cash_range": (12.0, 15.0), "fixed": 80.0, "growth": 20.0, "mstr": 80.0, "asst": 20.0},
    "SPRING": {"cash_range": (8.0, 10.0), "fixed": 70.0, "growth": 30.0, "mstr": 65.0, "asst": 35.0},
    "SUMMER": {"cash_range": (5.0, 7.0), "fixed": 60.0, "growth": 40.0, "mstr": 55.0, "asst": 45.0},
    "AUTUMN": {"cash_range": (10.0, 15.0), "fixed": 75.0, "growth": 25.0, "mstr": 75.0, "asst": 25.0},
}
SPRING_GROWTH_SPLIT = {
    "EARLY": (70.0, 30.0),
    "CENTER": (65.0, 35.0),
    "MATURE": (60.0, 40.0),
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _finite_required(value: Any, field: str, *, nonnegative: bool = False, positive: bool = False) -> float:
    number = _number(value)
    if number is None:
        raise ValueError(f"{field} must be finite numeric")
    if positive and number <= 0:
        raise ValueError(f"{field} must be positive")
    if nonnegative and number < 0:
        raise ValueError(f"{field} must be nonnegative")
    return number


def _claim_blocked(reason: str) -> dict[str, Any]:
    return {"state": "BLOCKED", "reason": reason, "value": None}


def _asset_facts(pack: dict[str, Any], *, asset: str, fact_type: str | None = None, ct_section: str | None = None) -> list[dict[str, Any]]:
    rows = pack.get("asset_facts", {}).get("items", [])
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get("asset_id") not in {None, asset}:
            continue
        if row.get("asset_id") is None:
            issuer = {"MSTR": "CIK-0001050446", "ASST": "CIK-0001920406"}[asset]
            if row.get("issuer_id") != issuer:
                continue
        if fact_type is not None and row.get("fact_type") != fact_type:
            continue
        if ct_section is not None and row.get("ct_section") != ct_section:
            continue
        result.append(row)
    return result


def _latest_fact(pack: dict[str, Any], *, asset: str, fact_type: str | None = None, ct_section: str | None = None) -> dict[str, Any] | None:
    rows = _asset_facts(pack, asset=asset, fact_type=fact_type, ct_section=ct_section)
    return rows[-1] if rows else None


def _residual_snapshot(
    *,
    asset_engine_snapshot: dict[str, Any] | None,
    burden_snapshot: dict[str, Any] | None,
    residual_input: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(asset_engine_snapshot, dict) or not isinstance(burden_snapshot, dict):
        return _claim_blocked("TREASURY_SNAPSHOT_UNAVAILABLE")
    if not isinstance(residual_input, dict):
        return _claim_blocked("RESIDUAL_VALUE_INPUT_UNAVAILABLE")
    btc = _number(asset_engine_snapshot.get("btc_holdings"))
    shares = _number(asset_engine_snapshot.get("diluted_shares"))
    senior = _number(burden_snapshot.get("senior_claims_usd"))
    usable_liquidity = _number(burden_snapshot.get("usable_liquidity_usd"))
    btc_price = _number(residual_input.get("btc_price_usd"))
    other_liquid = _number(residual_input.get("verified_other_liquid_assets_usd"))
    other_senior = _number(residual_input.get("other_senior_claims_usd"))
    coverage = residual_input.get("coverage_state")
    if coverage != "COMPLETE":
        return _claim_blocked("RESIDUAL_VALUE_COVERAGE_INCOMPLETE")
    if residual_input.get("capital_structure_coherence_state") != "VALIDATED":
        return _claim_blocked("CAPITAL_STRUCTURE_SCENARIO_NOT_VALIDATED")
    scenario_ref = residual_input.get("capital_structure_scenario_ref")
    if not isinstance(scenario_ref, str) or not scenario_ref.strip():
        return _claim_blocked("CAPITAL_STRUCTURE_SCENARIO_REF_MISSING")
    if any(v is None for v in (btc, shares, senior, usable_liquidity, btc_price, other_liquid, other_senior)):
        return _claim_blocked("RESIDUAL_VALUE_INPUT_INCOMPLETE")
    if shares <= 0 or btc_price <= 0 or min(btc, senior, usable_liquidity, other_liquid, other_senior) < 0:
        return _claim_blocked("RESIDUAL_VALUE_INPUT_INVALID")
    value = (btc * btc_price + usable_liquidity + other_liquid - senior - other_senior) / shares
    return {
        "state": "AVAILABLE",
        "reason": "VERIFIED_COMPONENTS_AND_COHERENT_DILUTED_SHARE_BASIS",
        "value": value,
        "components": {
            "btc_holdings": btc,
            "btc_price_usd": btc_price,
            "usable_liquidity_usd": usable_liquidity,
            "verified_other_liquid_assets_usd": other_liquid,
            "senior_claims_usd": senior,
            "other_senior_claims_usd": other_senior,
            "diluted_shares": shares,
            "capital_structure_scenario_ref": scenario_ref.strip(),
        },
    }


def _health_row(pack: dict[str, Any], asset: str, residual_inputs: dict[str, Any] | None) -> dict[str, Any]:
    valuation_fact = _latest_fact(pack, asset=asset, fact_type="TREASURY_VALUATION_CONTEXT")
    per_share_fact = _latest_fact(pack, asset=asset, fact_type="TREASURY_COMPANY_CT", ct_section="per_share_asset_engine")
    burden_fact = _latest_fact(pack, asset=asset, fact_type="TREASURY_COMPANY_CT", ct_section="capital_burden_resilience")
    conversion_fact = _latest_fact(pack, asset=asset, fact_type="TREASURY_COMPANY_CT", ct_section="capital_conversion")

    valuation = valuation_fact.get("evidence") if isinstance(valuation_fact, dict) else {}
    per_share = per_share_fact.get("evidence") if isinstance(per_share_fact, dict) else {}
    burden = burden_fact.get("evidence") if isinstance(burden_fact, dict) else {}
    conversion = conversion_fact.get("evidence") if isinstance(conversion_fact, dict) else {}

    current_asset = per_share.get("current") if isinstance(per_share, dict) else None
    previous_asset = per_share.get("previous") if isinstance(per_share, dict) else None
    current_burden = burden.get("current") if isinstance(burden, dict) else None
    previous_burden = burden.get("previous") if isinstance(burden, dict) else None

    supplied = residual_inputs.get(asset, {}) if isinstance(residual_inputs, dict) else {}
    current_residual = _residual_snapshot(
        asset_engine_snapshot=current_asset,
        burden_snapshot=current_burden,
        residual_input=supplied.get("current") if isinstance(supplied, dict) else None,
    )
    previous_residual = _residual_snapshot(
        asset_engine_snapshot=previous_asset,
        burden_snapshot=previous_burden,
        residual_input=supplied.get("previous") if isinstance(supplied, dict) else None,
    )

    current_bps = valuation.get("current_btc_per_diluted_share") if isinstance(valuation, dict) else None
    bps_change = valuation.get("btc_per_diluted_share_change_pct") if isinstance(valuation, dict) else None
    current_shares = _number((current_asset or {}).get("diluted_shares"))
    previous_shares = _number((previous_asset or {}).get("diluted_shares"))
    diluted_share_change = None
    if current_shares is not None and previous_shares is not None:
        diluted_share_change = current_shares - previous_shares

    def burden_delta(field: str) -> float | None:
        a = _number((current_burden or {}).get(field))
        b = _number((previous_burden or {}).get(field))
        return None if a is None or b is None else a - b

    senior_claim_change = burden_delta("senior_claims_usd")
    annual_carry_change = burden_delta("annual_carry_usd")
    liquidity_change = burden_delta("usable_liquidity_usd")
    cash_coverage_context = None
    if isinstance(current_burden, dict):
        cash_coverage_context = {
            "coverage_basis": current_burden.get("coverage_basis"),
            "carry_coverage_years": current_burden.get("carry_coverage_years"),
            "usable_liquidity_usd": current_burden.get("usable_liquidity_usd"),
        }

    blockers: list[str] = []
    if _number(current_bps) is None:
        blockers.append("BTC_PER_DILUTED_SHARE_UNAVAILABLE")
    if _number(bps_change) is None:
        blockers.append("BTC_PER_DILUTED_SHARE_CHANGE_UNAVAILABLE")
    if diluted_share_change is None:
        blockers.append("DILUTED_SHARE_CHANGE_UNAVAILABLE")
    if senior_claim_change is None:
        blockers.append("SENIOR_CLAIM_CHANGE_UNAVAILABLE")
    if annual_carry_change is None:
        blockers.append("ANNUAL_CARRY_CHANGE_UNAVAILABLE")
    if liquidity_change is None:
        blockers.append("LIQUIDITY_CHANGE_UNAVAILABLE")
    if not isinstance(cash_coverage_context, dict) or _number(cash_coverage_context.get("carry_coverage_years")) is None:
        blockers.append("CASH_COVERAGE_CONTEXT_INCOMPLETE")
    if current_residual["state"] != "AVAILABLE" or previous_residual["state"] != "AVAILABLE":
        blockers.append("NET_RESIDUAL_VALUE_PER_DILUTED_SHARE_UNAVAILABLE")
    residual_change_pct = None
    if not blockers or (
        current_residual["state"] == "AVAILABLE" and previous_residual["state"] == "AVAILABLE"
    ):
        prev = previous_residual["value"]
        if prev != 0:
            residual_change_pct = current_residual["value"] / prev - 1
        else:
            blockers.append("PREVIOUS_RESIDUAL_VALUE_ZERO")

    health_direction = "BLOCKED"
    health_reasons: list[str] = []
    if _number(bps_change) is not None and residual_change_pct is not None:
        if residual_change_pct < 0 or bps_change < 0:
            health_direction = "DETERIORATING"
            if residual_change_pct < 0:
                health_reasons.append("NET_RESIDUAL_VALUE_PER_DILUTED_SHARE_DECREASED")
            if bps_change < 0:
                health_reasons.append("BTC_PER_DILUTED_SHARE_DECREASED")
        elif residual_change_pct > 0 and bps_change > 0:
            health_direction = "IMPROVING"
            health_reasons.extend([
                "NET_RESIDUAL_VALUE_PER_DILUTED_SHARE_INCREASED",
                "BTC_PER_DILUTED_SHARE_INCREASED",
            ])
        else:
            health_direction = "STABLE"
            health_reasons.append("PER_SHARE_VALUE_MIXED_OR_FLAT")
    else:
        health_reasons.append("CRITICAL_HEALTH_COMPARISON_BLOCKED")

    events = []
    if isinstance(conversion, dict) and isinstance(conversion.get("events"), list):
        events = deepcopy(conversion["events"])

    return {
        "schema_version": HEALTH_SCHEMA_VERSION,
        "asset_id": asset,
        "net_residual_value_per_diluted_share": current_residual.get("value"),
        "previous_net_residual_value_per_diluted_share": previous_residual.get("value"),
        "net_residual_value_per_diluted_share_change_pct": residual_change_pct,
        "btc_per_diluted_share": current_bps,
        "btc_per_diluted_share_change_pct": bps_change,
        "diluted_share_change": diluted_share_change,
        "senior_claim_change_usd": senior_claim_change,
        "annual_carry_change_usd": annual_carry_change,
        "liquidity_change_usd": liquidity_change,
        "cash_coverage_context": cash_coverage_context,
        "capital_conversion_evidence": events,
        "health_direction": health_direction,
        "health_reasons": health_reasons,
        "blockers": sorted(set(blockers)),
        "action_output": "NONE",
    }


def build_common_equity_health(pack: dict[str, Any], residual_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(pack, dict):
        raise ValueError("pack must be an object")
    rows = {asset: _health_row(pack, asset, residual_inputs) for asset in SUPPORTED_ASSETS}
    directions = [row["health_direction"] for row in rows.values()]
    aggregate_state = (
        "AVAILABLE" if all(direction != "BLOCKED" for direction in directions)
        else "PARTIAL" if any(direction != "BLOCKED" for direction in directions)
        else "BLOCKED"
    )
    return {
        "schema_version": HEALTH_SCHEMA_VERSION,
        "state": aggregate_state,
        "assets": rows,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
        "machine_execution": "FORBIDDEN",
        "production": "NOT_APPROVED",
    }


def _season_destination(pack: dict[str, Any], season_context: Any) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    if not isinstance(season_context, dict):
        return None, ["SEASON_CONTEXT_MISSING"]
    source = season_context.get("season_source")
    posture = season_context.get("season_posture")
    destination = season_context.get("allocation_destination")
    phase = season_context.get("deployment_phase")
    if phase not in DEPLOYMENT_PHASES:
        blockers.append("DEPLOYMENT_PHASE_INVALID")
    if destination not in SEASONS:
        blockers.append("ALLOCATION_DESTINATION_INVALID")
    if posture not in SEASONS:
        blockers.append("SEASON_POSTURE_INVALID")
    if source == "FORMAL":
        router = pack.get("model_status", {}).get("btc_season_router", {})
        router = router if isinstance(router, dict) else {}
        router_season = router.get("season")
        router_available = (
            router.get("state") == "AVAILABLE"
            and router_season in SEASONS
        )
        if season_context.get("formal_state") != "AVAILABLE" or not router_available:
            blockers.append("FORMAL_SEASON_NOT_AVAILABLE")
        elif posture != router_season:
            blockers.append("FORMAL_SEASON_LINEAGE_MISMATCH")
    elif source == "LABELED_ANALYST_HYPOTHESIS":
        if season_context.get("analyst_hypothesis_evidence_state") != "INDEPENDENTLY_EVIDENCED":
            blockers.append("ANALYST_HYPOTHESIS_NOT_INDEPENDENTLY_EVIDENCED")
    else:
        blockers.append("SEASON_SOURCE_INVALID")
    if blockers:
        return None, blockers
    return {
        "season_source": source,
        "season_posture": posture,
        "allocation_destination": destination,
        "deployment_phase": phase,
        "spring_stage": season_context.get("spring_stage"),
        "severe_stress": season_context.get("severe_stress") is True,
        "extreme_summer_research_candidate": (
            season_context.get("extreme_summer_research_candidate") is True
        ),
        "cash_target_pct": season_context.get("cash_target_pct"),
    }, []

def _target_policy(destination: dict[str, Any]) -> dict[str, Any]:
    season = destination["allocation_destination"]
    policy = deepcopy(SEASON_POLICY[season])
    if season == "SPRING" and destination.get("spring_stage") in SPRING_GROWTH_SPLIT:
        policy["mstr"], policy["asst"] = SPRING_GROWTH_SPLIT[destination["spring_stage"]]
    if season == "SUMMER" and destination.get("extreme_summer_research_candidate"):
        policy["fixed"], policy["growth"] = 55.0, 45.0
        policy["extreme_summer_research_only"] = True
    else:
        policy["extreme_summer_research_only"] = False
    policy["cash_stress_cap"] = 20.0 if destination.get("severe_stress") else policy["cash_range"][1]
    target = _number(destination.get("cash_target_pct"))
    if target is not None:
        lo, hi = policy["cash_range"]
        max_hi = policy["cash_stress_cap"]
        if not (lo <= target <= max_hi):
            raise ValueError("cash_target_pct outside approved range/cap")
        policy["cash_target_pct"] = target
        invested = 100.0 - target
        policy["portfolio_math"] = {
            "cash_pct": target,
            "invested_capital_pct": invested,
            "fixed_income_portfolio_pct": invested * policy["fixed"] / 100.0,
            "growth_portfolio_pct": invested * policy["growth"] / 100.0,
            "mstr_portfolio_pct": invested * policy["growth"] / 100.0 * policy["mstr"] / 100.0,
            "asst_portfolio_pct": invested * policy["growth"] / 100.0 * policy["asst"] / 100.0,
        }
    else:
        policy["cash_target_pct"] = None
        policy["portfolio_math"] = None
    return policy


def _health_tilt(base_mstr: float, base_asst: float, health: dict[str, Any], valuation_constraints: Any, persistent: bool) -> dict[str, Any]:
    assets = health.get("assets", {}) if isinstance(health, dict) else {}
    m = assets.get("MSTR", {}).get("health_direction")
    a = assets.get("ASST", {}).get("health_direction")
    tilt = 0.0
    reason = "NO_RELATIVE_HEALTH_EDGE"
    if m in HEALTH_DIRECTIONS and a in HEALTH_DIRECTIONS and "BLOCKED" not in {m, a}:
        if m == "IMPROVING" and a in {"STABLE", "DETERIORATING"}:
            tilt = 10.0 if persistent and a == "DETERIORATING" else 5.0
            reason = "MSTR_RELATIVE_HEALTH_TILT"
        elif a == "IMPROVING" and m in {"STABLE", "DETERIORATING"}:
            tilt = -10.0 if persistent and m == "DETERIORATING" else -5.0
            reason = "ASST_RELATIVE_HEALTH_TILT"
    constraints = valuation_constraints if isinstance(valuation_constraints, dict) else {}
    if tilt > 0 and constraints.get("MSTR") != "ALLOW_TILT":
        tilt, reason = 0.0, "MSTR_VALUATION_CLEARANCE_REQUIRED"
    if tilt < 0 and constraints.get("ASST") != "ALLOW_TILT":
        tilt, reason = 0.0, "ASST_VALUATION_CLEARANCE_REQUIRED"
    return {
        "health_tilt_pct": tilt,
        "health_tilt_reason": reason,
        "suggested_mstr_pct": base_mstr + tilt,
        "suggested_asst_pct": base_asst - tilt,
        "valuation_constraint": deepcopy(constraints),
    }



def _strategic_btc_context(
    private_context: Any,
    pack: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(private_context, dict)
        or private_context.get("state")
        != "AVAILABLE"
    ):
        return {
            "state": "BLOCKED",
            "reason": (
                "PRIVATE_CAPITAL_STATE_UNAVAILABLE"
            ),
            "action_output": "NONE",
        }

    profile = private_context.get(
        "profile"
    )

    if not isinstance(profile, dict):
        return {
            "state": "BLOCKED",
            "reason": "PRIVATE_PROFILE_UNAVAILABLE",
            "action_output": "NONE",
        }

    strategy = profile.get(
        "btc_strategy"
    )

    if not isinstance(strategy, dict):
        return {
            "state": "BLOCKED",
            "reason": (
                "STRATEGIC_BTC_TARGET_UNAVAILABLE"
            ),
            "action_output": "NONE",
        }

    target = _number(
        strategy.get(
            "strategic_target_btc"
        )
    )

    basis_ref = strategy.get(
        "target_basis_ref"
    )

    if (
        target is None
        or target <= 0
        or not isinstance(
            basis_ref,
            str,
        )
        or not basis_ref.strip()
    ):
        return {
            "state": "BLOCKED",
            "reason": (
                "STRATEGIC_BTC_TARGET_INVALID"
            ),
            "action_output": "NONE",
        }

    holdings = profile.get(
        "holdings"
    )

    if not isinstance(holdings, list):
        return {
            "state": "BLOCKED",
            "reason": (
                "CAPITAL_HOLDINGS_UNAVAILABLE"
            ),
            "action_output": "NONE",
        }

    current_btc = 0.0

    for row in holdings:
        if not isinstance(row, dict):
            continue

        if (
            str(
                row.get("asset", "")
            ).upper()
            != "BTC"
        ):
            continue

        quantity = _number(
            row.get("quantity")
        )

        if (
            quantity is None
            or quantity < 0
        ):
            return {
                "state": "BLOCKED",
                "reason": (
                    "BTC_HOLDING_QUANTITY_INVALID"
                ),
                "action_output": "NONE",
            }

        current_btc += quantity

    gap = max(
        target - current_btc,
        0.0,
    )

    long_horizon = pack.get(
        "btc_long_horizon_context"
    )

    long_horizon_state = (
        long_horizon.get("state")
        if isinstance(
            long_horizon,
            dict,
        )
        else "UNAVAILABLE"
    )

    wait_risk_evidence = []

    if (
        gap > 0
        and long_horizon_state
        == "READY_FOR_ANALYST"
    ):
        wait_risk_evidence.append(
            "BTC_LONG_HORIZON_CONTEXT_AVAILABLE"
        )

    return {
        "state": "READY_FOR_ANALYST",
        "strategic_target_btc": target,
        "current_direct_btc": current_btc,
        "btc_acquisition_gap": gap,
        "target_basis_ref": basis_ref.strip(),
        "long_horizon_context_state": (
            long_horizon_state
        ),
        "acquisition_timing_asymmetry": {
            "wait_risk_evidence": (
                wait_risk_evidence
            ),
            "early_deployment_risk_evidence": [],
            "score": None,
            "analyst_judgment_required": True,
        },
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }


def _btc_acquisition_route_context(
    destination: dict[str, Any] | None,
    strategic: dict[str, Any],
) -> dict[str, Any]:
    if destination is None:
        return {
            "state": "BLOCKED",
            "reason": (
                "SEASON_DESTINATION_UNAVAILABLE"
            ),
            "action_output": "NONE",
        }

    early_deployment_risk = []

    if (
        destination.get(
            "season_posture"
        )
        != "WINTER"
    ):
        early_deployment_risk.append(
            "SEASON_POSTURE_NOT_WINTER"
        )

    gap = _number(
        strategic.get(
            "btc_acquisition_gap"
        )
    )

    if (
        strategic.get("state")
        != "READY_FOR_ANALYST"
    ):
        state = "BLOCKED"
        reason = (
            "STRATEGIC_BTC_CONTEXT_BLOCKED"
        )
    elif gap == 0:
        state = "READY_FOR_ANALYST"
        reason = (
            "STRATEGIC_BTC_TARGET_ALREADY_MET"
        )
    else:
        state = "READY_FOR_ANALYST"
        reason = (
            "CROSS_SEASON_BTC_ACQUISITION_"
            "ROUTE_READY_FOR_ANALYST"
        )

    asymmetry = strategic.get(
        "acquisition_timing_asymmetry"
    )

    wait_risk_evidence = (
        list(
            asymmetry.get(
                "wait_risk_evidence",
                [],
            )
        )
        if isinstance(
            asymmetry,
            dict,
        )
        else []
    )

    return {
        "state": state,
        "reason": reason,
        "harvest_source_assets": [
            "MSTR",
            "ASST",
        ],
        "reserve_purpose": (
            "FUTURE_BTC_ACQUISITION"
        ),
        "reserve_is_capital_purpose_not_second_ledger": (
            True
        ),
        "carrier_candidates": [
            "SATA",
            "STRC",
            "CASH",
        ],
        "carrier_selection_rule": (
            "REVALIDATE_ROLE_HEALTH_LIQUIDITY_"
            "CARRY_AND_RETURNABILITY"
        ),
        "carrier_selection_authority": (
            "ANALYST_AND_USER"
        ),
        "cash_optionality_is_valid_fallback": True,
        "winter_destination_asset": "BTC",
        "staged_acquisition_uses_existing_capital_plan": (
            True
        ),
        "peak_harvest_zone": {
            "analyst_judgment_only": True,
            "machine_peak_tick_detection": False,
            "summer_posture_autumn_destination": (
                destination.get(
                    "season_posture"
                )
                == "SUMMER"
                and destination.get(
                    "allocation_destination"
                )
                == "AUTUMN"
            ),
        },
        "acquisition_timing_asymmetry": {
            "wait_risk_evidence": (
                wait_risk_evidence
            ),
            "early_deployment_risk_evidence": (
                early_deployment_risk
            ),
            "score": None,
            "analyst_judgment_required": True,
        },
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
        "machine_execution": "FORBIDDEN",
    }


def _portfolio_state(private_context: Any, market_prices: Any) -> dict[str, Any]:
    if not isinstance(private_context, dict) or private_context.get("state") != "AVAILABLE":
        return {"state": "BLOCKED", "reason": "CAPITAL_STATE_UNAVAILABLE"}
    profile = private_context.get("profile")
    if not isinstance(profile, dict) or profile.get("capital_state_status", {}).get("state") != "AVAILABLE":
        return {"state": "BLOCKED", "reason": "CAPITAL_STATE_UNAVAILABLE"}
    prices = market_prices if isinstance(market_prices, dict) else {}
    holdings = profile.get("holdings")
    cash = profile.get("cash")
    if not isinstance(holdings, list) or not isinstance(cash, dict):
        return {"state": "BLOCKED", "reason": "CAPITAL_STATE_MALFORMED"}
    fixed = growth = 0.0
    values: dict[str, float] = {}
    strategic_btc_quantity = 0.0
    unknown = []
    for row in holdings:
        if not isinstance(row, dict):
            continue
        asset = str(row.get("asset", "")).upper()
        qty = _number(row.get("quantity"))
        if qty is None or qty < 0:
            unknown.append(asset or "UNKNOWN")
            continue
        if asset in {"STRC", "SATA", "MSTR", "ASST"}:
            px = _number(prices.get(asset))
            if px is None or px <= 0:
                unknown.append(asset)
                continue
            value = qty * px
            values[asset] = value
            if asset in {"STRC", "SATA"}:
                fixed += value
            else:
                growth += value
        elif asset == "BTC":
            strategic_btc_quantity += qty
        elif qty != 0:
            unknown.append(asset)
    available = _number(cash.get("available_usd"))
    reserved = _number(cash.get("reserved_usd", 0.0))
    if available is None or reserved is None or available < 0 or reserved < 0:
        return {"state": "BLOCKED", "reason": "CASH_STATE_INVALID"}
    if unknown:
        return {"state": "BLOCKED", "reason": "UNPRICED_OR_UNCLASSIFIED_HOLDINGS", "assets": sorted(set(unknown))}
    cash_total = available + reserved
    invested = fixed + growth
    total = cash_total + invested
    if total <= 0:
        return {"state": "BLOCKED", "reason": "PORTFOLIO_TOTAL_NONPOSITIVE"}
    result = {
        "state": "AVAILABLE",
        "values_usd": values,
        "cash_usd": cash_total,
        "fixed_income_usd": fixed,
        "growth_usd": growth,
        "total_portfolio_usd": total,
        "cash_portfolio_pct": cash_total / total * 100.0,
        "invested_capital_pct": invested / total * 100.0,
        "fixed_income_bucket_pct": fixed / invested * 100.0 if invested > 0 else None,
        "growth_bucket_pct": growth / invested * 100.0 if invested > 0 else None,
        "mstr_growth_bucket_pct": values.get("MSTR", 0.0) / growth * 100.0 if growth > 0 else None,
        "asst_growth_bucket_pct": values.get("ASST", 0.0) / growth * 100.0 if growth > 0 else None,
        "strategic_btc_quantity": strategic_btc_quantity,
        "strategic_btc_role": "STRATEGIC_CORE",
        "strategic_btc_excluded_from_policy_math": True,
        "allocation_scope": "FIXED_GROWTH_CASH_POLICY_EXCLUDES_STRATEGIC_BTC_CORE",
    }
    return result


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _capital_scope(side_job: dict[str, Any]) -> dict[str, Any]:
    legacy_shares = _number(side_job.get("legacy_strc_inventory_shares"))
    side_job_capital_usd = _number(side_job.get("side_job_capital_usd"))
    side_job_confirmed_shares = _number(side_job.get("side_job_confirmed_strc_shares"))
    state = "AVAILABLE"
    reason = "LEGACY_AND_SIDE_JOB_CAPITAL_SEPARATED"
    if legacy_shares is None or legacy_shares < 0:
        state = "BLOCKED"
        reason = "LEGACY_STRC_INVENTORY_SCOPE_UNAVAILABLE"
    elif (side_job_capital_usd is None or side_job_capital_usd < 0) and (
        side_job_confirmed_shares is None or side_job_confirmed_shares < 0
    ):
        state = "BLOCKED"
        reason = "SIDE_JOB_CAPITAL_SCOPE_UNAVAILABLE"
    return {
        "legacy_strc_inventory_shares": legacy_shares,
        "side_job_capital_usd": side_job_capital_usd,
        "side_job_confirmed_strc_shares": side_job_confirmed_shares,
        "capital_scope_state": state,
        "capital_scope_reason": reason,
    }


def _side_job(side_job: Any) -> dict[str, Any]:
    base = {
        "state": "BLOCKED",
        "fixed_income_carrier": "SATA",
        "return_destination": "SATA",
        "side_job_eligibility": "BLOCKED",
        "action_output": "NONE",
    }
    if not isinstance(side_job, dict):
        return {**base, "reason": "SIDE_JOB_CONTEXT_MISSING"}

    scope = _capital_scope(side_job)
    stage = side_job.get("window_stage")
    if stage not in {"D_MINUS_1", "D", "OUTSIDE_WINDOW", "D_PLUS"}:
        return {**base, **scope, "reason": "SIDE_JOB_STAGE_INVALID"}

    if side_job.get("window_binding_state") != "VALIDATED":
        return {**base, **scope, "reason": "ENTITLEMENT_WINDOW_NOT_VALIDATED", "window_stage": stage}
    basis_ref = side_job.get("window_basis_ref")
    if not isinstance(basis_ref, str) or not basis_ref.strip():
        return {**base, **scope, "reason": "ENTITLEMENT_WINDOW_BASIS_REF_MISSING", "window_stage": stage}

    evaluation_date = _parse_iso_date(side_job.get("evaluation_date"))
    ex_date = _parse_iso_date(side_job.get("strc_ex_date"))
    d1_date = _parse_iso_date(side_job.get("d_minus_1_trade_date"))
    if evaluation_date is None or ex_date is None or d1_date is None or d1_date >= ex_date:
        return {**base, **scope, "reason": "ENTITLEMENT_WINDOW_DATES_INVALID", "window_stage": stage}

    date_match = (
        (stage == "D_MINUS_1" and evaluation_date == d1_date)
        or (stage == "D" and evaluation_date == ex_date)
        or (stage == "D_PLUS" and evaluation_date > ex_date)
        or (stage == "OUTSIDE_WINDOW" and evaluation_date not in {d1_date, ex_date})
    )
    if not date_match:
        return {
            **base,
            **scope,
            "reason": "ENTITLEMENT_WINDOW_STAGE_DATE_MISMATCH",
            "window_stage": stage,
            "evaluation_date": evaluation_date.isoformat(),
            "strc_ex_date": ex_date.isoformat(),
            "d_minus_1_trade_date": d1_date.isoformat(),
            "window_binding_state": "VALIDATED",
            "window_basis_ref": basis_ref.strip(),
        }

    time_fields = {
        "window_stage": stage,
        "evaluation_date": evaluation_date.isoformat(),
        "strc_ex_date": ex_date.isoformat(),
        "d_minus_1_trade_date": d1_date.isoformat(),
        "window_binding_state": "VALIDATED",
        "window_basis_ref": basis_ref.strip(),
    }

    if stage in {"OUTSIDE_WINDOW", "D_PLUS"}:
        return {
            **base,
            **scope,
            **time_fields,
            "state": "SKIP",
            "side_job_eligibility": "SKIP",
            "reason": "OUTSIDE_STRC_ENTITLEMENT_WINDOW",
            "strc_dividend_per_share": _number(side_job.get("strc_dividend_per_share")),
            "sata_daily_distribution": _number(side_job.get("sata_daily_distribution")),
            "d1_entry_price": None,
            "foregone_sata_carry": None,
            "trading_friction_per_share": _number(side_job.get("trading_friction_per_share")),
            "tax_friction_per_share": _number(side_job.get("tax_friction_per_share")),
            "required_edge_per_share": _number(side_job.get("required_edge_per_share")),
            "d_exit_floor": None,
            "analyst_entry_gate_state": None,
            "long_cycle_policy_ref": "CRT_DUAL_HAIRPIN_CAPITAL_ROTATION_MENTAL_MODEL_V0.1",
            "short_cycle_policy": "D_MINUS_1_TO_D_ENTITLEMENT_SIDE_JOB",
            "action_output": "NONE",
        }

    required = (
        "strc_dividend_per_share",
        "sata_daily_distribution",
        "d1_entry_price",
        "trading_friction_per_share",
        "tax_friction_per_share",
        "required_edge_per_share",
    )
    vals = {key: _number(side_job.get(key)) for key in required}
    if any(value is None for value in vals.values()):
        return {**base, **scope, **time_fields, "reason": "SIDE_JOB_INPUT_INCOMPLETE"}
    if (
        vals["strc_dividend_per_share"] <= 0
        or vals["sata_daily_distribution"] < 0
        or vals["d1_entry_price"] <= 0
        or vals["trading_friction_per_share"] < 0
        or vals["tax_friction_per_share"] < 0
        or vals["required_edge_per_share"] < 0
    ):
        return {**base, **scope, **time_fields, "reason": "SIDE_JOB_INPUT_INVALID"}

    foregone_days = side_job.get("foregone_sata_distribution_days", 1)
    if not isinstance(foregone_days, int) or isinstance(foregone_days, bool) or foregone_days < 0:
        return {**base, **scope, **time_fields, "reason": "SIDE_JOB_FOREGONE_DAYS_INVALID"}
    foregone = vals["sata_daily_distribution"] * foregone_days
    exit_floor = (
        vals["d1_entry_price"]
        - vals["strc_dividend_per_share"]
        + foregone
        + vals["trading_friction_per_share"]
        + vals["tax_friction_per_share"]
        + vals["required_edge_per_share"]
    )

    state = "BLOCKED"
    reason = "SIDE_JOB_STAGE_INVALID"
    if stage == "D_MINUS_1":
        analyst_gate = side_job.get("analyst_entry_gate_state")
        if analyst_gate == "PASS":
            state, reason = "EXECUTE", "D_MINUS_1_ANALYST_ENTRY_GATE_PASSES"
        elif analyst_gate == "FAIL":
            state, reason = "SKIP", "D_MINUS_1_ANALYST_ENTRY_GATE_FAILS"
        else:
            state, reason = "BLOCKED", "D_MINUS_1_ANALYST_ENTRY_GATE_UNAVAILABLE"
    elif stage == "D":
        current_bid = _number(side_job.get("current_strc_bid"))
        if (
            side_job.get("entitlement_secured") is not True
            or current_bid is None
            or current_bid <= 0
        ):
            state, reason = "BLOCKED", "D_EXIT_INPUT_INCOMPLETE"
        elif current_bid >= exit_floor:
            state, reason = "EXECUTE", "D_EXIT_FLOOR_MET"
        elif side_job.get("max_hold_boundary_reached") is True:
            state, reason = "EXIT_PENDING", "MAX_HOLD_BOUNDARY_REACHED_HANDOFF_TO_LONG_CYCLE_REVIEW"
        else:
            state, reason = "EXIT_PENDING", "D_EXIT_FLOOR_NOT_YET_MET"

    return {
        **base,
        **scope,
        **time_fields,
        "state": state,
        "side_job_eligibility": state,
        "reason": reason,
        "strc_dividend_per_share": vals["strc_dividend_per_share"],
        "sata_daily_distribution": vals["sata_daily_distribution"],
        "d1_entry_price": vals["d1_entry_price"],
        "foregone_sata_carry": foregone,
        "trading_friction_per_share": vals["trading_friction_per_share"],
        "tax_friction_per_share": vals["tax_friction_per_share"],
        "required_edge_per_share": vals["required_edge_per_share"],
        "d_exit_floor": exit_floor,
        "analyst_entry_gate_state": side_job.get("analyst_entry_gate_state"),
        "long_cycle_policy_ref": "CRT_DUAL_HAIRPIN_CAPITAL_ROTATION_MENTAL_MODEL_V0.1",
        "short_cycle_policy": "D_MINUS_1_TO_D_ENTITLEMENT_SIDE_JOB",
        "action_output": "NONE",
    }

def _valuation_evidence(pack: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for asset in SUPPORTED_ASSETS:
        fact = _latest_fact(pack, asset=asset, fact_type="TREASURY_VALUATION_CONTEXT")
        evidence = fact.get("evidence") if isinstance(fact, dict) else {}
        if not isinstance(evidence, dict):
            evidence = {}
        def claim_value(name: str) -> Any:
            value = evidence.get(name)
            return value.get("value") if isinstance(value, dict) else value
        result[asset] = {
            "diluted_mnav": evidence.get("diluted_mnav"),
            "own_history_empirical_cdf_pct": claim_value("own_history_empirical_cdf_pct"),
            "five_week_mnav_change_pct": claim_value("five_week_mnav_change_pct"),
            "benchmark_empirical_cdf_pct": claim_value("benchmark_empirical_cdf_pct"),
            "formal_action_critical_state": evidence.get("formal_action_critical_state"),
            "evidence_authority": evidence.get("evidence_authority"),
        }
    return result


def build_portfolio_allocation_context(
    *,
    pack: dict[str, Any],
    private_context: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(pack, dict):
        raise ValueError("pack must be an object")
    cfg = inputs if isinstance(inputs, dict) else {}
    health = build_common_equity_health(pack, cfg.get("residual_value_inputs"))
    destination, blockers = _season_destination(pack, cfg.get("season_context"))
    side_job = _side_job(cfg.get("side_job_context"))
    current = _portfolio_state(private_context, cfg.get("market_prices"))
    strategic_btc = _strategic_btc_context(
        private_context,
        pack,
    )
    btc_route = _btc_acquisition_route_context(
        destination,
        strategic_btc,
    )
    if destination is None:
        return {
            "common_equity_health": health,
            "portfolio_allocation_context": {
                "schema_version": SCHEMA_VERSION,
                "state": "BLOCKED",
                "blockers": blockers,
                "side_job": side_job,
                "strategic_btc_context": strategic_btc,
                "btc_acquisition_route_context": btc_route,
                "action_output": "NONE",
                "external_action_authority": "NONE",
                "capital_decision_authority": "USER_ONLY",
                "machine_execution": "FORBIDDEN",
                "production": "NOT_APPROVED",
            },
        }
    policy = _target_policy(destination)
    tilt = _health_tilt(
        policy["mstr"], policy["asst"], health,
        cfg.get("valuation_constraints"),
        cfg.get("persistent_structural_health_difference") is True,
    )
    allocation_drift = None
    if current.get("state") == "AVAILABLE":
        allocation_drift = {
            "cash_portfolio_pct_delta": current["cash_portfolio_pct"] - (policy["cash_target_pct"] if policy["cash_target_pct"] is not None else sum(policy["cash_range"]) / 2.0),
            "fixed_income_bucket_pct_delta": current["fixed_income_bucket_pct"] - policy["fixed"],
            "growth_bucket_pct_delta": current["growth_bucket_pct"] - policy["growth"],
            "mstr_growth_bucket_pct_delta": current["mstr_growth_bucket_pct"] - tilt["suggested_mstr_pct"],
            "asst_growth_bucket_pct_delta": current["asst_growth_bucket_pct"] - tilt["suggested_asst_pct"],
        }
    out = {
        "schema_version": SCHEMA_VERSION,
        "state": "READY_FOR_ANALYST",
        "season_source": destination["season_source"],
        "season_posture": destination["season_posture"],
        "allocation_destination": destination["allocation_destination"],
        "deployment_phase": destination["deployment_phase"],
        "cash_target_range": list(policy["cash_range"]),
        "cash_stress_cap_pct": policy["cash_stress_cap"],
        "cash_target_pct": policy["cash_target_pct"],
        "invested_capital_pct": (
            100.0 - policy["cash_target_pct"] if policy["cash_target_pct"] is not None else None
        ),
        "fixed_income_target_pct": policy["fixed"],
        "growth_target_pct": policy["growth"],
        "mstr_growth_base_pct": policy["mstr"],
        "asst_growth_base_pct": policy["asst"],
        "mstr_health": health["assets"]["MSTR"]["health_direction"],
        "asst_health": health["assets"]["ASST"]["health_direction"],
        **tilt,
        "current_allocation": current,
        "valuation_evidence": _valuation_evidence(pack),
        "allocation_drift": allocation_drift,
        "target_portfolio_math": policy["portfolio_math"],
        "percentage_semantics": {
            "cash_target_range": "portfolio_pct",
            "fixed_income_target_pct": "invested_capital_bucket_pct",
            "growth_target_pct": "invested_capital_bucket_pct",
            "mstr_growth_base_pct": "growth_bucket_pct",
            "asst_growth_base_pct": "growth_bucket_pct",
            "suggested_mstr_pct": "growth_bucket_pct",
            "suggested_asst_pct": "growth_bucket_pct",
        },
        "side_job": side_job,
        "strategic_btc_context": strategic_btc,
        "btc_acquisition_route_context": btc_route,
        "reason": "SEASON_DESTINATION_WITH_HEALTH_AND_VALUATION_CONTEXT",
        "blockers": [],
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
        "machine_execution": "FORBIDDEN",
        "production": "NOT_APPROVED",
    }
    if current.get("state") != "AVAILABLE":
        out["blockers"].append(current.get("reason", "CURRENT_ALLOCATION_UNAVAILABLE"))
    if health["assets"]["MSTR"]["health_direction"] == "BLOCKED":
        out["blockers"].append("MSTR_HEALTH_BLOCKED")
    if health["assets"]["ASST"]["health_direction"] == "BLOCKED":
        out["blockers"].append("ASST_HEALTH_BLOCKED")
    if side_job["state"] == "BLOCKED":
        out["blockers"].append("SIDE_JOB_CONTEXT_BLOCKED")
    if side_job.get("capital_scope_state") == "BLOCKED":
        out["blockers"].append("SIDE_JOB_CAPITAL_SCOPE_BLOCKED")
    return {"common_equity_health": health, "portfolio_allocation_context": out}


def compact_portfolio_allocation_context_for_bridge(pack: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    health = pack.get("common_equity_health")
    if isinstance(health, dict):
        assets = {}
        for asset, row in health.get("assets", {}).items():
            if asset not in SUPPORTED_ASSETS or not isinstance(row, dict):
                continue
            coverage = row.get("cash_coverage_context")
            assets[asset] = {
                "net_residual_value_per_diluted_share": row.get("net_residual_value_per_diluted_share"),
                "net_residual_value_per_diluted_share_change_pct": row.get("net_residual_value_per_diluted_share_change_pct"),
                "btc_per_diluted_share": row.get("btc_per_diluted_share"),
                "btc_per_diluted_share_change_pct": row.get("btc_per_diluted_share_change_pct"),
                "diluted_share_change": row.get("diluted_share_change"),
                "senior_claim_change_usd": row.get("senior_claim_change_usd"),
                "annual_carry_change_usd": row.get("annual_carry_change_usd"),
                "liquidity_change_usd": row.get("liquidity_change_usd"),
                "carry_coverage_years": (
                    coverage.get("carry_coverage_years")
                    if isinstance(coverage, dict) else None
                ),
                "health_direction": row.get("health_direction"),
                "blockers": deepcopy(row.get("blockers", [])),
                "capital_conversion_event_count": (
                    len(row.get("capital_conversion_evidence"))
                    if isinstance(row.get("capital_conversion_evidence"), list)
                    else None
                ),
            }
        result["common_equity_health"] = {
            "schema_version": health.get("schema_version"),
            "state": health.get("state"),
            "assets": assets,
            "action_output": "NONE",
        }

    context = pack.get("portfolio_allocation_context")
    if isinstance(context, dict):
        current = context.get("current_allocation")
        current_summary = None
        if isinstance(current, dict):
            current_summary = {
                key: deepcopy(current.get(key))
                for key in (
                    "state",
                    "reason",
                    "cash_portfolio_pct",
                    "invested_capital_pct",
                    "fixed_income_bucket_pct",
                    "growth_bucket_pct",
                    "mstr_growth_bucket_pct",
                    "asst_growth_bucket_pct",
                    "strategic_btc_quantity",
                    "strategic_btc_role",
                    "strategic_btc_excluded_from_policy_math",
                    "allocation_scope",
                )
                if key in current
            }
        side_job = context.get("side_job")
        side_job_summary = None
        if isinstance(side_job, dict):
            side_job_summary = {
                key: deepcopy(side_job.get(key))
                for key in (
                    "state",
                    "fixed_income_carrier",
                    "return_destination",
                    "side_job_eligibility",
                    "reason",
                    "strc_dividend_per_share",
                    "sata_daily_distribution",
                    "d1_entry_price",
                    "foregone_sata_carry",
                    "trading_friction_per_share",
                    "tax_friction_per_share",
                    "required_edge_per_share",
                    "d_exit_floor",
                    "window_stage",
                    "analyst_entry_gate_state",
                    "legacy_strc_inventory_shares",
                    "side_job_capital_usd",
                    "side_job_confirmed_strc_shares",
                    "capital_scope_state",
                    "capital_scope_reason",
                    "long_cycle_policy_ref",
                    "short_cycle_policy",
                    "action_output",
                )
                if key in side_job
            }
        result["portfolio_allocation_context"] = {
            key: deepcopy(context.get(key))
            for key in (
                "schema_version",
                "state",
                "season_source",
                "season_posture",
                "allocation_destination",
                "deployment_phase",
                "cash_target_range",
                "cash_stress_cap_pct",
                "cash_target_pct",
                "invested_capital_pct",
                "fixed_income_target_pct",
                "growth_target_pct",
                "mstr_growth_base_pct",
                "asst_growth_base_pct",
                "mstr_health",
                "asst_health",
                "health_tilt_pct",
                "health_tilt_reason",
                "valuation_constraint",
                "suggested_mstr_pct",
                "suggested_asst_pct",
                "valuation_evidence",
                "allocation_drift",
                "target_portfolio_math",
                "strategic_btc_context",
                "btc_acquisition_route_context",
                "reason",
                "blockers",
                "action_output",
            )
        }
        result["portfolio_allocation_context"]["current_allocation"] = current_summary
        result["portfolio_allocation_context"]["side_job"] = side_job_summary
    return result
