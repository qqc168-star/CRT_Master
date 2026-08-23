from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


OUTBOX_SCHEMA_VERSION = "CRT_LOCAL_BRIDGE_OUTBOX_V0.1"
BRIDGE_SCHEMA_VERSION = "CRT_MINIMIZED_BRIDGE_PAYLOAD_V0.1"
BRIDGE_PRIVACY_CONTRACT_VERSION = (
    "CRT_BRIDGE_PAYLOAD_PRIVACY_CONTRACT_V0.1"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_bridge_payload(
    payload: dict[str, Any],
) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Bridge payload must be an object")

    if payload.get("schema_version") != BRIDGE_SCHEMA_VERSION:
        raise ValueError("Bridge payload schema mismatch")

    if (
        payload.get("privacy_contract_version")
        != BRIDGE_PRIVACY_CONTRACT_VERSION
    ):
        raise ValueError("Bridge privacy contract mismatch")

    if payload.get("state") != "BRIDGE_PAYLOAD_READY_LOCAL_ONLY":
        raise ValueError("Bridge payload is not local-only ready")

    event = payload.get("event")
    if not isinstance(event, dict):
        raise ValueError("Bridge event unavailable")

    event_id = event.get("event_id")
    if (
        not isinstance(event_id, str)
        or _HEX64.fullmatch(event_id) is None
    ):
        raise ValueError("Bridge event_id must be a 64-char hex hash")

    payload_hash = payload.get("bridge_payload_hash")
    if (
        not isinstance(payload_hash, str)
        or _HEX64.fullmatch(payload_hash) is None
    ):
        raise ValueError("Bridge payload hash unavailable")

    unhashed = dict(payload)
    unhashed.pop("bridge_payload_hash", None)

    if _canonical_hash(unhashed) != payload_hash:
        raise ValueError("Bridge payload hash mismatch")

    authority = payload.get("authority")
    if not isinstance(authority, dict):
        raise ValueError("Bridge authority unavailable")

    required_authority = {
        "production": "NOT_APPROVED",
        "trading_authority": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "transport_authority": "NONE",
        "transport_performed": False,
        "action_output": "NONE",
    }

    for key, expected in required_authority.items():
        if authority.get(key) != expected:
            raise ValueError(
                f"Bridge authority {key} must remain {expected!r}"
            )

    privacy = payload.get("privacy")
    if not isinstance(privacy, dict):
        raise ValueError("Bridge privacy metadata unavailable")

    required_privacy = {
        "mode": "MINIMIZED_ALLOWLIST_ONLY",
        "raw_private_context_included": False,
        "full_private_profile_included": False,
        "filesystem_paths_included": False,
        "broker_or_account_identifiers_included": False,
        "credentials_or_secrets_included": False,
        "transport_selected": False,
    }

    for key, expected in required_privacy.items():
        if privacy.get(key) != expected:
            raise ValueError(
                f"Bridge privacy {key} must remain {expected!r}"
            )

    return event_id, payload_hash


def _read_existing(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(
            "Existing bridge outbox record is unreadable"
        ) from exc

    if not isinstance(value, dict):
        raise ValueError(
            "Existing bridge outbox record is not an object"
        )

    return value


def enqueue_bridge_payload(
    outbox_dir: str | Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    event_id, payload_hash = _validate_bridge_payload(payload)

    root = Path(outbox_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{event_id}.json"

    if target.exists():
        existing = _read_existing(target)
        existing_event_id, existing_hash = (
            _validate_bridge_payload(existing)
        )

        if existing_event_id != event_id:
            raise ValueError(
                "Existing outbox event identity mismatch"
            )

        if existing_hash != payload_hash:
            raise ValueError(
                "Existing outbox event conflicts with new bridge payload"
            )

        return {
            "schema_version": OUTBOX_SCHEMA_VERSION,
            "state": "DUPLICATE_SKIPPED",
            "event_id": event_id,
            "bridge_payload_hash": payload_hash,
        }

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{event_id}.",
        suffix=".tmp",
        dir=root,
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        try:
            os.link(temp_path, target)
        except FileExistsError:
            existing = _read_existing(target)
            existing_event_id, existing_hash = (
                _validate_bridge_payload(existing)
            )

            if existing_event_id != event_id:
                raise ValueError(
                    "Concurrent outbox event identity mismatch"
                )

            if existing_hash != payload_hash:
                raise ValueError(
                    "Concurrent outbox event conflict"
                )

            return {
                "schema_version": OUTBOX_SCHEMA_VERSION,
                "state": "DUPLICATE_SKIPPED",
                "event_id": event_id,
                "bridge_payload_hash": payload_hash,
            }

    finally:
        temp_path.unlink(missing_ok=True)

    stored = _read_existing(target)
    stored_event_id, stored_hash = _validate_bridge_payload(stored)

    if stored_event_id != event_id or stored_hash != payload_hash:
        raise ValueError(
            "Bridge outbox post-write validation failed"
        )

    return {
        "schema_version": OUTBOX_SCHEMA_VERSION,
        "state": "OUTBOX_ENQUEUED",
        "event_id": event_id,
        "bridge_payload_hash": payload_hash,
    }
