from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


RADAR_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.json"
)

SCHEMA_VERSION = "CRT_BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1"
MAPPING_ID = "CRT-BTC-SEASON-SEMANTIC-MAPPING-CANDIDATE-V0.1"
EXPECTED_STATUS = "SEMANTIC_MAPPING_CANDIDATE_NOT_APPROVED"
EXPECTED_BASE_MAIN_SHA = "bd658a8813d8f0ce17a9a41efc62db13cae1c777"
EXPECTED_MAPPING_CANONICAL_SHA256 = (
    "9ddfa4137fff446403bca922274b6c95be27bd55b91db735745ba79e4948b965"
)

EXPECTED_SOURCE_CONTRACT = {
    "artifact_path": (
        "FORMAL_SOURCES/CRT-BTC-001_V1.0/"
        "CRT_BTC_001_V1.0_FORMAL_ARCHIVE.zip"
    ),
    "artifact_size_bytes": 300_152,
    "artifact_sha256": (
        "4556141b069596b24d78b8c4b5e19071f6b435f9748cd04891e91817e0a34c42"
    ),
    "working_body_member": (
        "CRT_BTC_001_V1.0_FORMAL_ARCHIVE/WORKING/"
        "CRT-BTC-001_WORKING_BODY.md"
    ),
    "working_body_size_bytes": 174_760,
    "working_body_sha256": (
        "5ba963b51bcf49839299c3ce4e7649728d3d8caa05d8ca442691689e667f0064"
    ),
    "chapter_id": "CH07",
    "chapter_start_marker": "## 第七章",
    "chapter_end_marker": "## 第八章",
    "chapter_size_bytes": 15_262,
    "chapter_sha256": (
        "fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26"
    ),
    "formal_status": "FORMAL_ARCHIVE",
    "acceptance": "AG-0_TO_AG-9_PASS",
}

EXPECTED_AUTHORITY = {
    "candidate_build": "USER_APPROVED_2026-08-22",
    "exact_mapping_hash": "NOT_YET_APPROVED",
    "formal_model": "NOT_APPROVED",
    "runtime_binding": "NOT_APPROVED",
    "season_output_authority": "NONE",
    "production": "NOT_APPROVED",
    "capital_decision_authority": "USER_ONLY",
    "external_action_authority": "NONE",
    "external_action_performed": False,
    "action_output": "NONE",
}

EXPECTED_CONSTANTS = {
    "layer_weights_percent": {
        "L1": 20,
        "L2": 20,
        "L3": 17,
        "L4": 25,
        "L5": 13,
        "L6": 5,
    },
    "light_thresholds": [-60, -35, 35, 60],
    "mnav_semantics": "Diluted Equity mNAV",
    "modification_authority": "NONE",
}

EXPECTED_RUNTIME_BOUNDARY = {
    "validator_scope": "STATIC_CONTRACT_COMPATIBILITY_ONLY",
    "may_import_into_v110_candidate": False,
    "may_read_candidate_score": False,
    "may_determine_btc_season": False,
    "may_emit_season": False,
    "season_output": None,
    "current_runtime_blocked_reason_must_remain": (
        "V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED"
    ),
    "mapping_candidate_blocked_reason": "BTC_SEASON_SEMANTIC_MAPPING_NOT_APPROVED",
}

EXPECTED_STATES = [
    ("SE-WI", "CONFIRMED_SEASON", "WINTER", None),
    ("SE-WI-SPC", "CANDIDATE_STATE", "WINTER", "SPRING"),
    ("SE-SP", "CONFIRMED_SEASON", "SPRING", None),
    ("SE-SP-SUC", "CANDIDATE_STATE", "SPRING", "SUMMER"),
    ("SE-SU", "CONFIRMED_SEASON", "SUMMER", None),
    ("SE-SU-AUC", "CANDIDATE_STATE", "SUMMER", "AUTUMN"),
    ("SE-AU", "CONFIRMED_SEASON", "AUTUMN", None),
    ("SE-AU-WTC", "CANDIDATE_STATE", "AUTUMN", "WINTER"),
    ("SE-X", "EXCEPTION_STATE", None, None),
]

EXPECTED_OUTPUT_QUALIFIERS = [
    ("SEASON_UNDER_REVIEW", "CONFIRMED_STATE_REVIEW_FLAG"),
    ("CANDIDATE_FAILED", "CANDIDATE_FAILURE_RESULT"),
    ("DATA_INCOMPLETE", "SE_X_REASON"),
    ("DATA_CONFLICT", "SE_X_REASON"),
]

EXPECTED_EDGES = [
    ("WI_TO_WI_SPC", "SE-WI", "SE-WI-SPC", "CANDIDATE_FORMATION"),
    ("WI_SPC_TO_SP", "SE-WI-SPC", "SE-SP", "CANDIDATE_CONFIRMATION"),
    ("WI_SPC_TO_WI", "SE-WI-SPC", "SE-WI", "CANDIDATE_FAILURE"),
    ("SP_TO_SP_SUC", "SE-SP", "SE-SP-SUC", "CANDIDATE_FORMATION"),
    ("SP_SUC_TO_SU", "SE-SP-SUC", "SE-SU", "CANDIDATE_CONFIRMATION"),
    ("SP_SUC_TO_SP", "SE-SP-SUC", "SE-SP", "CANDIDATE_FAILURE"),
    ("SU_TO_SU_AUC", "SE-SU", "SE-SU-AUC", "CANDIDATE_FORMATION"),
    ("SU_AUC_TO_AU", "SE-SU-AUC", "SE-AU", "CANDIDATE_CONFIRMATION"),
    ("SU_AUC_TO_SU", "SE-SU-AUC", "SE-SU", "CANDIDATE_FAILURE"),
    ("AU_TO_AU_WTC", "SE-AU", "SE-AU-WTC", "CANDIDATE_FORMATION"),
    ("AU_WTC_TO_WI", "SE-AU-WTC", "SE-WI", "CANDIDATE_CONFIRMATION"),
    ("AU_WTC_TO_AU", "SE-AU-WTC", "SE-AU", "CANDIDATE_FAILURE"),
    (
        "SP_TO_WI_REVIEWED_ROLLBACK",
        "SE-SP",
        "SE-WI",
        "CONFIRMED_STATE_ROLLBACK_AFTER_REVIEW",
    ),
]

EXPECTED_INVARIANT_IDS = {
    "INV_KEEP_LAST_VALID_SEASON_BEFORE_CANDIDATE",
    "INV_CANDIDATE_DOES_NOT_REPLACE_ANCHOR_SEASON",
    "INV_CANDIDATE_AND_CONFIRMATION_REQUIRE_DIFFERENT_EVENTS",
    "INV_CONFIRMATION_REQUIRES_INDEPENDENT_LATER_VALIDATION",
    "INV_CANDIDATE_FAILURE_RETURNS_TO_ANCHOR_SEASON",
    "INV_CONFIRMED_SEASON_THREAT_REQUIRES_REVIEW_BEFORE_ROLLBACK",
    "INV_NORMAL_TRANSITIONS_ARE_ADJACENT_ONLY",
    "INV_SCORE_IS_NOT_A_SEASON",
    "INV_LATEST_REAL_DATA_REQUIRED",
    "INV_DATA_INCOMPLETE_OR_CONFLICT_OUTPUTS_SE_X",
}

EXPECTED_PREDICATES = {
    "PRED_WI_TO_WI_SPC_STANDARD": "WI_TO_WI_SPC",
    "PRED_WI_SPC_TO_SP_CONFIRMATION": "WI_SPC_TO_SP",
    "PRED_WI_SPC_TO_WI_FAILURE": "WI_SPC_TO_WI",
    "PRED_SP_TO_WI_REVIEWED_ROLLBACK": "SP_TO_WI_REVIEWED_ROLLBACK",
}

EXPECTED_UNMAPPED_IDS = {
    "UM_STAGE3_EQUIVALENCE_CLASSIFIER",
    "UM_V_C_S_E_UPSTREAM_RUNTIME_CLASSIFIERS",
    "UM_INDEPENDENT_LATER_OBSERVATION_WINDOW",
    "UM_KEY_WEEKLY_STRUCTURE_IDENTIFICATION",
    "UM_SPOT_AND_INSTITUTIONAL_DEMAND_PERSISTENCE",
    "UM_D0_D4_AND_VETO_RUNTIME_CLASSIFIER",
    "UM_MACRO_TRANSMISSION_RUNTIME_CLASSIFIER",
    "UM_LAST_VALID_SEASON_BOOTSTRAP_AND_PERSISTENCE",
    "UM_SE_X_RECOVERY_AND_STATE_LEASE",
    "UM_NON_WINTER_TRANSITION_PREDICATES",
    "UM_FORMAL_SOURCE_BINDINGS_FRESHNESS_AND_CLOCK_ALIGNMENT",
    "UM_EXACT_MAPPING_HASH_AND_RUNTIME_PROMOTION_APPROVAL",
}

EXPECTED_RESEARCH_FIREWALL = {
    "research_delta_authority": "NONE",
    "research_delta_may_supply_state": False,
    "research_delta_may_supply_rule": False,
    "research_delta_may_supply_weight": False,
    "research_delta_may_supply_threshold": False,
    "research_delta_may_close_unmapped_requirement": False,
}


class SeasonSemanticMappingError(ValueError):
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_mapping(path: str | Path = DEFAULT_MAPPING) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SeasonSemanticMappingError("MAPPING_NOT_OBJECT")
    return value


def _source_refs_valid(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def validate_mapping(mapping: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if canonical_hash(mapping) != EXPECTED_MAPPING_CANONICAL_SHA256:
        errors.append("candidate canonical hash changed")
    if mapping.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version changed")
    if mapping.get("mapping_id") != MAPPING_ID:
        errors.append("mapping_id changed")
    if mapping.get("status") != EXPECTED_STATUS:
        errors.append("candidate status must remain not approved")
    if mapping.get("base_main_sha") != EXPECTED_BASE_MAIN_SHA:
        errors.append("base main SHA changed")
    if mapping.get("source_contract") != EXPECTED_SOURCE_CONTRACT:
        errors.append("formal source contract identity changed")
    if mapping.get("authority") != EXPECTED_AUTHORITY:
        errors.append("candidate authority boundary changed")
    if mapping.get("inherited_formal_constants") != EXPECTED_CONSTANTS:
        errors.append("inherited formal constants changed")
    if mapping.get("runtime_boundary") != EXPECTED_RUNTIME_BOUNDARY:
        errors.append("runtime fail-closed boundary changed")

    states = mapping.get("state_catalog")
    if not isinstance(states, list):
        errors.append("state_catalog must be a list")
        states = []
    actual_states = []
    for state in states:
        if not isinstance(state, dict):
            errors.append("state entry must be an object")
            continue
        actual_states.append(
            (
                state.get("state_id"),
                state.get("kind"),
                state.get("anchor_season"),
                state.get("proposed_season"),
            )
        )
        if state.get("source_ref") != "CH07-7.3":
            errors.append(f"{state.get('state_id')} source_ref changed")
    if actual_states != EXPECTED_STATES:
        errors.append("formal state catalog or ordering changed")

    qualifiers = mapping.get("output_qualifiers")
    if not isinstance(qualifiers, list):
        errors.append("output_qualifiers must be a list")
        qualifiers = []
    actual_qualifiers = []
    for qualifier in qualifiers:
        if not isinstance(qualifier, dict):
            errors.append("output qualifier must be an object")
            continue
        qualifier_id = qualifier.get("qualifier_id")
        actual_qualifiers.append((qualifier_id, qualifier.get("kind")))
        if not _source_refs_valid(qualifier.get("source_refs")):
            errors.append(f"{qualifier_id} source_refs missing")
    if actual_qualifiers != EXPECTED_OUTPUT_QUALIFIERS:
        errors.append("formal output qualifier catalog changed")

    edges = mapping.get("declared_edges")
    if not isinstance(edges, list):
        errors.append("declared_edges must be a list")
        edges = []
    actual_edges = []
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("edge entry must be an object")
            continue
        edge_id = edge.get("edge_id")
        actual_edges.append(
            (
                edge_id,
                edge.get("from_state"),
                edge.get("to_state"),
                edge.get("phase"),
            )
        )
        if not _source_refs_valid(edge.get("source_refs")):
            errors.append(f"{edge_id} source_refs missing")
    if actual_edges != EXPECTED_EDGES:
        errors.append("declared transition topology changed")

    invariants = mapping.get("global_invariants")
    if not isinstance(invariants, list):
        errors.append("global_invariants must be a list")
        invariants = []
    invariant_ids = {
        row.get("invariant_id") for row in invariants if isinstance(row, dict)
    }
    if invariant_ids != EXPECTED_INVARIANT_IDS or len(invariants) != len(
        EXPECTED_INVARIANT_IDS
    ):
        errors.append("global invariant set changed")
    for row in invariants:
        if isinstance(row, dict) and not _source_refs_valid(row.get("source_refs")):
            errors.append(f"{row.get('invariant_id')} source_refs missing")

    predicates = mapping.get("symbolic_predicate_contracts")
    if not isinstance(predicates, list):
        errors.append("symbolic_predicate_contracts must be a list")
        predicates = []
    predicate_index = {
        row.get("predicate_id"): row for row in predicates if isinstance(row, dict)
    }
    if set(predicate_index) != set(EXPECTED_PREDICATES) or len(predicates) != len(
        EXPECTED_PREDICATES
    ):
        errors.append("symbolic predicate set changed")
    for predicate_id, edge_id in EXPECTED_PREDICATES.items():
        row = predicate_index.get(predicate_id, {})
        if row.get("edge_id") != edge_id:
            errors.append(f"{predicate_id} edge binding changed")
        if row.get("status") != "SYMBOLIC_ONLY_NOT_RUNTIME_BOUND":
            errors.append(f"{predicate_id} gained runtime authority")
        symbols = row.get("required_symbols", row.get("trigger_symbols_any"))
        if not isinstance(symbols, list) or not symbols:
            errors.append(f"{predicate_id} symbolic requirements missing")
        if not _source_refs_valid(row.get("source_refs")):
            errors.append(f"{predicate_id} source_refs missing")

    unmapped = mapping.get("unmapped_requirements")
    if not isinstance(unmapped, list):
        errors.append("unmapped_requirements must be a list")
        unmapped = []
    unmapped_ids = {
        row.get("requirement_id") for row in unmapped if isinstance(row, dict)
    }
    if unmapped_ids != EXPECTED_UNMAPPED_IDS or len(unmapped) != len(
        EXPECTED_UNMAPPED_IDS
    ):
        errors.append("unmapped blocker set changed")
    for row in unmapped:
        if not isinstance(row, dict):
            errors.append("unmapped requirement must be an object")
            continue
        requirement_id = row.get("requirement_id")
        if row.get("status") != "UNMAPPED_BLOCKED":
            errors.append(f"{requirement_id} must remain UNMAPPED_BLOCKED")
        if row.get("research_delta_may_fill") is not False:
            errors.append(f"{requirement_id} research firewall changed")
        if not _source_refs_valid(row.get("source_refs")):
            errors.append(f"{requirement_id} source_refs missing")

    if mapping.get("research_firewall") != EXPECTED_RESEARCH_FIREWALL:
        errors.append("research firewall changed")
    return sorted(set(errors))


def validate_source_bytes(
    mapping: dict[str, Any],
    *,
    radar_root: str | Path = RADAR_ROOT,
) -> list[str]:
    errors: list[str] = []
    source = mapping.get("source_contract")
    if source != EXPECTED_SOURCE_CONTRACT:
        return ["formal source contract identity changed"]

    artifact = Path(radar_root) / source["artifact_path"]
    try:
        artifact_bytes = artifact.read_bytes()
    except OSError:
        return ["formal source archive missing"]
    if len(artifact_bytes) != source["artifact_size_bytes"]:
        errors.append("formal source archive size mismatch")
    if _sha256(artifact_bytes) != source["artifact_sha256"]:
        errors.append("formal source archive hash mismatch")

    try:
        with zipfile.ZipFile(artifact) as archive:
            if archive.testzip() is not None:
                errors.append("formal source archive CRC failure")
            body = archive.read(source["working_body_member"])
            manifest = json.loads(
                archive.read(
                    "CRT_BTC_001_V1.0_FORMAL_ARCHIVE/"
                    "MANIFEST/PACKAGE_MANIFEST.json"
                )
            )
            release = archive.read(
                "CRT_BTC_001_V1.0_FORMAL_ARCHIVE/RELEASE/"
                "CRT-BTC-001_RELEASE_RECORD_V1.0.md"
            ).decode("utf-8")
            acceptance = archive.read(
                "CRT_BTC_001_V1.0_FORMAL_ARCHIVE/RELEASE/"
                "CRT-BTC-001_USER_ACCEPTANCE_2026-07-21.md"
            ).decode("utf-8")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return sorted(set(errors + ["formal source archive cannot be verified"]))

    if len(body) != source["working_body_size_bytes"]:
        errors.append("formal working body size mismatch")
    if _sha256(body) != source["working_body_sha256"]:
        errors.append("formal working body hash mismatch")

    try:
        chapter_start = body.index(source["chapter_start_marker"].encode("utf-8"))
        chapter_end = body.index(
            source["chapter_end_marker"].encode("utf-8"), chapter_start
        )
        chapter = body[chapter_start:chapter_end]
    except ValueError:
        errors.append("formal Chapter 7 byte slice missing")
    else:
        if len(chapter) != source["chapter_size_bytes"]:
            errors.append("formal Chapter 7 size mismatch")
        if _sha256(chapter) != source["chapter_sha256"]:
            errors.append("formal Chapter 7 hash mismatch")

    expected_manifest = {
        "package": "CRT_BTC_001_V1.0_FORMAL_ARCHIVE",
        "version": "V1.0",
        "type": "formal_archive",
        "scope": "CH01-12",
        "status": source["formal_status"],
        "acceptance": source["acceptance"],
    }
    actual_manifest = {
        key: manifest.get(key) for key in expected_manifest
    } if isinstance(manifest, dict) else {}
    if actual_manifest != expected_manifest:
        errors.append("formal package manifest authority mismatch")
    if "狀態：FORMAL_ARCHIVE" not in release:
        errors.append("formal release status missing")
    if "AG-9：PASS" not in acceptance:
        errors.append("formal user acceptance missing")
    return sorted(set(errors))


def build_validation_report(
    mapping: dict[str, Any] | None = None,
    *,
    radar_root: str | Path = RADAR_ROOT,
) -> dict[str, Any]:
    candidate = load_mapping() if mapping is None else mapping
    mapping_errors = validate_mapping(candidate)
    source_errors = validate_source_bytes(candidate, radar_root=radar_root)
    errors = sorted(set(mapping_errors + source_errors))
    unmapped_ids = sorted(
        row["requirement_id"]
        for row in candidate.get("unmapped_requirements", [])
        if isinstance(row, dict) and isinstance(row.get("requirement_id"), str)
    )
    blocked_reasons = [f"UNMAPPED:{item}" for item in unmapped_ids]
    blocked_reasons.extend(
        [
            "EXACT_MAPPING_HASH_NOT_APPROVED",
            "FORMAL_RUNTIME_BINDING_NOT_APPROVED",
        ]
    )
    if errors:
        blocked_reasons.extend(f"INVALID:{item}" for item in errors)

    report: dict[str, Any] = {
        "schema_version": "CRT_BTC_SEASON_SEMANTIC_MAPPING_VALIDATION_V0.1",
        "mapping_id": candidate.get("mapping_id"),
        "mapping_hash": canonical_hash(candidate),
        "state": (
            "VALID_CANDIDATE_FAIL_CLOSED"
            if not errors
            else "INVALID_CANDIDATE_FAIL_CLOSED"
        ),
        "mapping_errors": errors,
        "unmapped_requirements": unmapped_ids,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "runtime_binding_ready": False,
        "machine_may_determine_btc_season": False,
        "season": None,
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    report["validation_report_hash"] = canonical_hash(report)
    return report
