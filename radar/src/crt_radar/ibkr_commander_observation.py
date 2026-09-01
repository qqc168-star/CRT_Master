"""Gate 6C-3 IBKR live observation bridge for one verified Commander Plan."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .commander_plan_adapter import CommanderPlanAdapter
from .ibkr_live_market_data_intake import ASSET_ORDER, LIVE_MARKET_DATA_TYPE


def _utc_from_ms(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("observed_at_ms must be a positive integer")
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _assert_live_market_data_types(market_data_types: object | None) -> None:
    if market_data_types is None:
        return
    if not isinstance(market_data_types, dict):
        raise ValueError("IBKR market data type proof must be an object")
    if list(market_data_types) != list(ASSET_ORDER):
        raise ValueError("IBKR market data type proof asset order mismatch")
    if any(
        market_data_types[asset] != LIVE_MARKET_DATA_TYPE
        for asset in ASSET_ORDER
    ):
        raise ValueError("IBKR observation market data is not fully live")


def _commander_event_id(event: dict[str, Any]) -> str:
    required = {
        "plan_id",
        "plan_sha",
        "asset",
        "line_id",
        "line_type",
        "level_price",
        "observed_price",
        "event_type",
        "timestamp",
    }
    missing = required - set(event)
    if missing:
        raise ValueError("commander event fields missing: " + ",".join(sorted(missing)))
    required_governance = {
        "action_output": "NONE",
        "machine_execution": "FORBIDDEN",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
        "price_reaching_is_not_action_trigger": True,
        "event_purpose": "WAKE_GPT_REANALYSIS_ONLY",
    }
    for key, expected in required_governance.items():
        if event.get(key) != expected:
            raise ValueError(f"commander event {key} must remain {expected!r}")
    canonical = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_commander_reanalysis_wake(
    event: dict[str, Any],
) -> dict[str, Any]:
    """Project one observation event into the existing reanalysis wake surface."""

    if not isinstance(event, dict):
        raise ValueError("commander event must be an object")
    event_id = _commander_event_id(event)
    reason = f"COMMANDER_LEVEL_OBSERVATION:{event_id}"
    return {
        "state": "REANALYSIS_REQUESTED",
        "reason": reason,
        "metric": "commander_level_event",
        "input_family": "COMMANDER_PLAN_OBSERVATION",
        "current_value": event["observed_price"],
        "previous_value": None,
        "percent_change": None,
        "historical_percentile": None,
        "baseline_count": 0,
        "wake_sources": ["COMMANDER_PLAN_OBSERVATION"],
        "wake_reasons": [reason],
        "analyst_reanalysis_requested": True,
        "commander_event_id": event_id,
        "commander_event": copy.deepcopy(event),
        "event_purpose": "WAKE_GPT_REANALYSIS_ONLY",
        "price_reaching_is_not_action_trigger": True,
        "action_output": "NONE",
        "machine_execution": "FORBIDDEN",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "capital_decision_authority": "USER_ONLY",
        "production": "NOT_APPROVED",
    }


class IbkrCommanderObservationBridge:
    """Route only plan-asset LAST and 5-second close observations to Gate 6A."""

    def __init__(self, adapter: CommanderPlanAdapter) -> None:
        if adapter.observation_mode != "IBKR_LIVE":
            raise ValueError("IBKR bridge requires an IBKR_LIVE adapter")
        self._adapter = adapter
        self.last_observation_count = 0
        self.bar_close_observation_count = 0
        self.ignored_asset_observation_count = 0

    @classmethod
    def arm(
        cls,
        plan: object,
        *,
        current_main_sha: str,
        now: datetime | None = None,
        gate6a_state: object | None = None,
    ) -> "IbkrCommanderObservationBridge":
        return cls(
            CommanderPlanAdapter.arm_live(
                plan,
                current_main_sha=current_main_sha,
                now=now,
                gate6a_state=gate6a_state,
            )
        )

    @property
    def asset(self) -> str:
        return self._adapter.asset

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return self._adapter.events

    def gate6a_state(self) -> dict[str, Any]:
        return self._adapter.gate6a_state()

    def latest_reanalysis_wake(self) -> dict[str, Any] | None:
        if not self.events:
            return None
        return build_commander_reanalysis_wake(self.events[-1])

    def on_ibkr_last(
        self,
        asset: str,
        price: float,
        observed_at_ms: int,
        *,
        market_data_types: dict[str, int | None] | None = None,
    ) -> None:
        _assert_live_market_data_types(market_data_types)
        if asset != self.asset:
            self.ignored_asset_observation_count += 1
            return
        self._adapter.on_live_last(price, _utc_from_ms(observed_at_ms))
        self.last_observation_count += 1

    def on_ibkr_5s_close(
        self,
        asset: str,
        close: float,
        observed_at_ms: int,
        *,
        market_data_types: dict[str, int | None] | None = None,
    ) -> None:
        _assert_live_market_data_types(market_data_types)
        if asset != self.asset:
            self.ignored_asset_observation_count += 1
            return
        self._adapter.on_live_5s_close(close, _utc_from_ms(observed_at_ms))
        self.bar_close_observation_count += 1

    def gate_summary(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "gate": "GATE_6C3",
                "state": "ARMED_OBSERVATION_ONLY",
                "asset": self.asset,
                "last_observation_count": self.last_observation_count,
                "bar_close_observation_count": self.bar_close_observation_count,
                "ignored_asset_observation_count": self.ignored_asset_observation_count,
                "observation_event_count": len(self.events),
                "reanalysis_wake_ready": bool(self.events),
                "event_purpose": "WAKE_GPT_REANALYSIS_ONLY",
                "price_reaching_is_not_action_trigger": True,
                "action_output": "NONE",
                "machine_execution": "FORBIDDEN",
                "external_action_authority": "NONE",
                "capital_decision_authority": "USER_ONLY",
                "production": "NOT_APPROVED",
            }
        )
