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

    if "capital_validation" in receipt:
        from .capital_decision_closure import render
        if receipt["output_text"] != render(receipt["capital_validation"]):
            raise ValueError("capital presentation mismatch")

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
        **({"capital_validation": receipt["capital_validation"]} if "capital_validation" in receipt else {}),
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


def _current_capital_qualification(pack: dict | None, *, at_ms: int) -> dict[str, Any]:
    """Verify the independent current daily observation before historical advice."""
    from .capital_decision_closure import digest
    from .broker_capital_observation import BLOCKED_BROKER_REASONS, reconcile_capital
    result = {"state": "BLOCKED", "reason": "CURRENT_CAPITAL_STATE_REQUIRED"}
    if not isinstance(pack, dict):
        return result
    try:
        if digest({k: v for k, v in pack.items() if k != "evidence_pack_hash"}) != pack.get("evidence_pack_hash"):
            raise ValueError("CURRENT_CAPITAL_EVIDENCE_HASH_INVALID")
        generated = pack["generated_at_ms"]
        if type(generated) is not int or type(at_ms) is not int or not 0 < generated <= at_ms:
            raise ValueError("CURRENT_CAPITAL_EVIDENCE_CLOCK_INVALID")
        reconciliation = pack["private_context"]["profile"]["capital_reconciliation"]
        observation = reconciliation.get("broker_observed")
        # A failed capture contains no broker facts. Preserve its recorded,
        # allowlisted failure reason rather than replace it with missing data.
        if (observation is None and reconciliation.get("state") == "BLOCKED"
                and reconciliation.get("reason") in BLOCKED_BROKER_REASONS):
            observation = {"capture_failed": True, "reason": reconciliation["reason"]}
        intent = reconciliation.get("user_confirmed")
        if reconcile_capital(observation, intent, at_ms=generated) != reconciliation:
            raise ValueError("CURRENT_CAPITAL_RECONCILIATION_MISMATCH")
        checked = reconcile_capital(observation, intent, at_ms=at_ms)
        return {"state": checked["state"], "reason": checked["reason"],
                "evidence_pack_hash": pack["evidence_pack_hash"],
                "capital_snapshot_hash": digest(checked["broker_observed"]),
                "broker_observed": checked["broker_observed"],
                "user_confirmed": checked["user_confirmed"],
                "full_decision_intent": pack["private_context"]["profile"].get("full_decision_intent")}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        result["reason"] = str(exc) if isinstance(exc, ValueError) else "CURRENT_CAPITAL_STATE_INVALID"
        return result


def _record_capital_qualification(path: Path, current: dict, qualification: dict,
                                  *, current_recommendation: bool, invalidated: bool = False) -> dict:
    """Mutable presentation status only; the receipt-bound advice stays intact."""
    status = {
        "state": qualification["state"], "reason": qualification["reason"],
        "recommendation_state": "CURRENT" if current_recommendation else "NOT_CURRENT",
        "invalidated": invalidated,
        "message": ("本資本建議仍須依原契約及有效期驗證。" if current_recommendation else
                    f"本次資本資料為 {qualification['state']}（資料資格），原因：{qualification['reason']}。"
                    "此舊資本建議不得作為當前合格建議使用；等待補齊證據並重新驗證，沒有交易指令。"),
    }
    status["status_hash"] = _hash(status)
    if current.get("current_qualification") != status:
        current = _seal({**current, "current_qualification": status})
        _write_atomic(path, current)
    return current


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
    *,
    capital: bool = False,
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
    if capital:
        from .capital_decision_closure import FULL_REQUEST_VERSION
        root = root / FULL_REQUEST_VERSION

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

    if "capital_source" in request:
        from .capital_decision_closure import validated_receipt
        artifact = _read_transport_json(root / "recommendations" / f"{event_id}.json")
        expected = validated_receipt(response, request,
            at_ms=artifact["capital_validation"]["evaluated_at_ms"])
        if artifact != expected:
            raise ValueError("capital artifact mismatch")

    if expected != state["receipt"]:
        raise ValueError("delivery receipt mismatch")

    return _validate_receipt(expected)


def ensure_from_transport(
    transport_state_dir: str | Path,
    notification_state_dir: str | Path,
    event_id: str,
    *,
    capital: bool = False,
) -> dict[str, Any]:
    receipt = _validated_receipt_from_transport(
        transport_state_dir,
        event_id,
        capital=capital,
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
    current_capital_source: dict | None = None,
    current_capital_state: dict | None = None,
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

        if "capital_validation" in current:
            from .capital_decision_closure import assert_current, render
            evaluated_at = int(time.time() * 1000) if now_ms is None else now_ms
            qualification = _current_capital_qualification(current_capital_state, at_ms=evaluated_at)
            if current_capital_state is None:
                return {"state": "CURRENT_CAPITAL_STATE_REQUIRED", "presentation_performed": False}
            if current_capital_source is None:
                if qualification["state"] != "AVAILABLE":
                    _record_capital_qualification(path, current, qualification,
                                                  current_recommendation=False, invalidated=True)
                    return {"state": "CAPITAL_RECOMMENDATION_NOT_CURRENT", "reason": qualification["reason"],
                            "presentation_performed": False}
                return {"state": "CURRENT_CAPITAL_SOURCE_REQUIRED", "presentation_performed": False}
            validated = current["capital_validation"]
            belongs_to_current = (
                validated.get("capital_snapshot_hash") == qualification.get("capital_snapshot_hash")
                and validated.get("evidence_lineage") == qualification.get("evidence_pack_hash")
            )
            previously_invalidated = current.get("current_qualification", {}).get("invalidated") is True
            if qualification["state"] == "AVAILABLE":
                # Clock refreshes do not change capital facts. A fresh qualified
                # pack still cannot lend its status to a different old source.
                def facts(value, clocks):
                    return ({k: v for k, v in value.items() if k not in clocks}
                            if isinstance(value, dict) else value)
                source_intent = current_capital_source.get("user_intent")
                if (facts(qualification.get("broker_observed"), {"observed_at_ms", "started_at_ms", "observation_hash"})
                        != facts(current_capital_source.get("broker_observation"), {"observed_at_ms", "started_at_ms", "observation_hash"})
                        or facts(qualification.get("full_decision_intent"), {"confirmed_at_ms"})
                        != facts(source_intent, {"confirmed_at_ms"})
                        or (isinstance(source_intent, dict)
                            and (qualification.get("user_confirmed") or {}).get("reserved_usd")
                            != source_intent.get("reserved_usd"))):
                    qualification = {**qualification, "reason": "CAPITAL_RECOMMENDATION_SUPERSEDED"}
                    previously_invalidated = True
            if ((qualification["state"] != "AVAILABLE" and not belongs_to_current)
                    or previously_invalidated):
                if (previously_invalidated and qualification["state"] == "AVAILABLE"
                        and qualification["reason"] != "CAPITAL_RECOMMENDATION_SUPERSEDED"):
                    qualification = {**qualification, "reason": "CAPITAL_RECOMMENDATION_REJUDGMENT_REQUIRED"}
                _record_capital_qualification(path, current, qualification,
                                              current_recommendation=False, invalidated=True)
                return {"state": "CAPITAL_RECOMMENDATION_NOT_CURRENT", "reason": qualification["reason"],
                        "presentation_performed": False}
            try:
                assert_current(current["capital_validation"], current_capital_source,
                    at_ms=evaluated_at)
                if current["output_text"] != render(current["capital_validation"]):
                    raise ValueError("capital presentation mismatch")
            except (ValueError, KeyError, TypeError) as exc:
                qualification = {**qualification, "reason": str(exc)}
                _record_capital_qualification(path, current, qualification,
                                              current_recommendation=False, invalidated=True)
                return {"state": "CAPITAL_RECOMMENDATION_NOT_CURRENT", "reason": qualification["reason"],
                        "presentation_performed": False}
            _record_capital_qualification(path, current, qualification, current_recommendation=True)

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
    if notification.get("capital_validation") != expected.get("capital_validation"):
        raise ValueError("capital notification does not bind validated delivery")


def present_from_transport(
    path: str | Path,
    transport_state_dir: str | Path,
    presenter: Presenter | None = None,
    *,
    now_ms: int | None = None,
    current_capital_source: dict | None = None,
    current_capital_state: dict | None = None,
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
        capital="capital_validation" in notification,
    )

    _assert_notification_binds_receipt(
        notification,
        receipt,
    )

    return present(
        path,
        presenter,
        now_ms=now_ms,
        current_capital_source=current_capital_source,
        current_capital_state=current_capital_state,
    )


def deliver_pending(
    transport_state_dir: str | Path,
    notification_state_dir: str | Path,
    presenter: Presenter | None = None,
    *,
    current_capital_source: dict | None = None,
    current_capital_state: dict | None = None,
) -> dict[str, Any]:
    root = Path(notification_state_dir)
    root.mkdir(parents=True, exist_ok=True)

    results = []

    for path in sorted(root.glob("*.json")):
        result = present_from_transport(
            path,
            transport_state_dir,
            presenter,
            current_capital_source=current_capital_source,
            current_capital_state=current_capital_state,
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
    sweep.add_argument("--capital-source", type=Path)
    sweep.add_argument("--capital-state", type=Path,
                       help="The current sealed daily Evidence Pack, never a historical event source.")

    args = parser.parse_args(argv)

    result = deliver_pending(
        args.transport_state_dir,
        args.notification_state_dir,
        current_capital_source=json.loads(args.capital_source.read_text(encoding="utf-8")) if args.capital_source else None,
        current_capital_state=json.loads(args.capital_state.read_text(encoding="utf-8")) if args.capital_state else None,
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
