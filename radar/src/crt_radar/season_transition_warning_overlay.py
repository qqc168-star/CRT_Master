from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .candidate_engine import (
    EXPECTED_LIGHT_THRESHOLDS,
    LIGHT_BUCKETS,
    canonical_hash,
    threshold_bucket,
)


SCHEMA_VERSION = "CRT_SEASON_TRANSITION_WARNING_OVERLAY_V0.1"
OVERLAY_ID = "SEASON_TRANSITION_WARNING_OVERLAY"

PRICE_FEATURES = (
    (
        "L6_CLOSE_MINUS_SMA200_OVER_ATR20",
        "close_minus_sma200_over_atr20",
        30.0,
    ),
    (
        "L6_SMA50_MINUS_SMA200_OVER_ATR20",
        "sma50_minus_sma200_over_atr20",
        25.0,
    ),
    (
        "L6_RETURN_20D_OVER_ATR_VOL",
        "return_20d_over_atr_vol",
        25.0,
    ),
)
PRICE_SELECTED_WEIGHT = sum(row[2] for row in PRICE_FEATURES)

LIGHT_PRESENTATION = {
    "C0_VERY_UNSUPPORTIVE": ("DEEP_RED", "🔴"),
    "C1_UNSUPPORTIVE": ("RED", "🔴"),
    "C2_MIXED": ("YELLOW", "🟡"),
    "C3_SUPPORTIVE": ("GREEN", "🟢"),
    "C4_VERY_SUPPORTIVE": ("DEEP_GREEN", "🟢"),
}

FLOW_WINDOWS = ("1d", "5d", "20d", "60d", "120d")
FLOW_ROLES = {
    "1d": "EVENT_PULSE_DISPLAY_ONLY",
    "5d": "WEEKLY_IMPULSE_EARLY_WARNING",
    "20d": "TRANSITION_TREND_MAIN_LIGHT",
    "60d": "INSTITUTIONAL_PERSISTENCE",
    "120d": "REGIME_CONTEXT_DISPLAY_ONLY",
}

SCENARIOS = {
    "SCENARIO_1": "情境 1｜春季證據強升級",
    "SCENARIO_2": "情境 2｜春芽存在、仍在拉扯",
    "SCENARIO_3": "情境 3｜假春風險升高",
}

SCORE_LIGHT_KEYS = (
    "price_structure",
    "spot_demand",
    "institutional_flow",
    "leverage_quality",
)

REQUIRED_LIGHT_FIELDS = {
    "score",
    "threshold_bucket",
    "light",
    "direction",
    "delta_score",
    "delta_light",
    "raw_metrics",
    "evidence_status",
}


def _finite_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float) -> float:
    result = round(float(value), 10)
    return 0.0 if result == 0 else result


def _layer(candidate: dict[str, Any], layer_id: str) -> dict[str, Any]:
    value = candidate.get("layers", {}).get(layer_id, {})
    return value if isinstance(value, dict) else {}


def _feature_score(
    candidate: dict[str, Any],
    layer_id: str,
    feature_id: str,
) -> float | None:
    scores = _layer(candidate, layer_id).get("feature_scores", {})
    if not isinstance(scores, dict):
        return None
    score = _finite_or_none(scores.get(feature_id))
    if score is None or not -100.0 <= score <= 100.0:
        return None
    return score


def _layer_score(candidate: dict[str, Any], layer_id: str) -> float | None:
    score = _finite_or_none(_layer(candidate, layer_id).get("score"))
    if score is None or not -100.0 <= score <= 100.0:
        return None
    return score


def _metric(layers: dict[str, Any], layer_id: str, metric: str) -> float | None:
    item = (
        layers.get(layer_id, {})
        .get("metrics", {})
        .get(metric, {})
    )
    if not isinstance(item, dict):
        return None
    return _finite_or_none(item.get("value"))


def _valid_previous(
    previous: dict[str, Any] | None,
    generated_at_ms: int,
) -> dict[str, Any] | None:
    if not isinstance(previous, dict):
        return None
    if previous.get("schema_version") != SCHEMA_VERSION:
        return None
    previous_generated = previous.get("generated_at_ms")
    if not isinstance(previous_generated, int):
        return None
    if previous_generated >= generated_at_ms:
        return None
    lights = previous.get("lights")
    if not isinstance(lights, dict):
        return None
    return previous


def _score_delta(
    score: float | None,
    light: str,
    previous_light: dict[str, Any] | None,
) -> tuple[str, float | None, dict[str, Any]]:
    previous_score = None
    previous_name = None
    if isinstance(previous_light, dict):
        previous_score = _finite_or_none(previous_light.get("score"))
        previous_name = previous_light.get("light")

    delta = None
    direction = "BASELINE_PENDING"
    if score is not None and previous_score is not None:
        delta = _rounded(score - previous_score)
        if delta > 0:
            direction = "UP"
        elif delta < 0:
            direction = "DOWN"
        else:
            direction = "FLAT"

    return (
        direction,
        delta,
        {
            "from": previous_name,
            "to": light,
            "changed": (
                None
                if previous_name is None
                else previous_name != light
            ),
        },
    )


def _score_light(
    *,
    score: float | None,
    raw_metrics: dict[str, Any],
    evidence_status: str,
    scoring_method: str,
    previous_light: dict[str, Any] | None,
) -> dict[str, Any]:
    if score is None:
        bucket = None
        light = "NOT_AVAILABLE"
        symbol = "⚪"
    else:
        score = _rounded(score)
        bucket = threshold_bucket(score)
        light, symbol = LIGHT_PRESENTATION[bucket]
    direction, delta_score, delta_light = _score_delta(
        score,
        light,
        previous_light,
    )
    return {
        "score": score,
        "threshold_bucket": bucket,
        "light": light,
        "light_symbol": symbol,
        "direction": direction,
        "delta_score": delta_score,
        "delta_light": delta_light,
        "raw_metrics": raw_metrics,
        "evidence_status": evidence_status,
        "scoring_method": scoring_method,
        "light_thresholds": list(EXPECTED_LIGHT_THRESHOLDS),
    }


def _price_light(
    candidate: dict[str, Any],
    layers: dict[str, Any],
    previous_light: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_scores: dict[str, float | None] = {}
    raw_values: dict[str, float | None] = {}
    weighted = 0.0
    complete = True
    for feature_id, metric, weight in PRICE_FEATURES:
        score = _feature_score(candidate, "L6", feature_id)
        normalized_scores[feature_id] = score
        raw_values[feature_id] = _metric(layers, "L6", metric)
        if score is None:
            complete = False
        else:
            weighted += score * weight
    score = weighted / PRICE_SELECTED_WEIGHT if complete else None
    return _score_light(
        score=score,
        previous_light=previous_light,
        evidence_status="AVAILABLE" if complete else "BLOCKED_INCOMPLETE_L6_PRICE_FEATURES",
        scoring_method=(
            "REUSE_L6_EXISTING_FEATURE_WEIGHTS_RENORMALIZED_AFTER_"
            "INTENTIONAL_CVD_ROLE_SEPARATION"
        ),
        raw_metrics={
            "feature_values": raw_values,
            "normalized_feature_scores": normalized_scores,
            "selected_existing_l6_weight_percent": PRICE_SELECTED_WEIGHT,
            "excluded_from_price_light": ["L6_CVD_20D_SHARE"],
            "exclusion_reason": "AVOID_DUPLICATE_VOTE_WITH_SPOT_DEMAND_LIGHT",
            "event_research_coordinates": {
                "attack_zone_usd": [82000.0, 83000.0],
                "retest_defense_zone_usd": [80000.0, 82000.0],
                "scope": "EVENT_SCOPED_DISPLAY_ONLY",
                "used_in_score": False,
                "formal_threshold_authority": "NONE",
            },
        },
    )


def _mechanisms(transition_diagnostic: dict[str, Any]) -> dict[str, Any]:
    nested = transition_diagnostic.get("mechanism_findings")
    if isinstance(nested, dict):
        return nested
    return transition_diagnostic


def _window(transition_diagnostic: dict[str, Any], name: str) -> dict[str, Any]:
    windows = transition_diagnostic.get("windows", {})
    if not isinstance(windows, dict):
        return {}
    value = windows.get(name, {})
    return value if isinstance(value, dict) else {}


def _spot_light(
    candidate: dict[str, Any],
    layers: dict[str, Any],
    transition_diagnostic: dict[str, Any],
    previous_light: dict[str, Any] | None,
) -> dict[str, Any]:
    score = _feature_score(candidate, "L6", "L6_CVD_20D_SHARE")
    mechanisms = _mechanisms(transition_diagnostic)
    recent_60 = _window(transition_diagnostic, "recent_60m")
    recent_30 = _window(transition_diagnostic, "recent_30m")
    prior_30 = _window(transition_diagnostic, "prior_30m")
    return _score_light(
        score=score,
        previous_light=previous_light,
        evidence_status="AVAILABLE" if score is not None else "BLOCKED_L6_CVD_SCORE_UNAVAILABLE",
        scoring_method="DIRECT_REUSE_L6_CVD_20D_SHARE_FEATURE_SCORE",
        raw_metrics={
            "l6_cvd_20d_share": _metric(layers, "L6", "cvd_20d_share"),
            "spot_buy_share_pct": recent_60.get("spot_buy_share_pct"),
            "spot_cvd_proxy_usd": recent_60.get("spot_cvd_proxy_usd"),
            "prior_30m": {
                "spot_buy_share_pct": prior_30.get("spot_buy_share_pct"),
                "spot_cvd_proxy_usd": prior_30.get("spot_cvd_proxy_usd"),
            },
            "recent_30m": {
                "spot_buy_share_pct": recent_30.get("spot_buy_share_pct"),
                "spot_cvd_proxy_usd": recent_30.get("spot_cvd_proxy_usd"),
            },
            "persistence_30m_to_30m": mechanisms.get("spot_demand_persistence"),
            "spot_demand_absorption": mechanisms.get("spot_demand_absorption"),
            "leverage_quality_cross_check": mechanisms.get("leverage_quality"),
            "diagnostic_state": transition_diagnostic.get("state"),
        },
    )


def _normalize_flow_windows(
    context: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    supplied = context if isinstance(context, dict) else {}
    raw_windows = supplied.get("windows", {})
    available = supplied.get("state") == "AVAILABLE" and isinstance(raw_windows, dict)
    result: dict[str, dict[str, Any]] = {}
    for label in FLOW_WINDOWS:
        raw = raw_windows.get(label, {}) if available else {}
        if not isinstance(raw, dict):
            raw = {}
        flow = _finite_or_none(raw.get("flow_usd"))
        starting_aum = _finite_or_none(raw.get("starting_aum_usd"))
        if flow is None or starting_aum is None or starting_aum <= 0:
            state = "NOT_AVAILABLE"
            pct_aum = None
        else:
            state = "AVAILABLE"
            pct_aum = _rounded(100.0 * flow / starting_aum)
        result[label] = {
            "state": state,
            "role": FLOW_ROLES[label],
            "flow_pct_starting_aum": pct_aum,
            "flow_usd_display_only": flow,
            "starting_aum_usd": starting_aum,
            "used_in_main_light_score": label == "20d",
            "formal_threshold_authority": "NONE",
        }
    return result


def classify_institutional_flow_pattern(
    windows: dict[str, dict[str, Any]],
) -> str:
    signs: dict[str, int] = {}
    for label in ("5d", "20d", "60d"):
        value = _finite_or_none(
            windows.get(label, {}).get("flow_pct_starting_aum")
        )
        if value is None or value == 0:
            return "UNRESOLVED"
        signs[label] = 1 if value > 0 else -1
    signature = (signs["5d"], signs["20d"], signs["60d"])
    return {
        (1, -1, -1): "EARLY_TURN",
        (1, 1, -1): "WINTER_END_SPRING_BUD_FORMING",
        (1, 1, 1): "INSTITUTIONAL_PERSISTENCE_CONFIRMED",
        (-1, 1, 1): "SHORT_TERM_COOLING_NOT_WINTER_REVERSAL",
    }.get(signature, "MIXED_OR_UNRESOLVED")


def _institutional_light(
    candidate: dict[str, Any],
    layers: dict[str, Any],
    flow_context: dict[str, Any] | None,
    previous_light: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    score = _feature_score(
        candidate,
        "L3",
        "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM",
    )
    windows = _normalize_flow_windows(flow_context)
    pattern = classify_institutional_flow_pattern(windows)
    layer_value = _metric(
        layers,
        "L3",
        "spot_btc_etp_flow_20d_pct_aum",
    )
    context_20d = windows["20d"]["flow_pct_starting_aum"]
    consistent = (
        None
        if layer_value is None or context_20d is None
        else math.isclose(layer_value, context_20d, rel_tol=1e-9, abs_tol=1e-9)
    )
    context_complete = all(
        windows[label]["state"] == "AVAILABLE"
        for label in FLOW_WINDOWS
    )
    if score is None:
        evidence_status = "BLOCKED_L3_20D_ETP_SCORE_UNAVAILABLE"
    elif consistent is False:
        evidence_status = "AVAILABLE_WITH_20D_CONTEXT_CONFLICT"
    elif not context_complete:
        evidence_status = "AVAILABLE_WITH_MULTI_WINDOW_CONTEXT_GAPS"
    else:
        evidence_status = "AVAILABLE"
    return (
        _score_light(
            score=score,
            previous_light=previous_light,
            evidence_status=evidence_status,
            scoring_method="DIRECT_REUSE_L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM_FEATURE_SCORE",
            raw_metrics={
                "main_feature_id": "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM",
                "main_metric_value_pct_starting_aum": layer_value,
                "windows": windows,
                "flow_pattern_5d_20d_60d": pattern,
                "context_20d_matches_l3_metric": consistent,
                "normalization": "100_X_FLOW_USD_DIVIDED_BY_STARTING_AUM_USD",
                "usd_absolute_flow_role": "DISPLAY_ONLY",
                "window_policy": {
                    "1d": "DISPLAY_ONLY_EVENT_PULSE",
                    "5d": "EARLY_WARNING_CONTEXT",
                    "20d": "MAIN_LIGHT",
                    "60d": "PERSISTENCE_CONTEXT",
                    "120d": "DISPLAY_ONLY_REGIME_CONTEXT",
                },
            },
        ),
        pattern,
    )


def _history_change(
    changes: dict[str, Any],
    metric_names: tuple[str, ...],
    horizon: str,
) -> dict[str, Any]:
    for metric in metric_names:
        row = changes.get(metric)
        if not isinstance(row, dict):
            continue
        value = row.get("horizons", {}).get(horizon)
        if not isinstance(value, dict):
            continue
        return {
            "metric": metric,
            "history_state": value.get("history_state"),
            "percent_change": value.get("percent_change"),
            "absolute_change": value.get("absolute_change"),
            "previous_as_of_ms": value.get("previous_as_of_ms"),
        }
    return {
        "metric": None,
        "history_state": "INSUFFICIENT_HISTORY",
        "percent_change": None,
        "absolute_change": None,
        "previous_as_of_ms": None,
    }


def _leverage_light(
    candidate: dict[str, Any],
    layers: dict[str, Any],
    changes: dict[str, Any],
    previous_light: dict[str, Any] | None,
) -> dict[str, Any]:
    score = _layer_score(candidate, "L4")
    funding_rate = _metric(layers, "L4", "funding_rate")
    return _score_light(
        score=score,
        previous_light=previous_light,
        evidence_status="AVAILABLE" if score is not None else "BLOCKED_L4_LAYER_SCORE_UNAVAILABLE",
        scoring_method="DIRECT_REUSE_EXISTING_L4_LAYER_SCORE",
        raw_metrics={
            "oi_24h_change": _history_change(
                changes,
                ("open_interest_notional_usd", "open_interest_contracts"),
                "1d",
            ),
            "oi_3d_change": _history_change(
                changes,
                ("open_interest_notional_usd", "open_interest_contracts"),
                "3d",
            ),
            "latest_funding_rate": funding_rate,
            "latest_funding_bp": (
                None if funding_rate is None else _rounded(10_000.0 * funding_rate)
            ),
            "funding_3d_mean_bp": _metric(layers, "L4", "funding_3d_mean_bp"),
            "abs_funding_3d_mean_bp": _metric(layers, "L4", "abs_funding_3d_mean_bp"),
            "long_liquidation_24h_usd": _metric(
                layers,
                "L4",
                "liquidation_24h_long_usd",
            ),
            "short_liquidation_24h_usd": _metric(
                layers,
                "L4",
                "liquidation_24h_short_usd",
            ),
            "included_existing_l4_components": [
                "OPEN_INTEREST",
                "FUNDING_RATE",
                "LIQUIDATION_INTENSITY",
                "LONG_SHORT_LIQUIDATION_DIRECTION",
            ],
        },
    )


def _collect_veto_evidence(
    *,
    btc_bull_validation: dict[str, Any],
    btc_entry_gate: dict[str, Any],
    transition_diagnostic: dict[str, Any],
    btc_control_transfer_validation: dict[str, Any],
    institutional_evidence_status: str,
) -> tuple[str, list[str], list[str], str]:
    decisive: list[str] = []
    conflicts: list[str] = []
    transition_states = {
        btc_entry_gate.get("transition_state"),
        btc_bull_validation.get("state"),
    }
    if "BEAR_REJECTION_STRENGTHENED" in transition_states:
        decisive.append("BEAR_REJECTION_STRENGTHENED")
    elif "BEAR_REJECTION_PLAUSIBLE" in transition_states:
        conflicts.append("BEAR_REJECTION_PLAUSIBLE")

    control = btc_entry_gate.get("control_transfer_validation", {})
    if not isinstance(control, dict):
        control = {}
    control_states = {
        control.get("research_state"),
        control.get("current_validation_status"),
    }
    decisive_control_states = {
        "FALSE_POSITIVE_REJECTED",
        "BEAR_CONTROL_RETAINED",
        "CONTROL_TRANSFER_CANDIDATE_FAILED",
        "REVERSED",
    }
    for state in sorted(
        item for item in control_states
        if isinstance(item, str) and item in decisive_control_states
    ):
        decisive.append(f"CONTROL_TRANSFER_{state}")

    post_c_states = {
        btc_control_transfer_validation.get("research_state"),
        btc_control_transfer_validation.get("current_validation_status"),
    }
    for state in sorted(
        item for item in post_c_states
        if isinstance(item, str) and item in decisive_control_states
    ):
        decisive.append(f"POST_C_{state}")

    checks = btc_bull_validation.get("checks", [])
    if not isinstance(checks, list):
        checks = []
    for check in checks:
        if not isinstance(check, dict) or check.get("status") != "ADVERSE":
            continue
        check_id = str(check.get("check_id", "UNKNOWN_ADVERSE_CHECK"))
        if check_id == "CONTROL_TRANSFER_LOOP":
            decisive.append("CONTROL_TRANSFER_LOOP_REJECTED")
        else:
            conflicts.append(check_id)

    mechanisms = _mechanisms(transition_diagnostic)
    if mechanisms.get("spot_demand_absorption") == "NOT_SUPPORTED":
        conflicts.append("SPOT_DEMAND_ABSORPTION_NOT_SUPPORTED")
    if mechanisms.get("leverage_quality") == "CAUTION":
        conflicts.append("LEVERAGE_QUALITY_CAUTION")
    if institutional_evidence_status == "AVAILABLE_WITH_20D_CONTEXT_CONFLICT":
        conflicts.append("INSTITUTIONAL_20D_CONTEXT_CONFLICT")

    decisive = sorted(set(decisive))
    conflicts = sorted(set(conflicts) - set(decisive))
    if decisive:
        state = "DECISIVE_VETO"
    elif conflicts:
        state = "CONFLICT_PRESENT"
    else:
        state = "NO_DECISIVE_VETO"

    source_states = {
        str(btc_bull_validation.get("state", "NOT_AVAILABLE")),
        str(btc_entry_gate.get("state", "NOT_AVAILABLE")),
        str(transition_diagnostic.get("state", "NOT_AVAILABLE")),
        str(btc_control_transfer_validation.get("state", "NOT_AVAILABLE")),
    }
    evidence_status = (
        "PARTIAL_SOURCE_EVIDENCE"
        if source_states <= {"BLOCKED", "NOT_AVAILABLE", "NOT_REQUESTED"}
        else "AVAILABLE"
    )
    return state, decisive, conflicts, evidence_status


def _veto_light(
    *,
    btc_bull_validation: dict[str, Any],
    btc_entry_gate: dict[str, Any],
    transition_diagnostic: dict[str, Any],
    btc_control_transfer_validation: dict[str, Any],
    institutional_evidence_status: str,
    previous_light: dict[str, Any] | None,
) -> dict[str, Any]:
    state, decisive, conflicts, evidence_status = _collect_veto_evidence(
        btc_bull_validation=btc_bull_validation,
        btc_entry_gate=btc_entry_gate,
        transition_diagnostic=transition_diagnostic,
        btc_control_transfer_validation=btc_control_transfer_validation,
        institutional_evidence_status=institutional_evidence_status,
    )
    light, symbol = {
        "NO_DECISIVE_VETO": ("GREEN", "🟢"),
        "CONFLICT_PRESENT": ("YELLOW", "🟡"),
        "DECISIVE_VETO": ("RED", "🔴"),
    }[state]
    previous_state = (
        previous_light.get("threshold_bucket")
        if isinstance(previous_light, dict)
        else None
    )
    ranks = {
        "NO_DECISIVE_VETO": 0,
        "CONFLICT_PRESENT": 1,
        "DECISIVE_VETO": 2,
    }
    if previous_state not in ranks:
        direction = "BASELINE_PENDING"
    elif ranks[state] > ranks[previous_state]:
        direction = "WORSENING"
    elif ranks[state] < ranks[previous_state]:
        direction = "IMPROVING"
    else:
        direction = "FLAT"
    previous_name = previous_light.get("light") if isinstance(previous_light, dict) else None
    return {
        "score": None,
        "threshold_bucket": state,
        "light": light,
        "light_symbol": symbol,
        "direction": direction,
        "delta_score": None,
        "delta_light": {
            "from": previous_name,
            "to": light,
            "changed": None if previous_name is None else previous_name != light,
        },
        "raw_metrics": {
            "decisive_veto_evidence": decisive,
            "conflict_evidence": conflicts,
            "insurance_fuse_not_vote": True,
            "numeric_conflict_score": None,
        },
        "evidence_status": evidence_status,
        "scoring_method": "CATEGORICAL_FUSE_NO_NUMERIC_SCORE",
        "light_thresholds": None,
    }


def _bucket_supportive(light: dict[str, Any]) -> bool:
    return light.get("threshold_bucket") in {
        "C3_SUPPORTIVE",
        "C4_VERY_SUPPORTIVE",
    }


def _gate_core_veto(
    lights: dict[str, dict[str, Any]],
    flow_pattern: str,
) -> tuple[dict[str, Any], str]:
    price = lights["price_structure"]
    spot = lights["spot_demand"]
    institution = lights["institutional_flow"]
    leverage = lights["leverage_quality"]
    veto_state = lights["conflict_veto"]["threshold_bucket"]

    if price.get("score") is None:
        gate_state = "BLOCKED"
        gate_reason = "PRICE_STRUCTURE_SCORE_UNAVAILABLE"
    elif _bucket_supportive(price):
        gate_state = "OPEN"
        gate_reason = "PRICE_STRUCTURE_C3_OR_C4"
    else:
        gate_state = "CLOSED"
        gate_reason = "PRICE_STRUCTURE_BELOW_C3"

    spot_supportive = _bucket_supportive(spot)
    institution_supportive = _bucket_supportive(institution)
    leverage_bucket = leverage.get("threshold_bucket")
    leverage_acceptable = leverage_bucket in {
        "C2_MIXED",
        "C3_SUPPORTIVE",
        "C4_VERY_SUPPORTIVE",
    }
    if (
        spot_supportive
        and institution_supportive
        and leverage_acceptable
        and flow_pattern == "INSTITUTIONAL_PERSISTENCE_CONFIRMED"
    ):
        core_state = "STRONG"
        core_reason = "SPOT_AND_20D_FLOW_SUPPORTIVE_WITH_60D_PERSISTENCE_AND_NON_ADVERSE_L4"
    elif spot_supportive or institution_supportive:
        core_state = "DEVELOPING"
        core_reason = "CORE_TRANSITION_EVIDENCE_PRESENT_BUT_NOT_FULLY_PERSISTENT"
    elif spot.get("score") is None and institution.get("score") is None:
        core_state = "BLOCKED"
        core_reason = "SPOT_AND_INSTITUTIONAL_CORE_SCORES_UNAVAILABLE"
    else:
        core_state = "NOT_ESTABLISHED"
        core_reason = "CORE_TRANSITION_EVIDENCE_NOT_SUPPORTIVE"

    if veto_state == "DECISIVE_VETO":
        scenario_id = "SCENARIO_3"
        selection_reason = "DECISIVE_VETO_STOPS_UPGRADE"
    elif veto_state == "CONFLICT_PRESENT" and gate_state != "OPEN":
        scenario_id = "SCENARIO_3"
        selection_reason = "CONFLICT_WITH_PRICE_GATE_NOT_OPEN"
    elif (
        gate_state == "OPEN"
        and core_state == "STRONG"
        and veto_state == "NO_DECISIVE_VETO"
    ):
        scenario_id = "SCENARIO_1"
        selection_reason = "PRICE_GATE_OPEN_AND_CORE_STRONG_WITHOUT_DECISIVE_VETO"
    else:
        scenario_id = "SCENARIO_2"
        selection_reason = "TRANSITION_EVIDENCE_REMAINS_IN_TENSION"

    return (
        {
            "decision_method": "GATE_PLUS_CORE_PLUS_VETO",
            "vote_counting_used": False,
            "gate": {"state": gate_state, "reason": gate_reason},
            "core": {
                "state": core_state,
                "reason": core_reason,
                "spot_supportive": spot_supportive,
                "institution_20d_supportive": institution_supportive,
                "institution_5d_20d_60d_pattern": flow_pattern,
                "leverage_guard": (
                    "ACCEPTABLE"
                    if leverage_acceptable
                    else "ADVERSE_OR_UNAVAILABLE"
                ),
            },
            "veto": {
                "state": veto_state,
                "upgrade_blocked": veto_state == "DECISIVE_VETO",
                "insurance_fuse_not_fifth_vote": True,
            },
            "selection_reason": selection_reason,
        },
        scenario_id,
    )


def _evidence_momentum(lights: dict[str, dict[str, Any]]) -> str:
    veto_direction = lights["conflict_veto"]["direction"]
    if veto_direction == "WORSENING":
        return "FALLING"
    deltas = [
        lights[key]["delta_score"]
        for key in SCORE_LIGHT_KEYS
        if lights[key]["delta_score"] is not None
    ]
    if not deltas:
        return "BASELINE_PENDING"
    if all(value >= 0 for value in deltas) and any(value > 0 for value in deltas):
        return "RISING"
    if all(value <= 0 for value in deltas) and any(value < 0 for value in deltas):
        return "FALLING"
    if all(value == 0 for value in deltas) and veto_direction in {"FLAT", "BASELINE_PENDING"}:
        return "FLAT"
    return "MIXED"


def _historical_replay(
    *,
    generated_at_ms: int,
    scenario_id: str,
    previous: dict[str, Any] | None,
    replay_context: dict[str, Any] | None,
) -> dict[str, Any]:
    signal_active = scenario_id in {"SCENARIO_1", "SCENARIO_2"}
    previous_replay = previous.get("historical_replay", {}) if previous else {}
    previous_active = bool(previous_replay.get("spring_transition_signal_active"))
    previous_onset = previous_replay.get("warning_onset_ms")
    if signal_active and previous_active and isinstance(previous_onset, int):
        onset = previous_onset
    elif signal_active:
        onset = generated_at_ms
    else:
        onset = None

    context = replay_context if isinstance(replay_context, dict) else {}
    historical_case_id = context.get("historical_case_id")
    ground_truth_at = context.get("ground_truth_transition_at_ms")
    if not isinstance(ground_truth_at, int):
        ground_truth_at = None
    outcome = context.get("ground_truth_outcome")
    if outcome not in {"TRANSITION_CONFIRMED", "NO_TRANSITION"}:
        outcome = None
    latency = (
        onset - ground_truth_at
        if onset is not None and ground_truth_at is not None
        else None
    )
    if outcome == "NO_TRANSITION":
        false_positive = signal_active
    elif outcome == "TRANSITION_CONFIRMED":
        false_positive = False if signal_active else None
    else:
        false_positive = None
    return {
        "objective": "DETECTION_LATENCY_X_FALSE_POSITIVE",
        "state": "EVALUATED" if outcome is not None else "GROUND_TRUTH_PENDING",
        "historical_case_id": historical_case_id,
        "spring_transition_signal_active": signal_active,
        "warning_onset_ms": onset,
        "ground_truth_transition_at_ms": ground_truth_at,
        "detection_latency_ms": latency,
        "ground_truth_outcome": outcome,
        "false_positive": false_positive,
        "optimization_policy": "DO_NOT_MINIMIZE_FALSE_POSITIVES_AT_THE_COST_OF_EXCESSIVE_LATENCY",
    }


def _format_score(value: float | None) -> str:
    if value is None:
        return "N/A"
    rounded = round(value)
    if math.isclose(value, rounded, abs_tol=1e-9):
        return f"{rounded:+d}"
    return f"{value:+.1f}"


def _direction_symbol(direction: str) -> str:
    return {
        "UP": "↑",
        "DOWN": "↓",
        "FLAT": "→",
        "WORSENING": "↑",
        "IMPROVING": "↓",
    }.get(direction, "→")


def _render_card(
    *,
    research_season: str,
    transition_warning: dict[str, Any],
    lights: dict[str, dict[str, Any]],
    scenario_label: str,
    evidence_momentum: str,
) -> str:
    labels = (
        ("① 價格結構", "price_structure"),
        ("② 現貨需求", "spot_demand"),
        ("③ 機構資金", "institutional_flow"),
        ("④ 槓桿品質", "leverage_quality"),
    )
    rows = [
        "CRT｜季節轉換預警",
        "",
        "Formal Season（正式季節）: NOT CONFIRMED",
        f"Research Season（研究季節）: {research_season}",
        (
            "Transition Warning（轉季預警）: "
            f"{transition_warning['level']} / {transition_warning['direction']}"
        ),
        "",
    ]
    for label, key in labels:
        light = lights[key]
        rows.append(
            f"{label:<10} {light['light_symbol']} "
            f"{_format_score(light['score'])} "
            f"{_direction_symbol(light['direction'])}"
        )
    veto = lights["conflict_veto"]
    rows.append(f"⑤ 重大反證       {veto['light_symbol']}")
    rows.extend(
        [
            "",
            scenario_label,
            f"Evidence Momentum（證據動量）: {evidence_momentum}",
        ]
    )
    return "\n".join(rows)


def build_season_transition_warning_overlay(
    *,
    formal_candidate: dict[str, Any],
    layers: dict[str, Any],
    changes: dict[str, Any],
    btc_bull_validation: dict[str, Any] | None,
    btc_entry_gate: dict[str, Any] | None,
    transition_diagnostic: dict[str, Any] | None,
    generated_at_ms: int,
    institutional_flow_context: dict[str, Any] | None = None,
    previous_overlay: dict[str, Any] | None = None,
    historical_replay_context: dict[str, Any] | None = None,
    btc_control_transfer_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a research warning overlay without routing Formal Season or actions."""

    candidate = formal_candidate if isinstance(formal_candidate, dict) else {}
    layer_data = layers if isinstance(layers, dict) else {}
    change_data = changes if isinstance(changes, dict) else {}
    bull = btc_bull_validation if isinstance(btc_bull_validation, dict) else {}
    entry = btc_entry_gate if isinstance(btc_entry_gate, dict) else {}
    diagnostic = transition_diagnostic if isinstance(transition_diagnostic, dict) else {}
    post_c = (
        btc_control_transfer_validation
        if isinstance(btc_control_transfer_validation, dict)
        else {}
    )
    generated_at = int(generated_at_ms)
    previous = _valid_previous(previous_overlay, generated_at)
    previous_lights = previous.get("lights", {}) if previous else {}

    lights: dict[str, dict[str, Any]] = {}
    lights["price_structure"] = _price_light(
        candidate,
        layer_data,
        previous_lights.get("price_structure"),
    )
    lights["spot_demand"] = _spot_light(
        candidate,
        layer_data,
        diagnostic,
        previous_lights.get("spot_demand"),
    )
    institution, flow_pattern = _institutional_light(
        candidate,
        layer_data,
        institutional_flow_context,
        previous_lights.get("institutional_flow"),
    )
    lights["institutional_flow"] = institution
    lights["leverage_quality"] = _leverage_light(
        candidate,
        layer_data,
        change_data,
        previous_lights.get("leverage_quality"),
    )
    lights["conflict_veto"] = _veto_light(
        btc_bull_validation=bull,
        btc_entry_gate=entry,
        transition_diagnostic=diagnostic,
        btc_control_transfer_validation=post_c,
        institutional_evidence_status=institution["evidence_status"],
        previous_light=previous_lights.get("conflict_veto"),
    )

    gate_core_veto, scenario_id = _gate_core_veto(lights, flow_pattern)
    momentum = _evidence_momentum(lights)
    veto_direction = lights["conflict_veto"]["direction"]
    conflict_direction = {
        "WORSENING": "RISING",
        "IMPROVING": "FALLING",
        "FLAT": "FLAT",
    }.get(veto_direction, "BASELINE_PENDING")
    warning_direction = (
        momentum
        if momentum in {"RISING", "FALLING", "FLAT", "MIXED"}
        else "BASELINE_PENDING"
    )
    transition_warning = {
        "level": "HIGH" if scenario_id in {"SCENARIO_1", "SCENARIO_3"} else "WATCH",
        "direction": warning_direction,
        "focus": (
            "SPRING_EVIDENCE_UPGRADE"
            if scenario_id == "SCENARIO_1"
            else "FALSE_SPRING_RISK"
            if scenario_id == "SCENARIO_3"
            else "EVIDENCE_TENSION"
        ),
    }
    research_season = (
        "WINTER -> SPRING CANDIDATE AT RISK"
        if scenario_id == "SCENARIO_3"
        else "WINTER -> SPRING CANDIDATE"
    )
    replay = _historical_replay(
        generated_at_ms=generated_at,
        scenario_id=scenario_id,
        previous=previous,
        replay_context=historical_replay_context,
    )

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "overlay_id": OVERLAY_ID,
        "scope": "RESEARCH_DECISION_SUPPORT_ONLY",
        "generated_at_ms": generated_at,
        "formal_season_status": "NOT_CONFIRMED",
        "formal_season": None,
        "research_season": research_season,
        "transition_warning": transition_warning,
        "evidence_momentum": momentum,
        "conflict_direction": conflict_direction,
        "lights": lights,
        "gate_core_veto": gate_core_veto,
        "scenario": {
            "id": scenario_id,
            "label": SCENARIOS[scenario_id],
            "selection_reason": gate_core_veto["selection_reason"],
        },
        "historical_replay": replay,
        "inherited_locks": {
            "light_thresholds": list(EXPECTED_LIGHT_THRESHOLDS),
            "light_buckets": list(LIGHT_BUCKETS),
            "formal_layer_weights_modified": False,
            "mnav_semantics_modified": False,
        },
        "authority": {
            "formal_model": "NOT_APPROVED",
            "production": "NOT_APPROVED",
            "formal_season_authority": "NONE",
            "score_may_determine_btc_season": False,
            "machine_may_confirm_bull_transition": False,
            "machine_may_output_trade_action": False,
            "analyst_judgment_required": True,
            "capital_decision_authority": "USER_ONLY",
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        },
    }
    result["card"] = _render_card(
        research_season=research_season,
        transition_warning=transition_warning,
        lights=lights,
        scenario_label=SCENARIOS[scenario_id],
        evidence_momentum=momentum,
    )
    result["overlay_hash"] = canonical_hash(result)
    return result


def validate_season_transition_warning_overlay(
    overlay: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(overlay, dict):
        return ["overlay must be an object"]
    if overlay.get("schema_version") != SCHEMA_VERSION:
        errors.append("overlay schema_version changed")
    if overlay.get("overlay_id") != OVERLAY_ID:
        errors.append("overlay id changed")
    if overlay.get("scope") != "RESEARCH_DECISION_SUPPORT_ONLY":
        errors.append("overlay scope must remain research decision support only")
    if overlay.get("formal_season_status") != "NOT_CONFIRMED":
        errors.append("Formal Season status must remain not confirmed")
    if overlay.get("formal_season") is not None:
        errors.append("Formal Season must remain null")

    locks = overlay.get("inherited_locks")
    if not isinstance(locks, dict):
        errors.append("inherited locks missing")
    else:
        if locks.get("light_thresholds") != EXPECTED_LIGHT_THRESHOLDS:
            errors.append("light thresholds changed")
        if locks.get("light_buckets") != list(LIGHT_BUCKETS):
            errors.append("light buckets changed")
        if locks.get("formal_layer_weights_modified") is not False:
            errors.append("formal layer weights modification flag must be false")
        if locks.get("mnav_semantics_modified") is not False:
            errors.append("mNAV semantics modification flag must be false")

    expected_authority = {
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "formal_season_authority": "NONE",
        "score_may_determine_btc_season": False,
        "machine_may_confirm_bull_transition": False,
        "machine_may_output_trade_action": False,
        "analyst_judgment_required": True,
        "capital_decision_authority": "USER_ONLY",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    if overlay.get("authority") != expected_authority:
        errors.append("overlay authority boundary changed")

    lights = overlay.get("lights")
    expected_light_keys = set(SCORE_LIGHT_KEYS) | {"conflict_veto"}
    if not isinstance(lights, dict) or set(lights) != expected_light_keys:
        errors.append("overlay must contain exactly five required lights")
        lights = {}
    for key in SCORE_LIGHT_KEYS:
        light = lights.get(key)
        if not isinstance(light, dict) or not REQUIRED_LIGHT_FIELDS <= set(light):
            errors.append(f"{key} light contract incomplete")
            continue
        score = _finite_or_none(light.get("score"))
        if score is None:
            if light.get("threshold_bucket") is not None or light.get("light") != "NOT_AVAILABLE":
                errors.append(f"{key} unavailable score must have no bucket and no light")
            continue
        try:
            expected_bucket = threshold_bucket(score)
        except Exception:
            errors.append(f"{key} score invalid")
            continue
        if light.get("threshold_bucket") != expected_bucket:
            errors.append(f"{key} threshold bucket mismatch")
        if light.get("light") != LIGHT_PRESENTATION[expected_bucket][0]:
            errors.append(f"{key} light presentation mismatch")

    veto = lights.get("conflict_veto")
    if not isinstance(veto, dict) or not REQUIRED_LIGHT_FIELDS <= set(veto):
        errors.append("conflict veto light contract incomplete")
    else:
        veto_state = veto.get("threshold_bucket")
        expected_veto_lights = {
            "NO_DECISIVE_VETO": "GREEN",
            "CONFLICT_PRESENT": "YELLOW",
            "DECISIVE_VETO": "RED",
        }
        if veto.get("score") is not None or veto.get("delta_score") is not None:
            errors.append("conflict veto must not have a numeric score")
        if veto_state not in expected_veto_lights:
            errors.append("conflict veto state invalid")
        elif veto.get("light") != expected_veto_lights[veto_state]:
            errors.append("conflict veto light mismatch")

    decision = overlay.get("gate_core_veto")
    if not isinstance(decision, dict):
        errors.append("Gate + Core + VETO result missing")
    else:
        if decision.get("decision_method") != "GATE_PLUS_CORE_PLUS_VETO":
            errors.append("decision method changed")
        if decision.get("vote_counting_used") is not False:
            errors.append("vote counting must remain disabled")

    scenario = overlay.get("scenario")
    if not isinstance(scenario, dict):
        errors.append("scenario missing")
    else:
        scenario_id = scenario.get("id")
        if scenario_id not in SCENARIOS:
            errors.append("scenario id invalid")
        elif scenario.get("label") != SCENARIOS[scenario_id]:
            errors.append("scenario label changed")

    replay = overlay.get("historical_replay")
    if not isinstance(replay, dict) or replay.get("objective") != "DETECTION_LATENCY_X_FALSE_POSITIVE":
        errors.append("historical replay objective changed")

    supplied_hash = overlay.get("overlay_hash")
    material = deepcopy(overlay)
    material.pop("overlay_hash", None)
    if supplied_hash != canonical_hash(material):
        errors.append("overlay hash mismatch")
    return errors


def assert_season_transition_warning_overlay(
    overlay: dict[str, Any],
) -> None:
    errors = validate_season_transition_warning_overlay(overlay)
    if errors:
        raise ValueError(
            "SEASON_TRANSITION_WARNING_OVERLAY_INVALID: "
            + "; ".join(errors)
        )
