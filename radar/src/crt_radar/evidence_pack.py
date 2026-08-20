from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .assumption_boundary_watch import evaluate_assumption_watch
from .asset_strategy_delta import build_asset_strategy_delta
from .change_engine import compute_changes, distill_top_changes
from .observation_store import Observation, ObservationStore, extract_observations
from .reflexivity_overlay import build_reflexivity_overlay
from .v110_candidate import evaluate_v110_candidate


PACK_SCHEMA_VERSION = "CRT_EVIDENCE_PACK_V0.2"
EXTERNAL_ACTION_AUTHORITY = "NONE"
FIRST_SLICE_REQUIRED_FAMILIES = {
    "DOLLAR_STRENGTH_PROXY",
    "OPEN_INTEREST",
    "FUNDING_RATE",
    "LIQUIDATION_AGGREGATES",
}
FIRST_SLICE_OPTIONAL_FAMILIES = {"ONCHAIN_VALUE"}
SIX_LAYER_REQUIRED_METRICS = {
    "L1": {
        "core_inflation_acceleration",
        "unemployment_deterioration",
        "real_policy_rate",
    },
    "L2": {
        "broad_usd_20d_log_change",
        "real_10y_yield_20d_change_bp",
        "nominal_2y_yield_20d_change_bp",
    },
    "L3": {
        "stablecoin_supply_30d_log_change",
        "spot_btc_etp_flow_20d_pct_aum",
        "high_yield_oas_20d_change_bp",
    },
    "L4": {
        "oi_to_market_cap_pct",
        "abs_funding_3d_mean_bp",
        "liquidation_intensity_24h_pct",
        "short_minus_long_liquidation_share_24h",
    },
    "L5": {"mvrv", "nupl", "realized_cap_30d_log_change"},
    "L6": {
        "close_minus_sma200_over_atr20",
        "sma50_minus_sma200_over_atr20",
        "return_20d_over_atr_vol",
        "cvd_20d_share",
    },
}
LOCKED_LAYER_WEIGHTS = {"L1": 20, "L2": 20, "L3": 17, "L4": 25, "L5": 13, "L6": 5}
LOCKED_LIGHT_THRESHOLDS = [-60, -35, 35, 60]


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
    for layer_name, layer in layers.items():
        required = SIX_LAYER_REQUIRED_METRICS.get(layer_name, set())
        missing = sorted(required - set(layer["metrics"]))
        layer["required_metrics"] = sorted(required)
        layer["missing_required_metrics"] = missing
        layer["status"] = "VALID" if not missing else "PARTIAL"
    return layers


def _model_status(layers: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    missing_by_layer: dict[str, list[str]] = {}
    for layer_name, required in SIX_LAYER_REQUIRED_METRICS.items():
        present = set(layers.get(layer_name, {}).get("metrics", {}))
        missing = sorted(required - present)
        if missing:
            missing_by_layer[layer_name] = missing

    evidence_blockers = [
        f"{layer_name}_{metric}_MISSING"
        for layer_name, metrics in missing_by_layer.items()
        for metric in metrics
    ]
    evidence_blockers.extend(candidate["input_blocked_reasons"])
    evidence_complete = not missing_by_layer and candidate["input_state"] == "COMPLETE"
    candidate_valid = candidate["model_state"] == "VALID_CANDIDATE_OUTPUT"
    router = candidate["season_router"]
    return {
        "six_layer_evidence": {
            "state": "COMPLETE_DIRECTIONAL" if evidence_complete else "BLOCKED",
            "missing_by_layer": missing_by_layer,
            "blocked_reasons": sorted(set(evidence_blockers)),
        },
        "locked_formal_scoring": {
            "state": "VALID_CANDIDATE_EXECUTABLE" if candidate_valid else "CANDIDATE_BLOCKED",
            "reason": (
                "FORMAL_CANDIDATE_AWAITING_EXACT_HASH_APPROVAL"
                if candidate_valid
                else "FORMAL_CANDIDATE_INPUT_OR_HISTORY_BLOCKED"
            ),
            "layer_weights_percent": LOCKED_LAYER_WEIGHTS,
            "light_thresholds": LOCKED_LIGHT_THRESHOLDS,
            "modification_authority": "NONE",
            "score": None,
            "candidate_score": candidate["candidate_score"],
            "candidate_threshold_bucket": candidate["threshold_bucket"],
            "candidate_contract_hash": candidate["candidate_contract_hash"],
            "candidate_output_hash": candidate["candidate_output_hash"],
            "formal_model": "NOT_APPROVED",
            "production": "NOT_APPROVED",
        },
        "btc_season_router": {
            "state": "CANDIDATE_BLOCKED",
            "reason": router["reason"],
            "season": None,
            "candidate_weather_bucket": router["candidate_weather_bucket"],
            "analyst_judgment_required": True,
            "score_may_determine_btc_season": False,
            "formal_model": "NOT_APPROVED",
            "production": "NOT_APPROVED",
        },
    }


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
        "runtime_checks": deepcopy(source_gate.get("runtime_checks", [])),
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


def _contract_surface(
    source_gate: dict[str, Any],
    reflexivity_input: dict[str, Any] | None,
) -> dict[str, Any]:
    blocked_reasons = source_gate.get("blocked_reasons")
    if not isinstance(blocked_reasons, list):
        blocked_reasons = []
    return build_reflexivity_overlay(
        reflexivity_input,
        source_gate_blocked_reasons=blocked_reasons,
    )


def build_evidence_pack(
    source_gate: dict[str, Any],
    *,
    observation_db: str | Path,
    generated_at_ms: int | None = None,
    reflexivity_input: dict[str, Any] | None = None,
    reanalysis_wake: dict[str, Any] | None = None,
    transition_diagnostic: dict[str, Any] | None = None,
    btc_entry_gate: dict[str, Any] | None = None,
    assumption_watch_context: dict[str, Any] | None = None,
    private_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(source_gate, dict):
        raise ValueError("source_gate must be an object")
    _assert_authority(source_gate)
    generated_at = int(time.time() * 1000) if generated_at_ms is None else int(generated_at_ms)
    observations = extract_observations(source_gate, recorded_at_ms=generated_at)
    evidence_by_family = _evidence_by_family(source_gate)

    layers = _group_layers(observations)
    with ObservationStore(observation_db) as store:
        store.record(observations)
        changes = compute_changes(store, observations)
        top_changes = distill_top_changes(changes, limit=8)
        formal_candidate = evaluate_v110_candidate(layers, store)

    pack: dict[str, Any] = {
        "schema_version": PACK_SCHEMA_VERSION,
        "action_output": "NONE",
        "generated_at_ms": generated_at,
        "source_gate_run_id": source_gate.get("run_id"),
        "source_gate_idempotency_key": source_gate.get("idempotency_key"),
        "scope": {
            "slice": "SIX_LAYER_EVIDENCE_TRANSITION_V0.3",
            "available_layers": sorted(layers),
            "not_yet_in_slice": sorted(set(SIX_LAYER_REQUIRED_METRICS) - set(layers)),
            "note": "The V1.10 locked-constant candidate is executable and fail-closed. Formal scoring and BTC season remain unapproved.",
        },
        "authority": {
            "production": "NOT_APPROVED",
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
            "external_action_performed": False,
            "analyst_judgment_required": True,
        },
        "data_health": _data_health(source_gate),
        "layers": layers,
        "model_status": _model_status(layers, formal_candidate),
        "formal_candidate": formal_candidate,
        "changes": changes,
        "distillation": {
            "top_changes": top_changes,
            "formal_extremes": [],
            "divergences": [],
            "data_quality_conflicts": deepcopy(source_gate.get("blocked_reasons", [])),
            "note": "No investment-semantic extreme or divergence rule is invented in this first slice.",
        },
        **_contract_surface(source_gate, reflexivity_input),
        "analyst_output": {
            "season": None,
            "weather": None,
            "dominant_forces": None,
            "asset_roles": None,
            "capital_strategy": None,
        },
    }
    if reanalysis_wake is not None:
        pack["reanalysis_wake"] = deepcopy(reanalysis_wake)
    if transition_diagnostic is not None:
        pack["transition_diagnostic"] = deepcopy(transition_diagnostic)
    if btc_entry_gate is not None:
        pack["btc_entry_gate"] = deepcopy(btc_entry_gate)
    if private_context is not None:
        pack["private_context"] = deepcopy(private_context)
    if assumption_watch_context is not None:
        assumption_watch = evaluate_assumption_watch(
            btc_entry_gate=btc_entry_gate,
            research_context=assumption_watch_context,
        )
        pack["assumption_watch"] = assumption_watch
        pack["asset_strategy_delta"] = build_asset_strategy_delta(
            btc_entry_gate=btc_entry_gate,
            assumption_watch=assumption_watch,
            private_context=private_context,
        )
    pack["pack_state"] = _pack_state(source_gate, evidence_by_family, changes)
    pack["evidence_pack_hash"] = _sha256(pack)
    return pack
