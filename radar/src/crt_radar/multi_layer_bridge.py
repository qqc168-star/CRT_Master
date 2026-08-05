from __future__ import annotations

from copy import deepcopy
from typing import Any

from .as_evidence_adapter import build_asl2_layer, build_asl5_layer
from .asl4_e2e_adapter import build_asl4_layer
from .liquidation_aggregator import canonical_json_bytes, sha256_hex


BRIDGE_SCHEMA_VERSION = "CRT_RADAR_MULTI_LAYER_BRIDGE_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"


def build_multi_layer_bridge(
    source_gate_result: dict[str, Any],
    *,
    upstream_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layers = {
        "AS-L2": build_asl2_layer(source_gate_result),
        "AS-L4": build_asl4_layer(source_gate_result),
        "AS-L5": build_asl5_layer(source_gate_result),
    }
    critical_invalid = [
        layer_id
        for layer_id, layer in layers.items()
        if layer.get("critical") is True and layer.get("status") != "VALID"
    ]
    # AS-L4 legacy adapter predates the explicit critical field.
    if layers["AS-L4"].get("status") != "VALID" and "AS-L4" not in critical_invalid:
        critical_invalid.append("AS-L4")
    formal_state = "BLOCKED" if critical_invalid else "OBSERVATION_ONLY"
    payload: dict[str, Any] = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "formal_parent": source_gate_result.get("formal_parent"),
        "architecture_target": deepcopy(source_gate_result.get("architecture_target", [])),
        "run_id": source_gate_result.get("run_id"),
        "as_of_ms": source_gate_result.get("as_of_ms"),
        "formal_state": formal_state,
        "data_status": "INPUT_LAYERS_READY" if formal_state == "OBSERVATION_ONLY" else "BLOCKED",
        "layers": layers,
        "critical_invalid_layers": sorted(critical_invalid),
        "noncritical_missing_layers": sorted(
            layer_id
            for layer_id, layer in layers.items()
            if layer.get("critical") is False and layer.get("status") != "VALID"
        ),
        "source_gate_idempotency_key": source_gate_result.get("idempotency_key"),
        "source_registry_hash": source_gate_result.get("source_registry_hash"),
        "score_authority": "NONE",
        "action_output": "NONE",
        "external_operation_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
    }
    if upstream_snapshot is not None:
        snapshot = deepcopy(upstream_snapshot)
        target = snapshot.setdefault("layers", {})
        if not isinstance(target, dict):
            raise ValueError("upstream_snapshot.layers must be an object")
        for layer_id, layer in layers.items():
            target[layer_id] = deepcopy(layer)
        snapshot["external_operation_authority"] = EXTERNAL_ACTION_AUTHORITY
        snapshot["external_action_performed"] = False
        snapshot["action_output"] = "NONE"
        payload["e2e_snapshot"] = snapshot
    payload["bridge_hash"] = sha256_hex(canonical_json_bytes(payload))
    payload["idempotency_key"] = sha256_hex(
        canonical_json_bytes(
            {
                "source_gate_idempotency_key": payload["source_gate_idempotency_key"],
                "layer_hashes": {
                    layer_id: layer["layer_input_hash"] for layer_id, layer in sorted(layers.items())
                },
                "upstream_snapshot_hash": (
                    sha256_hex(canonical_json_bytes(upstream_snapshot))
                    if upstream_snapshot is not None
                    else None
                ),
            }
        )
    )
    return payload
