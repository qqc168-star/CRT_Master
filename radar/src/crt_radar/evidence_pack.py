from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .change_engine import compute_changes, distill_top_changes
from .observation_store import Observation, ObservationStore, extract_observations


PACK_SCHEMA_VERSION = "CRT_EVIDENCE_PACK_V0.1"
EXTERNAL_ACTION_AUTHORITY = "NONE"
FIRST_SLICE_REQUIRED_FAMILIES = {
    "DOLLAR_STRENGTH_PROXY",
    "OPEN_INTEREST",
    "FUNDING_RATE",
    "LIQUIDATION_AGGREGATES",
}
FIRST_SLICE_OPTIONAL_FAMILIES = {"ONCHAIN_VALUE"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _assert_authority(source_gate: dict[str, Any]) -> None:
    if source_gate.get("external_action_authority") != EXTERNAL_ACTION_AUTHORITY:
        raise ValueError("source gate external_action_authority must be NONE")
    if source_gate.get("external_action_performed") is not False:
        raise ValueError("source gate must not perform external actions")
    if source_gate.get("action_output") != "NONE":
        raise ValueError("source gate action_output must be NONE")


def _evidence_by_family(source_gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = source_gate.get("evidence")
    if not isinstance(rows, list):
        raise ValueError("source_gate.evidence must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        family = row.get("input_family")
        if isinstance(family, str) and family:
            result[family] = row
    return result


def _group_layers(observations: list[Observation]) -> dict[str, Any]:
    layers: dict[str, Any] = {}
    for obs in observations:
        layer_name = obs.layer_id.removeprefix("AS-")
        layer = layers.setdefault(layer_name, {"status": "VALID", "metrics": {}})
        layer["metrics"][obs.metric] = {
            "value": obs.value_num,
            "as_of_ms": obs.as_of_ms,
            "input_family": obs.input_family,
            "source_id": obs.source_id,
            "quality_state": obs.quality_state,
            "evidence_hash": obs.evidence_hash,
        }
    return layers


def _data_health(source_gate: dict[str, Any]) -> dict[str, Any]:
    rows = source_gate.get("evidence") or []
    invalid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = row.get("quality_state")
        if not (isinstance(state, str) and (state.startswith("VALID") or state == "DIAGNOSTIC_ONLY")):
            invalid.append(
                {
                    "input_family": row.get("input_family"),
                    "quality_state": state,
                    "quality_error": row.get("quality_error"),
                }
            )
    return {
        "source_gate_state": source_gate.get("formal_state"),
        "critical_blockers": deepcopy(source_gate.get("blocked_reasons", [])),
        "unusable_or_missing_evidence": invalid,
        "source_registry_hash": source_gate.get("source_registry_hash"),
    }


def _pack_state(source_gate: dict[str, Any], evidence_by_family: dict[str, dict[str, Any]], changes: dict[str, Any]) -> str:
    if source_gate.get("formal_state") == "BLOCKED":
        return "BLOCKED"
    for family in FIRST_SLICE_REQUIRED_FAMILIES:
        row = evidence_by_family.get(family)
        if row is None or not str(row.get("quality_state", "")).startswith("VALID"):
            return "BLOCKED"
    optional_missing = any(
        family not in evidence_by_family or not str(evidence_by_family[family].get("quality_state", "")).startswith("VALID")
        for family in FIRST_SLICE_OPTIONAL_FAMILIES
    )
    history_available = any(
        horizon.get("history_state") == "AVAILABLE"
        for metric in changes.values()
        for horizon in metric.get("horizons", {}).values()
    )
    if optional_missing or not history_available:
        return "PARTIAL_FOR_ANALYST"
    return "READY_FOR_ANALYST"


def build_evidence_pack(
    source_gate: dict[str, Any],
    *,
    observation_db: str | Path,
    generated_at_ms: int | None = None,
) -> dict[str, Any]:
    if not isinstance(source_gate, dict):
        raise ValueError("source_gate must be an object")
    _assert_authority(source_gate)
    generated_at = int(time.time() * 1000) if generated_at_ms is None else int(generated_at_ms)
    observations = extract_observations(source_gate, recorded_at_ms=generated_at)
    evidence_by_family = _evidence_by_family(source_gate)

    with ObservationStore(observation_db) as store:
        store.record(observations)
        changes = compute_changes(store, observations)
        top_changes = distill_top_changes(changes, limit=8)

    pack: dict[str, Any] = {
        "schema_version": PACK_SCHEMA_VERSION,
        "generated_at_ms": generated_at,
        "source_gate_run_id": source_gate.get("run_id"),
        "source_gate_idempotency_key": source_gate.get("idempotency_key"),
        "scope": {
            "slice": "L2_L4_L5_FIRST_SLICE",
            "available_layers": ["L2", "L4", "L5"],
            "not_yet_in_slice": ["L1", "L3", "L6"],
            "note": "This pack is not a complete six-layer CRT judgment input yet.",
        },
        "authority": {
            "production": "NOT_APPROVED",
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
            "external_action_performed": False,
            "analyst_judgment_required": True,
        },
        "data_health": _data_health(source_gate),
        "layers": _group_layers(observations),
        "changes": changes,
        "distillation": {
            "top_changes": top_changes,
            "formal_extremes": [],
            "divergences": [],
            "data_quality_conflicts": deepcopy(source_gate.get("blocked_reasons", [])),
            "note": "No investment-semantic extreme or divergence rule is invented in this first slice.",
        },
        "analyst_output": {
            "season": None,
            "weather": None,
            "dominant_forces": None,
            "asset_roles": None,
            "capital_strategy": None,
        },
    }
    pack["pack_state"] = _pack_state(source_gate, evidence_by_family, changes)
    pack["evidence_pack_hash"] = _sha256(pack)
    return pack
