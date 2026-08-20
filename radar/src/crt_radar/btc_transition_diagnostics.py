from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from statistics import fmean
from typing import Any, Callable

USER_AGENT = "CRT-Radar/P3-03 diagnostic-only read-only"
SPOT_KLINES = "https://data-api.binance.vision/api/v3/klines"
OI_HISTORY = "https://fapi.binance.com/futures/data/openInterestHist"
PREMIUM_KLINES = "https://fapi.binance.com/fapi/v1/premiumIndexKlines"
FUNDING_HISTORY = "https://fapi.binance.com/fapi/v1/fundingRate"


class TransitionDiagnosticError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise TransitionDiagnosticError(f"{field} missing")
    number = float(value)
    if not math.isfinite(number):
        raise TransitionDiagnosticError(f"{field} not finite")
    return number


def _http_json(url: str, *, timeout: float = 15.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(
    base_url: str,
    params: dict[str, Any],
    *,
    http_json: Callable[[str], Any],
) -> Any:
    return http_json(f"{base_url}?{urllib.parse.urlencode(params)}")


def fetch_live_transition_bundle(
    *,
    now_ms: int | None = None,
    lookback_minutes: int = 180,
    http_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Fetch diagnostic-only read-only BTC event data.

    These endpoints do not change any formal CRT metric, score, threshold,
    season, asset role, capital strategy, or external action authority.
    """

    getter = _http_json if http_json is None else http_json
    as_of_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    start_ms = as_of_ms - int(lookback_minutes) * 60_000
    common = {
        "symbol": "BTCUSDT",
        "startTime": start_ms,
        "endTime": as_of_ms,
        "limit": 100,
    }
    return {
        "schema_version": "CRT_BTC_TRANSITION_DIAGNOSTIC_INPUT_V0.1",
        "authority": {
            "formal_metric_authority": "NONE",
            "investment_threshold_authority": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
        },
        "as_of_ms": as_of_ms,
        "provenance": {
            "spot_klines_5m": {
                "provider": "Binance Spot Public Market Data",
                "scope": "DIAGNOSTIC_EXTENSION",
                "formal_metric_authority": "NONE",
            },
            "oi_history_5m": {
                "provider": "Binance USD-M Futures",
                "scope": "DIAGNOSTIC_EXTENSION_OF_OPEN_INTEREST_NOTIONAL",
                "formal_metric_authority": "NONE",
            },
            "premium_klines_5m": {
                "provider": "Binance USD-M Futures",
                "scope": "DIAGNOSTIC_ONLY",
                "formal_metric_authority": "NONE",
            },
            "funding_history": {
                "provider": "Binance USD-M Futures",
                "scope": "DIAGNOSTIC_EXTENSION_OF_FUNDING_RATE",
                "formal_metric_authority": "NONE",
            },
        },
        "spot_klines_5m": _get(
            SPOT_KLINES,
            {**common, "interval": "5m"},
            http_json=getter,
        ),
        "oi_history_5m": _get(
            OI_HISTORY,
            {**common, "period": "5m"},
            http_json=getter,
        ),
        "premium_klines_5m": _get(
            PREMIUM_KLINES,
            {**common, "interval": "5m"},
            http_json=getter,
        ),
        "funding_history": _get(
            FUNDING_HISTORY,
            {
                "symbol": "BTCUSDT",
                "startTime": as_of_ms - 24 * 60 * 60_000,
                "endTime": as_of_ms,
                "limit": 100,
            },
            http_json=getter,
        ),
    }


def _normalize_rows(bundle: dict[str, Any]) -> list[dict[str, float]]:
    spot = bundle.get("spot_klines_5m")
    oi = bundle.get("oi_history_5m")
    premium = bundle.get("premium_klines_5m")
    if not isinstance(spot, list) or not isinstance(oi, list) or not isinstance(premium, list):
        raise TransitionDiagnosticError("5m diagnostic rows missing")

    spot_by: dict[int, list[Any]] = {}
    for row in spot:
        if isinstance(row, list) and len(row) > 10:
            spot_by[int(row[0])] = row

    oi_by: dict[int, dict[str, Any]] = {}
    for row in oi:
        if isinstance(row, dict) and row.get("timestamp") is not None:
            oi_by[int(row["timestamp"])] = row

    premium_by: dict[int, list[Any]] = {}
    for row in premium:
        if isinstance(row, list) and len(row) > 4:
            premium_by[int(row[0])] = row

    rows: list[dict[str, float]] = []
    for timestamp in sorted(set(spot_by) & set(oi_by) & set(premium_by)):
        s = spot_by[timestamp]
        o = oi_by[timestamp]
        p = premium_by[timestamp]
        quote_volume = _finite(s[7], "spot.quote_volume")
        taker_buy_quote = _finite(s[10], "spot.taker_buy_quote")
        rows.append(
            {
                "timestamp_ms": float(timestamp),
                "open": _finite(s[1], "spot.open"),
                "close": _finite(s[4], "spot.close"),
                "quote_volume": quote_volume,
                "taker_buy_quote": taker_buy_quote,
                "oi_btc": _finite(o.get("sumOpenInterest"), "oi.sumOpenInterest"),
                "premium_close": _finite(p[4], "premium.close"),
            }
        )
    if len(rows) < 6:
        raise TransitionDiagnosticError("insufficient aligned 5m rows")
    return rows


def _summary(rows: list[dict[str, float]]) -> dict[str, Any]:
    if len(rows) < 2:
        raise TransitionDiagnosticError("summary requires at least two rows")
    quote_volume = sum(row["quote_volume"] for row in rows)
    taker_buy_quote = sum(row["taker_buy_quote"] for row in rows)
    first_oi = rows[0]["oi_btc"]
    last_oi = rows[-1]["oi_btc"]
    first_price = rows[0]["open"]
    last_price = rows[-1]["close"]
    return {
        "bars": len(rows),
        "start_ms": int(rows[0]["timestamp_ms"]),
        "end_ms": int(rows[-1]["timestamp_ms"]),
        "price_change_pct": ((last_price / first_price) - 1.0) * 100.0,
        "oi_change_pct": ((last_oi / first_oi) - 1.0) * 100.0 if first_oi else None,
        "premium_mean_bp": fmean(row["premium_close"] for row in rows) * 10_000.0,
        "spot_buy_share_pct": (taker_buy_quote / quote_volume) * 100.0 if quote_volume else None,
        "spot_cvd_proxy_usd": 2.0 * taker_buy_quote - quote_volume,
    }


def summarize_transition_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    rows = _normalize_rows(bundle)
    recent = rows[-12:] if len(rows) >= 12 else rows
    prior = rows[-24:-12] if len(rows) >= 24 else []
    recent_30 = recent[-6:] if len(recent) >= 6 else recent
    prior_30 = recent[-12:-6] if len(recent) >= 12 else []

    strongest_index = 0
    strongest_return = -math.inf
    for index, row in enumerate(rows):
        change = ((row["close"] / row["open"]) - 1.0) * 100.0
        if change > strongest_return:
            strongest_return = change
            strongest_index = index
    impulse = rows[max(0, strongest_index - 1) : min(len(rows), strongest_index + 2)]
    if len(impulse) < 2:
        impulse = rows[max(0, strongest_index - 1) : strongest_index + 1]

    result: dict[str, Any] = {
        "recent_60m": _summary(recent),
        "impulse_window": _summary(impulse),
    }
    if prior:
        result["prior_60m"] = _summary(prior)
    if recent_30:
        result["recent_30m"] = _summary(recent_30)
    if prior_30:
        result["prior_30m"] = _summary(prior_30)
    return result


def _latest_funding_bp(bundle: dict[str, Any]) -> float | None:
    rows = bundle.get("funding_history")
    if not isinstance(rows, list) or not rows:
        return None
    valid = [row for row in rows if isinstance(row, dict) and row.get("fundingRate") is not None]
    if not valid:
        return None
    latest = max(valid, key=lambda row: int(row.get("fundingTime", 0)))
    return _finite(latest["fundingRate"], "fundingRate") * 10_000.0


def _liquidation_context(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {
            "state": "UNAVAILABLE",
            "time_resolution": None,
            "short_liquidation_usd": None,
            "long_liquidation_usd": None,
            "short_share_pct": None,
        }
    windows = snapshot.get("windows")
    one_hour = windows.get("1h") if isinstance(windows, dict) else None
    if not isinstance(one_hour, dict):
        return {
            "state": "UNAVAILABLE",
            "time_resolution": None,
            "short_liquidation_usd": None,
            "long_liquidation_usd": None,
            "short_share_pct": None,
        }
    short_usd = float(one_hour.get("short_liquidation_usd", 0.0) or 0.0)
    long_usd = float(one_hour.get("long_liquidation_usd", 0.0) or 0.0)
    total = short_usd + long_usd
    quality = str(snapshot.get("quality_state", ""))
    return {
        "state": "VALID" if quality.startswith("VALID") else "BLOCKED",
        "time_resolution": "ROLLING_1H",
        "short_liquidation_usd": short_usd,
        "long_liquidation_usd": long_usd,
        "short_share_pct": (short_usd / total) * 100.0 if total else None,
    }


def evaluate_transition_mechanisms(
    summaries: dict[str, Any],
    *,
    funding_latest_bp: float | None,
    liquidation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate mechanism evidence only; never confirm a bull market or trade action."""

    recent = summaries.get("recent_60m") or {}
    impulse = summaries.get("impulse_window") or {}
    recent_30 = summaries.get("recent_30m") or {}
    prior_30 = summaries.get("prior_30m") or {}
    liq = liquidation_context or {}

    impulse_oi = impulse.get("oi_change_pct")
    short_usd = liq.get("short_liquidation_usd")
    long_usd = liq.get("long_liquidation_usd")
    liq_valid = liq.get("state") == "VALID"
    if (
        impulse_oi is not None
        and impulse_oi < 0
        and liq_valid
        and short_usd is not None
        and long_usd is not None
        and short_usd > long_usd
    ):
        squeeze = "SUPPORTED"
    elif impulse_oi is not None and impulse_oi < 0:
        squeeze = "PLAUSIBLE"
    else:
        squeeze = "NOT_SUPPORTED"

    oi_change = recent.get("oi_change_pct")
    premium_mean = recent.get("premium_mean_bp")
    if (
        oi_change is not None
        and premium_mean is not None
        and funding_latest_bp is not None
        and oi_change > 0
        and premium_mean > 0
        and funding_latest_bp > 0
    ):
        long_fomo = "SUPPORTED"
    elif (
        oi_change is not None
        and premium_mean is not None
        and funding_latest_bp is not None
        and oi_change > 0
        and premium_mean <= 0
        and funding_latest_bp <= 0
    ):
        long_fomo = "NOT_SUPPORTED"
    else:
        long_fomo = "INCONCLUSIVE"

    buy_share = recent.get("spot_buy_share_pct")
    cvd = recent.get("spot_cvd_proxy_usd")
    if (
        oi_change is not None
        and premium_mean is not None
        and buy_share is not None
        and cvd is not None
        and oi_change > 0
        and premium_mean <= 0
        and buy_share > 50.0
        and cvd > 0
    ):
        absorption = "SUPPORTED"
    elif cvd is not None and cvd <= 0:
        absorption = "NOT_SUPPORTED"
    else:
        absorption = "INCONCLUSIVE"

    persistence = "NOT_YET_CONFIRMED"
    if prior_30 and recent_30:
        first_buy = prior_30.get("spot_buy_share_pct")
        first_cvd = prior_30.get("spot_cvd_proxy_usd")
        second_buy = recent_30.get("spot_buy_share_pct")
        second_cvd = recent_30.get("spot_cvd_proxy_usd")
        if (
            first_buy is not None
            and first_cvd is not None
            and second_buy is not None
            and second_cvd is not None
            and first_buy > 50.0
            and first_cvd > 0
            and second_buy > 50.0
            and second_cvd > 0
        ):
            persistence = "SUPPORTED"

    if long_fomo == "NOT_SUPPORTED" and absorption == "SUPPORTED":
        leverage_quality = "CONSTRUCTIVE"
    elif long_fomo == "SUPPORTED":
        leverage_quality = "CAUTION"
    else:
        leverage_quality = "MIXED"

    return {
        "short_squeeze": squeeze,
        "long_fomo_rebuild": long_fomo,
        "spot_demand_absorption": absorption,
        "spot_demand_persistence": persistence,
        "leverage_quality": leverage_quality,
        "machine_regime_judgment": None,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
    }


def not_requested_transition_diagnostic(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "CRT_BTC_TRANSITION_DIAGNOSTIC_V0.1",
        "state": "NOT_REQUESTED",
        "reason": reason,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_regime_judgment": None,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": False,
    }


def blocked_transition_diagnostic(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "CRT_BTC_TRANSITION_DIAGNOSTIC_V0.1",
        "state": "BLOCKED",
        "reason": reason,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_regime_judgment": None,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
    }


def build_transition_diagnostic_case(
    bundle: dict[str, Any],
    *,
    wake: dict[str, Any],
    liquidation_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    summaries = summarize_transition_bundle(bundle)
    funding_latest_bp = _latest_funding_bp(bundle)
    liquidation = _liquidation_context(liquidation_snapshot)
    mechanisms = evaluate_transition_mechanisms(
        summaries,
        funding_latest_bp=funding_latest_bp,
        liquidation_context=liquidation,
    )
    return {
        "schema_version": "CRT_BTC_TRANSITION_DIAGNOSTIC_V0.1",
        "state": "READY_FOR_ANALYST",
        "reason": "MATERIAL_BTC_MOVE_DIAGNOSED",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "source_mode": "DIAGNOSTIC_ONLY_READ_ONLY",
        "formal_metric_authority": "NONE",
        "investment_threshold_authority": "NONE",
        "data_health": {
            "state": "VALID_DIAGNOSTIC",
            "scope": "BINANCE_BTCUSDT_DIRECTIONAL_EVENT_DIAGNOSTICS",
            "limitations": [
                "Single-venue directional evidence; not a total-market claim.",
                "Rolling 1h liquidation context is coarser than exact event-window liquidation evidence.",
                "This diagnostic does not alter formal six-layer inputs or locked thresholds.",
            ],
            "provenance": bundle.get("provenance", {}),
        },
        "wake": wake,
        "windows": summaries,
        "funding_latest_bp": funding_latest_bp,
        "liquidation_context": liquidation,
        "mechanism_findings": mechanisms,
        "gpt_handoff": {
            "questions": [
                "Which causal explanation best fits the event?",
                "What alternative explanations remain?",
                "What evidence would invalidate the current mechanism judgment?",
                "Does the BTC regime hypothesis materially strengthen or weaken?",
                "What strategy assumptions change, if any?",
            ],
            "machine_may_confirm_bull_transition": False,
            "machine_may_output_trade_action": False,
        },
    }


def run_live_btc_transition_diagnostics(
    *,
    wake: dict[str, Any],
    liquidation_snapshot: dict[str, Any] | None,
    now_ms: int | None = None,
    http_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if wake.get("state") != "REANALYSIS_REQUESTED":
        return not_requested_transition_diagnostic("REANALYSIS_WAKE_NOT_REQUESTED")
    try:
        bundle = fetch_live_transition_bundle(now_ms=now_ms, http_json=http_json)
        return build_transition_diagnostic_case(
            bundle,
            wake=wake,
            liquidation_snapshot=liquidation_snapshot,
        )
    except Exception as exc:
        return blocked_transition_diagnostic(
            f"DIAGNOSTIC_INPUT_OR_RECONSTRUCTION_FAILED:{type(exc).__name__}:{exc}"
        )
