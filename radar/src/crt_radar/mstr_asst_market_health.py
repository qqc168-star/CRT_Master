from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


SCHEMA_VERSION = "CRT_MSTR_ASST_MARKET_HEALTH_V0.1"
SUPPORTED_ASSETS = ("MSTR", "ASST")
WAKE_REASONS = {
    "FALSE_BREAKOUT_CONFIRMED",
    "FIRST_DEFENSE_BREACHED",
    "TACTICAL_INVALIDATION_BREACHED",
    "BTC_PER_DILUTED_SHARE_DECREASED",
}


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _authority() -> dict[str, Any]:
    return {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def _assert_authority(payload: dict[str, Any], label: str) -> None:
    expected = _authority()
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"{label} {key} must remain {value!r}")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _commander_lines(asset: str, raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError(f"{asset} commander lines must be an object")
    if raw.get("source") != "THREE_ARMY_COMMANDER":
        raise ValueError(f"{asset} lines must come from THREE_ARMY_COMMANDER")
    if raw.get("approval_state") != "APPROVED":
        raise ValueError(f"{asset} commander lines must be APPROVED")
    return {
        "attack_line": _number(raw.get("attack_line"), "attack_line"),
        "first_defense": _number(raw.get("first_defense"), "first_defense"),
        "invalidation_line": _number(
            raw.get("invalidation_line"),
            "invalidation_line",
        ),
    }


def _asset_health(
    asset: str,
    market: dict[str, Any],
    options: dict[str, Any],
    lines: dict[str, float],
    issuer: dict[str, Any],
) -> dict[str, Any]:
    if market.get("state") != "VALID":
        raise ValueError(f"{asset} full-day market intake must be VALID")
    latest = market.get("latest_complete_session")
    previous = market.get("previous_complete_session")
    if not isinstance(latest, dict) or not isinstance(previous, dict):
        raise ValueError(f"{asset} requires latest and previous complete sessions")

    close = _number(latest.get("close"), "latest close")
    high = _number(latest.get("high"), "latest high")
    rvol20_raw = market.get("rvol20")
    rvol20 = (
        _number(rvol20_raw, "rvol20") if rvol20_raw is not None else None
    )
    reasons: list[str] = []

    if (
        high >= lines["attack_line"]
        and close < lines["attack_line"]
        and rvol20 is not None
        and rvol20 > 1.0
    ):
        reasons.append("FALSE_BREAKOUT_CONFIRMED")
    if close < lines["first_defense"]:
        reasons.append("FIRST_DEFENSE_BREACHED")
    if close < lines["invalidation_line"]:
        reasons.append("TACTICAL_INVALIDATION_BREACHED")

    if not isinstance(issuer, dict):
        raise ValueError(f"{asset} issuer BTC/share input must be an object")
    current_btc_share = _number(
        issuer.get("current_btc_per_diluted_share"),
        "current_btc_per_diluted_share",
    )
    previous_btc_share = _number(
        issuer.get("previous_btc_per_diluted_share"),
        "previous_btc_per_diluted_share",
    )
    if current_btc_share < previous_btc_share:
        reasons.append("BTC_PER_DILUTED_SHARE_DECREASED")

    relative = market.get("relative_btc")
    observations = {
        "relative_btc": deepcopy(relative) if isinstance(relative, dict) else None,
        "options": {
            "put_call_volume_ratio": options.get("aggregate_volume", {}).get(
                "put_call_volume_ratio"
            ),
            "covered_put_call_open_interest_ratio": options.get(
                "covered_open_interest", {}
            ).get("put_call_open_interest_ratio"),
            "top_call_oi_strikes": deepcopy(options.get("top_call_oi_strikes", [])),
            "top_put_oi_strikes": deepcopy(options.get("top_put_oi_strikes", [])),
            "wake_authority": "OBSERVATION_ONLY",
        },
    }

    return {
        "asset": asset,
        "state": "REANALYSIS_REQUESTED" if reasons else "NO_WAKE",
        "reanalysis_required": bool(reasons),
        "wake_reasons": reasons,
        "latest_complete_session": deepcopy(latest),
        "commander_lines": lines,
        "issuer_btc_per_diluted_share": {
            "current": current_btc_share,
            "previous": previous_btc_share,
        },
        "observations": observations,
    }


def validate_mstr_asst_market_health(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("mstr_asst_market_health must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("mstr_asst_market_health schema_version mismatch")
    _assert_authority(payload, "mstr_asst_market_health")
    assets = payload.get("assets")
    if not isinstance(assets, dict) or set(assets) != set(SUPPORTED_ASSETS):
        raise ValueError("mstr_asst_market_health must contain MSTR and ASST")
    expected_reasons: list[str] = []
    for asset in SUPPORTED_ASSETS:
        row = assets[asset]
        if not isinstance(row, dict):
            raise ValueError(f"{asset} market health must be an object")
        reasons = row.get("wake_reasons")
        if not isinstance(reasons, list) or any(reason not in WAKE_REASONS for reason in reasons):
            raise ValueError(f"{asset} wake_reasons are invalid")
        expected_reasons.extend(f"{asset}:{reason}" for reason in reasons)
        if row.get("reanalysis_required") is not bool(reasons):
            raise ValueError(f"{asset} reanalysis_required disagrees with reasons")
    if payload.get("wake_reasons") != expected_reasons:
        raise ValueError("market health aggregate wake_reasons mismatch")
    requested = bool(expected_reasons)
    expected_state = "REANALYSIS_REQUESTED" if requested else "NO_WAKE"
    if payload.get("state") != expected_state:
        raise ValueError("market health state disagrees with wake reasons")
    if payload.get("reanalysis_required") is not requested:
        raise ValueError("market health reanalysis_required mismatch")
    result = deepcopy(payload)
    supplied_hash = result.pop("market_health_hash", None)
    if supplied_hash != _canonical_hash(result):
        raise ValueError("market health hash mismatch")
    return deepcopy(payload)


def evaluate_mstr_asst_market_health(
    *,
    full_day_market_intake: dict[str, Any],
    options_daily_snapshot: dict[str, Any],
    commander_lines: dict[str, dict[str, Any]],
    issuer_btc_per_diluted_share: dict[str, dict[str, Any]],
    generated_at_ms: int,
) -> dict[str, Any]:
    for label, payload in (
        ("full_day_market_intake", full_day_market_intake),
        ("options_daily_snapshot", options_daily_snapshot),
    ):
        if not isinstance(payload, dict):
            raise ValueError(f"{label} must be an object")
        _assert_authority(payload, label)
    if not isinstance(commander_lines, dict) or set(commander_lines) != set(SUPPORTED_ASSETS):
        raise ValueError("commander_lines must contain exactly MSTR and ASST")
    if (
        not isinstance(issuer_btc_per_diluted_share, dict)
        or set(issuer_btc_per_diluted_share) != set(SUPPORTED_ASSETS)
    ):
        raise ValueError("issuer BTC/share must contain exactly MSTR and ASST")

    market_assets = full_day_market_intake.get("assets")
    option_assets = options_daily_snapshot.get("assets")
    if not isinstance(market_assets, dict) or not isinstance(option_assets, dict):
        raise ValueError("market and options inputs must contain assets")

    assets = {
        asset: _asset_health(
            asset,
            market_assets[asset],
            option_assets[asset],
            _commander_lines(asset, commander_lines[asset]),
            issuer_btc_per_diluted_share[asset],
        )
        for asset in SUPPORTED_ASSETS
    }
    reasons = [
        f"{asset}:{reason}"
        for asset in SUPPORTED_ASSETS
        for reason in assets[asset]["wake_reasons"]
    ]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": "REANALYSIS_REQUESTED" if reasons else "NO_WAKE",
        "reason": reasons[0] if reasons else "MARKET_HEALTH_STABLE",
        "reanalysis_required": bool(reasons),
        "generated_at_ms": generated_at_ms,
        "wake_reasons": reasons,
        "assets": assets,
        "observation_only_fields": [
            "RELATIVE_BTC",
            "PUT_CALL_CHANGE",
            "STRIKE_OPEN_INTEREST_CHANGE",
        ],
        "notification_authority": "GPT_JUDGMENT_REQUIRED",
        "commander_authority": "APPROVED_LINES_READ_ONLY",
        **_authority(),
    }
    result["market_health_hash"] = _canonical_hash(result)
    return validate_mstr_asst_market_health(result)
