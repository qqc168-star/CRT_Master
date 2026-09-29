"""Interpret existing validated CT organs; no collection, valuation or action."""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

from .treasury_company_ct import validate_pit_replay

DIMENSIONS = (
    "per_share_asset_engine", "common_capital_efficiency",
    "funding_market_acceptance", "senior_claims_carry", "liquidity_buffer",
    "capital_conversion_efficiency",
)


def _number(value):
    try:
        return float(value) if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:
        return None


def _direction(value, lower=False):
    value = _number(value)
    if value is None:
        return "BLOCKED"
    if value == 0:
        return "STABLE"
    return "IMPROVING" if (value < 0 if lower else value > 0) else "DETERIORATING"


def _dimension(claims, refs):
    known = {v["direction"] for v in claims.values()} - {"BLOCKED", "STABLE"}
    missing = [k for k, v in claims.items() if v["direction"] == "BLOCKED"]
    mixed = len(known) > 1
    direction = ("BLOCKED" if mixed else next(iter(known)) if known
                 else "STABLE" if len(missing) < len(claims) else "BLOCKED")
    return {"direction": direction,
            "state": "BLOCKED" if len(missing) == len(claims) else "PARTIAL" if missing else "AVAILABLE",
            "interpretation_state": "MIXED" if mixed else "INSUFFICIENT_EVIDENCE" if direction == "BLOCKED" else "CONSISTENT",
            "reason": "OPPOSING_VERIFIED_CLAIM_DIRECTIONS" if mixed else
                      "COMPARISON_EVIDENCE_UNAVAILABLE" if direction == "BLOCKED" else "VERIFIED_CLAIMS_SAME_DIRECTION",
            "claims": claims, "missing_evidence": missing,
            "supporting_evidence": sorted(set(refs)),
            "analyst_judgment_required": direction == "BLOCKED" or bool(missing)}


def build_health_dimensions(*, organs, issuer_id, as_of_ms, residual_change=None):
    """Inputs are sections of existing TREASURY_COMPANY_CT facts, never raw news.

    Recheck PIT and comparison bases even for caller-built packs. References are
    deduplicated provenance, not votes. Missing evidence cannot establish health.
    """
    provenance = {}

    def valid(row):
        if not isinstance(row, dict) or type(as_of_ms) is not int or as_of_ms <= 0:
            return False
        result = validate_pit_replay(row, issuer_id=issuer_id, replay_at=as_of_ms, mode="AUDIT_REPLAY")
        if result["state"] != "AVAILABLE":
            return False
        ref = row["source_ref"]
        metadata = result["record"]
        entries = provenance.setdefault(ref, [])
        if metadata not in entries:
            entries.append(metadata)
        return True

    def pair(section, *, liquidity=False):
        if not isinstance(section, dict):
            return None, None
        before, now = section.get("previous"), section.get("current")
        if not (valid(before) and valid(now)):
            return None, None
        if (not now.get("basis_ref") or before.get("basis_ref") != now["basis_ref"]
                or before["effective_time"] >= now["effective_time"]
                or before["source_semantic"] != now["source_semantic"]):
            return None, None
        if liquidity and (not before.get("cash_usability_basis_ref")
                or before.get("cash_usability_basis_ref") != now.get("cash_usability_basis_ref")
                or before.get("coverage_basis") != now.get("coverage_basis")):
            return None, None
        return before, now

    def claim(value, lower=False):
        return {"value": _number(value), "direction": _direction(value, lower)}

    def delta(before, now, field):
        a, b = _number((before or {}).get(field)), _number((now or {}).get(field))
        return b - a if a is not None and b is not None else None

    def refs(*rows):
        return [r["source_ref"] for r in rows if isinstance(r, dict) and r.get("source_ref")]

    asset = organs.get("per_share_asset_engine", {})
    burden = organs.get("capital_burden_resilience", {})
    funding = organs.get("funding_engine", {})
    conversion = organs.get("capital_conversion", {})
    before, now = pair(asset)
    asset_refs = refs(before, now)
    bps = delta(before, now, "btc_per_diluted_share")
    burden_before, burden_now = pair(burden)
    aligned = (before and now and burden_before and burden_now
               and before["effective_time"] == burden_before["effective_time"]
               and now["effective_time"] == burden_now["effective_time"])
    residual = residual_change if aligned else None
    dimensions = {"per_share_asset_engine": _dimension({
        "btc_per_diluted_share": claim(bps),
        "net_residual_value_per_share": claim(residual),
    }, asset_refs)}

    old, current = burden_before, burden_now
    dimensions["senior_claims_carry"] = _dimension({
        "senior_claims_usd": claim(delta(old, current, "senior_claims_usd"), True),
        "annual_carry_usd": claim(delta(old, current, "annual_carry_usd"), True),
    }, refs(old, current))
    cash_old, cash_now = pair(burden, liquidity=True)
    dimensions["liquidity_buffer"] = _dimension({
        "usable_liquidity_usd": claim(delta(cash_old, cash_now, "usable_liquidity_usd")),
        "carry_coverage_years": claim(delta(cash_old, cash_now, "carry_coverage_years")),
    }, refs(cash_old, cash_now))

    funding_claims, funding_refs = {}, []
    instruments = funding.get("instruments", [])
    ids = [r.get("instrument_id") for r in instruments if isinstance(r, dict)]
    for row in instruments:
        if not valid(row) or ids.count(row.get("instrument_id")) != 1:
            continue
        key = row["instrument_id"]
        funding_refs.extend(refs(row))
        previous_cost = row.get("previous_cost")
        cost = None
        if (valid(previous_cost) and row.get("cost_basis_ref")
                and previous_cost.get("cost_basis_ref") == row["cost_basis_ref"]
                and previous_cost["effective_time"] < row["effective_time"]):
            cost = delta(previous_cost, row, "annual_cost_rate_pct")
            funding_refs.extend(refs(previous_cost))
        funding_claims[key + ".cost"] = claim(cost, True)
        comparison = row.get("absorption_comparison", {})
        a, b = pair(comparison)
        absorption = None
        if (a and b and _number(a.get("window_ms")) is not None
                and a["window_ms"] > 0 and a["window_ms"] == b.get("window_ms")
                and b["effective_time"] == row["effective_time"]):
            absorption = delta(a, b, "net_proceeds_usd")
            funding_refs.extend(refs(a, b))
        funding_claims[key + ".market_absorption"] = claim(absorption)
    dimensions["funding_market_acceptance"] = _dimension(
        funding_claims or {"comparable_funding_observations": claim(None)}, funding_refs)
    dimensions["funding_market_acceptance"]["missing_evidence"].append("COMPARABLE_USABLE_CAPACITY")
    if dimensions["funding_market_acceptance"]["state"] == "AVAILABLE":
        dimensions["funding_market_acceptance"]["state"] = "PARTIAL"
    dimensions["funding_market_acceptance"]["analyst_judgment_required"] = True

    events, event_claims, event_refs = [], {}, []
    raw_events = conversion.get("events", [])
    ids = [e.get("event_id") for e in raw_events if isinstance(e, dict)]
    for row in raw_events:
        if (not valid(row) or row.get("active_for_calculation") is not True
                or not row.get("event_id") or ids.count(row["event_id"]) != 1
                or not row.get("source") or not row.get("destination")):
            continue
        events.append(row)
        event_refs.extend(refs(row))
        # Preserve independent accounting components; never net dollars against
        # BTC, sum overlapping events, or infer future capacity from a buyback.
        for field, lower in (("senior_claim_change_usd", True),
                             ("annual_carry_change_usd", True), ("liquidity_change_usd", False)):
            value = row.get(field) if row.get("consequence_basis_ref") else None
            event_claims[row["event_id"] + "." + field] = claim(value, lower)
    interval_events = [e for e in events if before and now and e.get("consequence_basis_ref")
                       and before["effective_time"] < e["effective_time"] <= now["effective_time"]]
    if interval_events:
        event_claims["interval_btc_per_share_outcome"] = claim(bps)
        event_claims["interval_residual_per_share_outcome"] = claim(residual)
        event_refs.extend(asset_refs)
    conversion_dimension = _dimension(event_claims or {"verified_consequences": claim(None)}, event_refs)
    conversion_dimension["analyst_judgment_required"] = True
    conversion_dimension["limitation"] = "COMPONENT_TRADE_OFFS_NOT_CAUSAL_RETURN_OR_FUTURE_CAPACITY"
    dimensions["capital_conversion_efficiency"] = conversion_dimension
    for name, section in (("funding_market_acceptance", funding),
                          ("capital_conversion_efficiency", conversion)):
        if section.get("coverage_state") != "COMPLETE" or not valid(section.get("coverage_evidence")):
            dimensions[name]["missing_evidence"].append("COMPLETE_SCOPE_COVERAGE")
            if dimensions[name]["state"] == "AVAILABLE":
                dimensions[name]["state"] = "PARTIAL"
            dimensions[name]["analyst_judgment_required"] = True

    # An interval comparison following a bound common issuance is descriptive,
    # not a causal return-on-capital estimate or a valuation clearance.
    common = [e for e in events if e.get("source") in {
        "MSTR_COMMON_ISSUANCE", "ASST_COMMON_ISSUANCE", "COMMON_ATM", "COMMON_ISSUANCE"}
        and before and now and before["effective_time"] < e["effective_time"] <= now["effective_time"]
        and e.get("consequence_basis_ref") and _number(e.get("amount_usd")) is not None
        and e["amount_usd"] > 0 and _number(e.get("diluted_share_change")) is not None
        and e["diluted_share_change"] > 0]
    dimensions["common_capital_efficiency"] = _dimension({
        "post_issuance_btc_per_share": claim(bps if common else None),
        "post_issuance_residual_per_share": claim(residual if common else None),
    }, asset_refs + refs(*common) if common else [])
    dimensions["common_capital_efficiency"]["limitation"] = "INTERVAL_OUTCOME_NOT_CAUSAL_ATTRIBUTION"

    scopes = {
        "per_share_asset_engine": "PER_SHARE_INTERVAL_CHANGE_ONLY",
        "common_capital_efficiency": "INTERVAL_OUTCOME_NOT_CAUSAL_ATTRIBUTION",
        "funding_market_acceptance": "PRIMARY_FUNDING_ABSORPTION_AND_COST_ONLY",
        "senior_claims_carry": "SENIOR_CLAIMS_AND_ANNUAL_CARRY_ONLY",
        "liquidity_buffer": "USABLE_CASH_AND_STATIC_CARRY_COVERAGE_ONLY",
        "capital_conversion_efficiency": "COMPONENT_TRADE_OFFS_NOT_CAUSAL_RETURN_OR_FUTURE_CAPACITY",
    }
    for name, scope in scopes.items():
        dimensions[name]["claim_scope"] = scope

    improving = [k for k in DIMENSIONS if dimensions[k]["direction"] == "IMPROVING"]
    deteriorating = [k for k in DIMENSIONS if dimensions[k]["direction"] == "DETERIORATING"]
    mixed = [k for k in DIMENSIONS if dimensions[k]["interpretation_state"] == "MIXED"]
    missing = [k + "." + c for k in DIMENSIONS for c in dimensions[k]["missing_evidence"]]
    events.sort(key=lambda e: (e["effective_time"], e["event_id"]))
    routes = [{"source": e["source"], "destination": e["destination"],
               "effective_time": e["effective_time"], "event_id": e["event_id"],
               "source_ref": e["source_ref"], "amount_usd": e.get("amount_usd"),
               "consequences": {k: e.get(k) for k in (
                   "btc_change", "diluted_share_change", "senior_claim_change_usd",
                   "annual_carry_change_usd", "liquidity_change_usd")}}
              for e in events if e.get("consequence_basis_ref") and _number(e.get("amount_usd")) is not None]
    latest_time = routes[-1]["effective_time"] if routes else None
    latest = [r for r in routes if r["effective_time"] == latest_time]
    prior_routes = {(r["source"], r["destination"]) for r in routes if r["effective_time"] < latest_time}
    emerging = [r for r in latest if prior_routes and (r["source"], r["destination"]) not in prior_routes]
    contradictions = ["OPPOSING_HEALTH_DIMENSIONS"] if improving and deteriorating or mixed else []
    coverage = {k: v.get("coverage_state", "UNSPECIFIED") for k, v in organs.items()}
    migration = {
        "state": "ANALYST_REQUIRED" if routes else "BLOCKED",
        "current_engine": latest, "emerging_engine": emerging,
        "supporting_evidence": sorted(set(event_refs + funding_refs + asset_refs + refs(old, current))),
        "trade_offs": {"improving": improving, "deteriorating": deteriorating, "mixed": mixed},
        "contradictions": contradictions,
        "missing_evidence": missing + ["DOMINANT_ENGINE_NOT_ESTABLISHED", "FUTURE_FUNDING_CAPACITY_NOT_ESTABLISHED"],
        "analyst_judgment_required": True,
        "limitation": "OBSERVED_ROUTES_ONLY_NOT_MANAGEMENT_INTENT_OR_CONFIRMED_MIGRATION",
    }
    result = {
        "schema_version": "CRT_COMPANY_HEALTH_DIMENSIONS_V0.1",
        "dimensions": {k: dimensions[k] for k in DIMENSIONS},
        "capital_engine": migration,
        "asset_role_integrity": {"state": "ANALYST_REQUIRED", "review_dimensions": deteriorating + mixed,
                                 "eligibility": "NOT_DETERMINED"},
        "as_of_ms": as_of_ms, "coverage": coverage, "provenance": provenance,
        "limitation": "OBSERVED_CHANGE_NOT_SOLVENCY_OR_INDEPENDENT_SOURCE_VOTES",
        "invalidation": "REVISED_SOURCE_OR_CHANGED_TIME_SHARE_ACCOUNTING_OR_USABILITY_BASIS",
        "machine_may_determine_btc_season": False,
        "action_output": "NONE", "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY", "machine_execution": "FORBIDDEN",
        "production": "NOT_APPROVED",
    }
    result["context_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"),
                                                       ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return result


def compact_health_dimensions(context):
    """Bounded projection: statuses and missing-claim counts; full evidence local."""
    material = {k: v for k, v in context.items() if k != "context_hash"}
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if context.get("context_hash") != digest:
        raise ValueError("Company health context hash mismatch")
    engine = context["capital_engine"]
    return {
        "dimensions": {k: {"direction": v["direction"], "state": v["state"],
                            "interpretation_state": v["interpretation_state"],
                            "reason": v["reason"],
                            "analyst_judgment_required": v["analyst_judgment_required"],
                            "claim_scope": v["claim_scope"],
                            "missing_claim_count": len(v["missing_evidence"]),
                            "missing_evidence": v["missing_evidence"][:3]}
                       for k, v in context["dimensions"].items()},
        "capital_engine": {"state": engine["state"],
                           "current_routes": sorted({r["source"] + "->" + r["destination"] for r in engine["current_engine"]})[:4],
                           "current_route_count": len({(r["source"], r["destination"]) for r in engine["current_engine"]}),
                           "emerging_route_count": len(engine["emerging_engine"]),
                           "contradictions": deepcopy(engine["contradictions"]),
                           "analyst_judgment_required": True,
                           "limitation": engine["limitation"]},
        "asset_role_integrity": deepcopy(context["asset_role_integrity"]),
        "as_of_ms": context["as_of_ms"], "context_hash": context["context_hash"],
    }
