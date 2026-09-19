from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


STRUCTURE_SCHEMA_VERSION = "CRT_BTC_TRANSITION_STRUCTURE_MEASUREMENTS_V0.1"
FIFTY_WMA_SCHEMA_VERSION = "CRT_BTC_50WMA_LONG_HORIZON_CONTEXT_V0.1"
SNAPSHOT_SCHEMA_VERSION = "CRT_BTC_TRANSITION_REPLAY_SNAPSHOT_V0.1"

ANALYST_CLASSIFICATION_FIELDS = (
    "meaningful_breakout",
    "meaningful_pullback",
    "higher_low",
    "reattack",
    "prior_control_high_break",
)


class TransitionReplayEvidenceError(ValueError):
    """Raised internally when deterministic replay inputs fail closed."""


def _authority_envelope() -> dict[str, Any]:
    return {
        "formal_season": None,
        "formal_model_authority": "NONE",
        "formal_weight_authority": "NONE",
        "formal_threshold_authority": "NONE",
        "season_transition_authority": "NONE",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_determine_btc_season": False,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
    }


def _parse_timestamp(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise TransitionReplayEvidenceError(
                f"INVALID_TIMESTAMP:{field}"
            ) from exc
    else:
        raise TransitionReplayEvidenceError(f"INVALID_TIMESTAMP:{field}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TransitionReplayEvidenceError(f"TIMESTAMP_TIMEZONE_REQUIRED:{field}")
    return parsed.astimezone(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise TransitionReplayEvidenceError(f"INVALID_POSITIVE_NUMBER:{field}")
    return float(value)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransitionReplayEvidenceError(f"INVALID_TEXT:{field}")
    return value.strip()


def _blocked(schema_version: str, reason: str, *, as_of: object) -> dict[str, Any]:
    try:
        parsed_as_of = _iso_z(_parse_timestamp(as_of, "as_of"))
    except TransitionReplayEvidenceError:
        parsed_as_of = None
    return {
        "schema_version": schema_version,
        "state": "BLOCKED",
        "reason": reason,
        "as_of": parsed_as_of,
        **_authority_envelope(),
    }


def _visible_structure_bars(
    bars: object,
    *,
    as_of: datetime,
) -> list[dict[str, Any]]:
    if not isinstance(bars, list):
        raise TransitionReplayEvidenceError("STRUCTURE_BARS_NOT_ARRAY")

    visible: list[tuple[datetime, object]] = []
    for index, raw in enumerate(bars):
        if not isinstance(raw, dict):
            raise TransitionReplayEvidenceError(f"STRUCTURE_BAR_NOT_OBJECT:{index}")
        available_at = _parse_timestamp(
            raw.get("available_at"), f"bars[{index}].available_at"
        )
        if available_at <= as_of:
            visible.append((available_at, raw))

    normalized: list[dict[str, Any]] = []
    previous: datetime | None = None
    for visible_index, (available_at, raw) in enumerate(visible):
        if previous is not None and available_at <= previous:
            reason = (
                "DUPLICATE_STRUCTURE_BAR_TIME"
                if available_at == previous
                else "UNSORTED_STRUCTURE_BARS"
            )
            raise TransitionReplayEvidenceError(reason)
        previous = available_at

        open_price = _positive_number(raw.get("open"), f"visible[{visible_index}].open")
        high = _positive_number(raw.get("high"), f"visible[{visible_index}].high")
        low = _positive_number(raw.get("low"), f"visible[{visible_index}].low")
        close = _positive_number(raw.get("close"), f"visible[{visible_index}].close")
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            raise TransitionReplayEvidenceError(
                f"INVALID_OHLC_RANGE:visible[{visible_index}]"
            )
        normalized.append(
            {
                "available_at_dt": available_at,
                "available_at": _iso_z(available_at),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            }
        )
    return normalized


def _first_timestamp(
    bars: list[dict[str, Any]],
    predicate: Any,
) -> str | None:
    for bar in bars:
        if predicate(bar):
            return str(bar["available_at"])
    return None


def build_structure_measurements(
    bars: object,
    *,
    as_of: datetime | str,
    old_control_high: float,
    old_control_zone_lower: float,
    old_control_zone_upper: float,
    candidate_invalidation_anchor: float,
    references_frozen_at: datetime | str,
    reference_provenance: str,
    candidate_breakout_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Measure point-in-time price facts without classifying their meaning."""

    try:
        cutoff = _parse_timestamp(as_of, "as_of")
        frozen_at = _parse_timestamp(references_frozen_at, "references_frozen_at")
        if frozen_at > cutoff:
            raise TransitionReplayEvidenceError("REFERENCES_NOT_VISIBLE_AT_AS_OF")

        control_high = _positive_number(old_control_high, "old_control_high")
        zone_lower = _positive_number(
            old_control_zone_lower, "old_control_zone_lower"
        )
        zone_upper = _positive_number(
            old_control_zone_upper, "old_control_zone_upper"
        )
        if zone_lower > zone_upper:
            raise TransitionReplayEvidenceError("CONTROL_ZONE_BOUNDS_REVERSED")
        invalidation_anchor = _positive_number(
            candidate_invalidation_anchor, "candidate_invalidation_anchor"
        )
        provenance = _required_text(reference_provenance, "reference_provenance")
        visible = _visible_structure_bars(bars, as_of=cutoff)
        if not visible:
            raise TransitionReplayEvidenceError("NO_VISIBLE_STRUCTURE_BARS")

        candidate_at = (
            _parse_timestamp(candidate_breakout_at, "candidate_breakout_at")
            if candidate_breakout_at is not None
            else None
        )
        if candidate_at is not None and frozen_at > candidate_at:
            raise TransitionReplayEvidenceError(
                "REFERENCES_FROZEN_AFTER_CANDIDATE"
            )
        candidate_visible = candidate_at is not None and candidate_at <= cutoff
        post_candidate = (
            [bar for bar in visible if bar["available_at_dt"] >= candidate_at]
            if candidate_visible and candidate_at is not None
            else []
        )
        if candidate_visible and not post_candidate:
            raise TransitionReplayEvidenceError(
                "CANDIDATE_WINDOW_HAS_NO_VISIBLE_BARS"
            )
        after_candidate = (
            [bar for bar in visible if bar["available_at_dt"] > candidate_at]
            if candidate_visible and candidate_at is not None
            else []
        )

        first_zone_breach_at = _first_timestamp(
            post_candidate,
            lambda bar: bar["low"] < zone_lower,
        )
        breach_dt = (
            _parse_timestamp(first_zone_breach_at, "first_zone_breach_at")
            if first_zone_breach_at is not None
            else None
        )
        first_zone_reclaim_at = _first_timestamp(
            [
                bar
                for bar in post_candidate
                if breach_dt is not None and bar["available_at_dt"] > breach_dt
            ],
            lambda bar: bar["close"] >= zone_lower,
        )

        post_high_bar = (
            max(post_candidate, key=lambda bar: bar["high"])
            if post_candidate
            else None
        )
        post_low_bar = (
            min(post_candidate, key=lambda bar: bar["low"])
            if post_candidate
            else None
        )

        measurements = {
            "first_raw_cross_above_old_control_high_at": _first_timestamp(
                visible,
                lambda bar: bar["high"] > control_high,
            ),
            "first_close_above_old_control_high_at": _first_timestamp(
                visible,
                lambda bar: bar["close"] > control_high,
            ),
            "candidate_window_visible": candidate_visible,
            "first_return_into_old_control_zone_at": _first_timestamp(
                after_candidate,
                lambda bar: bar["low"] <= zone_upper and bar["high"] >= zone_lower,
            ),
            "first_raw_breach_below_old_control_zone_at": first_zone_breach_at,
            "first_close_reclaim_of_old_control_zone_at": first_zone_reclaim_at,
            "post_candidate_high": (
                post_high_bar["high"] if post_high_bar is not None else None
            ),
            "post_candidate_high_at": (
                post_high_bar["available_at"] if post_high_bar is not None else None
            ),
            "post_candidate_low": (
                post_low_bar["low"] if post_low_bar is not None else None
            ),
            "post_candidate_low_at": (
                post_low_bar["available_at"] if post_low_bar is not None else None
            ),
            "prior_control_high_raw_break": (
                any(bar["high"] > control_high for bar in post_candidate)
                if candidate_visible
                else None
            ),
            "prior_control_high_close_break": (
                any(bar["close"] > control_high for bar in post_candidate)
                if candidate_visible
                else None
            ),
            "candidate_invalidation_anchor_raw_breach": (
                any(bar["low"] < invalidation_anchor for bar in post_candidate)
                if candidate_visible
                else None
            ),
            "candidate_invalidation_anchor_raw_breach_at": _first_timestamp(
                post_candidate,
                lambda bar: bar["low"] < invalidation_anchor,
            ),
            "lower_low_vs_candidate_invalidation_anchor": (
                any(bar["low"] < invalidation_anchor for bar in post_candidate)
                if candidate_visible
                else None
            ),
        }
        return {
            "schema_version": STRUCTURE_SCHEMA_VERSION,
            "state": "READY_FOR_ANALYST",
            "reason": "POINT_IN_TIME_STRUCTURE_FACTS_MEASURED",
            "as_of": _iso_z(cutoff),
            "visible_bar_count": len(visible),
            "references": {
                "old_control_high": control_high,
                "old_control_zone_lower": zone_lower,
                "old_control_zone_upper": zone_upper,
                "candidate_invalidation_anchor": invalidation_anchor,
                "frozen_at": _iso_z(frozen_at),
                "provenance": provenance,
            },
            "candidate_breakout_at": (
                _iso_z(candidate_at) if candidate_at is not None else None
            ),
            "measurements": measurements,
            **_authority_envelope(),
        }
    except TransitionReplayEvidenceError as exc:
        return _blocked(STRUCTURE_SCHEMA_VERSION, str(exc), as_of=as_of)


def _visible_completed_weekly_bars(
    weekly_bars: object,
    *,
    as_of: datetime,
) -> list[dict[str, Any]]:
    if not isinstance(weekly_bars, list):
        raise TransitionReplayEvidenceError("WEEKLY_BARS_NOT_ARRAY")

    visible: list[tuple[datetime, datetime, object]] = []
    for index, raw in enumerate(weekly_bars):
        if not isinstance(raw, dict):
            raise TransitionReplayEvidenceError(f"WEEKLY_BAR_NOT_OBJECT:{index}")
        available_at = _parse_timestamp(
            raw.get("available_at"), f"weekly_bars[{index}].available_at"
        )
        if available_at > as_of:
            continue
        week_closed_at = _parse_timestamp(
            raw.get("week_closed_at"), f"weekly_bars[{index}].week_closed_at"
        )
        is_complete = raw.get("is_complete")
        if not isinstance(is_complete, bool):
            raise TransitionReplayEvidenceError(
                f"WEEKLY_BAR_COMPLETION_FLAG_INVALID:{index}"
            )
        if is_complete and week_closed_at > as_of:
            raise TransitionReplayEvidenceError(
                f"COMPLETED_WEEK_CLOSES_AFTER_AS_OF:{index}"
            )
        if is_complete and week_closed_at <= as_of:
            visible.append((week_closed_at, available_at, raw))

    normalized: list[dict[str, Any]] = []
    previous: datetime | None = None
    for visible_index, (week_closed_at, available_at, raw) in enumerate(visible):
        if previous is not None and week_closed_at <= previous:
            reason = (
                "DUPLICATE_COMPLETED_WEEK_TIME"
                if week_closed_at == previous
                else "UNSORTED_COMPLETED_WEEKLY_BARS"
            )
            raise TransitionReplayEvidenceError(reason)
        previous = week_closed_at
        if available_at < week_closed_at:
            raise TransitionReplayEvidenceError(
                f"COMPLETED_WEEK_AVAILABLE_BEFORE_CLOSE:{visible_index}"
            )
        normalized.append(
            {
                "week_closed_at": _iso_z(week_closed_at),
                "week_closed_at_dt": week_closed_at,
                "available_at": _iso_z(available_at),
                "close": _positive_number(
                    raw.get("close"), f"completed_week[{visible_index}].close"
                ),
            }
        )
    return normalized


def build_long_horizon_50wma_context(
    weekly_bars: object,
    *,
    as_of: datetime | str,
    provenance: str,
    current_price: float | None = None,
    current_price_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build completed-week 50WMA context without creating a regime vote."""

    try:
        cutoff = _parse_timestamp(as_of, "as_of")
        source = _required_text(provenance, "provenance")
        completed = _visible_completed_weekly_bars(weekly_bars, as_of=cutoff)
        if len(completed) < 50:
            result = _blocked(
                FIFTY_WMA_SCHEMA_VERSION,
                "INSUFFICIENT_COMPLETED_WEEKLY_BARS",
                as_of=as_of,
            )
            result.update(
                {
                    "completed_week_count": len(completed),
                    "required_completed_week_count": 50,
                    "provenance": source,
                    "blockers": ["FIFTY_COMPLETED_WEEKS_REQUIRED"],
                }
            )
            return result

        points: list[dict[str, Any]] = []
        for index in range(49, len(completed)):
            window = completed[index - 49 : index + 1]
            moving_average = sum(row["close"] for row in window) / 50.0
            row = completed[index]
            points.append(
                {
                    "week_closed_at": row["week_closed_at"],
                    "close": row["close"],
                    "wma_50": moving_average,
                    "close_above_50wma": row["close"] > moving_average,
                }
            )

        latest = points[-1]
        streak = 0
        for point in reversed(points):
            if not point["close_above_50wma"]:
                break
            streak += 1
        streak_left_censored = streak == len(points) and streak > 0

        if (current_price is None) != (current_price_at is None):
            raise TransitionReplayEvidenceError(
                "CURRENT_PRICE_AND_TIMESTAMP_MUST_BE_PAIRED"
            )
        current_context: dict[str, Any] | None = None
        if current_price is not None and current_price_at is not None:
            observed_at = _parse_timestamp(current_price_at, "current_price_at")
            if observed_at > cutoff:
                raise TransitionReplayEvidenceError(
                    "CURRENT_PRICE_NOT_VISIBLE_AT_AS_OF"
                )
            spot = _positive_number(current_price, "current_price")
            current_context = {
                "price": spot,
                "observed_at": _iso_z(observed_at),
                "distance_from_latest_completed_50wma_pct": (
                    (spot / latest["wma_50"]) - 1.0
                )
                * 100.0,
                "counts_as_completed_week": False,
            }

        return {
            "schema_version": FIFTY_WMA_SCHEMA_VERSION,
            "state": "READY_FOR_ANALYST",
            "reason": "COMPLETED_WEEK_50WMA_CONTEXT_READY",
            "as_of": _iso_z(cutoff),
            "provenance": source,
            "completed_week_count": len(completed),
            "latest_completed_weekly_close": latest["close"],
            "latest_completed_week_closed_at": latest["week_closed_at"],
            "latest_completed_50wma": latest["wma_50"],
            "calculation": "ARITHMETIC_MEAN_OF_50_COMPLETED_WEEKLY_CLOSES",
            "latest_completed_close_distance_from_50wma_pct": (
                (latest["close"] / latest["wma_50"]) - 1.0
            )
            * 100.0,
            "consecutive_completed_closes_above_50wma": streak,
            "streak_left_censored": streak_left_censored,
            "current_price_context": current_context,
            "research_hypothesis": {
                "source_rule": "TWO_CONSECUTIVE_COMPLETED_WEEKLY_CLOSES_ABOVE_50WMA",
                "role": "LONG_HORIZON_CONTEXT_ONLY",
                "formal_threshold_authority": "NONE",
            },
            "blockers": [],
            **_authority_envelope(),
        }
    except TransitionReplayEvidenceError as exc:
        return _blocked(FIFTY_WMA_SCHEMA_VERSION, str(exc), as_of=as_of)


def build_transition_replay_snapshot(
    *,
    structure_bars: object,
    weekly_bars: object,
    as_of: datetime | str,
    old_control_high: float,
    old_control_zone_lower: float,
    old_control_zone_upper: float,
    candidate_invalidation_anchor: float,
    references_frozen_at: datetime | str,
    reference_provenance: str,
    weekly_provenance: str,
    candidate_breakout_at: datetime | str | None = None,
    current_price: float | None = None,
    current_price_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Combine measured facts and slow-time context in one research snapshot."""

    structure = build_structure_measurements(
        structure_bars,
        as_of=as_of,
        old_control_high=old_control_high,
        old_control_zone_lower=old_control_zone_lower,
        old_control_zone_upper=old_control_zone_upper,
        candidate_invalidation_anchor=candidate_invalidation_anchor,
        references_frozen_at=references_frozen_at,
        reference_provenance=reference_provenance,
        candidate_breakout_at=candidate_breakout_at,
    )
    long_horizon = build_long_horizon_50wma_context(
        weekly_bars,
        as_of=as_of,
        provenance=weekly_provenance,
        current_price=current_price,
        current_price_at=current_price_at,
    )
    blocked_components = [
        name
        for name, value in (
            ("structure_measurements", structure),
            ("long_horizon_50wma_context", long_horizon),
        )
        if value.get("state") == "BLOCKED"
    ]
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "state": "BLOCKED" if blocked_components else "READY_FOR_ANALYST",
        "reason": (
            "REPLAY_COMPONENT_BLOCKED:" + ",".join(blocked_components)
            if blocked_components
            else "TRANSITION_REPLAY_FACTS_READY_FOR_ANALYST"
        ),
        "as_of": structure.get("as_of") or long_horizon.get("as_of"),
        "structure_measurements": structure,
        "long_horizon_50wma_context": long_horizon,
        "analyst_classifications": {
            field: None for field in ANALYST_CLASSIFICATION_FIELDS
        },
        "blocked_components": blocked_components,
        **_authority_envelope(),
    }
