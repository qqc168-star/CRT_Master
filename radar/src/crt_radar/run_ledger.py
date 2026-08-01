from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .liquidation_aggregator import canonical_json_bytes, sha256_hex, verify_snapshot


LEDGER_SCHEMA_VERSION = "CRT_RUN_LEDGER_RECORD_V1"
GENESIS_HASH = "0" * 64
EXTERNAL_ACTION_AUTHORITY = "NONE"


class RunLedgerError(ValueError):
    """Raised when an append-only run ledger is invalid or tampered with."""


@dataclass(frozen=True)
class LedgerValidation:
    valid: bool
    record_count: int
    last_sequence: int
    head_hash: str
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "record_count": self.record_count,
            "last_sequence": self.last_sequence,
            "head_hash": self.head_hash,
            "errors": list(self.errors),
        }


class RunLedger:
    """Hash-chained append-only JSONL ledger for Live Shadow evidence.

    The ledger has no mutation or delete API. Every record contains the hash of
    the previous record, so edits, reordering and truncation at the tail are
    detectable when a known checkpoint head hash is retained.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _raw_lines(self) -> list[bytes]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        if not raw:
            return []
        if not raw.endswith(b"\n"):
            raise RunLedgerError("ledger does not end with newline; possible torn append")
        return [line for line in raw.splitlines() if line.strip()]

    def records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for index, raw_line in enumerate(self._raw_lines(), start=1):
            try:
                row = json.loads(raw_line.decode("utf-8"))
            except Exception as exc:  # pragma: no cover - exact decoder detail is unimportant
                raise RunLedgerError(f"invalid JSON at ledger line {index}") from exc
            if not isinstance(row, dict):
                raise RunLedgerError(f"ledger line {index} is not an object")
            records.append(row)
        return records

    @staticmethod
    def _body_for_hash(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "record_hash"}

    @classmethod
    def compute_record_hash(cls, record: dict[str, Any]) -> str:
        return sha256_hex(canonical_json_bytes(cls._body_for_hash(record)))

    def validate(self, *, expected_head_hash: str | None = None) -> LedgerValidation:
        errors: list[str] = []
        try:
            rows = self.records()
        except RunLedgerError as exc:
            return LedgerValidation(False, 0, 0, GENESIS_HASH, (str(exc),))

        previous_hash = GENESIS_HASH
        seen_hashes: set[str] = set()
        seen_snapshot_keys: set[tuple[int, str]] = set()
        last_sequence = 0

        for line_number, row in enumerate(rows, start=1):
            sequence = row.get("sequence")
            if sequence != line_number:
                errors.append(
                    f"line {line_number}: sequence {sequence!r} is not contiguous"
                )
            if row.get("schema_version") != LEDGER_SCHEMA_VERSION:
                errors.append(f"line {line_number}: wrong schema_version")
            if row.get("prev_record_hash") != previous_hash:
                errors.append(f"line {line_number}: previous hash mismatch")
            if row.get("external_action_authority") != EXTERNAL_ACTION_AUTHORITY:
                errors.append(f"line {line_number}: external action authority is not NONE")
            if row.get("external_action_performed") is not False:
                errors.append(f"line {line_number}: external_action_performed must be false")

            stored_hash = row.get("record_hash")
            computed_hash = self.compute_record_hash(row)
            if stored_hash != computed_hash:
                errors.append(f"line {line_number}: record hash mismatch")
            if isinstance(stored_hash, str):
                if stored_hash in seen_hashes:
                    errors.append(f"line {line_number}: duplicate record hash")
                seen_hashes.add(stored_hash)
                previous_hash = stored_hash

            if row.get("record_type") == "SNAPSHOT":
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    errors.append(f"line {line_number}: snapshot payload missing")
                else:
                    key = (int(payload.get("as_of_ms", -1)), str(payload.get("snapshot_hash")))
                    if key in seen_snapshot_keys:
                        errors.append(f"line {line_number}: duplicate snapshot ledger key")
                    seen_snapshot_keys.add(key)

            if isinstance(sequence, int):
                last_sequence = sequence

        if expected_head_hash is not None and previous_hash != expected_head_hash:
            errors.append("ledger head hash does not match retained checkpoint")

        return LedgerValidation(
            valid=not errors,
            record_count=len(rows),
            last_sequence=last_sequence,
            head_hash=previous_hash,
            errors=tuple(errors),
        )

    def _last_record(self) -> dict[str, Any] | None:
        rows = self.records()
        return rows[-1] if rows else None

    def _snapshot_exists(self, as_of_ms: int, snapshot_hash: str) -> dict[str, Any] | None:
        for row in reversed(self.records()):
            if row.get("record_type") != "SNAPSHOT":
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("as_of_ms") == as_of_ms and payload.get("snapshot_hash") == snapshot_hash:
                return row
        return None

    def append(
        self,
        record_type: str,
        payload: dict[str, Any],
        *,
        observed_ms: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.validate()
        if not current.valid:
            raise RunLedgerError("refusing append to invalid ledger: " + "; ".join(current.errors))

        now = int(time.time() * 1000) if observed_ms is None else int(observed_ms)
        previous = self._last_record()
        record: dict[str, Any] = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "sequence": current.record_count + 1,
            "record_type": str(record_type),
            "run_id": run_id or str(uuid.uuid4()),
            "observed_ms": now,
            "prev_record_hash": previous["record_hash"] if previous else GENESIS_HASH,
            "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
            "external_action_performed": False,
            "payload": payload,
        }
        record["record_hash"] = self.compute_record_hash(record)
        line = canonical_json_bytes(record) + b"\n"
        with self.path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

        post = self.validate()
        if not post.valid:
            raise RunLedgerError("ledger failed validation after append: " + "; ".join(post.errors))
        return record

    def append_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        registry_hash: str,
        archive_path: str,
        elapsed_ms: int,
        process_run_id: str,
        observed_ms: int | None = None,
    ) -> dict[str, Any]:
        verify_snapshot(snapshot)
        as_of_ms = int(snapshot["as_of_ms"])
        snapshot_hash = str(snapshot["snapshot_hash"])
        existing = self._snapshot_exists(as_of_ms, snapshot_hash)
        if existing is not None:
            return {
                "append_status": "DUPLICATE_SKIPPED",
                "existing_record_hash": existing["record_hash"],
                "existing_sequence": existing["sequence"],
            }

        payload = {
            "as_of_ms": as_of_ms,
            "registry_hash": registry_hash,
            "snapshot_hash": snapshot_hash,
            "archive_path": archive_path,
            "coverage_ratio": float(snapshot["coverage_ratio"]),
            "quality_state": snapshot["quality_state"],
            "blocked_reasons": list(snapshot.get("blocked_reasons", [])),
            "elapsed_ms": int(elapsed_ms),
            "event_set_hash": snapshot["event_set_hash"],
            "connection_set_hash": snapshot["connection_set_hash"],
            "process_run_id": process_run_id,
        }
        record = self.append(
            "SNAPSHOT",
            payload,
            observed_ms=observed_ms if observed_ms is not None else as_of_ms,
            run_id=str(uuid.uuid4()),
        )
        record["append_status"] = "APPENDED"
        return record

    def append_process_event(
        self,
        event: str,
        *,
        process_run_id: str,
        details: dict[str, Any] | None = None,
        observed_ms: int | None = None,
    ) -> dict[str, Any]:
        return self.append(
            "PROCESS_EVENT",
            {
                "event": event,
                "process_run_id": process_run_id,
                "details": details or {},
            },
            observed_ms=observed_ms,
            run_id=str(uuid.uuid4()),
        )

    def iter_type(self, record_type: str) -> Iterable[dict[str, Any]]:
        for row in self.records():
            if row.get("record_type") == record_type:
                yield row
