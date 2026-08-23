from __future__ import annotations

from typing import Any

from .observation_store import Observation, ObservationStore
from .reanalysis_wake import evaluate_intraday_reanalysis_wake


def run_intraday_reanalysis(
    store: ObservationStore,
    current: Observation,
    *,
    operational_percentile: float = 95.0,
) -> dict[str, Any]:
    """Evaluate one BTC spot observation against stored intraday history.

    This runner is deliberately read-only: it only calls ``series`` on the
    supplied store and delegates the decision to the existing wake evaluator.
    It emits a reanalysis request, never an investment or external action.
    """

    if current.input_family != "BTC_SPOT_PRICE":
        raise ValueError("intraday reanalysis requires BTC_SPOT_PRICE")
    if current.layer_id != "AS-L3":
        raise ValueError("intraday reanalysis requires AS-L3 observations")

    percentile = float(operational_percentile)
    if not (0.0 < percentile <= 100.0):
        raise ValueError("operational_percentile must be in (0, 100]")

    history = store.series(current.input_family, current.metric)
    decision = evaluate_intraday_reanalysis_wake(
        current,
        history,
        operational_percentile=percentile,
    )
    if decision.state not in {"NO_WAKE", "REANALYSIS_REQUESTED"}:
        raise RuntimeError(f"unexpected intraday reanalysis state: {decision.state}")

    payload = decision.to_dict()
    payload["operational_percentile"] = percentile
    payload.update(
        {
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
    )
    return payload
