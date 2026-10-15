
from __future__ import annotations

import math
from datetime import date
from copy import deepcopy
from typing import Any

from .company_health import build_health_dimensions, compact_health_dimensions
from .diluted_equity_mnav import (DENOMINATOR_BASIS, FORMULA_VERSION, SEMANTIC_REF,
                                 validate_diluted_mnav_evidence)
from .treasury_company_ct import validate_pit_replay

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
    "SUMMER": {"cash_range": (5.0, 7.0), "fixed": 55.0, "growth": 45.0, "mstr": 55.0, "asst": 45.0},
    "AUTUMN": {"cash_range": (10.0, 15.0), "fixed": 80.0, "growth": 20.0, "mstr": 75.0, "asst": 25.0},
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
    issuer_id: str,
    as_of_ms: int,
    asset_engine_snapshot: dict[str, Any] | None,
    burden_snapshot: dict[str, Any] | None,
    residual_input: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(asset_engine_snapshot, dict) or not isinstance(burden_snapshot, dict):
        return _claim_blocked("TREASURY_SNAPSHOT_UNAVAILABLE")
    if not isinstance(residual_input, dict):
        return _claim_blocked("RESIDUAL_VALUE_INPUT_UNAVAILABLE")
    if type(as_of_ms) is not int or as_of_ms <= 0:
        return _claim_blocked("RESIDUAL_REPLAY_TIME_UNAVAILABLE")
    # A caller's scenario assertion cannot turn separately valid dates into a
    # single shareholder snapshot, or make future/unverified CT facts visible.
    for snapshot in (asset_engine_snapshot, burden_snapshot):
        validity = validate_pit_replay(
            snapshot, issuer_id=issuer_id, replay_at=as_of_ms, mode="AUDIT_REPLAY"
        )
        if validity["state"] != "AVAILABLE":
            return _claim_blocked("RESIDUAL_SNAPSHOT_NOT_LOCALLY_VALIDATED")
        if not isinstance(snapshot.get("basis_ref"), str) or not snapshot["basis_ref"].strip():
            return _claim_blocked("RESIDUAL_SNAPSHOT_BASIS_MISSING")
    if asset_engine_snapshot["effective_time"] != burden_snapshot["effective_time"]:
        return _claim_blocked("RESIDUAL_SNAPSHOT_EFFECTIVE_TIME_MISMATCH")
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


def _residual_comparable(previous_asset, current_asset, previous_burden, current_burden,
                         previous_input, current_input):
    # Share basis and burden scope are separate economic dimensions. Each must
    # stay comparable over time; their basis strings need not equal each other.
    for previous, current in ((previous_asset, current_asset), (previous_burden, current_burden)):
        if (not isinstance(previous, dict) or not isinstance(current, dict)
                or previous.get("issuer_id") != current.get("issuer_id")
                or previous.get("basis_ref") != current.get("basis_ref")
                or previous.get("source_semantic") != current.get("source_semantic")
                or previous["effective_time"] >= current["effective_time"]):
            return False
    return (previous_input.get("capital_structure_scenario_ref")
            == current_input.get("capital_structure_scenario_ref"))


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

    issuer = {"MSTR": "CIK-0001050446", "ASST": "CIK-0001920406"}[asset]
    supplied = residual_inputs.get(asset, {}) if isinstance(residual_inputs, dict) else {}
    current_input = supplied.get("current") if isinstance(supplied, dict) else None
    previous_input = supplied.get("previous") if isinstance(supplied, dict) else None
    current_residual = _residual_snapshot(
        issuer_id=issuer, as_of_ms=pack.get("generated_at_ms"),
        asset_engine_snapshot=current_asset,
        burden_snapshot=current_burden,
        residual_input=current_input,
    )
    previous_residual = _residual_snapshot(
        issuer_id=issuer, as_of_ms=pack.get("generated_at_ms"),
        asset_engine_snapshot=previous_asset,
        burden_snapshot=previous_burden,
        residual_input=previous_input,
    )

    current_bps = valuation.get("current_btc_per_diluted_share") if isinstance(valuation, dict) else None
    bps_change = valuation.get("btc_per_diluted_share_change_pct") if isinstance(valuation, dict) else None
    # CT asset facts are independently usable when formal valuation is absent.
    # Revalidate local visibility and comparison basis before projecting them.
    def ct_visible(row):
        return (type(pack.get("generated_at_ms")) is int and pack["generated_at_ms"] > 0
            and isinstance(row, dict) and validate_pit_replay(
            row, issuer_id=issuer, replay_at=pack.get("generated_at_ms"),
            mode="AUDIT_REPLAY")["state"] == "AVAILABLE")
    ct_bps = (current_asset.get("btc_per_diluted_share")
              if ct_visible(current_asset) and current_asset.get("basis_ref") else None)
    ct_change = (per_share.get("btc_per_diluted_share_change_pct")
        if ct_visible(current_asset) and ct_visible(previous_asset)
        and current_asset.get("basis_ref") and current_asset["basis_ref"] == previous_asset.get("basis_ref")
        and current_asset["source_semantic"] == previous_asset["source_semantic"]
        and previous_asset["effective_time"] < current_asset["effective_time"] else None)
    bps_conflict = any(_number(a) is not None and _number(b) is not None and a != b
                      for a, b in ((current_bps, ct_bps), (bps_change, ct_change)))
    if bps_conflict:
        current_bps, bps_change = None, None
    else:
        if _number(current_bps) is None:
            current_bps = ct_bps
        if _number(bps_change) is None:
            bps_change = ct_change
    current_shares = _number((current_asset or {}).get("diluted_shares"))
    previous_shares = _number((previous_asset or {}).get("diluted_shares"))
    diluted_share_change = None
    if current_shares is not None and previous_shares is not None:
        diluted_share_change = current_shares - previous_shares

    residual_comparable = (
        current_residual["state"] == previous_residual["state"] == "AVAILABLE"
        and _residual_comparable(previous_asset, current_asset, previous_burden, current_burden,
                                 previous_input, current_input)
    )
    organs = {}
    for section in ("per_share_asset_engine", "funding_engine", "capital_burden_resilience",
                    "capital_conversion", "management_evidence"):
        fact = _latest_fact(pack, asset=asset, fact_type="TREASURY_COMPANY_CT", ct_section=section)
        if isinstance(fact, dict) and isinstance(fact.get("evidence"), dict):
            organs[section] = fact["evidence"]
    residual_delta = (current_residual["value"] - previous_residual["value"]
                      if residual_comparable else None)
    closure = build_health_dimensions(
        organs=organs, issuer_id=issuer, as_of_ms=pack.get("generated_at_ms"),
        residual_change=residual_delta,
    )
    # Legacy and compact fields must use the same qualified comparisons as the
    # health dimensions, not subtract incompatible reported cash/claim totals.
    carry_claims = closure["dimensions"]["senior_claims_carry"]["claims"]
    liquidity_claims = closure["dimensions"]["liquidity_buffer"]["claims"]
    senior_claim_change = carry_claims["senior_claims_usd"]["value"]
    annual_carry_change = carry_claims["annual_carry_usd"]["value"]
    liquidity_change = liquidity_claims["usable_liquidity_usd"]["value"]
    cash_coverage_context = None
    if ct_visible(current_burden) and current_burden.get("cash_usability_basis_ref"):
        cash_coverage_context = {
            "coverage_basis": current_burden.get("coverage_basis"),
            "carry_coverage_years": current_burden.get("carry_coverage_years"),
            "usable_liquidity_usd": current_burden.get("usable_liquidity_usd"),
        }

    blockers: list[str] = ["CT_VALUATION_BTC_SHARE_CONFLICT"] if bps_conflict else []
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
        blockers.extend(row["reason"] for row in (previous_residual, current_residual)
                        if row["state"] != "AVAILABLE")
    if current_residual["state"] == previous_residual["state"] == "AVAILABLE" and not residual_comparable:
        blockers.append("RESIDUAL_VALUE_SCENARIOS_NOT_COMPARABLE")
    residual_change_pct = None
    if residual_comparable:
        prev = previous_residual["value"]
        if prev > 0:
            residual_change_pct = current_residual["value"] / prev - 1
        else:
            # A negative denominator reverses the economic meaning of percent
            # change. Keep verified levels/absolute change for research only.
            blockers.append("PREVIOUS_RESIDUAL_VALUE_ZERO" if prev == 0
                            else "PREVIOUS_RESIDUAL_VALUE_NEGATIVE")

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

    # Opposing verified claims prevent either legacy polarity from driving a
    # relative-health tilt. Unknown claims alone do not establish opposition.
    dimensions = closure["dimensions"].values()
    directions = {d["direction"] for d in dimensions}
    if {"IMPROVING", "DETERIORATING"} <= directions or any(
        d["interpretation_state"] == "MIXED" for d in dimensions
    ):
        health_direction = "BLOCKED"
        health_reasons.append("MULTIDIMENSIONAL_TRADE_OFF_REQUIRES_ANALYST")

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
        "company_health": closure,
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
        "quantitative_inspection": build_quantitative_equity_inspection(pack, residual_inputs),
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
        "machine_execution": "FORBIDDEN",
        "production": "NOT_APPROVED",
    }


def residual_recovery_scenario(*, a_m, a_a, g_m, v_m, v_a, assumption_ref,
                               comparable_scope=False) -> dict:
    """Research sensitivity only. v is price/residual, NEVER formal mNAV.

    The caller describes a scenario, not a verified current financial snapshot.
    Equal investment at inception; distributions, fees and tax are excluded.
    """
    try:
        values = [_number(v) for v in (a_m, a_a, g_m, v_m, v_a)]
    except OverflowError:
        values = [None]
    blocked = {"qualification": "BLOCKED", "catch_up_growth_multiple": None,
               "asst_break_even_growth_multiple": None, "action_output": "NONE"}
    if (comparable_scope is not True or not isinstance(assumption_ref, str) or not assumption_ref.strip()
            or any(v is None or v <= 0 for v in values)):
        return {**blocked, "reason": "POSITIVE_COMPLETE_COMPARABLE_RESIDUAL_SCENARIO_REQUIRED"}
    am, aa, gm, vm, va = values
    try:
        catch_up, break_even = (am / aa) * (vm / va) * gm, 1 / (aa * va)
        m_recovery = am * gm * vm
    except (ZeroDivisionError, OverflowError):
        return {**blocked, "reason": "NONFINITE_SCENARIO"}
    if not all(math.isfinite(v) and v > 0 for v in (catch_up, break_even, m_recovery)):
        return {**blocked, "reason": "NONFINITE_SCENARIO"}
    return {"qualification": "RESEARCH_ONLY", "assumption_ref": assumption_ref,
            "catch_up_growth_multiple": catch_up,
            "asst_break_even_growth_multiple": break_even,
            "mstr_terminal_recovery_per_initial_dollar": m_recovery,
            "asst_return_at_catch_up": m_recovery - 1,
            "asst_positive_return_condition": "G_A > asst_break_even_growth_multiple",
            "formula": "(a_M/a_A)*(v_M/v_A)*G_M", "v_basis": "PRICE_PER_RESIDUAL_NOT_MNAV",
            "limitations": ["ASSUMPTIONS_NOT_CURRENT_FACTS", "NO_DISTRIBUTIONS_FEES_OR_TAX",
                            "NO_ZERO_CROSSING_OR_UNKNOWN_SENIOR_CLAIMS"], "action_output": "NONE"}


def build_quantitative_equity_inspection(pack, residual_inputs=None) -> dict:
    """Read-only numerical view of existing CT/valuation organs, no new model.

    CT levels are research facts, not valuation clearance. Recheck existing PIT
    contracts and retain source clocks; formal mNAV uses its original validator.
    Missing adapters are NOT_RUN, checked but unusable inputs are BLOCKED.
    This full local view is deliberately excluded from the bounded Smoke bridge.
    """
    from .treasury_company_ct import build_treasury_valuation_context, _same_valuation_basis

    as_of = pack.get("generated_at_ms")
    issuers = {"MSTR": "CIK-0001050446", "ASST": "CIK-0001920406"}
    clocks = ("effective_time", "disclosure_time", "first_seen_time", "retrieval_time")
    sources, sections, valuations = {}, {}, {}

    def missing(reason, state="BLOCKED"):
        return {"value": None, "qualification": state, "reason": reason,
                "source_ref": [], "clocks": [], "basis": None}

    def cell(value, records, basis):
        value = _number(value)
        if value is None or not records:
            return missing("NUMERIC_SOURCE_UNAVAILABLE")
        records = [component for r in records for component in
                   ([r] + list(r.get("input_evidence", {}).values()))]
        return {"value": value, "qualification": "RESEARCH_ONLY",
                "reason": "VALIDATED_CT_FACT_NOT_ACTION_CLEARANCE", "basis": basis,
                "source_ref": [r["source_ref"] for r in records],
                "clocks": [{k: r.get(k) for k in clocks} for r in records],
                "raw_sha256": [r.get("raw_sha256", (r.get("source_evidence") or {}).get("raw_sha256"))
                               for r in records]}

    def valid(record, asset):
        return (isinstance(record, dict) and type(as_of) is int and as_of > 0
                and validate_pit_replay(record, issuer_id=issuers[asset], replay_at=as_of,
                                        mode="AUDIT_REPLAY")["state"] == "AVAILABLE")

    def fact(asset, kind, section=None):
        rows = [r for r in _asset_facts(pack, asset=asset, fact_type=kind, ct_section=section)
                if r.get("issuer_id") in (None, issuers[asset])]
        # A second competing organ is not resolved by list order.
        return rows[0].get("evidence", {}) if len(rows) == 1 else {}

    for asset in SUPPORTED_ASSETS:
        sections[asset] = {name: fact(asset, "TREASURY_COMPANY_CT", name) for name in
                           ("per_share_asset_engine", "capital_burden_resilience", "capital_conversion")}
        sources[asset] = fact(asset, "ISSUER_CT_SOURCE_BINDING").get("observations", [])
        valuation = fact(asset, "TREASURY_VALUATION_CONTEXT")
        # The existing context stores normalized observations, not original
        # receipt envelopes. Restore only deterministic aliases/authority fields
        # (as _valuation_evidence already does); all four source components,
        # original clocks and dilution scope still undergo the original checks.
        history = []
        for r in valuation.get("mnav_observations", []):
            if isinstance(r, dict) and r.get("evidence_authority") in {
                    "FORMAL_ACTION_CRITICAL", "RESEARCH_SECONDARY_EVIDENCE"}:
                r = {**r, "asset_nav_usd": r.get("btc_market_value_usd"),
                     "source_class": ("VERIFIED_DETERMINISTIC" if r["evidence_authority"] == "FORMAL_ACTION_CRITICAL"
                                      else "RESEARCH_SECONDARY"),
                     "action_output": "NONE", "external_action_authority": "NONE",
                     "external_action_performed": False}
            history.append(r)
        # Reuse the original history admission/CDF, never trust a copied rank.
        valuations[asset] = build_treasury_valuation_context(asset_id=asset, as_of_ms=as_of,
            mnav_history=history) if type(as_of) is int and as_of > 0 else {}

    def level(asset, section, field, *, label="current"):
        r = sections[asset][section].get(label)
        if field == "usable_liquidity_usd" and (not isinstance(r, dict) or not r.get("cash_usability_basis_ref")):
            return missing("CASH_BALANCE_IS_NOT_VERIFIED_USABLE_LIQUIDITY")
        if valid(r, asset) and r.get("basis_ref") and _number(r.get(field)) is not None:
            return cell(r[field], [r], r["basis_ref"])
        # Preserve narrower, source-bound official components; these never feed
        # residuals/available cash merely because a reported number exists.
        if label == "current":
            reported = [r for r in sources[asset] if valid(r, asset) and _number(r.get(field)) is not None]
            if reported:
                latest = max(r["effective_time"] for r in reported)
                reported = [r for r in reported if r["effective_time"] == latest]
                if len({r[field] for r in reported}) == 1:
                    return cell(reported[0][field], reported, "REPORTED_COMPONENT_ONLY")
        return missing("SOURCE_TIME_BASIS_OR_COMPONENT_UNAVAILABLE")

    def change(asset, field):
        a = level(asset, "per_share_asset_engine", field, label="previous")
        b = level(asset, "per_share_asset_engine", field)
        if (a["value"] is None or b["value"] is None or a["value"] <= 0 or a["basis"] != b["basis"]
                or a["clocks"][-1]["effective_time"] >= b["clocks"][-1]["effective_time"]):
            return missing("COMPARABLE_POSITIVE_HISTORY_REQUIRED")
        r = sections[asset]["per_share_asset_engine"]
        if r["previous"].get("source_semantic") != r["current"].get("source_semantic"):
            return missing("HISTORICAL_SEMANTIC_MISMATCH")
        return cell(100 * (b["value"] / a["value"] - 1), [r["previous"], r["current"]], b["basis"])

    def mnav(asset, metric):
        v = valuations[asset]
        current = v.get("current_observation")
        if not current:
            return missing("FORMAL_MNAV_COMPONENTS_OR_COMPARABLE_HISTORY_UNAVAILABLE")
        value = v.get(metric)
        if isinstance(value, dict):
            value = value.get("value") if value.get("state") == "AVAILABLE" else None
        result = cell(value, [current], current["basis_ref"])
        if result["value"] is not None:
            result["qualification"] = ("QUALIFIED" if v["formal_action_critical_state"] == "AVAILABLE"
                                       else "RESEARCH_ONLY")
            result["reason"] = "ORIGINAL_VALUATION_CONTRACT_RECOMPUTED"
        return result

    def residual(asset):
        a = sections[asset]["per_share_asset_engine"].get("current")
        b = sections[asset]["capital_burden_resilience"].get("current")
        supplied = (residual_inputs or {}).get(asset, {}).get("current")
        result = _residual_snapshot(issuer_id=issuers[asset], as_of_ms=as_of,
            asset_engine_snapshot=a, burden_snapshot=b, residual_input=supplied)
        if result["state"] != "AVAILABLE":
            return missing(result["reason"])
        # Existing scenario assertions alone do not establish full claims or
        # eliminate warrants/convertible double counting. Require bound scenario
        # evidence on the same PIT date before displaying an exact residual.
        if (not b.get("cash_usability_basis_ref") or not valid(supplied, asset)
                or supplied.get("effective_time") != a["effective_time"]
                or supplied.get("basis_ref") != a.get("basis_ref")):
            return missing("SOURCE_BOUND_COHERENT_CAPITAL_STRUCTURE_REQUIRED")
        return cell(result["value"], [a, b, supplied], supplied["capital_structure_scenario_ref"])

    def ratio(asset, numerator, denominator, scale=1):
        a, b = numerator(asset), denominator(asset)
        if (a["value"] is None or b["value"] is None or b["value"] <= 0
                or a["clocks"][-1]["effective_time"] != b["clocks"][-1]["effective_time"]):
            return missing("SAME_DATE_QUALIFIED_COMPONENTS_REQUIRED")
        value = _number(scale * a["value"] / b["value"])
        if value is None:
            return missing("NONFINITE_COMPARISON")
        return {**a, "value": value,
                "basis": a["basis"] + "/" + b["basis"],
                "source_ref": a["source_ref"] + b["source_ref"],
                "clocks": a["clocks"] + b["clocks"],
                "raw_sha256": a.get("raw_sha256", []) + b.get("raw_sha256", [])}

    def price(asset):
        current = valuations[asset].get("current_observation")
        return (cell(current["equity_price_usd"], [current], current["share_basis_ref"])
                if current else missing("ALIGNED_PRICE_UNAVAILABLE"))

    def performance(asset, btc_power=False):
        history = valuations[asset].get("mnav_observations", [])
        if not history:
            return missing("ALIGNED_PRICE_HISTORY_NOT_ANALYSED", "NOT_RUN")
        if (len(history) < 2 or any(not isinstance(r, dict) for r in history)
                or any(not _same_valuation_basis(history[0], r) for r in history[1:])):
            return missing("COMPARABLE_PRICE_ADJUSTMENT_AND_SCOPE_REQUIRED")
        a, b = history[0], history[-1]
        growth = b["equity_price_usd"] / a["equity_price_usd"]
        if btc_power:
            growth /= b["btc_price_usd"] / a["btc_price_usd"]
        result = cell(100 * (growth - 1), [a, b], a["basis_ref"])
        result["reason"] = "PRICE_ONLY_NO_DIVIDENDS_FEES_TAX_NOT_TOTAL_RETURN"
        return result

    def conversion(asset, field):
        events = sections[asset]["capital_conversion"].get("events", [])
        ids = [r.get("event_id") for r in events]
        valid_events = [r for r in events if valid(r, asset) and r.get("active_for_calculation") is True
                        and r.get("consequence_basis_ref") and r.get("event_id")
                        and ids.count(r["event_id"]) == 1]
        if not valid_events:
            return missing("BOUND_ACTIVE_CONVERSION_EVENT_REQUIRED")
        latest = max(r["effective_time"] for r in valid_events)
        selected = [r for r in valid_events if r["effective_time"] == latest]
        if len(selected) != 1:
            return missing("OVERLAPPING_EVENTS_NOT_SUMMED")
        return cell(selected[0].get(field), selected, selected[0]["consequence_basis_ref"])

    def burden(field):
        return lambda asset: level(asset, "capital_burden_resilience", field)

    def asset_level(field):
        return lambda asset: level(asset, "per_share_asset_engine", field)

    specs = [
        ("equity_price_return", "%", "HISTORICAL_PERFORMANCE", lambda a: performance(a)),
        ("btc_purchasing_power_return", "%", "HISTORICAL_PERFORMANCE", lambda a: performance(a, True)),
        ("btc_holdings", "BTC", "PER_SHARE_ASSETS", asset_level("btc_holdings")),
        ("diluted_shares", "shares", "PER_SHARE_ASSETS", asset_level("diluted_shares")),
        ("btc_per_diluted_share", "BTC/share", "PER_SHARE_ASSETS", asset_level("btc_per_diluted_share")),
        ("btc_per_share_growth", "%", "PER_SHARE_ASSETS", lambda a: change(a, "btc_per_diluted_share")),
        ("diluted_share_growth", "%", "PER_SHARE_ASSETS", lambda a: change(a, "diluted_shares")),
        ("diluted_mnav", "x", "FORMAL_VALUATION", lambda a: mnav(a, "diluted_mnav")),
        ("own_history_percentile", "%", "FORMAL_VALUATION", lambda a: mnav(a, "own_history_empirical_cdf_pct")),
        ("residual_per_diluted_share", "USD/share", "SHAREHOLDER_RESIDUAL", residual),
        ("residual_per_dollar", "USD/USD", "SHAREHOLDER_RESIDUAL", lambda a: ratio(a, residual, price)),
        ("raw_btc_exposure_per_10000_usd", "USD", "CAPITAL_COMPETITIVENESS",
         lambda a: ({**mnav(a, "diluted_mnav"), "value": 10000 / mnav(a, "diluted_mnav")["value"]}
                    if mnav(a, "diluted_mnav")["value"] else missing("FORMAL_MNAV_REQUIRED"))),
        ("conversion_amount_not_net_settled", "USD", "FUNDING_EFFICIENCY", lambda a: conversion(a, "amount_usd")),
        ("conversion_new_shares", "shares", "FUNDING_EFFICIENCY", lambda a: conversion(a, "diluted_share_change")),
        ("conversion_btc_change", "BTC", "FUNDING_EFFICIENCY", lambda a: conversion(a, "btc_change")),
        ("debt_principal", "USD", "FINANCING_BURDEN", burden("debt_principal_usd")),
        ("preferred_claims", "USD", "FINANCING_BURDEN", burden("preferred_liquidation_claims_usd")),
        ("annual_carry", "USD/year", "FINANCING_BURDEN", burden("annual_carry_usd")),
        ("usable_cash", "USD", "CASH_HEALTH", burden("usable_liquidity_usd")),
        ("reported_cash", "USD", "CASH_HEALTH", burden("usd_cash_usd")),
        ("designated_reserve", "USD", "CASH_HEALTH", burden("usd_reserve_usd")),
        ("cash_carry_coverage", "years", "CASH_HEALTH",
         lambda a: ratio(a, burden("usable_liquidity_usd"), burden("annual_carry_usd"))),
    ]
    rows = []
    for metric, unit, category, calculate in specs:
        cells = {a: calculate(a) for a in SUPPORTED_ASSETS}
        a, b = cells.values()
        comparable = (a["value"] is not None and b["value"] is not None and a["basis"] == b["basis"]
                      and [r["effective_time"] for r in a["clocks"]] == [r["effective_time"] for r in b["clocks"]])
        rows.append({"metric": metric, "unit": unit, "category": category, **cells,
                     "relative_delta": a["value"] - b["value"] if comparable else None,
                     "delta_basis": "MSTR_MINUS_ASST_NOT_INVESTMENT_ADVANTAGE",
                     "comparison_state": "COMPARABLE" if comparable else "BLOCKED",
                     "capital_implication": "DESCRIPTIVE_FACT_NOT_ALLOCATION_OR_TRADE_CLEARANCE"})
    # No new historical-price, financing or operating-cash-flow intake contract.
    for metric, unit, category in (
        ("funding_gross_net_settled", "USD", "FUNDING_EFFICIENCY"), ("funding_new_shares", "shares", "FUNDING_EFFICIENCY"),
        ("funding_btc_bought", "BTC", "FUNDING_EFFICIENCY"), ("operating_cash_flow", "USD/period", "CASH_HEALTH"),
        ("maximum_drawdown", "%", "MARKET_RISK")):
        rows.append({"metric": metric, "unit": unit, "category": category,
                     **{a: missing("COMPARABLE_BOUND_INPUT_NOT_AVAILABLE", "NOT_RUN") for a in SUPPORTED_ASSETS},
                     "relative_delta": None, "comparison_state": "NOT_RUN",
                     "capital_implication": "NO_CAUSAL_OR_PRECISE_ALLOCATION_CONCLUSION"})
    # One chart: aligned observed BTC/share growth, with no interpolation or
    # forward-filled share counts. A singleton is not a time-series chart.
    series = {}
    for asset in SUPPORTED_ASSETS:
        observations = sections[asset]["per_share_asset_engine"].get("observations", [])
        series[asset] = [r for r in observations if valid(r, asset) and r.get("basis_ref")
                         and _number(r.get("btc_per_diluted_share")) is not None
                         and r["btc_per_diluted_share"] > 0]
    dates = sorted(set(r["effective_time"] for r in series["MSTR"])
                   & set(r["effective_time"] for r in series["ASST"]))
    chart = {"metric": "btc_per_diluted_share_index", "qualification": "BLOCKED", "points": [],
             "reason": "ALIGNED_COMPARABLE_OBSERVATIONS_REQUIRED", "interpolation": "NONE",
             "colors": {"MSTR": "blue", "ASST": "green"}}
    if len(dates) >= 2 and all(len({r["basis_ref"] for r in rs}) == 1
                              and len({r["effective_time"] for r in rs}) == len(rs)
                              and all(r["source_semantic"] == rs[0]["source_semantic"] for r in rs)
                              for rs in series.values()):
        for asset, rs in series.items():
            lookup = {r["effective_time"]: r for r in rs}
            first = lookup[dates[0]]["btc_per_diluted_share"]
            chart[asset] = [{"effective_time": d, "value": 100 * lookup[d]["btc_per_diluted_share"] / first,
                             "source_ref": lookup[d]["source_ref"],
                             "clocks": {k: lookup[d][k] for k in clocks}} for d in dates]
        chart.update(qualification="RESEARCH_ONLY", reason="OBSERVED_COMMON_DATES_BASE_100",
                     points=dates, metric="btc_per_diluted_share_index")
    return {"schema_version": "CRT_QUANTITATIVE_EQUITY_INSPECTION_V0.1", "as_of_ms": as_of,
            "rows": rows, "chart_data": chart,
            "inventory": {"ALREADY_AVAILABLE": ["CT", "SIX_HEALTH_DIMENSIONS", "FORMAL_MNAV", "RESIDUAL_SNAPSHOT"],
                          "NEEDS_COMPOSITION": ["NUMERICAL_COMPARISON_VIEW", "RESIDUAL_RECOVERY_SENSITIVITY"],
                          "MISSING_REQUIRED_EVIDENCE": [r["metric"] for r in rows if r["comparison_state"] != "COMPARABLE"]},
            "capital_summary": {"state": "ANALYST_REQUIRED", "target_weights": None,
                "reason": "HEALTH_VALUATION_CYCLE_AND_PERSONAL_CAPITAL_REMAIN_SEPARATE",
                "q1_state_inferred": False, "formal_season": None,
                "strongest_counterevidence": "INCOMPLETE_SENIOR_CLAIMS_SCOPE_OR_ASYNCHRONOUS_SNAPSHOTS_BLOCK_PRECISE_ADVANTAGE"},
            "efficiency_lenses": {
                "issuer_funding": ["conversion_amount_not_net_settled", "conversion_new_shares", "conversion_btc_change"],
                "per_share_capital": ["btc_per_share_growth", "diluted_share_growth", "residual_per_diluted_share"],
                "investor_capital": ["equity_price_return", "btc_purchasing_power_return", "residual_per_dollar"],
                "causal_return": "NOT_PROVEN", "funding_proceeds_are_additional_budget": False},
            "action_output": "NONE", "production": "NOT_APPROVED", "external_action_authority": "NONE",
            "capital_decision_authority": "USER_ONLY"}


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
        # Deprecated/no-op: retained only for legacy input compatibility.
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
    # Deprecated compatibility flag: Summer 55/45 is always the HOLD anchor.
    # Season anchors never identify or advance a Capital Rail step.
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
            values[asset] = values.get(asset, 0.0) + value
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
    # Broker cash is a gross observed balance; USER_CONFIRMED reserves are a
    # restriction within it, never additional money. Legacy snapshots retain
    # their original separate available/reserved convention.
    cash_total = available if isinstance(profile.get("capital_reconciliation"), dict) else available + reserved
    invested = fixed + growth
    total = cash_total + invested
    if total <= 0:
        return {"state": "BLOCKED", "reason": "PORTFOLIO_TOTAL_NONPOSITIVE"}
    # Multiple legitimate lots of one asset must agree with bucket totals.
    if abs(sum(values.values()) - invested) > max(0.000001, abs(invested) * 1e-10):
        return {"state": "BLOCKED", "reason": "HOLDING_DETAIL_BUCKET_TOTAL_MISMATCH"}
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
        current_formula = (evidence.get("formula_version") == FORMULA_VERSION
            and evidence.get("denominator_basis") == DENOMINATOR_BASIS
            and evidence.get("semantic_ref") == SEMANTIC_REF)
        current = evidence.get("current_observation")
        receipt = {**current, "asset_nav_usd": current.get("btc_market_value_usd"),
            "action_output": "NONE", "external_action_authority": "NONE",
            "external_action_performed": False} if isinstance(current, dict) else None
        calculated = validate_diluted_mnav_evidence(receipt, asset_id=asset,
            as_of_ms=pack.get("generated_at_ms"))
        current_formula = (current_formula and calculated["state"] == "AVAILABLE"
            and _number(evidence.get("diluted_mnav")) is not None
            and math.isclose(evidence["diluted_mnav"], calculated["mnav"], rel_tol=1e-12))
        def claim_value(name: str) -> Any:
            if not current_formula:
                return None
            value = evidence.get(name)
            return value.get("value") if isinstance(value, dict) else value
        result[asset] = {
            "diluted_mnav": evidence.get("diluted_mnav") if current_formula else None,
            "formula_version": evidence.get("formula_version"),
            "denominator_basis": evidence.get("denominator_basis"),
            "semantic_ref": evidence.get("semantic_ref"),
            "source_semantic": deepcopy(evidence.get("source_semantic")),
            "share_basis_ref": (evidence.get("current_observation") or {}).get("share_basis_ref"),
            "own_history_empirical_cdf_pct": claim_value("own_history_empirical_cdf_pct"),
            "five_week_mnav_change_pct": claim_value("five_week_mnav_change_pct"),
            "benchmark_empirical_cdf_pct": claim_value("benchmark_empirical_cdf_pct"),
            "formal_action_critical_state": evidence.get("formal_action_critical_state") if current_formula else "BLOCKED",
            "evidence_authority": evidence.get("evidence_authority") if current_formula else "BLOCKED_LEGACY_MNAV_FORMULA",
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


def _q4_split_has_economic_support(q4, income, review, split, as_of_ms):
    """Require a same-clock Q4 comparison, not an analyst's free-standing ratio.

    This checks documentation and lineage, not whether GPT's reasoning is correct.
    Q5 remains responsible for evaluating the investment conclusion.
    """
    from .gold_research_context import _hash
    case = q4.get("strc_sata_allocation_case") if isinstance(q4, dict) else None
    if not isinstance(case, dict) or not isinstance(review, dict):
        return False
    if not (case.get("state") == "RESEARCH_EVIDENCED"
            and case.get("as_of_ms") == as_of_ms
            and case.get("income_summary_hash") == income.get("summary_hash")
            and case.get("recommended_strc_sata_pct") == split
            and review.get("q4_allocation_case_hash") == _hash(case)):
        return False
    required = ("income_tradeoff", "issuer_risk", "capital_preservation",
                "round_trip_friction", "cash_alternative", "allocation_reason", "invalidation")
    reasons = case.get("economic_reasons")
    if not isinstance(reasons, dict) or any(
            not isinstance(reasons.get(key), str) or not reasons[key].strip() for key in required):
        return False
    references = case.get("asset_evidence_refs")
    if not isinstance(references, dict) or any(
            not isinstance(references.get(asset), str)
            or references[asset] != f"income_engine.assets.{asset}.current_terms"
            for asset in ("STRC", "SATA")):
        return False
    return True


def build_allocation_review_table(pack, rail, review):
    """Local table 4 arithmetic, using existing policy and a bound analyst review.

    Never chooses a rail, splits income assets by itself, or creates trade legs.
    Callers supply a PIT-validated review through capital_posture_context.
    """
    from .gold_research_context import _hash
    if (not isinstance(pack, dict) or pack.get("evidence_pack_hash") != _hash(
            {k: v for k, v in pack.items() if k != "evidence_pack_hash"})):
        raise ValueError("ALLOCATION_TABLE_PARENT_HASH_INVALID")
    assets = ("MSTR", "ASST", "STRC", "SATA", "USD_CASH")
    allocation = pack.get("portfolio_allocation_context") or {}
    current = allocation.get("current_allocation") or {}
    total = _number(current.get("total_portfolio_usd")) if current.get("state") == "AVAILABLE" else None
    if total is not None and total <= 0:
        total = None
    values = current.get("values_usd") or {}
    targets, reasons = {}, []
    parent = pack["evidence_pack_hash"]
    if (not isinstance(review, dict) or review.get("state") == "BLOCKED"
            or review.get("parent_evidence_pack_hash") != parent
            or review.get("reviewed_by") != "ANALYST"
            or review.get("allocation_source_hash") != _hash(allocation)):
        reasons.append("BOUND_ALLOCATION_REVIEW_REQUIRED")
    if rail.get("state") != "READY_FOR_ANALYST":
        reasons.append("USER_CONFIRMED_CURRENT_RAIL_REQUIRED")
    cash = _number(allocation.get("cash_target_pct"))
    if allocation.get("state") != "READY_FOR_ANALYST" or cash is None:
        reasons.append("EXPLICIT_EXISTING_CASH_POLICY_REQUIRED")
    targets_ready = not reasons
    split = rail.get("current_rail_step", {}).get("fixed_growth_pct") if targets_ready else None
    if not isinstance(split, list) or len(split) != 2:
        reasons.append("CURRENT_RAIL_HAS_NO_PERCENTAGE_SPLIT")
        targets_ready = False
    if targets_ready:
        # Reuse approved range, current confirmed step, and existing health tilt.
        lo, hi = allocation["cash_target_range"]
        if not lo <= cash <= allocation["cash_stress_cap_pct"] or hi < lo:
            reasons.append("CASH_OUTSIDE_EXISTING_POLICY")
            targets_ready = False
    if targets_ready:
        invested = 100 - cash
        targets["USD_CASH"] = cash
        mstr = _number(allocation.get("suggested_mstr_pct"))
        asst = _number(allocation.get("suggested_asst_pct"))
        if (mstr is not None and asst is not None and min(mstr, asst) >= 0
                and abs(mstr + asst - 100) < 1e-8):
            for asset, pct in (("MSTR", mstr), ("ASST", asst)):
                health = (pack.get("common_equity_health", {}).get("assets") or {}).get(asset) or {}
                if health.get("health_direction") in {"IMPROVING", "STABLE", "DETERIORATING"}:
                    targets[asset] = invested * split[1] / 100 * pct / 100
        q4 = pack.get("asset_strategy_delta")
        income = (q4.get("income_engine") or {}) if isinstance(q4, dict) else {}
        income_valid = (income.get("schema_version") == "CRT_DUAL_FIXED_INCOME_V0.1"
            and income.get("as_of_ms") == pack["generated_at_ms"]
            and income.get("summary_hash") == _hash({k: v for k, v in income.items() if k != "summary_hash"}))
        income_split = review.get("strc_sata_within_fixed_pct")
        if (income_valid and review.get("q4_source_hash") == _hash(q4)
                and _q4_split_has_economic_support(
                    q4, income, review, income_split, pack["generated_at_ms"])
                and isinstance(income_split, list) and len(income_split) == 2
                and all(_number(x) is not None and 0 <= x <= 100 for x in income_split)
                and abs(sum(income_split) - 100) < 1e-8):
            for asset, pct in zip(("STRC", "SATA"), income_split):
                fact = (income.get("assets") or {}).get(asset) or {}
                if (fact.get("holding_state") == "AVAILABLE"
                        and (fact.get("current_terms") or {}).get("state") == "AVAILABLE"):
                    targets[asset] = invested * split[0] / 100 * pct / 100
    rows = []
    for asset in assets:
        value = _number(current.get("cash_usd")) if asset == "USD_CASH" else _number(values.get(asset))
        # Unknown holdings are never inferred as zero or renormalized.
        current_pct = value / total * 100 if total is not None and value is not None else None
        target = targets.get(asset)
        target_usd = total * target / 100 if total is not None and target is not None else None
        row_reasons = list(reasons)
        if target is None:
            row_reasons.append("ASSET_ALLOCATION_BASIS_INCOMPLETE")
        if current_pct is None:
            row_reasons.append("COMPLETE_CURRENT_PORTFOLIO_DENOMINATOR_REQUIRED")
        rows.append({"asset": asset, "current_usd": value, "current_pct": current_pct,
            "target_pct": target, "delta_pct": None if current_pct is None or target is None else target-current_pct,
            "target_usd": target_usd, "delta_usd": None if value is None or target_usd is None else target_usd-value,
            "qualified_share_counts": None,
            "quantity_state": "NOT_APPLICABLE" if asset == "USD_CASH" else "BLOCKED",
            "quantity_reason": "EXISTING_FINAL_CAPITAL_VALIDATION_REQUIRED" if asset != "USD_CASH" else None,
            "state": "RESEARCH_ONLY" if not row_reasons else "BLOCKED", "blockers": row_reasons})
    all_targets = len(targets) == len(assets)
    expiries = [r.get("valid_until_ms") for r in (review, rail.get("provenance", {}))]
    expiry = min(expiries) if all(type(v) is int for v in expiries) else None
    return {"state": "RESEARCH_ONLY" if all_targets and all(r["state"] == "RESEARCH_ONLY" for r in rows) else "PARTIAL", "rows": rows,
        "target_total_pct": sum(targets.values()) if all_targets else None,
        "known_target_subtotal_pct": sum(targets.values()), "percentage_basis": "TOTAL_TACTICAL_PORTFOLIO",
        "parent_evidence_pack_hash": parent, "as_of_ms": pack["generated_at_ms"],
        "valid_until_ms": expiry,
        "capital_observation_hash": ((pack.get("private_context") or {}).get("profile", {})
            .get("capital_reconciliation", {}).get("broker_observed") or {}).get("observation_hash"),
        "current_rail_step": deepcopy(rail.get("current_rail_step")),
        "allocation_adjustment_scopes": deepcopy(review.get("allocation_adjustment_scopes", {}))
            if isinstance(review, dict) and review.get("state") != "BLOCKED" else {},
        "allocation_source_hash": _hash(allocation), "review_source_hash": _hash(review),
        "limitation": "RESEARCH_TARGETS_NOT_TRADE_QUANTITIES_NO_AUTOMATIC_RAIL_ADVANCEMENT"}


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
            if isinstance(row.get("company_health"), dict):
                assets[asset]["company_health"] = compact_health_dimensions(row["company_health"])
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
