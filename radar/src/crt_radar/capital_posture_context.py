"""Local capital synthesis for analyst review; never final capital eligibility.

Existing contexts own evidence and qualifications. This module preserves their
separation and calculates only the explicitly requested capital research math.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

from .deployment_posture_research_gate import translate_research_state_to_posture_constraints
from .gold_research_context import _hash
from .gpt_commander_plan_closure import _authority_scan
from .treasury_company_ct import validate_pit_replay

SCHEMA_VERSION = "CRT_CAPITAL_POSTURE_CONTEXT_V0.1"
LOCKS = {
    "final_eligibility": "NOT_DETERMINED", "action_output": "NONE",
    "external_action_authority": "NONE", "capital_decision_authority": "USER_ONLY",
    "machine_execution": "FORBIDDEN", "production": "NOT_APPROVED",
    "machine_may_determine_btc_season": False, "analyst_judgment_required": True,
}
RAILS = {
    "SPRING": [[70, 30], [65, 35], [60, 40], [55, 45]],
    "SUMMER_HOLD": [[55, 45]],
    "ANALYST_ROLLOVER": [[55, 45], [65, 35], [70, 30], [80, 20]],
    "AUTUMN_PRESERVATION": [[80, 20]],
    "WINTER_SPLIT": [],
}
MAINTENANCE = {
    "routine": "WEEKLY", "preventive": "MONTHLY", "major_service": "QUARTERLY_OR_10Q",
    "emergency": ["8K", "ISSUANCE", "FINANCING", "DISTRIBUTION", "GOVERNANCE_EVENT"],
    "seasonal_service": "SEASON_TRANSITION", "full_cycle_overhaul": "COMPLETED_BULL_BEAR_CYCLE",
}
FLYWHEEL = ["WINTER_BTC_ACCUMULATION", "SPRING_GROWTH_DEPLOYMENT",
    "MSTR_ASST_BTC_AMPLIFICATION", "SUMMER_HOLD",
    "ANALYST_VALUATION_REALIZATION_AND_STRUCTURE_ROLLOVER_REVIEW", "MSTR_ASST_HARVEST",
    "STRC_SATA_CASH_PRESERVATION", "AUTUMN_DEFENSE", "WINTER_OPERATING_FUND_SEPARATION",
    "EXCESS_CAPITAL_TO_BTC_CORE", "NEXT_CYCLE"]


def _blocked(reason):
    return {"state": "BLOCKED", "reason": reason}


def _claim(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError) as exc:
        return _blocked(str(exc))


def _number(value, *, positive=False, nonnegative=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or positive and value <= 0 or nonnegative and value < 0):
        raise ValueError("FINITE_SCOPED_NUMERIC_INPUT_REQUIRED")
    return float(value)


def _record(raw, *, as_of, metric):
    """Reuse existing PIT metadata validation, not a new evidence-binding engine."""
    if validate_pit_replay(raw, issuer_id="CAPITAL", replay_at=as_of,
                           mode="AUDIT_REPLAY")["state"] != "AVAILABLE":
        raise ValueError("CAPITAL_RESEARCH_INPUT_NOT_PIT_VALIDATED")
    if raw.get("metric_id") != metric:
        raise ValueError("CAPITAL_RESEARCH_METRIC_MISMATCH")
    for key in ("cycle_id", "basis_ref", "limitation", "invalidation"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ValueError("CYCLE_BASIS_LIMITATION_AND_INVALIDATION_REQUIRED")
    if type(raw.get("valid_until_ms")) is not int or raw["valid_until_ms"] < as_of:
        raise ValueError("CAPITAL_RESEARCH_INPUT_EXPIRED_OR_UNBOUNDED")
    return deepcopy(raw)


def seasonal_capital_rail(raw, *, as_of, parent_hash):
    row = _record(raw, as_of=as_of, metric="CURRENT_CAPITAL_RAIL")
    if row.get("parent_evidence_pack_hash") != parent_hash or row.get("recorded_by") != "USER":
        raise ValueError("EXPLICIT_USER_RECORDED_CURRENT_RAIL_REQUIRED")
    rail, step = row.get("rail"), row.get("step")
    if rail not in RAILS or type(step) is not int:
        raise ValueError("KNOWN_RAIL_AND_EXPLICIT_STEP_REQUIRED")
    path = RAILS[rail]
    if not (0 <= step < len(path) or rail == "WINTER_SPLIT" and step == 0):
        raise ValueError("CURRENT_RAIL_STEP_OUT_OF_RANGE")
    next_step = path[step+1] if step+1 < len(path) else None
    return {"state": "READY_FOR_ANALYST", "current_rail_step": {"rail": rail, "step": step,
                "fixed_growth_pct": deepcopy(path[step]) if path else None},
            "next_strategic_destination": deepcopy(next_step),
            "next_destination_status": "NOT_EVALUATED" if next_step else "NO_AUTOMATIC_NEXT_STEP",
            "qualification_owner": "ANALYST_AND_USER", "provenance": row,
            "limitation": "DESTINATION_NOT_ELIGIBILITY_NO_AUTOMATIC_STEP_OR_MANDATORY_QUOTA"}


def operating_fund(raw, *, as_of, cycle_id):
    row = _record(raw, as_of=as_of, metric="OPERATING_PRICE_ANCHOR")
    if row["cycle_id"] != cycle_id or not isinstance(row.get("approval_ref"), str) or not row["approval_ref"].strip():
        raise ValueError("CURRENT_CYCLE_APPROVED_PRICE_ANCHOR_REQUIRED")
    # Consume an approved historical aggregate; do not create another price engine.
    if (row.get("method") != "EQUAL_WEIGHT_STRC_SATA_9M_AVERAGE"
            or row.get("assets") != ["STRC", "SATA"] or row.get("currency") != "USD"
            or row.get("coverage_state") != "COMPLETE" or row.get("lookback_months") != 9):
        raise ValueError("APPROVED_NINE_MONTH_HISTORICAL_METHOD_REQUIRED")
    start, end = row.get("sample_start_ms"), row.get("sample_end_ms")
    if type(start) is not int or type(end) is not int or not 0 < start < end <= row["effective_time"]:
        raise ValueError("HISTORICAL_ANCHOR_SAMPLE_PERIOD_REQUIRED")
    price = _number(row.get("price_per_share_usd"), positive=True)
    anchor = _number(375 * price, positive=True)
    return {"state": "READY_FOR_ANALYST", "operating_capacity_shares": 375,
            "price_anchor_usd": price, "operating_fund_anchor_usd": anchor,
            "reestimate_each_winter": True, "provenance": row,
            "limitation": "RESEARCH_CAPACITY_ANCHOR_NOT_FIXED_DOLLARS_OR_TOTAL_ASSET_PERCENTAGE"}


def flywheel_economics(raw, *, as_of, cycle_id):
    row = _record(raw, as_of=as_of, metric="FLYWHEEL_SCENARIO")
    if row["cycle_id"] != cycle_id or row.get("scenario_only") is not True:
        raise ValueError("CURRENT_CYCLE_LABELED_SCENARIO_REQUIRED")
    if (not isinstance(row.get("assumption_ids"), list) or not row["assumption_ids"]
            or any(not isinstance(v, str) or not v.strip() for v in row["assumption_ids"])):
        raise ValueError("EXISTING_ASSUMPTION_WATCH_REFERENCES_REQUIRED")
    current = _number(row.get("current_btc_price_usd"), positive=True)
    winter = _number(row.get("expected_winter_btc_price_usd"), positive=True)
    years = _number(row.get("horizon_years"), positive=True)
    cagr = _number(row.get("crt_forward_cagr"))
    if cagr < -1:
        raise ValueError("CAGR_BELOW_MINUS_ONE_INVALID")
    hurdle = _number(math.expm1((math.log(winter)-math.log(current))/years))
    return {"state": "READY_FOR_ANALYST", "btc_opportunity_hurdle": hurdle,
            "crt_forward_cagr_assumption": cagr, "flywheel_margin": _number(cagr-hurdle),
            "units": "ANNUAL_DECIMAL_RETURN", "provenance": row,
            "limitation": "CONDITIONAL_PLANNING_COMPARISON_NOT_GUARANTEED_RETURN_OR_ROUTING_DECISION"}


def full_cycle_review(raw, *, as_of, cycle_id):
    row = _record(raw, as_of=as_of, metric="FULL_CYCLE_REVIEW")
    if row["cycle_id"] != cycle_id:
        raise ValueError("FULL_CYCLE_ID_MISMATCH")
    start, end = row.get("cycle_start_ms"), row.get("cycle_end_ms")
    if (row.get("completed_cycle") is not True or type(start) is not int or type(end) is not int
            or not 0 < start < end <= row["effective_time"]):
        raise ValueError("COMPLETED_FULL_CYCLE_REVIEW_PERIOD_REQUIRED")
    def accretion():
        start = _number(row.get("btc_core_start"), nonnegative=True)
        end = _number(row.get("btc_core_end"), nonnegative=True)
        return {"state": "READY_FOR_ANALYST", "btc_core_accretion": _number(end-start),
                "unit": "BTC", "btc_core_start": start, "btc_core_end": end}
    def capacity():
        shares = _number(row.get("ending_operating_capacity_shares"), nonnegative=True)
        return {"state": "READY_FOR_ANALYST", "operating_capacity_preserved": shares >= 375,
                "ending_capacity_shares": shares, "required_capacity_shares": 375}
    def loss():
        # Permanent loss is an attributed review judgment, not inferred from drawdown.
        if type(row.get("permanent_capital_loss")) is not bool or not row.get("loss_assessment_ref"):
            raise ValueError("PERMANENT_LOSS_REVIEW_ASSESSMENT_REQUIRED")
        return {"state": "READY_FOR_ANALYST", "permanent_capital_loss": row["permanent_capital_loss"],
                "assessment_ref": row["loss_assessment_ref"]}
    def comparison():
        if not row.get("same_period_cashflow_adjusted_basis_ref"):
            raise ValueError("COMPARABLE_REALIZED_CAGR_BASIS_REQUIRED")
        crt = _number(row.get("crt_realized_cagr"))
        btc = _number(row.get("btc_benchmark_cagr"))
        if min(crt, btc) < -1:
            raise ValueError("CAGR_BELOW_MINUS_ONE_INVALID")
        return {"state": "READY_FOR_ANALYST", "crt_realized_cagr": crt,
                "btc_benchmark_cagr": btc, "difference": _number(crt-btc)}
    claims = {"btc_core": _claim(accretion), "operating_capacity": _claim(capacity),
              "permanent_loss": _claim(loss), "realized_cagr_comparison": _claim(comparison)}
    return {"state": "READY_FOR_ANALYST" if any(c["state"] == "READY_FOR_ANALYST" for c in claims.values()) else "BLOCKED",
            "claims": claims, "provenance": row, "limitation": "REVIEW_METRICS_NOT_TRADE_TRIGGERS"}


def _sealed_context(raw, field):
    return isinstance(raw, dict) and raw.get(field) == _hash({k: v for k, v in raw.items() if k != field})


def _available(raw):
    return isinstance(raw, dict) and raw.get("state") in {"AVAILABLE", "READY_FOR_ANALYST"}


def _ref(raw, name):
    return {"source": name, "source_hash": _hash(raw) if isinstance(raw, dict) else None,
            "state": "AVAILABLE" if _available(raw) else "BLOCKED"}


def _winter_split(current, fund):
    if (not _available(current) or not _available(fund)
            or current.get("strategic_btc_excluded_from_policy_math") is not True):
        raise ValueError("EXISTING_CORE_EXCLUDED_CAPITAL_STATE_AND_ANCHOR_REQUIRED")
    tactical = _number(current.get("total_portfolio_usd"), nonnegative=True)
    core = _number(current.get("strategic_btc_quantity"), nonnegative=True)
    anchor = fund["operating_fund_anchor_usd"]
    return {"state": "READY_FOR_ANALYST", "tactical_capital_usd_excluding_btc_core": tactical,
            "operating_fund_anchor_usd": anchor, "anchor_shortfall_usd": max(anchor-tactical, 0),
            "research_residual_for_btc_accumulation_usd": max(tactical-anchor, 0),
            "existing_btc_core_quantity": core,
            "limitation": "GROSS_RESEARCH_SPLIT_NOT_AVAILABLE_CASH_TRANCHE_OR_TRANSFER_INSTRUCTION"}


def build_capital_posture_context(inputs, evidence_pack, gold_context=None):
    """Pure local synthesis; original contexts and downstream gate list are reused."""
    if not isinstance(inputs, dict) or not _sealed_context(evidence_pack, "evidence_pack_hash"):
        raise ValueError("INPUT_OR_PARENT_EVIDENCE_PACK_HASH_INVALID")
    _authority_scan(inputs)
    _authority_scan(evidence_pack)
    as_of, cycle = inputs.get("as_of_ms"), inputs.get("cycle_id")
    if (type(as_of) is not int or as_of <= 0 or type(evidence_pack.get("generated_at_ms")) is not int
            or evidence_pack["generated_at_ms"] > as_of or not isinstance(cycle, str) or not cycle.strip()):
        raise ValueError("EXPLICIT_CYCLE_AND_VISIBLE_PARENT_REQUIRED")
    parent_hash = evidence_pack["evidence_pack_hash"]
    gold_valid = (_sealed_context(gold_context, "context_hash")
        and gold_context.get("schema_version") == "CRT_GOLD_RESEARCH_CONTEXT_V0.1"
        and gold_context.get("parent_evidence_pack_hash") == parent_hash
        and type(gold_context.get("as_of_ms")) is int and gold_context["as_of_ms"] <= as_of
        and gold_context.get("storage") == "LOCAL_ONLY"
        and all(gold_context.get(k) == v for k, v in LOCKS.items()
                if k not in {"final_eligibility", "analyst_judgment_required"}))
    gold = gold_context if gold_valid else {}
    _authority_scan(gold)
    posture = translate_research_state_to_posture_constraints(inputs.get("research_evaluation")
        if inputs.get("research_evidence_pack_hash") == parent_hash else None)
    allocation = evidence_pack.get("portfolio_allocation_context", {})
    health = evidence_pack.get("common_equity_health", {})
    current = allocation.get("current_allocation", {})
    rail = _claim(seasonal_capital_rail, inputs.get("current_rail"), as_of=as_of, parent_hash=parent_hash)
    if _available(rail) and rail["provenance"]["cycle_id"] != cycle:
        rail = _blocked("CURRENT_RAIL_CYCLE_MISMATCH")
    economics = _claim(flywheel_economics, inputs.get("flywheel_scenario"), as_of=as_of, cycle_id=cycle)
    fund = _claim(operating_fund, inputs.get("operating_anchor"), as_of=as_of, cycle_id=cycle)
    review = _claim(full_cycle_review, inputs.get("full_cycle_review"), as_of=as_of, cycle_id=cycle)

    # Only availability is synthesized. Neither lane declares its thesis true.
    valuation = {}
    facts = evidence_pack.get("asset_facts", {}).get("items", [])
    for asset in ("MSTR", "ASST"):
        matches = [r.get("evidence") for r in facts if isinstance(r, dict)
                   and r.get("fact_type") == "TREASURY_VALUATION_CONTEXT" and r.get("asset_id") == asset]
        treasury = matches[0] if len(matches) == 1 and isinstance(matches[0], dict) else {}
        treasury_ready = treasury.get("formal_action_critical_state") == "AVAILABLE"
        next_cycle = gold.get("next_cycle_valuation", {}).get(asset, {})
        convexity = gold.get("treasury_convexity", {}).get("assets", {}).get(asset, {})
        valuation[asset] = {"state": "READY_FOR_ANALYST" if treasury_ready or _available(next_cycle) else "BLOCKED",
            "treasury_valuation": {"source_hash": _hash(treasury), "state": "AVAILABLE" if treasury_ready else "BLOCKED"},
            "next_cycle_valuation": _ref(next_cycle, "Gold.next_cycle_valuation."+asset),
            "btc_convexity": _ref(convexity, "Gold.treasury_convexity."+asset),
            "source_contexts": {"treasury_valuation": deepcopy(treasury),
                                "next_cycle_valuation": deepcopy(next_cycle), "btc_convexity": deepcopy(convexity)},
            "limitation": "DATA_FOR_REVIEW_NOT_VALUATION_REALIZATION_CONFIRMATION"}
    overlay = evidence_pack.get("season_transition_warning_overlay", {})
    structure = {"state": "READY_FOR_ANALYST" if posture["state"] == "READY_FOR_ANALYST" else "BLOCKED",
                 "research_posture": deepcopy(posture), "transition_overlay": deepcopy(overlay),
                 "control_transfer": deepcopy(evidence_pack.get("btc_control_transfer_validation", {})),
                 "limitation": "RESEARCH_EVIDENCE_NOT_ROLLOVER_CONFIRMATION"}
    harvest = "READY_FOR_ANALYST" if structure["state"] == "READY_FOR_ANALYST" and all(
        row["state"] == "READY_FOR_ANALYST" for row in valuation.values()) else "BLOCKED"

    # Import the canonical list through its existing producer; no second gate list.
    gates = {}
    for name in posture["required_downstream_gates"]:
        if name == "ACTIVE_CAPITAL_PLAN_AND_AVAILABLE_TRANCHE":
            status, reason = "EXTERNAL_TO_CONTEXT", "NO_FORMAL_PLAN_TRANCHE_BINDING_CONSUMED"
        elif name == "QUALIFIED_COMMANDER_ATTACK_AND_DEFENSE_LINES":
            status, reason = "EXTERNAL_TO_CONTEXT", "EXISTING_COMMANDER_VALIDATION_OWNS_QUALIFICATION"
        elif name == "GPT_ANALYST_JUDGMENT":
            status, reason = "NOT_EVALUATED", "GPT_OWNED"
        elif name == "USER_DECISION":
            status, reason = "PENDING_USER_DECISION", "USER_ONLY"
        else:
            # No unbound caller-supplied PASS flags are accepted.
            source = {"LATEST_CAPITAL_STATE": current,
                      "ASSET_SPECIFIC_FACTS": health,
                      "BULL_FOUNDATION": evidence_pack.get("btc_bull_validation", {}),
                      "EXISTING_BTC_DECISION_SUPPORT": evidence_pack.get("btc_entry_gate", {})}.get(name)
            status = "AVAILABLE" if _available(source) else "BLOCKED"
            reason = "UPSTREAM_CONTEXT_AVAILABLE_NOT_GATE_PASS" if status == "AVAILABLE" else "NO_QUALIFICATION_INFERRED"
        gates[name] = {"status": status, "reason": reason}

    contradictions = []
    for asset, row in health.get("assets", {}).items():
        if isinstance(row, dict) and (row.get("health_direction") == "BLOCKED" or any(
                isinstance(d, dict) and (d.get("analyst_judgment_required") is True or d.get("interpretation_state") == "MIXED")
                for d in row.get("company_health", {}).get("dimensions", {}).values())):
            contradictions.append({"asset": asset, "reason": "HEALTH_REQUIRES_ANALYST", "source": deepcopy(row)})
    if _available(rail):
        upstream = [allocation.get("fixed_income_target_pct"), allocation.get("growth_target_pct")]
        # Compare doctrine anchors, never an intermediate analyst-owned step.
        expected = {"SPRING": [70, 30], "SUMMER_HOLD": [55, 45],
                    "AUTUMN_PRESERVATION": [80, 20]}.get(rail["current_rail_step"]["rail"])
        if expected is not None and all(type(v) in (int, float) for v in upstream) and upstream != expected:
            contradictions.append({"reason": "UPSTREAM_SEASON_ANCHOR_DOCTRINE_MISMATCH",
                                   "upstream_anchor_pct": upstream, "expected_anchor_pct": expected})
    watch = gold.get("assumption_watch", {})
    assumptions = watch.get("assumptions", [])
    challenged = [deepcopy(r) for r in assumptions if r.get("status") in {"CHALLENGED", "INVALIDATED"}]
    if _available(economics):
        ids = set(economics["provenance"]["assumption_ids"])
        linked = [r for r in assumptions if r.get("assumption_id") in ids]
        economics["assumption_watch_state"] = "READY_FOR_ANALYST" if (
            len({r.get("assumption_id") for r in linked}) == len(ids)
            and all(r.get("status") == "WATCHING" for r in linked)) else "BLOCKED"
        if any(r.get("assumption_id") in ids for r in challenged):
            economics.update(state="BLOCKED", reason="LINKED_ASSUMPTION_REQUIRES_RECALCULATION",
                             recalculation_required=True, flywheel_margin=None,
                             btc_opportunity_hurdle=None)
    # Do not run a second assumption evaluator or turn elapsed time into a trigger.
    maintenance = {"cadence": deepcopy(MAINTENANCE), "source": deepcopy(watch),
        "state": "READY_FOR_ANALYST" if _available(watch) else "BLOCKED",
        "recalculation_required": True if challenged else False if _available(watch) else None,
        "challenged_or_invalidated": challenged}
    momentum = overlay.get("evidence_momentum")
    proximity = {"state": "READY_FOR_ANALYST" if momentum in {"RISING", "FALLING", "FLAT", "MIXED"} else "BLOCKED",
        "upstream_evidence_momentum": deepcopy(momentum), "source": "season_transition_warning_overlay",
        "limitation": "UPSTREAM_DESCRIPTION_NOT_NEW_DISTANCE_SCORE_OR_TRANSITION_CONFIRMATION"}
    blockers = [name for name, value in (("CURRENT_RAIL", rail), ("OPERATING_ANCHOR", fund),
        ("FLYWHEEL_ECONOMICS", economics), ("GOLD_CONTEXT", {"state": "AVAILABLE" if gold_valid else "BLOCKED"}))
        if not _available(value)]
    output = {"schema_version": SCHEMA_VERSION, "storage": "LOCAL_ONLY", "research_state": "RESEARCH_ONLY",
        "state": "READY_FOR_ANALYST" if any(_available(v) for v in (rail, economics, fund, review)) else "BLOCKED",
        "as_of_ms": as_of, "cycle_id": cycle, "parent_evidence_pack_hash": parent_hash,
        "gold_context_hash": gold.get("context_hash"), "current_strategic_capital_posture": rail,
        "current_rail_step": rail.get("current_rail_step", "BLOCKED"),
        "eligible_next_posture": {"state": "NOT_EVALUATED", "final_eligibility": "NOT_DETERMINED",
                                  "research_candidate": posture["posture_candidate"],
                                  "strategic_destination": rail.get("next_strategic_destination")},
        "seasonal_capital_rails": deepcopy(RAILS), "research_posture_candidate": posture,
        "required_downstream_gates": list(posture["required_downstream_gates"]), "downstream_gate_status": gates,
        "valuation_realization_evidence": valuation, "structure_rollover_evidence": structure,
        "harvest_review_state": harvest, "harvest_judgment_status": "NOT_EVALUATED",
        "operating_fund": fund, "flywheel_economics": economics, "full_cycle_review": review,
        "winter_capital_split": _claim(_winter_split, current, fund),
        "maintenance": maintenance, "transition_proximity": proximity, "blockers": blockers,
        "contradictions": contradictions, "flywheel_path": list(FLYWHEEL),
        "supporting_evidence": {"company_health": deepcopy(health), "portfolio_allocation_source_hash": _hash(allocation)},
        "model_dependency_context": deepcopy(gold.get("model_dependency_map", {})),
        "dual_lane_limitation": "TWO_REVIEW_LANES_NOT_TWO_PROVEN_INDEPENDENT_SIGNALS_ANALYST_MUST_ASSESS_DEPENDENCIES",
        "portfolio_implication": {"current_allocation": deepcopy(current),
            "strategic_btc_context": deepcopy(allocation.get("strategic_btc_context", {})),
            "btc_acquisition_route_context": deepcopy(allocation.get("btc_acquisition_route_context", {})),
            "tactical_denominator": "FIXED_GROWTH_EXCLUDES_BTC_CORE",
            "winter_capital_purposes": ["NEXT_CYCLE_OPERATING_FUND", "BTC_ACCUMULATION_CAPITAL", "EXISTING_BTC_CORE"],
            "btc_core_automatic_spring_recycling": False,
            "asset_roles": {"MSTR": "GROWTH_AMPLIFICATION_AND_ANALYST_HARVEST_REVIEW",
                "ASST": "GROWTH_AMPLIFICATION_AND_ANALYST_HARVEST_REVIEW",
                "STRC": "PRESERVATION_CARRIER_SUBJECT_TO_EXISTING_ROLE_RULES",
                "SATA": "PRESERVATION_CARRIER_SUBJECT_TO_EXISTING_ROLE_RULES", "BTC": "STRATEGIC_CORE"},
            "limitation": "CURRENT_RAIL_REQUIRES_EXPLICIT_INPUT_NO_STATIC_SEASON_FALLBACK_OR_REBALANCE_ORDER"},
        "rail_constraints": ["QUALIFIED_PULLBACK_REQUIRES_ANALYST_REVIEW", "55_45_IS_MAXIMUM_NOT_QUOTA",
            "SUMMER_NO_PRICE_HIGH_OR_CALENDAR_HARVEST", "HARVEST_DUAL_LANE_ANALYST_JUDGMENT_REQUIRED",
            "AUTUMN_INHERITS_HARVEST_NO_AUTOMATIC_GROWTH_INCREASE", "WINTER_NOT_PANIC_LIQUIDATION"],
        "bridge_policy": "LOCAL_ONLY_NO_BRIDGE_BYTES_ADDED", **LOCKS}
    output["context_hash"] = _hash(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--evidence-pack", type=Path, required=True)
    parser.add_argument("--gold-context", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    sources = [p for p in (args.input, args.evidence_pack, args.gold_context) if p is not None]
    if args.output.resolve() in {p.resolve() for p in sources}:
        parser.error("local output must not overwrite an input")
    read = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    result = build_capital_posture_context(read(args.input), read(args.evidence_pack),
                                          read(args.gold_context) if args.gold_context else None)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
