from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "CRT_POST_SEAL_MATURITY_ATTEMPT_V1"
STATUS_SCHEMA_VERSION = "CRT_POST_SEAL_MATURITY_STATUS_V1"
TARGET_RUNS = 20
GENESIS_HASH = "0" * 64


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("maturity ledger row must be an object")
            rows.append(value)
    previous = GENESIS_HASH
    for index, row in enumerate(rows, start=1):
        if row.get("sequence") != index or row.get("previous_record_hash") != previous:
            raise ValueError("maturity ledger chain is invalid")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        if row.get("record_hash") != _hash(body):
            raise ValueError("maturity ledger record hash mismatch")
        previous = str(row["record_hash"])
    return rows


def _qualification(pack: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if pack.get("pack_state") != "READY_FOR_ANALYST":
        reasons.append(f"PACK_{pack.get('pack_state', 'UNKNOWN')}")
    model = pack.get("model_status", {})
    six_layer = model.get("six_layer_evidence", {})
    scoring = model.get("locked_formal_scoring", {})
    router = model.get("btc_season_router", {})
    if six_layer.get("state") != "COMPLETE_DIRECTIONAL":
        reasons.extend(six_layer.get("blocked_reasons", []) or ["SIX_LAYER_EVIDENCE_NOT_COMPLETE"])
    if scoring.get("state") != "VALID_VERIFIED_EXECUTABLE":
        reasons.append(str(scoring.get("reason") or "FORMAL_SCORING_NOT_VERIFIED"))
    if router.get("state") != "VALID_VERIFIED_EXECUTABLE":
        reasons.append(str(router.get("reason") or "BTC_SEASON_ROUTER_NOT_VERIFIED"))
    authority = pack.get("authority", {})
    if authority.get("external_action_authority") != "NONE" or authority.get("external_action_performed") is not False:
        reasons.append("EXTERNAL_ACTION_BOUNDARY_INVALID")
    return not reasons, sorted(set(reasons))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def record_maturity_attempt(
    ledger_path: str | Path,
    status_path: str | Path,
    pack: dict[str, Any],
    *,
    observed_at_ms: int | None = None,
) -> dict[str, Any]:
    ledger = Path(ledger_path)
    status_target = Path(status_path)
    records = _load_records(ledger)
    pack_hash = pack.get("evidence_pack_hash")
    if not isinstance(pack_hash, str) or len(pack_hash) != 64:
        raise ValueError("evidence_pack_hash invalid")
    existing = next((row for row in records if row.get("evidence_pack_hash") == pack_hash), None)
    if existing is None:
        qualified, reasons = _qualification(pack)
        body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "sequence": len(records) + 1,
            "observed_at_ms": int(time.time() * 1000) if observed_at_ms is None else int(observed_at_ms),
            "evidence_pack_hash": pack_hash,
            "qualified": qualified,
            "blocked_reasons": reasons,
            "previous_record_hash": records[-1]["record_hash"] if records else GENESIS_HASH,
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
        }
        body["record_hash"] = _hash(body)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("ab") as handle:
            handle.write(_canonical_bytes(body) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        records.append(body)

    qualified_count = sum(1 for row in records if row.get("qualified") is True)
    latest = records[-1] if records else None
    status: dict[str, Any] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "qualified_runs": qualified_count,
        "target_runs": TARGET_RUNS,
        "remaining_runs": max(0, TARGET_RUNS - qualified_count),
        "maturity_state": "TARGET_REACHED" if qualified_count >= TARGET_RUNS else "ACCUMULATING",
        "attempt_count": len(records),
        "latest_attempt": latest,
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
    }
    status["status_hash"] = _hash(status)
    _write_json_atomic(status_target, status)
    return status
