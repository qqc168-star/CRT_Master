from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .liquidation_aggregator import canonical_json_bytes, sha256_hex


ADAPTER_SCHEMA_VERSION = "CRT_AS_EVIDENCE_ADAPTER_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"


class EvidenceAdapterError(ValueError):
    pass


def _iso_from_ms(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceAdapterError("as_of_ms must be an integer millisecond timestamp") from exc
    if ms < 1_000_000_000_000:
        raise EvidenceAdapterError("as_of_ms is not millisecond Unix time")
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _evidence_for_layer(source_gate: dict[str, Any], layer_id: str) -> list[dict[str, Any]]:
    rows = source_gate.get("evidence")
    if not isinstance(rows, list):
        raise EvidenceAdapterError("source_gate.evidence must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("namespace") != layer_id:
            continue
        family = raw.get("input_family")
        if not isinstance(family, str) or not family:
            raise EvidenceAdapterError(f"{layer_id} evidence family missing")
        if family in seen:
            raise EvidenceAdapterError(f"duplicate {layer_id} family: {family}")
        seen.add(family)
        result.append(deepcopy(raw))
    return result


def build_evidence_layer(
    source_gate: dict[str, Any],
    *,
    layer_id: str,
    required_families: tuple[str, ...],
    valid_quality_states: dict[str, str] | None = None,
    critical: bool,
) -> dict[str, Any]:
    if not isinstance(source_gate, dict):
        raise EvidenceAdapterError("source_gate must be an object")
    if source_gate.get("external_action_authority") != EXTERNAL_ACTION_AUTHORITY:
        raise EvidenceAdapterError("source gate authority must be NONE")
    if source_gate.get("external_action_performed") is not False:
        raise EvidenceAdapterError("source gate must not perform external actions")
    if source_gate.get("action_output") != "NONE":
        raise EvidenceAdapterError("source gate action_output must be NONE")

    registry_hash = source_gate.get("source_registry_hash")
    gate_key = source_gate.get("idempotency_key")
    if not isinstance(registry_hash, str) or len(registry_hash) != 64:
        raise EvidenceAdapterError("source_registry_hash invalid")
    if not isinstance(gate_key, str) or len(gate_key) != 64:
        raise EvidenceAdapterError("source gate idempotency_key invalid")

    rows = _evidence_for_layer(source_gate, layer_id)
    by_family = {str(row["input_family"]): row for row in rows}
    parsed = source_gate.get("parsed")
    if not isinstance(parsed, dict):
        raise EvidenceAdapterError("source_gate.parsed must be an object")

    expected_quality = valid_quality_states or {family: "VALID_FRESH" for family in required_families}
    missing = [family for family in required_families if family not in by_family]
    invalid = [
        f"{family}:{by_family[family].get('quality_state')}"
        for family in required_families
        if family in by_family and by_family[family].get("quality_state") != expected_quality[family]
    ]
    blocked_reasons = [f"{family}_EVIDENCE_MISSING" for family in missing] + invalid
    if blocked_reasons:
        status = "MISSING" if missing else "INVALID"
    else:
        status = "VALID"

    values = {
        family: deepcopy(parsed[family])
        for family in required_families
        if family in parsed and isinstance(parsed[family], dict)
    }
    evidence = [
        {
            "source_id": row.get("source_id"),
            "namespace": row.get("namespace"),
            "input_family": row.get("input_family"),
            "observed_at": _iso_from_ms(row.get("as_of_ms")),
            "quality_state": row.get("quality_state"),
            "transport_status": row.get("transport_status"),
            "payload_hash": row.get("payload_hash"),
            "evidence_hash": row.get("evidence_hash"),
            "registry_hash": row.get("registry_hash"),
            "quality_error": row.get("quality_error"),
        }
        for row in rows
    ]
    material: dict[str, Any] = {
        "schema_version": ADAPTER_SCHEMA_VERSION,
        "layer_id": layer_id,
        "status": status,
        "critical": critical,
        "score": None,
        "score_origin": "UPSTREAM_LOCKED_MODEL_REQUIRED",
        "rationale": (
            f"{layer_id} evidence complete; adapter maps inputs only and does not score."
            if status == "VALID"
            else f"{layer_id} evidence incomplete or invalid; fail-closed status preserved."
        ),
        "evidence": evidence,
        "values": values,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "source_gate_idempotency_key": gate_key,
        "source_registry_hash": registry_hash,
        "as_of": _iso_from_ms(source_gate.get("as_of_ms")),
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
        "action_output": "NONE",
    }
    material["layer_input_hash"] = sha256_hex(canonical_json_bytes(material))
    return material


def build_asl2_layer(source_gate: dict[str, Any]) -> dict[str, Any]:
    return build_evidence_layer(
        source_gate,
        layer_id="AS-L2",
        required_families=("DOLLAR_STRENGTH_PROXY",),
        critical=True,
    )


def build_asl5_layer(source_gate: dict[str, Any]) -> dict[str, Any]:
    return build_evidence_layer(
        source_gate,
        layer_id="AS-L5",
        required_families=("ONCHAIN_VALUE",),
        critical=False,
    )
