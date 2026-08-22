"""Fail-closed contract for BTC Season formal input timing and source identity.

This candidate validates only the input envelope.  It does not collect data,
classify Stage/V/C/S/E/D/M, bind runtime, or determine BTC Season.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .source_registry import SourceRegistry


RADAR_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_FORMAL_INPUT_ENVELOPE_CANDIDATE_V0.1.json"
)
DEFAULT_REGISTRY = RADAR_ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"

SCHEMA_VERSION = "CRT_BTC_SEASON_FORMAL_INPUT_ENVELOPE_CANDIDATE_V0.1"
ENVELOPE_ID = "CRT-BTC-SEASON-FORMAL-INPUT-ENVELOPE-CANDIDATE-V0.1"
EXPECTED_STATUS = "FORMAL_INPUT_ENVELOPE_CANDIDATE_NOT_APPROVED"
EXPECTED_BASE_MAIN_SHA = "cfc6da8ca80fc85059eac253ee99110855b78382"
EXPECTED_CONTRACT_CANONICAL_SHA256 = (
    "42a54300d3672ca0e05ff65b4e613a79f6d3a79819c489848a82e45b19934da2"
)
EXPECTED_REGISTRY_CANONICAL_SHA256 = (
    "30ee09f0c6403c9d782a49411c61c24b91d6522d8c4960c4dfd6ef572e7375bc"
)
EXPECTED_SEMANTIC_MAPPING_SHA256 = (
    "afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a"
)
EXPECTED_SEAL_SHA256 = (
    "6af3c17c263df8b4434e85078e95b9d506f6efb19acb484ac39745355322f75a"
)
RUNTIME_ENVELOPE_SCHEMA_VERSION = "CRT_BTC_SEASON_FORMAL_INPUT_ENVELOPE_V0.1"

EXPECTED_FAMILY_IDS = {
    "SEASON_STAGE_BACKGROUND",
    "VALUE_STATE_V",
    "CAPITULATION_STATE_C",
    "STOPPING_STATE_S",
    "EVIDENCE_CONSISTENCY_E",
    "CONFLICT_SEVERITY_D",
    "MACRO_OVERLAY_M",
    "KEY_WEEKLY_STRUCTURE",
    "SPOT_DEMAND_QUALITY",
    "INSTITUTIONAL_SPOT_DEMAND",
    "LEVERAGE_COMPATIBILITY",
    "INDEPENDENT_VALIDATION_EVENT",
}

EXPECTED_FAIL_CLOSED_RULES = {
    "REQUIRED_FIELD_MISSING",
    "REQUIRED_FAMILY_UNBOUND",
    "SOURCE_NOT_IN_PINNED_REGISTRY",
    "SOURCE_REGISTRY_HASH_MISMATCH",
    "QUALITY_Q0_BLOCK",
    "REQUIRED_GATE_QUALITY_Q1_OR_Q0_BLOCK",
    "STALE_OR_UNKNOWN_FRESHNESS_BLOCK",
    "FUTURE_CLOCK_BLOCK",
    "AVAILABLE_AFTER_ENVELOPE_AS_OF_BLOCK",
    "OBSERVED_AFTER_AVAILABLE_BLOCK",
    "INVALID_OR_FUTURE_WINDOW_BLOCK",
    "MATERIAL_EVENT_CLOCK_MISALIGNMENT_BLOCK",
}

EXPECTED_AUTHORITY = {
    "candidate_build": "USER_APPROVED_2026-08-22",
    "candidate_hash": "NOT_YET_APPROVED",
    "formal_model": "NOT_APPROVED",
    "runtime_binding": "NOT_APPROVED",
    "season_output_authority": "NONE",
    "production": "NOT_APPROVED",
    "capital_decision_authority": "USER_ONLY",
    "external_action_authority": "NONE",
    "action_output": "NONE",
}

EXPECTED_RUNTIME_BOUNDARY = {
    "validator_scope": "FORMAL_INPUT_ENVELOPE_CONTRACT_ONLY",
    "may_import_into_v110_candidate": False,
    "may_collect_or_fetch_data": False,
    "may_classify_stage_v_c_s_e_d_macro_or_structure": False,
    "may_determine_btc_season": False,
    "may_emit_season": False,
    "season_output": None,
    "unmapped_requirement_must_remain": (
        "UM_FORMAL_SOURCE_BINDINGS_FRESHNESS_AND_CLOCK_ALIGNMENT"
    ),
}


class FormalInputEnvelopeError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FormalInputEnvelopeError("FORMAL_INPUT_ENVELOPE_CONTRACT_NOT_OBJECT")
    return value


def validate_contract(
    contract: dict[str, Any],
    *,
    radar_root: str | Path = RADAR_ROOT,
) -> list[str]:
    errors: list[str] = []
    root = Path(radar_root)

    if canonical_hash(contract) != EXPECTED_CONTRACT_CANONICAL_SHA256:
        errors.append("formal input envelope candidate canonical hash changed")
    if contract.get("schema_version") != SCHEMA_VERSION:
        errors.append("formal input envelope schema changed")
    if contract.get("envelope_id") != ENVELOPE_ID:
        errors.append("formal input envelope identity changed")
    if contract.get("status") != EXPECTED_STATUS:
        errors.append("formal input envelope status changed")
    if contract.get("base_main_sha") != EXPECTED_BASE_MAIN_SHA:
        errors.append("formal input envelope base main changed")
    if contract.get("authority") != EXPECTED_AUTHORITY:
        errors.append("formal input envelope authority boundary changed")
    if contract.get("runtime_boundary") != EXPECTED_RUNTIME_BOUNDARY:
        errors.append("formal input envelope runtime boundary changed")

    authority = contract.get("formal_authority")
    if not isinstance(authority, dict):
        errors.append("formal authority identity missing")
    else:
        if authority.get("semantic_mapping_sha256") != EXPECTED_SEMANTIC_MAPPING_SHA256:
            errors.append("approved semantic mapping identity changed")
        if authority.get("hash_approval_seal_sha256") != EXPECTED_SEAL_SHA256:
            errors.append("hash approval seal identity changed")
        mapping_path = root / str(authority.get("semantic_mapping_path", ""))
        seal_path = root / str(authority.get("hash_approval_seal_path", ""))
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            seal = json.loads(seal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("approved semantic authority files cannot be loaded")
        else:
            if canonical_hash(mapping) != EXPECTED_SEMANTIC_MAPPING_SHA256:
                errors.append("approved semantic mapping bytes changed")
            if canonical_hash(seal) != EXPECTED_SEAL_SHA256:
                errors.append("hash approval seal bytes changed")

    dependency = contract.get("engineering_registry_dependency")
    if not isinstance(dependency, dict):
        errors.append("engineering registry dependency missing")
    else:
        if dependency.get("authority") != "PARTIAL_ENGINEERING_REGISTRY_ONLY":
            errors.append("partial registry authority changed")
        if dependency.get("may_be_treated_as_complete_season_source_authority") is not False:
            errors.append("partial registry escalated to Season source authority")
        if dependency.get("modified_by_candidate") is not False:
            errors.append("candidate claims to modify source registry")
        registry_path = root / str(dependency.get("path", ""))
        try:
            registry = SourceRegistry.load(registry_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("pinned engineering source registry cannot be loaded")
        else:
            if registry.hash != EXPECTED_REGISTRY_CANONICAL_SHA256:
                errors.append("pinned engineering registry canonical hash changed")
            if dependency.get("canonical_sha256") != EXPECTED_REGISTRY_CANONICAL_SHA256:
                errors.append("declared registry canonical hash changed")
            if dependency.get("registry_id") != registry.payload.get("registry_id"):
                errors.append("declared registry identity changed")

    family_rows = contract.get("required_family_bindings")
    if not isinstance(family_rows, list):
        errors.append("required family binding catalog missing")
    else:
        ids = {
            row.get("family_id")
            for row in family_rows
            if isinstance(row, dict) and isinstance(row.get("family_id"), str)
        }
        if ids != EXPECTED_FAMILY_IDS or len(family_rows) != len(EXPECTED_FAMILY_IDS):
            errors.append("required family binding catalog changed")
        for row in family_rows:
            if not isinstance(row, dict):
                errors.append("required family binding row is not an object")
                continue
            if row.get("binding_status") != "UNBOUND_BLOCKED":
                errors.append(f"{row.get('family_id')} must remain UNBOUND_BLOCKED")
            refs = row.get("formal_source_refs")
            if not isinstance(refs, list) or not refs:
                errors.append(f"{row.get('family_id')} formal source refs missing")

    if set(contract.get("fail_closed_rules", [])) != EXPECTED_FAIL_CLOSED_RULES:
        errors.append("formal input fail-closed rule set changed")
    effect = contract.get("candidate_effect")
    if not isinstance(effect, dict) or effect.get("closes_unmapped_requirement") is not False:
        errors.append("candidate may not close the unmapped requirement")
    elif effect.get("remaining_status") != "UNBOUND_BLOCKED":
        errors.append("candidate must remain UNBOUND_BLOCKED")
    elif effect.get("runtime_binding_ready") is not False:
        errors.append("candidate may not be runtime binding ready")

    firewall = contract.get("research_firewall")
    expected_firewall = {
        "research_delta_authority": "NONE",
        "research_may_supply_formal_binding": False,
        "research_may_override_freshness_or_clock_failure": False,
        "research_may_determine_season": False,
    }
    if firewall != expected_firewall:
        errors.append("research firewall changed")
    return sorted(set(errors))


def _integer_ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def evaluate_envelope(
    envelope: dict[str, Any],
    contract: dict[str, Any] | None = None,
    *,
    radar_root: str | Path = RADAR_ROOT,
    now_ms: int | None = None,
) -> dict[str, Any]:
    candidate = load_contract() if contract is None else contract
    contract_errors = validate_contract(candidate, radar_root=radar_root)
    blockers = {f"INVALID_CONTRACT:{item}" for item in contract_errors}

    if not isinstance(envelope, dict):
        envelope = {}
        blockers.add("REQUIRED_FIELD_MISSING:ENVELOPE_OBJECT")
    required_fields = candidate.get("required_envelope_fields", [])
    for field in required_fields:
        if field not in envelope:
            blockers.add(f"REQUIRED_FIELD_MISSING:{field}")

    as_of_ms = _integer_ms(envelope.get("as_of_ms"))
    if as_of_ms is None:
        blockers.add("REQUIRED_FIELD_MISSING:as_of_ms")
    evaluation_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    future_skew_ms = int(candidate.get("clock_contract", {}).get("future_clock_skew_seconds", 300)) * 1000
    if as_of_ms is not None and as_of_ms > evaluation_now_ms + future_skew_ms:
        blockers.add("FUTURE_CLOCK_BLOCK:ENVELOPE")
    if envelope.get("schema_version") != RUNTIME_ENVELOPE_SCHEMA_VERSION:
        blockers.add("REQUIRED_FIELD_MISSING:schema_version")
    if not isinstance(envelope.get("envelope_id"), str) or not envelope.get("envelope_id"):
        blockers.add("REQUIRED_FIELD_MISSING:envelope_id")
    if not isinstance(envelope.get("decision_event_id"), str) or not envelope.get("decision_event_id"):
        blockers.add("REQUIRED_FIELD_MISSING:decision_event_id")
    if envelope.get("source_registry_id") != "CRT-RADAR-SOURCE-REGISTRY-V1.4-WIP":
        blockers.add("SOURCE_REGISTRY_HASH_MISMATCH:REGISTRY_ID")
    registry_hash = envelope.get("source_registry_hash")
    if registry_hash != EXPECTED_REGISTRY_CANONICAL_SHA256:
        blockers.add("SOURCE_REGISTRY_HASH_MISMATCH:ENVELOPE")

    inputs = envelope.get("inputs")
    if not isinstance(inputs, list):
        inputs = []
        blockers.add("REQUIRED_FIELD_MISSING:inputs")
    by_family: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in inputs:
        if not isinstance(row, dict):
            blockers.add("REQUIRED_FIELD_MISSING:INPUT_OBJECT")
            continue
        family_id = row.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            blockers.add("REQUIRED_FIELD_MISSING:family_id")
            continue
        if family_id in by_family:
            duplicates.add(family_id)
        by_family[family_id] = row
    for family_id in duplicates:
        blockers.add(f"DUPLICATE_FAMILY:{family_id}")

    required_input_fields = candidate.get("required_input_fields", [])
    try:
        registry = SourceRegistry.load(Path(radar_root) / "CONFIG" / "SOURCE_REGISTRY_V1.2.json")
    except (OSError, ValueError, json.JSONDecodeError):
        registry = None
        blockers.add("SOURCE_REGISTRY_UNAVAILABLE")

    for family_id in sorted(EXPECTED_FAMILY_IDS):
        row = by_family.get(family_id)
        if row is None:
            blockers.add(f"REQUIRED_FIELD_MISSING:FAMILY:{family_id}")
            blockers.add(f"REQUIRED_FAMILY_UNBOUND:{family_id}")
            continue
        for field in required_input_fields:
            if field not in row:
                blockers.add(f"REQUIRED_FIELD_MISSING:{family_id}:{field}")

        if row.get("binding_status") != "FORMALLY_BOUND":
            blockers.add(f"REQUIRED_FAMILY_UNBOUND:{family_id}")
        source_id = row.get("source_id")
        if row.get("binding_status") == "FORMALLY_BOUND":
            if not isinstance(source_id, str) or not source_id:
                blockers.add(f"SOURCE_NOT_IN_PINNED_REGISTRY:{family_id}")
            elif registry is None:
                blockers.add(f"SOURCE_NOT_IN_PINNED_REGISTRY:{family_id}")
            else:
                try:
                    registry.get(source_id)
                except ValueError:
                    blockers.add(f"SOURCE_NOT_IN_PINNED_REGISTRY:{family_id}")
        if row.get("source_registry_hash") != EXPECTED_REGISTRY_CANONICAL_SHA256:
            blockers.add(f"SOURCE_REGISTRY_HASH_MISMATCH:{family_id}")

        quality = row.get("quality_state")
        if quality == "Q0":
            blockers.add(f"QUALITY_Q0_BLOCK:{family_id}")
        if quality in {"Q0", "Q1"}:
            blockers.add(f"REQUIRED_GATE_QUALITY_Q1_OR_Q0_BLOCK:{family_id}")
        if quality not in {"Q3", "Q2", "Q1", "Q0"}:
            blockers.add(f"REQUIRED_FIELD_MISSING:{family_id}:quality_state")

        freshness = row.get("freshness_state")
        if freshness in {"STALE", "UNKNOWN"}:
            blockers.add(f"STALE_OR_UNKNOWN_FRESHNESS_BLOCK:{family_id}")
        elif freshness == "FUTURE_CLOCK":
            blockers.add(f"FUTURE_CLOCK_BLOCK:{family_id}")
        elif freshness != "FRESH":
            blockers.add(f"REQUIRED_FIELD_MISSING:{family_id}:freshness_state")

        observed = _integer_ms(row.get("observed_at_ms"))
        available = _integer_ms(row.get("available_at_ms"))
        window_start = _integer_ms(row.get("window_start_ms"))
        window_end = _integer_ms(row.get("window_end_ms"))
        if None in {observed, available, window_start, window_end}:
            blockers.add(f"INVALID_OR_FUTURE_WINDOW_BLOCK:{family_id}")
        else:
            assert observed is not None and available is not None
            assert window_start is not None and window_end is not None
            if available < observed:
                blockers.add(f"OBSERVED_AFTER_AVAILABLE_BLOCK:{family_id}")
            if as_of_ms is not None and available > as_of_ms:
                blockers.add(f"AVAILABLE_AFTER_ENVELOPE_AS_OF_BLOCK:{family_id}")
            if window_start > window_end or (as_of_ms is not None and window_end > as_of_ms):
                blockers.add(f"INVALID_OR_FUTURE_WINDOW_BLOCK:{family_id}")
            if as_of_ms is not None and max(observed, available, window_end) > as_of_ms + future_skew_ms:
                blockers.add(f"FUTURE_CLOCK_BLOCK:{family_id}")

        crossed = row.get("crossed_material_event_ids")
        if not isinstance(crossed, list):
            blockers.add(f"REQUIRED_FIELD_MISSING:{family_id}:crossed_material_event_ids")
        elif crossed:
            blockers.add(f"MATERIAL_EVENT_CLOCK_MISALIGNMENT_BLOCK:{family_id}")

    unknown_families = sorted(set(by_family) - EXPECTED_FAMILY_IDS)
    blockers.update(f"UNKNOWN_FAMILY:{item}" for item in unknown_families)
    blockers.update(f"REQUIRED_FAMILY_UNBOUND:{item}" for item in EXPECTED_FAMILY_IDS)

    report: dict[str, Any] = {
        "schema_version": "CRT_BTC_SEASON_FORMAL_INPUT_ENVELOPE_VALIDATION_V0.1",
        "contract_id": candidate.get("envelope_id"),
        "contract_hash": canonical_hash(candidate),
        "envelope_id": envelope.get("envelope_id"),
        "as_of_ms": as_of_ms,
        "state": "UNBOUND_BLOCKED",
        "contract_errors": contract_errors,
        "blocked_reasons": sorted(blockers),
        "required_family_count": len(EXPECTED_FAMILY_IDS),
        "formally_bound_family_count": 0,
        "unbound_family_ids": sorted(EXPECTED_FAMILY_IDS),
        "closes_unmapped_requirement": False,
        "remaining_unmapped_requirement": (
            "UM_FORMAL_SOURCE_BINDINGS_FRESHNESS_AND_CLOCK_ALIGNMENT"
        ),
        "formal_model": "NOT_APPROVED",
        "runtime_binding_ready": False,
        "machine_may_determine_btc_season": False,
        "season": None,
        "production": "NOT_APPROVED",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    report["validation_report_hash"] = canonical_hash(report)
    return report
