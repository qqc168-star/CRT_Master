from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .run_ledger import GENESIS_HASH, RunLedger


SCHEMA_VERSION = "CRT_GPT_HANDOFF_V0.1"
HANDOFF_RECORD_TYPE = "GPT_HANDOFF"
RESET_RECORD_TYPE = "GPT_HANDOFF_RESET"


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
