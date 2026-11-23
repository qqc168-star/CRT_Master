"""One-shot unattended delivery over the existing outbox/boundary contracts.

An ambiguous network outcome is never automatically replayed. A durable response
can be finalized after a crash; a lease abandoned before sending can be reclaimed.
No provider exactly-once guarantee is assumed from an idempotency header.
"""
from __future__ import annotations

import argparse
import hashlib
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import re
import time
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib import request as urlrequest
from urllib.error import HTTPError

from .gpt_bridge_outbox import (_validate_bridge_payload, canonical_bytes, build_transfer_manifest,
    receive_transfer_part, reassemble_transfer)
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
INLINE_REQUEST_BYTES = 64 * 1024  # Routing threshold, never a total-data ceiling.
UPLOAD_PART_BYTES = 63 * 1024     # Leaves room for multipart request headers.
INPUT_TRANSFER_ATTEMPTS = 3
_PAYLOAD_FIELDS = {
    "schema_version", "privacy_contract_version", "state", "event",
    "market_context", "capital_state", "analysis_contract", "privacy",
    "authority", "bridge_payload_hash",
}
_OPTIONAL_PAYLOAD_FIELDS = {"issuer_ratio_observation"}
_SENSITIVE_TEXT = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|file://|/(?:home|Users|tmp|var)/|"
    r"\bsk-[A-Za-z0-9_-]{12,}|\bBearer\s+\S+|"
    r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE
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


class _ProviderHTTPResponse(dict):
    """In-process provenance for the shared HTTP boundary, never provider text."""


def _requires_capital_contract(payload: dict[str, Any]) -> bool:
    expanded = expand_bridge_field_names(payload)
    return (expanded["analysis_contract"].get("delivery_scope") == "FULL_DECISION_OFFLINE"
            or "BROKER_CAPITAL_STATE" in expanded["event"].get("wake", {}).get("wake_sources", []))


def send_response(envelope: dict[str, Any], *, transfer_root=None, before_inference=None) -> dict[str, Any]:
    """Send only the validated request body to the fixed TLS provider endpoint."""
    validate_request_envelope(envelope)
    if "capital_source" in envelope:
        raise ValueError("Capital model delivery requires independent approval; OFFLINE_ONLY")
    return _post_response(envelope, transfer_root=transfer_root, before_inference=before_inference)


class InputTransferPending(Exception):
    """No model request was started; the input journal can safely resume."""


def _transfer_journal(path, state):
    state = dict(state)
    state.pop("journal_hash", None)
    state["journal_hash"] = hashlib.sha256(canonical_bytes(state)).hexdigest()
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".upload-")
    try:
        with os.fdopen(fd,"wb") as handle:
            handle.write(canonical_bytes(state));handle.flush();os.fsync(handle.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def _upload_response_input(raw, *, opener, key, root, part_bytes=UPLOAD_PART_BYTES):
    """Official Uploads parts -> complete -> downloaded SHA256 -> input_file.

    Only byte transfer retries here. The inference POST is never retried.
    A lost part acknowledgement can leave an unused server part; the committed
    ordered manifest includes exactly one part per position, never extra data.
    """
    manifest, chunks = build_transfer_manifest(raw,part_bytes=part_bytes)
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    for digest,data in chunks.items():
        receive_transfer_part(root,manifest,digest,data)
    if reassemble_transfer(root,manifest)!=raw:
        raise ValueError("Input transfer local reassembly mismatch")
    journal=root/(manifest["manifest_hash"]+".json")
    if journal.exists():
        state=_read_json(journal); check=dict(state); recorded=check.pop("journal_hash",None)
        if (hashlib.sha256(canonical_bytes(check)).hexdigest()!=recorded
                or state.get("manifest")!=manifest):
            raise ValueError("Input transfer journal integrity invalid")
    else:
        state={"manifest":manifest,"parts":{},"attempt_history":[]}
    filename="crt-"+manifest["sha256"]+".txt"

    def call(path, data=None, content_type="application/json", *, binary=False, method="POST"):
        if not (path=="/v1/uploads" or re.fullmatch(r"/v1/uploads/upload_[A-Za-z0-9_-]+/(?:parts|complete)",path)
                or path=="/v1/files?purpose=assistants&limit=100&order=desc"
                or re.fullmatch(r"/v1/files/file[-_][A-Za-z0-9_-]+/content",path)):
            raise ValueError("Input transfer endpoint forbidden")
        request=urlrequest.Request("https://api.openai.com"+path,data=data,
            headers={"Authorization":"Bearer "+key,"Content-Type":content_type},method=method)
        last=None
        for _ in range(INPUT_TRANSFER_ATTEMPTS):
            try:
                with opener.open(request,timeout=TIMEOUT_SECONDS) as result:
                    if result.status!=200: raise ValueError("Input transfer HTTP failure")
                    body=result.read((len(raw) if binary else MAX_RESPONSE_BYTES)+1)
                if binary:
                    if len(body)!=len(raw) or hashlib.sha256(body).hexdigest()!=manifest["sha256"]:
                        raise ValueError("Remote input reassembly SHA256 mismatch")
                    return body
                return json.loads(body)
            except HTTPError as exc:
                if exc.code==413: raise
                if exc.code not in {408,429} and exc.code<500: raise
                last=exc
            except (TimeoutError,ConnectionError,OSError) as exc:
                last=exc
            except ValueError as exc:
                if not binary:raise
                last=exc
        raise InputTransferPending("INPUT_PART_TRANSFER_INCOMPLETE") from last

    if state.get("file_id"):
        try:
            call("/v1/files/"+state["file_id"]+"/content",binary=True,method="GET")
            return state["file_id"]
        except HTTPError as exc:
            if exc.code!=404:raise
            state["attempt_history"].append({k:state[k] for k in ("upload_id","file_id","expires_at","parts")})
            state.pop("file_id");state.pop("upload_id");state["expires_at"]=0;state["parts"]={}
    if state.get("expires_at",0)<=time.time():
        if state.get("upload_id"):
            state["attempt_history"].append({k:state[k] for k in ("upload_id","expires_at","parts")})
        created=call("/v1/uploads",canonical_bytes({"purpose":"assistants","filename":filename,
            "bytes":len(raw),"mime_type":"text/plain","expires_after":{"anchor":"created_at","seconds":3600}}))
        upload_id=created.get("id")
        if (not isinstance(upload_id,str) or re.fullmatch(r"upload_[A-Za-z0-9_-]+",upload_id) is None
                or type(created.get("expires_at")) not in (int,float) or created["expires_at"]<=time.time()):
            raise ValueError("Upload identity/expiry invalid")
        state.update(upload_id=upload_id,expires_at=created["expires_at"],parts={})
        _transfer_journal(journal,state)
    upload_id=state["upload_id"]
    for row in manifest["parts"]:
        digest=row["sha256"]; data=chunks[digest]; position=str(row["index"])
        if position in state["parts"]:
            ack=state["parts"][position]
            if ack.get("sha256")!=digest or ack.get("bytes")!=len(data):
                raise ValueError("Input part acknowledgement mismatch")
            continue
        boundary="CRT-"+digest
        body=("--"+boundary+'\r\nContent-Disposition: form-data; name="data"; filename="part.bin"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n').encode()+data+("\r\n--"+boundary+"--\r\n").encode()
        ack=call("/v1/uploads/"+upload_id+"/parts",body,"multipart/form-data; boundary="+boundary)
        if (not isinstance(ack.get("id"),str) or re.fullmatch(r"part_[A-Za-z0-9_-]+",ack["id"]) is None
                or ack.get("upload_id")!=upload_id):
            raise ValueError("Input part server identity invalid")
        state["parts"][position]={"id":ack["id"],"sha256":digest,"bytes":len(data),"acknowledged_at_ms":int(time.time()*1000)}
        _transfer_journal(journal,state)
    try:
        completed=call("/v1/uploads/"+upload_id+"/complete",canonical_bytes({
            "part_ids":[state["parts"][str(p["index"])]["id"] for p in manifest["parts"]],
            "md5":hashlib.md5(raw,usedforsecurity=False).hexdigest()}))
    except (InputTransferPending,HTTPError):
        # Completion may have succeeded despite a lost acknowledgement. Never
        # infer success from the filename: download and verify the entire file.
        listing=call("/v1/files?purpose=assistants&limit=100&order=desc",method="GET")
        for item in listing.get("data",[]):
            file_id=item.get("id")
            if (item.get("filename")==filename and item.get("bytes")==len(raw)
                    and isinstance(file_id,str) and re.fullmatch(r"file[-_][A-Za-z0-9_-]+",file_id)):
                call("/v1/files/"+file_id+"/content",binary=True,method="GET")
                completed={"id":upload_id,"status":"completed","file":{"id":file_id}}
                break
        else:
            raise InputTransferPending("INPUT_COMPLETION_NOT_RECONCILED")
    file_id=(completed.get("file") or {}).get("id")
    if (completed.get("status")!="completed" or completed.get("id")!=upload_id
            or not isinstance(file_id,str) or re.fullmatch(r"file[-_][A-Za-z0-9_-]+",file_id) is None):
        raise ValueError("Input upload not completed")
    call("/v1/files/"+file_id+"/content",binary=True,method="GET")
    state["file_id"]=file_id;state["remote_sha256_verified"]=manifest["sha256"]
    state["verified_at_ms"]=int(time.time()*1000)
    _transfer_journal(journal,state)
    return file_id


def _post_response(envelope: dict[str, Any], *, transfer_root=None, before_inference=None, force_upload=False) -> dict[str, Any]:
    """Shared fixed-endpoint HTTP implementation; callers own authorization.

    The normal sender above continues to reject capital. The repository-only
    controlled acceptance entry is the sole additional caller and checks an
    exact synthetic request plus one-shot human approval before reaching here.
    """
    validate_request_envelope(envelope)
    decoded = json.loads(envelope["request_body"]["input"])
    payload = (envelope["capital_bridge_payload"] if "capital_source" in envelope else
               decoded["bridge_payload"] if "text" in envelope["request_body"] else decoded)
    validate_transport_payload(payload)
    if _requires_capital_contract(payload) and "capital_source" not in envelope:
        raise ValueError("Capital wake/full decision cannot be downgraded to Smoke; capital source required")
    key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if not key:
        raise ValueError("Provider credential unavailable")
    body=deepcopy(envelope["request_body"])
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect())
    uploaded = force_upload or len(canonical_bytes(body))>INLINE_REQUEST_BYTES
    if uploaded:
        with tempfile.TemporaryDirectory(prefix="crt-input-") if transfer_root is None else _existing_transfer_root(transfer_root) as root:
            part_bytes=UPLOAD_PART_BYTES
            while True:
                try:
                    file_id=_upload_response_input(body["input"].encode("utf-8"),opener=opener,key=key,root=root,part_bytes=part_bytes)
                    break
                except HTTPError as exc:
                    if exc.code==413 and part_bytes>1024:
                        part_bytes//=2
                        continue
                    raise InputTransferPending("INPUT_SERVICE_CAPACITY_PENDING") from exc
                except (InputTransferPending,ValueError,OSError) as exc:
                    raise InputTransferPending("INPUT_INTEGRITY_OR_TRANSFER_PENDING") from exc
            body["input"]=[{"role":"user","content":[{"type":"input_file","file_id":file_id},
                {"type":"input_text","text":"Use the complete attached CRT JSON evidence, including exact references and all blockers. No omitted or inferred evidence."}]}]
    request = urlrequest.Request(
        "https://api.openai.com" + RESPONSES_PATH,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    # No ambient proxies, redirects, SDK retries, tools, or arbitrary endpoints.
    if before_inference is not None:
        before_inference()
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as result:
            if result.status != 200:
                raise ValueError("Provider HTTP failure")
            raw = result.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code==413:
            if not uploaded:
                return _post_response(envelope,transfer_root=transfer_root,
                    before_inference=before_inference,force_upload=True)
            raise InputTransferPending("PROVIDER_CONTEXT_CAPACITY_PENDING_NO_EVIDENCE_DROPPED") from exc
        raise
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Provider response exceeds limit")
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError("Provider response is not an object")
    return _ProviderHTTPResponse(response)


@contextmanager
def _existing_transfer_root(root):
    Path(root).mkdir(parents=True,exist_ok=True)
    yield root


def _receipt(response: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    return build_delivery_receipt(
        response, event_id=envelope["event_id"],
        bridge_payload_hash=envelope["bridge_payload_hash"],
        request_hash=envelope["request_hash"],
    )


def _capital_blocked_review(response: dict[str, Any], envelope: dict[str, Any], *,
                            at_ms: int, failure: Exception) -> dict[str, Any]:
    """Disclose a bound rejected assessment without issuing an advice receipt.

    Provider text is rendered only after independent shape/source validation.
    Exception text, provider metadata and unauthenticated response fields never
    enter the visible result. This does not change delivery or notification state.
    """
    from .capital_decision_closure import assess_response, render

    reason = str(failure)
    if reason != "CAPITAL_RECOMMENDATION_NOT_VALIDATED" and not re.fullmatch(
            r"VALUATION_EVIDENCE_UNQUALIFIED:(?:MSTR|ASST)", reason):
        reason = "CAPITAL_RESPONSE_REJECTED"
    result = {"qualified": False, "capital_decision_state": "BLOCKED",
              "reason": reason, "assessment_available": False,
              "message": "資本模型回應未通過驗證；沒有合格資本建議，不得依此交易。"}
    try:
        validation = assess_response(response, envelope, at_ms=at_ms)
        items = [{"qualified": False, "capital_decision_state": "BLOCKED",
                  **{key: deepcopy(item[key]) for key in (
            "decision_scope", "asset", "action", "validation_state", "blockers",
            "contradictions", "invalidation")}}
            for item in validation["items"]]
        # Recover only an exact known failure code matched to a source-bound
        # scope. Never disclose general exception text or unauthenticated data.
        comparison_failures = [item for item in validation.get("reasoning_review", {}).get("items", [])
            if str(failure) == "INVESTMENT_COMPARISON_NOT_SOURCE_SUPPORTED:" + item["decision_scope"]
            and item["reasoning_support"]["cash_comparison"]["state"] == "INSUFFICIENT_EVIDENCE"]
        trusted_reason = ("INVESTMENT_COMPARISON_NOT_SOURCE_SUPPORTED:" + comparison_failures[0]["decision_scope"]
                          if comparison_failures else reason)
        message = "此為未合格評估揭露，並非合格資本建議；本次完整決策為 BLOCKED，不得依此交易。\n"
        if any(item["validation_state"] == "VALIDATED" for item in validation["items"]):
            message += "以下 VALIDATED 僅表示原財務／來源檢查狀態，不代表本次完整決策或投資推理合格。\n"
        message += render(validation).replace("美股範圍投資組合資本建議；", "美股範圍資本評估紀錄；", 1)
        if _SENSITIVE_TEXT.search(message) or _SENSITIVE_TEXT.search(json.dumps(items, ensure_ascii=False)):
            return result
    except Exception:
        return result
    return {**result, "reason": trusted_reason, "assessment_available": True, "items": items, "message": message}


def deliver_event(
    outbox_path: Path, state_dir: Path, *,
    notification_state_dir: Path | None = None,
    transport: Callable[[dict[str, Any]], dict[str, Any]] = send_response,
    now_ms: int | None = None,
    source_bundle: dict | None = None,
    current_main_sha: str | None = None,
    asset: str | None = None,
    capital_source: dict | None = None,
) -> dict[str, Any]:
    payload = _read_json(outbox_path)
    event_id, payload_hash = validate_transport_payload(payload)
    if outbox_path.stem != event_id:
        raise ValueError("Outbox event filename mismatch")
    if _requires_capital_contract(payload) and capital_source is None:
        raise ValueError("Capital wake/full decision cannot be downgraded to Smoke; capital source required")
    # Freeze caller-owned source inputs before validation or provider dispatch.
    source_bundle = deepcopy(source_bundle)
    context = None
    now = int(time.time() * 1000) if now_ms is None else now_ms
    check_time = datetime.fromtimestamp(now / 1000, tz=timezone.utc)
    if capital_source is not None:
        if transport is send_response:
            raise ValueError("Capital model delivery requires independent approval; OFFLINE_ONLY")
        if source_bundle is not None or asset is not None:
            raise ValueError("Capital and Commander sources must remain separate")
        if capital_source.get("source_main_sha") != current_main_sha:
            raise ValueError("Capital source main lineage mismatch")
    elif any(value is not None for value in (source_bundle, current_main_sha, asset)):
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
    if capital_source is not None:
        from .capital_decision_closure import FULL_REQUEST_VERSION, build_envelope, build_projection
        if context is not None:
            raise ValueError("Capital and Commander requests are distinct contracts")
        build_projection(payload, capital_source, at_ms=now)
        envelope = build_envelope(payload, deepcopy(capital_source), at_ms=capital_source["task"]["as_of_ms"], full_decision=True)
        # Keep Smoke's paths stable; capital shares the same durable machinery
        # inside a contract namespace, including locks, responses and artifacts.
        legacy_state = state_dir / f"{event_id}.json"
        legacy_response = state_dir / "responses" / f"{event_id}.json"
        legacy_hashes = {envelope["request_hash"]}
        if legacy_state.exists():
            from .capital_decision_closure import _build_envelope
            legacy_hashes.add(_build_envelope(payload, capital_source,
                at_ms=capital_source["task"]["as_of_ms"], full_decision=True,
                legacy_references=True)["request_hash"])
            legacy_hashes.add(_build_envelope(payload, capital_source,
                at_ms=capital_source["task"]["as_of_ms"], full_decision=True,
                legacy_semantics=True)["request_hash"])
        if ((legacy_state.exists() and _read_json(legacy_state).get("request_hash") in legacy_hashes)
                or (legacy_response.exists() and "capital_source" in _read_json(legacy_response).get("request", {}))):
            # Never turn an old unnamespaced send into a fresh delivery.
            return {"event_id": event_id, "state": "RECONCILIATION_REQUIRED",
                    "reason": "LEGACY_CAPITAL_STATE_REQUIRES_RECONCILIATION",
                    "transport_performed": False, "notification_eligible": False}
        state_dir = state_dir / FULL_REQUEST_VERSION
    else:
        envelope = build_request_envelope(payload, model=SMOKE_MODEL, judgment_context=context)

    def validated_receipt(response):
        if capital_source is not None:
            from .capital_decision_closure import validated_receipt as capital_receipt, assert_current
            destination = state_dir / "recommendations" / f"{event_id}.json"
            current_time = int(time.time() * 1000) if now_ms is None else now_ms
            stored = _read_json(destination) if destination.exists() else None
            evaluated = stored["capital_validation"]["evaluated_at_ms"] if stored else current_time
            receipt = capital_receipt(response, envelope, at_ms=evaluated)
            assert_current(receipt["capital_validation"], capital_source, at_ms=current_time)
            if stored is not None:
                if stored != receipt:
                    raise ValueError("Persisted capital recommendation mismatch")
            else:
                _write_no_clobber(destination, receipt)
            return receipt
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
        if capital_source is None and evidence_path.exists():
            # A capacity/codec revision must not rewrite or resend a completed
            # event under today's request version. Validate its original first.
            saved_request=_read_json(evidence_path)["request"]
            validate_request_envelope(saved_request)
            saved_input=json.loads(saved_request["request_body"]["input"])
            saved_payload=(saved_input["bridge_payload"] if "text" in saved_request["request_body"] else saved_input)
            expected_input=json.loads(envelope["request_body"]["input"])
            if (saved_payload!=payload or saved_request["event_id"]!=event_id
                    or saved_request["bridge_payload_hash"]!=payload_hash
                    or (context is not None and saved_input.get("commander_judgment_request")!=expected_input.get("commander_judgment_request"))):
                raise ValueError("Persisted original request lineage mismatch")
            envelope=saved_request
        if capital_source is not None and evidence_path.exists():
            # A schema refinement must not rewrite or resend a prior event.
            # Validate the immutable original request before replaying its receipt.
            saved_request = _read_json(evidence_path)["request"]
            validate_request_envelope(saved_request)
            if (saved_request.get("contract_version") != FULL_REQUEST_VERSION
                    or saved_request.get("capital_source") != envelope["capital_source"]
                    or saved_request.get("capital_bridge_payload") != payload
                    or saved_request.get("request_at_ms") != capital_source["task"]["as_of_ms"]):
                raise ValueError("Persisted capital request lineage mismatch")
            envelope = saved_request

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
            except Exception as exc:
                review = ({"capital_blocked_review": _capital_blocked_review(
                    evidence["response"], envelope,
                    at_ms=int(time.time() * 1000) if now_ms is None else now_ms, failure=exc)}
                    if capital_source is not None else {})
                return {**result, "state": "RECONCILIATION_REQUIRED", **review}
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
            # Input upload is resumable and does not invoke inference. The
            # durable inference marker is set immediately before that POST.
            def before_inference():
                nonlocal state
                state = _seal_state({**state, "request_hash": envelope["request_hash"],
                                     "reason": "PROVIDER_SEND_STARTED"})
                persist_boundary_state(state_dir, state)
            response = None
            try:
                if transport is send_response:
                    response = transport(envelope,transfer_root=state_dir/"input_transfers",
                                         before_inference=before_inference)
                else:
                    before_inference()
                    response = transport(envelope)
                result["transport_performed"] = True
                # Preserve the complete provider object before semantic validation,
                # including refusals, malformed judgment text and incomplete output.
                _write_no_clobber(evidence_path, {"request": envelope, "response": response})
                receipt = validated_receipt(response)
            except InputTransferPending:
                # This exception is reserved for pre-inference transfer failure
                # or an explicit 413 rejection, never an ambiguous model POST.
                if transport is not send_response:
                    state=mark_retryable(state,claim_token=token,reason="PROVIDER_RESULT_REQUIRES_RECONCILIATION")
                    persist_boundary_state(state_dir,state)
                    return {**result,"state":"RECONCILIATION_REQUIRED"}
                state = mark_retryable(state,claim_token=token,reason="INPUT_TRANSFER_PENDING")
                state.pop("request_hash",None)
                persist_boundary_state(state_dir,_seal_state(state))
                return {**result,"state":"INPUT_TRANSFER_PENDING","input_transfer_state":"PENDING",
                        "input_transfer_activity":"PARTS_MAY_HAVE_BEEN_SENT",
                        "inference_state":"NOT_STARTED_OR_EXPLICITLY_REJECTED"}
            except Exception as exc:
                # Never persist exception text, headers, URLs, or credentials.
                state = mark_retryable(state, claim_token=token,
                                       reason="PROVIDER_RESULT_REQUIRES_RECONCILIATION")
                persist_boundary_state(state_dir, state)
                review = ({"capital_blocked_review": _capital_blocked_review(
                    response, envelope,
                    at_ms=int(time.time() * 1000) if now_ms is None else now_ms, failure=exc)}
                    if capital_source is not None and isinstance(response, dict) else {})
                return {**result, "state": "RECONCILIATION_REQUIRED", **review}
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
    parser.add_argument("--capital-source", type=Path, help="Current local capital recommendation source; independent of Commander")
    args = parser.parse_args(argv)
    structured = args.capital_source is None and any((args.source_bundle, args.current_main_sha, args.asset))
    if structured and not all((args.source_bundle, args.current_main_sha, args.asset, args.event_id)):
        parser.error("Structured delivery requires source-bundle, current-main-sha, asset and event-id")
    if args.capital_source and (not args.current_main_sha or not args.event_id or args.source_bundle or args.asset):
        parser.error("Capital delivery requires current-main-sha and event-id, without Commander inputs")
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
                capital_source=_read_json(args.capital_source) if args.capital_source else None,
            )
        except Exception:
            result = {"state": "VALIDATION_OR_PERSISTENCE_BLOCKED"}
        print(json.dumps(result, sort_keys=True))
        failed |= result["state"] in {"VALIDATION_OR_PERSISTENCE_BLOCKED",
                                     "CREDENTIAL_UNAVAILABLE", "RECONCILIATION_REQUIRED"}
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
