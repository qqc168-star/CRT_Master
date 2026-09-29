from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass, asdict
from fractions import Fraction
from datetime import datetime, timedelta, timezone
from typing import Any


STRUCTURE_SCHEMA_VERSION = "CRT_BTC_TRANSITION_STRUCTURE_MEASUREMENTS_V0.1"
FIFTY_WMA_SCHEMA_VERSION = "CRT_BTC_50WMA_LONG_HORIZON_CONTEXT_V0.1"
TWO_HUNDRED_WMA_SCHEMA_VERSION = "CRT_BTC_200WMA_LONG_HORIZON_CONTEXT_V0.1"
BTC_LONG_HORIZON_SCHEMA_VERSION = "CRT_BTC_LONG_HORIZON_CONTEXT_V0.1"
SNAPSHOT_SCHEMA_VERSION = "CRT_BTC_TRANSITION_REPLAY_SNAPSHOT_V0.1"
OVERBALANCE_SCHEMA_VERSION = "CRT_PRICE_TIME_OVERBALANCE_MEASUREMENT_V0.1"

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



def build_long_horizon_200wma_context(
    weekly_bars: object,
    *,
    as_of: datetime | str,
    provenance: str,
    current_price: float | None = None,
    current_price_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build completed-week 200WMA context without creating a regime vote."""

    try:
        cutoff = _parse_timestamp(as_of, "as_of")
        source = _required_text(provenance, "provenance")
        completed = _visible_completed_weekly_bars(
            weekly_bars,
            as_of=cutoff,
        )

        if len(completed) < 200:
            result = _blocked(
                TWO_HUNDRED_WMA_SCHEMA_VERSION,
                "INSUFFICIENT_COMPLETED_WEEKLY_BARS",
                as_of=as_of,
            )
            result.update(
                {
                    "completed_week_count": len(completed),
                    "required_completed_week_count": 200,
                    "provenance": source,
                    "blockers": [
                        "TWO_HUNDRED_COMPLETED_WEEKS_REQUIRED"
                    ],
                }
            )
            return result

        points: list[dict[str, Any]] = []

        for index in range(199, len(completed)):
            window = completed[index - 199 : index + 1]
            moving_average = (
                sum(row["close"] for row in window) / 200.0
            )
            row = completed[index]

            points.append(
                {
                    "week_closed_at": row["week_closed_at"],
                    "week_closed_at_dt": row["week_closed_at_dt"],
                    "close": row["close"],
                    "wma_200": moving_average,
                }
            )

        latest = points[-1]

        prior_target = (
            latest["week_closed_at_dt"]
            - timedelta(weeks=52)
        )

        prior = next(
            (
                point
                for point in points
                if point["week_closed_at_dt"] == prior_target
            ),
            None,
        )

        blockers: list[str] = []

        wma_200_growth_yoy_pct = None

        if prior is None:
            blockers.append(
                "EXACT_52_WEEK_200WMA_BASELINE_UNAVAILABLE"
            )
        else:
            wma_200_growth_yoy_pct = (
                (
                    latest["wma_200"]
                    / prior["wma_200"]
                )
                - 1.0
            ) * 100.0

        if (current_price is None) != (
            current_price_at is None
        ):
            raise TransitionReplayEvidenceError(
                "CURRENT_PRICE_AND_TIMESTAMP_MUST_BE_PAIRED"
            )

        current_context: dict[str, Any] | None = None

        if (
            current_price is not None
            and current_price_at is not None
        ):
            observed_at = _parse_timestamp(
                current_price_at,
                "current_price_at",
            )

            if observed_at > cutoff:
                raise TransitionReplayEvidenceError(
                    "CURRENT_PRICE_NOT_VISIBLE_AT_AS_OF"
                )

            spot = _positive_number(
                current_price,
                "current_price",
            )

            current_context = {
                "price": spot,
                "observed_at": _iso_z(observed_at),
                "distance_from_latest_completed_200wma_pct": (
                    (
                        spot
                        / latest["wma_200"]
                    )
                    - 1.0
                )
                * 100.0,
                "counts_as_completed_week": False,
            }

        return {
            "schema_version": (
                TWO_HUNDRED_WMA_SCHEMA_VERSION
            ),
            "state": "READY_FOR_ANALYST",
            "reason": (
                "COMPLETED_WEEK_200WMA_CONTEXT_READY"
            ),
            "as_of": _iso_z(cutoff),
            "provenance": source,
            "completed_week_count": len(completed),
            "latest_completed_weekly_close": (
                latest["close"]
            ),
            "latest_completed_week_closed_at": (
                latest["week_closed_at"]
            ),
            "latest_completed_200wma": (
                latest["wma_200"]
            ),
            "calculation": (
                "ARITHMETIC_MEAN_OF_200_"
                "COMPLETED_WEEKLY_CLOSES"
            ),
            "latest_completed_close_distance_from_200wma_pct": (
                (
                    latest["close"]
                    / latest["wma_200"]
                )
                - 1.0
            )
            * 100.0,
            "wma_200_growth_yoy_pct": (
                wma_200_growth_yoy_pct
            ),
            "wma_200_yoy_basis": (
                {
                    "from_week_closed_at": (
                        prior["week_closed_at"]
                    ),
                    "to_week_closed_at": (
                        latest["week_closed_at"]
                    ),
                    "interpolation_used": False,
                }
                if prior is not None
                else None
            ),
            "current_price_context": current_context,
            "research_role": (
                "LONG_HORIZON_CONTEXT_ONLY"
            ),
            "formal_price_target_authority": "NONE",
            "blockers": blockers,
            **_authority_envelope(),
        }

    except TransitionReplayEvidenceError as exc:
        return _blocked(
            TWO_HUNDRED_WMA_SCHEMA_VERSION,
            str(exc),
            as_of=as_of,
        )


def build_cycle_drawdown_context(
    payload: object,
) -> dict[str, Any]:
    """Measure supplied cycle drawdowns without predicting the next cycle."""

    try:
        if not isinstance(payload, dict):
            raise TransitionReplayEvidenceError(
                "CYCLE_DRAWDOWN_CONTEXT_NOT_OBJECT"
            )

        historical = payload.get(
            "historical_cycles"
        )

        if (
            not isinstance(historical, list)
            or not historical
        ):
            raise TransitionReplayEvidenceError(
                "HISTORICAL_CYCLES_REQUIRED"
            )

        rows: list[dict[str, Any]] = []

        for index, raw in enumerate(historical):
            if not isinstance(raw, dict):
                raise TransitionReplayEvidenceError(
                    f"HISTORICAL_CYCLE_NOT_OBJECT:{index}"
                )

            cycle_id = _required_text(
                raw.get("cycle_id"),
                f"historical_cycles[{index}].cycle_id",
            )

            if raw.get("final") is not True:
                raise TransitionReplayEvidenceError(
                    f"HISTORICAL_CYCLE_NOT_FINAL:{index}"
                )

            peak = _positive_number(
                raw.get("peak_price_usd"),
                (
                    f"historical_cycles[{index}]"
                    ".peak_price_usd"
                ),
            )

            trough = _positive_number(
                raw.get("trough_price_usd"),
                (
                    f"historical_cycles[{index}]"
                    ".trough_price_usd"
                ),
            )

            if trough > peak:
                raise TransitionReplayEvidenceError(
                    f"CYCLE_TROUGH_EXCEEDS_PEAK:{index}"
                )

            rows.append(
                {
                    "cycle_id": cycle_id,
                    "peak_price_usd": peak,
                    "trough_price_usd": trough,
                    "max_drawdown_pct": (
                        (trough / peak) - 1.0
                    )
                    * 100.0,
                    "final": True,
                    "basis_ref": raw.get(
                        "basis_ref"
                    ),
                }
            )

        severity = [
            -row["max_drawdown_pct"]
            for row in rows
        ]

        monotonic_compression = (
            len(severity) >= 2
            and all(
                after < before
                for before, after in zip(
                    severity,
                    severity[1:],
                )
            )
        )

        current_result = None
        current = payload.get(
            "current_cycle"
        )

        if current is not None:
            if not isinstance(current, dict):
                raise TransitionReplayEvidenceError(
                    "CURRENT_CYCLE_NOT_OBJECT"
                )

            peak = _positive_number(
                current.get("peak_price_usd"),
                "current_cycle.peak_price_usd",
            )

            trough = _positive_number(
                current.get("trough_price_usd"),
                "current_cycle.trough_price_usd",
            )

            if trough > peak:
                raise TransitionReplayEvidenceError(
                    "CURRENT_CYCLE_TROUGH_EXCEEDS_PEAK"
                )

            final = current.get("final")

            if not isinstance(final, bool):
                raise TransitionReplayEvidenceError(
                    "CURRENT_CYCLE_FINAL_FLAG_REQUIRED"
                )

            current_result = {
                "cycle_id": _required_text(
                    current.get("cycle_id"),
                    "current_cycle.cycle_id",
                ),
                "peak_price_usd": peak,
                "trough_price_usd": trough,
                "current_cycle_max_drawdown_pct": (
                    (trough / peak) - 1.0
                )
                * 100.0,
                "current_cycle_drawdown_final": final,
                "basis_ref": current.get(
                    "basis_ref"
                ),
            }

        return {
            "state": "READY_FOR_ANALYST",
            "historical_cycles": rows,
            "historical_sample_count": len(rows),
            "drawdown_compression_observation": (
                "HISTORICAL_FINAL_DRAWDOWN_"
                "SEVERITY_DECREASED_SEQUENTIALLY"
                if monotonic_compression
                else
                "NO_MONOTONIC_HISTORICAL_"
                "COMPRESSION_CLAIM"
            ),
            "current_cycle": current_result,
            "next_cycle_drawdown_prediction": None,
            "research_hypothesis_only": True,
            "formal_threshold_authority": "NONE",
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "analyst_judgment_required": True,
        }

    except TransitionReplayEvidenceError as exc:
        return {
            "state": "BLOCKED",
            "reason": str(exc),
            "research_hypothesis_only": True,
            "formal_threshold_authority": "NONE",
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "analyst_judgment_required": True,
        }


def build_cycle_envelope_scenarios(
    scenarios: object,
) -> dict[str, Any]:
    """Perform scenario arithmetic only; never emit a formal BTC price target."""

    try:
        if (
            not isinstance(scenarios, list)
            or not scenarios
        ):
            raise TransitionReplayEvidenceError(
                "CYCLE_ENVELOPE_SCENARIOS_REQUIRED"
            )

        results: list[dict[str, Any]] = []

        for index, raw in enumerate(scenarios):
            if not isinstance(raw, dict):
                raise TransitionReplayEvidenceError(
                    (
                        "CYCLE_ENVELOPE_SCENARIO_"
                        f"NOT_OBJECT:{index}"
                    )
                )

            scenario_id = _required_text(
                raw.get("scenario_id"),
                (
                    f"cycle_envelope_scenarios"
                    f"[{index}].scenario_id"
                ),
            )

            floor = _positive_number(
                raw.get(
                    "future_bear_floor_usd"
                ),
                (
                    f"cycle_envelope_scenarios"
                    f"[{index}]"
                    ".future_bear_floor_usd"
                ),
            )

            drawdown = raw.get(
                "assumed_drawdown_pct"
            )

            if (
                isinstance(drawdown, bool)
                or not isinstance(
                    drawdown,
                    (int, float),
                )
                or not math.isfinite(
                    drawdown
                )
                or drawdown <= 0
                or drawdown >= 100
            ):
                raise TransitionReplayEvidenceError(
                    (
                        "INVALID_ASSUMED_"
                        f"DRAWDOWN_PCT:{index}"
                    )
                )

            drawdown = float(drawdown)

            implied_peak = (
                floor
                / (
                    1.0
                    - drawdown / 100.0
                )
            )

            results.append(
                {
                    "scenario_id": scenario_id,
                    "future_bear_floor_usd": (
                        floor
                    ),
                    "assumed_drawdown_pct": (
                        drawdown
                    ),
                    "implied_cycle_peak_usd": (
                        implied_peak
                    ),
                    "basis_ref": raw.get(
                        "basis_ref"
                    ),
                    "scenario_only": True,
                    "formal_price_target_authority": (
                        "NONE"
                    ),
                    "dependent_evidence_warning": (
                        True
                    ),
                }
            )

        return {
            "state": "READY_FOR_ANALYST",
            "scenarios": results,
            "scenario_only": True,
            "formal_price_target_authority": "NONE",
            "dependent_evidence_warning": (
                "FUTURE_BEAR_FLOOR_AND_"
                "IMPLIED_PEAK_ARE_NOT_"
                "INDEPENDENT_VOTES"
            ),
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "analyst_judgment_required": True,
        }

    except TransitionReplayEvidenceError as exc:
        return {
            "state": "BLOCKED",
            "reason": str(exc),
            "scenario_only": True,
            "formal_price_target_authority": "NONE",
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "analyst_judgment_required": True,
        }


def build_btc_long_horizon_context(
    inputs: object,
) -> dict[str, Any]:
    """Compose research-only BTC long-horizon context."""

    if not isinstance(inputs, dict):
        return {
            "schema_version": (
                BTC_LONG_HORIZON_SCHEMA_VERSION
            ),
            "state": "BLOCKED",
            "reason": (
                "BTC_LONG_HORIZON_INPUT_NOT_OBJECT"
            ),
            "formal_price_target_authority": "NONE",
            **_authority_envelope(),
        }

    wma = build_long_horizon_200wma_context(
        inputs.get("weekly_bars"),
        as_of=inputs.get("as_of"),
        provenance=inputs.get(
            "weekly_provenance"
        ),
        current_price=inputs.get(
            "current_price"
        ),
        current_price_at=inputs.get(
            "current_price_at"
        ),
    )

    drawdown = build_cycle_drawdown_context(
        inputs.get(
            "cycle_drawdown_context"
        )
    )

    envelope = build_cycle_envelope_scenarios(
        inputs.get(
            "cycle_envelope_scenarios"
        )
    )

    blocked_components = [
        name
        for name, value in (
            (
                "long_horizon_200wma_context",
                wma,
            ),
            (
                "cycle_drawdown_context",
                drawdown,
            ),
            (
                "cycle_envelope_scenarios",
                envelope,
            ),
        )
        if value.get("state") == "BLOCKED"
    ]

    return {
        "schema_version": (
            BTC_LONG_HORIZON_SCHEMA_VERSION
        ),
        "state": (
            "BLOCKED"
            if wma.get("state") == "BLOCKED"
            else "READY_FOR_ANALYST"
        ),
        "reason": (
            "BTC_200WMA_CONTEXT_BLOCKED"
            if wma.get("state") == "BLOCKED"
            else
            "BTC_LONG_HORIZON_RESEARCH_"
            "CONTEXT_READY"
        ),
        "as_of": wma.get("as_of"),
        "long_horizon_200wma_context": wma,
        "cycle_drawdown_context": drawdown,
        "cycle_envelope_scenarios": envelope,
        "blocked_components": blocked_components,
        "research_role": (
            "SUPPORTING_CONTEXT_ONLY"
        ),
        "formal_price_target_authority": "NONE",
        **_authority_envelope(),
    }


def build_forward_200wma_context(weekly_bars: object, *, as_of: str,
                                provenance: str, scenario: object) -> dict[str, Any]:
    """Roll the existing 200WMA calculation through a frozen hypothetical path.

    Projected bars are synthetic scenario inputs, never historical observations.
    The original completed-week loader and 200WMA calculator remain authoritative.
    """
    authority = {**_authority_envelope(), "research_state": "RESEARCH_ONLY",
                 "formal_price_target_authority": "NONE", "production": "NOT_APPROVED",
                 "capital_decision_authority": "USER_ONLY", "machine_execution": "FORBIDDEN"}
    try:
        cutoff = _parse_timestamp(as_of, "as_of")
        completed = _visible_completed_weekly_bars(weekly_bars, as_of=cutoff)
        if len(completed) < 200:
            raise TransitionReplayEvidenceError("TWO_HUNDRED_COMPLETED_WEEKS_REQUIRED")
        history = completed[-200:]
        if any(b["week_closed_at_dt"] - a["week_closed_at_dt"] != timedelta(weeks=1)
               for a, b in zip(history, history[1:])):
            raise TransitionReplayEvidenceError("CONSECUTIVE_COMPLETED_WEEKS_REQUIRED")
        if not isinstance(scenario, dict):
            raise TransitionReplayEvidenceError("LABELED_FUTURE_SCENARIO_REQUIRED")
        scenario_id = _required_text(scenario.get("scenario_id"), "scenario_id")
        source = _required_text(scenario.get("source_ref"), "scenario.source_ref")
        if _parse_timestamp(scenario.get("frozen_at"), "scenario.frozen_at") > cutoff:
            raise TransitionReplayEvidenceError("SCENARIO_NOT_AVAILABLE_AT_REPLAY_CUTOFF")
        points = scenario.get("weekly_path")
        if not isinstance(points, list) or not 1 <= len(points) <= 520:
            raise TransitionReplayEvidenceError("SCENARIO_REQUIRES_1_TO_520_WEEKLY_POINTS")
        synthetic = [{"week_closed_at": r["week_closed_at"], "available_at": r["available_at"],
                      "close": r["close"], "is_complete": True} for r in history]
        baseline = build_long_horizon_200wma_context(synthetic, as_of=as_of, provenance=provenance)
        if baseline["state"] == "BLOCKED":
            raise TransitionReplayEvidenceError(baseline["reason"])
        previous = history[-1]["week_closed_at_dt"]
        projected = []
        for point in points:
            if not isinstance(point, dict):
                raise TransitionReplayEvidenceError("SCENARIO_POINT_NOT_OBJECT")
            at = _parse_timestamp(point.get("week_closed_at"), "scenario.week_closed_at")
            if at <= cutoff or at - previous != timedelta(weeks=1):
                raise TransitionReplayEvidenceError("CONSECUTIVE_FUTURE_WEEKLY_SCENARIO_REQUIRED")
            price = _positive_number(point.get("close"), "scenario.close")
            synthetic.append({"week_closed_at": _iso_z(at), "available_at": _iso_z(at),
                              "close": price, "is_complete": True})
            virtual = build_long_horizon_200wma_context(synthetic[-200:], as_of=_iso_z(at),
                                                       provenance="SCENARIO:" + source)
            projected.append({"week_closed_at": _iso_z(at), "scenario_btc_close": price,
                              "scenario_200wma": virtual["latest_completed_200wma"]})
            previous = at
        return {"state": "AVAILABLE", "as_of": _iso_z(cutoff), "scenario_id": scenario_id,
                "source_ref": source, "historical_provenance": provenance,
                "frozen_at": scenario["frozen_at"], "baseline_200wma": baseline["latest_completed_200wma"],
                "path": projected, "scenario_only": True,
                "legacy_research_scenarios_usd": [120000, 135000, 150000],
                "limitation": "HYPOTHETICAL_PRICE_PATH_NOT_FORECAST_OR_INDEPENDENT_EVIDENCE",
                "invalidation": "REVISED_HISTORY_OR_CHANGED_SCENARIO_PATH", **authority}
    except (TransitionReplayEvidenceError, OverflowError) as exc:
        return {"state": "BLOCKED", "reason": str(exc), "path": [], **authority}


@dataclass(frozen=True)
class FrozenRallyReference:
    """Immutable supplied anchors, not a pivot detector or transition state."""

    reference_start_at: str
    reference_end_at: str
    reference_start_price: float
    reference_high_price: float
    reference_frozen_at: str
    reference_provenance: str
    candidate_start_at: str
    candidate_start_price: float


def _overbalance_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _completed_daily_measurement_bars(bars: object, *, as_of: datetime) -> list[dict[str, Any]]:
    """Add completion clocks to the existing OHLC validator without changing it."""
    if not isinstance(bars, list):
        raise TransitionReplayEvidenceError("DAILY_BARS_NOT_ARRAY")
    selected = []
    for raw in bars:
        if not isinstance(raw, dict):
            raise TransitionReplayEvidenceError("DAILY_BAR_NOT_OBJECT")
        available = _parse_timestamp(raw.get("available_at"), "daily.available_at")
        if available > as_of:
            continue
        if raw.get("is_complete") is False:
            continue
        if raw.get("is_complete") is not True:
            raise TransitionReplayEvidenceError("EXPLICIT_DAILY_COMPLETION_REQUIRED")
        closed = _parse_timestamp(raw.get("day_closed_at"), "daily.day_closed_at")
        if closed > available:
            raise TransitionReplayEvidenceError("DAILY_COMPLETION_FUTURE_LEAKAGE")
        selected.append((closed, raw))
    normalized = _visible_structure_bars([raw for _, raw in selected], as_of=as_of)
    result = []
    for (closed, _), row in zip(selected, normalized):
        if result and closed <= _parse_timestamp(result[-1]["day_closed_at"], "previous.daily"):
            raise TransitionReplayEvidenceError("DUPLICATE_OR_UNSORTED_DAILY_CLOSE")
        result.append({"day_closed_at": _iso_z(closed),
                       **{k: v for k, v in row.items() if k != "available_at_dt"}})
    return result


def build_price_time_overbalance_measurement(
    daily_bars: object, *, reference: FrozenRallyReference, as_of: datetime | str,
    previous_measurement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Count completed daily intervals (start, first highest-high occurrence].

    Equal highs retain their first occurrence. Previous snapshots are optional
    replay provenance checkpoints, never eligibility/state-machine transitions.
    """
    locks = {**_authority_envelope(), "capital_decision_authority": "USER_ONLY",
             "production": "NOT_APPROVED", "machine_execution": "FORBIDDEN",
             "research_state": "RESEARCH_ONLY"}
    try:
        cutoff = _parse_timestamp(as_of, "as_of")
        if not isinstance(reference, FrozenRallyReference):
            raise TransitionReplayEvidenceError("IMMUTABLE_FROZEN_REFERENCE_REQUIRED")
        rs, re, frozen, cs = [_parse_timestamp(getattr(reference, key), key) for key in (
            "reference_start_at", "reference_end_at", "reference_frozen_at", "candidate_start_at")]
        if not rs <= re <= frozen <= cs <= cutoff:
            raise TransitionReplayEvidenceError("REFERENCE_CANDIDATE_CLOCK_ORDER_INVALID")
        start_price = _positive_number(reference.reference_start_price, "reference_start_price")
        ref_high = _positive_number(reference.reference_high_price, "reference_high_price")
        candidate_price = _positive_number(reference.candidate_start_price, "candidate_start_price")
        _required_text(reference.reference_provenance, "reference_provenance")
        reference_return = Fraction(str(ref_high))/Fraction(str(start_price))-1
        ref_gain = float(reference_return*100)
        if not math.isfinite(ref_gain) or ref_gain <= 0:
            raise TransitionReplayEvidenceError("REFERENCE_GAIN_MUST_BE_POSITIVE_FINITE")
        visible = _completed_daily_measurement_bars(daily_bars, as_of=cutoff)
        def segment(start, end, availability):
            rows = [r for r in visible if start < _parse_timestamp(r["day_closed_at"], "day") <= end
                    and _parse_timestamp(r["available_at"], "available") <= availability]
            expected = start + timedelta(days=1)
            for row in rows:
                if _parse_timestamp(row["day_closed_at"], "day") != expected:
                    raise TransitionReplayEvidenceError("CONSECUTIVE_COMPLETED_DAILY_INTERVALS_REQUIRED")
                expected += timedelta(days=1)
            return rows
        reference_rows = segment(rs, re, frozen)
        if not reference_rows or _parse_timestamp(reference_rows[-1]["day_closed_at"], "end") != re:
            raise TransitionReplayEvidenceError("REFERENCE_DURATION_OR_FROZEN_COVERAGE_INVALID")
        measured_high = max(r["high"] for r in reference_rows)
        if measured_high != ref_high:
            raise TransitionReplayEvidenceError("FROZEN_REFERENCE_HIGH_NOT_SUPPORTED_BY_BARS")
        ref_index = next(i for i, r in enumerate(reference_rows) if r["high"] == measured_high)
        ref_duration = ref_index+1
        candidates = segment(cs, cutoff, cutoff)
        if not candidates:
            raise TransitionReplayEvidenceError("NO_VISIBLE_COMPLETED_CANDIDATE_DAYS")
        if _parse_timestamp(candidates[-1]["day_closed_at"], "last.daily") + timedelta(days=1) <= cutoff:
            raise TransitionReplayEvidenceError("COMPLETED_CANDIDATE_DAILY_COVERAGE_INCOMPLETE")
        material = {"anchors": asdict(reference), "reference_bars": reference_rows}
        reference_hash = _overbalance_hash(material)
        if previous_measurement is not None:
            previous = previous_measurement
            if (not isinstance(previous, dict) or previous.get("state") != "READY_FOR_ANALYST"
                    or previous.get("measurement_hash") != _overbalance_hash({k: v for k, v in previous.items()
                                                                              if k != "measurement_hash"})
                    or previous.get("reference_hash") != reference_hash):
                raise TransitionReplayEvidenceError("FROZEN_REFERENCE_OR_CHECKPOINT_CHANGED")
            previous_at = _parse_timestamp(previous.get("as_of"), "previous.as_of")
            if previous_at > cutoff:
                raise TransitionReplayEvidenceError("FUTURE_REPLAY_CHECKPOINT")
            prefix = [r for r in candidates if _parse_timestamp(r["available_at"], "available") <= previous_at]
            if prefix != previous.get("observed_candidate_bars"):
                raise TransitionReplayEvidenceError("PREVIOUSLY_VISIBLE_CANDIDATE_HISTORY_CHANGED")
        high = None
        duration = 0
        price_first = time_first = both_first = occurrence = None
        for index, row in enumerate(candidates):
            if high is None or row["high"] > high:
                high, duration, occurrence = row["high"], index+1, row["day_closed_at"]
            candidate_return = Fraction(str(high))/Fraction(str(candidate_price))-1
            gain = float(candidate_return*100)
            exact_price_ratio = candidate_return/reference_return
            price_ratio, time_ratio = float(exact_price_ratio), duration/ref_duration
            if not all(math.isfinite(v) for v in (gain, price_ratio, time_ratio)):
                raise TransitionReplayEvidenceError("NONFINITE_OVERBALANCE_MEASUREMENT")
            if exact_price_ratio > 1 and price_first is None:
                price_first = row["day_closed_at"]
            if duration > ref_duration and time_first is None:
                time_first = row["day_closed_at"]
            if exact_price_ratio > 1 and duration > ref_duration and both_first is None:
                both_first = row["day_closed_at"]
        result = {"schema_version": OVERBALANCE_SCHEMA_VERSION, "state": "READY_FOR_ANALYST",
            "as_of": _iso_z(cutoff), "reference": material, "reference_hash": reference_hash,
            "reference_gain_pct": ref_gain, "reference_duration_bars": ref_duration,
            "reference_high_at": reference_rows[ref_index]["day_closed_at"],
            "candidate_gain_pct": gain, "candidate_duration_bars": duration,
            "running_completed_daily_high": high, "running_high_first_at": occurrence,
            "price_overbalance_ratio": price_ratio, "time_overbalance_ratio": time_ratio,
            "price_overbalance_first_at": price_first, "time_overbalance_first_at": time_first,
            "prior_rally_price_time_envelope_exceeded": both_first is not None,
            "prior_rally_price_time_envelope_exceeded_at": both_first,
            "interpretation": "EARLY_TRANSITION_PRESSURE_AVAILABLE_FOR_ANALYST" if both_first else None,
            "counting_convention": "COMPLETED_DAILY_INTERVALS_START_EXCLUSIVE_FIRST_MAX_INCLUSIVE",
            "observed_candidate_bars": candidates,
            "limitation": "MEASUREMENT_ONLY_NOT_BULL_SEASON_CAPITAL_CONFIRMATION_OR_DURABILITY_PREDICTION",
            **locks}
        result["measurement_hash"] = _overbalance_hash(result)
        return result
    except (TransitionReplayEvidenceError, OverflowError) as exc:
        return {**_blocked(OVERBALANCE_SCHEMA_VERSION, str(exc), as_of=as_of), **locks}


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
    overbalance_daily_bars: object = None,
    overbalance_reference: FrozenRallyReference | None = None,
    previous_overbalance_measurement: dict[str, Any] | None = None,
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
    result = {
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
    if overbalance_reference is not None or overbalance_daily_bars is not None:
        measurement = build_price_time_overbalance_measurement(overbalance_daily_bars,
            reference=overbalance_reference, as_of=as_of, previous_measurement=previous_overbalance_measurement)
        result["price_time_overbalance_measurement"] = measurement
        # Preserve the existing raw-breach wording: it is not a new invalidation rule.
        candidate_matches = (isinstance(overbalance_reference, FrozenRallyReference)
            and structure.get("candidate_breakout_at") == _iso_z(_parse_timestamp(
                overbalance_reference.candidate_start_at, "candidate_start_at"))) if measurement["state"] != "BLOCKED" else False
        result["overbalance_existing_structure_invalidation"] = {
            "state": structure["state"] if candidate_matches else "BLOCKED",
            "candidate_invalidation_anchor_raw_breach_at": structure.get("measurements", {}).get(
                "candidate_invalidation_anchor_raw_breach_at") if candidate_matches else None,
            "source": "structure_measurements", "limitation": "EXISTING_RAW_BREACH_NOT_NEW_CONFIRMED_INVALIDATION"}
    return result
