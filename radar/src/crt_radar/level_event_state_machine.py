"""The existing Gate 6A observation-only level event state machine.

This is the single reusable implementation promoted from the verified Gate 6A
offline harness.  Plan adapters provide line identity through the emit callback;
they do not implement another state machine.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import math
from typing import Any, Final


ALLOWED_DIRECTIONS: Final = frozenset({"UP", "DOWN"})
ALLOWED_STATES: Final = frozenset(
    {"FAR", "APPROACH", "CROSS_RAW", "ACCEPTED", "REJECTED"}
)
EVENT_TYPES: Final = frozenset(
    {"APPROACH", "CROSS_RAW", "ACCEPTED", "REJECTED", "RETEST", "REARMED"}
)
STATE_SCHEMA_VERSION: Final = "CRT_GATE6A_LEVEL_EVENT_STATE_V0.1"

EmitCallback = Callable[[str, float, str], None]


def _positive_price(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a positive number")
    return float(value)


class LevelEventEngine:
    """Gate 6A state machine for one directional observation line."""

    def __init__(
        self,
        *,
        level: float,
        direction: str,
        emit_callback: EmitCallback,
        approach_band_bps: float = 20,
        accept_required: int = 3,
        accept_window: int = 4,
    ) -> None:
        if direction not in ALLOWED_DIRECTIONS:
            raise ValueError(f"unsupported direction: {direction}")
        if not callable(emit_callback):
            raise TypeError("emit_callback must be callable")
        if (
            isinstance(approach_band_bps, bool)
            or not isinstance(approach_band_bps, (int, float))
            or not math.isfinite(approach_band_bps)
            or approach_band_bps < 0
        ):
            raise ValueError("approach_band_bps must be nonnegative")
        if (
            isinstance(accept_window, bool)
            or not isinstance(accept_window, int)
            or accept_window <= 0
        ):
            raise ValueError("accept_window must be a positive integer")
        if (
            isinstance(accept_required, bool)
            or not isinstance(accept_required, int)
            or accept_required <= 0
            or accept_required > accept_window
        ):
            raise ValueError("accept_required must be within accept_window")

        self.level = _positive_price(level, "level")
        self.direction = direction
        self.emit_callback = emit_callback
        self.band_bps = float(approach_band_bps)
        self.accept_required = accept_required
        self.accept_window = accept_window

        self.last_price: float | None = None
        self.state = "FAR"
        self.cross_active = False
        self.accepted = False
        self.accepted_departed = False
        self.retest_emitted = False
        self.closes: deque[float] = deque(maxlen=accept_window)

    def snapshot_state(self) -> dict[str, Any]:
        """Return the complete state of this existing Gate 6A engine."""

        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "level": self.level,
            "direction": self.direction,
            "approach_band_bps": self.band_bps,
            "accept_required": self.accept_required,
            "accept_window": self.accept_window,
            "last_price": self.last_price,
            "state": self.state,
            "cross_active": self.cross_active,
            "accepted": self.accepted,
            "accepted_departed": self.accepted_departed,
            "retest_emitted": self.retest_emitted,
            "closes": list(self.closes),
        }

    def restore_state(self, payload: object) -> None:
        """Fail closed before restoring a sealed Gate 6A checkpoint."""

        if not isinstance(payload, dict):
            raise ValueError("Gate 6A state must be an object")
        required = set(self.snapshot_state())
        if set(payload) != required:
            raise ValueError("Gate 6A state fields mismatch")
        if payload.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ValueError("Gate 6A state schema mismatch")

        identity = {
            "level": self.level,
            "direction": self.direction,
            "approach_band_bps": self.band_bps,
            "accept_required": self.accept_required,
            "accept_window": self.accept_window,
        }
        _positive_price(payload.get("level"), "checkpoint_level")
        checkpoint_band = payload.get("approach_band_bps")
        if (
            isinstance(checkpoint_band, bool)
            or not isinstance(checkpoint_band, (int, float))
            or not math.isfinite(checkpoint_band)
            or checkpoint_band < 0
        ):
            raise ValueError("Gate 6A approach band mismatch")
        if any(
            isinstance(payload.get(field), bool)
            or not isinstance(payload.get(field), int)
            or payload[field] <= 0
            for field in ("accept_required", "accept_window")
        ):
            raise ValueError("Gate 6A acceptance window mismatch")
        for key, expected in identity.items():
            if payload.get(key) != expected:
                raise ValueError(f"Gate 6A state identity mismatch:{key}")

        last_price = payload.get("last_price")
        if last_price is not None:
            last_price = _positive_price(last_price, "last_price")
        state = payload.get("state")
        if state not in ALLOWED_STATES:
            raise ValueError("Gate 6A state value mismatch")
        if last_price is None and state != "FAR":
            raise ValueError("Gate 6A state requires last price")

        bool_fields = (
            "cross_active",
            "accepted",
            "accepted_departed",
            "retest_emitted",
        )
        if any(type(payload.get(field)) is not bool for field in bool_fields):
            raise ValueError("Gate 6A state boolean mismatch")
        cross_active = payload["cross_active"]
        accepted = payload["accepted"]
        accepted_departed = payload["accepted_departed"]
        retest_emitted = payload["retest_emitted"]

        expected_flags = {
            "FAR": (False, False),
            "APPROACH": (False, False),
            "CROSS_RAW": (True, False),
            "ACCEPTED": (True, True),
            "REJECTED": (False, False),
        }
        if (cross_active, accepted) != expected_flags[state]:
            raise ValueError("Gate 6A state transition flags mismatch")
        if accepted_departed and not accepted:
            raise ValueError("Gate 6A accepted departure mismatch")
        if retest_emitted and not accepted_departed:
            raise ValueError("Gate 6A retest state mismatch")

        closes = payload.get("closes")
        if not isinstance(closes, list) or len(closes) > self.accept_window:
            raise ValueError("Gate 6A close window mismatch")
        restored_closes = [
            _positive_price(close, "checkpoint_close") for close in closes
        ]
        if state == "CROSS_RAW" and len(restored_closes) >= self.accept_window:
            raise ValueError("Gate 6A unresolved close window mismatch")

        self.last_price = last_price
        self.state = state
        self.cross_active = cross_active
        self.accepted = accepted
        self.accepted_departed = accepted_departed
        self.retest_emitted = retest_emitted
        self.closes = deque(restored_closes, maxlen=self.accept_window)

    def beyond(self, price: float) -> bool:
        if self.direction == "UP":
            return price >= self.level
        return price <= self.level

    def pre_side(self, price: float) -> bool:
        if self.direction == "UP":
            return price < self.level
        return price > self.level

    def distance_bps(self, price: float) -> float:
        return abs(price - self.level) / self.level * 10_000.0

    def crossed(self, previous: float | None, current: float) -> bool:
        if previous is None:
            return False
        if self.direction == "UP":
            return previous < self.level <= current
        return previous > self.level >= current

    def emit(self, event_type: str, price: float, timestamp: str) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {event_type}")
        self.emit_callback(event_type, price, timestamp)

    def on_price(self, price: float, timestamp: str) -> None:
        """Consume a LAST price or a 5-second close."""

        price = _positive_price(price, "observed_price")
        distance = self.distance_bps(price)

        # Corrective delta retained from Gate 6B: an unresolved crossing cannot
        # open another CROSS_RAW cycle.
        if (
            self.crossed(self.last_price, price)
            and not self.cross_active
            and not self.accepted
        ):
            self.cross_active = True
            self.accepted = False
            self.accepted_departed = False
            self.retest_emitted = False
            self.closes.clear()
            self.state = "CROSS_RAW"
            self.emit("CROSS_RAW", price, timestamp)
        elif not self.cross_active:
            if self.pre_side(price) and distance <= self.band_bps and self.state == "FAR":
                self.state = "APPROACH"
                self.emit("APPROACH", price, timestamp)
            elif (
                self.state == "REJECTED"
                and self.pre_side(price)
                and distance > self.band_bps
            ):
                self.emit("REARMED", price, timestamp)
                self.state = "FAR"

        if self.accepted:
            if self.beyond(price) and distance > self.band_bps:
                self.accepted_departed = True
            elif (
                self.accepted_departed
                and self.beyond(price)
                and distance <= self.band_bps
                and not self.retest_emitted
            ):
                self.emit("RETEST", price, timestamp)
                self.retest_emitted = True

        self.last_price = price

    def on_5s_close(self, close: float, timestamp: str) -> None:
        """Use 5-second closes only for acceptance/rejection confirmation."""

        close = _positive_price(close, "close")
        if not self.cross_active or self.accepted:
            return

        self.closes.append(close)
        if len(self.closes) < self.accept_window:
            return

        accepted_count = sum(1 for price in self.closes if self.beyond(price))
        if accepted_count >= self.accept_required:
            self.accepted = True
            self.state = "ACCEPTED"
            self.emit("ACCEPTED", close, timestamp)
        else:
            self.cross_active = False
            self.accepted = False
            self.state = "REJECTED"
            self.emit("REJECTED", close, timestamp)
