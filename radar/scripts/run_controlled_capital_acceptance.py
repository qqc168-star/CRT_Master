"""Repository-only synthetic capital acceptance; default preflight never sends.

The synthetic replay clock is distinct from the actual execution clock. Nothing
here reads a private profile, broker socket, account, credentials file or daily
outbox. A real request requires a separately supplied exact one-shot approval.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

RADAR = Path(__file__).resolve().parents[1]
for location in (RADAR, RADAR / "src", RADAR / "tests"):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))

from crt_radar import capital_decision_closure as capital
from crt_radar import gpt_transport_worker as worker
from crt_radar.broker_capital_observation import reconcile_capital
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_handoff import build_full_decision_bridge_payload, run_gpt_handoff_gate
from crt_radar.gpt_notification_boundary import present_from_transport
from crt_radar.gpt_transport_boundary import _read_json, _write_no_clobber
from crt_radar.openai_responses_adapter_contract import API_KEY_ENV_VAR, SMOKE_MODEL, validate_request_envelope
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.treasury_company_ct import build_treasury_valuation_context

CASE_VERSION = "CRT_CONTROLLED_SYNTHETIC_CAPITAL_CASE_V0.1"
APPROVAL_VERSION = "CRT_CONTROLLED_CAPITAL_APPROVAL_V0.1"
INPUT_USD_PER_MILLION = Decimal("0.20")
OUTPUT_USD_PER_MILLION = Decimal("1.20")
PRICING_SOURCE = "https://developers.openai.com/api/docs/models/gpt-5.6-luna"


def synthetic_case(*, at_ms: int, source_main_sha: str) -> dict:
    """Use existing synthetic scaffolding, never captured public/live fixtures."""
    from tests.test_capital_decision_closure import source_fixture
    from tests.test_gpt_handoff import bridge_pack, pack

    if type(at_ms) is not int or at_ms <= 0 or not re.fullmatch(r"[0-9a-f]{40}", source_main_sha):
        raise ValueError("Synthetic snapshot clock/main identity required")
    source = source_fixture(at=at_ms)
    source["source_main_sha"] = source_main_sha
    source["posture"].update(formal_season="NOT_DETERMINED", rail="RESEARCH_ONLY",
        research_state="SYNTHETIC_REPLAY_ONLY", context_hash=capital.digest({"fixture": CASE_VERSION}))
    source["task"]["scopes"] = [
        {"decision_scope": "MSTR-addition", "asset": "MSTR", "exposure": "PROPOSED_CHANGE"},
        {"decision_scope": "STRC-addition", "asset": "STRC", "exposure": "PROPOSED_CHANGE"},
        {"decision_scope": "MSTR-existing", "asset": "MSTR", "exposure": "EXISTING"},
    ]
    evidence = bridge_pack(pack(evidence_hash="a" * 64, requested=True))
    evidence["generated_at_ms"] = at_ms
    # Replace the scaffold's fake private sentinel fields with the same synthetic
    # broker/intent snapshot that supplies the capital decision source.
    intent = {key: source["user_intent"][key] for key in ("source", "confirmed_at_ms", "reserved_usd")}
    intent["plan_policy"] = "CANCEL_ALL_NO_REPLACEMENT"
    reconciliation = reconcile_capital(source["broker_observation"], intent, at_ms=at_ms)
    evidence["private_context"] = {"state": "AVAILABLE", "profile": {
        "capital_reconciliation": reconciliation,
        "strc": {"shares": 75, "current_annual_distribution_rate": 0.10},
        "derived": {"six_month_cash_usd": 375, "minimum_shares_for_target": 75}}}
    evidence["layers"] = {f"L{i}": {"status": "VALID", "metrics": {
        f"synthetic_layer_{i}_direction": {"value": i / 10, "as_of_ms": at_ms,
            "quality_state": "VALID_FRESH", "source_id": "SYNTHETIC_FIXTURE_ONLY"}}}
        for i in range(1, 7)}
    evidence["changes"] = {"synthetic_market_direction": {"horizons": {
        "1d": {"history_state": "AVAILABLE", "percent_change": -2.5}}}}
    evidence["distillation"] = {"note": "合成市場與合成資本，僅供受控契約驗收；不是實際投資證據。"}
    evidence["asset_facts"] = {"items": [{"asset_id": asset,
        "fact_type": "TREASURY_VALUATION_CONTEXT", "evidence":
        build_treasury_valuation_context(asset_id=asset, as_of_ms=at_ms)} for asset in ("MSTR", "ASST")]}
    evidence["evidence_pack_hash"] = capital.digest({key: value for key, value in evidence.items()
                                                   if key != "evidence_pack_hash"})
    with tempfile.TemporaryDirectory() as temporary:
        handoff = run_gpt_handoff_gate(evidence, build_plain_language_notice(evidence),
            ledger_path=Path(temporary) / "synthetic-handoff.jsonl", full_decision=True)
        payload = build_full_decision_bridge_payload(evidence, handoff)
    source["bridge_payload_hash"] = payload["bridge_payload_hash"]
    source["evidence_lineage"] = payload["event"]["source_evidence_pack_hash"]
    envelope = capital.build_envelope(payload, source, at_ms=at_ms, full_decision=True)
    result = {"contract_version": CASE_VERSION, "data_scope": "SYNTHETIC_MARKET_AND_CAPITAL_ONLY",
        "evaluation_clock": "SYNTHETIC_SNAPSHOT_REPLAY", "snapshot_at_ms": at_ms,
        "source_main_sha": source_main_sha, "payload": payload, "source": source, "envelope": envelope}
    result["case_hash"] = capital.digest(result)
    return result


def validate_case(case: dict) -> dict:
    expected = synthetic_case(at_ms=case["snapshot_at_ms"], source_main_sha=case["source_main_sha"])
    if case != expected:
        raise ValueError("Controlled acceptance requires the exact generated synthetic fixture")
    validate_request_envelope(case["envelope"])
    worker.validate_transport_payload(case["payload"])
    return case


def preflight(root: Path, *, source_main_sha: str, at_ms: int | None = None) -> dict:
    destination = root / "synthetic-case.json"
    case = (_read_json(destination) if destination.exists() else
            synthetic_case(at_ms=int(time.time() * 1000) if at_ms is None else at_ms,
                           source_main_sha=source_main_sha))
    validate_case(case)
    if case["source_main_sha"] != source_main_sha:
        raise ValueError("Controlled acceptance source main changed")
    if not destination.exists():
        _write_no_clobber(destination, case)
    body = case["envelope"]["request_body"]
    # This conservative byte-based planning figure is not a tokenizer or a
    # measured model token count. It creates no new formal input ceiling.
    planning_input_units = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    cost_estimate = (Decimal(planning_input_units) * INPUT_USD_PER_MILLION +
                     Decimal(body["max_output_tokens"]) * OUTPUT_USD_PER_MILLION) / Decimal(1_000_000)
    return {"state": "PRECHECK_READY_HUMAN_APPROVAL_REQUIRED", "mode": "PREFLIGHT_NO_NETWORK",
        "case_hash": case["case_hash"], "request_hash": case["envelope"]["request_hash"],
        "model": body["model"], "max_calls": 1, "data_scope": case["data_scope"],
        "full_contract_version": case["envelope"]["contract_version"],
        "projection_utf8_bytes": case["envelope"]["measurement"]["projection_utf8_bytes"],
        "request_body_utf8_bytes": case["envelope"]["measurement"]["request_body_utf8_bytes"],
        "formal_input_capacity": "NOT_APPROVED", "production": "NOT_APPROVED",
        "external_action_authority": "NONE", "daily_auto_send_enabled": False,
        "model_tokens": "NOT_MEASURED", "model_cost": "NOT_MEASURED",
        "model_comprehension": "NOT_YET_PROVEN", "network_performed": False,
        "credential_available": bool(os.environ.get(API_KEY_ENV_VAR, "").strip()),
        "cost_estimate_usd": str(cost_estimate), "cost_estimate_basis": "CONSERVATIVE_UTF8_BYTES_NOT_MEASURED_TOKENS",
        "pricing_source": PRICING_SOURCE, "max_output_tokens": body["max_output_tokens"]}


def validate_approval(approval: dict, case: dict, *, now_ms: int) -> None:
    expected_fields = {"contract_version", "source", "approved", "model", "request_hash",
        "case_hash", "max_calls", "max_cost_usd", "approved_at_ms", "expires_at_ms"}
    if (not isinstance(approval, dict) or set(approval) != expected_fields
            or approval["contract_version"] != APPROVAL_VERSION
            or approval["source"] != "USER_EXPLICIT_APPROVAL" or approval["approved"] is not True
            or approval["model"] != SMOKE_MODEL or approval["request_hash"] != case["envelope"]["request_hash"]
            or approval["case_hash"] != case["case_hash"] or type(approval["max_calls"]) is not int
            or approval["max_calls"] != 1 or type(approval["approved_at_ms"]) is not int
            or type(approval["expires_at_ms"]) is not int
            or not 0 < approval["approved_at_ms"] <= now_ms < approval["expires_at_ms"]):
        raise ValueError("Explicit exact one-shot controlled model approval required")
    if type(approval["max_cost_usd"]) not in (str, int, float):
        raise ValueError("Explicit approved USD cost ceiling required")
    ceiling = Decimal(str(approval["max_cost_usd"]))
    body = case["envelope"]["request_body"]
    estimated = (Decimal(len(json.dumps(body, ensure_ascii=False).encode("utf-8"))) * INPUT_USD_PER_MILLION +
                 Decimal(body["max_output_tokens"]) * OUTPUT_USD_PER_MILLION) / Decimal(1_000_000)
    if not ceiling.is_finite() or ceiling <= 0 or estimated > ceiling:
        raise ValueError("Controlled model estimate exceeds approved cost ceiling")


def simulated_response(case: dict) -> dict:
    from tests.test_capital_decision_closure import item, leg, provider_response, recommendation
    response = provider_response(recommendation(
        item("WAIT", wait_kind="EVIDENCE_BLOCKED", blockers=["valuation:MSTR:FORMAL_INPUTS_MISSING"],
             reason="合成情境：正式估值缺失，不得買入，等待補證據。"),
        item("BUY", asset="STRC", scope="STRC-addition", legs=[leg(asset="STRC")]),
        item("HOLD", scope="MSTR-existing")))
    return response


def execute(root: Path, *, mode: str, approval: dict | None = None,
            offline_response: dict | None = None) -> dict:
    if mode not in {"OFFLINE_SIMULATION", "CONTROLLED_REAL_REQUEST"}:
        raise ValueError("Unknown controlled acceptance mode")
    case = validate_case(_read_json(root / "synthetic-case.json"))
    actual_now = int(time.time() * 1000)
    if mode == "CONTROLLED_REAL_REQUEST":
        if offline_response is not None:
            raise ValueError("Mock response cannot be recorded as real acceptance")
        validate_approval(approval, case, now_ms=actual_now)
        if not os.environ.get(API_KEY_ENV_VAR, "").strip():
            raise ValueError("Provider credential unavailable; no controlled call attempted")

    destination = root / mode
    enqueue_bridge_payload(destination / "outbox", case["payload"])
    event_id = case["envelope"]["event_id"]

    def transport(envelope):
        if envelope != case["envelope"]:
            raise ValueError("Controlled request identity changed")
        if mode == "OFFLINE_SIMULATION":
            return deepcopy(offline_response if offline_response is not None else simulated_response(case))
        validate_case(case)
        validate_approval(approval, case, now_ms=int(time.time() * 1000))
        # Persist the single approved attempt before the shared HTTP sender.
        # Any ambiguous response stays in the existing reconciliation state.
        _write_no_clobber(destination / "controlled-call-intent.json", {
            "case_hash": case["case_hash"], "request_hash": envelope["request_hash"],
            "approval_hash": capital.digest(approval), "mode": "CONTROLLED_REAL_REQUEST", "max_calls": 1})
        response = worker._post_response(envelope)
        if not isinstance(response, worker._ProviderHTTPResponse):
            raise ValueError("Injected mock is not evidence of a real HTTP model response")
        _write_no_clobber(destination / "controlled-http-result.json", {
            "case_hash": case["case_hash"], "request_hash": envelope["request_hash"],
            "approval_hash": capital.digest(approval), "response_hash": capital.digest(response)})
        return response

    result = worker.deliver_event(destination / "outbox" / f"{event_id}.json", destination / "transport",
        notification_state_dir=destination / "notifications", capital_source=case["source"],
        current_main_sha=case["source_main_sha"], now_ms=case["snapshot_at_ms"], transport=transport)
    presentations = []
    notification_results = [present_from_transport(path, destination / "transport",
        lambda text: presentations.append(text) or 1, now_ms=case["snapshot_at_ms"],
        current_capital_source=case["source"]) for path in sorted((destination / "notifications").glob("*.json"))]
    report = {"mode": mode, "execution_at_ms": actual_now, "data_scope": case["data_scope"],
        "evaluation_clock": case["evaluation_clock"], "case_hash": case["case_hash"],
        "request_hash": case["envelope"]["request_hash"], "delivery": result,
        "notification_results": notification_results, "presented_text": presentations,
        "model_tokens": "NOT_MEASURED", "model_cost": "NOT_MEASURED",
        "model_comprehension": "NOT_YET_PROVEN", "real_model_acceptance": "NOT_MEASURED",
        "production": "NOT_APPROVED", "external_action_authority": "NONE"}
    if mode == "CONTROLLED_REAL_REQUEST":
        evidence_path = destination / "transport" / capital.FULL_REQUEST_VERSION / "responses" / f"{event_id}.json"
        provenance_path = destination / "controlled-http-result.json"
        if evidence_path.exists() and provenance_path.exists():
            response = _read_json(evidence_path)["response"]
            provenance = _read_json(provenance_path)
            if provenance != {"case_hash": case["case_hash"], "request_hash": case["envelope"]["request_hash"],
                    "approval_hash": capital.digest(approval), "response_hash": capital.digest(response)}:
                raise ValueError("Controlled HTTP provenance mismatch")
            report["provider_response"] = response
            report["real_model_acceptance"] = "CONTRACT_PASSED" if result["notification_eligible"] else "CONTRACT_FAILED"
            usage = response.get("usage", {})
            inputs, outputs = usage.get("input_tokens"), usage.get("output_tokens")
            if type(inputs) is int and type(outputs) is int and inputs >= 0 and outputs >= 0:
                report["model_tokens"] = {"input_tokens": inputs, "output_tokens": outputs}
                report["model_cost"] = {"usd_upper_bound_from_reported_usage": str(
                    (Decimal(inputs) * INPUT_USD_PER_MILLION + Decimal(outputs) * OUTPUT_USD_PER_MILLION) /
                    Decimal(1_000_000)), "invoice_cost": "NOT_MEASURED", "pricing_source": PRICING_SOURCE}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--source-main-sha", required=True)
    parser.add_argument("--mode", choices=("preflight", "simulate", "approved-real"), default="preflight")
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args(argv)
    summary = preflight(args.state_dir, source_main_sha=args.source_main_sha)
    if args.mode != "preflight":
        approval = _read_json(args.approval_file) if args.approval_file else None
        summary = execute(args.state_dir, mode="OFFLINE_SIMULATION" if args.mode == "simulate" else
            "CONTROLLED_REAL_REQUEST", approval=approval)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("delivery", {}).get("state", "PRECHECK_READY") in {
        "PRECHECK_READY", "DELIVERED", "ALREADY_DELIVERED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
