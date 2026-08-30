"""Gate 6C verified Commander Plan to Gate 6A adapter.

The adapter verifies the full plan before arming any line, then delegates every
observation to the existing Gate 6A state machine.  Gate 6C-2 uses TEST_ONLY
observations; Gate 6C-3 adds a narrowly typed IBKR_LIVE observation mode.  The
adapter has no broker, order, position, account, or funds surface.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Final

from .level_event_state_machine import LevelEventEngine


ALLOWED_ASSETS: Final = frozenset({"MSTR", "ASST", "STRC", "SATA"})
ALLOWED_LINE_TYPES: Final = frozenset(
    {"ATTACK", "FIRST_DEFENSE", "INVALIDATION", "HARVEST"}
)
ALLOWED_DIRECTIONS: Final = frozenset({"UP", "DOWN"})
REQUIRED_TOP_FIELDS: Final = frozenset(
    {
        "plan_id",
        "plan_version",
        "plan_mode",
        "generated_at",
        "valid_until",
        "asset",
        "source_main_sha",
        "lines",
        "governance",
        "plan_sha",
    }
)
REQUIRED_LINE_FIELDS: Final = frozenset(
    {"line_id", "line_type", "price", "direction"}
)
REQUIRED_GOVERNANCE: Final = {
    "action_output": "NONE",
    "machine_execution": "FORBIDDEN",
    "external_action_authority": "NONE",
    "capital_decision_authority": "USER_ONLY",
}
TEST_ONLY: Final = "TEST_ONLY"
SIMULATION_ONLY: Final = "SIMULATION_ONLY"
IBKR_LIVE: Final = "IBKR_LIVE"
VERIFIED_COMMANDER_PLAN: Final = "VERIFIED_COMMANDER_PLAN"


class CommanderPlanBlocked(RuntimeError):
    """Raised before arming when the Commander Plan fails closed."""

    def __init__(self, blockers: list[str]) -> None:
        self.blockers = tuple(blockers)
        super().__init__(";".join(blockers))


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_not_string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp_missing_timezone")
    return parsed.astimezone(timezone.utc)


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp_missing_timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_plan_payload(plan: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(plan)
    payload.pop("plan_sha", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def calculate_plan_sha(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_plan_payload(plan)).hexdigest()


def seal_commander_plan(plan: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(plan)
    sealed["plan_sha"] = calculate_plan_sha(sealed)
    return sealed


def validate_commander_plan(
    plan: object,
    *,
    current_main_sha: str,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    """Apply the Gate 6C-1 seal and governance checks without arming lines."""

    blockers: list[str] = []
    if not isinstance(plan, dict):
        return False, ["PLAN_NOT_OBJECT"]

    missing = sorted(REQUIRED_TOP_FIELDS - set(plan))
    if missing:
        return False, ["MISSING_TOP_FIELDS:" + ",".join(missing)]

    if plan["plan_mode"] != "OBSERVATION_ONLY":
        blockers.append("PLAN_MODE_NOT_OBSERVATION_ONLY")
    if not isinstance(plan["asset"], str) or plan["asset"] not in ALLOWED_ASSETS:
        blockers.append(f"UNKNOWN_ASSET:{plan['asset']}")
    if plan["source_main_sha"] != current_main_sha:
        blockers.append("SOURCE_MAIN_SHA_MISMATCH")

    check_time = now or datetime.now(timezone.utc)
    if check_time.tzinfo is None:
        raise ValueError("now must include a timezone")
    check_time = check_time.astimezone(timezone.utc)
    try:
        generated_at = _parse_timestamp(plan["generated_at"])
        valid_until = _parse_timestamp(plan["valid_until"])
        if generated_at >= valid_until:
            blockers.append("INVALID_TIME_WINDOW")
        if valid_until <= check_time:
            blockers.append("PLAN_EXPIRED")
    except (TypeError, ValueError) as exc:
        blockers.append(f"INVALID_TIMESTAMP:{exc}")

    governance = plan["governance"]
    if not isinstance(governance, dict):
        blockers.append("GOVERNANCE_NOT_OBJECT")
    else:
        for key, expected in REQUIRED_GOVERNANCE.items():
            if governance.get(key) != expected:
                blockers.append(f"GOVERNANCE_LOCK_FAIL:{key}")
        unknown_governance = set(governance) - set(REQUIRED_GOVERNANCE)
        if unknown_governance:
            blockers.append(
                "GOVERNANCE_UNKNOWN_FIELDS:" + ",".join(sorted(unknown_governance))
            )

    lines = plan["lines"]
    if not isinstance(lines, list):
        blockers.append("LINES_NOT_ARRAY")
    else:
        seen_ids: set[str] = set()
        seen_types: set[str] = set()
        for index, line in enumerate(lines):
            prefix = f"LINE_{index}"
            if not isinstance(line, dict):
                blockers.append(f"{prefix}_NOT_OBJECT")
                continue
            missing_line = REQUIRED_LINE_FIELDS - set(line)
            if missing_line:
                blockers.append(f"{prefix}_MISSING:" + ",".join(sorted(missing_line)))
                continue

            line_id = line["line_id"]
            line_type = line["line_type"]
            direction = line["direction"]
            price = line["price"]
            if not isinstance(line_id, str) or not line_id.strip():
                blockers.append(f"INVALID_LINE_ID:{index}")
            elif line_id in seen_ids:
                blockers.append(f"DUPLICATE_LINE_ID:{line_id}")
            else:
                seen_ids.add(line_id)

            if not isinstance(line_type, str) or line_type not in ALLOWED_LINE_TYPES:
                blockers.append(f"ILLEGAL_LINE_TYPE:{line_type}")
            elif line_type in seen_types:
                blockers.append(f"DUPLICATE_LINE_TYPE:{line_type}")
            else:
                seen_types.add(line_type)

            if not isinstance(direction, str) or direction not in ALLOWED_DIRECTIONS:
                blockers.append(f"ILLEGAL_DIRECTION:{direction}")
            if (
                isinstance(price, bool)
                or not isinstance(price, (int, float))
                or not math.isfinite(price)
                or price <= 0
            ):
                blockers.append(f"INVALID_PRICE:{line_id}")

        missing_types = ALLOWED_LINE_TYPES - seen_types
        if missing_types:
            blockers.append("MISSING_LINE_TYPES:" + ",".join(sorted(missing_types)))

    try:
        expected_sha = calculate_plan_sha(plan)
    except (TypeError, ValueError) as exc:
        blockers.append(f"PLAN_CANONICALIZATION_FAILED:{exc}")
    else:
        if plan["plan_sha"] != expected_sha:
            blockers.append("PLAN_SHA_MISMATCH")

    return not blockers, blockers


class CommanderPlanAdapter:
    """Thin metadata adapter from a verified plan to the one Gate 6A engine."""

    def __init__(
        self,
        plan: object,
        *,
        current_main_sha: str,
        now: datetime | None = None,
        observation_mode: str = TEST_ONLY,
    ) -> None:
        valid, blockers = validate_commander_plan(
            plan,
            current_main_sha=current_main_sha,
            now=now,
        )
        if not valid:
            raise CommanderPlanBlocked(blockers)
        assert isinstance(plan, dict)
        if observation_mode not in {TEST_ONLY, IBKR_LIVE}:
            raise ValueError(f"unsupported observation_mode: {observation_mode}")
        if observation_mode == TEST_ONLY:
            offline_blockers: list[str] = []
            if plan.get("price_classification") != TEST_ONLY:
                offline_blockers.append("OFFLINE_PLAN_NOT_TEST_ONLY")
            for line in plan["lines"]:
                if line.get("price_classification") != TEST_ONLY:
                    offline_blockers.append(
                        f"OFFLINE_LINE_NOT_TEST_ONLY:{line['line_id']}"
                    )
            if offline_blockers:
                raise CommanderPlanBlocked(offline_blockers)
        self._plan = copy.deepcopy(plan)
        self._observation_mode = observation_mode
        self._current_observation_channel: str | None = None
        self._events: list[dict[str, Any]] = []
        self._engines: list[LevelEventEngine] = []
        for line in self._plan["lines"]:
            self._engines.append(
                LevelEventEngine(
                    level=line["price"],
                    direction=line["direction"],
                    emit_callback=self._emitter_for(line),
                )
            )

    @classmethod
    def arm_offline(
        cls,
        plan: object,
        *,
        current_main_sha: str,
        now: datetime | None = None,
    ) -> "CommanderPlanAdapter":
        return cls(
            plan,
            current_main_sha=current_main_sha,
            now=now,
            observation_mode=TEST_ONLY,
        )

    @classmethod
    def arm_live(
        cls,
        plan: object,
        *,
        current_main_sha: str,
        now: datetime | None = None,
    ) -> "CommanderPlanAdapter":
        return cls(
            plan,
            current_main_sha=current_main_sha,
            now=now,
            observation_mode=IBKR_LIVE,
        )

    @property
    def armed_line_count(self) -> int:
        return len(self._engines)

    @property
    def armed_line_ids(self) -> tuple[str, ...]:
        return tuple(line["line_id"] for line in self._plan["lines"])

    @property
    def asset(self) -> str:
        return self._plan["asset"]

    @property
    def observation_mode(self) -> str:
        return self._observation_mode

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._events))

    def _emitter_for(self, line: dict[str, Any]):
        def emit(event_type: str, observed_price: float, timestamp: str) -> None:
            level_classification = line.get(
                "price_classification",
                self._plan.get("price_classification", VERIFIED_COMMANDER_PLAN),
            )
            if TEST_ONLY in {level_classification, self._observation_mode}:
                combined_classification = TEST_ONLY
            elif level_classification == SIMULATION_ONLY:
                combined_classification = "SEALED_SIMULATION_X_IBKR_LIVE"
            else:
                combined_classification = "VERIFIED_PLAN_X_IBKR_LIVE"
            self._events.append(
                {
                    "plan_id": self._plan["plan_id"],
                    "plan_sha": self._plan["plan_sha"],
                    "asset": self._plan["asset"],
                    "line_id": line["line_id"],
                    "line_type": line["line_type"],
                    "level_price": float(line["price"]),
                    "observed_price": float(observed_price),
                    "event_type": event_type,
                    "timestamp": timestamp,
                    "observation_channel": self._current_observation_channel,
                    "event_purpose": "WAKE_GPT_REANALYSIS_ONLY",
                    "price_classification": combined_classification,
                    "level_price_classification": level_classification,
                    "observed_price_classification": self._observation_mode,
                    "engineering_parameters": TEST_ONLY,
                    "price_reaching_is_not_action_trigger": True,
                    "action_output": "NONE",
                    "machine_execution": "FORBIDDEN",
                    "external_action_authority": "NONE",
                    "capital_decision_authority": "USER_ONLY",
                    "production": "NOT_APPROVED",
                }
            )

        return emit

    def _observation(
        self,
        price: float,
        timestamp: datetime | str,
        observation_mode: str,
    ) -> tuple[float, str]:
        if observation_mode != self._observation_mode:
            raise ValueError(
                f"ADAPTER_MODE_MISMATCH:{self._observation_mode}:{observation_mode}"
            )
        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(price)
            or price <= 0
        ):
            raise ValueError("observed_price must be a positive number")
        parsed = _parse_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
        return float(price), _iso_z(parsed)

    def _dispatch_to_engines(
        self,
        *,
        channel: str,
        price: float,
        observed_at: str,
        confirm_5s_close: bool,
    ) -> None:
        self._current_observation_channel = channel
        try:
            for engine in self._engines:
                engine.on_price(price, observed_at)
                if confirm_5s_close:
                    engine.on_5s_close(price, observed_at)
        finally:
            self._current_observation_channel = None

    def on_test_last(
        self,
        price: float,
        timestamp: datetime | str,
        *,
        price_classification: str,
    ) -> None:
        """Feed a TEST_ONLY LAST observation; BID/ASK have no adapter surface."""

        if price_classification != TEST_ONLY:
            raise ValueError("GATE_6C2_OFFLINE_REQUIRES_TEST_ONLY")
        price, observed_at = self._observation(
            price, timestamp, price_classification
        )
        self._dispatch_to_engines(
            channel="TEST_LAST",
            price=price,
            observed_at=observed_at,
            confirm_5s_close=False,
        )

    def on_test_5s_close(
        self,
        close: float,
        timestamp: datetime | str,
        *,
        price_classification: str,
    ) -> None:
        """Feed a TEST_ONLY 5-second close for crossing and confirmation."""

        if price_classification != TEST_ONLY:
            raise ValueError("GATE_6C2_OFFLINE_REQUIRES_TEST_ONLY")
        close, observed_at = self._observation(
            close, timestamp, price_classification
        )
        self._dispatch_to_engines(
            channel="TEST_5S_CLOSE",
            price=close,
            observed_at=observed_at,
            confirm_5s_close=True,
        )

    def on_live_last(self, price: float, timestamp: datetime | str) -> None:
        """Feed a timestamped IBKR LAST observation."""

        price, observed_at = self._observation(price, timestamp, IBKR_LIVE)
        self._dispatch_to_engines(
            channel="IBKR_LAST",
            price=price,
            observed_at=observed_at,
            confirm_5s_close=False,
        )

    def on_live_5s_close(self, close: float, timestamp: datetime | str) -> None:
        """Feed a timestamped IBKR 5-second close."""

        close, observed_at = self._observation(close, timestamp, IBKR_LIVE)
        self._dispatch_to_engines(
            channel="IBKR_5S_CLOSE",
            price=close,
            observed_at=observed_at,
            confirm_5s_close=True,
        )
