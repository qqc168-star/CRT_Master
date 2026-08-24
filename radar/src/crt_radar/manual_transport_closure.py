from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib import parse as urlparse
from urllib import request as urlrequest

from .gpt_bridge_outbox import _validate_bridge_payload
from .openai_responses_adapter_contract import (
    RESPONSES_PATH,
    SMOKE_MODEL,
    build_delivery_receipt,
    build_instructions,
    build_request_envelope,
    classify_http_result,
    validate_request_envelope,
)


MANUAL_HANDOFF_VERSION = "CRT_ZERO_COST_MANUAL_HANDOFF_V0.1"
MANUAL_RECEIPT_VERSION = "CRT_ZERO_COST_MANUAL_RECEIPT_V0.1"
LOOPBACK_RECEIPT_VERSION = "CRT_ZERO_COST_LOOPBACK_ACCEPTANCE_V0.1"
MANUAL_ADAPTER_ID = "CRT_HUMAN_MEDIATED_CHATGPT_V0.1"
LOOPBACK_HOST = "127.0.0.1"
MAX_MANUAL_RESPONSE_UTF8_BYTES = 64 * 1024
MAX_LOOPBACK_RESPONSE_UTF8_BYTES = 256 * 1024
LOOPBACK_TIMEOUT_SECONDS = 5

_HANDOFF_FIELDS = {
    "schema_version",
    "state",
    "adapter_id",
    "event_id",
    "bridge_payload_hash",
    "instructions",
    "input",
    "transfer",
    "limitations",
    "authority",
    "handoff_hash",
}

_MANUAL_TRANSFER = {
    "mode": "HUMAN_COPY_PASTE",
    "destination": "USER_SELECTED_CHATGPT_SESSION",
    "program_transport": "NONE",
    "credential_required_by_program": False,
    "credential_value_included": False,
    "external_network_performed_by_program": False,
    "incremental_api_cost_by_program": "ZERO",
}

_MANUAL_LIMITATIONS = {
    "live_openai_api_transport_verified": False,
    "openai_api_account_verified": False,
    "provider_model_identity_verified": False,
    "unattended_delivery_verified": False,
    "existing_transport_boundary_completed": False,
}

_AUTHORITY = {
    "production": "NOT_APPROVED",
    "trading_authority": "NONE",
    "external_action_authority": "NONE",
    "action_output": "NONE",
}


class _NoRedirectHandler(urlrequest.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Any,
        file_pointer: Any,
        status_code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        raise ValueError("Loopback redirects are forbidden")


def _hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_hash(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a 64-char lowercase hex hash")
    return value


def _unhashed(value: dict[str, Any], hash_field: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(hash_field, None)
    return result


def build_manual_handoff(
    bridge_payload: dict[str, Any],
) -> dict[str, Any]:
    event_id, payload_hash = _validate_bridge_payload(bridge_payload)
    envelope = build_request_envelope(bridge_payload, model=SMOKE_MODEL)

    handoff = {
        "schema_version": MANUAL_HANDOFF_VERSION,
        "state": "MANUAL_HANDOFF_READY",
        "adapter_id": MANUAL_ADAPTER_ID,
        "event_id": event_id,
        "bridge_payload_hash": payload_hash,
        "instructions": build_instructions(),
        "input": envelope["request_body"]["input"],
        "transfer": dict(_MANUAL_TRANSFER),
        "limitations": dict(_MANUAL_LIMITATIONS),
        "authority": dict(_AUTHORITY),
    }
    handoff["handoff_hash"] = _hash(handoff)
    return validate_manual_handoff(handoff)


def validate_manual_handoff(
    handoff: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(handoff, dict) or set(handoff) != _HANDOFF_FIELDS:
        raise ValueError("Manual handoff field set mismatch")
    if handoff.get("schema_version") != MANUAL_HANDOFF_VERSION:
        raise ValueError("Manual handoff schema mismatch")
    if handoff.get("state") != "MANUAL_HANDOFF_READY":
        raise ValueError("Manual handoff state mismatch")
    if handoff.get("adapter_id") != MANUAL_ADAPTER_ID:
        raise ValueError("Manual adapter identity mismatch")
    if handoff.get("instructions") != build_instructions():
        raise ValueError("Manual handoff instructions mismatch")
    if handoff.get("transfer") != _MANUAL_TRANSFER:
        raise ValueError("Manual transfer contract mismatch")
    if handoff.get("limitations") != _MANUAL_LIMITATIONS:
        raise ValueError("Manual limitation contract mismatch")
    if handoff.get("authority") != _AUTHORITY:
        raise ValueError("Manual authority contract mismatch")

    serialized_input = handoff.get("input")
    if not isinstance(serialized_input, str):
        raise ValueError("Manual handoff input must be serialized text")
    try:
        bridge_payload = json.loads(serialized_input)
    except json.JSONDecodeError as exc:
        raise ValueError("Manual handoff input is not valid JSON") from exc
    event_id, payload_hash = _validate_bridge_payload(bridge_payload)
    envelope = build_request_envelope(bridge_payload, model=SMOKE_MODEL)
    if envelope["request_body"]["input"] != serialized_input:
        raise ValueError("Manual handoff input serialization mismatch")
    if handoff.get("event_id") != event_id:
        raise ValueError("Manual handoff event identity mismatch")
    if handoff.get("bridge_payload_hash") != payload_hash:
        raise ValueError("Manual handoff payload hash mismatch")

    expected_hash = _require_hash(
        handoff.get("handoff_hash"),
        "Manual handoff hash",
    )
    if _hash(_unhashed(handoff, "handoff_hash")) != expected_hash:
        raise ValueError("Manual handoff hash mismatch")
    return handoff


def render_manual_prompt(handoff: dict[str, Any]) -> str:
    validated = validate_manual_handoff(handoff)
    return "\n".join(
        [
            "CRT Zero-Cost Manual Transport Handoff V0.1",
            f"Handoff hash: {validated['handoff_hash']}",
            "",
            "Instructions:",
            validated["instructions"],
            "",
            "Minimized bridge payload:",
            validated["input"],
            "",
            "Return textual analysis only.",
            "Do not perform external actions.",
            "Do not claim this copy/paste path proves OpenAI API transport,",
            "provider model identity, or unattended delivery.",
            "",
        ]
    )


def build_manual_receipt(
    handoff: dict[str, Any],
    response_text: str,
    *,
    user_confirmed: bool,
) -> dict[str, Any]:
    validated = validate_manual_handoff(handoff)
    if user_confirmed is not True:
        raise ValueError("Explicit user transfer confirmation is required")
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("Manual response text is unavailable")
    if len(response_text.encode("utf-8")) > MAX_MANUAL_RESPONSE_UTF8_BYTES:
        raise ValueError("Manual response exceeds UTF-8 byte ceiling")

    receipt = {
        "schema_version": MANUAL_RECEIPT_VERSION,
        "state": "MANUAL_TRANSFER_ATTESTED",
        "adapter_id": MANUAL_ADAPTER_ID,
        "event_id": validated["event_id"],
        "bridge_payload_hash": validated["bridge_payload_hash"],
        "handoff_hash": validated["handoff_hash"],
        "response_text": response_text,
        "response_hash": _text_hash(response_text),
        "attestation": {
            "human_copy_paste_completed": True,
            "attested_by": "USER",
            "response_source": "USER_SELECTED_CHATGPT_SESSION",
        },
        "limitations": dict(_MANUAL_LIMITATIONS),
        "privacy": {
            "input_contract": "MINIMIZED_ALLOWLIST_ONLY",
            "response_review": "USER_REQUIRED_BEFORE_REUSE",
        },
        "authority": dict(_AUTHORITY),
    }
    receipt["receipt_hash"] = _hash(receipt)
    return validate_manual_receipt(receipt, validated)


def validate_manual_receipt(
    receipt: dict[str, Any],
    handoff: dict[str, Any],
) -> dict[str, Any]:
    validated_handoff = validate_manual_handoff(handoff)
    expected_fields = {
        "schema_version",
        "state",
        "adapter_id",
        "event_id",
        "bridge_payload_hash",
        "handoff_hash",
        "response_text",
        "response_hash",
        "attestation",
        "limitations",
        "privacy",
        "authority",
        "receipt_hash",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_fields:
        raise ValueError("Manual receipt field set mismatch")
    if receipt.get("schema_version") != MANUAL_RECEIPT_VERSION:
        raise ValueError("Manual receipt schema mismatch")
    if receipt.get("state") != "MANUAL_TRANSFER_ATTESTED":
        raise ValueError("Manual receipt state mismatch")
    if receipt.get("adapter_id") != MANUAL_ADAPTER_ID:
        raise ValueError("Manual receipt adapter mismatch")

    for field in ("event_id", "bridge_payload_hash", "handoff_hash"):
        if receipt.get(field) != validated_handoff[field]:
            raise ValueError(f"Manual receipt {field} mismatch")

    response_text = receipt.get("response_text")
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("Manual receipt response text unavailable")
    if len(response_text.encode("utf-8")) > MAX_MANUAL_RESPONSE_UTF8_BYTES:
        raise ValueError("Manual receipt response exceeds UTF-8 byte ceiling")
    if receipt.get("response_hash") != _text_hash(response_text):
        raise ValueError("Manual receipt response hash mismatch")
    if receipt.get("attestation") != {
        "human_copy_paste_completed": True,
        "attested_by": "USER",
        "response_source": "USER_SELECTED_CHATGPT_SESSION",
    }:
        raise ValueError("Manual receipt attestation mismatch")
    if receipt.get("limitations") != _MANUAL_LIMITATIONS:
        raise ValueError("Manual receipt limitations mismatch")
    if receipt.get("privacy") != {
        "input_contract": "MINIMIZED_ALLOWLIST_ONLY",
        "response_review": "USER_REQUIRED_BEFORE_REUSE",
    }:
        raise ValueError("Manual receipt privacy contract mismatch")
    if receipt.get("authority") != _AUTHORITY:
        raise ValueError("Manual receipt authority mismatch")

    expected_hash = _require_hash(
        receipt.get("receipt_hash"),
        "Manual receipt hash",
    )
    if _hash(_unhashed(receipt, "receipt_hash")) != expected_hash:
        raise ValueError("Manual receipt hash mismatch")
    return receipt


def validate_loopback_url(url: str) -> str:
    try:
        parsed = urlparse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Loopback URL is invalid") from exc
    if parsed.scheme != "http":
        raise ValueError("Loopback transport requires plain local HTTP")
    if (
        parsed.hostname != LOOPBACK_HOST
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ValueError("Loopback host must be literal 127.0.0.1 with a port")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Loopback URL user information is forbidden")
    if parsed.netloc != f"{LOOPBACK_HOST}:{port}":
        raise ValueError("Loopback network location is not canonical")
    if parsed.path != RESPONSES_PATH:
        raise ValueError("Loopback response path mismatch")
    if parsed.query or parsed.fragment:
        raise ValueError("Loopback query and fragment are forbidden")
    return url


def _post_loopback_request(
    url: str,
    envelope: dict[str, Any],
    *,
    opener: Callable[..., Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    validate_loopback_url(url)
    validated = validate_request_envelope(envelope)
    request_body = json.dumps(
        validated["request_body"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urlrequest.Request(
        url,
        data=request_body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "X-CRT-Transport-Mode": "LOOPBACK_ONLY",
        },
    )
    open_request = opener or urlrequest.build_opener(
        urlrequest.ProxyHandler({}),
        _NoRedirectHandler(),
    ).open
    with open_request(
        request,
        timeout=LOOPBACK_TIMEOUT_SECONDS,
    ) as response:
        status = int(response.getcode())
        raw = response.read(MAX_LOOPBACK_RESPONSE_UTF8_BYTES + 1)
    if len(raw) > MAX_LOOPBACK_RESPONSE_UTF8_BYTES:
        raise ValueError("Loopback response exceeds UTF-8 byte ceiling")
    if classify_http_result(status, attempt_count=1) != "SUCCESS":
        raise ValueError(f"Loopback returned terminal HTTP status {status}")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Loopback response is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Loopback response must be an object")
    return status, decoded


def _synthetic_response(request_hash: str) -> dict[str, Any]:
    return {
        "id": f"resp_loopback_{request_hash[:24]}",
        "status": "completed",
        "model": SMOKE_MODEL,
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Synthetic local loopback acceptance.",
                    }
                ],
            }
        ],
    }


def _loopback_handler(
    expected_body: dict[str, Any],
    response_body: dict[str, Any],
    audit: dict[str, Any],
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            audit["request_count"] += 1
            credential_headers = {
                "authorization",
                "api-key",
                "x-api-key",
                "openai-organization",
                "openai-project",
            }
            present_headers = {name.lower() for name in self.headers}
            audit["credential_header_included"] = bool(
                credential_headers & present_headers
            )
            audit["authorization_header_included"] = (
                "authorization" in present_headers
            )

            if self.path != RESPONSES_PATH:
                self._respond(404, {"error": "PATH_MISMATCH"})
                return
            if audit["credential_header_included"]:
                self._respond(400, {"error": "CREDENTIAL_HEADER_FORBIDDEN"})
                return
            if self.headers.get("X-CRT-Transport-Mode") != "LOOPBACK_ONLY":
                self._respond(400, {"error": "LOOPBACK_MARKER_MISSING"})
                return
            if self.headers.get("Content-Type") != (
                "application/json; charset=utf-8"
            ):
                self._respond(400, {"error": "CONTENT_TYPE_MISMATCH"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._respond(400, {"error": "CONTENT_LENGTH_INVALID"})
                return
            if content_length <= 0 or content_length > 64 * 1024:
                self._respond(400, {"error": "CONTENT_LENGTH_REJECTED"})
                return
            try:
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._respond(400, {"error": "BODY_INVALID"})
                return
            if body != expected_body:
                self._respond(400, {"error": "BODY_MISMATCH"})
                return

            audit["request_validated"] = True
            self._respond(200, response_body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def _build_loopback_receipt(
    envelope: dict[str, Any],
    *,
    status: int,
    response: dict[str, Any],
    port: int,
    audit: dict[str, Any],
) -> dict[str, Any]:
    adapter_receipt = build_delivery_receipt(
        response,
        event_id=envelope["event_id"],
        bridge_payload_hash=envelope["bridge_payload_hash"],
        request_hash=envelope["request_hash"],
    )
    receipt = {
        "schema_version": LOOPBACK_RECEIPT_VERSION,
        "state": "LOOPBACK_ACCEPTANCE_PASSED",
        "event_id": envelope["event_id"],
        "bridge_payload_hash": envelope["bridge_payload_hash"],
        "request_hash": envelope["request_hash"],
        "response_contract_receipt_hash": adapter_receipt["receipt_hash"],
        "transport": {
            "method": "POST",
            "path": RESPONSES_PATH,
            "host": LOOPBACK_HOST,
            "port": port,
            "request_count": audit["request_count"],
            "response_status_code": status,
            "attempt_count": 1,
            "local_loopback_http_performed": True,
            "external_network_performed": False,
            "live_openai_api_request_performed": False,
            "authorization_header_included": audit[
                "authorization_header_included"
            ],
            "credential_header_included": audit[
                "credential_header_included"
            ],
            "api_key_read": False,
            "incremental_api_cost": "ZERO",
        },
        "limitations": dict(_MANUAL_LIMITATIONS),
        "authority": dict(_AUTHORITY),
    }
    receipt["receipt_hash"] = _hash(receipt)
    return validate_loopback_receipt(receipt, envelope)


def validate_loopback_receipt(
    receipt: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    validated_envelope = validate_request_envelope(envelope)
    expected_fields = {
        "schema_version",
        "state",
        "event_id",
        "bridge_payload_hash",
        "request_hash",
        "response_contract_receipt_hash",
        "transport",
        "limitations",
        "authority",
        "receipt_hash",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_fields:
        raise ValueError("Loopback receipt field set mismatch")
    if receipt.get("schema_version") != LOOPBACK_RECEIPT_VERSION:
        raise ValueError("Loopback receipt schema mismatch")
    if receipt.get("state") != "LOOPBACK_ACCEPTANCE_PASSED":
        raise ValueError("Loopback receipt state mismatch")
    for field in ("event_id", "bridge_payload_hash", "request_hash"):
        if receipt.get(field) != validated_envelope[field]:
            raise ValueError(f"Loopback receipt {field} mismatch")

    transport = receipt.get("transport")
    if not isinstance(transport, dict):
        raise ValueError("Loopback receipt transport unavailable")
    port = transport.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("Loopback receipt port is invalid")
    expected_transport = {
        "method": "POST",
        "path": RESPONSES_PATH,
        "host": LOOPBACK_HOST,
        "port": port,
        "request_count": 1,
        "response_status_code": 200,
        "attempt_count": 1,
        "local_loopback_http_performed": True,
        "external_network_performed": False,
        "live_openai_api_request_performed": False,
        "authorization_header_included": False,
        "credential_header_included": False,
        "api_key_read": False,
        "incremental_api_cost": "ZERO",
    }
    if transport != expected_transport:
        raise ValueError("Loopback receipt transport contract mismatch")
    if receipt.get("limitations") != _MANUAL_LIMITATIONS:
        raise ValueError("Loopback receipt limitations mismatch")
    if receipt.get("authority") != _AUTHORITY:
        raise ValueError("Loopback receipt authority mismatch")

    response = _synthetic_response(validated_envelope["request_hash"])
    adapter_receipt = build_delivery_receipt(
        response,
        event_id=validated_envelope["event_id"],
        bridge_payload_hash=validated_envelope["bridge_payload_hash"],
        request_hash=validated_envelope["request_hash"],
    )
    if (
        receipt.get("response_contract_receipt_hash")
        != adapter_receipt["receipt_hash"]
    ):
        raise ValueError("Loopback response contract receipt mismatch")

    expected_hash = _require_hash(
        receipt.get("receipt_hash"),
        "Loopback receipt hash",
    )
    if _hash(_unhashed(receipt, "receipt_hash")) != expected_hash:
        raise ValueError("Loopback receipt hash mismatch")
    return receipt


def run_loopback_acceptance(
    bridge_payload: dict[str, Any],
) -> dict[str, Any]:
    envelope = build_request_envelope(bridge_payload, model=SMOKE_MODEL)
    response_body = _synthetic_response(envelope["request_hash"])
    audit = {
        "request_count": 0,
        "request_validated": False,
        "authorization_header_included": False,
        "credential_header_included": False,
    }
    handler = _loopback_handler(
        envelope["request_body"],
        response_body,
        audit,
    )
    server = HTTPServer((LOOPBACK_HOST, 0), handler)
    server.timeout = LOOPBACK_TIMEOUT_SECONDS
    port = int(server.server_address[1])
    thread = threading.Thread(
        target=server.handle_request,
        name="crt-loopback-once",
        daemon=True,
    )
    thread.start()
    try:
        status, response = _post_loopback_request(
            f"http://{LOOPBACK_HOST}:{port}{RESPONSES_PATH}",
            envelope,
        )
    finally:
        thread.join(LOOPBACK_TIMEOUT_SECONDS)
        server.server_close()
    if thread.is_alive():
        raise RuntimeError("Loopback server did not terminate after one request")
    if audit["request_count"] != 1 or audit["request_validated"] is not True:
        raise ValueError("Loopback request was not accepted exactly once")
    return _build_loopback_receipt(
        envelope,
        status=status,
        response=response,
        port=port,
        audit=audit,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"JSON file is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_json_no_clobber(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def prepare_manual_bundle(
    bundle_dir: str | Path,
    bridge_payload: dict[str, Any],
) -> dict[str, Any]:
    target = Path(bundle_dir)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing bundle: {target}")

    handoff = build_manual_handoff(bridge_payload)
    loopback_receipt = run_loopback_acceptance(bridge_payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent)
    )
    try:
        _write_json(staging / "manual-handoff.json", handoff)
        (staging / "manual-prompt.txt").write_text(
            render_manual_prompt(handoff),
            encoding="utf-8",
            newline="\n",
        )
        _write_json(staging / "loopback-receipt.json", loopback_receipt)
        verify_manual_bundle(staging)
        os.rename(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return verify_manual_bundle(target)


def close_manual_bundle(
    bundle_dir: str | Path,
    response_file: str | Path,
    *,
    user_confirmed: bool,
) -> dict[str, Any]:
    root = Path(bundle_dir)
    prepared = verify_manual_bundle(root)
    if prepared["state"] not in {"PREPARED", "MANUALLY_CLOSED"}:
        raise ValueError("Manual bundle is not prepared")
    handoff = _read_json(root / "manual-handoff.json")
    response_text = Path(response_file).read_text(encoding="utf-8")
    receipt = build_manual_receipt(
        handoff,
        response_text,
        user_confirmed=user_confirmed,
    )
    receipt_path = root / "manual-receipt.json"
    if receipt_path.exists():
        existing = _read_json(receipt_path)
        validate_manual_receipt(existing, handoff)
        if existing.get("receipt_hash") != receipt["receipt_hash"]:
            raise ValueError("Existing manual receipt conflicts with response")
    else:
        _write_json_no_clobber(receipt_path, receipt)
    return verify_manual_bundle(root)


def verify_manual_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    root = Path(bundle_dir)
    if not root.is_dir():
        raise ValueError(f"Manual bundle directory unavailable: {root}")
    handoff = validate_manual_handoff(
        _read_json(root / "manual-handoff.json")
    )
    expected_prompt = render_manual_prompt(handoff)
    actual_prompt = (root / "manual-prompt.txt").read_text(encoding="utf-8")
    if actual_prompt != expected_prompt:
        raise ValueError("Manual prompt does not match handoff")

    bridge_payload = json.loads(handoff["input"])
    envelope = build_request_envelope(bridge_payload, model=SMOKE_MODEL)
    loopback_receipt = validate_loopback_receipt(
        _read_json(root / "loopback-receipt.json"),
        envelope,
    )

    receipt_path = root / "manual-receipt.json"
    if receipt_path.exists():
        manual_receipt = validate_manual_receipt(
            _read_json(receipt_path),
            handoff,
        )
        state = "MANUALLY_CLOSED"
        manual_receipt_hash: str | None = manual_receipt["receipt_hash"]
    else:
        state = "PREPARED"
        manual_receipt_hash = None

    return {
        "schema_version": MANUAL_HANDOFF_VERSION,
        "state": state,
        "event_id": handoff["event_id"],
        "bridge_payload_hash": handoff["bridge_payload_hash"],
        "handoff_hash": handoff["handoff_hash"],
        "loopback_receipt_hash": loopback_receipt["receipt_hash"],
        "manual_receipt_hash": manual_receipt_hash,
        "live_openai_api_transport_verified": False,
        "unattended_delivery_verified": False,
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "incremental_api_cost_by_program": "ZERO",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CRT zero-cost manual transport closure",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare",
        help="run local loopback acceptance and create a manual handoff bundle",
    )
    prepare.add_argument("--bridge-payload", required=True)
    prepare.add_argument("--bundle-dir", required=True)

    close = commands.add_parser(
        "close",
        help="bind a manually transferred response to the handoff",
    )
    close.add_argument("--bundle-dir", required=True)
    close.add_argument("--response-file", required=True)
    close.add_argument(
        "--confirm-user-transfer",
        action="store_true",
        help="attest that the user completed copy/paste transfer",
    )

    verify = commands.add_parser(
        "verify",
        help="verify the loopback, handoff, and optional manual receipt",
    )
    verify.add_argument("--bundle-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_manual_bundle(
                args.bundle_dir,
                _read_json(Path(args.bridge_payload)),
            )
        elif args.command == "close":
            result = close_manual_bundle(
                args.bundle_dir,
                args.response_file,
                user_confirmed=args.confirm_user_transfer,
            )
        else:
            result = verify_manual_bundle(args.bundle_dir)
    except Exception as exc:
        raise SystemExit(f"BLOCKED: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
