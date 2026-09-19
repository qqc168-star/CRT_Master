"""GPT-authored lines to the existing observation-only Commander operator.

Source bundles bind the source checkout SHA, evidence, handoff and Work B inputs
before GPT judgment. Work B remains research-only, never capital eligibility.
No line is inferred, no broker interface is introduced, and no monitor is armed
until the candidate is revalidated against the current source bundle and time.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .commander_plan_adapter import (
    CommanderPlanBlocked, REQUIRED_GOVERNANCE, REQUIRED_LINE_FIELDS,
    seal_commander_plan, validate_commander_plan,
)
from .deployment_posture_research_gate import translate_research_state_to_posture_constraints
from .gpt_handoff import SCHEMA_VERSION as HANDOFF_SCHEMA_VERSION
from .ibkr_commander_operator import run_gate6c3_operator
from .ibkr_live_market_data_intake import IbkrIntakeConfig, NativeIbkrFeed
from .premarket_battle_map import build_premarket_battle_map
from .premarket_evidence_binding import build_premarket_evidence_binding
from .premarket_equity_live_snapshot import validate_equity_live_snapshot
from .premarket_live_market_handoff import apply_live_market_handoff_to_asset_facts

BUNDLE_SCHEMA = "CRT_COMMANDER_SOURCE_BUNDLE_V0.1"
JUDGMENT_SCHEMA = "CRT_GPT_COMMANDER_JUDGMENT_V0.1"
CANDIDATE_SCHEMA = "CRT_GPT_COMMANDER_CANDIDATE_V0.1"
AUTHORITY = {**REQUIRED_GOVERNANCE, "production": "NOT_APPROVED"}
JUDGMENT_FIELDS = {
    "schema_version", "state", "judgment_id", "asset", "generated_at", "valid_until",
    "source_main_sha", "source_bundle_hash", "posture_candidate", "lines", "governance",
}
LINE_FIELDS = set(REQUIRED_LINE_FIELDS) | {"btc_condition", "confirmation_condition", "rationale"}
BUNDLE_FIELDS = {
    "schema_version", "source_main_sha", "evidence_pack", "handoff",
    "research_evaluation", "posture_gate", "bundle_hash", "governance",
}


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CommanderPlanBlocked([reason])


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sealed(value: dict, field: str, extras: tuple[str, ...] = ()) -> bool:
    material = {k: v for k, v in value.items() if k not in (field, *extras)}
    return value.get(field) == _hash(material)


def _timestamp(value: Any) -> datetime:
    _require(isinstance(value, str), "INVALID_TIMESTAMP")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(result.tzinfo is not None, "TIMESTAMP_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)


def _text(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().upper() not in {"UNKNOWN", "BLOCKED", "NONE", "NULL"})


def _authority_scan(value: Any) -> None:
    # Reject authority overrides at every nesting depth, including extra metadata.
    locks = {**AUTHORITY, "external_action_performed": False,
             "machine_may_execute_trade": False, "transport_authority": "NONE",
             "transport_performed": False, "trading_authority": "NONE",
             "formal_season_authority": "NONE", "season_transition_authority": "NONE"}
    if isinstance(value, dict):
        for key, child in value.items():
            if key in locks:
                expected = locks[key]
                _require(type(child) is type(expected) and child == expected,
                         "AUTHORITY_VIOLATION:" + key)
            _authority_scan(child)
    elif isinstance(value, list):
        for child in value:
            _authority_scan(child)


def build_commander_source_bundle(*, source_main_sha: str, evidence_pack: dict,
        handoff: dict, research_evaluation: dict, posture_gate: dict) -> dict:
    """Bind original source checkout provenance before requesting GPT judgment.

    source_main_sha is the independently verified checkout used for these inputs,
    not a replacement SHA assigned to old evidence when main changes. This local
    hash seal detects mutation; it is not a signature or a capital approval.
    """
    bundle = deepcopy({"schema_version": BUNDLE_SCHEMA, "source_main_sha": source_main_sha,
        "evidence_pack": evidence_pack, "handoff": handoff,
        "research_evaluation": research_evaluation, "posture_gate": posture_gate,
        "governance": AUTHORITY})
    try:
        bundle["bundle_hash"] = _hash(bundle)
        _validate_bundle(bundle)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise CommanderPlanBlocked(["SOURCE_BUNDLE_INVALID:" + str(exc)]) from exc
    return bundle


def _validate_bundle(bundle: Any) -> None:
    _require(isinstance(bundle, dict) and set(bundle) == BUNDLE_FIELDS,
             "SOURCE_BUNDLE_SCHEMA_MISMATCH")
    _require(bundle["schema_version"] == BUNDLE_SCHEMA, "SOURCE_BUNDLE_SCHEMA_MISMATCH")
    _require(isinstance(bundle["source_main_sha"], str)
             and re.fullmatch(r"[0-9a-f]{40}", bundle["source_main_sha"]) is not None,
             "SOURCE_MAIN_SHA_INVALID")
    _require(bundle["governance"] == AUTHORITY, "SOURCE_BUNDLE_GOVERNANCE_MISMATCH")
    _authority_scan(bundle)
    _require(_sealed(bundle, "bundle_hash"), "SOURCE_BUNDLE_HASH_MISMATCH")
    pack, handoff = bundle["evidence_pack"], bundle["handoff"]
    _require(isinstance(pack, dict) and pack.get("schema_version") == "CRT_EVIDENCE_PACK_V0.2",
             "EVIDENCE_SCHEMA_MISMATCH")
    _require(_sealed(pack, "evidence_pack_hash"), "EVIDENCE_HASH_MISMATCH")
    _require(pack.get("action_output") == "NONE", "EVIDENCE_AUTHORITY_MISSING")
    authority = pack.get("authority", {})
    for key, expected in {"production": "NOT_APPROVED", "external_action_authority": "NONE",
                          "external_action_performed": False,
                          "capital_decision_authority": "USER_ONLY"}.items():
        _require(type(authority.get(key)) is type(expected) and authority.get(key) == expected,
                 "EVIDENCE_AUTHORITY_MISMATCH:" + key)
    _require(pack.get("pack_state") in ("READY_FOR_ANALYST", "PARTIAL_FOR_ANALYST"),
             "EVIDENCE_NOT_READY")
    _require(pack.get("data_health", {}).get("critical_blockers") == [],
             "EVIDENCE_CRITICAL_BLOCKERS")
    _require(isinstance(handoff, dict) and handoff.get("schema_version") == HANDOFF_SCHEMA_VERSION,
             "HANDOFF_SCHEMA_MISMATCH")
    _require(handoff.get("state") == "GPT_HANDOFF_READY", "HANDOFF_NOT_READY")
    for key, expected in {"action_output": "NONE", "external_action_authority": "NONE",
                          "external_action_performed": False,
                          "transport_authority": "NONE", "transport_performed": False}.items():
        _require(type(handoff.get(key)) is type(expected) and handoff.get(key) == expected,
                 "HANDOFF_AUTHORITY_MISMATCH:" + key)
    _require(_sealed(handoff, "handoff_hash", ("append_status", "ledger_record_hash", "bridge_outbox")),
             "HANDOFF_HASH_MISMATCH")
    _require(handoff.get("source_evidence_pack_hash") == pack["evidence_pack_hash"],
             "HANDOFF_EVIDENCE_LINEAGE_MISMATCH")
    canonical = translate_research_state_to_posture_constraints(bundle["research_evaluation"])
    _require(canonical["state"] == "READY_FOR_ANALYST", "POSTURE_NOT_READY")
    _require(bundle["posture_gate"] == canonical, "POSTURE_LINEAGE_MISMATCH")


def _asset_facts(bundle: dict, asset: str, check_time: datetime) -> dict:
    pack = bundle["evidence_pack"]
    market = pack.get("premarket_market_data", {})
    battle = market.get("battle_map", {})
    handoff = battle.get("live_market_handoff")
    _require(isinstance(handoff, dict) and handoff.get("source_mode") == "MACHINE_VERIFIED_ONLY",
             "MACHINE_MARKET_EVIDENCE_REQUIRED")
    _require(market.get("live_market_handoff") == handoff, "MARKET_LINEAGE_MISMATCH")
    source_binding = handoff.get("machine_equity_source_binding", {})
    end_ms = int(check_time.timestamp() * 1000)
    validate_equity_live_snapshot(handoff.get("machine_equity_snapshot"),
        source_binding=source_binding, evaluation_window={
            "start_ms": end_ms - source_binding["max_age_seconds"] * 1000,
            "end_ms": end_ms,
        })
    supplied = battle.get("asset_facts", {})
    mnav = {a: supplied.get(a, {}).get("diluted_mnav") for a in ("MSTR", "ASST")}
    binding = build_premarket_evidence_binding(reflexivity_overlay=pack,
        evaluation_window=handoff.get("evaluation_window"), mnav_results=mnav)
    facts = apply_live_market_handoff_to_asset_facts(binding["asset_facts"], handoff)
    contract = json.loads((Path(__file__).resolve().parents[2] / "CONFIG" /
        "PREMARKET_BATTLE_MAP_CONTRACT_V0.1.json").read_text(encoding="utf-8"))
    rebuilt = build_premarket_battle_map(contract=contract, asset_facts=facts,
        issuer_reflexivity=binding["issuer_reflexivity"], as_of=battle.get("as_of"),
        source_mode="MACHINE_VERIFIED_ONLY", live_market_handoff=handoff)
    _require(battle.get("contract_version") == rebuilt["contract_version"], "BATTLE_MAP_SCHEMA_MISMATCH")
    readiness = rebuilt["asset_fact_readiness"][asset]
    _require(battle.get("asset_fact_readiness", {}).get(asset) == readiness,
             "ASSET_READINESS_LINEAGE_MISMATCH")
    _require(readiness["state"] == "AVAILABLE", "ASSET_FACTS_NOT_READY")
    for field in contract["required_facts"][asset]:
        fact = facts[asset].get(field)
        _require(isinstance(fact, dict) and fact.get("state") == "AVAILABLE",
                 "ACTION_CRITICAL_FACT_NOT_AVAILABLE:" + field)
        _require(supplied.get(asset, {}).get(field) == fact, "ASSET_FACT_LINEAGE_MISMATCH:" + field)
    if asset in ("MSTR", "ASST"):
        for field in ("premarket_price", "btc_holdings_current", "diluted_shares", "btc_per_diluted_share"):
            value = facts[asset][field].get("value")
            _require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                     "ACTION_CRITICAL_FACT_INVALID:" + field)
    return readiness


def build_candidate_commander_plan(judgment: Any, *, source_bundle: Any,
        current_main_sha: str, now: datetime | None = None) -> dict:
    """Validate GPT-authored observation lines; return an unsealed candidate."""
    try:
        return _build_candidate(judgment, source_bundle, current_main_sha, now)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise CommanderPlanBlocked(["CANDIDATE_SCHEMA_INVALID:" + str(exc)]) from exc


def _build_candidate(judgment: Any, bundle: Any, current_main_sha: str,
                     now: datetime | None) -> dict:
    _validate_bundle(bundle)
    _require(bundle["source_main_sha"] == current_main_sha, "SOURCE_MAIN_LINEAGE_MISMATCH")
    _require(isinstance(judgment, dict) and set(judgment) == JUDGMENT_FIELDS,
             "JUDGMENT_SCHEMA_MISMATCH")
    _require(judgment["schema_version"] == JUDGMENT_SCHEMA, "JUDGMENT_SCHEMA_MISMATCH")
    _require(judgment["state"] == "READY_FOR_VALIDATION", "JUDGMENT_NOT_READY")
    _require(judgment["governance"] == AUTHORITY, "JUDGMENT_GOVERNANCE_MISMATCH")
    _authority_scan(judgment)
    _require(judgment["source_main_sha"] == current_main_sha, "JUDGMENT_MAIN_LINEAGE_MISMATCH")
    _require(judgment["source_bundle_hash"] == bundle["bundle_hash"], "JUDGMENT_EVIDENCE_LINEAGE_MISMATCH")
    _require(_text(judgment["judgment_id"]), "JUDGMENT_ID_REQUIRED")
    posture = bundle["posture_gate"]
    _require(posture["posture_candidate"] in ("SCOUT", "BRIDGEHEAD", "REINFORCEMENT"),
             "POSTURE_CANDIDATE_UNAVAILABLE")
    _require(judgment["posture_candidate"] == posture["posture_candidate"], "POSTURE_CANDIDATE_MISMATCH")
    asset = judgment["asset"]
    _require(asset in ("MSTR", "ASST", "STRC", "SATA"), "UNKNOWN_ASSET")
    check_time = now or datetime.now(timezone.utc)
    _require(check_time.tzinfo is not None, "NOW_TIMEZONE_REQUIRED")
    readiness = _asset_facts(bundle, asset, check_time)
    generated, expires = _timestamp(judgment["generated_at"]), _timestamp(judgment["valid_until"])
    _require(generated <= check_time < expires and generated < expires, "PLAN_VALIDITY_WINDOW_INVALID")
    evidence_at = bundle["evidence_pack"].get("generated_at_ms")
    _require(type(evidence_at) is int and 0 < evidence_at <= int(generated.timestamp() * 1000),
             "EVIDENCE_TIME_LINEAGE_MISMATCH")
    lines = judgment["lines"]
    _require(isinstance(lines, list) and len(lines) == 4, "FOUR_COMMANDER_LINES_REQUIRED")
    for line in lines:
        _require(isinstance(line, dict) and set(line) == LINE_FIELDS, "LINE_SCHEMA_MISMATCH")
        for field in ("btc_condition", "confirmation_condition", "rationale"):
            _require(_text(line[field]), "LINE_CONTEXT_REQUIRED:" + field)
    candidate = {
        "closure_schema_version": CANDIDATE_SCHEMA,
        "plan_id": judgment["judgment_id"], "plan_version": "0.1",
        "plan_mode": "OBSERVATION_ONLY", "asset": asset,
        "generated_at": judgment["generated_at"], "valid_until": judgment["valid_until"],
        "source_main_sha": current_main_sha, "lines": deepcopy(lines),
        "governance": dict(REQUIRED_GOVERNANCE),
        "closure_lineage": {
            "source_bundle_hash": bundle["bundle_hash"], "judgment_hash": _hash(judgment),
            "evidence_pack_hash": bundle["evidence_pack"]["evidence_pack_hash"],
            "handoff_hash": bundle["handoff"]["handoff_hash"],
            "research_evaluation_hash": _hash(bundle["research_evaluation"]),
            "posture_gate_hash": _hash(posture), "asset_readiness_hash": _hash(readiness),
            "posture_candidate": posture["posture_candidate"],
            "posture_effect": posture["posture_effect"],
            "eligibility_level": posture["eligibility_level"],
            "final_eligibility": posture["final_eligibility"],
            "required_downstream_gates": deepcopy(posture["required_downstream_gates"]),
            "production": "NOT_APPROVED",
        },
    }
    # Existing validator owns Commander line shape, prices, seal and governance.
    # This transient seal is validation-only and is never exposed or armed.
    valid, blockers = validate_commander_plan(seal_commander_plan(candidate),
        current_main_sha=current_main_sha, now=check_time)
    if not valid:
        raise CommanderPlanBlocked(blockers)
    return candidate


def validate_candidate_commander_plan(candidate: Any, judgment: Any, *,
        source_bundle: Any, current_main_sha: str, now: datetime | None = None) -> tuple[bool, list[str]]:
    try:
        expected = build_candidate_commander_plan(judgment, source_bundle=source_bundle,
            current_main_sha=current_main_sha, now=now)
        _require(_hash(candidate) == _hash(expected), "CANDIDATE_LINEAGE_OR_SCHEMA_MISMATCH")
    except CommanderPlanBlocked as exc:
        return False, list(exc.blockers)
    except (ValueError, TypeError, OverflowError) as exc:
        return False, ["CANDIDATE_SCHEMA_INVALID:" + str(exc)]
    return True, []


def seal_candidate_commander_plan(candidate: Any, judgment: Any, *, source_bundle: Any,
        current_main_sha: str, now: datetime | None = None) -> dict:
    valid, blockers = validate_candidate_commander_plan(candidate, judgment,
        source_bundle=source_bundle, current_main_sha=current_main_sha, now=now)
    if not valid:
        raise CommanderPlanBlocked(blockers)
    return seal_commander_plan(candidate)


def run_gpt_commander_observation(judgment: Any, *, source_bundle: Any,
        current_main_sha: str, config: IbkrIntakeConfig, ledger_path: str | Path,
        dedupe_state_path: str | Path, observation_journal_path: str | Path | None = None,
        report_path: str | Path | None = None, now: datetime | None = None,
        feed_factory=NativeIbkrFeed) -> dict:
    """Revalidate, seal, then delegate one bounded live observation cycle.

    No feed construction, runtime writes, or arming occurs on validation failure.
    The existing operator retains observation journaling, reanalysis and handoff.
    """
    # Freeze caller-owned dictionaries across validation and delegation.
    judgment, source_bundle = deepcopy(judgment), deepcopy(source_bundle)
    candidate = build_candidate_commander_plan(judgment, source_bundle=source_bundle,
        current_main_sha=current_main_sha, now=now)
    plan = seal_candidate_commander_plan(candidate, judgment, source_bundle=source_bundle,
        current_main_sha=current_main_sha, now=now)
    return run_gate6c3_operator(plan, current_main_sha=current_main_sha, config=config,
        ledger_path=ledger_path, dedupe_state_path=dedupe_state_path,
        observation_journal_path=observation_journal_path, report_path=report_path,
        now=now, feed_factory=feed_factory)
