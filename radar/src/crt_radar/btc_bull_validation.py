from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "CRT_BTC_BULL_VALIDATION_OVERLAY_V0.1"

ALLOWED_TRANSITION_STATES = {
    "TRANSITION_UNRESOLVED",
    "BULL_ACCEPTANCE_DEVELOPING",
    "BULL_ACCEPTANCE_STRENGTHENED",
    "BEAR_REJECTION_PLAUSIBLE",
    "BEAR_REJECTION_STRENGTHENED",
}


def _check(
    check_id: str,
    status: str,
    reason: str,
    *,
    value: Any = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "reason": reason,
        "value": value,
    }


def _l3_etp_flow(layers: dict[str, Any]) -> dict[str, Any]:
    metric = (
        layers.get("L3", {})
        .get("metrics", {})
        .get("spot_btc_etp_flow_20d_pct_aum")
    )

    if not isinstance(metric, dict):
        return _check(
            "SPOT_BTC_ETP_FLOW",
            "PENDING",
            "SPOT_BTC_ETP_FLOW_NOT_AVAILABLE",
        )

    value = metric.get("value")
    if not isinstance(value, (int, float)):
        return _check(
            "SPOT_BTC_ETP_FLOW",
            "PENDING",
            "SPOT_BTC_ETP_FLOW_VALUE_NOT_COMPARABLE",
        )

    if value > 0:
        status = "SUPPORTIVE"
        reason = "TWENTY_DAY_FLOW_POSITIVE"
    elif value < 0:
        status = "ADVERSE"
        reason = "TWENTY_DAY_FLOW_NEGATIVE"
    else:
        status = "NEUTRAL"
        reason = "TWENTY_DAY_FLOW_FLAT"

    return _check(
        "SPOT_BTC_ETP_FLOW",
        status,
        reason,
        value=float(value),
    )


def _l6_breakout_volume_quality(layers: dict[str, Any]) -> dict[str, Any]:
    metrics = layers.get("L6", {}).get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    metric_names = (
        "quote_volume_rvol20",
        "taker_buy_quote_share_1d",
        "cvd_20d_share",
    )

    values: dict[str, float] = {}
    missing: list[str] = []

    for metric_name in metric_names:
        item = metrics.get(metric_name)
        if not isinstance(item, dict):
            missing.append(metric_name)
            continue

        value = item.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            missing.append(metric_name)
            continue

        values[metric_name] = float(value)

    if missing:
        return _check(
            "BREAKOUT_VOLUME_QUALITY",
            "PENDING",
            "L6_SPOT_VOLUME_RESEARCH_METRICS_NOT_COMPLETE",
            value={
                "missing_metrics": sorted(missing),
                "formal_threshold_authority": "NONE",
                "formal_composite_authority": "NONE",
                "source_scope": "BINANCE_BTCUSDT_DIRECTIONAL_PROXY",
            },
        )

    rvol = values["quote_volume_rvol20"]
    taker_buy_share = values["taker_buy_quote_share_1d"]
    cvd_share = values["cvd_20d_share"]

    volume_expanded = rvol > 1.0
    latest_buy_dominant = taker_buy_share > 0.5
    latest_sell_dominant = taker_buy_share < 0.5
    persistent_buy_positive = cvd_share > 0.0
    persistent_sell_negative = cvd_share < 0.0

    if (
        volume_expanded
        and latest_buy_dominant
        and persistent_buy_positive
    ):
        status = "SUPPORTIVE"
        reason = "EXPANDED_SPOT_VOLUME_WITH_BUY_DOMINANCE_AND_POSITIVE_20D_CVD"
    elif (
        volume_expanded
        and latest_sell_dominant
        and persistent_sell_negative
    ):
        status = "ADVERSE"
        reason = "EXPANDED_SPOT_VOLUME_WITH_SELL_DOMINANCE_AND_NEGATIVE_20D_CVD"
    else:
        status = "MIXED"
        reason = "SPOT_VOLUME_DIRECTIONAL_EVIDENCE_MIXED"

    return _check(
        "BREAKOUT_VOLUME_QUALITY",
        status,
        reason,
        value={
            **values,
            "volume_expanded": volume_expanded,
            "latest_buy_dominant": latest_buy_dominant,
            "persistent_buy_positive": persistent_buy_positive,
            "natural_research_baselines": {
                "quote_volume_rvol20": 1.0,
                "taker_buy_quote_share_1d": 0.5,
                "cvd_20d_share": 0.0,
            },
            "baseline_meaning": {
                "quote_volume_rvol20": "LATEST_COMPLETE_DAY_VS_PRIOR_20_COMPLETE_DAY_MEAN",
                "taker_buy_quote_share_1d": "LATEST_COMPLETE_DAY_BUY_SELL_MAJORITY",
                "cvd_20d_share": "TWENTY_DAY_TAKER_IMBALANCE_SIGN",
            },
            "formal_threshold_authority": "NONE",
            "formal_composite_authority": "NONE",
            "source_scope": "BINANCE_BTCUSDT_DIRECTIONAL_PROXY",
        },
    )


def evaluate_btc_bull_validation(
    *,
    pack_state: str,
    btc_entry_gate: dict[str, Any] | None,
    transition_diagnostic: dict[str, Any] | None,
    layers: dict[str, Any],
    generated_at_ms: int,
) -> dict[str, Any]:
    entry = btc_entry_gate if isinstance(btc_entry_gate, dict) else {}
    transition = entry.get("transition_state")

    if pack_state == "BLOCKED":
        state = "BLOCKED"
        reason = "EVIDENCE_PACK_BLOCKED"
    elif entry.get("state") == "BLOCKED":
        state = "BLOCKED"
        reason = str(entry.get("reason", "BTC_ENTRY_GATE_BLOCKED"))
    elif transition in ALLOWED_TRANSITION_STATES:
        state = str(transition)
        reason = str(entry.get("reason", "ENTRY_GATE_TRANSITION_STATE"))
    else:
        state = "TRANSITION_UNRESOLVED"
        reason = "BTC_ENTRY_GATE_TRANSITION_NOT_AVAILABLE"

    quantitative = entry.get("quantitative")
    if not isinstance(quantitative, dict):
        quantitative = {}

    mechanism = entry.get("mechanism_support")
    if not isinstance(mechanism, dict):
        mechanism = {}

    accepted_upper = quantitative.get("accepted_upper_by_price_closes")
    accepted_lower = quantitative.get("accepted_lower_by_price_closes")
    rejected_lower = quantitative.get("rejected_lower_by_price_closes")
    provisional_sma = quantitative.get("provisional_sma200_reclaim")
    closed_daily_sma = quantitative.get("closed_daily_sma200_reclaim")

    if entry.get("state") == "BLOCKED":
        price_check = _check(
            "PRICE_ACCEPTANCE_AND_SMA200",
            "BLOCKED",
            "BTC_ENTRY_GATE_BLOCKED",
        )
    elif accepted_upper is True and provisional_sma is True:
        price_check = _check(
            "PRICE_ACCEPTANCE_AND_SMA200",
            "SUPPORTIVE",
            (
                "UPPER_RESEARCH_CORRIDOR_ACCEPTED_AND_SMA200_RECLAIMED"
                if closed_daily_sma is True
                else "UPPER_RESEARCH_CORRIDOR_ACCEPTED_WITH_PROVISIONAL_SMA200_RECLAIM"
            ),
            value={
                "accepted_upper": True,
                "provisional_sma200_reclaim": True,
                "closed_daily_sma200_reclaim": closed_daily_sma,
            },
        )
    elif rejected_lower is True:
        price_check = _check(
            "PRICE_ACCEPTANCE_AND_SMA200",
            "ADVERSE",
            "LOWER_RESEARCH_CORRIDOR_REJECTED",
        )
    elif accepted_lower is True:
        price_check = _check(
            "PRICE_ACCEPTANCE_AND_SMA200",
            "DEVELOPING",
            "LOWER_RESEARCH_CORRIDOR_ACCEPTED_BUT_UPPER_ACCEPTANCE_PENDING",
        )
    else:
        price_check = _check(
            "PRICE_ACCEPTANCE_AND_SMA200",
            "PENDING",
            "PRICE_ACCEPTANCE_NOT_DECISIVE",
        )

    if entry.get("state") == "BLOCKED":
        mechanism_check = _check(
            "BREAKOUT_DRIVER_QUALITY",
            "BLOCKED",
            "BTC_ENTRY_GATE_BLOCKED",
        )
    elif mechanism.get("constructive") is True:
        mechanism_check = _check(
            "BREAKOUT_DRIVER_QUALITY",
            "SUPPORTIVE",
            "SPOT_ABSORPTION_AND_LEVERAGE_QUALITY_CONSTRUCTIVE",
            value={
                "spot_demand_absorption": mechanism.get("spot_demand_absorption"),
                "spot_demand_persistence": mechanism.get("spot_demand_persistence"),
                "leverage_quality": mechanism.get("leverage_quality"),
                "long_fomo_rebuild": mechanism.get("long_fomo_rebuild"),
            },
        )
    elif mechanism.get("adverse") is True:
        mechanism_check = _check(
            "BREAKOUT_DRIVER_QUALITY",
            "ADVERSE",
            "SPOT_OR_LEVERAGE_MECHANISM_ADVERSE",
        )
    else:
        mechanism_check = _check(
            "BREAKOUT_DRIVER_QUALITY",
            "PENDING",
            "BREAKOUT_DRIVER_MECHANISM_NOT_DECISIVE",
        )

    etp_check = _l3_etp_flow(layers)

    volume_check = _l6_breakout_volume_quality(layers)

    current_price = quantitative.get("current_price_usd")
    price_only_above_83k = (
        isinstance(current_price, (int, float))
        and float(current_price) >= 83000.0
    )

    time_price_check = _check(
        "TIME_PRICE_OVERBALANCE",
        "PENDING",
        (
            "PRICE_ONLY_OBSERVED_BEFORE_FULL_TIME_STRUCTURE_VALIDATION"
            if price_only_above_83k
            else "TIME_PRICE_OVERBALANCE_REQUIRES_LATER_TIME_AND_SWING_STRUCTURE"
        ),
        value={
            "current_price_usd": current_price,
            "research_price_zone_usd": [82000.0, 83000.0],
            "research_time_window": ["2026-09-29", "2026-10-05"],
            "formal_threshold_authority": "NONE",
        },
    )

    higher_low_check = _check(
        "MACRO_HIGHER_LOW",
        "PENDING",
        "POST_BREAKOUT_PULLBACK_STRUCTURE_NOT_YET_AVAILABLE",
    )

    relative_strength_check = _check(
        "BTC_RELATIVE_STRENGTH",
        "PENDING",
        "BTC_GOLD_SP500_DOW_RELATIVE_SERIES_NOT_YET_IN_OVERLAY_INPUT",
    )

    checks = [
        price_check,
        mechanism_check,
        etp_check,
        volume_check,
        time_price_check,
        higher_low_check,
        relative_strength_check,
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "NON_WEIGHTED_EVIDENCE_OVERLAY",
        "state": state,
        "reason": reason,
        "generated_at_ms": int(generated_at_ms),
        "checks": checks,
        "supportive_checks": [
            row["check_id"]
            for row in checks
            if row["status"] == "SUPPORTIVE"
        ],
        "adverse_checks": [
            row["check_id"]
            for row in checks
            if row["status"] == "ADVERSE"
        ],
        "mixed_checks": [
            row["check_id"]
            for row in checks
            if row["status"] == "MIXED"
        ],
        "pending_checks": [
            row["check_id"]
            for row in checks
            if row["status"] in {"PENDING", "DEVELOPING"}
        ],
        "research_coordinates": {
            "price_zone_usd": [82000.0, 83000.0],
            "time_window": ["2026-09-29", "2026-10-05"],
            "meaning": "EVENT_SCOPED_TIME_PRICE_VALIDATION_COORDINATE",
            "formal_threshold_authority": "NONE",
        },
        "authority": {
            "formal_model_authority": "NONE",
            "formal_weight_authority": "NONE",
            "formal_threshold_authority": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        },
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
        "action_output": "NONE",
    }
