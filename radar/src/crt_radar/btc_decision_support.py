from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import fmean
from typing import Any, Callable

from .btc_transition_research_eval import evaluate_control_transfer_evidence

SCHEMA_VERSION = "CRT_BTC_ENTRY_GATE_V0.2"
CONTEXT_SCHEMA_VERSION = "CRT_BTC_ENTRY_GATE_RESEARCH_CONTEXT_V0.1"
USER_AGENT = "CRT-Radar/BTC-entry-gate research-only read-only"
SPOT_KLINES = "https://data-api.binance.vision/api/v3/klines"


class BtcEntryGateError(ValueError):
    pass


def default_btc_entry_gate_context_path() -> Path:
    return Path.home() / "CRT_Runtime" / "private" / "btc_entry_gate_research.json"


def _finite(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise BtcEntryGateError(f"{field} missing")
    number = float(value)
    if not math.isfinite(number):
        raise BtcEntryGateError(f"{field} not finite")
    return number


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "BLOCKED",
        "reason": reason,
        "transition_state": "TRANSITION_UNRESOLVED",
        "decision_eligibility": "WAIT",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_output_trade_action": False,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
    }


def blocked_btc_entry_gate(reason: str) -> dict[str, Any]:
    return _blocked(reason)


def load_btc_entry_gate_context(
    path: str | Path | None = None,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    target = default_btc_entry_gate_context_path() if path is None else Path(path)
    if not target.exists():
        return {
            "state": "BLOCKED",
            "reason": "BTC_ENTRY_GATE_RESEARCH_CONTEXT_MISSING",
            "path": str(target),
        }
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "state": "BLOCKED",
            "reason": f"BTC_ENTRY_GATE_RESEARCH_CONTEXT_INVALID:{type(exc).__name__}",
            "path": str(target),
        }
    if not isinstance(payload, dict):
        return {"state": "BLOCKED", "reason": "BTC_ENTRY_GATE_RESEARCH_CONTEXT_NOT_OBJECT", "path": str(target)}
    if payload.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        return {"state": "BLOCKED", "reason": "BTC_ENTRY_GATE_RESEARCH_CONTEXT_SCHEMA_MISMATCH", "path": str(target)}
    if payload.get("formal_threshold_authority") != "NONE":
        return {"state": "BLOCKED", "reason": "BTC_ENTRY_GATE_FORMAL_THRESHOLD_AUTHORITY_MUST_BE_NONE", "path": str(target)}
    if payload.get("external_action_authority") != "NONE":
        return {"state": "BLOCKED", "reason": "BTC_ENTRY_GATE_EXTERNAL_ACTION_AUTHORITY_MUST_BE_NONE", "path": str(target)}
    lower = _finite(payload.get("lower_usd"), "lower_usd")
    upper = _finite(payload.get("upper_usd"), "upper_usd")
    if lower <= 0 or upper <= lower:
        return {"state": "BLOCKED", "reason": "BTC_ENTRY_GATE_RESEARCH_CORRIDOR_INVALID", "path": str(target)}
    valid_until_ms = int(_finite(payload.get("valid_until_ms"), "valid_until_ms"))
    as_of_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if as_of_ms > valid_until_ms:
        return {"state": "BLOCKED", "reason": "BTC_ENTRY_GATE_RESEARCH_CONTEXT_EXPIRED", "path": str(target)}
    return {
        "state": "AVAILABLE",
        "path": str(target),
        "context": payload,
    }


def _http_json(url: str, *, timeout: float = 15.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_klines(
    *,
    interval: str,
    limit: int,
    end_time_ms: int,
    http_json: Callable[[str], Any],
) -> Any:
    params = urllib.parse.urlencode(
        {"symbol": "BTCUSDT", "interval": interval, "limit": int(limit), "endTime": int(end_time_ms)}
    )
    return http_json(f"{SPOT_KLINES}?{params}")


def fetch_live_btc_market_structure(
    *,
    now_ms: int | None = None,
    http_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    getter = _http_json if http_json is None else http_json
    as_of_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return {
        "schema_version": "CRT_BTC_MARKET_STRUCTURE_INPUT_V0.1",
        "as_of_ms": as_of_ms,
        "authority": {
            "formal_metric_authority": "NONE",
            "formal_threshold_authority": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
        },
        "provenance": {
            "provider": "Binance Spot Public Market Data",
            "scope": "RESEARCH_ONLY_PRICE_STRUCTURE",
            "symbol": "BTCUSDT",
        },
        "klines_1h": _get_klines(interval="1h", limit=12, end_time_ms=as_of_ms, http_json=getter),
        "klines_4h": _get_klines(interval="4h", limit=12, end_time_ms=as_of_ms, http_json=getter),
        "klines_1d": _get_klines(interval="1d", limit=205, end_time_ms=as_of_ms, http_json=getter),
    }


def _close(row: Any, field: str) -> float:
    if not isinstance(row, list) or len(row) < 7:
        raise BtcEntryGateError(f"{field} malformed")
    return _finite(row[4], f"{field}.close")


def _close_time(row: Any, field: str) -> int:
    if not isinstance(row, list) or len(row) < 7:
        raise BtcEntryGateError(f"{field} malformed")
    return int(_finite(row[6], f"{field}.close_time"))


def _latest_closed(rows: Any, *, now_ms: int, field: str) -> list[Any]:
    if not isinstance(rows, list):
        raise BtcEntryGateError(f"{field} missing")
    closed = [row for row in rows if _close_time(row, field) <= now_ms]
    if not closed:
        raise BtcEntryGateError(f"{field} has no closed candle")
    return max(closed, key=lambda row: _close_time(row, field))


def summarize_btc_market_structure(bundle: dict[str, Any]) -> dict[str, Any]:
    as_of_ms = int(_finite(bundle.get("as_of_ms"), "as_of_ms"))
    one_hour = bundle.get("klines_1h")
    four_hour = bundle.get("klines_4h")
    daily = bundle.get("klines_1d")
    if not isinstance(one_hour, list) or not one_hour:
        raise BtcEntryGateError("klines_1h missing")
    if not isinstance(four_hour, list) or not four_hour:
        raise BtcEntryGateError("klines_4h missing")
    if not isinstance(daily, list):
        raise BtcEntryGateError("klines_1d missing")

    current_price = _close(one_hour[-1], "klines_1h.latest")
    close_1h = _close(_latest_closed(one_hour, now_ms=as_of_ms, field="klines_1h"), "klines_1h.closed")
    close_4h = _close(_latest_closed(four_hour, now_ms=as_of_ms, field="klines_4h"), "klines_4h.closed")

    closed_daily = [row for row in daily if _close_time(row, "klines_1d") <= as_of_ms]
    if len(closed_daily) < 200:
        raise BtcEntryGateError("fewer than 200 closed daily candles")
    closes = [_close(row, "klines_1d") for row in closed_daily]
    sma200_closed = fmean(closes[-200:])
    provisional_sma200 = fmean(closes[-199:] + [current_price])
    last_daily_close = closes[-1]

    return {
        "as_of_ms": as_of_ms,
        "current_price_usd": current_price,
        "last_closed_1h_usd": close_1h,
        "last_closed_4h_usd": close_4h,
        "last_closed_daily_usd": last_daily_close,
        "sma200_closed_usd": sma200_closed,
        "sma200_provisional_usd": provisional_sma200,
        "current_vs_sma200_provisional_pct": ((current_price / provisional_sma200) - 1.0) * 100.0,
        "daily_close_vs_sma200_closed_pct": ((last_daily_close / sma200_closed) - 1.0) * 100.0,
    }


def build_signal_role_classification(
    transition_diagnostic: dict[str, Any] | None,
    structure: dict[str, Any] | None,
) -> dict[str, Any]:
    mechanism = {}
    if isinstance(transition_diagnostic, dict):
        maybe = transition_diagnostic.get("mechanism_findings")
        if isinstance(maybe, dict):
            mechanism = maybe
    structure = structure or {}
    return {
        "schema_version": "CRT_BTC_SIGNAL_ROLE_CLASSIFICATION_V0.1",
        "authority": {
            "formal_model_authority": "NONE",
            "formal_weight_authority": "NONE",
            "external_action_authority": "NONE",
        },
        "roles": [
            {
                "signal": "macro_rates_liquidity_context",
                "timing_role": "LEADING",
                "decision_role": "WARNING",
                "state": "NOT_IN_CURRENT_ENTRY_GATE_SLICE",
            },
            {
                "signal": "short_squeeze",
                "timing_role": "COINCIDENT",
                "decision_role": "DIAGNOSTIC",
                "state": mechanism.get("short_squeeze", "UNAVAILABLE"),
            },
            {
                "signal": "long_fomo_rebuild",
                "timing_role": "COINCIDENT",
                "decision_role": "DIAGNOSTIC",
                "state": mechanism.get("long_fomo_rebuild", "UNAVAILABLE"),
            },
            {
                "signal": "spot_demand_absorption",
                "timing_role": "COINCIDENT",
                "decision_role": "ENTRY_SUPPORT",
                "state": mechanism.get("spot_demand_absorption", "UNAVAILABLE"),
            },
            {
                "signal": "spot_demand_persistence",
                "timing_role": "COINCIDENT",
                "decision_role": "ENTRY_SUPPORT",
                "state": mechanism.get("spot_demand_persistence", "UNAVAILABLE"),
            },
            {
                "signal": "leverage_quality",
                "timing_role": "COINCIDENT",
                "decision_role": "ENTRY_SUPPORT",
                "state": mechanism.get("leverage_quality", "UNAVAILABLE"),
            },
            {
                "signal": "sma200_reclaim",
                "timing_role": "LAGGING",
                "decision_role": "CONFIRMATION",
                "state": (
                    "ABOVE_PROVISIONAL_SMA200"
                    if structure.get("current_vs_sma200_provisional_pct") is not None
                    and float(structure["current_vs_sma200_provisional_pct"]) >= 0
                    else "BELOW_PROVISIONAL_SMA200"
                    if structure.get("current_vs_sma200_provisional_pct") is not None
                    else "UNAVAILABLE"
                ),
            },
            {
                "signal": "transition_corridor_acceptance_rejection",
                "timing_role": "COINCIDENT",
                "decision_role": "ENTRY_GATE",
                "state": "EVALUATED_SEPARATELY",
            },
            {
                "signal": "major_swing_structure_break",
                "timing_role": "LAGGING",
                "decision_role": "CONFIRMATION",
                "state": "NOT_IN_CURRENT_ENTRY_GATE_SLICE",
            },
        ],
    }


def evaluate_btc_entry_gate(
    *,
    transition_diagnostic: dict[str, Any] | None,
    structure: dict[str, Any],
    research_context: dict[str, Any],
    control_transfer_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = research_context.get("context") if research_context.get("state") == "AVAILABLE" else None
    if not isinstance(context, dict):
        return _blocked(str(research_context.get("reason", "BTC_ENTRY_GATE_RESEARCH_CONTEXT_UNAVAILABLE")))

    lower = _finite(context.get("lower_usd"), "lower_usd")
    upper = _finite(context.get("upper_usd"), "upper_usd")
    current = _finite(structure.get("current_price_usd"), "current_price_usd")
    close_1h = _finite(structure.get("last_closed_1h_usd"), "last_closed_1h_usd")
    close_4h = _finite(structure.get("last_closed_4h_usd"), "last_closed_4h_usd")
    current_vs_sma = _finite(structure.get("current_vs_sma200_provisional_pct"), "current_vs_sma200_provisional_pct")
    daily_vs_sma = _finite(structure.get("daily_close_vs_sma200_closed_pct"), "daily_close_vs_sma200_closed_pct")

    mechanism = {}
    if isinstance(transition_diagnostic, dict):
        maybe = transition_diagnostic.get("mechanism_findings")
        if isinstance(maybe, dict):
            mechanism = maybe

    accepted_lower = current >= lower and close_1h >= lower and close_4h >= lower
    accepted_upper = current >= upper and close_1h >= upper and close_4h >= upper
    rejected_lower = current < lower and close_1h < lower and close_4h < lower
    provisional_reclaim = current_vs_sma >= 0
    closed_daily_reclaim = daily_vs_sma >= 0

    absorption = mechanism.get("spot_demand_absorption")
    persistence = mechanism.get("spot_demand_persistence")
    leverage = mechanism.get("leverage_quality")
    long_fomo = mechanism.get("long_fomo_rebuild")
    mechanism_ready = bool(mechanism)
    constructive_mechanism = (
        absorption == "SUPPORTED"
        and leverage == "CONSTRUCTIVE"
        and long_fomo != "SUPPORTED"
    )
    adverse_mechanism = absorption == "NOT_SUPPORTED" or leverage == "CAUTION"
    control_transfer = evaluate_control_transfer_evidence(
        control_transfer_evidence
    )
    control_transfer_loop_closed = bool(
        control_transfer.get("control_transfer_loop_closed")
    )

    transition_state = "TRANSITION_UNRESOLVED"
    decision_eligibility = "WAIT"
    reason = "CORRIDOR_OR_MECHANISM_NOT_YET_DECISIVE"

    if accepted_upper and provisional_reclaim and constructive_mechanism:
        if control_transfer_loop_closed:
            transition_state = "BULL_ACCEPTANCE_STRENGTHENED"
            decision_eligibility = "PROBE_ELIGIBLE"
            reason = "UPPER_CORRIDOR_ACCEPTED_WITH_CLOSED_CONTROL_TRANSFER_LOOP"
        else:
            transition_state = "BULL_ACCEPTANCE_DEVELOPING"
            decision_eligibility = "WATCH"
            reason = (
                "UPPER_CORRIDOR_ATTACK_SUPPORTED_BUT_"
                "CONTROL_TRANSFER_LOOP_NOT_CLOSED"
            )
    elif accepted_lower and provisional_reclaim and constructive_mechanism:
        transition_state = "BULL_ACCEPTANCE_DEVELOPING"
        decision_eligibility = "WATCH"
        reason = "LOWER_CORRIDOR_ACCEPTED_WITH_CONSTRUCTIVE_MECHANISM"
    elif rejected_lower and adverse_mechanism:
        transition_state = "BEAR_REJECTION_STRENGTHENED"
        decision_eligibility = "WAIT"
        reason = "LOWER_CORRIDOR_REJECTED_WITH_ADVERSE_MECHANISM"
    elif rejected_lower:
        transition_state = "BEAR_REJECTION_PLAUSIBLE"
        reason = "LOWER_CORRIDOR_REJECTED_MECHANISM_INCOMPLETE"

    if not mechanism_ready and transition_state.startswith("BULL_"):
        transition_state = "TRANSITION_UNRESOLVED"
        decision_eligibility = "WAIT"
        reason = "PRICE_STRUCTURE_SUPPORTIVE_BUT_MECHANISM_NOT_AVAILABLE"

    return {
        "schema_version": SCHEMA_VERSION,
        "state": "READY_FOR_ANALYST",
        "reason": reason,
        "transition_state": transition_state,
        "decision_eligibility": decision_eligibility,
        "research_corridor": {
            "lower_usd": lower,
            "upper_usd": upper,
            "formal_threshold_authority": "NONE",
            "valid_until_ms": context.get("valid_until_ms"),
        },
        "quantitative": {
            **structure,
            "distance_to_lower_pct": ((current / lower) - 1.0) * 100.0,
            "distance_to_upper_pct": ((current / upper) - 1.0) * 100.0,
            "accepted_lower_by_price_closes": accepted_lower,
            "accepted_upper_by_price_closes": accepted_upper,
            "rejected_lower_by_price_closes": rejected_lower,
            "provisional_sma200_reclaim": provisional_reclaim,
            "closed_daily_sma200_reclaim": closed_daily_reclaim,
        },
        "mechanism_support": {
            "available": mechanism_ready,
            "spot_demand_absorption": absorption,
            "spot_demand_persistence": persistence,
            "leverage_quality": leverage,
            "long_fomo_rebuild": long_fomo,
            "constructive": constructive_mechanism,
            "adverse": adverse_mechanism,
        },
        "control_transfer_validation": control_transfer,
        "signal_roles": build_signal_role_classification(transition_diagnostic, structure),
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_output_trade_action": False,
        "machine_may_confirm_bull_transition": False,
        "analyst_judgment_required": True,
    }


def run_live_btc_entry_gate(
    *,
    transition_diagnostic: dict[str, Any] | None,
    research_context: dict[str, Any],
    control_transfer_evidence: dict[str, Any] | None = None,
    now_ms: int | None = None,
    http_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if research_context.get("state") != "AVAILABLE":
        return _blocked(str(research_context.get("reason", "BTC_ENTRY_GATE_RESEARCH_CONTEXT_UNAVAILABLE")))
    try:
        bundle = fetch_live_btc_market_structure(now_ms=now_ms, http_json=http_json)
        structure = summarize_btc_market_structure(bundle)
        return evaluate_btc_entry_gate(
            transition_diagnostic=transition_diagnostic,
            structure=structure,
            research_context=research_context,
            control_transfer_evidence=control_transfer_evidence,
        )
    except Exception as exc:
        return _blocked(f"BTC_ENTRY_GATE_INPUT_OR_RECONSTRUCTION_FAILED:{type(exc).__name__}:{exc}")
