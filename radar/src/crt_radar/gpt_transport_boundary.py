from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from .gpt_bridge_outbox import _validate_bridge_payload

BOUNDARY_SCHEMA_VERSION = "CRT_GPT_TRANSPORT_BOUNDARY_V0.1"
PENDING_REASON = "TRANSPORT_NOT_CONFIGURED"
VALID_STATES = {"PENDING", "CLAIMED", "RETRYABLE", "DELIVERED"}


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(state)
    sealed.pop("boundary_state_hash", None)
    sealed["boundary_state_hash"] = _canonical_hash(sealed)
    return sealed


def _validate_state(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("Transport boundary state must be an object")
    if state.get("schema_version") != BOUNDARY_SCHEMA_VERSION:
        raise ValueError("Transport boundary schema mismatch")

    delivery_state = state.get("state")
    if delivery_state not in VALID_STATES:
        raise ValueError("Transport boundary state is invalid")

    event_id = state.get("event_id")
    payload_hash = state.get("bridge_payload_hash")
    if not isinstance(event_id, str) or len(event_id) != 64:
        raise ValueError("Transport boundary event_id is invalid")
    if not isinstance(payload_hash, str) or len(payload_hash) != 64:
        raise ValueError("Transport boundary payload hash is invalid")

    if state.get("production") != "NOT_APPROVED":
        raise ValueError("Production approval must remain NOT_APPROVED")
    if state.get("external_action_authority") != "NONE":
        raise ValueError("External Action Authority must remain NONE")
    if state.get("action_output") != "NONE":
        raise ValueError("Action output must remain NONE")

    expected_hash = state.get("boundary_state_hash")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("Transport boundary state hash unavailable")

    unhashed = dict(state)
    unhashed.pop("boundary_state_hash", None)
    if _canonical_hash(unhashed) != expected_hash:
        raise ValueError("Transport boundary state hash mismatch")

    claim = state.get("claim")
    receipt = state.get("receipt")

    if delivery_state in {"PENDING", "RETRYABLE"}:
        if claim is not None:
            raise ValueError("Unclaimed state must not retain a claim")
        if receipt is not None:
            raise ValueError("Undelivered state must not retain a receipt")

    if delivery_state == "CLAIMED":
        if not isinstance(claim, dict):
            raise ValueError("Claimed state requires claim metadata")
        if receipt is not None:
            raise ValueError("Claimed state must not retain a receipt")
        for key in ("claim_token", "adapter_id", "claimed_at_ms", "expires_at_ms"):
            if key not in claim:
                raise ValueError(f"Claim metadata missing {key}")
        if claim["expires_at_ms"] <= claim["claimed_at_ms"]:
            raise ValueError("Claim expiry must be after claim time")

    if delivery_state == "DELIVERED":
        if claim is not None:
            raise ValueError("Delivered state must clear claim metadata")
        if not isinstance(receipt, dict) or not receipt:
            raise ValueError("Delivered state requires a receipt")

    return state


def build_pending_state(payload: dict[str, Any]) -> dict[str, Any]:
    event_id, payload_hash = _validate_bridge_payload(payload)
    return _seal_state(
        {
            "schema_version": BOUNDARY_SCHEMA_VERSION,
            "state": "PENDING",
            "reason": PENDING_REASON,
            "event_id": event_id,
            "bridge_payload_hash": payload_hash,
            "attempt_count": 0,
            "claim": None,
            "receipt": None,
            "adapter_selected": False,
            "production": "NOT_APPROVED",
            "external_action_authority": "NONE",
            "action_output": "NONE",
        }
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Unreadable JSON record: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON record is not an object: {path.name}")
    return value


def _write_no_clobber(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
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
        os.link(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def ensure_pending_boundary_state(
    state_dir: str | Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    pending = build_pending_state(payload)
    event_id = pending["event_id"]
    payload_hash = pending["bridge_payload_hash"]
    root = Path(state_dir)
    target = root / f"{event_id}.json"

    if target.exists():
        existing = _validate_state(_read_json(target))
        if existing["event_id"] != event_id:
            raise ValueError("Existing boundary event identity mismatch")
        if existing["bridge_payload_hash"] != payload_hash:
            raise ValueError(
                "Existing boundary event conflicts with outbox payload"
            )
        return {
            "state": "BOUNDARY_EXISTS",
            "event_id": event_id,
            "bridge_payload_hash": payload_hash,
            "delivery_state": existing["state"],
        }

    try:
        _write_no_clobber(target, pending)
    except FileExistsError:
        existing = _validate_state(_read_json(target))
        if existing["event_id"] != event_id:
            raise ValueError("Concurrent boundary event identity mismatch")
        if existing["bridge_payload_hash"] != payload_hash:
            raise ValueError("Concurrent boundary event conflict")
        return {
            "state": "BOUNDARY_EXISTS",
            "event_id": event_id,
            "bridge_payload_hash": payload_hash,
            "delivery_state": existing["state"],
        }

    stored = _validate_state(_read_json(target))
    if stored["event_id"] != event_id:
        raise ValueError("Boundary post-write identity mismatch")
    if stored["bridge_payload_hash"] != payload_hash:
        raise ValueError("Boundary post-write payload hash mismatch")

    return {
        "state": "BOUNDARY_PENDING_CREATED",
        "event_id": event_id,
        "bridge_payload_hash": payload_hash,
        "delivery_state": stored["state"],
    }


def sync_transport_boundary(
    outbox_dir: str | Path,
    state_dir: str | Path,
) -> dict[str, Any]:
    outbox_root = Path(outbox_dir)
    state_root = Path(state_dir)
    state_root.mkdir(parents=True, exist_ok=True)

    if not outbox_root.exists():
        return {
            "schema_version": BOUNDARY_SCHEMA_VERSION,
            "state": "SYNC_COMPLETE",
            "created": 0,
            "existing": 0,
            "events": [],
            "transport_configured": False,
            "transport_performed": False,
        }

    created = 0
    existing = 0
    events: list[dict[str, Any]] = []

    for path in sorted(outbox_root.glob("*.json")):
        payload = _read_json(path)
        event_id, _ = _validate_bridge_payload(payload)
        if path.stem != event_id:
            raise ValueError(
                "Outbox filename does not match semantic event_id"
            )

        result = ensure_pending_boundary_state(state_root, payload)
        events.append(result)
        if result["state"] == "BOUNDARY_PENDING_CREATED":
            created += 1
        else:
            existing += 1

    return {
        "schema_version": BOUNDARY_SCHEMA_VERSION,
        "state": "SYNC_COMPLETE",
        "created": created,
        "existing": existing,
        "events": events,
        "transport_configured": False,
        "transport_performed": False,
    }


def claim_delivery(
    state: dict[str, Any],
    *,
    adapter_id: str,
    now_ms: int,
    lease_ms: int,
    adapter_selected: bool,
) -> dict[str, Any]:
    current = _validate_state(dict(state))

    if not adapter_selected:
        raise ValueError("Transport adapter is not selected")
    if not isinstance(adapter_id, str) or not adapter_id.strip():
        raise ValueError("Adapter id is required")
    if lease_ms <= 0:
        raise ValueError("Claim lease must be positive")
    if current["state"] == "DELIVERED":
        raise ValueError("Delivered event cannot be claimed again")

    if current["state"] == "CLAIMED":
        claim = current["claim"]
        if now_ms < claim["expires_at_ms"]:
            raise ValueError("Transport boundary event is already claimed")

    claimed = {
        **current,
        "state": "CLAIMED",
        "reason": "ADAPTER_CLAIMED",
        "attempt_count": int(current.get("attempt_count", 0)) + 1,
        "claim": {
            "claim_token": secrets.token_hex(32),
            "adapter_id": adapter_id.strip(),
            "claimed_at_ms": int(now_ms),
            "expires_at_ms": int(now_ms) + int(lease_ms),
        },
        "receipt": None,
        "adapter_selected": True,
    }
    return _validate_state(_seal_state(claimed))


def mark_retryable(
    state: dict[str, Any],
    *,
    claim_token: str,
    reason: str,
) -> dict[str, Any]:
    current = _validate_state(dict(state))
    if current["state"] != "CLAIMED":
        raise ValueError("Only a claimed event can become retryable")
    claim = current["claim"]
    if claim.get("claim_token") != claim_token:
        raise ValueError("Claim token mismatch")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Retry reason is required")

    retryable = {
        **current,
        "state": "RETRYABLE",
        "reason": reason.strip(),
        "claim": None,
        "receipt": None,
        "adapter_selected": False,
    }
    return _validate_state(_seal_state(retryable))


def mark_delivered(
    state: dict[str, Any],
    *,
    claim_token: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    current = _validate_state(dict(state))
    if current["state"] != "CLAIMED":
        raise ValueError("Only a claimed event can become delivered")
    claim = current["claim"]
    if claim.get("claim_token") != claim_token:
        raise ValueError("Claim token mismatch")
    if not isinstance(receipt, dict) or not receipt:
        raise ValueError("Delivery receipt is required")

    delivered = {
        **current,
        "state": "DELIVERED",
        "reason": "DELIVERY_RECEIPT_RECORDED",
        "claim": None,
        "receipt": dict(receipt),
        "adapter_selected": True,
    }
    return _validate_state(_seal_state(delivered))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Maintain the local CRT GPT transport boundary state. "
            "No network transport is implemented."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync = subparsers.add_parser(
        "sync",
        help=(
            "Mirror durable outbox events into local PENDING "
            "transport-boundary state."
        ),
    )
    sync.add_argument("--outbox-dir", type=Path, required=True)
    sync.add_argument("--state-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "sync":
        result = sync_transport_boundary(
            args.outbox_dir,
            args.state_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
