"""Existing locked L6 calculations shared by research and candidate runtime."""
from __future__ import annotations

import math
import statistics
from typing import Any, Callable

DAY_MS = 86_400_000

class CandidateDataError(ValueError):
    pass


def _finite(value: Any, code: str) -> float:
    if isinstance(value, bool):
        raise CandidateDataError(code)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateDataError(code) from exc
    if not math.isfinite(result):
        raise CandidateDataError(code)
    return result


def _positive(value: Any, code: str) -> float:
    result = _finite(value, code)
    if result <= 0:
        raise CandidateDataError(code)
    return result


def _nonnegative(value: Any, code: str) -> float:
    result = _finite(value, code)
    if result < 0:
        raise CandidateDataError(code)
    return result


def _integer_ms(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CandidateDataError(code)
    return value


def _select_latest_revisions(
    rows: Any,
    *,
    as_of_ms: int,
    identity: Callable[[dict[str, Any]], Any],
    code_prefix: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise CandidateDataError(f"{code_prefix}_MISSING")
    selected: dict[Any, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise CandidateDataError(f"{code_prefix}_ROW_INVALID")
        observed_at_ms = _integer_ms(
            raw.get("observed_at_ms"), f"{code_prefix}_OBSERVED_AT_INVALID"
        )
        available_at_ms = _integer_ms(
            raw.get("available_at_ms"), f"{code_prefix}_AVAILABLE_AT_INVALID"
        )
        if observed_at_ms > available_at_ms:
            raise CandidateDataError(f"{code_prefix}_AVAILABLE_BEFORE_OBSERVATION")
        if available_at_ms > as_of_ms:
            continue
        key = identity(raw)
        if key is None:
            raise CandidateDataError(f"{code_prefix}_IDENTITY_INVALID")
        previous = selected.get(key)
        if previous is None or available_at_ms > previous["available_at_ms"]:
            selected[key] = raw
        elif available_at_ms == previous["available_at_ms"] and raw != previous:
            raise CandidateDataError(f"{code_prefix}_AMBIGUOUS_REVISION")
    if not selected:
        raise CandidateDataError(f"{code_prefix}_NO_POINT_IN_TIME_OBSERVATION")
    return sorted(selected.values(), key=lambda row: (row["observed_at_ms"], str(identity(row))))


def _table(
    raw_inputs: dict[str, Any],
    name: str,
    as_of_ms: int,
    *,
    identity_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    tables = raw_inputs.get("tables")
    if not isinstance(tables, dict):
        raise CandidateDataError("RAW_TABLES_NOT_OBJECT")

    def identity(row: dict[str, Any]) -> tuple[Any, ...] | None:
        values = tuple(row.get(field) for field in identity_fields)
        return None if any(value is None for value in values) else values

    return _select_latest_revisions(
        tables.get(name),
        as_of_ms=as_of_ms,
        identity=identity,
        code_prefix=name,
    )


def _last(rows: list[dict[str, Any]], count: int, code: str) -> list[dict[str, Any]]:
    if len(rows) < count:
        raise CandidateDataError(f"{code}_HISTORY_INSUFFICIENT")
    return rows[-count:]


def _ohlcv(raw: dict[str, Any], as_of_ms: int) -> tuple[list[dict[str, float]], float]:
    rows = _table(
        raw,
        "OHLCV_DAILY",
        as_of_ms,
        identity_fields=("observed_at_ms",),
    )
    rows = _last(rows, 201, "OHLCV_DAILY")
    timestamps = [row["observed_at_ms"] for row in rows]
    if any(right - left != DAY_MS for left, right in zip(timestamps, timestamps[1:])):
        raise CandidateDataError("OHLCV_DAILY_PERIOD_GAP")
    parsed: list[dict[str, float]] = []
    for row in rows:
        if row.get("complete") is not True:
            raise CandidateDataError("OHLCV_DAILY_PARTIAL_BAR")
        open_value = _positive(row.get("open"), "OHLCV_OPEN_INVALID")
        high = _positive(row.get("high"), "OHLCV_HIGH_INVALID")
        low = _positive(row.get("low"), "OHLCV_LOW_INVALID")
        close = _positive(row.get("close"), "OHLCV_CLOSE_INVALID")
        if high < max(open_value, close, low) or low > min(open_value, close, high):
            raise CandidateDataError("OHLCV_BAR_GEOMETRY_INVALID")
        parsed.append({"open": open_value, "high": high, "low": low, "close": close})
    true_ranges = []
    for index in range(len(parsed) - 20, len(parsed)):
        current = parsed[index]
        previous_close = parsed[index - 1]["close"]
        true_ranges.append(
            max(
                current["high"] - current["low"],
                abs(current["high"] - previous_close),
                abs(current["low"] - previous_close),
            )
        )
    atr20 = _positive(statistics.fmean(true_ranges), "ATR20_NONPOSITIVE")
    return parsed, atr20


def _close_minus_sma200(raw: dict[str, Any], as_of_ms: int) -> float:
    bars, atr20 = _ohlcv(raw, as_of_ms)
    closes = [bar["close"] for bar in bars]
    return (closes[-1] - statistics.fmean(closes[-200:])) / atr20


def _sma50_minus_sma200(raw: dict[str, Any], as_of_ms: int) -> float:
    bars, atr20 = _ohlcv(raw, as_of_ms)
    closes = [bar["close"] for bar in bars]
    return (statistics.fmean(closes[-50:]) - statistics.fmean(closes[-200:])) / atr20


def _return_20d_over_atr(raw: dict[str, Any], as_of_ms: int) -> float:
    bars, atr20 = _ohlcv(raw, as_of_ms)
    current = bars[-1]["close"]
    lag_20 = bars[-21]["close"]
    return math.log(current / lag_20) / ((atr20 / current) * math.sqrt(20))


def _cvd(raw: dict[str, Any], as_of_ms: int) -> float:
    rows = _table(
        raw,
        "AGGRESSOR_DAILY",
        as_of_ms,
        identity_fields=("observed_at_ms",),
    )
    rows = _last(rows, 20, "AGGRESSOR_DAILY")
    timestamps = [row["observed_at_ms"] for row in rows]
    if any(right - left != DAY_MS for left, right in zip(timestamps, timestamps[1:])):
        raise CandidateDataError("AGGRESSOR_DAILY_PERIOD_GAP")
    signed = 0.0
    total_sum = 0.0
    for row in rows:
        if row.get("complete") is not True:
            raise CandidateDataError("AGGRESSOR_DAILY_PARTIAL_BAR")
        buyer = _nonnegative(
            row.get("buyer_initiated_quote_volume"), "CVD_BUYER_VOLUME_INVALID"
        )
        seller = _nonnegative(
            row.get("seller_initiated_quote_volume"), "CVD_SELLER_VOLUME_INVALID"
        )
        unknown = _nonnegative(
            row.get("unknown_aggressor_quote_volume"), "CVD_UNKNOWN_VOLUME_INVALID"
        )
        total = _nonnegative(row.get("total_quote_volume"), "CVD_TOTAL_VOLUME_INVALID")
        if unknown != 0:
            raise CandidateDataError("CVD_UNKNOWN_AGGRESSOR_VOLUME")
        if not math.isclose(total, buyer + seller + unknown, rel_tol=1e-12, abs_tol=1e-9):
            raise CandidateDataError("CVD_VOLUME_SUM_MISMATCH")
        signed += buyer - seller
        total_sum += total
    return signed / _positive(total_sum, "CVD_TOTAL_VOLUME_NONPOSITIVE")
