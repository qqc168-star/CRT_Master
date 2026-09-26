from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any


STRUCTURE_SCHEMA_VERSION = "CRT_BTC_TRANSITION_STRUCTURE_MEASUREMENTS_V0.1"
FIFTY_WMA_SCHEMA_VERSION = "CRT_BTC_50WMA_LONG_HORIZON_CONTEXT_V0.1"
TWO_HUNDRED_WMA_SCHEMA_VERSION = "CRT_BTC_200WMA_LONG_HORIZON_CONTEXT_V0.1"
BTC_LONG_HORIZON_SCHEMA_VERSION = "CRT_BTC_LONG_HORIZON_CONTEXT_V0.1"
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
