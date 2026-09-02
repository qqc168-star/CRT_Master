from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


SCHEMA_VERSION = "CRT_MSTR_ASST_OPTIONS_DAILY_SNAPSHOT_V0.1"
SUPPORTED_ASSETS = ("MSTR", "ASST")


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


def _numeric(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator != 0 else None


def _asset_snapshot(asset: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{asset} options snapshot input must be an object")
    aggregate = raw.get("aggregate_volume")
    contracts = raw.get("contracts")
    coverage = raw.get("coverage")
    if not isinstance(aggregate, dict):
        raise ValueError(f"{asset} aggregate_volume must be an object")
    if not isinstance(contracts, list):
        raise ValueError(f"{asset} contracts must be a list")
    if not isinstance(coverage, dict):
        raise ValueError(f"{asset} coverage must be an object")

    call_volume = _numeric(aggregate.get("call_volume"), "call_volume")
    put_volume = _numeric(aggregate.get("put_volume"), "put_volume")
    normalized_contracts: list[dict[str, Any]] = []
    call_oi = 0.0
    put_oi = 0.0
    for row in contracts:
        if not isinstance(row, dict):
            raise ValueError(f"{asset} contract must be an object")
        right = str(row.get("right", "")).upper()
        if right not in {"CALL", "PUT"}:
            raise ValueError(f"{asset} contract right must be CALL or PUT")
        oi = _numeric(row.get("open_interest"), "open_interest")
        volume_state = str(row.get("volume_state", "UNKNOWN"))
        volume_raw = row.get("volume")
        if volume_raw is None:
            if not volume_state.startswith("BLOCKED"):
                raise ValueError(
                    f"{asset} missing contract volume must be explicitly BLOCKED"
                )
            volume = None
        else:
            volume = _numeric(volume_raw, "volume")
        normalized = {
            "expiry": str(row.get("expiry")),
            "strike": _numeric(row.get("strike"), "strike"),
            "right": right,
            "volume": volume,
            "open_interest": oi,
            "implied_volatility": _numeric(
                row.get("implied_volatility"),
                "implied_volatility",
            ),
            "volume_state": volume_state,
            "open_interest_state": str(
                row.get("open_interest_state", "UNKNOWN")
            ),
            "implied_volatility_state": str(
                row.get("implied_volatility_state", "UNKNOWN")
            ),
            "observed_at_ms": row.get("observed_at_ms"),
            "oi_effective_at": row.get("oi_effective_at"),
        }
        normalized_contracts.append(normalized)
        if right == "CALL":
            call_oi += oi
        else:
            put_oi += oi

    def top(right: str) -> list[dict[str, Any]]:
        rows = [row for row in normalized_contracts if row["right"] == right]
        rows.sort(key=lambda row: (-row["open_interest"], row["expiry"], row["strike"]))
        return [
            {
                "expiry": row["expiry"],
                "strike": row["strike"],
                "open_interest": row["open_interest"],
                "open_interest_state": row["open_interest_state"],
            }
            for row in rows[:5]
        ]

    coverage_state = str(coverage.get("state", "LIMITED"))
    if coverage_state not in {"COMPLETE", "LIMITED"}:
        raise ValueError(f"{asset} coverage.state must be COMPLETE or LIMITED")

    return {
        "asset": asset,
        "state": "VALID",
        "session_date": str(raw.get("session_date")),
        "aggregate_volume": {
            "call_volume": call_volume,
            "put_volume": put_volume,
            "put_call_volume_ratio": _ratio(put_volume, call_volume),
            "source_state": str(aggregate.get("source_state", "UNKNOWN")),
            "observed_at_ms": aggregate.get("observed_at_ms"),
        },
        "covered_open_interest": {
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
            "put_call_open_interest_ratio": _ratio(put_oi, call_oi),
            "claim_scope": (
                "FULL_CHAIN" if coverage_state == "COMPLETE" else "COVERED_CONTRACTS_ONLY"
            ),
        },
        "top_call_oi_strikes": top("CALL"),
        "top_put_oi_strikes": top("PUT"),
        "contracts": normalized_contracts,
        "coverage": deepcopy(coverage),
        "dealer_gamma_gex": {
            "state": "BLOCKED",
            "reason": "DEALER_POSITIONING_NOT_AVAILABLE_OI_IV_ARE_INSUFFICIENT",
        },
        "short_interest": {
            "state": "BLOCKED",
            "reason": "SHORT_INTEREST_SOURCE_NOT_AVAILABLE",
        },
    }


def build_mstr_asst_options_daily_snapshot(
    *,
    asset_inputs: dict[str, dict[str, Any]],
    generated_at_ms: int,
) -> dict[str, Any]:
    if not isinstance(asset_inputs, dict):
        raise ValueError("asset_inputs must be an object")
    if set(asset_inputs) != set(SUPPORTED_ASSETS):
        raise ValueError("asset_inputs must contain exactly MSTR and ASST")
    if not isinstance(generated_at_ms, int):
        raise ValueError("generated_at_ms must be an integer")

    assets = {
        asset: _asset_snapshot(asset, asset_inputs[asset])
        for asset in SUPPORTED_ASSETS
    }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": "VALID",
        "generated_at_ms": generated_at_ms,
        "clock_policy": "VOLUME_AND_OI_EFFECTIVE_TIMES_REMAIN_SEPARATE",
        "coverage_policy": "CLAIM_ONLY_OBSERVED_CONTRACT_COVERAGE",
        "assets": assets,
        **_authority(),
    }
    result["snapshot_hash"] = _canonical_hash(result)
    return result
