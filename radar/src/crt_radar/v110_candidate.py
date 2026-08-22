from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .candidate_engine import (
    EXPECTED_LAYER_WEIGHTS,
    EXPECTED_LIGHT_THRESHOLDS,
    canonical_hash,
    evaluate_candidate,
    load_registry,
    validate_registry,
)
from .observation_store import ObservationRevisionConflict, ObservationStore
from .oi_revision_policy import (
    EXPECTED_POLICY_CANONICAL_SHA256,
    OiRevisionPolicyError,
    POLICY_ID,
    is_scoped_metric,
)


RADAR_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = RADAR_ROOT / "CONFIG" / "V110_FORMAL_CANDIDATE_RUNTIME_V0.1.json"
DEFAULT_REGISTRY = RADAR_ROOT / "research" / "CRT_SIX_LAYER_CANDIDATE_V0.1.json"
CONTRACT_SCHEMA_VERSION = "CRT_V110_FORMAL_CANDIDATE_RUNTIME_V0.1"
OUTPUT_SCHEMA_VERSION = "CRT_V110_FORMAL_CANDIDATE_OUTPUT_V0.1"
EXPECTED_STATUS = "FORMAL_CANDIDATE_NOT_APPROVED"
EXPECTED_CANDIDATE_ID = "CRT-V110-FORMAL-CANDIDATE-RUNTIME-V0.1"
EXPECTED_BASE_MAIN_SHA = "dc49442efa4a2b2cc442f77e13f4bb7b91b33e77"
EXPECTED_MNAV_SEMANTICS = "Diluted Equity mNAV"
EXPECTED_PARENT_PATH = "research/CRT_SIX_LAYER_CANDIDATE_V0.1.json"
EXPECTED_FORMAL_SEAL_PATH = "RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md"


class V110CandidateError(ValueError):
    pass


def _finite(value: Any, code: str) -> float:
    if isinstance(value, bool):
        raise V110CandidateError(code)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise V110CandidateError(code) from exc
    if not math.isfinite(result):
        raise V110CandidateError(code)
    return result


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V110CandidateError("CONTRACT_NOT_OBJECT")
    return value


def load_locked_registry(path: str | Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    return load_registry(path)


def _feature_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        feature["feature_id"]: {"layer_id": layer["layer_id"], "feature": feature}
        for layer in registry.get("layers", [])
        for feature in layer.get("features", [])
    }


def validate_contract(contract: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        errors.append("candidate contract schema changed")
    if contract.get("status") != EXPECTED_STATUS:
        errors.append("candidate status must remain not approved")
    if contract.get("candidate_id") != EXPECTED_CANDIDATE_ID:
        errors.append("candidate id changed")
    if contract.get("base_main_sha") != EXPECTED_BASE_MAIN_SHA:
        errors.append("candidate base main SHA changed")

    approval = contract.get("approval")
    if not isinstance(approval, dict):
        errors.append("approval must be an object")
    else:
        expected_approval = {
            "candidate_rebuild": "USER_APPROVED_2026-08-17",
            "exact_candidate_hash": "NOT_YET_APPROVED",
            "formal_model": "NOT_APPROVED",
            "production": "NOT_APPROVED",
            "capital_decision_authority": "USER_ONLY",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
        }
        for key, expected in expected_approval.items():
            if approval.get(key) != expected:
                errors.append(f"approval.{key} changed")

    inherited = contract.get("inherited_formal_constants")
    if not isinstance(inherited, dict):
        errors.append("inherited formal constants missing")
    else:
        if inherited.get("layer_weights_percent") != EXPECTED_LAYER_WEIGHTS:
            errors.append("V1.10 layer weights changed")
        if inherited.get("light_thresholds") != EXPECTED_LIGHT_THRESHOLDS:
            errors.append("V1.10 light thresholds changed")
        if inherited.get("mnav_semantics") != EXPECTED_MNAV_SEMANTICS:
            errors.append("V1.10 mNAV semantics changed")
        if inherited.get("modification_authority") != "NONE":
            errors.append("formal constant modification authority changed")
        if inherited.get("source") != EXPECTED_FORMAL_SEAL_PATH:
            errors.append("formal seal source changed")

    registry_errors = validate_registry(registry)
    if registry_errors:
        errors.extend(f"registry: {item}" for item in registry_errors)
    parent = contract.get("parent_research_registry")
    if not isinstance(parent, dict):
        errors.append("parent registry binding missing")
    else:
        if parent.get("path") != EXPECTED_PARENT_PATH:
            errors.append("parent registry path changed")
        if parent.get("canonical_sha256") != canonical_hash(registry):
            errors.append("parent registry canonical hash mismatch")
        if parent.get("status_required") != registry.get("status"):
            errors.append("parent registry status mismatch")

    index = _feature_index(registry)
    bindings = contract.get("feature_bindings")
    if not isinstance(bindings, list):
        errors.append("feature_bindings must be a list")
        bindings = []
    binding_ids = [item.get("feature_id") for item in bindings if isinstance(item, dict)]
    if len(binding_ids) != len(set(binding_ids)):
        errors.append("feature binding ids must be unique")
    if set(binding_ids) != set(index):
        errors.append("feature bindings must exactly cover the locked registry")
    for binding in bindings:
        if not isinstance(binding, dict):
            errors.append("feature binding must be an object")
            continue
        feature_id = binding.get("feature_id")
        indexed = index.get(feature_id)
        if indexed is not None and binding.get("layer_id") != indexed["layer_id"]:
            errors.append(f"{feature_id} layer binding changed")
        for field in ("metric", "input_family"):
            if not isinstance(binding.get(field), str) or not binding[field]:
                errors.append(f"{feature_id} {field} missing")
        sources = binding.get("allowed_source_ids")
        if not isinstance(sources, list) or not sources or any(not isinstance(item, str) or not item for item in sources):
            errors.append(f"{feature_id} allowed_source_ids invalid")

    validations = contract.get("validation_bindings")
    if not isinstance(validations, list) or [item.get("observation_id") for item in validations] != ["L5_NUPL_OBSERVED"]:
        errors.append("L5 NUPL validation binding changed")

    router = contract.get("season_router")
    if not isinstance(router, dict):
        errors.append("season router boundary missing")
    else:
        if router.get("status") != "SPEC_NOT_RECOVERED_CANDIDATE_FAIL_CLOSED":
            errors.append("season router must remain fail closed")
        if router.get("score_may_determine_btc_season") is not False:
            errors.append("candidate score cannot determine BTC season")
        if router.get("blocked_reason") != "V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED":
            errors.append("season router blocker changed")
    return errors


def _metric_observation(
    layers: dict[str, Any],
    binding: dict[str, Any],
    store: ObservationStore,
    *,
    needs_history: bool,
    evaluation_at_ms: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    feature_id = str(binding["feature_id"])
    layer = layers.get(binding["layer_id"])
    if not isinstance(layer, dict):
        return None, [f"{feature_id}_LAYER_MISSING"]
    metrics = layer.get("metrics")
    if not isinstance(metrics, dict):
        return None, [f"{feature_id}_LAYER_METRICS_MISSING"]
    item = metrics.get(binding["metric"])
    if not isinstance(item, dict):
        return None, [f"{feature_id}_METRIC_MISSING"]

    blockers: list[str] = []
    if item.get("input_family") != binding["input_family"]:
        blockers.append(f"{feature_id}_INPUT_FAMILY_NOT_APPROVED")
    if item.get("source_id") not in binding["allowed_source_ids"]:
        blockers.append(f"{feature_id}_SOURCE_NOT_APPROVED")
    quality = item.get("quality_state")
    if not isinstance(quality, str) or not quality.startswith("VALID"):
        blockers.append(f"{feature_id}_QUALITY_NOT_VALID")
    try:
        as_of_ms = int(item.get("as_of_ms"))
    except (TypeError, ValueError):
        blockers.append(f"{feature_id}_AS_OF_INVALID")
        as_of_ms = 0
    try:
        value = _finite(item.get("value"), f"{feature_id}_VALUE_INVALID")
    except V110CandidateError as exc:
        blockers.append(str(exc))
        value = 0.0
    if blockers:
        return None, sorted(set(blockers))

    observation: dict[str, Any] = {"as_of_ms": as_of_ms, "value": value}
    if needs_history:
        history: list[dict[str, Any]] = []
        history_blocked = False
        try:
            rows = (
                store.point_in_time_series(
                    binding["input_family"],
                    binding["metric"],
                    visible_at_ms=evaluation_at_ms,
                )
                if is_scoped_metric(binding["input_family"], binding["metric"])
                else store.series(binding["input_family"], binding["metric"])
            )
        except ObservationRevisionConflict as exc:
            blockers.append(f"{feature_id}_{str(exc).split(':', 1)[0]}")
            rows = []
        except OiRevisionPolicyError:
            blockers.append(f"{feature_id}_REVISION_POLICY_INVALID_BLOCKED")
            rows = []
        for row in rows:
            if row.as_of_ms >= as_of_ms:
                continue
            if row.source_id not in binding["allowed_source_ids"] or not row.quality_state.startswith("VALID"):
                history_blocked = True
                continue
            history.append({"as_of_ms": row.as_of_ms, "value": row.value_num})
        if history_blocked:
            blockers.append(f"{feature_id}_HISTORY_PROVENANCE_NOT_APPROVED")
        observation["history"] = history
    return observation, sorted(set(blockers))


def _route_candidate(candidate_score_output: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    router = contract["season_router"]
    result: dict[str, Any] = {
        "schema_version": "CRT_V110_SEASON_ROUTER_CANDIDATE_V0.1",
        "state": "BLOCKED",
        "reason": router["blocked_reason"],
        "season": None,
        "candidate_weather_bucket": candidate_score_output.get("threshold_bucket"),
        "analyst_judgment_required": True,
        "score_may_determine_btc_season": False,
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    result["router_output_hash"] = canonical_hash(result)
    return result


def evaluate_v110_candidate(
    layers: dict[str, Any],
    store: ObservationStore,
    *,
    contract: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
    evaluation_at_ms: int | None = None,
) -> dict[str, Any]:
    candidate_contract = deepcopy(contract if contract is not None else load_contract())
    locked_registry = deepcopy(registry if registry is not None else load_locked_registry())
    errors = validate_contract(candidate_contract, locked_registry)
    if errors:
        raise V110CandidateError("CONTRACT_INVALID: " + "; ".join(errors))
    if not isinstance(layers, dict):
        raise V110CandidateError("LAYERS_NOT_OBJECT")

    if evaluation_at_ms is None:
        layer_times: list[int] = []
        for layer in layers.values():
            if not isinstance(layer, dict):
                continue
            metrics = layer.get("metrics")
            if not isinstance(metrics, dict):
                continue
            for item in metrics.values():
                if not isinstance(item, dict):
                    continue
                try:
                    layer_times.append(int(item.get("as_of_ms")))
                except (TypeError, ValueError):
                    continue
        if not layer_times:
            raise V110CandidateError("EVALUATION_AT_INVALID")
        evaluation_at = max(layer_times)
    else:
        try:
            evaluation_at = int(evaluation_at_ms)
        except (TypeError, ValueError) as exc:
            raise V110CandidateError("EVALUATION_AT_INVALID") from exc
    if evaluation_at <= 0:
        raise V110CandidateError("EVALUATION_AT_INVALID")

    index = _feature_index(locked_registry)
    observations: dict[str, Any] = {}
    input_blockers: list[str] = []
    for binding in candidate_contract["feature_bindings"]:
        feature = index[binding["feature_id"]]["feature"]
        needs_history = feature["transform"]["type"] != "TANH_FIXED"
        observation, blockers = _metric_observation(
            layers,
            binding,
            store,
            needs_history=needs_history,
            evaluation_at_ms=evaluation_at,
        )
        input_blockers.extend(blockers)
        if observation is not None:
            observations[binding["feature_id"]] = observation

    for binding in candidate_contract["validation_bindings"]:
        validation_binding = {
            "feature_id": binding["observation_id"],
            "layer_id": binding["layer_id"],
            "metric": binding["metric"],
            "input_family": binding["input_family"],
            "allowed_source_ids": binding["allowed_source_ids"],
        }
        observation, blockers = _metric_observation(
            layers,
            validation_binding,
            store,
            needs_history=False,
            evaluation_at_ms=evaluation_at,
        )
        input_blockers.extend(blockers)
        if observation is not None:
            observations[binding["observation_id"]] = observation

    engine_output = evaluate_candidate(observations, locked_registry)
    scoring_blockers = sorted(set(input_blockers + engine_output["blocked_reasons"]))
    model_state = "VALID_CANDIDATE_OUTPUT" if not scoring_blockers else "BLOCKED"
    candidate_score = engine_output["candidate_score"] if model_state == "VALID_CANDIDATE_OUTPUT" else None
    threshold_bucket = engine_output["threshold_bucket"] if model_state == "VALID_CANDIDATE_OUTPUT" else None
    score_surface = {
        "model_state": model_state,
        "candidate_score": candidate_score,
        "threshold_bucket": threshold_bucket,
    }
    router_output = _route_candidate(score_surface, candidate_contract)

    result: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "candidate_id": candidate_contract["candidate_id"],
        "candidate_status": candidate_contract["status"],
        "candidate_contract_hash": canonical_hash(candidate_contract),
        "candidate_registry_hash": canonical_hash(locked_registry),
        "candidate_input_hash": canonical_hash(observations),
        "history_resolution": {
            "evaluation_at_ms": evaluation_at,
            "l4_oi_policy_id": POLICY_ID,
            "l4_oi_policy_canonical_sha256": EXPECTED_POLICY_CANONICAL_SHA256,
            "scope": "CANDIDATE_EVIDENCE_AND_HISTORY_REPLAY_ONLY",
        },
        "input_state": "COMPLETE" if not input_blockers else "BLOCKED",
        "input_blocked_reasons": sorted(set(input_blockers)),
        "model_state": model_state,
        "candidate_score": candidate_score,
        "threshold_bucket": threshold_bucket,
        "formal_score": None,
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "layers": engine_output["layers"],
        "scoring_blocked_reasons": scoring_blockers,
        "season_router": router_output,
        "season": None,
        "capital_decision": None,
        "authority": deepcopy(candidate_contract["approval"]),
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    result["candidate_output_hash"] = canonical_hash(result)
    return result
