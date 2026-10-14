"""CRT Q0: offline publication gate connecting one Evidence Pack, analyst coverage,
and an independently validated capital recommendation receipt.

This is a *companion* publication audit; historical capital receipts are never
changed. It cannot approve production, causal reasoning, a season, or trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from .analysis_coverage_gate import (ASSETS, ORGANS, REASONING_STEPS,
    SCHEMA_VERSION as COVERAGE_SCHEMA, audit_360_coverage, _hash_pack)

SCHEMA_VERSION = "CRT_Q0_360_DELIVERY_V0.1"
QUALIFIED_ITEMS = frozenset(("VALIDATED", "VALIDATED_NON_TRADING_WAIT"))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sealed(value: Mapping, field: str) -> bool:
    if not isinstance(value, dict):
        return False
    stated = value.get(field)
    return isinstance(stated, str) and len(stated) == 64 and stated == digest({
        key: val for key, val in value.items() if key != field})


def _item_index(items, *, problems: list[str], label: str):
    result = {}
    if not isinstance(items, list):
        problems.append(label + "_MISSING")
        return result
    for item in items:
        if not isinstance(item, dict):
            problems.append(label + "_ROW_INVALID")
            continue
        scope, asset, action = (item.get("decision_scope"), item.get("asset"), item.get("action"))
        if (not isinstance(scope, str) or not scope or asset not in ASSETS or
                action not in {"BUY", "SELL", "HOLD", "WAIT", "ROTATE"}):
            problems.append(label + "_ROW_INVALID")
            continue
        if scope in result:
            problems.append(label + "_DUPLICATE_SCOPE")
            continue
        result[scope] = (asset, action)
    return result


def review_360_delivery(report: Mapping, pack: Mapping, capital_receipt: Mapping) -> dict:
    """Verify report-to-capital lineage, full scope coverage and structure.

    The receipt hash and validation hash demonstrate local *integrity* only.
    A caller must obtain the receipt from CRT's original validated-receipt path;
    hashes do not independently authenticate the issuer, broker or model.
    """
    problems = []
    if not isinstance(report, Mapping) or not isinstance(pack, Mapping):
        report, pack = {}, {}
        problems.append("REPORT_OR_PACK_MISSING")
    # Structural audit is always performed even if capital lineage fails.
    coverage = audit_360_coverage(report, pack)
    if not isinstance(capital_receipt, Mapping):
        capital_receipt = {}
        problems.append("CAPITAL_RECEIPT_MISSING")
    else:
        if not _sealed(capital_receipt, "receipt_hash"):
            problems.append("CAPITAL_RECEIPT_HASH_INVALID")
        if capital_receipt.get("state") != "RESPONSES_DELIVERY_RECEIPT_READY":
            problems.append("CAPITAL_RECEIPT_NOT_VALIDATED_DELIVERY")
        if (capital_receipt.get("production") != "NOT_APPROVED" or
                capital_receipt.get("external_action_authority") != "NONE" or
                capital_receipt.get("action_output") != "NONE"):
            problems.append("CAPITAL_RECEIPT_AUTHORITY_MISMATCH")

    validation = capital_receipt.get("capital_validation")
    if not isinstance(validation, Mapping):
        validation = {}
        problems.append("CAPITAL_VALIDATION_MISSING")
    elif not _sealed(validation, "validation_hash"):
        problems.append("CAPITAL_VALIDATION_HASH_INVALID")
    if validation.get("evidence_lineage") != pack.get("evidence_pack_hash"):
        problems.append("CAPITAL_PACK_LINEAGE_MISMATCH")
    if report.get("capital_receipt_hash") != capital_receipt.get("receipt_hash") or not report.get("capital_receipt_hash"):
        problems.append("REPORT_CAPITAL_RECEIPT_HASH_MISMATCH")
    if report.get("event_id") != capital_receipt.get("event_id") or not report.get("event_id"):
        problems.append("REPORT_EVENT_ID_MISMATCH")
    if (type(report.get("analysis_as_of_ms")) is not int or
            type(validation.get("evaluated_at_ms")) is not int or
            report["analysis_as_of_ms"] < validation["evaluated_at_ms"]):
        problems.append("REPORT_PRECEDES_CAPITAL_ASSESSMENT")

    recommendation = validation.get("recommendation")
    if not isinstance(recommendation, Mapping):
        recommendation = {}
        problems.append("CAPITAL_RECOMMENDATION_MISSING")
    recommended = _item_index(recommendation.get("items"), problems=problems,
                              label="CAPITAL_RECOMMENDATION")
    assessed = _item_index(validation.get("items"), problems=problems,
                           label="CAPITAL_VALIDATION")
    if recommended != assessed:
        problems.append("CAPITAL_ASSESSMENT_RECOMMENDATION_DIVERGENCE")
    for item in validation.get("items", []) if isinstance(validation.get("items"), list) else []:
        if (not isinstance(item, dict) or
                item.get("validation_state") not in QUALIFIED_ITEMS):
            problems.append("CAPITAL_SCOPE_NOT_QUALIFIED")

    # A single asset can legitimately have HOLD-existing and WAIT-addition.
    # Every decision scope is therefore checked, not reduced to one action.
    manifest = report.get("action_scopes")
    if not isinstance(manifest, list):
        manifest = []
        problems.append("ACTION_SCOPES_MISSING")
    analyzed = _item_index(manifest, problems=problems, label="ACTION_SCOPES")
    if recommended != analyzed:
        problems.append("REPORT_CAPITAL_ACTION_SCOPES_MISMATCH")
    for asset in ASSETS:
        scope_actions = {action for a, action in recommended.values() if a == asset}
        if not scope_actions:
            problems.append("CAPITAL_ASSET_SCOPE_MISSING:" + asset)
            continue
        row = report.get("actions", {}).get(asset) if isinstance(report.get("actions"), Mapping) else None
        # This is a primary-summary action; all additional scope actions must
        # still be enumerated exactly in action_scopes.
        if not isinstance(row, Mapping) or row.get("action") not in scope_actions:
            problems.append("REPORT_PRIMARY_ACTION_MISMATCH:" + asset)
    if not _sealed(capital_receipt, "receipt_hash") or not _sealed(validation, "validation_hash"):
        problems.append("CAPITAL_INTEGRITY_NOT_VERIFIED")

    problems = sorted(set(problems + coverage["problems"]))
    if problems:
        publication_state = "REJECTED"
    elif coverage["coverage_state"] == "REVIEWED_WITH_BLOCKERS":
        publication_state = "REVIEWED_WITH_BLOCKERS_Q5_PENDING"
    elif coverage["coverage_state"] == "COVERAGE_READY_FOR_REASONING_REVIEW":
        publication_state = "COVERAGE_READY_Q5_PENDING"
    else:
        publication_state = "REJECTED"
        problems.append("COVERAGE_INCOMPLETE")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "publication_state": publication_state,
        "source_evidence_pack_hash": pack.get("evidence_pack_hash"),
        "capital_receipt_hash": capital_receipt.get("receipt_hash"),
        "analysis_report_hash": digest(report),
        "event_id": capital_receipt.get("event_id"),
        "coverage_schema": COVERAGE_SCHEMA,
        "coverage_state": coverage["coverage_state"],
        "blocked_organs": coverage["blocked_organs"],
        "not_run_organs": coverage["not_run_organs"],
        "validated_action_scopes": [
            {"decision_scope": scope, "asset": asset, "action": action}
            for scope, (asset, action) in sorted(recommended.items())
        ] if not problems else [],
        "problems": sorted(set(problems)),
        "capital_source_integrity": "SELF_CONSISTENT_ONLY" if not problems else "NOT_VERIFIED",
        "reasoning_state": "NOT_YET_PROVEN",
        "may_claim_crt_360_complete": False,
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
        "machine_execution": "FORBIDDEN",
    }
    receipt["review_receipt_hash"] = digest(receipt)
    return receipt


def initialize_360_manifest(pack: Mapping, capital_receipt: Mapping) -> dict:
    """Generate a complete NOT_RUN scaffold; never synthesize analyst conclusions.

    The manifest is usable only with the same validated capital receipt and
    Evidence Pack. An analyst must actually review and fill every organ.
    """
    if (not isinstance(pack, Mapping) or not isinstance(capital_receipt, Mapping)
            or pack.get("evidence_pack_hash") != _hash_pack(pack)
            or not _sealed(capital_receipt, "receipt_hash")
            or capital_receipt.get("state") != "RESPONSES_DELIVERY_RECEIPT_READY"
            or capital_receipt.get("production") != "NOT_APPROVED"
            or capital_receipt.get("external_action_authority") != "NONE"
            or capital_receipt.get("action_output") != "NONE"):
        raise ValueError("SOURCE_INTEGRITY_NOT_VERIFIED")
    validation = capital_receipt.get("capital_validation")
    if (not isinstance(validation, Mapping) or not _sealed(validation, "validation_hash")
            or validation.get("evidence_lineage") != pack.get("evidence_pack_hash")):
        raise ValueError("CAPITAL_LINEAGE_NOT_VERIFIED")
    recommendation = validation.get("recommendation")
    if not isinstance(recommendation, Mapping):
        raise ValueError("CAPITAL_RECOMMENDATION_REQUIRED")
    errs = []
    rows = _item_index(recommendation.get("items"), problems=errs, label="RECOMMENDATION")
    assessed = _item_index(validation.get("items"), problems=errs, label="VALIDATION")
    if rows != assessed or errs or any(not isinstance(item, Mapping) or
                    item.get("validation_state") not in QUALIFIED_ITEMS
                    for item in validation.get("items", [])):
        raise ValueError("CAPITAL_SCOPES_NOT_VALIDATED")
    primary = {}
    for asset in ASSETS:
        selections = sorted((scope, action) for scope,(a,action) in rows.items() if a == asset)
        if not selections:
            raise ValueError("CAPITAL_FOUR_ASSETS_REQUIRED")
        primary[asset] = {"action": selections[0][1], "reason": "NOT_RUN",
                          "invalidation": "NOT_RUN", "next_trigger": "NOT_RUN"}
    # Reference all known decision scopes; separate existing vs addition.
    return {"manifest_schema": "CRT_Q0_360_MANIFEST_V0.1",
            "event_id": capital_receipt["event_id"],
            "capital_receipt_hash": capital_receipt["receipt_hash"],
            "evidence_pack_hash": pack["evidence_pack_hash"],
            "analysis_as_of_ms": max(pack["generated_at_ms"], validation["evaluated_at_ms"]),
            "organs": {group: {name: {"state": "NOT_RUN"} for name in organs}
                        for group, organs in ORGANS.items()},
            "reasoning": {key: "NOT_RUN" for key in REASONING_STEPS},
            "actions": primary,
            "action_scopes": [{"decision_scope": scope, "asset": asset, "action": action}
                              for scope, (asset,action) in sorted(rows.items())]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CRT Q0 360 publication preflight; no notification or trade")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--initialize-report", action="store_true",
                        help="Create NOT_RUN template bound to real pack and capital receipt")
    parser.add_argument("--evidence-pack", required=True, type=Path)
    parser.add_argument("--capital-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        print("Q0_360_STOP: OUTPUT_EXISTS_NO_OVERWRITE")
        return 2
    try:
        if not args.initialize_report and args.report is None:
            raise ValueError("REPORT_REQUIRED")
        pack = json.loads(args.evidence_pack.read_text(encoding="utf-8"))
        capital = json.loads(args.capital_receipt.read_text(encoding="utf-8"))
        if args.initialize_report:
            if args.report is not None:
                raise ValueError("REPORT_MUST_BE_OMITTED_FOR_INITIALIZE")
            receipt = initialize_360_manifest(pack, capital)
        else:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            receipt = review_360_delivery(report, pack, capital)
        # Exclusive create, no overwrite; never copy private source records.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as f:
            json.dump(receipt, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.write("\n")
    except (OSError, ValueError, TypeError, OverflowError):
        print("Q0_360_STOP: INPUT_INVALID")
        return 2
    if args.initialize_report:
        print("Q0_360_MANIFEST_CREATED_ALL_ORGANS_NOT_RUN")
        print("Q0_360_MANIFEST=" + str(args.output))
        return 0
    print("Q0_360_" + receipt["publication_state"])
    print("Q0_360_REVIEW_RECEIPT=" + str(args.output))
    return 2 if receipt["publication_state"] == "REJECTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
