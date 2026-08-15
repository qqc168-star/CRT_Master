from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

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
