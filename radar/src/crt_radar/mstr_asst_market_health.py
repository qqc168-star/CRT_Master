from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import datetime, timezone
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


def issuer_ratio_observation(
    asset: str, issuer: Any, *, generated_at_ms: int,
) -> tuple[dict[str, Any], list[str]]:
    """The existing issuer wake comparison, with reported-clock provenance intact."""
    if not isinstance(issuer, dict):
        raise ValueError(f"{asset} issuer BTC/share input must be an object")
    current = _number(issuer.get("current_btc_per_diluted_share"), "current_btc_per_diluted_share")
    previous = _number(issuer.get("previous_btc_per_diluted_share"), "previous_btc_per_diluted_share")
    if not all(math.isfinite(value) and value > 0 for value in (previous, current)):
        raise ValueError("issuer BTC/share must be finite and positive")
    result = {"current": current, "previous": previous}
    if any(key in issuer for key in ("time_semantic", "source_role", "current_reported_date", "previous_reported_date")):
        required = {
            "source_role": "PRIMARY_OFFICIAL_MSTR_BTC_ADSO_HISTORY",
            "time_semantic": "REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME",
            "reported_at_rule": "REPORTED_DATE_UTC_MIDNIGHT_SORT_KEY_ONLY",
            "comparison_horizon": "ADJACENT_REPORTED_OBSERVATIONS",
            "ct_binding_state": "NOT_CT_BOUND",
            "ct_blocker": "ADSO_EFFECTIVE_TIME_UNRESOLVED",
            "wake_authority": "OBSERVATION_ONLY",
            "machine_execution": "FORBIDDEN",
            "semantic_source_url": "https://www.strategy.com/notes",
            "semantic_authority": "METRIC_SEMANTIC_AUTHORITY",
            "sec_authority": "DISCLOSURE_AND_CAPITAL_EVENT_AUTHORITY",
        }
        if asset != "MSTR" or any(issuer.get(key) != value for key, value in required.items()):
            raise ValueError("Ledger observation contract mismatch")
        if any("effective" in key.lower() or "disclosure" in key.lower() for key in issuer):
            raise ValueError("Ledger observation must not invent effective/disclosure clocks")
        dates = []
        for prefix, ratio in (("previous", previous), ("current", current)):
            reported = issuer.get(f"{prefix}_reported_date")
            if not isinstance(reported, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", reported):
                raise ValueError("Ledger reported_date must be ISO date")
            sort_ms = int(datetime.fromisoformat(reported).replace(tzinfo=timezone.utc).timestamp() * 1000)
            clocks = [issuer.get(f"{prefix}_{key}") for key in
                      ("reported_at_ms", "first_seen_at_ms", "retrieved_at_ms")]
            if (any(type(value) is not int or value <= 0 for value in clocks)
                    or clocks[0] != sort_ms or not sort_ms <= clocks[1] <= clocks[2] <= generated_at_ms):
                raise ValueError("Ledger reported/retrieval clock ordering invalid")
            dates.append(reported)
            btc = _number(issuer.get(f"{prefix}_btc_holdings"), "Ledger BTC")
            shares = _number(issuer.get(f"{prefix}_diluted_shares"), "Ledger ADSO")
            if (not all(math.isfinite(value) and value > 0 for value in (btc, shares))
                    or not math.isclose(ratio, btc / shares, rel_tol=1e-12)):
                raise ValueError("Ledger ratio must use same-row BTC/ADSO")
            if issuer.get(f"{prefix}_source_url") != "https://www.strategy.com/ledger":
                raise ValueError("Ledger official source URL mismatch")
            if not re.fullmatch(r"[0-9a-f]{64}", str(issuer.get(f"{prefix}_evidence_hash", ""))):
                raise ValueError("Ledger raw evidence hash invalid")
        if dates[0] >= dates[1]:
            raise ValueError("Ledger adjacent reported dates must be increasing")
        result.update(deepcopy(issuer))
        result.update({"current": current, "previous": previous})
        result["direction_claim"] = (
            "ADJACENT_REPORTED_BTC_PER_ADSO_DECREASED" if current < previous
            else "ADJACENT_REPORTED_BTC_PER_ADSO_NON_DECREASED"
        )
    reasons = ["BTC_PER_DILUTED_SHARE_DECREASED"] if current < previous else []
    return result, reasons


ISSUER_OBSERVATION_SCHEMA_VERSION = "CRT_ISSUER_RATIO_OBSERVATION_V0.1"


def build_issuer_ratio_observation(
    source_proof: Any, *, generated_at_ms: int,
) -> dict[str, Any]:
    """Consume the existing issuer proof without requiring the other four sources."""
    # Local import avoids the runtime -> daily runner -> evidence pack import cycle.
    from .mstr_asst_market_health_runtime import _validated_source

    data = _validated_source(
        "issuer_btc_per_diluted_share", source_proof,
        generated_at_ms=generated_at_ms,
    )
    provenance = {key: deepcopy(source_proof[key]) for key in
                  ("source_id", "data_hash", "observed_at_ms")}
    return _issuer_observation_section(data, provenance, generated_at_ms)


def _issuer_observation_section(
    data: Any, provenance: Any, generated_at_ms: int,
) -> dict[str, Any]:
    if type(generated_at_ms) is not int or generated_at_ms <= 0:
        raise ValueError("issuer observation generated_at_ms must be positive integer")
    if not isinstance(data, dict) or not data or set(data) - set(SUPPORTED_ASSETS):
        raise ValueError("issuer observations must be keyed by MSTR/ASST")
    if (not isinstance(provenance, dict)
            or provenance.get("source_id") != "CRT-CONN-MSTR-ASST-OFFICIAL-ISSUER-RATIO-001"
            or not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("data_hash", "")))
            or type(provenance.get("observed_at_ms")) is not int
            or not 0 < provenance["observed_at_ms"] <= generated_at_ms):
        raise ValueError("issuer observation source provenance invalid")
    observations = {}
    for asset, issuer in sorted(data.items()):
        if not isinstance(issuer, dict):
            raise ValueError("issuer observation row must be an object")
        if asset == "MSTR" and issuer.get("time_semantic") != "REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME":
            raise ValueError("MSTR observation requires the locked Ledger reported semantics")
        checked, _ = issuer_ratio_observation(asset, issuer, generated_at_ms=provenance["observed_at_ms"])
        if asset == "ASST":
            # Keep the existing SEC effective clocks; never coerce them to Ledger clocks.
            times = [issuer.get(f"{prefix}_effective_at_ms") for prefix in ("previous", "current")]
            if (any(type(value) is not int for value in times)
                    or not 0 < times[0] < times[1] <= provenance["observed_at_ms"]):
                raise ValueError("ASST effective clock ordering invalid")
            for prefix, ratio in (("previous", checked["previous"]), ("current", checked["current"])):
                btc = _number(issuer.get(f"{prefix}_btc_holdings"), "ASST BTC")
                shares = _number(issuer.get(f"{prefix}_diluted_shares"), "ASST diluted shares")
                if (not all(math.isfinite(v) and v > 0 for v in (btc, shares))
                        or not math.isclose(ratio, btc / shares, rel_tol=1e-12)):
                    raise ValueError("ASST ratio must use same-state BTC/shares")
        row = {}
        for prefix in ("previous", "current"):
            for field in ("btc_holdings", "diluted_shares", "btc_per_diluted_share", "source_url", "evidence_hash"):
                key = f"{prefix}_{field}"
                row[key] = deepcopy(issuer[key])
            if not re.fullmatch(r"[0-9a-f]{64}", str(row[f"{prefix}_evidence_hash"])):
                raise ValueError("issuer raw evidence hash invalid")
            if not isinstance(row[f"{prefix}_source_url"], str) or not row[f"{prefix}_source_url"].startswith("https://"):
                raise ValueError("issuer source URL invalid")
            clocks = ("reported_date", "reported_at_ms", "first_seen_at_ms", "retrieved_at_ms") if asset == "MSTR" else ("effective_at_ms",)
            for field in clocks:
                row[f"{prefix}_{field}"] = deepcopy(issuer[f"{prefix}_{field}"])
        if asset == "MSTR":
            for field in ("source_role", "time_semantic", "reported_at_rule", "comparison_horizon",
                          "ct_binding_state", "ct_blocker", "semantic_source_url", "semantic_authority", "sec_authority"):
                row[field] = checked[field]
            row.update({"source_url": row["current_source_url"], "evidence_hash": row["current_evidence_hash"],
                        "retrieved_at_ms": row["current_retrieved_at_ms"], "first_seen_at_ms": row["current_first_seen_at_ms"]})
        row["latest_to_previous_change_pct"] = (checked["current"] / checked["previous"] - 1) * 100
        row["wake_authority"] = "OBSERVATION_ONLY"
        row["machine_execution"] = "FORBIDDEN"
        observations[asset] = row
    result = {
        "schema_version": ISSUER_OBSERVATION_SCHEMA_VERSION,
        "state": "VALID", "generated_at_ms": generated_at_ms,
        "observations": observations, "source_provenance": deepcopy(provenance),
        "analyst_judgment_required": True, **_authority(),
    }
    result["observation_hash"] = _canonical_hash(result)
    return result


def validate_issuer_ratio_observation(
    payload: Any, *, generated_at_ms: int | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("issuer_ratio_observation must be an object")
    observed = payload.get("generated_at_ms")
    if generated_at_ms is not None and (type(observed) is not int or observed > generated_at_ms):
        raise ValueError("issuer observation cannot be in the future")
    expected = _issuer_observation_section(
        payload.get("observations"), payload.get("source_provenance"), observed,
    )
    if payload != expected:
        raise ValueError("issuer observation contract/hash mismatch")
    return expected


def compact_issuer_ratio_observation(payload: Any, *, generated_at_ms: int) -> dict[str, Any]:
    """Keep paired facts literal; full provenance remains in the sealed pack."""
    checked = validate_issuer_ratio_observation(payload, generated_at_ms=generated_at_ms)
    rows = {}
    for asset, row in checked["observations"].items():
        if asset == "MSTR":
            keys = (
                "previous_reported_date", "current_reported_date", "previous_btc_holdings",
                "current_btc_holdings", "previous_diluted_shares", "current_diluted_shares",
                "previous_btc_per_diluted_share", "current_btc_per_diluted_share",
                "latest_to_previous_change_pct", "source_url", "evidence_hash",
                "retrieved_at_ms", "first_seen_at_ms", "time_semantic", "comparison_horizon",
                "ct_binding_state", "ct_blocker", "wake_authority", "machine_execution",
            )
            rows[asset] = {key: deepcopy(row[key]) for key in keys}
        else:
            rows[asset] = deepcopy(row)
            for key in ("source_url", "evidence_hash"):
                if row[f"previous_{key}"] == row[f"current_{key}"]:
                    rows[asset][key] = rows[asset].pop(f"current_{key}")
                    rows[asset].pop(f"previous_{key}")
            rows[asset]["shared_source_fields_scope"] = "BOTH_SEC_PAIRED_STATES"
    return {
        "observation_hash": checked["observation_hash"], "observations": rows,
        "provenance_scope": "FULL_TIME_AND_SOURCE_PROVENANCE_IN_EVIDENCE_PACK",
    }


def _asset_health(
    asset: str,
    market: dict[str, Any],
    options: dict[str, Any],
    lines: dict[str, float],
    issuer: dict[str, Any],
    generated_at_ms: int,
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

    issuer_observation, issuer_reasons = issuer_ratio_observation(
        asset, issuer, generated_at_ms=generated_at_ms,
    )
    reasons.extend(issuer_reasons)

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
        "issuer_btc_per_diluted_share": issuer_observation,
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
        issuer = row.get("issuer_btc_per_diluted_share", {})
        if any(key in issuer for key in ("time_semantic", "source_role", "current_reported_date", "previous_reported_date")):
            checked, issuer_reasons = issuer_ratio_observation(
                asset, issuer, generated_at_ms=payload["generated_at_ms"],
            )
            if (checked != issuer or ("BTC_PER_DILUTED_SHARE_DECREASED" in reasons)
                    != bool(issuer_reasons)):
                raise ValueError("Ledger observation/wake semantics mismatch")
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
            generated_at_ms,
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
