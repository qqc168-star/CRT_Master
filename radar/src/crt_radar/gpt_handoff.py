from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .run_ledger import GENESIS_HASH, RunLedger


SCHEMA_VERSION = "CRT_GPT_HANDOFF_V0.1"
HANDOFF_RECORD_TYPE = "GPT_HANDOFF"
RESET_RECORD_TYPE = "GPT_HANDOFF_RESET"

REANALYSIS_SEMANTICS_SCHEMA_VERSION = (
    "CRT_GPT_REANALYSIS_SEMANTICS_V0.1"
)

REANALYSIS_SEQUENCE = (
    "CATALYST",
    "AMPLIFIER",
    "PERSISTENCE",
    "ACCEPTANCE",
    "CONTRADICTIONS",
    "MISSING_EVIDENCE",
)

CAUSAL_GUARDRAILS = (
    "TEMPORAL_ORDER_IS_NOT_CAUSATION",
    "TRANSIENT_PRICE_CROSSING_IS_NOT_ACCEPTANCE_OR_REAL_DEMAND",
    "CONTRADICTORY_EVIDENCE_MUST_BE_SURFACED",
    "MISSING_EVIDENCE_MUST_NOT_BE_IMPUTED_OR_GUESSED",
)

EVIDENCE_RULES = (
    "SEPARATE_OBSERVATION_FROM_INFERENCE",
    "STATE_UNRESOLVED_CAUSALITY_EXPLICITLY",
    "USE_LATEST_REQUIRED_INPUTS",
)

GOVERNANCE_GUARDRAILS = (
    "RESEARCH_OVERLAY_CANNOT_PROMOTE_FORMAL_SEASON",
    "NO_AUTOMATIC_BUY_SELL",
    "NO_EXTERNAL_ACTION",
)

BRIDGE_PAYLOAD_SCHEMA_VERSION = (
    "CRT_MINIMIZED_BRIDGE_PAYLOAD_V0.1"
)

BRIDGE_PRIVACY_CONTRACT_VERSION = (
    "CRT_BRIDGE_PAYLOAD_PRIVACY_CONTRACT_V0.1"
)

BRIDGE_FORBIDDEN_EXACT_KEYS = {
    "private_context",
    "profile",
    "path",
    "email",
    "phone",
    "address",
    "account_number",
    "broker_account",
    "brokerage_account",
    "api_key",
    "access_token",
    "password",
    "secret",
    "credential",
    "credentials",
}

BRIDGE_OPTIONAL_MARKET_SECTIONS = (
    "dvol_regime_watch",
    "transition_diagnostic",
    "btc_entry_gate",
    "btc_bull_validation",
)


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
        "transport_authority": "NONE",
        "transport_performed": False,
    }


def _reanalysis_semantics() -> dict[str, Any]:
    return {
        "schema_version": (
            REANALYSIS_SEMANTICS_SCHEMA_VERSION
        ),
        "scope": "POST_WAKE_ANALYSIS_ONLY",
        "analysis_sequence": list(
            REANALYSIS_SEQUENCE
        ),
        "causal_guardrails": list(
            CAUSAL_GUARDRAILS
        ),
        "evidence_rules": list(
            EVIDENCE_RULES
        ),
        "governance_guardrails": list(
            GOVERNANCE_GUARDRAILS
        ),
        "wake_authority": "NONE",
        "formal_season_authority": "NONE",
        "trading_authority": "NONE",
        "external_action_authority": "NONE",
    }


def _assert_bridge_privacy(
    value: Any,
    *,
    location: str = "$",
) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.strip().lower()

            if normalized in BRIDGE_FORBIDDEN_EXACT_KEYS:
                raise ValueError(
                    "Bridge payload contains forbidden key "
                    f"{location}.{key}"
                )

            _assert_bridge_privacy(
                child,
                location=f"{location}.{key}",
            )

    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_bridge_privacy(
                child,
                location=f"{location}[{index}]",
            )


def _bridge_data_health(
    pack: dict[str, Any],
) -> dict[str, Any]:
    raw = pack.get("data_health")

    if not isinstance(raw, dict):
        return {
            "source_gate_state": None,
            "critical_blockers": [],
            "unusable_or_missing_evidence": [],
        }

    unusable = []

    for row in raw.get(
        "unusable_or_missing_evidence",
        [],
    ):
        if not isinstance(row, dict):
            continue

        unusable.append(
            {
                "input_family": row.get(
                    "input_family"
                ),
                "quality_state": row.get(
                    "quality_state"
                ),
            }
        )

    return {
        "source_gate_state": raw.get(
            "source_gate_state"
        ),
        "critical_blockers": deepcopy(
            raw.get(
                "critical_blockers",
                [],
            )
        ),
        "unusable_or_missing_evidence": (
            unusable
        ),
    }


def _bridge_market_context(
    pack: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "generated_at_ms": pack.get(
            "generated_at_ms"
        ),
        "pack_state": pack.get(
            "pack_state"
        ),
        "data_health": _bridge_data_health(
            pack
        ),
        "layers": deepcopy(
            pack.get(
                "layers",
                {},
            )
        ),
        "changes": deepcopy(
            pack.get(
                "changes",
                {},
            )
        ),
        "distillation": deepcopy(
            pack.get(
                "distillation",
                {},
            )
        ),
        "model_status": deepcopy(
            pack.get(
                "model_status",
                {},
            )
        ),
    }

    for key in BRIDGE_OPTIONAL_MARKET_SECTIONS:
        if key in pack:
            result[key] = deepcopy(
                pack[key]
            )

    return result


def _bridge_capital_condition(
    payload: Any,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(
            "capital-state validity condition "
            "must be an object"
        )

    result: dict[str, Any] = {}

    for key in (
        "field",
        "operator",
        "value",
    ):
        if key in payload:
            result[key] = deepcopy(
                payload[key]
            )

    return result


def _bridge_capital_state(
    private_context: Any,
) -> dict[str, Any]:
    if not isinstance(
        private_context,
        dict,
    ):
        raise ValueError(
            "current private context unavailable"
        )

    if (
        private_context.get("state")
        != "AVAILABLE"
    ):
        raise ValueError(
            "current private context must be AVAILABLE"
        )

    profile = private_context.get(
        "profile"
    )

    if not isinstance(profile, dict):
        raise ValueError(
            "current private profile unavailable"
        )

    status = profile.get(
        "capital_state_status"
    )

    if (
        not isinstance(status, dict)
        or status.get("state")
        != "AVAILABLE"
    ):
        raise ValueError(
            "current Capital State must be AVAILABLE"
        )

    if (
        status.get("execution_authority")
        != "USER_ONLY"
    ):
        raise ValueError(
            "Capital State execution authority "
            "must remain USER_ONLY"
        )

    meta = profile.get("capital_state")

    if not isinstance(meta, dict):
        raise ValueError(
            "capital_state unavailable"
        )

    capital_state = {
        key: deepcopy(meta.get(key))
        for key in (
            "contract_version",
            "source",
            "as_of",
            "base_currency",
        )
    }

    holdings_raw = profile.get(
        "holdings"
    )

    if not isinstance(
        holdings_raw,
        list,
    ):
        raise ValueError(
            "holdings unavailable"
        )

    holdings = []

    for row in holdings_raw:
        if not isinstance(row, dict):
            raise ValueError(
                "holding must be an object"
            )

        holdings.append(
            {
                "asset": row.get("asset"),
                "quantity": row.get(
                    "quantity"
                ),
            }
        )

    cash_raw = profile.get("cash")

    if not isinstance(cash_raw, dict):
        raise ValueError(
            "cash unavailable"
        )

    cash = {
        "available_usd": cash_raw.get(
            "available_usd"
        ),
        "reserved_usd": cash_raw.get(
            "reserved_usd"
        ),
    }

    roles_raw = profile.get(
        "asset_roles"
    )

    if not isinstance(roles_raw, dict):
        raise ValueError(
            "asset_roles unavailable"
        )

    plans_raw = profile.get("plans")

    if not isinstance(plans_raw, list):
        raise ValueError(
            "plans unavailable"
        )

    plans = []

    for plan_raw in plans_raw:
        if not isinstance(plan_raw, dict):
            raise ValueError(
                "plan must be an object"
            )

        if (
            str(
                plan_raw.get("status")
            ).upper()
            != "ACTIVE"
        ):
            continue

        tranches_raw = plan_raw.get(
            "tranches",
            [],
        )

        if not isinstance(
            tranches_raw,
            list,
        ):
            raise ValueError(
                "plan tranches unavailable"
            )

        tranches = []

        for tranche_raw in tranches_raw:
            if not isinstance(
                tranche_raw,
                dict,
            ):
                raise ValueError(
                    "tranche must be an object"
                )

            conditions_raw = (
                tranche_raw.get(
                    "validity_conditions",
                    [],
                )
            )

            if not isinstance(
                conditions_raw,
                list,
            ):
                raise ValueError(
                    "validity_conditions "
                    "must be a list"
                )

            tranches.append(
                {
                    "tranche_id": (
                        tranche_raw.get(
                            "tranche_id"
                        )
                    ),
                    "budget_usd": (
                        tranche_raw.get(
                            "budget_usd"
                        )
                    ),
                    "status": (
                        tranche_raw.get(
                            "status"
                        )
                    ),
                    "validity_conditions": [
                        _bridge_capital_condition(
                            condition
                        )
                        for condition
                        in conditions_raw
                    ],
                }
            )

        plans.append(
            {
                "plan_id": plan_raw.get(
                    "plan_id"
                ),
                "asset": plan_raw.get(
                    "asset"
                ),
                "side": plan_raw.get(
                    "side"
                ),
                "status": plan_raw.get(
                    "status"
                ),
                "tranches": tranches,
            }
        )

    referenced_assets = {
        str(row.get("asset"))
        for row in holdings
        if row.get("asset") is not None
    }

    referenced_assets.update(
        str(row.get("asset"))
        for row in plans
        if row.get("asset") is not None
    )

    asset_roles = {
        str(asset): deepcopy(role)
        for asset, role in roles_raw.items()
        if str(asset) in referenced_assets
    }

    return {
        "capital_state": capital_state,
        "holdings": holdings,
        "cash": cash,
        "asset_roles": asset_roles,
        "active_plans": plans,
        "execution_authority": "USER_ONLY",
    }


def _bridge_plan_drift(
    handoff: dict[str, Any],
) -> dict[str, Any]:
    raw = handoff.get(
        "plan_drift"
    )

    if not isinstance(raw, dict):
        raise ValueError(
            "handoff plan_drift unavailable"
        )

    conditions = []

    for row in raw.get(
        "violated_conditions",
        [],
    ):
        if not isinstance(row, dict):
            continue

        conditions.append(
            {
                key: deepcopy(
                    row.get(key)
                )
                for key in (
                    "plan_id",
                    "tranche_id",
                    "field",
                    "operator",
                    "target_value",
                    "source_kind",
                )
            }
        )

    return {
        "state": raw.get("state"),
        "reason": raw.get("reason"),
        "reanalysis_required": raw.get(
            "reanalysis_required"
        ),
        "violated_conditions": conditions,
    }


def build_minimized_bridge_payload(
    pack: dict[str, Any],
    handoff: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(pack, dict):
        raise ValueError(
            "Evidence Pack must be an object"
        )

    if not isinstance(handoff, dict):
        raise ValueError(
            "GPT handoff must be an object"
        )

    if (
        handoff.get("state")
        != "GPT_HANDOFF_READY"
    ):
        raise ValueError(
            "Bridge payload requires "
            "GPT_HANDOFF_READY"
        )

    pack_hash = pack.get(
        "evidence_pack_hash"
    )

    if (
        not isinstance(pack_hash, str)
        or not pack_hash
    ):
        raise ValueError(
            "Evidence Pack hash unavailable"
        )

    if (
        handoff.get(
            "source_evidence_pack_hash"
        )
        != pack_hash
    ):
        raise ValueError(
            "handoff is not linked to "
            "current Evidence Pack"
        )

    pack_authority = pack.get(
        "authority"
    )

    if not isinstance(
        pack_authority,
        dict,
    ):
        raise ValueError(
            "Evidence Pack authority unavailable"
        )

    if (
        pack_authority.get(
            "production"
        )
        != "NOT_APPROVED"
    ):
        raise ValueError(
            "Production approval must remain "
            "NOT_APPROVED"
        )

    if (
        pack_authority.get(
            "external_action_authority"
        )
        != "NONE"
    ):
        raise ValueError(
            "Evidence Pack EAA must remain NONE"
        )

    required_handoff_authority = {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "transport_authority": "NONE",
        "transport_performed": False,
    }

    for key, expected in (
        required_handoff_authority.items()
    ):
        if handoff.get(key) != expected:
            raise ValueError(
                f"handoff {key} must remain "
                f"{expected!r}"
            )

    semantics = handoff.get(
        "reanalysis_semantics"
    )

    if not isinstance(
        semantics,
        dict,
    ):
        raise ValueError(
            "reanalysis semantics unavailable"
        )

    instruction = handoff.get(
        "instruction_for_gpt"
    )

    if (
        not isinstance(instruction, str)
        or not instruction.strip()
    ):
        raise ValueError(
            "instruction_for_gpt unavailable"
        )

    wake_raw = handoff.get("wake")

    if not isinstance(wake_raw, dict):
        raise ValueError(
            "handoff wake unavailable"
        )

    payload: dict[str, Any] = {
        "schema_version": (
            BRIDGE_PAYLOAD_SCHEMA_VERSION
        ),
        "privacy_contract_version": (
            BRIDGE_PRIVACY_CONTRACT_VERSION
        ),
        "state": (
            "BRIDGE_PAYLOAD_READY_LOCAL_ONLY"
        ),
        "event": {
            "event_id": handoff.get(
                "event_id"
            ),
            "semantic_wake_key": (
                handoff.get(
                    "semantic_wake_key"
                )
            ),
            "handoff_hash": handoff.get(
                "handoff_hash"
            ),
            "source_evidence_pack_hash": (
                pack_hash
            ),
            "source_notice_hash": (
                handoff.get(
                    "source_notice_hash"
                )
            ),
            "wake": {
                "state": wake_raw.get(
                    "state"
                ),
                "reason": wake_raw.get(
                    "reason"
                ),
                "wake_sources": deepcopy(
                    wake_raw.get(
                        "wake_sources",
                        [],
                    )
                ),
                "wake_reasons": deepcopy(
                    wake_raw.get(
                        "wake_reasons",
                        [],
                    )
                ),
            },
            "plan_drift": (
                _bridge_plan_drift(
                    handoff
                )
            ),
        },
        "market_context": (
            _bridge_market_context(
                pack
            )
        ),
        "capital_state": (
            _bridge_capital_state(
                pack.get(
                    "private_context"
                )
            )
        ),
        "analysis_contract": {
            "instruction_for_gpt": (
                instruction
            ),
            "reanalysis_semantics": (
                deepcopy(semantics)
            ),
            "source_required_inputs": (
                deepcopy(
                    handoff.get(
                        "required_inputs",
                        [],
                    )
                )
            ),
            "required_behavior": (
                deepcopy(
                    handoff.get(
                        "required_behavior",
                        [],
                    )
                )
            ),
        },
        "privacy": {
            "mode": (
                "MINIMIZED_ALLOWLIST_ONLY"
            ),
            "user_authorization_scope": (
                "ANALYSIS_AND_NOTIFICATION_ONLY"
            ),
            "raw_private_context_included": (
                False
            ),
            "full_private_profile_included": (
                False
            ),
            "filesystem_paths_included": (
                False
            ),
            "broker_or_account_identifiers_included": (
                False
            ),
            "credentials_or_secrets_included": (
                False
            ),
            "transport_selected": False,
        },
        "authority": {
            "production": "NOT_APPROVED",
            "trading_authority": "NONE",
            "external_action_authority": (
                "NONE"
            ),
            "external_action_performed": (
                False
            ),
            "transport_authority": "NONE",
            "transport_performed": False,
            "action_output": "NONE",
        },
    }

    _assert_bridge_privacy(payload)

    payload[
        "bridge_payload_hash"
    ] = _canonical_hash(payload)

    _assert_bridge_privacy(payload)

    return payload


def _assert_optional_authority(
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    expected = {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }

    for key, expected_value in expected.items():
        if (
            key in payload
            and payload.get(key) != expected_value
        ):
            raise ValueError(
                f"{label} {key} must remain {expected_value!r}"
            )


def _violated_condition_signatures(
    plan_drift: dict[str, Any],
) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []

    for plan in plan_drift.get("plans", []):
        if not isinstance(plan, dict):
            continue

        plan_id = plan.get("plan_id")

        for condition in plan.get("conditions", []):
            if not isinstance(condition, dict):
                continue

            if condition.get("evaluation") != "VIOLATED":
                continue

            signatures.append(
                {
                    "plan_id": plan_id,
                    "tranche_id": condition.get("tranche_id"),
                    "field": condition.get("field"),
                    "operator": condition.get("operator"),
                    "target_value": condition.get(
                        "target_value"
                    ),
                    "source_kind": condition.get(
                        "source_kind"
                    ),
                    "source_path": condition.get(
                        "source_path"
                    ),
                }
            )

    return sorted(
        signatures,
        key=lambda row: json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _semantic_descriptor(
    pack: dict[str, Any],
) -> dict[str, Any]:
    wake = pack.get("reanalysis_wake")
    plan_drift = pack.get("plan_drift")

    if not isinstance(wake, dict):
        raise ValueError(
            "Evidence Pack reanalysis_wake must be an object"
        )

    if not isinstance(plan_drift, dict):
        raise ValueError(
            "Evidence Pack plan_drift must be an object"
        )

    wake_sources = sorted(
        {
            str(value)
            for value in wake.get("wake_sources", [])
        }
    )

    wake_reasons = sorted(
        {
            str(value)
            for value in wake.get("wake_reasons", [])
        }
    )

    if (
        wake.get("state") == "REANALYSIS_REQUESTED"
        and not wake_reasons
    ):
        wake_reasons = [
            str(
                wake.get(
                    "reason",
                    "REANALYSIS_REQUESTED",
                )
            )
        ]

    return {
        "wake_state": wake.get("state"),
        "wake_reason": wake.get("reason"),
        "wake_sources": wake_sources,
        "wake_reasons": wake_reasons,
        "plan_drift_state": plan_drift.get("state"),
        "plan_drift_reanalysis_required": (
            plan_drift.get("reanalysis_required")
        ),
        "violated_conditions": (
            _violated_condition_signatures(
                plan_drift
            )
        ),
    }


def semantic_wake_key(
    pack: dict[str, Any],
) -> str:
    return _canonical_hash(
        _semantic_descriptor(pack)
    )


def _last_gate_record(
    ledger: RunLedger,
) -> dict[str, Any] | None:
    for row in reversed(ledger.records()):
        if row.get("record_type") in {
            HANDOFF_RECORD_TYPE,
            RESET_RECORD_TYPE,
        }:
            return row

    return None


def _base_result(
    *,
    state: str,
    append_status: str,
    event_id: str | None,
    semantic_key: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "append_status": append_status,
        "event_id": event_id,
        "semantic_wake_key": semantic_key,
        **_authority(),
    }


def run_gpt_handoff_gate(
    pack: dict[str, Any],
    notice: dict[str, Any],
    *,
    ledger_path: str | Path,
) -> dict[str, Any]:
    if not isinstance(pack, dict):
        raise ValueError(
            "Evidence Pack must be an object"
        )

    if not isinstance(notice, dict):
        raise ValueError(
            "notice must be an object"
        )

    authority = pack.get("authority")

    if not isinstance(authority, dict):
        raise ValueError(
            "Evidence Pack authority must be an object"
        )

    _assert_optional_authority(
        authority,
        label="Evidence Pack authority",
    )
    _assert_optional_authority(
        notice,
        label="notice",
    )

    pack_hash = pack.get("evidence_pack_hash")
    notice_pack_hash = notice.get(
        "source_evidence_pack_hash"
    )

    if (
        not isinstance(pack_hash, str)
        or not pack_hash
    ):
        raise ValueError(
            "Evidence Pack hash is unavailable"
        )

    if notice_pack_hash != pack_hash:
        raise ValueError(
            "notice is not linked to current Evidence Pack"
        )

    wake = pack.get("reanalysis_wake")

    if not isinstance(wake, dict):
        raise ValueError(
            "Evidence Pack reanalysis_wake must be an object"
        )

    _assert_optional_authority(
        wake,
        label="reanalysis_wake",
    )

    wake_requested = (
        wake.get("state")
        == "REANALYSIS_REQUESTED"
    )

    notice_requested = (
        notice.get("state")
        == "GPT_REANALYSIS_REQUESTED"
    )

    if wake_requested != notice_requested:
        raise ValueError(
            "wake and notice reanalysis states disagree"
        )

    ledger_file = Path(ledger_path)

    if not wake_requested:
        if not ledger_file.exists():
            return _base_result(
                state="NO_HANDOFF",
                append_status="NOOP",
                event_id=None,
                semantic_key=None,
            )

        ledger = RunLedger(ledger_file)
        validation = ledger.validate()

        if not validation.valid:
            raise ValueError(
                "GPT handoff ledger is invalid: "
                + "; ".join(validation.errors)
            )

        last = _last_gate_record(ledger)

        if (
            last is None
            or last.get("record_type")
            == RESET_RECORD_TYPE
        ):
            return _base_result(
                state="NO_HANDOFF",
                append_status="NOOP",
                event_id=None,
                semantic_key=None,
            )

        payload = last.get("payload", {})

        reset = ledger.append(
            RESET_RECORD_TYPE,
            {
                "schema_version": SCHEMA_VERSION,
                "reason": "WAKE_CLEARED",
                "prior_event_id": payload.get(
                    "event_id"
                ),
                "prior_semantic_wake_key": (
                    payload.get(
                        "semantic_wake_key"
                    )
                ),
                "source_evidence_pack_hash": (
                    pack_hash
                ),
                "source_notice_hash": notice.get(
                    "notice_hash"
                ),
                **_authority(),
            },
        )

        result = _base_result(
            state="NO_HANDOFF",
            append_status="RESET_APPENDED",
            event_id=None,
            semantic_key=None,
        )
        result["reset_record_hash"] = reset[
            "record_hash"
        ]
        return result

    descriptor = _semantic_descriptor(pack)
    semantic_key = _canonical_hash(descriptor)

    ledger = RunLedger(ledger_file)
    validation = ledger.validate()

    if not validation.valid:
        raise ValueError(
            "GPT handoff ledger is invalid: "
            + "; ".join(validation.errors)
        )

    last = _last_gate_record(ledger)

    if (
        last is not None
        and last.get("record_type")
        == HANDOFF_RECORD_TYPE
    ):
        previous_payload = last.get(
            "payload",
            {},
        )

        if (
            previous_payload.get(
                "semantic_wake_key"
            )
            == semantic_key
        ):
            result = _base_result(
                state="DUPLICATE_SKIPPED",
                append_status="DUPLICATE_SKIPPED",
                event_id=previous_payload.get(
                    "event_id"
                ),
                semantic_key=semantic_key,
            )
            result[
                "existing_record_hash"
            ] = last.get("record_hash")
            result[
                "source_evidence_pack_hash"
            ] = pack_hash
            result[
                "source_notice_hash"
            ] = notice.get("notice_hash")
            return result

    episode_anchor = (
        last.get("record_hash")
        if isinstance(last, dict)
        else GENESIS_HASH
    )

    event_id = _canonical_hash(
        {
            "semantic_wake_key": semantic_key,
            "episode_anchor": episode_anchor,
        }
    )

    plan_drift = pack["plan_drift"]

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": "GPT_HANDOFF_READY",
        "event_id": event_id,
        "semantic_wake_key": semantic_key,
        "semantic_descriptor": descriptor,
        "episode_anchor": episode_anchor,
        "source_evidence_pack_hash": pack_hash,
        "source_notice_hash": notice.get(
            "notice_hash"
        ),
        "wake": {
            "state": wake.get("state"),
            "reason": wake.get("reason"),
            "wake_sources": list(
                wake.get("wake_sources", [])
            ),
            "wake_reasons": list(
                wake.get("wake_reasons", [])
            ),
        },
        "plan_drift": {
            "state": plan_drift.get("state"),
            "reason": plan_drift.get("reason"),
            "reanalysis_required": (
                plan_drift.get(
                    "reanalysis_required"
                )
            ),
            "violated_conditions": (
                descriptor[
                    "violated_conditions"
                ]
            ),
        },
        "instruction_for_gpt": notice.get(
            "instruction_for_gpt"
        ),
        "reanalysis_semantics": (
            _reanalysis_semantics()
        ),
        "required_inputs": [
            "LATEST_EVIDENCE_PACK",
            "LATEST_CAPITAL_STATE",
            "LATEST_NOTICE",
        ],
        "required_behavior": [
            "READ_CURRENT_EVIDENCE",
            "REANALYZE",
            "ADVISE_USER_ONLY",
            "NO_EXTERNAL_ACTION",
        ],
        **_authority(),
    }

    payload["handoff_hash"] = _canonical_hash(
        payload
    )

    record = ledger.append(
        HANDOFF_RECORD_TYPE,
        payload,
    )

    result = dict(payload)
    result["append_status"] = "APPENDED"
    result["ledger_record_hash"] = record[
        "record_hash"
    ]

    return result
