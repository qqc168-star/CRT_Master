#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
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
    if not spec.endpoint:
        return FetchResult(spec.source_id, "ERROR", error="endpoint missing")
    request = urllib.request.Request(
        spec.endpoint,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"},
    )
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            if spec.transport == "HTTPS_CSV":
                payload: Any = raw.decode("utf-8-sig")
            else:
                payload = json.loads(raw.decode("utf-8"))
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


def parse_oi(payload: Any) -> dict[str, Any]:
    row = _require_mapping(payload, "OI payload")
    if row.get("symbol") != "BTCUSDT":
        raise ContractViolation("OI symbol must be BTCUSDT")
    return {
        "as_of_ms": _timestamp_ms(row.get("time"), "time"),
        "symbol": "BTCUSDT",
        "open_interest_contracts": _finite(row.get("openInterest"), "openInterest", positive=True),
    }


def parse_funding(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ContractViolation("Funding payload must be non-empty list")
    row = _require_mapping(payload[-1], "Funding observation")
    if row.get("symbol") != "BTCUSDT":
        raise ContractViolation("Funding symbol must be BTCUSDT")
    return {
        "as_of_ms": _timestamp_ms(row.get("fundingTime"), "fundingTime"),
        "symbol": "BTCUSDT",
        "funding_rate": _finite(row.get("fundingRate"), "fundingRate"),
        "mark_price": _finite(row.get("markPrice"), "markPrice", positive=True),
    }


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
        if raw.get("CapMrktCurUSD") in {None, ""} or raw.get("CapRealUSD") in {None, ""}:
            continue
        as_of_ms = _iso8601_ms(raw.get("time"), "time")
        candidates.append((as_of_ms, raw))
    if not candidates:
        raise ContractViolation("No complete BTC CapMrktCurUSD/CapRealUSD observation")
    as_of_ms, latest = max(candidates, key=lambda item: item[0])
    market_cap = _finite(latest.get("CapMrktCurUSD"), "CapMrktCurUSD", positive=True)
    realized_cap = _finite(latest.get("CapRealUSD"), "CapRealUSD", positive=True)
    mvrv = market_cap / realized_cap
    nupl = (market_cap - realized_cap) / market_cap
    return {
        "as_of_ms": as_of_ms,
        "asset": "btc",
        "market_cap_usd": market_cap,
        "realized_cap_usd": realized_cap,
        "mvrv": mvrv,
        "nupl": nupl,
        "formula_contract": {
            "mvrv": "CapMrktCurUSD / CapRealUSD",
            "nupl": "(CapMrktCurUSD - CapRealUSD) / CapMrktCurUSD",
        },
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
    "COINMETRICS_CAPS_V1": parse_coinmetrics_caps,
}


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
