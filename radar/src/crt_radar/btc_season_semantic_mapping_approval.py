"""Fail-closed validation for the external BTC Season mapping hash approval seal.

The seal approves one immutable semantic-mapping canonical hash.  It does not
modify the approved candidate, bind runtime, determine Season, approve
Production, or grant external-action authority.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


RADAR_ROOT = Path(__file__).resolve().parents[2]
MAPPING_RELATIVE_PATH = Path(
    "CONFIG/BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1.json"
)
SEAL_RELATIVE_PATH = Path(
    "CONFIG/BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_SEAL_V0.1.json"
)
DEFAULT_SEAL = RADAR_ROOT / SEAL_RELATIVE_PATH

SCHEMA_VERSION = "CRT_BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_SEAL_V0.1"
SEAL_ID = "CRT-BTC-SEASON-SEMANTIC-MAPPING-HASH-APPROVAL-SEAL-V0.1"
EXPECTED_STATUS = "EXACT_MAPPING_HASH_APPROVED"
EXPECTED_SEAL_CANONICAL_SHA256 = (
    "6af3c17c263df8b4434e85078e95b9d506f6efb19acb484ac39745355322f75a"
)

EXPECTED_APPROVED_ARTIFACT = {
    "mapping_id": "CRT-BTC-SEASON-SEMANTIC-MAPPING-CANDIDATE-V0.1.1",
    "mapping_schema_version": "CRT_BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1",
    "candidate_path": str(MAPPING_RELATIVE_PATH).replace("\\", "/"),
    "candidate_commit_sha": "744ac4341c02229b1a1d7a4954a4c4d253b86265",
    "candidate_base_main_sha": "f4e35d889cc2721b4ce785a1bd6c1d695a626e23",
    "candidate_pr_number": 32,
    "mapping_canonical_sha256": (
        "afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a"
    ),
    "validation_report_sha256": (
        "b4501884e8c91a8c5de19e37f161346e5666a1ca30e4af27966290aaa4e63cc9"
    ),
    "formal_chapter_7_sha256": (
        "fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26"
    ),
}

EXPECTED_APPROVAL_SCOPE = {
    "exact_mapping_hash": "APPROVED",
    "formal_model": "NOT_APPROVED",
    "runtime_binding": "NOT_APPROVED",
    "season_output_authority": "NONE",
    "production": "NOT_APPROVED",
    "capital_decision_authority": "USER_ONLY",
    "external_action_authority": "NONE",
    "external_action_performed": False,
    "action_output": "NONE",
}

EXPECTED_GATE_EFFECT = {
    "closed_gate": "AG_EXACT_MAPPING_HASH",
    "remaining_approval_gates": ["AG_RUNTIME_PROMOTION"],
    "runtime_promotion_ready": False,
}

EXPECTED_IMMUTABILITY_BOUNDARY = {
    "approval_record_is_external_to_candidate": True,
    "candidate_json_modified_by_approval": False,
    "approved_mapping_canonical_sha256_must_remain_exact": True,
}

EXPECTED_RESEARCH_FIREWALL = {
    "research_delta_authority": "NONE",
    "research_delta_may_approve_hash": False,
    "research_delta_may_approve_runtime": False,
    "research_delta_may_close_blocker": False,
}

EXPECTED_UNMAPPED_IDS = {
    "UM_STAGE3_EQUIVALENCE_CLASSIFIER",
    "UM_V_C_S_E_UPSTREAM_RUNTIME_CLASSIFIERS",
    "UM_VALUE_ROUTE_CLASSIFIER_AND_ROUTE_SPECIFIC_GATES",
    "UM_INDEPENDENT_LATER_OBSERVATION_AND_EVENT_IDENTITY",
    "UM_KEY_WEEKLY_STRUCTURE_AND_BREAKOUT_RETEST_CLASSIFIER",
    "UM_SPOT_AND_INSTITUTIONAL_DEMAND_PERSISTENCE",
    "UM_D0_D4_AND_VETO_RUNTIME_CLASSIFIER",
    "UM_MACRO_OVERLAY_AND_TRANSMISSION_RUNTIME_CLASSIFIER",
    "UM_LAST_VALID_SEASON_BOOTSTRAP_AND_PERSISTENCE",
    "UM_SE_X_RECOVERY_AND_STATE_LEASE",
    "UM_NON_WINTER_TRANSITION_PREDICATES",
    "UM_FORMAL_SOURCE_BINDINGS_FRESHNESS_AND_CLOCK_ALIGNMENT",
    "UM_DATA_QUALITY_GATE_RUNTIME_EVALUATION",
    "UM_FORMAL_OUTPUT_ASSEMBLY_AND_CHAPTER8_INTERFACE",
}


class SeasonSemanticMappingApprovalError(ValueError):
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


def load_seal(path: str | Path = DEFAULT_SEAL) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SeasonSemanticMappingApprovalError("APPROVAL_SEAL_NOT_OBJECT")
    return value


def _load_mapping(radar_root: str | Path) -> dict[str, Any]:
    value = json.loads(
        (Path(radar_root) / MAPPING_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise SeasonSemanticMappingApprovalError("APPROVED_MAPPING_NOT_OBJECT")
    return value


def _validate_approved_source(
    candidate: dict[str, Any],
    *,
    radar_root: str | Path,
) -> list[str]:
    errors: list[str] = []
    source = candidate.get("source_contract")
    if not isinstance(source, dict):
        return ["approved mapping formal source contract missing"]

    required = {
        "artifact_path",
        "artifact_size_bytes",
        "artifact_sha256",
        "working_body_member",
        "working_body_size_bytes",
        "working_body_sha256",
        "chapter_start_marker",
        "chapter_end_marker",
        "chapter_size_bytes",
        "chapter_sha256",
    }
    if not required.issubset(source):
        return ["approved mapping formal source contract incomplete"]

    artifact = Path(radar_root) / source["artifact_path"]
    try:
        artifact_bytes = artifact.read_bytes()
    except OSError:
        return ["approved formal source archive missing"]
    if len(artifact_bytes) != source["artifact_size_bytes"]:
        errors.append("approved formal source archive size mismatch")
    if hashlib.sha256(artifact_bytes).hexdigest() != source["artifact_sha256"]:
        errors.append("approved formal source archive hash mismatch")

    try:
        with zipfile.ZipFile(artifact) as archive:
            if archive.testzip() is not None:
                errors.append("approved formal source archive CRC failure")
            body = archive.read(source["working_body_member"])
    except (OSError, KeyError, zipfile.BadZipFile):
        return sorted(set(errors + ["approved formal source archive unreadable"]))

    if len(body) != source["working_body_size_bytes"]:
        errors.append("approved formal working body size mismatch")
    if hashlib.sha256(body).hexdigest() != source["working_body_sha256"]:
        errors.append("approved formal working body hash mismatch")

    try:
        chapter_start = body.index(source["chapter_start_marker"].encode("utf-8"))
        chapter_end = body.index(
            source["chapter_end_marker"].encode("utf-8"),
            chapter_start,
        )
        chapter = body[chapter_start:chapter_end]
    except (AttributeError, TypeError, ValueError):
        return sorted(set(errors + ["approved formal Chapter 7 byte slice missing"]))

    if len(chapter) != source["chapter_size_bytes"]:
        errors.append("approved formal Chapter 7 size mismatch")
    chapter_hash = hashlib.sha256(chapter).hexdigest()
    if chapter_hash != source["chapter_sha256"]:
        errors.append("approved formal Chapter 7 hash mismatch")
    if chapter_hash != EXPECTED_APPROVED_ARTIFACT["formal_chapter_7_sha256"]:
        errors.append("seal and approved formal Chapter 7 identity mismatch")
    return sorted(set(errors))


def validate_approval_seal(
    seal: dict[str, Any],
    mapping: dict[str, Any] | None = None,
    *,
    radar_root: str | Path = RADAR_ROOT,
) -> list[str]:
    errors: list[str] = []

    if canonical_hash(seal) != EXPECTED_SEAL_CANONICAL_SHA256:
        errors.append("approval seal canonical hash changed")
    if seal.get("schema_version") != SCHEMA_VERSION:
        errors.append("approval seal schema_version changed")
    if seal.get("seal_id") != SEAL_ID:
        errors.append("approval seal identity changed")
    if seal.get("status") != EXPECTED_STATUS:
        errors.append("exact mapping hash approval status changed")
    if seal.get("approval_date") != "2026-08-22":
        errors.append("approval date changed")
    if seal.get("approval_actor") != "CRT_OWNER_USER":
        errors.append("approval actor changed")
    if seal.get("approval_evidence") != "EXPLICIT_USER_APPROVAL_2026-08-22":
        errors.append("approval evidence changed")
    if seal.get("approved_artifact") != EXPECTED_APPROVED_ARTIFACT:
        errors.append("approved artifact identity changed")
    if seal.get("approval_scope") != EXPECTED_APPROVAL_SCOPE:
        errors.append("approval scope or authority boundary changed")
    if seal.get("gate_effect") != EXPECTED_GATE_EFFECT:
        errors.append("approval gate effect changed")
    if seal.get("immutability_boundary") != EXPECTED_IMMUTABILITY_BOUNDARY:
        errors.append("approved candidate immutability boundary changed")
    if seal.get("research_firewall") != EXPECTED_RESEARCH_FIREWALL:
        errors.append("approval research firewall changed")

    try:
        candidate = _load_mapping(radar_root) if mapping is None else mapping
    except (OSError, ValueError, json.JSONDecodeError):
        return sorted(set(errors + ["approved mapping candidate cannot be loaded"]))

    if canonical_hash(candidate) != EXPECTED_APPROVED_ARTIFACT[
        "mapping_canonical_sha256"
    ]:
        errors.append("approved mapping canonical hash mismatch")
    if candidate.get("mapping_id") != EXPECTED_APPROVED_ARTIFACT["mapping_id"]:
        errors.append("approved mapping identity mismatch")
    if candidate.get("schema_version") != EXPECTED_APPROVED_ARTIFACT[
        "mapping_schema_version"
    ]:
        errors.append("approved mapping schema mismatch")

    errors.extend(_validate_approved_source(candidate, radar_root=radar_root))
    return sorted(set(errors))


def build_approval_validation_report(
    seal: dict[str, Any] | None = None,
    mapping: dict[str, Any] | None = None,
    *,
    radar_root: str | Path = RADAR_ROOT,
) -> dict[str, Any]:
    candidate_seal = (
        load_seal(Path(radar_root) / SEAL_RELATIVE_PATH)
        if seal is None
        else seal
    )
    errors = validate_approval_seal(
        candidate_seal,
        mapping,
        radar_root=radar_root,
    )
    exact_hash_approved = not errors
    remaining_gates = ["AG_RUNTIME_PROMOTION"]
    if not exact_hash_approved:
        remaining_gates.append("AG_EXACT_MAPPING_HASH")

    unmapped = sorted(EXPECTED_UNMAPPED_IDS)
    blocked_reasons = {f"UNMAPPED:{item}" for item in unmapped}
    blocked_reasons.update(f"APPROVAL_GATE:{item}" for item in remaining_gates)
    blocked_reasons.update(f"INVALID:{item}" for item in errors)

    report: dict[str, Any] = {
        "schema_version": (
            "CRT_BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_VALIDATION_V0.1"
        ),
        "seal_id": candidate_seal.get("seal_id"),
        "seal_hash": canonical_hash(candidate_seal),
        "approved_mapping_hash": EXPECTED_APPROVED_ARTIFACT[
            "mapping_canonical_sha256"
        ],
        "state": (
            "VALID_HASH_APPROVAL_SEAL_FAIL_CLOSED"
            if exact_hash_approved
            else "INVALID_HASH_APPROVAL_SEAL_FAIL_CLOSED"
        ),
        "seal_errors": errors,
        "exact_mapping_hash_approved": exact_hash_approved,
        "remaining_unmapped_requirements": unmapped,
        "remaining_approval_gates": sorted(remaining_gates),
        "blocked_reasons": sorted(blocked_reasons),
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
