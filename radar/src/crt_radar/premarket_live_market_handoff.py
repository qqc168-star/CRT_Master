from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .premarket_equity_live_snapshot import (
    build_equity_source_binding,
    equity_snapshot_to_asset_market,
    validate_equity_live_snapshot,
    validate_equity_source_binding,
)
from .source_registry import SourceRegistry


SCHEMA_VERSION = "CRT_PREMARKET_LIVE_MARKET_HANDOFF_V0.1"

ASSET_ORDER = (
    "MSTR",
    "ASST",
    "STRC",
    "SATA",
)

SOURCE_MODES = {
    "MANUAL_WEB_SUPPLEMENT",
    "MACHINE_VERIFIED_ONLY",
}

ANALYSIS_INPUT_SECTIONS = (
    "PRICE_STRUCTURE",
    "VOLUME_QUALITY",
    "SPOT_VS_DERIVATIVES",
    "BULL_BEAR_FORCE_DISTRIBUTION",
    "BTC_MACRO_TRANSMISSION",
)

SECTION_SOURCE_FAMILIES = {
    "PRICE_STRUCTURE": (
        "BTC_SPOT_PRICE",
        "PRICE_STRUCTURE_CONTEXT",
    ),
    "VOLUME_QUALITY": (
        "PRICE_STRUCTURE_CONTEXT",
    ),
    "SPOT_VS_DERIVATIVES": (
        "BTC_SPOT_PRICE",
        "OPEN_INTEREST",
        "OPEN_INTEREST_NOTIONAL",
        "FUNDING_RATE",
        "LIQUIDATION_AGGREGATES",
    ),
    "BULL_BEAR_FORCE_DISTRIBUTION": (
        "BTC_SPOT_PRICE",
        "OPEN_INTEREST",
        "OPEN_INTEREST_NOTIONAL",
        "FUNDING_RATE",
        "LIQUIDATION_AGGREGATES",
    ),
    "BTC_MACRO_TRANSMISSION": (
        "BTC_SPOT_PRICE",
        "DOLLAR_STRENGTH_PROXY",
        "RATES_CONTEXT",
        "CREDIT_LIQUIDITY_CONTEXT",
    ),
}


def _blocked(
    reason: str,
    value: Any = None,
) -> dict[str, Any]:
    return {
        "state": "BLOCKED",
        "reason": reason,
        "value": deepcopy(value),
    }


def _available(
    value: Any,
    *,
    unit: str | None = None,
    observed_at_ms: int | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": "AVAILABLE",
        "value": deepcopy(value),
    }

    if unit is not None:
        result["unit"] = unit

    if observed_at_ms is not None:
        result["observed_at_ms"] = observed_at_ms

    if source_refs is not None:
        result["source_refs"] = deepcopy(source_refs)

    return result


def _normalize_window(
    value: dict[str, Any] | None,
) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(
            "evaluation_window must be an object"
        )

    start = value.get("start_ms")
    end = value.get("end_ms")

    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start <= 0
        or end < start
    ):
        raise ValueError(
            "evaluation_window timestamps invalid"
        )

    return {
        "start_ms": start,
        "end_ms": end,
    }


def _finite(
    value: Any,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError("numeric value missing")

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "numeric value invalid"
        ) from exc

    if not math.isfinite(number):
        raise ValueError(
            "numeric value must be finite"
        )

    if positive and number <= 0:
        raise ValueError(
            "numeric value must be positive"
        )

    if nonnegative and number < 0:
        raise ValueError(
            "numeric value must be nonnegative"
        )

    return number


def _public_source_ref(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            "source_ref must be an object"
        )

    source_id = value.get("source_id")

    if (
        not isinstance(source_id, str)
        or not source_id.strip()
    ):
        raise ValueError(
            "source_ref.source_id required"
        )

    allowed = (
        "source_id",
        "source_type",
        "retrieved_at_ms",
        "evidence_hash",
        "label",
    )

    result = {
        key: deepcopy(value[key])
        for key in allowed
        if key in value
    }

    result["source_id"] = source_id.strip()

    return result


def _snapshot_blocked(
    reason: str,
) -> dict[str, Any]:
    return {
        "state": "BLOCKED",
        "reason": reason,
        "session": "PREMARKET",
        "premarket_price": _blocked(reason),
        "previous_close": _blocked(reason),
        "premarket_high": _blocked(reason),
        "premarket_low": _blocked(reason),
        "premarket_volume": _blocked(reason),
    }


def _optional_metric(
    row: dict[str, Any],
    key: str,
    *,
    unit: str,
    observed_at_ms: int,
    source_refs: list[dict[str, Any]],
    positive: bool = False,
    nonnegative: bool = False,
) -> dict[str, Any]:
    if key not in row or row.get(key) is None:
        return _blocked(
            f"{key.upper()}_NOT_SUPPLIED"
        )

    number = _finite(
        row.get(key),
        positive=positive,
        nonnegative=nonnegative,
    )

    return _available(
        number,
        unit=unit,
        observed_at_ms=observed_at_ms,
        source_refs=source_refs,
    )


def _manual_asset_snapshot(
    asset: str,
    row: Any,
    *,
    evaluation_window: dict[str, int],
) -> dict[str, Any]:
    if not isinstance(row, dict):
        return _snapshot_blocked(
            "MANUAL_PREMARKET_OBSERVATION_MISSING"
        )

    if row.get("session") != "PREMARKET":
        return _snapshot_blocked(
            "MARKET_SESSION_NOT_PREMARKET"
        )

    observed = row.get("observed_at_ms")

    if (
        not isinstance(observed, int)
        or isinstance(observed, bool)
    ):
        return _snapshot_blocked(
            "MARKET_OBSERVATION_TIMESTAMP_INVALID"
        )

    if (
        observed < evaluation_window["start_ms"]
        or observed > evaluation_window["end_ms"]
    ):
        return _snapshot_blocked(
            "MARKET_OBSERVATION_OUTSIDE_EVALUATION_WINDOW"
        )

    try:
        source_ref = _public_source_ref(
            row.get("source_ref")
        )

        price = _finite(
            row.get("premarket_price"),
            positive=True,
        )

        refs = [source_ref]

        previous = _optional_metric(
            row,
            "previous_close",
            unit="USD",
            observed_at_ms=observed,
            source_refs=refs,
            positive=True,
        )

        high = _optional_metric(
            row,
            "premarket_high",
            unit="USD",
            observed_at_ms=observed,
            source_refs=refs,
            positive=True,
        )

        low = _optional_metric(
            row,
            "premarket_low",
            unit="USD",
            observed_at_ms=observed,
            source_refs=refs,
            positive=True,
        )

        volume = _optional_metric(
            row,
            "premarket_volume",
            unit="SHARES",
            observed_at_ms=observed,
            source_refs=refs,
            nonnegative=True,
        )

        if (
            high.get("state") == "AVAILABLE"
            and low.get("state") == "AVAILABLE"
        ):
            high_value = float(high["value"])
            low_value = float(low["value"])

            if high_value < low_value:
                return _snapshot_blocked(
                    "PREMARKET_RANGE_GEOMETRY_INVALID"
                )

            if not (
                low_value <= price <= high_value
            ):
                return _snapshot_blocked(
                    "PREMARKET_PRICE_OUTSIDE_REPORTED_RANGE"
                )

    except ValueError:
        return _snapshot_blocked(
            "MANUAL_PREMARKET_OBSERVATION_INVALID"
        )

    return {
        "state": "AVAILABLE",
        "asset": asset,
        "session": "PREMARKET",
        "observed_at_ms": observed,
        "source_refs": refs,
        "premarket_price": _available(
            price,
            unit="USD",
            observed_at_ms=observed,
            source_refs=refs,
        ),
        "previous_close": previous,
        "premarket_high": high,
        "premarket_low": low,
        "premarket_volume": volume,
    }


def _machine_asset_snapshot(
    asset: str,
) -> dict[str, Any]:
    result = _snapshot_blocked(
        "MACHINE_EQUITY_LIVE_SOURCE_NOT_BOUND"
    )
    result["asset"] = asset
    return result


def _source_gate_context(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "state": "BLOCKED",
            "reason": "SOURCE_GATE_RESULT_MISSING",
            "formal_state": None,
            "blocked_reasons": [],
            "source_registry_hash": None,
            "parsed": {},
            "evidence_quality": [],
        }

    if value.get("action_output") != "NONE":
        raise ValueError(
            "source gate action_output must remain NONE"
        )

    if (
        value.get("external_action_authority")
        != "NONE"
    ):
        raise ValueError(
            "source gate external action authority "
            "must remain NONE"
        )

    if (
        value.get("external_action_performed")
        is not False
    ):
        raise ValueError(
            "source gate must not perform external action"
        )

    formal_state = value.get("formal_state")

    if formal_state not in {
        "BLOCKED",
        "OBSERVATION_ONLY",
    }:
        raise ValueError(
            "unsupported source gate formal_state"
        )

    parsed = value.get("parsed")

    if not isinstance(parsed, dict):
        raise ValueError(
            "source gate parsed section invalid"
        )

    evidence_quality = []

    evidence = value.get("evidence", [])

    if isinstance(evidence, list):
        for row in evidence:
            if not isinstance(row, dict):
                continue

            evidence_quality.append(
                {
                    key: deepcopy(row.get(key))
                    for key in (
                        "source_id",
                        "input_family",
                        "quality_state",
                        "as_of_ms",
                        "evidence_hash",
                    )
                }
            )

    if formal_state == "OBSERVATION_ONLY":
        state = "AVAILABLE"
        reason = "SOURCE_GATE_OBSERVATION_ONLY"
    elif parsed:
        state = "PARTIAL"
        reason = "SOURCE_GATE_PARTIAL_WITH_BLOCKERS"
    else:
        state = "BLOCKED"
        reason = "SOURCE_GATE_BLOCKED"

    return {
        "state": state,
        "reason": reason,
        "formal_state": formal_state,
        "blocked_reasons": deepcopy(
            value.get("blocked_reasons", [])
        ),
        "source_registry_hash": value.get(
            "source_registry_hash"
        ),
        "parsed": deepcopy(parsed),
        "evidence_quality": evidence_quality,
    }


def _asset_metric_available(
    snapshot: dict[str, Any],
    metric: str,
) -> bool:
    value = snapshot.get(metric)

    return (
        isinstance(value, dict)
        and value.get("state") == "AVAILABLE"
    )


def _analysis_input(
    section_id: str,
    *,
    asset_market: dict[str, dict[str, Any]],
    source_gate: dict[str, Any],
) -> dict[str, Any]:
    families = SECTION_SOURCE_FAMILIES[
        section_id
    ]

    parsed = source_gate.get("parsed", {})

    available_families = {
        family: deepcopy(parsed[family])
        for family in families
        if family in parsed
    }

    missing_inputs = [
        family
        for family in families
        if family not in parsed
    ]

    evidence_count = len(available_families)

    required_asset_metric = None

    if section_id == "PRICE_STRUCTURE":
        required_asset_metric = "premarket_price"

    elif section_id == "VOLUME_QUALITY":
        required_asset_metric = "premarket_volume"

    elif section_id == "BULL_BEAR_FORCE_DISTRIBUTION":
        required_asset_metric = "premarket_price"
        missing_inputs.append(
            "EQUITY_OPTIONS_SHORT_GAMMA_NOT_BOUND"
        )

    asset_observations = {}

    for asset in ASSET_ORDER:
        snapshot = asset_market[asset]
        asset_observations[asset] = deepcopy(snapshot)

        if required_asset_metric is not None:
            if _asset_metric_available(
                snapshot,
                required_asset_metric,
            ):
                evidence_count += 1
            else:
                missing_inputs.append(
                    f"{asset}_{required_asset_metric.upper()}"
                )

    if evidence_count == 0:
        state = "BLOCKED"
    elif missing_inputs:
        state = "PARTIAL"
    else:
        state = "AVAILABLE"

    return {
        "state": state,
        "section_id": section_id,
        "available_source_families": (
            available_families
        ),
        "asset_market_observations": (
            asset_observations
        ),
        "missing_inputs": missing_inputs,
        "machine_judgment": None,
        "analyst_judgment_required": True,
    }


def build_premarket_live_market_handoff(
    *,
    source_mode: str,
    evaluation_window: dict[str, Any],
    source_gate_result: dict[str, Any] | None = None,
    manual_asset_observations: dict[str, Any] | None = None,
    machine_equity_snapshot: dict[str, Any] | None = None,
    machine_equity_source_registry: SourceRegistry | None = None,
    machine_equity_source_id: str | None = None,
) -> dict[str, Any]:
    if source_mode not in SOURCE_MODES:
        raise ValueError(
            "unsupported live-market source mode"
        )

    window = _normalize_window(
        evaluation_window
    )

    manual = (
        manual_asset_observations
        if isinstance(
            manual_asset_observations,
            dict,
        )
        else {}
    )

    if (
        source_mode == "MACHINE_VERIFIED_ONLY"
        and manual
    ):
        raise ValueError(
            "manual market observations are forbidden "
            "in MACHINE_VERIFIED_ONLY mode"
        )

    machine_material = (
        machine_equity_snapshot,
        machine_equity_source_registry,
        machine_equity_source_id,
    )

    machine_material_count = sum(
        value is not None
        for value in machine_material
    )

    if (
        source_mode == "MANUAL_WEB_SUPPLEMENT"
        and machine_material_count != 0
    ):
        raise ValueError(
            "machine equity material is forbidden "
            "in MANUAL_WEB_SUPPLEMENT mode"
        )

    if (
        source_mode == "MACHINE_VERIFIED_ONLY"
        and machine_material_count not in {0, 3}
    ):
        raise ValueError(
            "machine equity source binding is incomplete"
        )

    locked_machine_binding = None
    locked_machine_snapshot = None

    if (
        source_mode == "MACHINE_VERIFIED_ONLY"
        and machine_material_count == 3
    ):
        locked_machine_binding = (
            build_equity_source_binding(
                machine_equity_source_registry,
                source_id=machine_equity_source_id,
            )
        )

        locked_machine_snapshot = (
            validate_equity_live_snapshot(
                machine_equity_snapshot,
                source_binding=locked_machine_binding,
                evaluation_window=window,
            )
        )

        asset_market = (
            equity_snapshot_to_asset_market(
                locked_machine_snapshot,
                source_binding=locked_machine_binding,
                evaluation_window=window,
            )
        )

    else:
        asset_market = {}

        for asset in ASSET_ORDER:
            if source_mode == "MANUAL_WEB_SUPPLEMENT":
                asset_market[asset] = (
                    _manual_asset_snapshot(
                        asset,
                        manual.get(asset),
                        evaluation_window=window,
                    )
                )
            else:
                asset_market[asset] = (
                    _machine_asset_snapshot(asset)
                )

    source_gate = _source_gate_context(
        source_gate_result
    )

    analysis_inputs = {
        section_id: _analysis_input(
            section_id,
            asset_market=asset_market,
            source_gate=source_gate,
        )
        for section_id in ANALYSIS_INPUT_SECTIONS
    }

    price_available = sum(
        1
        for asset in ASSET_ORDER
        if _asset_metric_available(
            asset_market[asset],
            "premarket_price",
        )
    )

    if (
        price_available == len(ASSET_ORDER)
        and source_gate["state"] != "BLOCKED"
    ):
        state = "READY_FOR_ANALYST"

    elif (
        price_available > 0
        or source_gate["state"] != "BLOCKED"
    ):
        state = "PARTIAL"

    else:
        state = "BLOCKED"

    result = {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "source_mode": source_mode,
        "evaluation_window": deepcopy(window),
        "asset_order": list(ASSET_ORDER),
        "asset_market": asset_market,
        "machine_equity_source_binding": (
            deepcopy(locked_machine_binding)
            if locked_machine_binding is not None
            else None
        ),
        "machine_equity_snapshot": (
            deepcopy(locked_machine_snapshot)
            if locked_machine_snapshot is not None
            else None
        ),
        "source_gate_context": source_gate,
        "analysis_inputs": analysis_inputs,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
        "analyst_judgment_required": True,
    }

    return validate_premarket_live_market_handoff(
        result
    )


def validate_premarket_live_market_handoff(
    value: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            "live market handoff must be an object"
        )

    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "live market handoff schema mismatch"
        )

    if value.get("source_mode") not in SOURCE_MODES:
        raise ValueError(
            "live market handoff source mode invalid"
        )

    if value.get("asset_order") != list(ASSET_ORDER):
        raise ValueError(
            "live market handoff asset order mismatch"
        )

    if value.get("action_output") != "NONE":
        raise ValueError(
            "live market handoff action_output "
            "must remain NONE"
        )

    if (
        value.get("external_action_authority")
        != "NONE"
    ):
        raise ValueError(
            "live market handoff external action "
            "authority must remain NONE"
        )

    if (
        value.get("external_action_performed")
        is not False
    ):
        raise ValueError(
            "live market handoff performed "
            "external action"
        )

    if value.get("machine_may_execute_trade") is not False:
        raise ValueError(
            "machine trading authority forbidden"
        )

    if (
        value.get("capital_decision_authority")
        != "USER_ONLY"
    ):
        raise ValueError(
            "capital decision authority must "
            "remain USER_ONLY"
        )

    asset_market = value.get("asset_market")

    if (
        not isinstance(asset_market, dict)
        or list(asset_market) != list(ASSET_ORDER)
    ):
        raise ValueError(
            "live market asset map invalid"
        )

    for asset in ASSET_ORDER:
        snapshot = asset_market.get(asset)

        if not isinstance(snapshot, dict):
            raise ValueError(
                "live market asset snapshot invalid"
            )

        price = snapshot.get("premarket_price")

        if not isinstance(price, dict):
            raise ValueError(
                "live market premarket price wrapper invalid"
            )

    machine_binding = value.get(
        "machine_equity_source_binding"
    )
    machine_snapshot = value.get(
        "machine_equity_snapshot"
    )

    machine_mode = (
        value.get("source_mode")
        == "MACHINE_VERIFIED_ONLY"
    )

    if machine_mode:
        material_count = sum(
            item is not None
            for item in (
                machine_binding,
                machine_snapshot,
            )
        )

        if material_count == 1:
            raise ValueError(
                "machine equity provenance incomplete"
            )

        if material_count == 0:
            for asset in ASSET_ORDER:
                if (
                    asset_market[asset][
                        "premarket_price"
                    ].get("state")
                    == "AVAILABLE"
                ):
                    raise ValueError(
                        "machine equity live source is not bound"
                    )

        else:
            locked_binding = (
                validate_equity_source_binding(
                    machine_binding
                )
            )

            locked_snapshot = (
                validate_equity_live_snapshot(
                    machine_snapshot,
                    source_binding=locked_binding,
                    evaluation_window=_normalize_window(
                        value.get("evaluation_window")
                    ),
                )
            )

            expected_market = (
                equity_snapshot_to_asset_market(
                    locked_snapshot,
                    source_binding=locked_binding,
                    evaluation_window=_normalize_window(
                        value.get("evaluation_window")
                    ),
                )
            )

            if asset_market != expected_market:
                raise ValueError(
                    "machine equity asset market "
                    "does not match verified snapshot"
                )

    else:
        if (
            machine_binding is not None
            or machine_snapshot is not None
        ):
            raise ValueError(
                "manual handoff cannot carry "
                "machine equity provenance"
            )

    analysis_inputs = value.get(
        "analysis_inputs"
    )

    if (
        not isinstance(analysis_inputs, dict)
        or list(analysis_inputs)
        != list(ANALYSIS_INPUT_SECTIONS)
    ):
        raise ValueError(
            "live market analysis input map invalid"
        )

    for section_id in ANALYSIS_INPUT_SECTIONS:
        section = analysis_inputs.get(section_id)

        if not isinstance(section, dict):
            raise ValueError(
                "live market analysis input invalid"
            )

        if section.get("machine_judgment") is not None:
            raise ValueError(
                "machine judgment is forbidden"
            )

        if (
            section.get("analyst_judgment_required")
            is not True
        ):
            raise ValueError(
                "analyst judgment boundary invalid"
            )

    return deepcopy(value)


def apply_live_market_handoff_to_asset_facts(
    asset_facts: dict[str, Any] | None,
    handoff: dict[str, Any],
) -> dict[str, Any]:
    locked = validate_premarket_live_market_handoff(
        handoff
    )

    result = (
        deepcopy(asset_facts)
        if isinstance(asset_facts, dict)
        else {}
    )

    for asset in ASSET_ORDER:
        target = result.get(asset)

        if not isinstance(target, dict):
            target = {}
            result[asset] = target

        incoming = locked["asset_market"][asset][
            "premarket_price"
        ]

        existing = target.get("premarket_price")

        existing_available = (
            isinstance(existing, dict)
            and existing.get("state") == "AVAILABLE"
        )

        # A live-market handoff supplements missing evidence.
        # It must never replace an already AVAILABLE upstream fact.
        if not existing_available:
            target["premarket_price"] = deepcopy(
                incoming
            )

    return result
