#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


MANIFEST_SCHEMA_VERSION = "CRT_CANDIDATE_POINT_IN_TIME_DATASET_MANIFEST_V0.3"
ARTIFACT_FIELDS = {
    "source_contract_id",
    "request_identity",
    "retrieved_at_ms",
    "first_seen_at_ms",
    "available_at_coverage_start_ms",
    "available_at_coverage_end_ms",
    "sha256",
    "size_bytes",
    "archive_relpath",
    "content_type",
    "integrity_proof_type",
    "provider_checksum",
    "license_classification",
    "source_authority_hash",
    "evidence_class",
    "availability_proof_type",
    "replay_eligible",
    "revision_of_sha256",
}
ROOT_FIELDS = {
    "schema_version",
    "candidate_registry_hash",
    "public_source_authority_hash",
    "acquisition_contract_hash",
    "source_contract_hash",
    "created_at_ms",
    "artifacts",
    "manifest_sha256",
}
ALLOWED_EVIDENCE_CLASSES = {
    "CURRENT_FIRST_SEEN_CAPTURE",
    "IMMUTABLE_PROVIDER_ARCHIVE",
    "OFFICIAL_FILING",
    "SYNTHETIC_FIXTURE",
}


class AcquisitionError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcquisitionError(code)
    return value


def _timestamp_ms(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AcquisitionError(code)
    return value


def _archive_relpath(digest: str) -> str:
    return f"artifacts/sha256/{digest[:2]}/{digest}"


def _identity_relpath(artifact: dict[str, Any]) -> str:
    identity_hash = canonical_hash(
        {
            "source_contract_id": artifact["source_contract_id"],
            "request_identity": artifact["request_identity"],
            "sha256": artifact["sha256"],
        }
    )
    return f"metadata/identities/{identity_hash[:2]}/{identity_hash}.json"


def _write_content_addressed(path: Path, raw_bytes: bytes, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or sha256_bytes(path.read_bytes()) != digest:
            raise AcquisitionError("ARCHIVE_EXISTING_BYTES_HASH_MISMATCH")
        return

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".candidate-artifact-",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(raw_bytes)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if not path.is_file() or sha256_bytes(path.read_bytes()) != digest:
                raise AcquisitionError("ARCHIVE_EXISTING_BYTES_HASH_MISMATCH")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _identity_record(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "CRT_CANDIDATE_ARTIFACT_IDENTITY_V0.1",
        "artifact": artifact,
    }
    payload["record_sha256"] = canonical_hash(payload)
    return payload


def _record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_sha256", None)
    return canonical_hash(payload)


def _bind_first_seen_metadata(
    archive_root: Path,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    path = archive_root / _identity_relpath(artifact)
    if path.exists():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AcquisitionError("IDENTITY_METADATA_UNREADABLE") from exc
        if not isinstance(record, dict) or record.get("record_sha256") != _record_hash(record):
            raise AcquisitionError("IDENTITY_METADATA_HASH_MISMATCH")
        stored = record.get("artifact")
        if not isinstance(stored, dict):
            raise AcquisitionError("IDENTITY_METADATA_ARTIFACT_INVALID")
        if stored.get("first_seen_at_ms") != artifact.get("first_seen_at_ms"):
            raise AcquisitionError("FIRST_SEEN_METADATA_CONFLICT")
        immutable_fields = set(ARTIFACT_FIELDS) - {"retrieved_at_ms"}
        if any(stored.get(field) != artifact.get(field) for field in immutable_fields):
            raise AcquisitionError("ARTIFACT_IDENTITY_METADATA_CONFLICT")
        if artifact["retrieved_at_ms"] < stored.get("retrieved_at_ms", 0):
            raise AcquisitionError("RETRIEVAL_PRECEDES_FIRST_CAPTURE")
        return dict(stored)

    record = _identity_record(artifact)
    raw = canonical_bytes(record) + b"\n"
    try:
        _write_content_addressed(path, raw, sha256_bytes(raw))
    except AcquisitionError as exc:
        raise AcquisitionError("IDENTITY_METADATA_CREATE_CONFLICT") from exc
    return artifact


def archive_artifact(
    archive_root: str | Path,
    raw_bytes: bytes,
    *,
    source_contract_id: str,
    request_identity: str,
    retrieved_at_ms: int,
    first_seen_at_ms: int,
    available_at_coverage_start_ms: int,
    available_at_coverage_end_ms: int,
    integrity_proof_type: str,
    provider_checksum: str | None,
    license_classification: str,
    source_authority_hash: str,
    evidence_class: str,
    replay_eligible: bool,
    content_type: str,
    availability_proof_type: str,
    revision_of_sha256: str | None,
) -> dict[str, Any]:
    """Archive caller-supplied bytes without implementing any network fetch."""
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise AcquisitionError("RAW_BYTES_REQUIRED")
    source_contract_id = _required_text(source_contract_id, "SOURCE_CONTRACT_ID_REQUIRED")
    request_identity = _required_text(request_identity, "REQUEST_IDENTITY_REQUIRED")
    integrity_proof_type = _required_text(
        integrity_proof_type,
        "INTEGRITY_PROOF_TYPE_REQUIRED",
    )
    license_classification = _required_text(
        license_classification,
        "LICENSE_CLASSIFICATION_REQUIRED",
    )
    content_type = _required_text(content_type, "CONTENT_TYPE_REQUIRED")
    availability_proof_type = _required_text(
        availability_proof_type,
        "AVAILABILITY_PROOF_TYPE_REQUIRED",
    )
    if not _is_sha256(source_authority_hash):
        raise AcquisitionError("SOURCE_AUTHORITY_HASH_INVALID")
    if provider_checksum is not None and not isinstance(provider_checksum, str):
        raise AcquisitionError("PROVIDER_CHECKSUM_INVALID")
    if revision_of_sha256 is not None and not _is_sha256(revision_of_sha256):
        raise AcquisitionError("REVISION_HASH_INVALID")
    if evidence_class not in ALLOWED_EVIDENCE_CLASSES:
        raise AcquisitionError("EVIDENCE_CLASS_INVALID")
    if not isinstance(replay_eligible, bool):
        raise AcquisitionError("REPLAY_ELIGIBLE_INVALID")
    if evidence_class == "SYNTHETIC_FIXTURE" and replay_eligible:
        raise AcquisitionError("SYNTHETIC_FIXTURE_CANNOT_BE_REPLAY_ELIGIBLE")

    retrieved = _timestamp_ms(retrieved_at_ms, "RETRIEVED_AT_INVALID")
    first_seen = _timestamp_ms(first_seen_at_ms, "FIRST_SEEN_AT_INVALID")
    coverage_start = _timestamp_ms(
        available_at_coverage_start_ms,
        "AVAILABLE_AT_COVERAGE_START_INVALID",
    )
    coverage_end = _timestamp_ms(
        available_at_coverage_end_ms,
        "AVAILABLE_AT_COVERAGE_END_INVALID",
    )
    if first_seen > retrieved:
        raise AcquisitionError("FIRST_SEEN_AFTER_RETRIEVAL")
    if coverage_start > coverage_end:
        raise AcquisitionError("AVAILABLE_AT_COVERAGE_REVERSED")
    if coverage_end > retrieved:
        raise AcquisitionError("AVAILABLE_AT_COVERAGE_AFTER_RETRIEVAL")
    if evidence_class == "CURRENT_FIRST_SEEN_CAPTURE" and (
        coverage_start != first_seen or coverage_end != first_seen
    ):
        raise AcquisitionError("CURRENT_CAPTURE_CANNOT_PROVE_EARLIER_AVAILABILITY")
    if evidence_class == "IMMUTABLE_PROVIDER_ARCHIVE" and not provider_checksum:
        raise AcquisitionError("PROVIDER_ARCHIVE_CHECKSUM_REQUIRED")

    digest = sha256_bytes(raw_bytes)
    relpath = _archive_relpath(digest)
    path = Path(archive_root) / relpath
    _write_content_addressed(path, raw_bytes, digest)
    artifact = {
        "source_contract_id": source_contract_id,
        "request_identity": request_identity,
        "retrieved_at_ms": retrieved,
        "first_seen_at_ms": first_seen,
        "available_at_coverage_start_ms": coverage_start,
        "available_at_coverage_end_ms": coverage_end,
        "sha256": digest,
        "size_bytes": len(raw_bytes),
        "archive_relpath": relpath,
        "content_type": content_type,
        "integrity_proof_type": integrity_proof_type,
        "provider_checksum": provider_checksum,
        "license_classification": license_classification,
        "source_authority_hash": source_authority_hash,
        "evidence_class": evidence_class,
        "availability_proof_type": availability_proof_type,
        "replay_eligible": replay_eligible,
        "revision_of_sha256": revision_of_sha256,
    }
    return _bind_first_seen_metadata(Path(archive_root), artifact)


def manifest_hash(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    return canonical_hash(payload)


def build_dataset_manifest(
    artifacts: Iterable[dict[str, Any]],
    *,
    candidate_registry_hash: str,
    public_source_authority_hash: str,
    acquisition_contract_hash: str,
    source_contract_hash: str,
    created_at_ms: int,
) -> dict[str, Any]:
    hashes = {
        "candidate_registry_hash": candidate_registry_hash,
        "public_source_authority_hash": public_source_authority_hash,
        "acquisition_contract_hash": acquisition_contract_hash,
        "source_contract_hash": source_contract_hash,
    }
    for field, value in hashes.items():
        if not _is_sha256(value):
            raise AcquisitionError(f"{field.upper()}_INVALID")
    created = _timestamp_ms(created_at_ms, "CREATED_AT_INVALID")
    normalized = [dict(item) for item in artifacts]
    for index, item in enumerate(normalized):
        if not ARTIFACT_FIELDS.issubset(item):
            raise AcquisitionError(f"ARTIFACT_{index}_FIELDS_INVALID")
    normalized.sort(
        key=lambda item: (
            str(item.get("source_contract_id")),
            int(item.get("available_at_coverage_start_ms", -1)),
            str(item.get("sha256")),
        )
    )
    identities = [
        (
            item.get("source_contract_id"),
            item.get("request_identity"),
            item.get("sha256"),
        )
        for item in normalized
    ]
    if len(identities) != len(set(identities)):
        raise AcquisitionError("DUPLICATE_ARTIFACT_IDENTITY")

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        **hashes,
        "created_at_ms": created,
        "artifacts": normalized,
    }
    manifest["manifest_sha256"] = manifest_hash(manifest)
    return manifest


def _safe_archive_path(archive_root: Path, relpath: Any) -> Path | None:
    if not isinstance(relpath, str) or not relpath:
        return None
    root = archive_root.resolve()
    candidate = (root / relpath).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def validate_dataset_manifest(
    manifest: dict[str, Any],
    *,
    archive_root: str | Path,
    required_source_contract_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    if not ROOT_FIELDS.issubset(manifest):
        errors.append("manifest root fields invalid")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("manifest schema mismatch")
    if manifest.get("manifest_sha256") != manifest_hash(manifest):
        errors.append("manifest sha256 mismatch")
    for field in (
        "candidate_registry_hash",
        "public_source_authority_hash",
        "acquisition_contract_hash",
        "source_contract_hash",
    ):
        if not _is_sha256(manifest.get(field)):
            errors.append(f"manifest {field} invalid")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("manifest artifacts invalid")
        return errors

    root = Path(archive_root)
    present: set[str] = set()
    for index, artifact in enumerate(artifacts):
        prefix = f"artifact {index}"
        artifact_valid = True
        if not isinstance(artifact, dict) or not ARTIFACT_FIELDS.issubset(artifact):
            errors.append(f"{prefix} fields invalid")
            continue
        digest = artifact.get("sha256")
        if not _is_sha256(digest):
            errors.append(f"{prefix} sha256 invalid")
            continue
        if artifact.get("archive_relpath") != _archive_relpath(digest):
            errors.append(f"{prefix} archive path invalid")
            continue
        path = _safe_archive_path(root, artifact.get("archive_relpath"))
        if path is None:
            errors.append(f"{prefix} archive path escapes root")
            continue
        if not path.is_file():
            errors.append(f"{prefix} archive missing")
            continue
        raw = path.read_bytes()
        if sha256_bytes(raw) != digest:
            errors.append(f"{prefix} archive sha256 mismatch")
            artifact_valid = False
        if artifact.get("size_bytes") != len(raw):
            errors.append(f"{prefix} archive size mismatch")
            artifact_valid = False
        evidence_class = artifact.get("evidence_class")
        replay_eligible = artifact.get("replay_eligible")
        if evidence_class not in ALLOWED_EVIDENCE_CLASSES:
            errors.append(f"{prefix} evidence class invalid")
            artifact_valid = False
        if not isinstance(replay_eligible, bool):
            errors.append(f"{prefix} replay eligibility invalid")
            artifact_valid = False
        if evidence_class == "SYNTHETIC_FIXTURE" and replay_eligible:
            errors.append(f"{prefix} synthetic fixture marked eligible")
            artifact_valid = False
        timestamp_fields = (
            "retrieved_at_ms",
            "first_seen_at_ms",
            "available_at_coverage_start_ms",
            "available_at_coverage_end_ms",
        )
        timestamps = [artifact.get(field) for field in timestamp_fields]
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in timestamps
        ):
            errors.append(f"{prefix} timestamp invalid")
            artifact_valid = False
        else:
            retrieved, first_seen, coverage_start, coverage_end = timestamps
            if first_seen > retrieved:
                errors.append(f"{prefix} first seen after retrieval")
                artifact_valid = False
            if coverage_start > coverage_end or coverage_end > retrieved:
                errors.append(f"{prefix} availability coverage invalid")
                artifact_valid = False
        if evidence_class == "CURRENT_FIRST_SEEN_CAPTURE" and (
            artifact.get("available_at_coverage_start_ms") != artifact.get("first_seen_at_ms")
            or artifact.get("available_at_coverage_end_ms") != artifact.get("first_seen_at_ms")
        ):
            errors.append(f"{prefix} current capture backdated")
            artifact_valid = False
        if evidence_class == "IMMUTABLE_PROVIDER_ARCHIVE" and not artifact.get(
            "provider_checksum"
        ):
            errors.append(f"{prefix} provider archive checksum missing")
            artifact_valid = False
        if not _is_sha256(artifact.get("source_authority_hash")):
            errors.append(f"{prefix} source authority hash invalid")
            artifact_valid = False
        if artifact_valid and replay_eligible is True and evidence_class != "SYNTHETIC_FIXTURE":
            source_id = artifact.get("source_contract_id")
            if isinstance(source_id, str) and source_id:
                present.add(source_id)

    for source_id in sorted((required_source_contract_ids or set()) - present):
        errors.append(f"source contract {source_id} missing replay-eligible artifact")
    return errors


def write_manifest_immutable(
    archive_root: str | Path,
    manifest: dict[str, Any],
) -> Path:
    if manifest.get("manifest_sha256") != manifest_hash(manifest):
        raise AcquisitionError("MANIFEST_HASH_INVALID")
    raw = canonical_bytes(manifest) + b"\n"
    digest = manifest["manifest_sha256"]
    path = Path(archive_root) / "manifests" / f"{digest}.json"
    _write_content_addressed(path, raw, sha256_bytes(raw))
    return path
