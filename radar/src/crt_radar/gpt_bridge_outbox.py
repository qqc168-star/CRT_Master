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

EVIDENCE_ENCODING = "CRT_EXACT_EVIDENCE_REFS_V1"
_REF = "$crt_evidence_ref"
_IDENTITY_KEYS = {
    "asset_id", "issuer_id", "security_id", "symbol", "pair", "metric", "source_id", "source",
    "metric_id", "observation_id", "event_id", "data_hash", "semantic_ref", "semantic_version", "currency",
    "source_ref", "source_url", "source_hash", "raw_sha256", "evidence_hash", "accession",
    "as_of_ms", "as_of", "effective_time", "effective_at_ms", "disclosure_time", "first_seen_time", "retrieval_time",
    "first_seen_at_ms", "retrieval_time_ms", "source_name",
    "observed_at_ms", "available_at_ms", "retrieved_at_ms", "validated_at_ms",
    "quality_state", "verification_state", "schema_version", "version", "basis_ref", "unit",
    "generated_at_ms", "cutoff_ms", "effective_date", "session_date", "date", "observation_time",
    "period_start_date", "period_end_date", "comparison_basis", "scope", "layer",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def encode_evidence_references(value: dict) -> dict:
    """Share exact content AND inherited evidence identity; never numeric proximity."""
    from copy import deepcopy
    groups = {}

    def identity(node, inherited):
        result = dict(inherited)
        if isinstance(node, dict):
            result.update({k: node[k] for k in _IDENTITY_KEYS if k in node})
        return result

    def key_for(node, context):
        return _canonical_hash([context, node])

    def child_context(context, container, key):
        result=dict(context)
        if container=="metrics":result["metric"]=key
        if key in {"MSTR","ASST","STRC","SATA","BTC"} or container in {"assets","by_asset"}:
            result["asset_id"]=key
        if key in {"L0","L1","L2","L3","L4","L5","L6"}:result["layer"]=key
        return result

    def count(node, inherited, container=None):
        context = identity(node, inherited)
        if isinstance(node, (dict, list)):
            if isinstance(node, dict) and (_REF in node or "evidence_reference_encoding" in node):
                raise ValueError("Reserved evidence reference field")
            raw = canonical_bytes(node)
            evidence_record=isinstance(node,dict) and bool(set(node)&{
                "source_id","source_ref","source_url","raw_sha256","evidence_hash","observation_id","metric","asset_id"})
            if len(raw) >= 256 or evidence_record:
                key = key_for(node, context)
                row = groups.setdefault(key, [0, raw, context,evidence_record])
                if row[1] != raw or row[2] != context:
                    raise ValueError("Evidence content hash collision")
                row[0] += 1
            for key,child in (node.items() if isinstance(node, dict) else enumerate(node)):
                count(child,child_context(context,container,key) if isinstance(node,dict) else context,
                      key if isinstance(node,dict) else container)

    count(value, {})
    selected = {k for k, (n, raw, context, record) in groups.items() if n > 1
                and (record or len(raw) * (n-1) > n * 92 + len(canonical_bytes(context)) + 160)}
    objects = {}

    def encode(node, inherited, *, root=False, container=None):
        context = identity(node, inherited)
        if not isinstance(node, (dict, list)):
            return deepcopy(node)
        key = key_for(node, context)
        if not root and key in selected:
            if key not in objects:
                objects[key] = {"identity": context, "content_hash": _canonical_hash(node),
                                "value": encode(node, inherited, root=True,container=container)}
            return {_REF: key}
        return ({k: encode(v,child_context(context,container,k),container=k) for k,v in sorted(node.items())} if isinstance(node,dict)
                else [encode(v, context,container=container) for v in node])

    result = encode(value, {}, root=True)
    if objects:
        result["evidence_reference_encoding"] = {"schema_version": EVIDENCE_ENCODING,
            "content_hash": _canonical_hash(value), "objects": objects}
        if (not any(groups[k][3] for k in objects)
                and len(canonical_bytes(result)) >= len(canonical_bytes(value))):
            return deepcopy(value)
    return result


def expand_evidence_references(value: dict) -> dict:
    from copy import deepcopy
    result = deepcopy(value)
    codec = result.pop("evidence_reference_encoding", None)
    if codec is None:
        return result
    if (not isinstance(codec,dict) or set(codec)!={"schema_version","content_hash","objects"}
            or codec["schema_version"] != EVIDENCE_ENCODING or not isinstance(codec["objects"],dict)):
        raise ValueError("Evidence reference encoding invalid")
    objects, seen, active, cache = codec["objects"], set(), set(), {}

    def expand(node):
        if isinstance(node,dict):
            if _REF in node:
                if set(node)!={_REF} or node[_REF] not in objects:
                    raise ValueError("Evidence reference missing")
                key=node[_REF]; seen.add(key)
                if key in active:
                    raise ValueError("Evidence reference cycle")
                if key not in cache:
                    active.add(key); row=objects[key]
                    if not isinstance(row,dict) or set(row)!={"identity","content_hash","value"}:
                        raise ValueError("Evidence object invalid")
                    restored=expand(row["value"])
                    if _canonical_hash(restored)!=row["content_hash"] or _canonical_hash([row["identity"],restored])!=key:
                        raise ValueError("Evidence object hash mismatch")
                    cache[key]=restored; active.remove(key)
                return deepcopy(cache[key])
            return {k:expand(v) for k,v in node.items()}
        return [expand(v) for v in node] if isinstance(node,list) else node

    result=expand(result)
    if seen!=set(objects) or _canonical_hash(result)!=codec["content_hash"]:
        raise ValueError("Evidence reference completeness mismatch")
    return result


def build_transfer_manifest(raw: bytes, *, part_bytes: int) -> tuple[dict, dict[str,bytes]]:
    """No total-size cap. Parts are content addressed and ordered separately."""
    if type(part_bytes) is not int or part_bytes<=0 or not isinstance(raw,bytes):
        raise ValueError("Transfer part configuration invalid")
    parts, unique = [], {}
    for start in range(0,len(raw),part_bytes):
        data=raw[start:start+part_bytes]; digest=hashlib.sha256(data).hexdigest()
        if digest in unique and unique[digest]!=data:
            raise ValueError("Transfer hash collision")
        unique[digest]=data
        parts.append({"index":len(parts),"sha256":digest,"bytes":len(data)})
    manifest={"schema_version":"CRT_BRIDGE_PARTS_V1","sha256":hashlib.sha256(raw).hexdigest(),
              "bytes":len(raw),"part_bytes":part_bytes,"parts":parts}
    manifest["manifest_hash"]=_canonical_hash(manifest)
    return manifest,unique


def validate_transfer_manifest(manifest: dict) -> None:
    body=dict(manifest); digest=body.pop("manifest_hash",None)
    if digest!=_canonical_hash(body) or body.get("schema_version")!="CRT_BRIDGE_PARTS_V1":
        raise ValueError("Transfer manifest hash invalid")
    parts=body.get("parts")
    if (not isinstance(parts,list) or type(body.get("part_bytes")) is not int or body["part_bytes"]<=0
            or type(body.get("bytes")) is not int or body["bytes"]<0
            or sum(p.get("bytes",-1) for p in parts)!=body["bytes"]
            or any(p.get("index")!=i or type(p.get("bytes")) is not int or not 0<p["bytes"]<=body["part_bytes"]
                   or _HEX64.fullmatch(str(p.get("sha256"))) is None for i,p in enumerate(parts))):
        raise ValueError("Transfer manifest ordering/length invalid")


def receive_transfer_part(root: str | Path, manifest: dict, digest: str, raw: bytes) -> None:
    validate_transfer_manifest(manifest)
    row=next((p for p in manifest["parts"] if p["sha256"]==digest),None)
    if row is None or len(raw)!=row["bytes"] or hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError("Transfer part hash/length invalid")
    objects=Path(root)/"parts"; objects.mkdir(parents=True,exist_ok=True)
    target=objects/(digest+".bin")
    if target.exists():
        if target.read_bytes()!=raw: raise ValueError("Stored transfer part corrupt")
        return
    fd,name=tempfile.mkstemp(dir=objects,prefix=".part-")
    try:
        with os.fdopen(fd,"wb") as handle:
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
        try: os.link(name,target)
        except FileExistsError:
            if target.read_bytes()!=raw: raise ValueError("Stored transfer part conflict")
    finally:
        Path(name).unlink(missing_ok=True)


def reassemble_transfer(root: str | Path, manifest: dict) -> bytes:
    validate_transfer_manifest(manifest)
    assembled=[]
    for row in manifest["parts"]:
        raw=(Path(root)/"parts"/(row["sha256"]+".bin")).read_bytes()
        if len(raw)!=row["bytes"] or hashlib.sha256(raw).hexdigest()!=row["sha256"]:
            raise ValueError("Stored transfer part corrupt")
        assembled.append(raw)
    raw=b"".join(assembled)
    if len(raw)!=manifest["bytes"] or hashlib.sha256(raw).hexdigest()!=manifest["sha256"]:
        raise ValueError("Transfer reassembly hash invalid")
    return raw


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
