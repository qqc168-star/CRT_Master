from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from statistics import median
from typing import Any, Callable


DERIBIT_DVOL_ENDPOINT = (
    "https://www.deribit.com/api/v2/public/get_volatility_index_data"
)

SCHEMA_VERSION = "CRT_DVOL_REGIME_WATCH_V0.1"


class DvolRegimeError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise DvolRegimeError(f"{field} missing")
    number = float(value)
    if not math.isfinite(number):
        raise DvolRegimeError(f"{field} not finite")
    return number


def _http_json(url: str, *, timeout: float = 15.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CRT-Radar/DVOL-V0.1 research-only read-only",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _authority() -> dict[str, Any]:
    return {
        "formal_model_authority": "NONE",
        "formal_weight_authority": "NONE",
        "formal_threshold_authority": "NONE",
        "season_transition_authority": "NONE",
        "investment_threshold_authority": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }


def blocked_dvol_regime_watch(
    reason: str,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "NON_WEIGHTED_RESEARCH_OVERLAY",
        "state": "BLOCKED",
        "reason": reason,
        "direction": "UNKNOWN",
        "current_dvol": None,
        "change_1d_pct": None,
        "change_7d_pct": None,
        "dvol_30d_low": None,
        "rebound_from_30d_low_pct": None,
        "level_percentile_1y": None,
        "low_30d_percentile_1y": None,
        "hours_since_30d_low": None,
        "baseline_count": 0,
        "scale_normalization": None,
        "recommended_wake_operational_percentile": 95.0,
        "error": error,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": False,
        **_authority(),
    }


def fetch_dvol_candles(
    *,
    start_timestamp: int,
    end_timestamp: int,
    resolution: str,
    http_json: Callable[[str], Any] | None = None,
) -> list[Any]:
    getter = _http_json if http_json is None else http_json
    query = urllib.parse.urlencode(
        {
            "currency": "BTC",
            "start_timestamp": int(start_timestamp),
            "end_timestamp": int(end_timestamp),
            "resolution": resolution,
        }
    )
    payload = getter(f"{DERIBIT_DVOL_ENDPOINT}?{query}")

    if not isinstance(payload, dict):
        raise DvolRegimeError("Deribit payload is not an object")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise DvolRegimeError("Deribit result missing")
    data = result.get("data")
    if not isinstance(data, list):
        raise DvolRegimeError("Deribit result.data missing")
    return data


def _parse_candles(raw: list[Any]) -> list[tuple[int, float]]:
    rows: dict[int, float] = {}
    for item in raw:
        if not isinstance(item, list) or len(item) < 5:
            continue
        timestamp = int(_finite(item[0], "timestamp"))
        close = _finite(item[4], "close")
        if close <= 0:
            raise DvolRegimeError("DVOL close must be positive")
        rows[timestamp] = close

    parsed = sorted(rows.items())
    if not parsed:
        raise DvolRegimeError("No usable DVOL candles")
    return parsed


def _detect_scale(
    daily: list[tuple[int, float]],
    hourly: list[tuple[int, float]],
) -> tuple[float, str]:
    sample = [value for _, value in hourly[-48:]]
    if not sample:
        sample = [value for _, value in daily[-30:]]

    center = median(sample)

    if 2.0 <= center <= 300.0:
        return 1.0, "PERCENT_POINTS_X1"

    if 0.02 <= center < 2.0:
        return 100.0, "FRACTION_X100"

    raise DvolRegimeError(
        f"DVOL scale ambiguous; recent median={center}"
    )


def _pct_change(current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None
    return ((current / previous) - 1.0) * 100.0


def _percentile(value: float, baseline: list[float]) -> float:
    if not baseline:
        raise DvolRegimeError("DVOL percentile baseline missing")
    count = sum(1 for item in baseline if item <= value)
    return (count / len(baseline)) * 100.0


def _value_at_or_before(
    rows: list[tuple[int, float]],
    timestamp: int,
) -> float | None:
    candidates = [value for ts, value in rows if ts <= timestamp]
    if not candidates:
        return None
    return candidates[-1]


def evaluate_dvol_regime_watch(
    daily_candles: list[Any],
    hourly_candles: list[Any],
    *,
    now_ms: int | None = None,
    minimum_baseline_count: int = 180,
    extreme_percentile: float = 10.0,
    elevated_percentile: float = 20.0,
    expansion_rebound_pct: float = 15.0,
    expansion_activation_max_hours: float = 168.0,
) -> dict[str, Any]:
    """
    Research-only volatility-regime sensor.

    Absolute values such as DVOL 40 are deliberately not used as formal or
    operational gates. Classification uses DVOL's own historical distribution.

    The result can arm or wake analysis, but cannot infer direction, confirm a
    bull transition, alter the six-layer model, or authorize a trade.
    """

    if not (0.0 < extreme_percentile < elevated_percentile < 100.0):
        raise DvolRegimeError("research percentile ordering invalid")

    daily_raw = _parse_candles(daily_candles)
    hourly_raw = _parse_candles(hourly_candles)

    factor, scale_name = _detect_scale(daily_raw, hourly_raw)

    daily = [(ts, value * factor) for ts, value in daily_raw]
    hourly = [(ts, value * factor) for ts, value in hourly_raw]

    latest_ts, current = hourly[-1]
    evaluation_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)

    age_ms = evaluation_ms - latest_ts
    if age_ms < -2 * 60 * 60_000:
        raise DvolRegimeError("DVOL latest candle is materially future-dated")
    if age_ms > 6 * 60 * 60_000:
        raise DvolRegimeError(
            f"DVOL hourly data stale by {age_ms / 3_600_000:.2f}h"
        )

    current_day_ms = latest_ts - (latest_ts % 86_400_000)
    baseline = [
        value
        for ts, value in daily
        if ts < current_day_ms
    ][-365:]

    if len(baseline) < minimum_baseline_count:
        raise DvolRegimeError(
            f"insufficient DVOL daily baseline: {len(baseline)}"
        )

    cutoff_30d = latest_ts - 30 * 86_400_000
    recent_30d = [
        (ts, value)
        for ts, value in hourly
        if ts >= cutoff_30d
    ]
    if not recent_30d:
        raise DvolRegimeError("30d DVOL hourly history missing")

    low_ts, low_30d = min(recent_30d, key=lambda row: row[1])
    rebound_pct = ((current / low_30d) - 1.0) * 100.0
    hours_since_low = (latest_ts - low_ts) / 3_600_000.0

    previous_1d = _value_at_or_before(
        hourly,
        latest_ts - 24 * 60 * 60_000,
    )
    previous_7d = _value_at_or_before(
        hourly,
        latest_ts - 7 * 24 * 60 * 60_000,
    )

    change_1d = _pct_change(current, previous_1d)
    change_7d = _pct_change(current, previous_7d)

    level_percentile = _percentile(current, baseline)
    low_percentile = _percentile(low_30d, baseline)

    if (
        low_percentile <= extreme_percentile
        and rebound_pct >= expansion_rebound_pct
        and hours_since_low <= expansion_activation_max_hours
    ):
        state = "EXPANSION_ACTIVATED"
        reason = "EXTREME_COMPRESSION_FOLLOWED_BY_MATERIAL_DVOL_REEXPANSION"
    elif level_percentile <= extreme_percentile:
        state = "COMPRESSION_EXTREME"
        reason = "DVOL_LEVEL_IN_EXTREME_LOW_HISTORICAL_PERCENTILE"
    elif level_percentile <= elevated_percentile:
        state = "COMPRESSION_ELEVATED"
        reason = "DVOL_LEVEL_IN_ELEVATED_COMPRESSION_PERCENTILE"
    else:
        state = "NORMAL"
        reason = "DVOL_LEVEL_WITHIN_NON_EXTREME_HISTORICAL_RANGE"

    recommended_wake_percentile = (
        90.0
        if state in {"COMPRESSION_EXTREME", "EXPANSION_ACTIVATED"}
        else 95.0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "NON_WEIGHTED_RESEARCH_OVERLAY",
        "state": state,
        "reason": reason,
        "direction": "UNKNOWN",
        "as_of_ms": latest_ts,
        "current_dvol": current,
        "change_1d_pct": change_1d,
        "change_7d_pct": change_7d,
        "dvol_30d_low": low_30d,
        "dvol_30d_low_as_of_ms": low_ts,
        "rebound_from_30d_low_pct": rebound_pct,
        "hours_since_30d_low": hours_since_low,
        "level_percentile_1y": level_percentile,
        "low_30d_percentile_1y": low_percentile,
        "baseline_count": len(baseline),
        "scale_normalization": scale_name,
        "recommended_wake_operational_percentile": (
            recommended_wake_percentile
        ),
        "research_parameters": {
            "minimum_baseline_count": minimum_baseline_count,
            "extreme_percentile": extreme_percentile,
            "elevated_percentile": elevated_percentile,
            "expansion_rebound_pct": expansion_rebound_pct,
            "expansion_activation_max_hours": (
                expansion_activation_max_hours
            ),
            "absolute_dvol_40_is_formal_threshold": False,
            "parameter_authority": "RESEARCH_OPERATIONAL_ONLY",
        },
        "provenance": {
            "provider": "Deribit",
            "metric": "BTC DVOL",
            "endpoint": DERIBIT_DVOL_ENDPOINT,
            "claim_precision": "DIRECTIONAL_RESEARCH",
            "source_scope": "DERIBIT_BTC_OPTIONS_IMPLIED_VOLATILITY",
        },
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
        **_authority(),
    }


def run_live_dvol_regime_watch(
    *,
    now_ms: int | None = None,
    http_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    evaluation_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)

    try:
        daily = fetch_dvol_candles(
            start_timestamp=evaluation_ms - 400 * 86_400_000,
            end_timestamp=evaluation_ms,
            resolution="1D",
            http_json=http_json,
        )
        hourly = fetch_dvol_candles(
            start_timestamp=evaluation_ms - 35 * 86_400_000,
            end_timestamp=evaluation_ms,
            resolution="3600",
            http_json=http_json,
        )
        return evaluate_dvol_regime_watch(
            daily,
            hourly,
            now_ms=evaluation_ms,
        )
    except Exception as exc:
        return blocked_dvol_regime_watch(
            "DVOL_INPUT_OR_EVALUATION_FAILED",
            error=f"{type(exc).__name__}:{exc}",
        )
