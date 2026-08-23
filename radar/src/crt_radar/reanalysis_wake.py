from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from .observation_store import Observation


@dataclass(frozen=True)
class ReanalysisWakeDecision:
    state: str
    reason: str
    metric: str | None
    input_family: str | None
    current_value: float | None
    previous_value: float | None
    percent_change: float | None
    historical_percentile: float | None
    baseline_count: int

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "metric": self.metric,
            "input_family": self.input_family,
            "current_value": self.current_value,
            "previous_value": self.previous_value,
            "percent_change": self.percent_change,
            "historical_percentile": self.historical_percentile,
            "baseline_count": self.baseline_count,
            "action_output": "NONE",
            "analyst_reanalysis_requested": self.state == "REANALYSIS_REQUESTED",
        }


def _percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def _percentile(value: float, values: list[float]) -> float | None:
    if not values:
        return None
    count = sum(1 for item in values if item <= value)
    return (count / len(values)) * 100.0


def evaluate_intraday_reanalysis_wake(
    current: Observation,
    history: Iterable[Observation],
    *,
    minimum_baseline_count: int = 8,
    operational_percentile: float = 95.0,
) -> ReanalysisWakeDecision:
    """
    Read-only operational wake-up logic.

    operational_percentile is an operational sensitivity setting,
    not an investment threshold, formal CRT score, or trading signal.
    """

    series = [
        row
        for row in history
        if row.input_family == current.input_family
        and row.metric == current.metric
        and row.as_of_ms < current.as_of_ms
    ]
    series.sort(key=lambda row: row.as_of_ms)

    if not series:
        return ReanalysisWakeDecision(
            state="NO_WAKE",
            reason="NO_PRIOR_OBSERVATION",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=None,
            percent_change=None,
            historical_percentile=None,
            baseline_count=0,
        )

    previous = series[-1]

    historical_moves: list[float] = []
    for left, right in zip(series, series[1:]):
        delta = _percent_change(right.value_num, left.value_num)
        if delta is not None:
            historical_moves.append(abs(delta))

    current_change = _percent_change(current.value_num, previous.value_num)

    if current_change is None:
        return ReanalysisWakeDecision(
            state="NO_WAKE",
            reason="NON_COMPARABLE_PREVIOUS_VALUE",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=previous.value_num,
            percent_change=None,
            historical_percentile=None,
            baseline_count=len(historical_moves),
        )

    if len(historical_moves) < minimum_baseline_count:
        return ReanalysisWakeDecision(
            state="NO_WAKE",
            reason="INSUFFICIENT_INTRADAY_HISTORY",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=previous.value_num,
            percent_change=current_change,
            historical_percentile=None,
            baseline_count=len(historical_moves),
        )

    percentile = _percentile(abs(current_change), historical_moves)

    if percentile is not None and percentile >= operational_percentile:
        return ReanalysisWakeDecision(
            state="REANALYSIS_REQUESTED",
            reason="MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=previous.value_num,
            percent_change=current_change,
            historical_percentile=percentile,
            baseline_count=len(historical_moves),
        )

    return ReanalysisWakeDecision(
        state="NO_WAKE",
        reason="CHANGE_WITHIN_INTRADAY_HISTORY",
        metric=current.metric,
        input_family=current.input_family,
        current_value=current.value_num,
        previous_value=previous.value_num,
        percent_change=current_change,
        historical_percentile=percentile,
        baseline_count=len(historical_moves),
    )


def _assert_optional_authority(
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    expected = {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }

    for key, expected_value in expected.items():
        if key in payload and payload.get(key) != expected_value:
            raise ValueError(
                f"{label} {key} must remain {expected_value!r}"
            )


def fuse_reanalysis_wake(
    base_wake: dict[str, Any] | None,
    *,
    plan_drift: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Fuse read-only reanalysis sources into one wake surface."""

    if base_wake is not None and not isinstance(base_wake, dict):
        raise ValueError("base_wake must be an object or None")

    if plan_drift is not None and not isinstance(plan_drift, dict):
        raise ValueError("plan_drift must be an object or None")

    if isinstance(base_wake, dict):
        _assert_optional_authority(
            base_wake,
            label="base_wake",
        )

    if isinstance(plan_drift, dict):
        _assert_optional_authority(
            plan_drift,
            label="plan_drift",
        )

    plan_requested = bool(
        isinstance(plan_drift, dict)
        and plan_drift.get("reanalysis_required") is True
    )

    if base_wake is None and not plan_requested:
        return None

    if base_wake is None:
        result: dict[str, Any] = {
            "state": "NO_WAKE",
            "reason": "WAKE_NOT_EVALUATED",
            "metric": None,
            "input_family": None,
            "current_value": None,
            "previous_value": None,
            "percent_change": None,
            "historical_percentile": None,
            "baseline_count": 0,
        }
    else:
        result = deepcopy(base_wake)

    base_requested = (
        result.get("state") == "REANALYSIS_REQUESTED"
    )

    wake_sources: list[str] = []
    wake_reasons: list[str] = []

    if base_requested:
        base_reason = str(
            result.get(
                "reason",
                "BASE_REANALYSIS_REQUESTED",
            )
        )

        if base_reason == "DVOL_EXPANSION_ACTIVATED":
            base_source = "DVOL"
        elif result.get("input_family") == "BTC_SPOT_PRICE":
            base_source = "BTC_INTRADAY"
        else:
            base_source = "BASE_WAKE"

        wake_sources.append(base_source)
        wake_reasons.append(base_reason)

    if plan_requested:
        plan_reason = str(
            plan_drift.get(
                "reason",
                "ACTIVE_PLAN_CONDITION_VIOLATED",
            )
        )

        wake_sources.append("PLAN_DRIFT")
        wake_reasons.append(plan_reason)

        if not base_requested:
            result.update(
                {
                    "state": "REANALYSIS_REQUESTED",
                    "reason": plan_reason,
                    "metric": "plan_drift",
                    "input_family": "CAPITAL_PLAN",
                    "current_value": None,
                    "previous_value": None,
                    "percent_change": None,
                    "historical_percentile": None,
                    "baseline_count": 0,
                }
            )

    requested = (
        result.get("state") == "REANALYSIS_REQUESTED"
    )

    result["analyst_reanalysis_requested"] = requested
    result["wake_sources"] = wake_sources
    result["wake_reasons"] = wake_reasons

    result["plan_drift_state"] = (
        plan_drift.get("state")
        if isinstance(plan_drift, dict)
        else None
    )

    result["plan_drift_reanalysis_required"] = (
        plan_drift.get("reanalysis_required")
        if isinstance(plan_drift, dict)
        else None
    )

    result["action_output"] = "NONE"
    result["external_action_authority"] = "NONE"
    result["external_action_performed"] = False

    return result
