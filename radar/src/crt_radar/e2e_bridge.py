from __future__ import annotations

from copy import deepcopy
from typing import Any

from .asl4_e2e_adapter import AS_L4_LAYER_ID, build_asl4_layer, inject_asl4_layer
from .liquidation_aggregator import canonical_json_bytes, sha256_hex


BRIDGE_SCHEMA_VERSION = "CRT_RADAR_E2E_BRIDGE_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"


def build_bridge_payload(
    source_gate_result: dict[str, Any],
    *,
    upstream_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layer = build_asl4_layer(source_gate_result)
    formal_state = "OBSERVATION_ONLY" if layer["status"] == "VALID" else "BLOCKED"
    payload: dict[str, Any] = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "formal_parent": source_gate_result.get("formal_parent"),
        "architecture_target": deepcopy(source_gate_result.get("architecture_target", [])),
        "run_id": source_gate_result.get("run_id"),
        "as_of_ms": source_gate_result.get("as_of_ms"),
        "formal_state": formal_state,
        "data_status": "ASL4_READY" if formal_state == "OBSERVATION_ONLY" else "BLOCKED",
        "layers": {AS_L4_LAYER_ID: layer},
        "blocked_reasons": deepcopy(layer["blocked_reasons"]),
        "source_gate_idempotency_key": source_gate_result.get("idempotency_key"),
        "source_registry_hash": source_gate_result.get("source_registry_hash"),
        "semantic_locks": {
            "mnav": "diluted_equity_mnav",
            "q4_window": "2026-Q4",
        },
        "action_output": "NONE",
        "external_operation_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
    }
    if upstream_snapshot is not None:
        payload["e2e_snapshot"] = inject_asl4_layer(upstream_snapshot, layer, overwrite=True)
    material = deepcopy(payload)
    payload["bridge_hash"] = sha256_hex(canonical_json_bytes(material))
    payload["idempotency_key"] = sha256_hex(
        canonical_json_bytes(
            {
                "source_gate_idempotency_key": payload["source_gate_idempotency_key"],
                "layer_input_hash": layer["layer_input_hash"],
                "upstream_snapshot_hash": (
                    sha256_hex(canonical_json_bytes(upstream_snapshot))
                    if upstream_snapshot is not None
                    else None
                ),
            }
        )
    )
    return payload
