from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .source_registry import (
    SourceSpec,
    canonical_json_bytes,
    sha256_hex,
)


SCHEMA_VERSION = "CRT_PREMARKET_EQUITY_LIVE_SNAPSHOT_V0.1"
INPUT_FAMILY = "EQUITY_PREMARKET_SNAPSHOT"
PARSER_ID = "CRT_EQUITY_PREMARKET_SNAPSHOT_V1"
TRANSPORT = "LOCAL_VERIFIED_JSON_SNAPSHOT"
AUTHENTICATION = "LOCAL_READ_ONLY"
SOURCE_TYPE = "MACHINE_VERIFIED_EQUITY_SNAPSHOT"

ASSET_ORDER = (
    "MSTR",
    "ASST",
    "STRC",
    "SATA",
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _finite(
    value: Any,
    field: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} missing or invalid")

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field} must be numeric"
        ) from exc

    if not math.isfinite(number):
        raise ValueError(
            f"{field} must be finite"
        )

    if positive and number <= 0:
        raise ValueError(
            f"{field} must be positive"
        )

    if nonnegative and number < 0:
        raise ValueError(
            f"{field} must be nonnegative"
        )

    return number


def _timestamp(
    value: Any,
    field: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError(
            f"{field} must be positive integer"
        )

    return value


def _hash64(
    value: Any,
    field: str,
) -> str:
    if (
        not isinstance(value, str)
        or _HASH_RE.fullmatch(value) is None
    ):
        raise ValueError(
            f"{field} must be lowercase sha256"
        )

    return value


def _window(
    value: dict[str, Any] | None,
) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(
            "evaluation_window must be object"
        )

    start = _timestamp(
        value.get("start_ms"),
        "evaluation_window.start_ms",
    )

    end = _timestamp(
        value.get("end_ms"),
        "evaluation_window.end_ms",
    )

    if end < start:
        raise ValueError(
            "evaluation_window end before start"
        )

    return {
        "start_ms": start,
        "end_ms": end,
    }


def build_equity_source_binding(
    spec: SourceSpec,
    *,
    source_registry_hash: str,
) -> dict[str, Any]:
    if not isinstance(spec, SourceSpec):
        raise ValueError(
            "equity source spec required"
        )

    if spec.input_family != INPUT_FAMILY:
        raise ValueError(
            "equity source input family mismatch"
        )

    if spec.transport != TRANSPORT:
        raise ValueError(
            "equity source transport mismatch"
        )

    if spec.parser_id != PARSER_ID:
        raise ValueError(
            "equity source parser mismatch"
        )

    if (
        spec.raw.get("authentication")
        != AUTHENTICATION
    ):
        raise ValueError(
            "equity source authentication mismatch"
        )

    if (
        spec.raw.get("implementation_state")
        != "LIVE_READ_ONLY_COLLECTOR"
    ):
        raise ValueError(
            "equity collector is not live read-only"
        )

    if (
        spec.raw.get("provider_binding_state")
        != "BOUND"
    ):
        raise ValueError(
            "equity provider is not bound"
        )

    provider_contract_id = spec.raw.get(
        "provider_contract_id"
    )

    if (
        not isinstance(provider_contract_id, str)
        or not provider_contract_id.strip()
    ):
        raise ValueError(
            "equity provider contract id missing"
        )

    documentation = spec.raw.get(
        "documentation"
    )

    if not (
        isinstance(documentation, str)
        and documentation.strip()
    ):
        raise ValueError(
            "equity source documentation missing"
        )

    registry_hash = _hash64(
        source_registry_hash,
        "source_registry_hash",
    )

    result = {
        "binding_state": "BOUND",
        "source_id": spec.source_id,
        "source_registry_hash": registry_hash,
        "input_family": INPUT_FAMILY,
        "provider": spec.provider,
        "provider_contract_id": (
            provider_contract_id.strip()
        ),
        "documentation": documentation.strip(),
        "transport": TRANSPORT,
        "authentication": AUTHENTICATION,
        "parser_id": PARSER_ID,
        "max_age_seconds": int(
            spec.max_age_seconds
        ),
    }

    return validate_equity_source_binding(
        result
    )


def validate_equity_source_binding(
    value: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            "equity source binding must be object"
        )

    required = {
        "binding_state",
        "source_id",
        "source_registry_hash",
        "input_family",
        "provider",
        "provider_contract_id",
        "documentation",
        "transport",
        "authentication",
        "parser_id",
        "max_age_seconds",
    }

    if not required.issubset(value):
        raise ValueError(
            "equity source binding fields missing"
        )

    if value.get("binding_state") != "BOUND":
        raise ValueError(
            "equity source binding not bound"
        )

    if value.get("input_family") != INPUT_FAMILY:
        raise ValueError(
            "equity source binding family mismatch"
        )

    if value.get("transport") != TRANSPORT:
        raise ValueError(
            "equity source binding transport mismatch"
        )

    if (
        value.get("authentication")
        != AUTHENTICATION
    ):
        raise ValueError(
            "equity source binding auth mismatch"
        )

    if value.get("parser_id") != PARSER_ID:
        raise ValueError(
            "equity source binding parser mismatch"
        )

    for field in (
        "source_id",
        "provider",
        "provider_contract_id",
        "documentation",
    ):
        raw = value.get(field)

        if (
            not isinstance(raw, str)
            or not raw.strip()
        ):
            raise ValueError(
                f"equity source {field} missing"
            )

    _hash64(
        value.get("source_registry_hash"),
        "source_registry_hash",
    )

    max_age = value.get("max_age_seconds")

    if (
        not isinstance(max_age, int)
        or isinstance(max_age, bool)
        or max_age <= 0
    ):
        raise ValueError(
            "equity source max age invalid"
        )

    return deepcopy(value)


def seal_equity_live_snapshot(
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(
            "equity snapshot payload must be object"
        )

    if "snapshot_hash" in payload:
        raise ValueError(
            "unsealed payload must not contain snapshot_hash"
        )

    result = deepcopy(payload)

    result["snapshot_hash"] = sha256_hex(
        canonical_json_bytes(result)
    )

    return result


def _validate_asset(
    asset: str,
    row: Any,
) -> None:
    if not isinstance(row, dict):
        raise ValueError(
            f"{asset} snapshot must be object"
        )

    if row.get("symbol") != asset:
        raise ValueError(
            f"{asset} symbol mismatch"
        )

    price = _finite(
        row.get("premarket_price"),
        f"{asset}.premarket_price",
        positive=True,
    )

    previous = row.get("previous_close")
    high = row.get("premarket_high")
    low = row.get("premarket_low")
    volume = row.get("premarket_volume")

    if previous is not None:
        _finite(
            previous,
            f"{asset}.previous_close",
            positive=True,
        )

    high_value = None
    low_value = None

    if high is not None:
        high_value = _finite(
            high,
            f"{asset}.premarket_high",
            positive=True,
        )

    if low is not None:
        low_value = _finite(
            low,
            f"{asset}.premarket_low",
            positive=True,
        )

    if volume is not None:
        _finite(
            volume,
            f"{asset}.premarket_volume",
            nonnegative=True,
        )

    if (
        high_value is not None
        and low_value is not None
    ):
        if high_value < low_value:
            raise ValueError(
                f"{asset} premarket range invalid"
            )

        if not (
            low_value <= price <= high_value
        ):
            raise ValueError(
                f"{asset} price outside premarket range"
            )


def validate_equity_live_snapshot(
    snapshot: dict[str, Any],
    *,
    source_binding: dict[str, Any],
    evaluation_window: dict[str, Any],
) -> dict[str, Any]:
    binding = validate_equity_source_binding(
        source_binding
    )

    if not isinstance(snapshot, dict):
        raise ValueError(
            "equity live snapshot must be object"
        )

    if (
        snapshot.get("schema_version")
        != SCHEMA_VERSION
    ):
        raise ValueError(
            "equity live snapshot schema mismatch"
        )

    if (
        snapshot.get("source_id")
        != binding["source_id"]
    ):
        raise ValueError(
            "equity live snapshot source mismatch"
        )

    if (
        snapshot.get("provider")
        != binding["provider"]
    ):
        raise ValueError(
            "equity live snapshot provider mismatch"
        )

    if (
        snapshot.get("provider_contract_id")
        != binding["provider_contract_id"]
    ):
        raise ValueError(
            "equity provider contract mismatch"
        )

    if snapshot.get("session") != "PREMARKET":
        raise ValueError(
            "equity snapshot session must be PREMARKET"
        )

    observed = _timestamp(
        snapshot.get("observed_at_ms"),
        "observed_at_ms",
    )

    retrieved = _timestamp(
        snapshot.get("retrieved_at_ms"),
        "retrieved_at_ms",
    )

    first_seen = _timestamp(
        snapshot.get("first_seen_at_ms"),
        "first_seen_at_ms",
    )

    if observed > retrieved:
        raise ValueError(
            "equity observation after retrieval"
        )

    if first_seen != retrieved:
        raise ValueError(
            "prospective first_seen must equal retrieval"
        )

    window = _window(evaluation_window)

    if not (
        window["start_ms"]
        <= observed
        <= window["end_ms"]
    ):
        raise ValueError(
            "equity observation outside evaluation window"
        )

    if not (
        window["start_ms"]
        <= retrieved
        <= window["end_ms"]
    ):
        raise ValueError(
            "equity retrieval outside evaluation window"
        )

    age_ms = window["end_ms"] - observed

    if (
        age_ms
        > binding["max_age_seconds"] * 1000
    ):
        raise ValueError(
            "equity snapshot stale"
        )

    _hash64(
        snapshot.get("request_identity_hash"),
        "request_identity_hash",
    )

    _hash64(
        snapshot.get("raw_response_hash"),
        "raw_response_hash",
    )

    if snapshot.get("action_output") != "NONE":
        raise ValueError(
            "equity snapshot action_output must be NONE"
        )

    if (
        snapshot.get("external_action_authority")
        != "NONE"
    ):
        raise ValueError(
            "equity snapshot authority must be NONE"
        )

    if (
        snapshot.get("external_action_performed")
        is not False
    ):
        raise ValueError(
            "equity snapshot performed external action"
        )

    assets = snapshot.get("assets")

    if (
        not isinstance(assets, dict)
        or list(assets) != list(ASSET_ORDER)
    ):
        raise ValueError(
            "equity snapshot asset order mismatch"
        )

    for asset in ASSET_ORDER:
        _validate_asset(
            asset,
            assets.get(asset),
        )

    supplied_hash = _hash64(
        snapshot.get("snapshot_hash"),
        "snapshot_hash",
    )

    material = deepcopy(snapshot)
    material.pop("snapshot_hash", None)

    expected_hash = sha256_hex(
        canonical_json_bytes(material)
    )

    if supplied_hash != expected_hash:
        raise ValueError(
            "equity snapshot hash mismatch"
        )

    return deepcopy(snapshot)


def _blocked(
    reason: str,
) -> dict[str, Any]:
    return {
        "state": "BLOCKED",
        "reason": reason,
        "value": None,
    }


def _available(
    value: Any,
    *,
    unit: str,
    observed_at_ms: int,
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "state": "AVAILABLE",
        "value": value,
        "unit": unit,
        "observed_at_ms": observed_at_ms,
        "source_refs": deepcopy(source_refs),
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
    raw = row.get(key)

    if raw is None:
        return _blocked(
            f"MACHINE_{key.upper()}_NOT_SUPPLIED"
        )

    number = _finite(
        raw,
        key,
        positive=positive,
        nonnegative=nonnegative,
    )

    return _available(
        number,
        unit=unit,
        observed_at_ms=observed_at_ms,
        source_refs=source_refs,
    )


def equity_snapshot_to_asset_market(
    snapshot: dict[str, Any],
    *,
    source_binding: dict[str, Any],
    evaluation_window: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    binding = validate_equity_source_binding(
        source_binding
    )

    locked = validate_equity_live_snapshot(
        snapshot,
        source_binding=binding,
        evaluation_window=evaluation_window,
    )

    observed = int(
        locked["observed_at_ms"]
    )

    source_ref = {
        "source_id": binding["source_id"],
        "source_type": SOURCE_TYPE,
        "provider": binding["provider"],
        "provider_contract_id": (
            binding["provider_contract_id"]
        ),
        "source_registry_hash": (
            binding["source_registry_hash"]
        ),
        "retrieved_at_ms": locked[
            "retrieved_at_ms"
        ],
        "evidence_hash": locked[
            "snapshot_hash"
        ],
        "request_identity_hash": locked[
            "request_identity_hash"
        ],
        "raw_response_hash": locked[
            "raw_response_hash"
        ],
    }

    refs = [source_ref]

    result = {}

    for asset in ASSET_ORDER:
        row = locked["assets"][asset]

        price = _finite(
            row["premarket_price"],
            f"{asset}.premarket_price",
            positive=True,
        )

        result[asset] = {
            "state": "AVAILABLE",
            "asset": asset,
            "session": "PREMARKET",
            "observed_at_ms": observed,
            "source_refs": deepcopy(refs),
            "premarket_price": _available(
                price,
                unit="USD",
                observed_at_ms=observed,
                source_refs=refs,
            ),
            "previous_close": _optional_metric(
                row,
                "previous_close",
                unit="USD",
                observed_at_ms=observed,
                source_refs=refs,
                positive=True,
            ),
            "premarket_high": _optional_metric(
                row,
                "premarket_high",
                unit="USD",
                observed_at_ms=observed,
                source_refs=refs,
                positive=True,
            ),
            "premarket_low": _optional_metric(
                row,
                "premarket_low",
                unit="USD",
                observed_at_ms=observed,
                source_refs=refs,
                positive=True,
            ),
            "premarket_volume": _optional_metric(
                row,
                "premarket_volume",
                unit="SHARES",
                observed_at_ms=observed,
                source_refs=refs,
                nonnegative=True,
            ),
        }

    return result
