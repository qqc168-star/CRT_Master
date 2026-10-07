from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = "CRT_GPT_NOTIFICATION_BOUNDARY_V0.1"
VALID_STATES = {
    "PENDING",
    "CLAIMED",
    "DELIVERED",
    "RECONCILIATION_REQUIRED",
}


def _hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def notification_id(event_id: str, receipt_hash: str) -> str:
    if len(event_id) != 64 or len(receipt_hash) != 64:
        raise ValueError("invalid notification identity input")
    return _hash({
        "event_id": event_id,
        "receipt_hash": receipt_hash,
    })


def _validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("state") != "RESPONSES_DELIVERY_RECEIPT_READY":
        raise ValueError("receipt not ready")

    if receipt.get("production") != "NOT_APPROVED":
        raise ValueError("production lock changed")
    if receipt.get("external_action_authority") != "NONE":
        raise ValueError("EAA lock changed")
    if receipt.get("action_output") != "NONE":
        raise ValueError("action output changed")

    for key in (
        "event_id",
        "bridge_payload_hash",
        "request_hash",
        "response_hash",
        "receipt_hash",
    ):
        value = receipt.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"invalid receipt field: {key}")

    if not receipt.get("response_id"):
        raise ValueError("missing response_id")
    if not isinstance(receipt.get("output_text"), str):
        raise ValueError("missing output_text")

    raw = dict(receipt)
    expected = raw.pop("receipt_hash")

    if _hash(raw) != expected:
        raise ValueError("receipt hash mismatch")

    return receipt


def _seal(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state.pop("notification_state_hash", None)
    state["notification_state_hash"] = _hash(state)
    return state


def _validate_state(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("schema mismatch")

    if state.get("state") not in VALID_STATES:
        raise ValueError("invalid state")

    if state["notification_id"] != notification_id(
        state["event_id"],
        state["receipt_hash"],
    ):
        raise ValueError("notification identity mismatch")

    raw = dict(state)
    expected = raw.pop("notification_state_hash")

    if _hash(raw) != expected:
        raise ValueError("notification state hash mismatch")

    return state


def build_pending(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt = _validate_receipt(dict(receipt))

    return _seal({
        "schema_version": SCHEMA_VERSION,
        "state": "PENDING",
        "notification_id": notification_id(
            receipt["event_id"],
            receipt["receipt_hash"],
        ),
        "event_id": receipt["event_id"],
        "receipt_hash": receipt["receipt_hash"],
        "bridge_payload_hash": receipt["bridge_payload_hash"],
        "request_hash": receipt["request_hash"],
        "response_id": receipt["response_id"],
        "response_hash": receipt["response_hash"],
        "output_text": receipt["output_text"],
        "attempt_count": 0,
        "claim_token": None,
        "presentation": None,
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "action_output": "NONE",
    })


def _write_atomic(path: Path, state: dict[str, Any]) -> None:
    state = _validate_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )

    temp = Path(temp_name)

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(
                state,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp, path)

    finally:
        temp.unlink(missing_ok=True)


def ensure_pending(
    root: str | Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    pending = build_pending(receipt)

    path = (
        Path(root)
        / f"{pending['notification_id']}.json"
    )

    if path.exists():
        existing = _validate_state(
            json.loads(path.read_text(encoding="utf-8"))
        )

        if (
            existing["receipt_hash"] != pending["receipt_hash"]
            or existing["output_text"] != pending["output_text"]
        ):
            raise ValueError("notification conflict")

        return {
            "state": "EXISTS",
            "notification_id": existing["notification_id"],
            "delivery_state": existing["state"],
        }

    _write_atomic(path, pending)

    return {
        "state": "CREATED",
        "notification_id": pending["notification_id"],
        "delivery_state": "PENDING",
    }


Presenter = Callable[[str], int]


def present(
    path: str | Path,
    presenter: Presenter,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    path = Path(path)

    current = _validate_state(
        json.loads(path.read_text(encoding="utf-8"))
    )

    if current["state"] == "DELIVERED":
        return {
            "state": "ALREADY_DELIVERED",
            "presentation_performed": False,
        }

    if current["state"] == "RECONCILIATION_REQUIRED":
        return {
            "state": "RECONCILIATION_REQUIRED",
            "presentation_performed": False,
        }

    if current["state"] == "CLAIMED":
        blocked = _seal({
            **current,
            "state": "RECONCILIATION_REQUIRED",
            "claim_token": None,
        })
        _write_atomic(path, blocked)

        return {
            "state": "RECONCILIATION_REQUIRED",
            "presentation_performed": False,
        }

    claimed = _seal({
        **current,
        "state": "CLAIMED",
        "attempt_count": current["attempt_count"] + 1,
        "claim_token": secrets.token_hex(32),
    })

    _write_atomic(path, claimed)

    try:
        result = presenter(current["output_text"])

        if result not in (1, -1):
            raise RuntimeError("popup result ambiguous")

    except Exception:
        blocked = _seal({
            **claimed,
            "state": "RECONCILIATION_REQUIRED",
            "claim_token": None,
        })

        _write_atomic(path, blocked)

        return {
            "state": "RECONCILIATION_REQUIRED",
            "presentation_performed": True,
        }

    delivered = _seal({
        **claimed,
        "state": "DELIVERED",
        "claim_token": None,
        "presentation": {
            "channel": "WSCRIPT_POPUP",
            "result": result,
            "presented_at_ms": (
                int(time.time() * 1000)
                if now_ms is None
                else int(now_ms)
            ),
        },
    })

    _write_atomic(path, delivered)

    return {
        "state": "DELIVERED",
        "presentation_performed": True,
        "result": result,
    }

def _validated_receipt_from_transport(
    transport_state_dir: str | Path,
    event_id: str,
) -> dict[str, Any]:
    from .gpt_transport_boundary import (
        _read_json as _read_transport_json,
        _validate_state as _validate_transport_state,
    )
    from .openai_responses_adapter_contract import (
        build_delivery_receipt,
        validate_request_envelope,
    )

    if (
        not isinstance(event_id, str)
        or len(event_id) != 64
        or any(c not in "0123456789abcdef" for c in event_id)
    ):
        raise ValueError("invalid event identity")

    root = Path(transport_state_dir)

    state = _validate_transport_state(
        _read_transport_json(root / f"{event_id}.json")
    )

    if state["state"] != "DELIVERED":
        raise ValueError("transport is not DELIVERED")

    evidence = _read_transport_json(
        root / "responses" / f"{event_id}.json"
    )

    request = evidence.get("request")
    response = evidence.get("response")

    if not isinstance(request, dict) or not isinstance(response, dict):
        raise ValueError("provider evidence incomplete")

    validate_request_envelope(request)

    if request["event_id"] != state["event_id"]:
        raise ValueError("request event mismatch")

    if (
        request["bridge_payload_hash"]
        != state["bridge_payload_hash"]
    ):
        raise ValueError("request payload hash mismatch")

    if state.get("request_hash") != request["request_hash"]:
        raise ValueError("request hash mismatch")

    expected = build_delivery_receipt(
        response,
        event_id=request["event_id"],
        bridge_payload_hash=request["bridge_payload_hash"],
        request_hash=request["request_hash"],
    )

    if expected != state["receipt"]:
        raise ValueError("delivery receipt mismatch")

    return _validate_receipt(expected)


def ensure_from_transport(
    transport_state_dir: str | Path,
    notification_state_dir: str | Path,
    event_id: str,
) -> dict[str, Any]:
    receipt = _validated_receipt_from_transport(
        transport_state_dir,
        event_id,
    )

    return ensure_pending(
        notification_state_dir,
        receipt,
    )

def notification_lock(
    root: str | Path,
    notification_id_value: str,
):
    from .gpt_transport_boundary import delivery_lock

    return delivery_lock(
        root,
        notification_id_value,
    )


_ensure_pending_without_process_lock = ensure_pending
_present_without_process_lock = present


def ensure_pending(
    root: str | Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    pending = build_pending(receipt)

    with notification_lock(
        root,
        pending["notification_id"],
    ) as acquired:

        if not acquired:
            return {
                "state": "BUSY",
                "notification_id":
                    pending["notification_id"],
                "delivery_state": None,
            }

        return _ensure_pending_without_process_lock(
            root,
            receipt,
        )


def windows_popup_presenter(
    text: str,
    *,
    timeout_seconds: int = 30,
) -> int:
    import shutil
    import subprocess

    powershell = shutil.which("powershell.exe")

    if not powershell:
        raise RuntimeError(
            "powershell.exe unavailable"
        )

    script = (
        '$ErrorActionPreference="Stop"; '
        '$w=New-Object -ComObject WScript.Shell; '
        '$r=$w.Popup('
        '$env:CRT_NOTIFICATION_TEXT,'
        '30,'
        '"CRT N.S.",'
        '64'
        '); '
        'Write-Output $r; '
        'if ($r -eq 1 -or $r -eq -1) '
        '{ exit 0 } else { exit 2 }'
    )

    env = os.environ.copy()
    env["CRT_NOTIFICATION_TEXT"] = text

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds + 15,
        env=env,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "Windows popup result ambiguous"
        )

    lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]

    if not lines:
        raise RuntimeError(
            "Windows popup result unavailable"
        )

    try:
        result = int(lines[-1])
    except ValueError as exc:
        raise RuntimeError(
            "Windows popup result invalid"
        ) from exc

    if result not in (1, -1):
        raise RuntimeError(
            "Windows popup was not completed"
        )

    return result


def present(
    path: str | Path,
    presenter: Presenter | None = None,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    path = Path(path)

    current = _validate_state(
        json.loads(
            path.read_text(encoding="utf-8")
        )
    )

    with notification_lock(
        path.parent,
        current["notification_id"],
    ) as acquired:

        if not acquired:
            return {
                "state": "BUSY",
                "presentation_performed": False,
            }

        selected = (
            windows_popup_presenter
            if presenter is None
            else presenter
        )

        return _present_without_process_lock(
            path,
            selected,
            now_ms=now_ms,
        )

def _assert_notification_binds_receipt(
    notification: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    expected = build_pending(receipt)

    for key in (
        "notification_id",
        "event_id",
        "receipt_hash",
        "bridge_payload_hash",
        "request_hash",
        "response_id",
        "response_hash",
        "output_text",
    ):
        if notification[key] != expected[key]:
            raise ValueError(
                "notification does not bind validated GPT delivery"
            )


def present_from_transport(
    path: str | Path,
    transport_state_dir: str | Path,
    presenter: Presenter | None = None,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    path = Path(path)

    notification = _validate_state(
        json.loads(
            path.read_text(encoding="utf-8")
        )
    )

    receipt = _validated_receipt_from_transport(
        transport_state_dir,
        notification["event_id"],
    )

    _assert_notification_binds_receipt(
        notification,
        receipt,
    )

    return present(
        path,
        presenter,
        now_ms=now_ms,
    )


def deliver_pending(
    transport_state_dir: str | Path,
    notification_state_dir: str | Path,
    presenter: Presenter | None = None,
) -> dict[str, Any]:
    root = Path(notification_state_dir)
    root.mkdir(parents=True, exist_ok=True)

    results = []

    for path in sorted(root.glob("*.json")):
        result = present_from_transport(
            path,
            transport_state_dir,
            presenter,
        )
        results.append(result)

    return {
        "state": "NOTIFICATION_SWEEP_COMPLETE",
        "count": len(results),
        "presentation_count": sum(
            1
            for item in results
            if item.get("presentation_performed") is True
        ),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Deliver durable post-GPT notifications "
            "to the interactive Windows user."
        )
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sweep = sub.add_parser("deliver-pending")

    sweep.add_argument(
        "--transport-state-dir",
        required=True,
        type=Path,
    )

    sweep.add_argument(
        "--notification-state-dir",
        required=True,
        type=Path,
    )

    args = parser.parse_args(argv)

    result = deliver_pending(
        args.transport_state_dir,
        args.notification_state_dir,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    blocked = any(
        row.get("state")
        == "RECONCILIATION_REQUIRED"
        for row in result["results"]
    )

    return int(blocked)


if __name__ == "__main__":
    raise SystemExit(main())