#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import candidate_acquisition
import prospective_capture


AUDIT_SCHEMA_VERSION = "CRT_ETP_PROSPECTIVE_CAPTURE_AUDIT_V0.1"
SOURCE_CONTRACT_ID = "US_SPOT_BTC_ETP_POINT_IN_TIME"


def _error(errors: list[str], code: str, relpath: str | None = None) -> None:
    errors.append(code if relpath is None else f"{code}:{relpath}")


def _safe_file(
    root: Path,
    relpath: str,
    *,
    code: str,
    errors: list[str],
) -> Path | None:
    current = root
    for part in Path(relpath).parts:
        current = current / part
        if current.is_symlink():
            _error(errors, f"{code}_SYMLINK_FORBIDDEN", relpath)
            return None
    try:
        path = prospective_capture._safe_path(root, relpath, code)
    except prospective_capture.ProspectiveCaptureError:
        _error(errors, code, relpath)
        return None
    if not path.is_file():
        _error(errors, f"{code}_MISSING", relpath)
        return None
    return path


def _read_json_bytes(
    path: Path,
    *,
    code: str,
    relpath: str,
    errors: list[str],
) -> tuple[bytes, dict[str, Any]] | None:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _error(errors, f"{code}_UNREADABLE", relpath)
        return None
    if not isinstance(value, dict):
        _error(errors, f"{code}_NOT_OBJECT", relpath)
        return None
    return raw, value


def _read_cas_json(
    root: Path,
    relpath: str,
    *,
    prefix: str,
    code: str,
    errors: list[str],
) -> dict[str, Any] | None:
    path = _safe_file(root, relpath, code=code, errors=errors)
    if path is None:
        return None
    loaded = _read_json_bytes(path, code=code, relpath=relpath, errors=errors)
    if loaded is None:
        return None
    raw, value = loaded
    digest = prospective_capture.sha256_bytes(raw)
    expected = f"{prefix}/sha256/{digest[:2]}/{digest}.json"
    if relpath != expected:
        _error(errors, f"{code}_CONTENT_ADDRESS_MISMATCH", relpath)
    if raw != prospective_capture.canonical_bytes(value) + b"\n":
        _error(errors, f"{code}_NONCANONICAL_JSON", relpath)
    return value


def _discover(root: Path, pattern: str) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.glob(pattern)
        if path.is_file() or path.is_symlink()
    )


def _scan_managed_paths(
    root: Path,
    *,
    known_files: set[str],
    errors: list[str],
) -> None:
    for dirname in ("capture_runs", "capture_receipts", "manifests", "artifacts", "metadata"):
        managed = root / dirname
        if not managed.exists() and not managed.is_symlink():
            continue
        if managed.is_symlink():
            _error(errors, "MANAGED_PATH_SYMLINK_FORBIDDEN", dirname)
            continue
        if not managed.is_dir():
            _error(errors, "MANAGED_PATH_NOT_DIRECTORY", dirname)
            continue
        for path in managed.rglob("*"):
            relpath = path.relative_to(root).as_posix()
            if path.is_symlink():
                _error(errors, "MANAGED_PATH_SYMLINK_FORBIDDEN", relpath)
            elif path.is_file() and relpath not in known_files:
                _error(errors, "UNEXPECTED_MANAGED_FILE", relpath)


def _validate_raw_reference(
    root: Path,
    reference: Any,
    *,
    errors: list[str],
) -> str | None:
    if not isinstance(reference, dict):
        _error(errors, "RAW_REFERENCE_INVALID")
        return None
    digest = reference.get("sha256")
    size = reference.get("size_bytes")
    relpath = reference.get("relpath", reference.get("archive_relpath"))
    if not prospective_capture._is_sha256(digest):
        _error(errors, "RAW_REFERENCE_SHA256_INVALID")
        return None
    expected = f"artifacts/sha256/{digest[:2]}/{digest}"
    if relpath != expected:
        _error(errors, "RAW_REFERENCE_PATH_INVALID", str(relpath))
        return None
    path = _safe_file(root, relpath, code="RAW_ARTIFACT", errors=errors)
    if path is None:
        return relpath
    try:
        raw = path.read_bytes()
    except OSError:
        _error(errors, "RAW_ARTIFACT_UNREADABLE", relpath)
        return relpath
    if prospective_capture.sha256_bytes(raw) != digest:
        _error(errors, "RAW_ARTIFACT_SHA256_MISMATCH", relpath)
    if isinstance(size, bool) or not isinstance(size, int) or size != len(raw):
        _error(errors, "RAW_ARTIFACT_SIZE_MISMATCH", relpath)
    return relpath


def _validate_cas_reference(
    reference: Any,
    *,
    prefix: str,
    code: str,
    errors: list[str],
) -> str | None:
    if not isinstance(reference, dict):
        _error(errors, f"{code}_REFERENCE_INVALID")
        return None
    digest = reference.get("sha256")
    relpath = reference.get("relpath")
    if not prospective_capture._is_sha256(digest):
        _error(errors, f"{code}_REFERENCE_SHA256_INVALID")
        return None
    expected = f"{prefix}/sha256/{digest[:2]}/{digest}.json"
    if relpath != expected:
        _error(errors, f"{code}_REFERENCE_PATH_INVALID", str(relpath))
        return None
    return relpath


def _validate_manifest_reference(
    reference: Any,
    *,
    errors: list[str],
) -> str | None:
    if not isinstance(reference, dict):
        _error(errors, "MANIFEST_REFERENCE_INVALID")
        return None
    digest = reference.get("sha256")
    relpath = reference.get("relpath")
    if not prospective_capture._is_sha256(digest):
        _error(errors, "MANIFEST_REFERENCE_SHA256_INVALID")
        return None
    expected = f"manifests/{digest}.json"
    if relpath != expected:
        _error(errors, "MANIFEST_REFERENCE_PATH_INVALID", str(relpath))
        return None
    return relpath


def _base_report() -> dict[str, Any]:
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "state": "BLOCKED",
        "run_report_count": 0,
        "receipt_count": 0,
        "manifest_count": 0,
        "raw_artifact_count": 0,
        "identity_metadata_count": 0,
        "replayed_snapshot_count": 0,
        "captured_observation_count": 0,
        "complete_capture_run_count": 0,
        "mode": "SHADOW_ONLY",
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "historical_dataset_ready": False,
        "historical_backfill_authority": "NONE",
        "errors": [],
    }


def audit_capture_archive(archive_root: str | Path) -> dict[str, Any]:
    report = _base_report()
    errors: list[str] = report["errors"]
    root = Path(archive_root)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        _error(errors, "ARCHIVE_ROOT_INVALID")
        return report

    try:
        capture, adapters, acquisition, authority, sources, protocol = (
            prospective_capture._resolved_contracts(None, None, None, None, None, None)
        )
    except prospective_capture.ProspectiveCaptureError as exc:
        _error(errors, f"CAPTURE_CONTRACT_INVALID_{str(exc)}")
        return report

    expected_hashes = {
        "capture_contract_hash": prospective_capture.canonical_hash(capture),
        "adapter_contract_hash": prospective_capture.canonical_hash(adapters),
        "acquisition_contract_hash": prospective_capture.canonical_hash(acquisition),
        "source_contract_hash": prospective_capture.canonical_hash(sources),
        "walk_forward_protocol_hash": prospective_capture.canonical_hash(protocol),
    }
    manifest_hashes = {
        "candidate_registry_hash": capture["candidate_registry_hash"],
        "public_source_authority_hash": prospective_capture.canonical_hash(authority),
        "acquisition_contract_hash": expected_hashes["acquisition_contract_hash"],
        "source_contract_hash": expected_hashes["source_contract_hash"],
    }

    run_relpaths = _discover(root, "capture_runs/sha256/*/*.json") if root.exists() else []
    receipt_relpaths = (
        _discover(root, "capture_receipts/sha256/*/*.json") if root.exists() else []
    )
    manifest_relpaths = _discover(root, "manifests/*.json") if root.exists() else []
    raw_relpaths = _discover(root, "artifacts/sha256/*/*") if root.exists() else []
    identity_relpaths = (
        _discover(root, "metadata/identities/*/*.json") if root.exists() else []
    )
    report.update(
        {
            "run_report_count": len(run_relpaths),
            "receipt_count": len(receipt_relpaths),
            "manifest_count": len(manifest_relpaths),
            "raw_artifact_count": len(raw_relpaths),
            "identity_metadata_count": len(identity_relpaths),
        }
    )
    _scan_managed_paths(
        root,
        known_files=set(
            run_relpaths
            + receipt_relpaths
            + manifest_relpaths
            + raw_relpaths
            + identity_relpaths
        ),
        errors=errors,
    )

    referenced_receipts: dict[str, dict[str, Any]] = {}
    referenced_manifests: dict[str, str] = {}
    referenced_raw: set[str] = set()
    referenced_identities: set[str] = set()
    receipt_artifacts: dict[tuple[str, str, str], dict[str, Any]] = {}

    retry_states = {
        "FETCH_FAILED_RETRY_REQUIRED",
        "PARSE_FAILED_RETRY_REQUIRED",
        "STALE_SOURCE_RETRY_REQUIRED",
    }
    blocked_states = {"FUTURE_SOURCE_DATE_BLOCKED", "ARCHIVE_VALIDATION_BLOCKED"}

    for relpath in run_relpaths:
        run = _read_cas_json(
            root,
            relpath,
            prefix="capture_runs",
            code="RUN_REPORT",
            errors=errors,
        )
        if run is None:
            continue
        if run.get("schema_version") != prospective_capture.RUN_REPORT_SCHEMA_VERSION:
            _error(errors, "RUN_REPORT_SCHEMA_INVALID", relpath)
        for field, expected in expected_hashes.items():
            if run.get(field) != expected:
                _error(errors, f"RUN_REPORT_{field.upper()}_MISMATCH", relpath)
        expected_authority = {
            "mode": "SHADOW_ONLY",
            "formal_model": "NOT_APPROVED",
            "production": "NOT_APPROVED",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
            "historical_dataset_ready": False,
            "prior_value_carry_forward": False,
            "historical_backfill_authority": "NONE",
        }
        for field, expected in expected_authority.items():
            if run.get(field) != expected:
                _error(errors, f"RUN_REPORT_{field.upper()}_INVALID", relpath)

        ticker_results = run.get("ticker_results")
        if not isinstance(ticker_results, dict):
            _error(errors, "RUN_REPORT_TICKER_RESULTS_INVALID", relpath)
            continue
        run_at = run.get("run_at_ms")
        decision = run.get("decision")
        if isinstance(run_at, bool) or not isinstance(run_at, int) or run_at < 0:
            _error(errors, "RUN_REPORT_RUN_AT_INVALID", relpath)
            expected_decision = None
        else:
            try:
                expected_decision = prospective_capture.capture_decision(run_at, capture)
            except (OverflowError, OSError, ValueError):
                _error(errors, "RUN_REPORT_RUN_AT_OUT_OF_RANGE", relpath)
                expected_decision = None
        if decision != expected_decision:
            _error(errors, "RUN_REPORT_DECISION_MISMATCH", relpath)
        decision_state = decision.get("state") if isinstance(decision, dict) else None
        if decision_state == "CAPTURE_DUE":
            if set(ticker_results) != set(prospective_capture.READY_TICKERS):
                _error(errors, "RUN_REPORT_CAPTURE_UNIVERSE_MISMATCH", relpath)
        elif ticker_results:
            _error(errors, "RUN_REPORT_NONCAPTURE_HAS_TICKER_RESULTS", relpath)
        captured = 0
        retried = 0
        blocked = 0
        for ticker, result in ticker_results.items():
            if ticker not in prospective_capture.READY_TICKERS or not isinstance(result, dict):
                _error(errors, "RUN_REPORT_TICKER_RESULT_INVALID", relpath)
                continue
            state = result.get("state")
            if state == "CAPTURED":
                captured += 1
                report["captured_observation_count"] += 1
            elif state in retry_states:
                retried += 1
            elif state in blocked_states:
                blocked += 1
            else:
                _error(errors, "RUN_REPORT_TICKER_STATE_INVALID", relpath)

            if "staged_raw" in result:
                raw_relpath = _validate_raw_reference(
                    root,
                    result.get("staged_raw"),
                    errors=errors,
                )
                if raw_relpath is not None:
                    referenced_raw.add(raw_relpath)

            if state == "CAPTURED":
                artifact = result.get("artifact")
                snapshot = result.get("snapshot")
                receipt_reference = result.get("receipt")
                if not isinstance(artifact, dict) or not isinstance(snapshot, dict):
                    _error(errors, "RUN_REPORT_CAPTURE_CONTENT_INVALID", relpath)
                    continue
                artifact_relpath = _validate_raw_reference(root, artifact, errors=errors)
                if artifact_relpath is not None:
                    referenced_raw.add(artifact_relpath)
                receipt_relpath = _validate_cas_reference(
                    receipt_reference,
                    prefix="capture_receipts",
                    code="RECEIPT",
                    errors=errors,
                )
                if receipt_relpath is not None:
                    expected_receipt = {
                        "ticker": ticker,
                        "artifact": artifact,
                        "snapshot": snapshot,
                    }
                    previous = referenced_receipts.get(receipt_relpath)
                    if previous is not None and previous != expected_receipt:
                        _error(errors, "RECEIPT_REFERENCE_CONFLICT", receipt_relpath)
                    referenced_receipts[receipt_relpath] = expected_receipt
            elif any(field in result for field in ("artifact", "snapshot", "receipt")):
                _error(errors, "NONCAPTURE_RESULT_CONTAINS_PROMOTED_EVIDENCE", relpath)

        expected_counts = {
            "captured_count": captured,
            "retry_required_count": retried,
            "blocked_count": blocked,
        }
        for field, expected in expected_counts.items():
            if run.get(field) != expected:
                _error(errors, f"RUN_REPORT_{field.upper()}_MISMATCH", relpath)
        no_capture_states = {
            "MARKET_CLOSED": "MARKET_CLOSED_NO_CAPTURE",
            "NOT_DUE": "NOT_DUE_NO_CAPTURE",
            "CALENDAR_OUT_OF_RANGE": "BLOCKED_CALENDAR_OUT_OF_RANGE",
        }
        if decision_state in no_capture_states:
            expected_state = no_capture_states[decision_state]
        elif captured == len(prospective_capture.READY_TICKERS):
            expected_state = "COMPLETE_SHADOW_CAPTURE"
        elif blocked and captured:
            expected_state = "PARTIAL_BLOCKED"
        elif blocked:
            expected_state = "BLOCKED_NO_VALID_CAPTURE"
        elif captured:
            expected_state = "PARTIAL_RETRY_REQUIRED"
        else:
            expected_state = "RETRY_REQUIRED_NO_VALID_CAPTURE"
        if run.get("state") != expected_state:
            _error(errors, "RUN_REPORT_STATE_MISMATCH", relpath)
        elif expected_state == "COMPLETE_SHADOW_CAPTURE":
            report["complete_capture_run_count"] += 1
        manifest_reference = run.get("manifest")
        if captured:
            manifest_relpath = _validate_manifest_reference(
                manifest_reference,
                errors=errors,
            )
            if manifest_relpath is not None:
                digest = str(manifest_reference["sha256"])
                previous = referenced_manifests.get(manifest_relpath)
                if previous is not None and previous != digest:
                    _error(errors, "MANIFEST_REFERENCE_CONFLICT", manifest_relpath)
                referenced_manifests[manifest_relpath] = digest
        elif manifest_reference is not None:
            _error(errors, "RUN_REPORT_EMPTY_CAPTURE_HAS_MANIFEST", relpath)

    for relpath in receipt_relpaths:
        receipt = _read_cas_json(
            root,
            relpath,
            prefix="capture_receipts",
            code="RECEIPT",
            errors=errors,
        )
        if receipt is None:
            continue
        expected = referenced_receipts.get(relpath)
        if expected is None:
            _error(errors, "UNREFERENCED_RECEIPT", relpath)
        elif any(receipt.get(field) != value for field, value in expected.items()):
            _error(errors, "RUN_REPORT_RECEIPT_CONTENT_MISMATCH", relpath)
        try:
            prospective_capture.replay_capture_receipt(root, relpath)
        except (prospective_capture.ProspectiveCaptureError, candidate_acquisition.AcquisitionError) as exc:
            _error(errors, f"RECEIPT_REPLAY_FAILED_{str(exc)}", relpath)
            continue
        report["replayed_snapshot_count"] += 1
        artifact = receipt.get("artifact")
        snapshot = receipt.get("snapshot")
        if isinstance(artifact, dict):
            raw_relpath = _validate_raw_reference(root, artifact, errors=errors)
            if raw_relpath is not None:
                referenced_raw.add(raw_relpath)
            key = (
                str(artifact.get("source_contract_id")),
                str(artifact.get("request_identity")),
                str(artifact.get("sha256")),
            )
            receipt_artifacts[key] = artifact
            if isinstance(snapshot, dict):
                identity_relpath = prospective_capture._identity_relpath(
                    str(snapshot.get("source_url")),
                    str(artifact.get("sha256")),
                )
                referenced_identities.add(identity_relpath)

    for relpath in manifest_relpaths:
        path = _safe_file(root, relpath, code="MANIFEST", errors=errors)
        if path is None:
            continue
        loaded = _read_json_bytes(
            path,
            code="MANIFEST",
            relpath=relpath,
            errors=errors,
        )
        if loaded is None:
            continue
        raw, manifest = loaded
        digest = manifest.get("manifest_sha256")
        if not prospective_capture._is_sha256(digest) or relpath != f"manifests/{digest}.json":
            _error(errors, "MANIFEST_CONTENT_ADDRESS_MISMATCH", relpath)
        if raw != candidate_acquisition.canonical_bytes(manifest) + b"\n":
            _error(errors, "MANIFEST_NONCANONICAL_JSON", relpath)
        if referenced_manifests.get(relpath) != digest:
            _error(errors, "UNREFERENCED_MANIFEST", relpath)
        for field, expected in manifest_hashes.items():
            if manifest.get(field) != expected:
                _error(errors, f"MANIFEST_{field.upper()}_MISMATCH", relpath)
        manifest_errors = candidate_acquisition.validate_dataset_manifest(
            manifest,
            archive_root=root,
            required_source_contract_ids={SOURCE_CONTRACT_ID},
        )
        for item in manifest_errors:
            _error(errors, f"MANIFEST_VALIDATION_{item}", relpath)
        artifacts = manifest.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                raw_relpath = _validate_raw_reference(root, artifact, errors=errors)
                if raw_relpath is not None:
                    referenced_raw.add(raw_relpath)
                key = (
                    str(artifact.get("source_contract_id")),
                    str(artifact.get("request_identity")),
                    str(artifact.get("sha256")),
                )
                if receipt_artifacts.get(key) != artifact:
                    _error(errors, "MANIFEST_ARTIFACT_WITHOUT_MATCHING_RECEIPT", relpath)

    for relpath in identity_relpaths:
        path = _safe_file(root, relpath, code="IDENTITY_METADATA", errors=errors)
        if path is None:
            continue
        loaded = _read_json_bytes(
            path,
            code="IDENTITY_METADATA",
            relpath=relpath,
            errors=errors,
        )
        if loaded is None:
            continue
        raw, record = loaded
        if raw != candidate_acquisition.canonical_bytes(record) + b"\n":
            _error(errors, "IDENTITY_METADATA_NONCANONICAL_JSON", relpath)
        if record.get("record_sha256") != candidate_acquisition._record_hash(record):
            _error(errors, "IDENTITY_METADATA_RECORD_HASH_MISMATCH", relpath)
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            _error(errors, "IDENTITY_METADATA_ARTIFACT_INVALID", relpath)
            continue
        try:
            expected_relpath = candidate_acquisition._identity_relpath(artifact)
        except (KeyError, TypeError):
            _error(errors, "IDENTITY_METADATA_IDENTITY_FIELDS_INVALID", relpath)
        else:
            if relpath != expected_relpath:
                _error(errors, "IDENTITY_METADATA_PATH_MISMATCH", relpath)
        if relpath not in referenced_identities:
            _error(errors, "UNREFERENCED_IDENTITY_METADATA", relpath)
        raw_relpath = _validate_raw_reference(root, artifact, errors=errors)
        if raw_relpath is not None:
            referenced_raw.add(raw_relpath)
        key = (
            str(artifact.get("source_contract_id")),
            str(artifact.get("request_identity")),
            str(artifact.get("sha256")),
        )
        if receipt_artifacts.get(key) != artifact:
            _error(errors, "IDENTITY_METADATA_WITHOUT_MATCHING_RECEIPT", relpath)

    for relpath in raw_relpaths:
        path = _safe_file(root, relpath, code="RAW_ARTIFACT", errors=errors)
        if path is None:
            continue
        digest = path.name
        expected = f"artifacts/sha256/{digest[:2]}/{digest}"
        if not prospective_capture._is_sha256(digest) or relpath != expected:
            _error(errors, "RAW_ARTIFACT_CONTENT_ADDRESS_INVALID", relpath)
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            _error(errors, "RAW_ARTIFACT_UNREADABLE", relpath)
            continue
        if prospective_capture.sha256_bytes(raw) != digest:
            _error(errors, "RAW_ARTIFACT_SHA256_MISMATCH", relpath)
        if relpath not in referenced_raw:
            _error(errors, "UNREFERENCED_RAW_ARTIFACT", relpath)

    errors[:] = sorted(set(errors))
    if errors:
        report["state"] = "BLOCKED"
    elif not run_relpaths:
        report["state"] = "EMPTY_ARCHIVE"
    elif report["complete_capture_run_count"]:
        report["state"] = "SHADOW_CAPTURE_AUDIT_PASS"
    elif receipt_relpaths:
        report["state"] = "INTEGRITY_PASS_PARTIAL_CAPTURE"
    else:
        report["state"] = "INTEGRITY_PASS_NO_CAPTURE"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit a local ETP prospective shadow capture archive without network access."
    )
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--require-complete-capture", action="store_true")
    args = parser.parse_args(argv)
    report = audit_capture_archive(args.archive_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["state"] == "BLOCKED":
        return 2
    if report["state"] == "EMPTY_ARCHIVE":
        return 3
    if args.require_complete_capture and report["state"] != "SHADOW_CAPTURE_AUDIT_PASS":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
