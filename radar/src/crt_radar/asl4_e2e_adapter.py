from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .liquidation_aggregator import canonical_json_bytes, sha256_hex


ADAPTER_SCHEMA_VERSION = "CRT_ASL4_E2E_ADAPTER_V1"
AS_L4_LAYER_ID = "AS-L4"
EXTERNAL_ACTION_AUTHORITY = "NONE"
REQUIRED_FAMILIES = ("OPEN_INTEREST", "FUNDING_RATE", "LIQUIDATION_AGGREGATES")
VALID_QUALITY_STATES = {
    "OPEN_INTEREST": "VALID_FRESH",
    "FUNDING_RATE": "VALID_FRESH",
    "LIQUIDATION_AGGREGATES": "VALID_FRESH_COMPLETE_COVERAGE",
}


class AdapterError(ValueError):
    """Raised when a source-gate result cannot be mapped safely to AS-L4."""


def _iso_from_ms(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError) as exc:
        raise AdapterError("as_of_ms must be an integer millisecond timestamp") from exc
    if ms < 1_000_000_000_000:
        raise AdapterError("as_of_ms is not a millisecond Unix timestamp")
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdapterError(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise AdapterError(f"{field} must be a list")
    return value


def _status_from_blocked_reasons(reasons: list[str]) -> str:
    if any("CONFLICT" in reason for reason in reasons):
        return "CONFLICT"
    if any("STALE" in reason for reason in reasons):
        return "STALE"
    if any("TRANSPORT_ERROR" in reason or "MISSING" in reason or "REQUIRED" in reason for reason in reasons):
        return "MISSING"
    return "INVALID"


def _family_evidence(source_gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = _list(source_gate.get("evidence"), "source_gate.evidence")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = _mapping(raw, "source_gate.evidence[]")
        if row.get("namespace") != AS_L4_LAYER_ID:
            continue
        family = row.get("input_family")
        if not isinstance(family, str) or not family:
            raise AdapterError("AS-L4 evidence input_family missing")
        if family in result:
            raise AdapterError(f"duplicate AS-L4 evidence family: {family}")
        result[family] = row
    return result


def _normalized_values(source_gate: dict[str, Any]) -> dict[str, Any]:
    parsed = _mapping(source_gate.get("parsed", {}), "source_gate.parsed")
    values: dict[str, Any] = {}
    for family in REQUIRED_FAMILIES:
        item = parsed.get(family)
        if isinstance(item, dict):
            values[family] = deepcopy(item)
    return values


def build_asl4_layer(source_gate: dict[str, Any]) -> dict[str, Any]:
    """Convert the read-only Source Gate output to a deterministic AS-L4 layer.

    This adapter intentionally does not compute a Radar score. The locked model
    remains an upstream dependency, so score and score_origin stay explicit.
    """

    source_gate = _mapping(source_gate, "source_gate")
    if source_gate.get("external_action_authority") != EXTERNAL_ACTION_AUTHORITY:
        raise AdapterError("source gate external_action_authority must be NONE")
    if source_gate.get("external_action_performed") is not False:
        raise AdapterError("source gate must not perform external actions")
    if source_gate.get("action_output") != "NONE":
        raise AdapterError("source gate action_output must be NONE")

    registry_hash = source_gate.get("source_registry_hash")
    if not isinstance(registry_hash, str) or len(registry_hash) != 64:
        raise AdapterError("source_registry_hash missing or invalid")
    source_gate_idempotency = source_gate.get("idempotency_key")
    if not isinstance(source_gate_idempotency, str) or len(source_gate_idempotency) != 64:
        raise AdapterError("source gate idempotency_key missing or invalid")

    evidence_by_family = _family_evidence(source_gate)
    missing_families = sorted(set(REQUIRED_FAMILIES) - set(evidence_by_family))
    blocked_reasons = [str(value) for value in source_gate.get("blocked_reasons", [])]
    if missing_families:
        blocked_reasons.extend(f"{family}_EVIDENCE_MISSING" for family in missing_families)

    invalid_quality: list[str] = []
    for family in REQUIRED_FAMILIES:
        row = evidence_by_family.get(family)
        if row is None:
            continue
        expected = VALID_QUALITY_STATES[family]
        if row.get("quality_state") != expected:
            invalid_quality.append(f"{family}:{row.get('quality_state')}")
    blocked_reasons.extend(invalid_quality)
    blocked_reasons = sorted(set(blocked_reasons))

    if blocked_reasons or source_gate.get("formal_state") != "OBSERVATION_ONLY":
        status = _status_from_blocked_reasons(blocked_reasons)
        rationale = "AS-L4 fail-closed：來源 Gate 未形成完整、可驗證的 OI／Funding／Liquidation 組合。"
    else:
        status = "VALID"
        rationale = "AS-L4 來源完整；只提供鎖定模型的輸入，不在 Adapter 內計分。"

    evidence_rows: list[dict[str, Any]] = []
    for family in REQUIRED_FAMILIES:
        row = evidence_by_family.get(family)
        if row is None:
            continue
        evidence_rows.append(
            {
                "source_id": row.get("source_id"),
                "namespace": row.get("namespace"),
                "input_family": family,
                "observed_at": _iso_from_ms(row.get("as_of_ms")),
                "quality_state": row.get("quality_state"),
                "transport_status": row.get("transport_status"),
                "payload_hash": row.get("payload_hash"),
                "evidence_hash": row.get("evidence_hash"),
                "registry_hash": row.get("registry_hash"),
                "quality_error": row.get("quality_error"),
            }
        )

    layer_material = {
        "schema_version": ADAPTER_SCHEMA_VERSION,
        "layer_id": AS_L4_LAYER_ID,
        "status": status,
        "score": None,
        "score_origin": "UPSTREAM_LOCKED_MODEL_REQUIRED",
        "rationale": rationale,
        "evidence": evidence_rows,
        "values": _normalized_values(source_gate),
        "blocked_reasons": blocked_reasons,
        "source_gate_idempotency_key": source_gate_idempotency,
        "source_registry_hash": registry_hash,
        "as_of": _iso_from_ms(source_gate.get("as_of_ms")),
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
        "action_output": "NONE",
    }
    layer_material["layer_input_hash"] = sha256_hex(canonical_json_bytes(layer_material))
    return layer_material


def inject_asl4_layer(
    e2e_snapshot: dict[str, Any],
    asl4_layer: dict[str, Any],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    snapshot = deepcopy(_mapping(e2e_snapshot, "e2e_snapshot"))
    layer = _mapping(asl4_layer, "asl4_layer")
    if layer.get("layer_id") != AS_L4_LAYER_ID:
        raise AdapterError("asl4_layer.layer_id must be AS-L4")
    layers = snapshot.setdefault("layers", {})
    if not isinstance(layers, dict):
        raise AdapterError("e2e_snapshot.layers must be an object")
    if AS_L4_LAYER_ID in layers and not overwrite:
        raise AdapterError("AS-L4 already exists; explicit overwrite required")
    layers[AS_L4_LAYER_ID] = {
        "status": layer["status"],
        "score": layer["score"],
        "score_origin": layer["score_origin"],
        "rationale": layer["rationale"],
        "evidence": deepcopy(layer["evidence"]),
        "adapter_metadata": {
            "schema_version": layer["schema_version"],
            "layer_input_hash": layer["layer_input_hash"],
            "source_registry_hash": layer["source_registry_hash"],
            "source_gate_idempotency_key": layer["source_gate_idempotency_key"],
            "blocked_reasons": deepcopy(layer["blocked_reasons"]),
            "values": deepcopy(layer["values"]),
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        },
    }
    snapshot["external_operation_authority"] = EXTERNAL_ACTION_AUTHORITY
    snapshot["external_action_performed"] = False
    snapshot["action_output"] = "NONE"
    return snapshot
