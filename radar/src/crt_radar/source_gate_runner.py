#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
import statistics
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .source_registry import SourceRegistry, SourceSpec, canonical_json_bytes, sha256_hex
from .liquidation_aggregator import load_verified_snapshot, verify_snapshot, SnapshotCorruption


USER_AGENT = "CRT-Radar/0.4-RC1 read-only source gate"
FUTURE_CLOCK_SKEW_S = 300


class ContractViolation(ValueError):
    pass


class StaleData(ContractViolation):
    pass


@dataclass
class FetchResult:
    source_id: str
    status: str
    payload: Any = None
    elapsed_ms: float | None = None
    attempts: int = 1
    error: str | None = None


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or 500 <= exc.code < 600
    return isinstance(exc, (TimeoutError, urllib.error.URLError, OSError))


def _http_get(
    spec: SourceSpec,
    *,
    timeout: float = 15.0,
    max_attempts: int = 3,
    base_backoff_s: float = 0.25,
) -> FetchResult:
    endpoint_map = spec.raw.get("endpoints")
    if endpoint_map is not None and not (
        isinstance(endpoint_map, dict)
        and endpoint_map
        and all(isinstance(key, str) and isinstance(value, str) for key, value in endpoint_map.items())
    ):
        return FetchResult(spec.source_id, "ERROR", error="endpoints must be a non-empty string map")
    if endpoint_map is None and not spec.endpoint:
        return FetchResult(spec.source_id, "ERROR", error="endpoint missing")
    endpoints = endpoint_map or {"default": spec.endpoint}
    endpoint_transports = spec.raw.get("endpoint_transports", {})
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            fetched_payloads: dict[str, Any] = {}
            for key, endpoint in endpoints.items():
                request = urllib.request.Request(
                    endpoint,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"},
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read()
                endpoint_transport = endpoint_transports.get(key, spec.transport)
                if endpoint_transport in {"HTTPS_CSV", "MULTI_HTTPS_CSV"}:
                    fetched_payloads[key] = raw.decode("utf-8-sig")
                else:
                    fetched_payloads[key] = json.loads(raw.decode("utf-8"))
            payload: Any = fetched_payloads if endpoint_map is not None else fetched_payloads["default"]
            return FetchResult(
                spec.source_id,
                "OK",
                payload=payload,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                attempts=attempt,
            )
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not _is_retryable(exc):
                break
            time.sleep(base_backoff_s * (2 ** (attempt - 1)) + random.random() * base_backoff_s)
    assert last_error is not None
    return FetchResult(
        spec.source_id,
        "ERROR",
        elapsed_ms=(time.perf_counter() - started) * 1000,
        attempts=attempt,
        error=f"{type(last_error).__name__}: {last_error}",
    )


def probe_liquidation_stream(
    spec: SourceSpec,
    *,
    open_timeout_s: float = 10.0,
    observation_seconds: float = 5.0,
    max_attempts: int = 3,
    base_backoff_s: float = 0.25,
) -> FetchResult:
    """Diagnostic only. Never supplies official liquidation metrics."""
    if spec.input_family != "LIQUIDATION_CONNECTIVITY_PROBE":
        raise ValueError("Expected LIQUIDATION_CONNECTIVITY_PROBE source")
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        opened_ms = int(time.time() * 1000)
        try:
            from websockets.sync.client import connect

            messages: list[Any] = []
            deadline = time.perf_counter() + observation_seconds
            with connect(
                spec.endpoint,
                open_timeout=open_timeout_s,
                close_timeout=1.0,
                user_agent_header=USER_AGENT,
            ) as websocket:
                while time.perf_counter() < deadline:
                    remaining = deadline - time.perf_counter()
                    try:
                        message = websocket.recv(timeout=max(0.0, remaining))
                    except TimeoutError:
                        break
                    if message is None:
                        raise ConnectionError("stream closed unexpectedly")
                    messages.append(json.loads(message))
            return FetchResult(
                spec.source_id,
                "PROBE_ONLY",
                payload={
                    "connected": True,
                    "opened_ms": opened_ms,
                    "closed_ms": int(time.time() * 1000),
                    "message_count": len(messages),
                    "messages": messages,
                    "metric_authority": "NONE",
                },
                elapsed_ms=(time.perf_counter() - started) * 1000,
                attempts=attempt,
            )
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(base_backoff_s * (2 ** (attempt - 1)) + random.random() * base_backoff_s)
    assert last_error is not None
    return FetchResult(
        spec.source_id,
        "ERROR",
        elapsed_ms=(time.perf_counter() - started) * 1000,
        attempts=attempt,
        error=f"{type(last_error).__name__}: {last_error}",
    )


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractViolation(f"{field} must be an object")
    return value


def _finite(value: Any, field: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise ContractViolation(f"{field} missing or invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"{field} not numeric") from exc
    if not math.isfinite(number):
        raise ContractViolation(f"{field} not finite")
    if positive and number <= 0:
        raise ContractViolation(f"{field} must be positive")
    if nonnegative and number < 0:
        raise ContractViolation(f"{field} must be nonnegative")
    return number


def _timestamp_ms(value: Any, field: str) -> int:
    number = int(_finite(value, field, positive=True))
    if number < 1_000_000_000_000:
        raise ContractViolation(f"{field} is not millisecond Unix time")
    return number


def parse_fred_latest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, str) or not payload.strip():
        raise ContractViolation("FRED payload empty")
    rows = list(csv.DictReader(io.StringIO(payload)))
    valid = [r for r in rows if len(r) >= 2 and list(r.values())[1] not in {"", ".", "NA", None}]
    if not valid:
        raise ContractViolation("No valid FRED observations")
    row = valid[-1]
    keys = list(row)
    date = datetime.strptime(row[keys[0]], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return {
        "as_of_ms": int(date.timestamp() * 1000),
        "date": date.date().isoformat(),
        "value": _finite(row[keys[1]], keys[1]),
        "series_id": keys[1],
    }


def _fred_history(payload: Any, expected_series: str) -> list[tuple[int, float]]:
    if not isinstance(payload, str) or not payload.strip():
        raise ContractViolation(f"{expected_series} FRED payload empty")
    rows = list(csv.DictReader(io.StringIO(payload)))
    if not rows:
        raise ContractViolation(f"{expected_series} FRED rows missing")
    keys = list(rows[0])
    if len(keys) < 2 or expected_series not in keys:
        raise ContractViolation(f"{expected_series} FRED column missing")
    result: list[tuple[int, float]] = []
    for row in rows:
        raw_value = row.get(expected_series)
        if raw_value in {None, "", ".", "NA"}:
            continue
        date = datetime.strptime(str(row[keys[0]]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        result.append((int(date.timestamp() * 1000), _finite(raw_value, expected_series)))
    if not result:
        raise ContractViolation(f"{expected_series} has no valid observations")
    result.sort(key=lambda item: item[0])
    return result


def _last_values(rows: list[tuple[int, float]], count: int, field: str) -> list[tuple[int, float]]:
    if len(rows) < count:
        raise ContractViolation(f"{field} history requires {count} observations")
    return rows[-count:]


def parse_macro_context(payload: Any) -> dict[str, Any]:
    row = _require_mapping(payload, "macro context payload")
    cpi = _last_values(_fred_history(row.get("core_cpi"), "CPILFESL"), 13, "CPILFESL")
    unemployment = _last_values(_fred_history(row.get("unemployment"), "UNRATE"), 15, "UNRATE")
    effr = _fred_history(row.get("effr"), "EFFR")[-1]
    core_pce = _last_values(_fred_history(row.get("core_pce"), "PCEPILFE"), 13, "PCEPILFE")

    cpi_values = [value for _, value in cpi]
    core_inflation_acceleration = (
        100.0 * ((cpi_values[-1] / cpi_values[-4]) ** 4 - 1.0)
        - 100.0 * (cpi_values[-1] / cpi_values[-13] - 1.0)
    )
    unrate_values = [value for _, value in unemployment]
    current_unemployment_mean = statistics.fmean(unrate_values[-3:])
    prior_unemployment_means = [
        statistics.fmean(unrate_values[index - 2 : index + 1])
        for index in range(len(unrate_values) - 2, 1, -1)
    ]
    if len(prior_unemployment_means) != 12:
        raise ContractViolation("UNRATE prior-window count invalid")
    unemployment_deterioration = current_unemployment_mean - min(prior_unemployment_means)
    pce_values = [value for _, value in core_pce]
    core_pce_yoy = 100.0 * (pce_values[-1] / pce_values[-13] - 1.0)
    real_policy_rate = effr[1] - core_pce_yoy

    return {
        "as_of_ms": max(cpi[-1][0], unemployment[-1][0], effr[0], core_pce[-1][0]),
        "core_inflation_acceleration": core_inflation_acceleration,
        "unemployment_deterioration": unemployment_deterioration,
        "real_policy_rate": real_policy_rate,
        "source_series": ["CPILFESL", "UNRATE", "EFFR", "PCEPILFE"],
    }


def parse_rates_context(payload: Any) -> dict[str, Any]:
    row = _require_mapping(payload, "rates context payload")
    usd = _last_values(_fred_history(row.get("broad_usd"), "DTWEXBGS"), 21, "DTWEXBGS")
    real_10y = _last_values(_fred_history(row.get("real_10y"), "DFII10"), 21, "DFII10")
    nominal_2y = _last_values(_fred_history(row.get("nominal_2y"), "DGS2"), 21, "DGS2")
    return {
        "as_of_ms": max(usd[-1][0], real_10y[-1][0], nominal_2y[-1][0]),
        "broad_usd_20d_log_change": 100.0 * math.log(usd[-1][1] / usd[0][1]),
        "real_10y_yield_20d_change_bp": 100.0 * (real_10y[-1][1] - real_10y[0][1]),
        "nominal_2y_yield_20d_change_bp": 100.0 * (nominal_2y[-1][1] - nominal_2y[0][1]),
    }


def _stablecoin_series(payload: Any, field: str) -> list[tuple[int, float]]:
    if not isinstance(payload, list) or not payload:
        raise ContractViolation(f"{field} stablecoin history missing")
    result: list[tuple[int, float]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        totals = raw.get("totalCirculatingUSD")
        if not isinstance(totals, dict) or totals.get("peggedUSD") is None:
            continue
        timestamp_ms = int(_finite(raw.get("date"), f"{field}.date", positive=True) * 1000)
        result.append((timestamp_ms, _finite(totals.get("peggedUSD"), f"{field}.peggedUSD", nonnegative=True)))
    if not result:
        raise ContractViolation(f"{field} stablecoin history has no valid rows")
    result.sort(key=lambda item: item[0])
    return result


def parse_credit_liquidity_context(payload: Any) -> dict[str, Any]:
    row = _require_mapping(payload, "credit liquidity context payload")
    usdt = _stablecoin_series(row.get("usdt"), "USDT")
    usdc = _stablecoin_series(row.get("usdc"), "USDC")
    latest_ms = min(usdt[-1][0], usdc[-1][0])
    prior_ms = latest_ms - 30 * 86_400_000

    def exact_value(series: list[tuple[int, float]], timestamp_ms: int, field: str) -> float:
        match = next((value for observed_ms, value in series if observed_ms == timestamp_ms), None)
        if match is None:
            raise ContractViolation(f"{field} exact 30-day observation missing")
        return match

    current_total = exact_value(usdt, latest_ms, "USDT") + exact_value(usdc, latest_ms, "USDC")
    prior_total = exact_value(usdt, prior_ms, "USDT") + exact_value(usdc, prior_ms, "USDC")
    if current_total <= 0 or prior_total <= 0:
        raise ContractViolation("stablecoin aggregate must be positive")
    high_yield = _last_values(_fred_history(row.get("high_yield_oas"), "BAMLH0A0HYM2"), 21, "BAMLH0A0HYM2")
    return {
        "as_of_ms": max(latest_ms, high_yield[-1][0]),
        "stablecoin_supply_30d_log_change": 100.0 * math.log(current_total / prior_total),
        "high_yield_oas_20d_change_bp": 100.0 * (high_yield[-1][1] - high_yield[0][1]),
        "spot_btc_etp_flow_20d_pct_aum": None,
        "spot_btc_etp_flow_state": "COLLECTING_OFFICIAL_ISSUER_HISTORY",
        "stablecoin_universe": ["1:USDT", "2:USDC"],
    }


def parse_open_interest_notional(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ContractViolation("OI notional payload must be a non-empty list")
    row = _require_mapping(payload[-1], "OI notional observation")
    if row.get("symbol") != "BTCUSDT":
        raise ContractViolation("OI notional symbol must be BTCUSDT")
    return {
        "as_of_ms": _timestamp_ms(row.get("timestamp"), "timestamp"),
        "open_interest_notional_usd": _finite(row.get("sumOpenInterestValue"), "sumOpenInterestValue", nonnegative=True),
    }


def parse_oi(payload: Any) -> dict[str, Any]:
    row = _require_mapping(payload, "OI payload")
    if row.get("symbol") != "BTCUSDT":
        raise ContractViolation("OI symbol must be BTCUSDT")
    return {
        "as_of_ms": _timestamp_ms(row.get("time"), "time"),
        "symbol": "BTCUSDT",
        "open_interest_contracts": _finite(row.get("openInterest"), "openInterest", positive=True),
    }


def parse_btc_spot_ticker(payload: Any) -> dict[str, Any]:
    row = _require_mapping(payload, "BTC spot ticker payload")
    if row.get("symbol") != "BTCUSDT":
        raise ContractViolation("BTC spot symbol must be BTCUSDT")
    return {
        "as_of_ms": _timestamp_ms(row.get("closeTime"), "closeTime"),
        "symbol": "BTCUSDT",
        "spot_price_usd": _finite(
            row.get("lastPrice"),
            "lastPrice",
            positive=True,
        ),
    }


def parse_funding(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ContractViolation("Funding payload must be non-empty list")
    row = _require_mapping(payload[-1], "Funding observation")
    if row.get("symbol") != "BTCUSDT":
        raise ContractViolation("Funding symbol must be BTCUSDT")
    result = {
        "as_of_ms": _timestamp_ms(row.get("fundingTime"), "fundingTime"),
        "symbol": "BTCUSDT",
        "funding_rate": _finite(row.get("fundingRate"), "fundingRate"),
        "mark_price": _finite(row.get("markPrice"), "markPrice", positive=True),
    }
    if len(payload) >= 9:
        selected = payload[-9:]
        timestamps = [_timestamp_ms(item.get("fundingTime"), "fundingTime") for item in selected]
        if all(right - left == 28_800_000 for left, right in zip(timestamps, timestamps[1:])):
            result["abs_funding_3d_mean_bp"] = 10_000.0 * abs(
                statistics.fmean(_finite(item.get("fundingRate"), "fundingRate") for item in selected)
            )
    return result


def _iso8601_ms(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{field} missing or invalid")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    match = re.match(r"^(.*?\.)(\d+)([+-]\d{2}:\d{2})$", text)
    if match and len(match.group(2)) > 6:
        text = match.group(1) + match.group(2)[:6] + match.group(3)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractViolation(f"{field} is not ISO 8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def parse_coinmetrics_caps(payload: Any) -> dict[str, Any]:
    row = _require_mapping(payload, "Coin Metrics payload")
    data = row.get("data")
    if not isinstance(data, list) or not data:
        raise ContractViolation("Coin Metrics data must be a non-empty list")
    candidates: list[tuple[int, dict[str, Any]]] = []
    for raw in data:
        if not isinstance(raw, dict) or raw.get("asset") != "btc":
            continue
        direct_mvrv = raw.get("CapMVRVCur") not in {None, ""}
        legacy_caps = raw.get("CapMrktCurUSD") not in {None, ""} and raw.get("CapRealUSD") not in {None, ""}
        if not direct_mvrv and not legacy_caps:
            continue
        as_of_ms = _iso8601_ms(raw.get("time"), "time")
        candidates.append((as_of_ms, raw))
    if not candidates:
        raise ContractViolation("No complete BTC CapMrktCurUSD/CapRealUSD observation")
    as_of_ms, latest = max(candidates, key=lambda item: item[0])
    if latest.get("CapMVRVCur") not in {None, ""}:
        mvrv = _finite(latest.get("CapMVRVCur"), "CapMVRVCur", positive=True)
    else:
        mvrv = _finite(latest.get("CapMrktCurUSD"), "CapMrktCurUSD", positive=True) / _finite(
            latest.get("CapRealUSD"), "CapRealUSD", positive=True
        )
    market_cap = None
    realized_cap = None
    if latest.get("CapMrktCurUSD") not in {None, ""}:
        market_cap = _finite(latest.get("CapMrktCurUSD"), "CapMrktCurUSD", positive=True)
        realized_cap = (
            _finite(latest.get("CapRealUSD"), "CapRealUSD", positive=True)
            if latest.get("CapRealUSD") not in {None, ""}
            else market_cap / mvrv
        )
    result = {
        "as_of_ms": as_of_ms,
        "asset": "btc",
        "market_cap_usd": market_cap,
        "realized_cap_usd": realized_cap,
        "mvrv": mvrv,
        "nupl": 1.0 - 1.0 / mvrv,
        "formula_contract": {
            "mvrv": "Coin Metrics CapMVRVCur",
            "nupl": "1 - 1 / CapMVRVCur",
            "realized_cap_usd": "CapMrktCurUSD / CapMVRVCur when CapMrktCurUSD is available",
        },
    }
    complete_caps = [
        (timestamp_ms, raw)
        for timestamp_ms, raw in candidates
        if raw.get("CapMrktCurUSD") not in {None, ""}
    ]
    prior = next((raw for timestamp_ms, raw in complete_caps if timestamp_ms == as_of_ms - 30 * 86_400_000), None)
    if realized_cap is not None and prior is not None:
        prior_market_cap = _finite(prior.get("CapMrktCurUSD"), "CapMrktCurUSD", positive=True)
        if prior.get("CapMVRVCur") not in {None, ""}:
            prior_realized_cap = prior_market_cap / _finite(prior.get("CapMVRVCur"), "CapMVRVCur", positive=True)
        else:
            prior_realized_cap = _finite(prior.get("CapRealUSD"), "CapRealUSD", positive=True)
        result["realized_cap_30d_log_change"] = 100.0 * math.log(realized_cap / prior_realized_cap)
    return result


def parse_price_structure(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise ContractViolation("BTC kline payload must be a list")
    now_ms = int(time.time() * 1000)
    complete = [row for row in payload if isinstance(row, list) and len(row) >= 11 and int(row[6]) < now_ms]
    if len(complete) < 201:
        raise ContractViolation("BTC price structure requires 201 complete daily bars")
    bars = complete[-201:]
    parsed: list[dict[str, float]] = []
    for row in bars:
        open_value = _finite(row[1], "open", positive=True)
        high = _finite(row[2], "high", positive=True)
        low = _finite(row[3], "low", positive=True)
        close = _finite(row[4], "close", positive=True)
        quote_volume = _finite(row[7], "quote_volume", nonnegative=True)
        taker_buy_quote = _finite(row[10], "taker_buy_quote_volume", nonnegative=True)
        if high < max(open_value, low, close) or low > min(open_value, high, close):
            raise ContractViolation("BTC kline geometry invalid")
        if taker_buy_quote > quote_volume:
            raise ContractViolation("taker buy quote volume exceeds total quote volume")
        parsed.append(
            {
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
                "quote_volume": quote_volume,
                "taker_buy_quote": taker_buy_quote,
            }
        )
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
    atr20 = statistics.fmean(true_ranges)
    if atr20 <= 0:
        raise ContractViolation("ATR20 must be positive")
    closes = [bar["close"] for bar in parsed]
    signed_quote_volume = sum(2.0 * bar["taker_buy_quote"] - bar["quote_volume"] for bar in parsed[-20:])
    total_quote_volume = sum(bar["quote_volume"] for bar in parsed[-20:])
    if total_quote_volume <= 0:
        raise ContractViolation("20-day quote volume must be positive")
    return {
        "as_of_ms": int(bars[-1][6]),
        "close_minus_sma200_over_atr20": (closes[-1] - statistics.fmean(closes[-200:])) / atr20,
        "sma50_minus_sma200_over_atr20": (
            statistics.fmean(closes[-50:]) - statistics.fmean(closes[-200:])
        ) / atr20,
        "return_20d_over_atr_vol": math.log(closes[-1] / closes[-21]) / ((atr20 / closes[-1]) * math.sqrt(20.0)),
        "cvd_20d_share": signed_quote_volume / total_quote_volume,
        "source_scope": "BINANCE_BTCUSDT_DIRECTIONAL_PROXY",
        "formal_composite_authority": "NONE",
    }


def parse_liquidation_aggregate(payload: Any, spec: SourceSpec) -> dict[str, Any]:
    row = _require_mapping(payload, "Liquidation aggregate snapshot")
    try:
        verify_snapshot(row)
    except SnapshotCorruption as exc:
        raise ContractViolation(f"liquidation snapshot integrity failure: {exc}") from exc
    if row.get("quality_state") != "VALID_FRESH_COMPLETE_COVERAGE":
        raise ContractViolation("liquidation snapshot is not quality-valid")
    if row.get("blocked_reasons") not in ([], None):
        raise ContractViolation("liquidation snapshot contains blocked reasons")
    if row.get("schema_version") != "CRT_LIQ_AGGREGATE_SNAPSHOT_V1":
        raise ContractViolation("Unsupported liquidation aggregate schema")
    if row.get("symbol") != "BTCUSDT":
        raise ContractViolation("Liquidation aggregate symbol must be BTCUSDT")
    coverage = _finite(row.get("coverage_ratio"), "coverage_ratio", nonnegative=True)
    minimum = float(spec.raw.get("minimum_coverage_ratio", 0.95))
    if coverage > 1:
        raise ContractViolation("coverage_ratio cannot exceed 1")
    if coverage < minimum:
        raise ContractViolation(f"coverage_ratio below {minimum}")
    windows = _require_mapping(row.get("windows"), "windows")
    parsed_windows: dict[str, Any] = {}
    for label in ("1h", "24h"):
        bucket = _require_mapping(windows.get(label), f"windows.{label}")
        long_usd = _finite(bucket.get("long_liquidation_usd"), f"{label}.long", nonnegative=True)
        short_usd = _finite(bucket.get("short_liquidation_usd"), f"{label}.short", nonnegative=True)
        total_usd = _finite(bucket.get("total_liquidation_usd"), f"{label}.total", nonnegative=True)
        if abs((long_usd + short_usd) - total_usd) > max(0.01, total_usd * 1e-9):
            raise ContractViolation(f"{label} total does not equal long + short")
        parsed_windows[label] = {
            "long_liquidation_usd": long_usd,
            "short_liquidation_usd": short_usd,
            "total_liquidation_usd": total_usd,
            "event_count": int(_finite(bucket.get("event_count"), f"{label}.event_count", nonnegative=True)),
        }
    return {
        "as_of_ms": _timestamp_ms(row.get("as_of_ms"), "as_of_ms"),
        "symbol": "BTCUSDT",
        "coverage_ratio": coverage,
        "windows": parsed_windows,
    }


PARSERS: dict[str, Callable[..., dict[str, Any]]] = {
    "FRED_LATEST_CSV_V1": parse_fred_latest,
    "BINANCE_OI_V1": parse_oi,
    "BINANCE_FUNDING_V1": parse_funding,
    "BINANCE_SPOT_TICKER_24H_V1": parse_btc_spot_ticker,
    "FRED_MACRO_CONTEXT_V1": parse_macro_context,
    "FRED_RATES_CONTEXT_V1": parse_rates_context,
    "CRT_CREDIT_LIQUIDITY_CONTEXT_V1": parse_credit_liquidity_context,
    "BINANCE_OI_NOTIONAL_V1": parse_open_interest_notional,
    "COINMETRICS_MVRV_COMMUNITY_V1": parse_coinmetrics_caps,
    "BINANCE_PRICE_STRUCTURE_PROXY_V1": parse_price_structure,
}


def _derive_cross_family_metrics(parsed: dict[str, Any]) -> None:
    oi = parsed.get("OPEN_INTEREST_NOTIONAL")
    onchain = parsed.get("ONCHAIN_VALUE")
    liquidation = parsed.get("LIQUIDATION_AGGREGATES")
    if isinstance(oi, dict) and isinstance(onchain, dict):
        market_cap = onchain.get("market_cap_usd")
        if isinstance(market_cap, (int, float)) and market_cap > 0:
            oi["oi_to_market_cap_pct"] = 100.0 * float(oi["open_interest_notional_usd"]) / float(market_cap)
    if isinstance(oi, dict) and isinstance(liquidation, dict):
        notional = float(oi.get("open_interest_notional_usd", 0.0))
        bucket = liquidation.get("windows", {}).get("24h", {})
        total = float(bucket.get("total_liquidation_usd", 0.0))
        long_value = float(bucket.get("long_liquidation_usd", 0.0))
        short_value = float(bucket.get("short_liquidation_usd", 0.0))
        if notional > 0:
            liquidation["liquidation_intensity_24h_pct"] = 100.0 * total / notional
        liquidation["short_minus_long_liquidation_share_24h"] = (
            0.0 if total == 0 else (short_value - long_value) / total
        )


def _assert_fresh(as_of_ms: int, *, now_ms: int, max_age_seconds: int) -> None:
    if as_of_ms > now_ms + FUTURE_CLOCK_SKEW_S * 1000:
        raise ContractViolation("source timestamp implausibly in future")
    if now_ms - as_of_ms > max_age_seconds * 1000:
        raise StaleData("source exceeds freshness policy")


def _payload_hash(payload: Any) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = canonical_json_bytes(payload)
    return sha256_hex(raw)


def _evidence_envelope(
    spec: SourceSpec,
    fetched: FetchResult,
    *,
    registry_hash: str,
    parsed: dict[str, Any] | None,
    quality_state: str,
    quality_error: str | None = None,
) -> dict[str, Any]:
    envelope = {
        "source_id": spec.source_id,
        "namespace": spec.namespace,
        "input_family": spec.input_family,
        "parser_id": spec.parser_id,
        "transport_status": fetched.status,
        "quality_state": quality_state,
        "as_of_ms": parsed.get("as_of_ms") if parsed else None,
        "attempts": fetched.attempts,
        "elapsed_ms": fetched.elapsed_ms,
        "payload_hash": _payload_hash(fetched.payload),
        "registry_hash": registry_hash,
        "quality_error": quality_error,
    }
    envelope["evidence_hash"] = sha256_hex(canonical_json_bytes(envelope))
    return envelope


def run_source_gate(
    registry: SourceRegistry,
    *,
    fetch_overrides: dict[str, FetchResult] | None = None,
    liquidation_aggregate_payload: dict[str, Any] | None = None,
    probe_fetcher: Callable[[SourceSpec], FetchResult] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    now = int(time.time() * 1000) if now_ms is None else now_ms
    run_id = str(uuid.uuid4())
    overrides = fetch_overrides or {}
    evidence: list[dict[str, Any]] = []
    parsed: dict[str, Any] = {}
    blocked: list[str] = []

    critical_families = ["DOLLAR_STRENGTH_PROXY", "OPEN_INTEREST", "FUNDING_RATE"]
    for family in critical_families:
        spec = registry.by_input_family(family)
        if fetch_overrides is not None:
            fetched = overrides.get(spec.source_id) or FetchResult(
                spec.source_id, "MISSING", error="explicit offline override missing"
            )
        else:
            fetched = _http_get(spec)
        parsed_value: dict[str, Any] | None = None
        quality_state = "INVALID"
        quality_error: str | None = None
        if fetched.status != "OK":
            blocked.append(f"{family}_TRANSPORT_ERROR")
            quality_state = "TRANSPORT_ERROR"
        else:
            try:
                parser = PARSERS[spec.parser_id]
                parsed_value = parser(fetched.payload)
                _assert_fresh(parsed_value["as_of_ms"], now_ms=now, max_age_seconds=spec.max_age_seconds)
                quality_state = "VALID_FRESH"
                parsed[family] = parsed_value
            except Exception as exc:
                quality_error = f"{type(exc).__name__}: {exc}"
                quality_state = "STALE" if isinstance(exc, StaleData) else "INVALID"
                blocked.append(f"{family}_{quality_state}")
        evidence.append(
            _evidence_envelope(
                spec,
                fetched,
                registry_hash=registry.hash,
                parsed=parsed_value,
                quality_state=quality_state,
                quality_error=quality_error,
            )
        )

    probe_spec = registry.by_input_family("LIQUIDATION_CONNECTIVITY_PROBE")
    probe = overrides.get(probe_spec.source_id)
    if probe is None and probe_fetcher is not None:
        probe = probe_fetcher(probe_spec)
    if probe is not None:
        evidence.append(
            _evidence_envelope(
                probe_spec,
                probe,
                registry_hash=registry.hash,
                parsed=None,
                quality_state="DIAGNOSTIC_ONLY" if probe.status == "PROBE_ONLY" else "TRANSPORT_ERROR",
                quality_error=probe.error,
            )
        )

    agg_spec = registry.by_input_family("LIQUIDATION_AGGREGATES")
    agg_fetch = FetchResult(
        agg_spec.source_id,
        "OK" if liquidation_aggregate_payload is not None else "MISSING",
        payload=liquidation_aggregate_payload,
    )
    agg_parsed: dict[str, Any] | None = None
    agg_quality = "MISSING"
    agg_error: str | None = None
    if liquidation_aggregate_payload is None:
        blocked.append("LIQUIDATION_AGGREGATOR_REQUIRED")
    else:
        try:
            agg_parsed = parse_liquidation_aggregate(liquidation_aggregate_payload, agg_spec)
            _assert_fresh(agg_parsed["as_of_ms"], now_ms=now, max_age_seconds=agg_spec.max_age_seconds)
            agg_quality = "VALID_FRESH_COMPLETE_COVERAGE"
            parsed["LIQUIDATION_AGGREGATES"] = agg_parsed
        except Exception as exc:
            agg_error = f"{type(exc).__name__}: {exc}"
            agg_quality = "STALE" if isinstance(exc, StaleData) else "INVALID"
            blocked.append(f"LIQUIDATION_AGGREGATES_{agg_quality}")
    evidence.append(
        _evidence_envelope(
            agg_spec,
            agg_fetch,
            registry_hash=registry.hash,
            parsed=agg_parsed,
            quality_state=agg_quality,
            quality_error=agg_error,
        )
    )

    handled_families = set(critical_families) | {
        "LIQUIDATION_CONNECTIVITY_PROBE",
        "LIQUIDATION_AGGREGATES",
    }
    for source_row in registry.payload["sources"]:
        family = str(source_row["input_family"])
        if family in handled_families:
            continue
        spec = registry.by_input_family(family)
        if fetch_overrides is not None:
            fetched = overrides.get(spec.source_id) or FetchResult(
                spec.source_id, "MISSING", error="explicit offline override missing"
            )
        else:
            fetched = _http_get(spec)
        parsed_value: dict[str, Any] | None = None
        quality_state = "INVALID"
        quality_error: str | None = None
        if fetched.status != "OK":
            quality_state = "TRANSPORT_ERROR"
            quality_error = fetched.error
        else:
            try:
                parser = PARSERS.get(spec.parser_id)
                if parser is None:
                    raise ContractViolation(f"unsupported parser_id: {spec.parser_id}")
                parsed_value = parser(fetched.payload)
                _assert_fresh(parsed_value["as_of_ms"], now_ms=now, max_age_seconds=spec.max_age_seconds)
                quality_state = "VALID_FRESH"
                parsed[family] = parsed_value
            except Exception as exc:
                quality_error = f"{type(exc).__name__}: {exc}"
                quality_state = "STALE" if isinstance(exc, StaleData) else "INVALID"
        if spec.criticality == "CRITICAL_FAIL_CLOSED" and quality_state != "VALID_FRESH":
            blocked.append(f"{family}_{quality_state}")
        evidence.append(
            _evidence_envelope(
                spec,
                fetched,
                registry_hash=registry.hash,
                parsed=parsed_value,
                quality_state=quality_state,
                quality_error=quality_error,
            )
        )

    _derive_cross_family_metrics(parsed)

    idempotency_material = {
        "registry_hash": registry.hash,
        "evidence_hashes": sorted(item["evidence_hash"] for item in evidence),
    }
    result = {
        "run_id": run_id,
        "idempotency_key": sha256_hex(canonical_json_bytes(idempotency_material)),
        "as_of_ms": now,
        "formal_parent": registry.payload["formal_parent"],
        "architecture_target": registry.payload.get("architecture_target", []),
        "source_registry_id": registry.payload["registry_id"],
        "source_registry_hash": registry.hash,
        "safety_component_version": "CRT-RADAR-SOURCE-GATE-V0.8-WIP",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "evidence": evidence,
        "parsed": parsed,
        "action_output": "NONE",
    }
    if blocked:
        result.update({"formal_state": "BLOCKED", "blocked_reasons": sorted(set(blocked))})
    else:
        result.update({"formal_state": "OBSERVATION_ONLY", "blocked_reasons": []})
    return result


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"


def default_liquidation_snapshot_path() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime" / "snapshots" / "latest.json"


def main() -> int:
    registry = SourceRegistry.load(default_registry_path())
    aggregate_payload = None
    snapshot_path = default_liquidation_snapshot_path()
    if snapshot_path.exists():
        try:
            aggregate_payload = load_verified_snapshot(snapshot_path)
        except SnapshotCorruption:
            aggregate_payload = None
    result = run_source_gate(
        registry,
        liquidation_aggregate_payload=aggregate_payload,
        probe_fetcher=probe_liquidation_stream,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["formal_state"] in {"BLOCKED", "OBSERVATION_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
