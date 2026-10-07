"""One-shot unattended delivery over the existing outbox/boundary contracts.

An ambiguous network outcome is never automatically replayed. A durable response
can be finalized after a crash; a lease abandoned before sending can be reclaimed.
No provider exactly-once guarantee is assumed from an idempotency header.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib import request as urlrequest

from .gpt_bridge_outbox import _validate_bridge_payload
from .gpt_handoff import _assert_bridge_privacy, expand_bridge_field_names, build_minimized_bridge_payload
from .gpt_commander_plan_closure import (
    _validate_bundle, _asset_facts, parse_commander_judgment_response,
)
from .gpt_transport_boundary import (
    _read_json, _seal_state, _validate_state, _write_no_clobber,
    claim_delivery, delivery_lock, ensure_pending_boundary_state,
    mark_delivered, mark_retryable, persist_boundary_state,
)
from .openai_responses_adapter_contract import (
    API_KEY_ENV_VAR, RESPONSES_PATH, SMOKE_MODEL, build_delivery_receipt,
    build_request_envelope, validate_request_envelope,
)

from .gpt_notification_boundary import ensure_pending

ADAPTER_ID = "CRT_OPENAI_RESPONSES_WORKER_V0.1"
LEASE_MS = 180_000
TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_PAYLOAD_FIELDS = {
    "schema_version", "privacy_contract_version", "state", "event",
    "market_context", "capital_state", "analysis_contract", "privacy",
    "authority", "bridge_payload_hash",
}
_OPTIONAL_PAYLOAD_FIELDS = {"issuer_ratio_observation"}
_SENSITIVE_TEXT = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|file://|/(?:home|Users|tmp|var)/|"
    r"\bsk-[A-Za-z0-9_-]{12,}|\bBearer\s+\S+|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE
)


def validate_transport_payload(payload: dict[str, Any]) -> tuple[str, str]:
    identity = _validate_bridge_payload(payload)
    if set(payload) - _OPTIONAL_PAYLOAD_FIELDS != _PAYLOAD_FIELDS:
        raise ValueError("Transport requires the minimized bridge field set")
    expanded = expand_bridge_field_names(payload)
    _assert_bridge_privacy(payload)
    _assert_bridge_privacy(expanded)
    if payload["authority"].get("capital_decision_authority") != "USER_ONLY":
        raise ValueError("Capital decision authority must remain USER_ONLY")
    if payload["authority"].get("machine_may_execute_trade") is not False:
        raise ValueError("Machine trade execution forbidden")

    def check(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if re.search(r"(?:credential|password|secret|account_number|broker_account|api_key|access_token)", key, re.I):
                    # Existing boolean privacy declarations are not secrets.
                    if key not in {"credentials_or_secrets_included", "broker_or_account_identifiers_included"}:
                        raise ValueError("Forbidden transport field")
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif isinstance(value, str) and _SENSITIVE_TEXT.search(value):
            raise ValueError("Forbidden transport text")
    check(payload)
    check(expanded)
    return identity


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("Provider redirects forbidden")


def send_response(envelope: dict[str, Any]) -> dict[str, Any]:
    """Send only the validated request body to the fixed TLS provider endpoint."""
    validate_request_envelope(envelope)
    decoded = json.loads(envelope["request_body"]["input"])
    validate_transport_payload(decoded["bridge_payload"] if "text" in envelope["request_body"] else decoded)
    key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if not key:
        raise ValueError("Provider credential unavailable")
    request = urlrequest.Request(
        "https://api.openai.com" + RESPONSES_PATH,
        data=json.dumps(envelope["request_body"], ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    # No ambient proxies, redirects, SDK retries, tools, or arbitrary endpoints.
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as result:
        if result.status != 200:
            raise ValueError("Provider HTTP failure")
        raw = result.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Provider response exceeds limit")
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError("Provider response is not an object")
    return response


def _receipt(response: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    return build_delivery_receipt(
        response, event_id=envelope["event_id"],
        bridge_payload_hash=envelope["bridge_payload_hash"],
        request_hash=envelope["request_hash"],
    )


def deliver_event(
    outbox_path: Path, state_dir: Path, *,
    notification_state_dir: Path | None = None,
    transport: Callable[[dict[str, Any]], dict[str, Any]] = send_response,
    now_ms: int | None = None,
    source_bundle: dict | None = None,
    current_main_sha: str | None = None,
    asset: str | None = None,
) -> dict[str, Any]:
    payload = _read_json(outbox_path)
    event_id, payload_hash = validate_transport_payload(payload)
    if outbox_path.stem != event_id:
        raise ValueError("Outbox event filename mismatch")
    # Freeze caller-owned source inputs before validation or provider dispatch.
    source_bundle = deepcopy(source_bundle)
    context = None
    now = int(time.time() * 1000) if now_ms is None else now_ms
    check_time = datetime.fromtimestamp(now / 1000, tz=timezone.utc)
    if any(value is not None for value in (source_bundle, current_main_sha, asset)):
        if source_bundle is None or current_main_sha is None or asset is None:
            raise ValueError("Structured delivery requires bundle, verified main and asset")
        _validate_bundle(source_bundle)
        if source_bundle["source_main_sha"] != current_main_sha:
            raise ValueError("Source main lineage mismatch")
        if asset not in {"MSTR", "ASST", "STRC", "SATA"}:
            raise ValueError("Unknown requested asset")
        _asset_facts(source_bundle, asset, check_time)
        expected_payload = build_minimized_bridge_payload(
            source_bundle["evidence_pack"], source_bundle["handoff"])
        if payload != expected_payload:
            raise ValueError("Source bundle does not bind this exact minimized bridge")
        context = {"source_main_sha": current_main_sha,
                   "source_bundle_hash": source_bundle["bundle_hash"], "asset": asset,
                   "posture_candidate": source_bundle["posture_gate"]["posture_candidate"]}
    envelope = build_request_envelope(payload, model=SMOKE_MODEL, judgment_context=context)

    def validated_receipt(response):
        receipt = _receipt(response, envelope)
        if context is not None:
            judgment, candidate = parse_commander_judgment_response(response,
                source_bundle=source_bundle, current_main_sha=current_main_sha,
                asset=asset, now=(datetime.now(timezone.utc) if now_ms is None else check_time))
            artifact = {"request_hash": envelope["request_hash"],
                        "response_hash": receipt["response_hash"],
                        "judgment": judgment, "candidate": candidate}
            destination = state_dir / "judgments" / f"{event_id}.json"
            if destination.exists():
                if _read_json(destination) != artifact:
                    raise ValueError("Persisted judgment mismatch")
            else:
                _write_no_clobber(destination, artifact)
        return receipt

    result = {"event_id": event_id, "transport_performed": False,
              "notification_eligible": False}
    with delivery_lock(state_dir, event_id) as acquired:
        if not acquired:
            return {**result, "state": "BUSY"}
        ensure_pending_boundary_state(state_dir, payload)
        state = _validate_state(_read_json(state_dir / f"{event_id}.json"))
        if state["event_id"] != event_id or state["bridge_payload_hash"] != payload_hash:
            raise ValueError("Boundary identity mismatch")
        evidence_dir = state_dir / "responses"
        evidence_path = evidence_dir / f"{event_id}.json"

        if state["state"] == "DELIVERED":
            evidence = _read_json(evidence_path)

            if (
                evidence["request"] != envelope
                or state["receipt"]
                != validated_receipt(evidence["response"])
            ):
                raise ValueError("Delivered evidence mismatch")

            if (
                state.get("notification_required") is True
                and notification_state_dir is not None
            ):
                ensure_pending(
                    notification_state_dir,
                    state["receipt"],
                )

            return {
                **result,
                "state": "ALREADY_DELIVERED",
            }

        if state["state"] == "CLAIMED" and now < state["claim"]["expires_at_ms"]:
            return {**result, "state": "CLAIMED"}

        # The send marker survives mark_retryable and process death. Never infer
        # that an expired claim means a provider did not receive the request.
        if state.get("request_hash"):
            if state["request_hash"] != envelope["request_hash"]:
                raise ValueError("Persisted request identity mismatch")
            if not evidence_path.exists():
                return {**result, "state": "RECONCILIATION_REQUIRED"}
            evidence = _read_json(evidence_path)
            if evidence["request"] != envelope:
                raise ValueError("Persisted request mismatch")
            try:
                receipt = validated_receipt(evidence["response"])
            except Exception:
                return {**result, "state": "RECONCILIATION_REQUIRED"}
        else:
            if evidence_path.exists():
                raise ValueError("Unbound provider evidence")
            receipt = None
            if transport is send_response and not os.environ.get(API_KEY_ENV_VAR, "").strip():
                return {**result, "state": "CREDENTIAL_UNAVAILABLE"}

        state = claim_delivery(state, adapter_id=ADAPTER_ID, now_ms=now,
                               lease_ms=LEASE_MS, adapter_selected=True)
        persist_boundary_state(state_dir, state)
        token = state["claim"]["claim_token"]
        if receipt is None:
            # Persist intent BEFORE any network call. Crash in this window blocks
            # replay conservatively; it cannot cause a duplicate provider call.
            state = _seal_state({**state, "request_hash": envelope["request_hash"],
                                 "reason": "PROVIDER_SEND_STARTED"})
            persist_boundary_state(state_dir, state)
            try:
                response = transport(envelope)
                result["transport_performed"] = True
                # Preserve the complete provider object before semantic validation,
                # including refusals, malformed judgment text and incomplete output.
                _write_no_clobber(evidence_path, {"request": envelope, "response": response})
                receipt = validated_receipt(response)
            except Exception:
                # Never persist exception text, headers, URLs, or credentials.
                state = mark_retryable(state, claim_token=token,
                                       reason="PROVIDER_RESULT_REQUIRES_RECONCILIATION")
                persist_boundary_state(state_dir, state)
                return {**result, "state": "RECONCILIATION_REQUIRED"}
        delivered = mark_delivered(
            state,
            claim_token=token,
            receipt=receipt,
        )

        delivered = _seal_state({
            **delivered,
            "notification_required":
                notification_state_dir is not None,
        })

        persist_boundary_state(
            state_dir,
            delivered,
        )

        stored = _validate_state(
            _read_json(state_dir / f"{event_id}.json")
        )

        if stored != delivered:
            raise ValueError(
                "Delivery persistence verification failed"
            )

        if notification_state_dir is not None:
            ensure_pending(
                notification_state_dir,
                receipt,
            )

        return {
            **result,
            "state": "DELIVERED",
            "notification_eligible": True,
            "receipt_hash": receipt["receipt_hash"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outbox-dir", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--notification-state-dir", type=Path)
    parser.add_argument("--event-id", help="Restrict live acceptance to one existing event")
    parser.add_argument("--source-bundle", type=Path)
    parser.add_argument("--current-main-sha", help="Independently verified source main SHA")
    parser.add_argument("--asset", choices=("MSTR", "ASST", "STRC", "SATA"))
    args = parser.parse_args(argv)
    structured = any((args.source_bundle, args.current_main_sha, args.asset))
    if structured and not all((args.source_bundle, args.current_main_sha, args.asset, args.event_id)):
        parser.error("Structured delivery requires source-bundle, current-main-sha, asset and event-id")
    bundle = _read_json(args.source_bundle) if args.source_bundle else None
    paths = sorted(args.outbox_dir.glob("*.json"))
    if args.event_id:
        if not re.fullmatch(r"[0-9a-f]{64}", args.event_id):
            parser.error("Invalid event id")
        paths = [args.outbox_dir / f"{args.event_id}.json"]
    failed = False
    for path in paths:
        try:
            result = deliver_event(
                path,
                args.state_dir,
                notification_state_dir=args.notification_state_dir,
                source_bundle=bundle,
                current_main_sha=args.current_main_sha,
                asset=args.asset,
            )
        except Exception:
            result = {"state": "VALIDATION_OR_PERSISTENCE_BLOCKED"}
        print(json.dumps(result, sort_keys=True))
        failed |= result["state"] in {"VALIDATION_OR_PERSISTENCE_BLOCKED",
                                     "CREDENTIAL_UNAVAILABLE", "RECONCILIATION_REQUIRED"}
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
