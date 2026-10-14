"""CRT Q0: structural coverage audit for the existing GPT Analysis Doctrine.

This tool DOES NOT validate causal reasoning or authorize trading. It verifies
that a purported full analysis actually visits its required organs, binds the
claimed observations to an immutable Evidence Pack, and distinguishes absent
analysis from blocked source evidence. It is a report-review tool, not a second
season model or an alternate capital-decision engine.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

SCHEMA_VERSION = "CRT_Q0_COVERAGE_AUDIT_V0.1"
STATES = frozenset({"SOURCE_BOUND", "RESEARCH_ONLY", "BLOCKED", "NOT_RUN"})
ASSETS = ("MSTR", "ASST", "STRC", "SATA")
ACTIONS = frozenset({"BUY", "SELL", "HOLD", "WAIT", "ROTATE"})

# These are the existing Doctrine/Active-Baton responsibilities, NOT model layers.
ORGANS = {
    "BTC": (
        "cycle_context", "formal_season", "research_season", "q1_control_transfer",
        "L0", "L1", "L2", "L3", "L4", "L5", "L6", "gold_research",
    ),
    "MSTR": (
        "formal_mnav", "historical_mnav_position", "btc_per_diluted_share",
        "company_health", "market_health",
    ),
    "ASST": (
        "formal_mnav", "historical_mnav_position", "btc_per_diluted_share",
        "company_health", "market_health",
    ),
    "STRC": ("cash_income", "issuer_risk", "rotation_case"),
    "SATA": ("cash_income", "issuer_risk", "rotation_case"),
    "PORTFOLIO": (
        "dual_hairpin_six_month_cash", "dual_hairpin_capital_preservation",
        "confirmed_capital_state", "confirmed_seasonal_rail", "allocation_translation",
        "relative_opportunity_cost", "btc_acquisition_power", "capital_judgment",
    ),
}

# A reference into a real pack is necessary but never sufficient for formal
# source qualification or proof of the prose's causal interpretation.
ALLOWED_PATH_ROOTS = {
    "BTC": ("layers", "model_status", "btc_bull_validation", "btc_control_transfer_validation",
            "season_transition_warning_overlay", "btc_long_horizon_context", "reanalysis_wake",
            "changes", "distillation", "btc_etf_evidence", "assumption_watch", "institutional_flow_context"),
    "MSTR": ("asset_facts", "treasury_valuation_context", "common_equity_health",
             "mstr_asst_market_health", "issuer_ratio_observation", "qualified_equity_prices"),
    "ASST": ("asset_facts", "treasury_valuation_context", "common_equity_health",
             "mstr_asst_market_health", "issuer_ratio_observation", "qualified_equity_prices"),
    "STRC": ("asset_facts", "asset_strategy_delta", "issuer_announcement_wake",
             "portfolio_allocation_context", "qualified_equity_prices"),
    "SATA": ("asset_facts", "asset_strategy_delta", "issuer_announcement_wake",
             "portfolio_allocation_context", "qualified_equity_prices"),
    "PORTFOLIO": ("private_context", "portfolio_allocation_context", "plan_drift",
                  "asset_strategy_delta", "btc_long_horizon_context", "common_equity_health"),
}
REASONING_STEPS = (
    "catalyst", "amplifier", "persistence", "acceptance", "contradictions",
    "missing_evidence", "evidence_independence", "decision_asymmetry",
)
REVIEW_FIELDS = ("judgment", "contradictions", "capital_effect", "invalidation", "next_trigger")


def _hash_pack(pack: Mapping) -> str:
    raw = {k: v for k, v in pack.items() if k != "evidence_pack_hash"}
    data = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _meaningful(value) -> bool:
    return isinstance(value, str) and len(value.strip()) >= 6 and value.strip().lower() not in {
        "unknown", "blocked", "not run", "not_run", "pending", "none", "n/a", "待補充", "不知道",
    }


def _pointer(pack: Mapping, path: str):
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise ValueError("PATH_NOT_JSON_POINTER")
    node = pack
    for raw in path[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping):
            if token not in node:
                raise ValueError("PATH_NOT_IN_EVIDENCE_PACK")
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                raise ValueError("PATH_NOT_IN_EVIDENCE_PACK")
            node = node[int(token)]
        else:
            raise ValueError("PATH_NOT_IN_EVIDENCE_PACK")
    if node is None or node == "":
        raise ValueError("EMPTY_EVIDENCE_AT_PATH")
    return node


def audit_360_coverage(report: Mapping, evidence_pack: Mapping) -> dict:
    """Return fail-closed coverage state. Never grant a trading or reasoning receipt.

    Expected report is an independent, non-authoritative review manifest:
      evidence_pack_hash, analysis_as_of_ms,
      organs: {BTC: {L1: {state, judgment, contradictions, capital_effect,
                          invalidation, next_trigger, evidence_paths, blocked_reasons}, ...}, ...},
      reasoning: {catalyst: ..., ...},
      actions: {MSTR: {action, reason, invalidation, next_trigger}, ...}

    BLOCKED organs are allowed *if individually explained*; NOT_RUN organs and
    absent organs prevent any full-coverage claim. An all-BLOCKED report cannot
    masquerade as a finished cross-asset analysis.
    """
    problems: list[str] = []
    detail = {}
    if not isinstance(evidence_pack, Mapping) or not isinstance(report, Mapping):
        return {"schema_version": SCHEMA_VERSION, "coverage_state": "INCOMPLETE",
                "problems": ["REPORT_OR_PACK_NOT_OBJECT"], "reasoning_state": "NOT_YET_PROVEN",
                "may_claim_crt_360_complete": False, "external_action_authority": "NONE"}
    pack_time = evidence_pack.get("generated_at_ms")
    as_of = report.get("analysis_as_of_ms")
    if type(pack_time) is not int or pack_time <= 0:
        problems.append("EVIDENCE_PACK_CLOCK_INVALID")
    if (type(as_of) is not int or type(pack_time) is not int
            or as_of < pack_time):
        problems.append("REPORT_CLOCK_BEFORE_EVIDENCE_OR_INVALID")
    if (not isinstance(evidence_pack.get("evidence_pack_hash"), str)
            or evidence_pack.get("evidence_pack_hash") != _hash_pack(evidence_pack)
            or report.get("evidence_pack_hash") != evidence_pack.get("evidence_pack_hash")):
        problems.append("EVIDENCE_PACK_LINEAGE_INVALID")

    groups = report.get("organs")
    if not isinstance(groups, Mapping):
        groups = {}
        problems.append("ORGANS_SECTION_MISSING")
    any_source = False
    blocked = []
    not_run = []
    for group, keys in ORGANS.items():
        found = groups.get(group)
        if not isinstance(found, Mapping):
            found = {}
            problems.append("GROUP_MISSING:" + group)
        for key in keys:
            full = group + "." + key
            row = found.get(key)
            if not isinstance(row, Mapping):
                problems.append("ORGAN_MISSING:" + full)
                not_run.append(full)
                continue
            state = row.get("state")
            detail[full] = state
            if state not in STATES:
                problems.append("ORGAN_STATE_INVALID:" + full)
                continue
            if state == "NOT_RUN":
                problems.append("ORGAN_NOT_RUN:" + full)
                not_run.append(full)
                continue
            for name in REVIEW_FIELDS:
                if not _meaningful(row.get(name)):
                    problems.append("REVIEW_FIELD_MISSING:" + full + ":" + name)
            refs = row.get("evidence_paths", [])
            if not isinstance(refs, list) or any(not isinstance(x, str) for x in refs):
                problems.append("EVIDENCE_PATHS_NOT_LIST:" + full)
                refs = []
            if state == "BLOCKED":
                blocked.append(full)
                reasons = row.get("blocked_reasons")
                if (not isinstance(reasons, list) or not reasons
                        or any(not _meaningful(v) for v in reasons)):
                    problems.append("BLOCKED_WITHOUT_SPECIFIC_REASON:" + full)
            elif not refs:
                problems.append("SOURCE_BOUND_WITHOUT_SOURCE:" + full)
            if refs:
                if len(refs) != len(set(refs)):
                    problems.append("DUPLICATE_EVIDENCE_PATH:" + full)
                for path in refs:
                    root = path.split("/")[1] if path.startswith("/") else ""
                    if root not in ALLOWED_PATH_ROOTS[group]:
                        problems.append("EVIDENCE_ROOT_MISMATCH:" + full + ":" + path)
                        continue
                    try:
                        value = _pointer(evidence_pack, path)
                        if (state == "SOURCE_BOUND" and isinstance(value, Mapping)
                                and value.get("state") in {"BLOCKED", "UNBOUND_BLOCKED", "NOT_RUN"}):
                            problems.append("BLOCKED_SOURCE_MARKED_BOUND:" + full + ":" + path)
                        if state in {"SOURCE_BOUND", "RESEARCH_ONLY"}:
                            any_source = True
                    except ValueError as exc:
                        problems.append(str(exc) + ":" + full + ":" + path)

    reasoning = report.get("reasoning")
    if not isinstance(reasoning, Mapping):
        reasoning = {}
        problems.append("REASONING_SECTION_MISSING")
    for step in REASONING_STEPS:
        if not _meaningful(reasoning.get(step)):
            problems.append("REASONING_STEP_MISSING:" + step)
    actions = report.get("actions")
    if not isinstance(actions, Mapping):
        actions = {}
        problems.append("ACTIONS_SECTION_MISSING")
    for asset in ASSETS:
        row = actions.get(asset)
        if not isinstance(row, Mapping):
            problems.append("ACTION_MISSING:" + asset)
            continue
        if row.get("action") not in ACTIONS:
            problems.append("ACTION_INVALID:" + asset)
        for field in ("reason", "invalidation", "next_trigger"):
            if not _meaningful(row.get(field)):
                problems.append("ACTION_FIELD_MISSING:" + asset + ":" + field)
    if not any_source:
        problems.append("NO_INDEPENDENT_SOURCE_BOUND_ANALYSIS")

    state = ("INCOMPLETE" if problems else
             "REVIEWED_WITH_BLOCKERS" if blocked else "COVERAGE_READY_FOR_REASONING_REVIEW")
    return {
        "schema_version": SCHEMA_VERSION,
        "coverage_state": state,
        "organ_states": detail,
        "blocked_organs": blocked,
        "not_run_organs": not_run,
        "problems": sorted(set(problems)),
        "reasoning_state": "NOT_YET_PROVEN",
        "may_claim_crt_360_complete": False,  # cannot certify free-text investment reasoning
        "formal_season_authority": "NONE",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }


def main(argv=None) -> int:
    """Offline manual acceptance check; never performs notifications or trades."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Audit structural CRT 360 coverage (not causal correctness)")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--evidence-pack", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.report.open(encoding="utf-8") as stream:
            report = json.load(stream)
        with args.evidence_pack.open(encoding="utf-8") as stream:
            pack = json.load(stream)
        result = audit_360_coverage(report, pack)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {"schema_version": SCHEMA_VERSION, "coverage_state": "INCOMPLETE",
                  "problems": ["AUDIT_INPUT_INVALID:" + str(exc)],
                  "reasoning_state": "NOT_YET_PROVEN", "may_claim_crt_360_complete": False,
                  "external_action_authority": "NONE"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["coverage_state"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
