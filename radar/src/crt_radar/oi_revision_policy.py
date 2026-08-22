from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RADAR_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = RADAR_ROOT / "CONFIG" / "L4_OI_POINT_IN_TIME_REVISION_POLICY_V0.1.json"
DEFAULT_SOURCE_REGISTRY = RADAR_ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"

POLICY_SCHEMA_VERSION = "CRT_L4_OI_POINT_IN_TIME_REVISION_POLICY_V0.1"
POLICY_ID = "CRT-L4-OI-POINT-IN-TIME-REVISION-POLICY-V0.1"
POLICY_STATUS = "ENGINEERING_CANDIDATE_NOT_APPROVED"
EXPECTED_BASE_MAIN_SHA = "3d40a230f1cea08c253f0dafaa5f3a15ad876cb8"
EXPECTED_POLICY_CANONICAL_SHA256 = "41894ff01877da4fd7a0baf9aefcb783110129ab194350bd6c6696278f7c357e"
EXPECTED_REGISTRY_CANONICAL_SHA256 = "30ee09f0c6403c9d782a49411c61c24b91d6522d8c4960c4dfd6ef572e7375bc"
EXPECTED_REGISTRY_ID = "CRT-RADAR-SOURCE-REGISTRY-V1.4-WIP"

EXPECTED_SCOPED_SERIES = (
    (
        "OPEN_INTEREST",
        "open_interest_contracts",
        "CRT-CONN-BTC-DERIV-BINANCE-OI-001",
    ),
    (
        "OPEN_INTEREST_NOTIONAL",
        "open_interest_notional_usd",
        "CRT-CONN-BTC-DERIV-BINANCE-OI-NOTIONAL-001",
    ),
    (
        "OPEN_INTEREST_NOTIONAL",
        "oi_to_market_cap_pct",
        "CRT-CONN-BTC-DERIV-BINANCE-OI-NOTIONAL-001",
    ),
)
EXPECTED_SOURCE_BY_METRIC = {
    (family, metric): source_id
    for family, metric, source_id in EXPECTED_SCOPED_SERIES
}


class OiRevisionPolicyError(ValueError):
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


def load_policy(path: str | Path = DEFAULT_POLICY) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OiRevisionPolicyError("POLICY_NOT_OBJECT")
    return value


def _load_registry(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OiRevisionPolicyError("SOURCE_REGISTRY_NOT_OBJECT")
    return value


def is_scoped_metric(input_family: str, metric: str) -> bool:
    return (input_family, metric) in EXPECTED_SOURCE_BY_METRIC


def expected_source_id(input_family: str, metric: str) -> str | None:
    return EXPECTED_SOURCE_BY_METRIC.get((input_family, metric))


def validate_policy(
    policy: dict[str, Any],
    *,
    source_registry_path: str | Path = DEFAULT_SOURCE_REGISTRY,
) -> list[str]:
    errors: list[str] = []
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        errors.append("policy schema_version changed")
    if policy.get("policy_id") != POLICY_ID:
        errors.append("policy id changed")
    if policy.get("status") != POLICY_STATUS:
        errors.append("policy status must remain not approved")
    if policy.get("base_main_sha") != EXPECTED_BASE_MAIN_SHA:
        errors.append("policy base main SHA changed")
    if canonical_hash(policy) != EXPECTED_POLICY_CANONICAL_SHA256:
        errors.append("policy canonical hash drift")

    dependency = policy.get("engineering_registry_dependency")
    if not isinstance(dependency, dict):
        errors.append("engineering registry dependency missing")
    else:
        expected_dependency = {
            "path": "CONFIG/SOURCE_REGISTRY_V1.2.json",
            "registry_id": EXPECTED_REGISTRY_ID,
            "canonical_sha256": EXPECTED_REGISTRY_CANONICAL_SHA256,
            "authority": "PINNED_ENGINEERING_SOURCE_IDENTITY_ONLY",
            "may_be_treated_as_formal_season_source_authority": False,
        }
        if dependency != expected_dependency:
            errors.append("engineering registry dependency changed")

    scope = policy.get("scope")
    expected_scope = [
        {"input_family": family, "metric": metric, "source_id": source_id}
        for family, metric, source_id in EXPECTED_SCOPED_SERIES
    ]
    if not isinstance(scope, dict) or scope.get("layer_id") != "AS-L4":
        errors.append("L4 policy scope changed")
    elif scope.get("series") != expected_scope:
        errors.append("L4 policy series scope changed")

    point_in_time = policy.get("point_in_time_contract")
    expected_point_in_time = {
        "observation_identity_fields": ["input_family", "metric", "as_of_ms"],
        "observation_clock_field": "as_of_ms",
        "availability_proxy_field": "recorded_at_ms",
        "availability_proxy_semantics": "CRT_FIRST_RECORDED_AT_OR_AFTER_SOURCE_AVAILABILITY",
        "visibility_rule": "recorded_at_ms <= evaluation_at_ms",
        "selection_rule": "For each observation identity, select the visible row with the greatest recorded_at_ms.",
        "future_revision_rule": "A row with recorded_at_ms greater than evaluation_at_ms is invisible.",
        "same_release_tie_rule": (
            "Two non-deduplicated rows at the selected recorded_at_ms for one "
            "observation identity are ambiguous and block the affected series."
        ),
        "source_identity_rule": (
            "Every visible row in scope must retain the pinned AS-L4 source_id; "
            "source substitution is not a revision."
        ),
        "ordering_rule": "Selected observations are ordered by as_of_ms only after revision resolution.",
        "raw_retention_rule": "All distinct evidence revisions remain append-only in ObservationStore.",
        "forbidden_resolution_rules": [
            "DELETE_OLDER_REVISION",
            "OVERWRITE_IN_PLACE",
            "LATEST_DATABASE_ROW_WINS",
            "HIGHEST_OR_LOWEST_VALUE_WINS",
            "EVIDENCE_HASH_LEXICAL_TIE_BREAK",
            "BACKDATE_RECORDED_AT",
            "SOURCE_OR_VENUE_SUBSTITUTION",
            "ZERO_OR_FORWARD_FILL",
        ],
    }
    if point_in_time != expected_point_in_time:
        errors.append("point-in-time revision contract changed")

    expected_fail_closed = {
        "ambiguous_selected_revision": "AMBIGUOUS_REVISION_BLOCKED",
        "invalid_clock_order": "REVISION_CLOCK_INVALID_BLOCKED",
        "source_identity_mismatch": "SOURCE_IDENTITY_MISMATCH_BLOCKED",
        "policy_identity_or_hash_drift": "REVISION_POLICY_INVALID_BLOCKED",
    }
    if policy.get("fail_closed_states") != expected_fail_closed:
        errors.append("fail-closed revision states changed")

    expected_integration = {
        "allowed_consumers": [
            "CHANGE_ENGINE_OI_HISTORY",
            "V110_CANDIDATE_L4_OI_HISTORY",
        ],
        "raw_store_api_remains_append_only": True,
        "may_change_weights_or_thresholds": False,
        "may_change_mnav_semantics": False,
        "may_approve_formal_model": False,
        "may_bind_production_runtime": False,
        "may_determine_btc_season": False,
        "season_output": None,
    }
    if policy.get("integration_boundary") != expected_integration:
        errors.append("integration boundary changed")

    expected_authority = {
        "candidate_build": "USER_APPROVED_2026-08-22",
        "exact_policy_hash": "NOT_YET_APPROVED",
        "formal_model": "NOT_APPROVED",
        "runtime_binding": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "capital_decision_authority": "USER_ONLY",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }
    if policy.get("authority") != expected_authority:
        errors.append("policy authority boundary changed")

    try:
        registry = _load_registry(source_registry_path)
    except (OSError, json.JSONDecodeError, OiRevisionPolicyError):
        errors.append("source registry unreadable")
        return errors
    if registry.get("registry_id") != EXPECTED_REGISTRY_ID:
        errors.append("source registry id mismatch")
    if canonical_hash(registry) != EXPECTED_REGISTRY_CANONICAL_SHA256:
        errors.append("source registry canonical hash mismatch")
    registry_sources = {
        (row.get("input_family"), row.get("source_id"), row.get("namespace"))
        for row in registry.get("sources", [])
        if isinstance(row, dict)
    }
    for family, _, source_id in EXPECTED_SCOPED_SERIES:
        if (family, source_id, "AS-L4") not in registry_sources:
            errors.append(f"pinned source missing from registry: {family}")
    return errors


def assert_policy_valid() -> dict[str, Any]:
    policy = load_policy()
    errors = validate_policy(policy)
    if errors:
        raise OiRevisionPolicyError("POLICY_INVALID: " + "; ".join(errors))
    return policy
