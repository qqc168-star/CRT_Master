#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import statistics
from bisect import bisect_right
from copy import deepcopy
from pathlib import Path
from typing import Any


EXPECTED_LAYER_WEIGHTS = {"L1": 20, "L2": 20, "L3": 17, "L4": 25, "L5": 13, "L6": 5}
EXPECTED_LIGHT_THRESHOLDS = [-60, -35, 35, 60]
KNOWN_TRANSFORMS = {"ROBUST_Z", "PERCENTILE", "TANH_FIXED"}


class CandidateModelError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def canonical_hash(value: Any) -> str:
    return _sha256(value)


def _rounded(value: float) -> float:
    result = round(float(value), 10)
    return 0.0 if result == 0 else result


def _finite(value: Any, error_code: str) -> float:
    if isinstance(value, bool):
        raise CandidateModelError(error_code)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateModelError(error_code) from exc
    if not math.isfinite(result):
        raise CandidateModelError(error_code)
    return result


def load_registry(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateModelError("REGISTRY_NOT_OBJECT")
    return value


def _feature_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        feature["feature_id"]: feature
        for layer in registry.get("layers", [])
        for feature in layer.get("features", [])
        if isinstance(feature, dict) and isinstance(feature.get("feature_id"), str)
    }


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != "CRT_RESEARCH_CANDIDATE_MODEL_V0.1":
        errors.append("schema_version must be CRT_RESEARCH_CANDIDATE_MODEL_V0.1")
    if registry.get("status") != "RESEARCH_ONLY_NOT_APPROVED":
        errors.append("status must be RESEARCH_ONLY_NOT_APPROVED")

    authority = registry.get("authority")
    if not isinstance(authority, dict):
        errors.append("authority must be an object")
    else:
        expected_authority = {
            "formal_model": "NOT_APPROVED",
            "production": "NOT_APPROVED",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
            "capital_decision_authority": "USER_ONLY",
        }
        for key, expected in expected_authority.items():
            if authority.get(key) != expected:
                errors.append(f"authority.{key} must be {expected}")

    inherited = registry.get("inherited_formal_constants")
    if not isinstance(inherited, dict):
        errors.append("inherited_formal_constants must be an object")
        weights = None
        thresholds = None
    else:
        weights = inherited.get("layer_weights_percent")
        thresholds = inherited.get("light_thresholds")
        if weights != EXPECTED_LAYER_WEIGHTS:
            errors.append("formal layer weights changed")
        if thresholds != EXPECTED_LIGHT_THRESHOLDS:
            errors.append("formal light thresholds changed")
        if inherited.get("mnav_semantics") != "Diluted Equity mNAV":
            errors.append("mNAV semantics changed")
        if inherited.get("modification_authority") != "NONE":
            errors.append("formal constants modification authority must be NONE")

    layers = registry.get("layers")
    if not isinstance(layers, list):
        return errors + ["layers must be a list"]
    layer_ids = [layer.get("layer_id") for layer in layers if isinstance(layer, dict)]
    if layer_ids != list(EXPECTED_LAYER_WEIGHTS):
        errors.append("layers must be ordered L1 through L6 exactly once")

    feature_ids: list[str] = []
    for layer in layers:
        if not isinstance(layer, dict):
            errors.append("layer must be an object")
            continue
        layer_id = layer.get("layer_id")
        features = layer.get("features")
        if not isinstance(features, list) or not features:
            errors.append(f"{layer_id} features must be a non-empty list")
            continue
        internal_weight = 0.0
        for feature in features:
            if not isinstance(feature, dict):
                errors.append(f"{layer_id} feature must be an object")
                continue
            feature_id = feature.get("feature_id")
            if not isinstance(feature_id, str) or not feature_id:
                errors.append(f"{layer_id} feature_id missing")
                continue
            feature_ids.append(feature_id)
            if feature.get("required") is not True:
                errors.append(f"{feature_id} must be required; no missing-data reweighting")
            weight = feature.get("weight_percent")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
                errors.append(f"{feature_id} weight_percent must be positive")
            else:
                internal_weight += float(weight)
            if feature.get("direction") not in {-1, 1}:
                errors.append(f"{feature_id} direction must be -1 or 1")
            transform = feature.get("transform")
            if not isinstance(transform, dict) or transform.get("type") not in KNOWN_TRANSFORMS:
                errors.append(f"{feature_id} transform unsupported")
        if not math.isclose(internal_weight, 100.0):
            errors.append(f"{layer_id} feature weights must sum to 100")
    if len(feature_ids) != len(set(feature_ids)):
        errors.append("feature_id values must be unique")

    aggregation = registry.get("aggregation")
    if not isinstance(aggregation, dict):
        errors.append("aggregation must be an object")
    else:
        if aggregation.get("missing_policy") != "BLOCK_NO_RENORMALIZATION":
            errors.append("aggregation missing_policy must block without reweighting")
        if aggregation.get("score_range") != [-100, 100]:
            errors.append("aggregation score_range must be [-100, 100]")
    return errors


def _check_bound(feature: dict[str, Any], value: float) -> None:
    bounds = feature.get("valid_range")
    if not isinstance(bounds, dict):
        return
    if "minimum_inclusive" in bounds and value < float(bounds["minimum_inclusive"]):
        raise CandidateModelError("VALUE_OUT_OF_RANGE")
    if "minimum_exclusive" in bounds and value <= float(bounds["minimum_exclusive"]):
        raise CandidateModelError("VALUE_OUT_OF_RANGE")
    if "maximum_inclusive" in bounds and value > float(bounds["maximum_inclusive"]):
        raise CandidateModelError("VALUE_OUT_OF_RANGE")
    if "maximum_exclusive" in bounds and value >= float(bounds["maximum_exclusive"]):
        raise CandidateModelError("VALUE_OUT_OF_RANGE")


def _history(feature: dict[str, Any], observation: dict[str, Any]) -> list[float]:
    transform = feature["transform"]
    rows = observation.get("history")
    if not isinstance(rows, list):
        raise CandidateModelError("HISTORY_MISSING")
    try:
        current_ms = int(observation.get("as_of_ms"))
    except (TypeError, ValueError) as exc:
        raise CandidateModelError("AS_OF_INVALID") from exc
    normalized: list[tuple[int, float]] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateModelError("HISTORY_ROW_INVALID")
        try:
            as_of_ms = int(row.get("as_of_ms"))
        except (TypeError, ValueError) as exc:
            raise CandidateModelError("HISTORY_TIMESTAMP_INVALID") from exc
        if as_of_ms >= current_ms:
            raise CandidateModelError("HISTORY_NOT_STRICTLY_PRIOR")
        if as_of_ms in seen:
            raise CandidateModelError("HISTORY_TIMESTAMP_DUPLICATE")
        seen.add(as_of_ms)
        value = _finite(row.get("value"), "HISTORY_VALUE_INVALID")
        _check_bound(feature, value)
        normalized.append((as_of_ms, value))
    normalized.sort(key=lambda item: item[0])
    window = int(transform["history_window_observations"])
    minimum = int(transform["minimum_history_observations"])
    selected = normalized[-window:]
    if len(selected) < minimum:
        raise CandidateModelError("HISTORY_INSUFFICIENT")
    return [value for _, value in selected]


def score_feature(feature: dict[str, Any], observation: dict[str, Any]) -> float:
    if not isinstance(observation, dict):
        raise CandidateModelError("OBSERVATION_INVALID")
    try:
        as_of_ms = int(observation.get("as_of_ms"))
    except (TypeError, ValueError) as exc:
        raise CandidateModelError("AS_OF_INVALID") from exc
    if as_of_ms <= 0:
        raise CandidateModelError("AS_OF_INVALID")
    value = _finite(observation.get("value"), "VALUE_INVALID")
    _check_bound(feature, value)
    direction = int(feature["direction"])
    transform = feature["transform"]
    transform_type = transform["type"]

    if transform_type == "TANH_FIXED":
        scale = _finite(transform.get("scale"), "TRANSFORM_SCALE_INVALID")
        if scale <= 0:
            raise CandidateModelError("TRANSFORM_SCALE_INVALID")
        return _rounded(100.0 * math.tanh(direction * value / scale))

    history = _history(feature, observation)
    if transform_type == "ROBUST_Z":
        center = statistics.median(history)
        mad = statistics.median(abs(item - center) for item in history)
        if mad <= 0:
            raise CandidateModelError("HISTORY_ZERO_DISPERSION")
        clip_z = _finite(transform.get("clip_z"), "TRANSFORM_CLIP_INVALID")
        if clip_z <= 0:
            raise CandidateModelError("TRANSFORM_CLIP_INVALID")
        robust_z = (value - center) / (1.4826 * mad)
        signed = direction * max(-clip_z, min(clip_z, robust_z))
        return _rounded(100.0 * signed / clip_z)
    if transform_type == "PERCENTILE":
        below = sum(item < value for item in history)
        equal = sum(item == value for item in history)
        percentile = (below + 0.5 * equal) / len(history)
        return _rounded(direction * (2.0 * percentile - 1.0) * 100.0)
    raise CandidateModelError("TRANSFORM_UNSUPPORTED")


def _threshold_bucket(score: float, thresholds: list[float]) -> str:
    labels = ["C0_VERY_UNSUPPORTIVE", "C1_UNSUPPORTIVE", "C2_MIXED", "C3_SUPPORTIVE", "C4_VERY_SUPPORTIVE"]
    return labels[bisect_right(thresholds, score)]


def aggregate_feature_scores(
    registry: dict[str, Any],
    normalized_feature_scores: dict[str, Any],
) -> dict[str, Any]:
    errors = validate_registry(registry)
    if errors:
        raise CandidateModelError("REGISTRY_INVALID: " + "; ".join(errors))
    if not isinstance(normalized_feature_scores, dict):
        raise CandidateModelError("FEATURE_SCORES_NOT_OBJECT")

    layer_scores: dict[str, float] = {}
    for layer in registry["layers"]:
        value = 0.0
        for feature in layer["features"]:
            feature_id = feature["feature_id"]
            if feature_id not in normalized_feature_scores:
                raise CandidateModelError(f"{feature_id}_MISSING")
            score = _finite(normalized_feature_scores[feature_id], f"{feature_id}_INVALID")
            if score < -100 or score > 100:
                raise CandidateModelError(f"{feature_id}_OUT_OF_RANGE")
            value += score * float(feature["weight_percent"]) / 100.0
        layer_scores[layer["layer_id"]] = _rounded(value)

    weights = registry["inherited_formal_constants"]["layer_weights_percent"]
    candidate_score = _rounded(
        sum(layer_scores[layer_id] * float(weights[layer_id]) / 100.0 for layer_id in EXPECTED_LAYER_WEIGHTS)
    )
    return {
        "layer_scores": layer_scores,
        "candidate_score": candidate_score,
        "threshold_bucket": _threshold_bucket(
            candidate_score,
            registry["inherited_formal_constants"]["light_thresholds"],
        ),
    }


def _identity_blockers(registry: dict[str, Any], observations: dict[str, Any]) -> list[tuple[str, str]]:
    blockers: list[tuple[str, str]] = []
    for rule in registry.get("validation_rules", []):
        if rule.get("type") != "MVRV_NUPL_IDENTITY":
            blockers.append((str(rule.get("layer_id")), f"{rule.get('rule_id')}_UNSUPPORTED"))
            continue
        layer_id = str(rule["layer_id"])
        mvrv_id = str(rule["mvrv_feature_id"])
        nupl_id = str(rule["nupl_feature_id"])
        mvrv_item = observations.get(mvrv_id)
        nupl_item = observations.get(nupl_id)
        if not isinstance(mvrv_item, dict):
            blockers.append((layer_id, f"{mvrv_id}_MISSING"))
            continue
        if not isinstance(nupl_item, dict):
            blockers.append((layer_id, f"{nupl_id}_MISSING"))
            continue
        try:
            mvrv = _finite(mvrv_item.get("value"), f"{mvrv_id}_VALUE_INVALID")
            nupl = _finite(nupl_item.get("value"), f"{nupl_id}_VALUE_INVALID")
            if mvrv <= 0:
                raise CandidateModelError(f"{mvrv_id}_VALUE_OUT_OF_RANGE")
            if int(mvrv_item.get("as_of_ms")) != int(nupl_item.get("as_of_ms")):
                blockers.append((layer_id, f"{rule['rule_id']}_AS_OF_MISMATCH"))
                continue
        except (CandidateModelError, TypeError, ValueError) as exc:
            blockers.append((layer_id, str(exc)))
            continue
        expected = 1.0 - 1.0 / mvrv
        if abs(nupl - expected) > float(rule["absolute_tolerance"]):
            blockers.append((layer_id, f"{rule['rule_id']}_MISMATCH"))
    return blockers


def evaluate_candidate(
    observations: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    model = deepcopy(registry)
    errors = validate_registry(model)
    if errors:
        raise CandidateModelError("REGISTRY_INVALID: " + "; ".join(errors))
    if not isinstance(observations, dict):
        raise CandidateModelError("OBSERVATIONS_NOT_OBJECT")

    layer_results: dict[str, dict[str, Any]] = {}
    all_scores: dict[str, float] = {}
    blocker_pairs: list[tuple[str, str]] = []
    for layer in model["layers"]:
        layer_id = layer["layer_id"]
        scores: dict[str, float] = {}
        layer_blockers: list[str] = []
        for feature in layer["features"]:
            feature_id = feature["feature_id"]
            observation = observations.get(feature_id)
            if observation is None:
                reason = f"{feature_id}_MISSING"
                layer_blockers.append(reason)
                blocker_pairs.append((layer_id, reason))
                continue
            try:
                scores[feature_id] = score_feature(feature, observation)
            except CandidateModelError as exc:
                reason = f"{feature_id}_{exc}"
                layer_blockers.append(reason)
                blocker_pairs.append((layer_id, reason))
        layer_results[layer_id] = {
            "state": "BLOCKED" if layer_blockers else "VALID_RESEARCH_LAYER",
            "score": None,
            "feature_scores": scores,
            "blocked_reasons": sorted(set(layer_blockers)),
        }
        all_scores.update(scores)

    for layer_id, reason in _identity_blockers(model, observations):
        blocker_pairs.append((layer_id, reason))
        target = layer_results[layer_id]
        target["state"] = "BLOCKED"
        target["score"] = None
        target["blocked_reasons"] = sorted(set(target["blocked_reasons"] + [reason]))

    for layer in model["layers"]:
        layer_id = layer["layer_id"]
        target = layer_results[layer_id]
        if target["state"] == "BLOCKED":
            continue
        target["score"] = _rounded(
            sum(
                all_scores[feature["feature_id"]] * float(feature["weight_percent"]) / 100.0
                for feature in layer["features"]
            )
        )

    blocked_reasons = sorted({reason for _, reason in blocker_pairs})
    if blocked_reasons:
        aggregate = {"candidate_score": None, "threshold_bucket": None}
        model_state = "BLOCKED"
    else:
        aggregate = aggregate_feature_scores(model, all_scores)
        model_state = "VALID_RESEARCH_OUTPUT"

    result: dict[str, Any] = {
        "schema_version": "CRT_RESEARCH_CANDIDATE_OUTPUT_V0.1",
        "candidate_id": model["candidate_id"],
        "candidate_status": model["status"],
        "candidate_registry_hash": _sha256(model),
        "candidate_input_hash": _sha256(observations),
        "model_state": model_state,
        "candidate_score": aggregate["candidate_score"],
        "threshold_bucket": aggregate["threshold_bucket"],
        "threshold_semantics": "NON_FORMAL_OFFLINE_COMPARISON_ONLY",
        "layers": layer_results,
        "blocked_reasons": blocked_reasons,
        "capital_decision": None,
        "authority": deepcopy(model["authority"]),
    }
    result["candidate_output_hash"] = _sha256(result)
    return result


