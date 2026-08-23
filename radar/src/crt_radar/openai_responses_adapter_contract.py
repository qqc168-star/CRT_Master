from __future__ import annotations

import hashlib
import json
from typing import Any

from .gpt_bridge_outbox import _validate_bridge_payload
from .gpt_handoff import (
    CAUSAL_GUARDRAILS,
    EVIDENCE_RULES,
    GOVERNANCE_GUARDRAILS,
    REANALYSIS_SEQUENCE,
)

CONTRACT_VERSION = "CRT_OPENAI_RESPONSES_ADAPTER_CONTRACT_V0.1"
RESPONSES_PATH = "/v1/responses"
API_KEY_ENV_VAR = "OPENAI_API_KEY"
MAX_OUTPUT_TOKENS = 1800
RETRYABLE_HTTP_STATUS = {408, 409, 429, 500, 502, 503, 504}


def _hash(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_instructions() -> str:
    return "\n".join(
        [
            "CRT post-wake reanalysis contract.",
            "Sequence: " + " > ".join(REANALYSIS_SEQUENCE),
            "Causal guardrails: " + " | ".join(CAUSAL_GUARDRAILS),
            "Evidence rules: " + " | ".join(EVIDENCE_RULES),
            "Governance guardrails: " + " | ".join(GOVERNANCE_GUARDRAILS),
            "Use only the supplied minimized bridge payload.",
            "Do not infer missing evidence. Do not perform external actions.",
        ]
    )


def build_request_envelope(
    bridge_payload: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    event_id, payload_hash = _validate_bridge_payload(bridge_payload)
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Responses model must be non-empty")

    envelope = {
        "contract_version": CONTRACT_VERSION,
        "transport": {
            "method": "POST",
            "path": RESPONSES_PATH,
            "auth_env_var": API_KEY_ENV_VAR,
            "secret_value_included": False,
        },
        "event_id": event_id,
        "bridge_payload_hash": payload_hash,
        "request_body": {
            "model": model.strip(),
            "instructions": build_instructions(),
            "input": json.dumps(
                bridge_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "store": False,
            "background": False,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
        "tools_allowed": False,
        "network_performed": False,
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "action_output": "NONE",
    }
    envelope["request_hash"] = _hash(envelope)
    return validate_request_envelope(envelope)


def validate_request_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Adapter contract version mismatch")

    transport = envelope.get("transport")
    body = envelope.get("request_body")
    if not isinstance(transport, dict) or not isinstance(body, dict):
        raise ValueError("Adapter envelope incomplete")

    if transport.get("method") != "POST" or transport.get("path") != RESPONSES_PATH:
        raise ValueError("Responses transport mismatch")
    if transport.get("auth_env_var") != API_KEY_ENV_VAR:
        raise ValueError("Unexpected API key environment variable")
    if transport.get("secret_value_included") is not False:
        raise ValueError("Secret values must not be included")

    if body.get("store") is not False or body.get("background") is not False:
        raise ValueError("Responses persistence/background must remain disabled")
    if "tools" in body or envelope.get("tools_allowed") is not False:
        raise ValueError("Tools are forbidden by this contract")
    if envelope.get("network_performed") is not False:
        raise ValueError("Offline contract must not perform network I/O")
    if envelope.get("production") != "NOT_APPROVED":
        raise ValueError("Production must remain NOT_APPROVED")
    if envelope.get("external_action_authority") != "NONE":
        raise ValueError("EAA must remain NONE")
    if envelope.get("action_output") != "NONE":
        raise ValueError("Action output must remain NONE")

    decoded = json.loads(body["input"])
    event_id, payload_hash = _validate_bridge_payload(decoded)
    if event_id != envelope.get("event_id"):
        raise ValueError("Event identity mismatch")
    if payload_hash != envelope.get("bridge_payload_hash"):
        raise ValueError("Payload hash mismatch")

    expected = envelope.get("request_hash")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Request hash unavailable")
    unhashed = dict(envelope)
    unhashed.pop("request_hash", None)
    if _hash(unhashed) != expected:
        raise ValueError("Request hash mismatch")
    return envelope


def classify_http_result(
    status_code: int,
    *,
    attempt_count: int,
    max_attempts: int = 3,
) -> str:
    if 200 <= status_code < 300:
        return "SUCCESS"
    if status_code in RETRYABLE_HTTP_STATUS and attempt_count < max_attempts:
        return "RETRYABLE"
    return "TERMINAL"


def build_delivery_receipt(
    response: dict[str, Any],
    *,
    event_id: str,
    bridge_payload_hash: str,
    request_hash: str,
) -> dict[str, Any]:
    if response.get("status") != "completed":
        raise ValueError("Responses result is not completed")
    response_id = response.get("id")
    model = response.get("model")
    output = response.get("output")
    if not isinstance(response_id, str) or not response_id:
        raise ValueError("Response id unavailable")
    if not isinstance(model, str) or not model:
        raise ValueError("Response model unavailable")
    if not isinstance(output, list):
        raise ValueError("Response output unavailable")

    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)

    output_text = "\n".join(chunks).strip()
    if not output_text:
        raise ValueError("Response output text unavailable")

    receipt = {
        "contract_version": CONTRACT_VERSION,
        "state": "RESPONSES_DELIVERY_RECEIPT_READY",
        "event_id": event_id,
        "bridge_payload_hash": bridge_payload_hash,
        "request_hash": request_hash,
        "response_id": response_id,
        "response_status": "completed",
        "model": model,
        "response_hash": _hash(response),
        "output_text": output_text,
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "action_output": "NONE",
    }
    receipt["receipt_hash"] = _hash(receipt)
    return receipt
