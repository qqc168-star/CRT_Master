from __future__ import annotations

from bisect import bisect_right
from typing import Any

from .observation_store import (
    COMPARABLE_METRICS,
    Observation,
    ObservationRevisionConflict,
    ObservationStore,
)
from .oi_revision_policy import OiRevisionPolicyError, is_scoped_metric


HORIZONS_MS = {
    "1d": 86_400_000,
    "7d": 7 * 86_400_000,
    "30d": 30 * 86_400_000,
}


def history_tolerance_ms(horizon_ms: int) -> int:
    # Operational lookup tolerance, not an investment threshold.
    # It allows normal run-time jitter without looking forward in time.
    return max(6 * 3_600_000, int(horizon_ms * 0.10))


def _direction(current: float, previous: float) -> str:
    if current > previous:
        return "UP"
    if current < previous:
        return "DOWN"
    return "FLAT"


def _change(current: Observation, previous: Observation) -> dict[str, Any]:
    absolute = current.value_num - previous.value_num
    percent = None if previous.value_num == 0 else (absolute / abs(previous.value_num)) * 100.0
    result: dict[str, Any] = {
        "history_state": "AVAILABLE",
        "current_value": current.value_num,
        "previous_value": previous.value_num,
        "previous_as_of_ms": previous.as_of_ms,
        "absolute_change": absolute,
        "percent_change": percent,
        "direction": _direction(current.value_num, previous.value_num),
    }
    if current.input_family == "FUNDING_RATE" and current.metric == "funding_rate":
        result["delta_bps"] = absolute * 10_000.0
    return result


def _historical_magnitudes(series: list[Observation], horizon_ms: int) -> list[float]:
    if len(series) < 2:
        return []
    times = [o.as_of_ms for o in series]
    tolerance = history_tolerance_ms(horizon_ms)
    magnitudes: list[float] = []
    for idx, current in enumerate(series):
        target = current.as_of_ms - horizon_ms
        previous_idx = bisect_right(times, target, hi=idx) - 1
        if previous_idx < 0:
            continue
        previous = series[previous_idx]
        if target - previous.as_of_ms > tolerance:
            continue
        magnitudes.append(abs(current.value_num - previous.value_num))
    return magnitudes


def _latest_in_series_at_or_before(
    series: list[Observation],
    target_ms: int,
    *,
    max_gap_ms: int,
) -> Observation | None:
    times = [row.as_of_ms for row in series]
    index = bisect_right(times, int(target_ms)) - 1
    if index < 0:
        return None
    observation = series[index]
    if int(target_ms) - observation.as_of_ms > int(max_gap_ms):
        return None
    return observation


def _percentile(value: float, values: list[float]) -> float | None:
    if len(values) < 8:
        return None
    count = sum(1 for item in values if item <= value)
    return (count / len(values)) * 100.0


def _revision_blocked_horizons(state: str, reason: str) -> dict[str, Any]:
    return {
        label: {
            "history_state": state,
            "blocked_reason": reason,
        }
        for label in HORIZONS_MS
    }


def compute_changes(store: ObservationStore, current: list[Observation]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    by_key = {(o.input_family, o.metric): o for o in current}
    for key in sorted(COMPARABLE_METRICS):
        observation = by_key.get(key)
        if observation is None:
            continue
        metric_result: dict[str, Any] = {
            "input_family": observation.input_family,
            "layer_id": observation.layer_id,
            "as_of_ms": observation.as_of_ms,
            "current_value": observation.value_num,
            "horizons": {},
        }
        scoped = is_scoped_metric(observation.input_family, observation.metric)
        try:
            series = (
                store.point_in_time_series(
                    observation.input_family,
                    observation.metric,
                    visible_at_ms=observation.recorded_at_ms,
                )
                if scoped
                else store.series(observation.input_family, observation.metric)
            )
        except ObservationRevisionConflict as exc:
            blocked_state = str(exc).split(":", 1)[0]
            metric_result["horizons"] = _revision_blocked_horizons(
                blocked_state,
                str(exc),
            )
            result[observation.metric] = metric_result
            continue
        except OiRevisionPolicyError as exc:
            metric_result["horizons"] = _revision_blocked_horizons(
                "REVISION_POLICY_INVALID_BLOCKED",
                str(exc),
            )
            result[observation.metric] = metric_result
            continue
        for label, horizon_ms in HORIZONS_MS.items():
            target = observation.as_of_ms - horizon_ms
            tolerance = history_tolerance_ms(horizon_ms)
            previous = _latest_in_series_at_or_before(
                series,
                target,
                max_gap_ms=tolerance,
            )
            if previous is None:
                metric_result["horizons"][label] = {"history_state": "INSUFFICIENT_HISTORY"}
                continue
            change = _change(observation, previous)
            magnitudes = _historical_magnitudes(series, horizon_ms)
            change["magnitude_percentile"] = _percentile(abs(change["absolute_change"]), magnitudes)
            change["baseline_count"] = len(magnitudes)
            metric_result["horizons"][label] = change
        result[observation.metric] = metric_result
    return result


def distill_top_changes(changes: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for metric, metric_row in changes.items():
        for horizon, change in metric_row.get("horizons", {}).items():
            percentile = change.get("magnitude_percentile")
            if percentile is None:
                continue
            candidates.append(
                {
                    "metric": metric,
                    "input_family": metric_row.get("input_family"),
                    "horizon": horizon,
                    "direction": change.get("direction"),
                    "absolute_change": change.get("absolute_change"),
                    "percent_change": change.get("percent_change"),
                    "magnitude_percentile": percentile,
                    "baseline_count": change.get("baseline_count"),
                }
            )
    candidates.sort(key=lambda row: (-float(row["magnitude_percentile"]), str(row["metric"]), str(row["horizon"])))
    return candidates[: max(0, int(limit))]
