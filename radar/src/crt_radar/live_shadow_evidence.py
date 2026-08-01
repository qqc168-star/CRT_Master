from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .liquidation_aggregator import (
    LiquidationStore,
    canonical_json_bytes,
    load_verified_snapshot,
    sha256_hex,
    write_snapshot,
)
from .run_ledger import RunLedger


EVIDENCE_SCHEMA_VERSION = "CRT_LIQ_LIVE_SHADOW_EVIDENCE_V2"


def archive_snapshot(snapshot: dict[str, Any], archive_root: str | Path) -> Path:
    root = Path(archive_root)
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{int(snapshot['as_of_ms'])}_{snapshot['snapshot_hash']}.json"
    path = root / filename
    if path.exists():
        existing = load_verified_snapshot(path)
        if existing["snapshot_hash"] != snapshot["snapshot_hash"]:
            raise ValueError("snapshot archive collision")
        return path
    return write_snapshot(snapshot, path)


def _jsonl_records(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} is not an object")
            rows.append(row)
    return rows


def _store_counts(store: LiquidationStore) -> dict[str, int]:
    with closing(sqlite3.connect(store.db_path)) as db:
        event_count = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        distinct_event_count = int(db.execute("SELECT COUNT(DISTINCT event_hash) FROM events").fetchone()[0])
        session_count = int(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        open_session_count = int(
            db.execute("SELECT COUNT(*) FROM sessions WHERE closed_ms IS NULL").fetchone()[0]
        )
        anomaly_count = int(db.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0])
    return {
        "event_count": event_count,
        "distinct_event_count": distinct_event_count,
        "session_count": session_count,
        "open_session_count": open_session_count,
        "anomaly_count": anomaly_count,
    }


def _process_run_id(row: dict[str, Any]) -> str | None:
    if row.get("record_type") == "PROCESS_EVENT":
        payload = row.get("payload")
        if isinstance(payload, dict):
            value = payload.get("process_run_id")
            return str(value) if value else None
    if row.get("record_type") == "SNAPSHOT":
        payload = row.get("payload")
        if isinstance(payload, dict):
            value = payload.get("process_run_id")
            return str(value) if value else None
    return None


def _event_name(row: dict[str, Any]) -> str | None:
    payload = row.get("payload")
    if row.get("record_type") != "PROCESS_EVENT" or not isinstance(payload, dict):
        return None
    value = payload.get("event")
    return str(value) if value is not None else None


def _select_process_run(rows: list[dict[str, Any]], requested: str | None) -> str | None:
    if requested:
        return requested
    starts = [row for row in rows if _event_name(row) == "PROCESS_START" and _process_run_id(row)]
    if not starts:
        return None
    starts.sort(key=lambda row: int(row.get("sequence", 0)))
    return _process_run_id(starts[-1])


def _safe_archive_path(root: Path, raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("snapshot archive path missing")
    root_resolved = root.resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("snapshot archive path escapes runtime root") from exc
    return candidate


def _process_timeline(
    rows: list[dict[str, Any]],
    process_run_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if process_run_id is None:
        return [], [], ["PROCESS_START_EVIDENCE_MISSING"]
    scoped = [row for row in rows if _process_run_id(row) == process_run_id]
    process_events = [row for row in scoped if row.get("record_type") == "PROCESS_EVENT"]
    snapshots = [row for row in scoped if row.get("record_type") == "SNAPSHOT"]
    process_events.sort(key=lambda row: int(row.get("sequence", 0)))
    snapshots.sort(key=lambda row: int(row.get("sequence", 0)))

    starts = [row for row in process_events if _event_name(row) == "PROCESS_START"]
    stops = [row for row in process_events if _event_name(row) == "PROCESS_STOP"]
    if len(starts) != 1:
        errors.append("PROCESS_START_COUNT_INVALID")
    if len(stops) != 1:
        errors.append("PROCESS_STOP_COUNT_INVALID")
    if starts and stops:
        start_seq = int(starts[0].get("sequence", 0))
        stop_seq = int(stops[-1].get("sequence", 0))
        if start_seq >= stop_seq:
            errors.append("PROCESS_EVENT_ORDER_INVALID")
        if process_events and int(process_events[0].get("sequence", 0)) != start_seq:
            errors.append("PROCESS_START_NOT_FIRST")
        if process_events and int(process_events[-1].get("sequence", 0)) != stop_seq:
            errors.append("PROCESS_STOP_NOT_LAST")
        if any(not (start_seq < int(row.get("sequence", 0)) < stop_seq) for row in snapshots):
            errors.append("SNAPSHOT_OUTSIDE_PROCESS_SEQUENCE")

    segment_starts: dict[int, int] = {}
    segment_stops: dict[int, int] = {}
    for row in process_events:
        name = _event_name(row)
        payload = row.get("payload")
        details = payload.get("details") if isinstance(payload, dict) else None
        if not isinstance(details, dict):
            details = {}
        if name not in {"SEGMENT_START", "SEGMENT_STOP"}:
            continue
        try:
            index = int(details["segment_index"])
        except (KeyError, TypeError, ValueError):
            errors.append("SEGMENT_INDEX_INVALID")
            continue
        target = segment_starts if name == "SEGMENT_START" else segment_stops
        if index in target:
            errors.append("SEGMENT_EVENT_DUPLICATE")
        target[index] = int(row.get("sequence", 0))
    if segment_starts or segment_stops:
        if set(segment_starts) != set(segment_stops):
            errors.append("SEGMENT_PAIR_MISMATCH")
        for index in set(segment_starts) & set(segment_stops):
            if segment_starts[index] >= segment_stops[index]:
                errors.append("SEGMENT_EVENT_ORDER_INVALID")
        if sorted(segment_starts) != list(range(len(segment_starts))):
            errors.append("SEGMENT_INDEX_GAP")

    return process_events, snapshots, errors


def build_evidence_summary(
    runtime_root: str | Path,
    ledger_path: str | Path,
    *,
    minimum_duration_s: int = 86_400,
    minimum_coverage_ratio: float = 0.95,
    required_controlled_restarts: int = 1,
    process_run_id: str | None = None,
    expected_registry_hash: str | None = None,
    snapshot_interval_s: int | None = None,
    minimum_snapshot_delivery_ratio: float = 0.0,
    maximum_snapshot_gap_s: int | None = None,
    maximum_snapshot_clock_skew_s: int = 300,
    elapsed_duration_tolerance_s: float = 2.0,
) -> dict[str, Any]:
    root = Path(runtime_root)
    store = LiquidationStore(root)
    ledger = RunLedger(ledger_path)
    ledger_validation = ledger.validate()
    rows = ledger.records() if ledger_validation.valid else []
    selected_process_run_id = _select_process_run(rows, process_run_id)
    process_events, snapshots, timeline_errors = _process_timeline(rows, selected_process_run_id)
    process_names = [_event_name(row) for row in process_events]
    controlled_restarts = sum(1 for name in process_names if name == "CONTROLLED_RESTART")

    starts = [row for row in process_events if _event_name(row) == "PROCESS_START"]
    stops = [row for row in process_events if _event_name(row) == "PROCESS_STOP"]
    start_observed_ms = int(starts[0]["observed_ms"]) if len(starts) == 1 else None
    stop_observed_ms = int(stops[0]["observed_ms"]) if len(stops) == 1 else None
    process_duration_ms = (
        max(0, stop_observed_ms - start_observed_ms)
        if start_observed_ms is not None and stop_observed_ms is not None
        else 0
    )
    stop_outcomes: list[str] = []
    reported_elapsed_s: float | None = None
    for row in stops:
        payload = row.get("payload")
        details = payload.get("details") if isinstance(payload, dict) else None
        if isinstance(details, dict):
            if details.get("outcome") is not None:
                stop_outcomes.append(str(details.get("outcome")))
            if details.get("elapsed_s") is not None:
                try:
                    reported_elapsed_s = float(details["elapsed_s"])
                except (TypeError, ValueError):
                    reported_elapsed_s = None

    archive_errors: list[str] = []
    snapshot_payloads: list[dict[str, Any]] = []
    snapshot_registry_hashes: list[str] = []
    for row in snapshots:
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            archive_errors.append("snapshot ledger payload is not an object")
            continue
        snapshot_registry_hashes.append(str(payload.get("registry_hash", "")))
        try:
            archive_path = _safe_archive_path(root, payload.get("archive_path"))
            archived = load_verified_snapshot(archive_path)
            if archived["snapshot_hash"] != payload.get("snapshot_hash"):
                raise ValueError("snapshot hash differs from ledger")
            if int(archived["as_of_ms"]) != int(payload.get("as_of_ms")):
                raise ValueError("snapshot as_of differs from ledger")
            snapshot_payloads.append(archived)
        except Exception as exc:
            archive_errors.append(f"{payload.get('archive_path')}: {type(exc).__name__}: {exc}")

    coverages = [float(s["coverage_ratio"]) for s in snapshot_payloads]
    valid_snapshots = [
        s for s in snapshot_payloads if s.get("quality_state") == "VALID_FRESH_COMPLETE_COVERAGE"
    ]
    blocked_snapshots = [s for s in snapshot_payloads if s.get("quality_state") == "BLOCKED"]
    snapshot_times = [int(s["as_of_ms"]) for s in snapshot_payloads]

    raw_event_errors: list[str] = []
    try:
        raw_event_rows = _jsonl_records(list((root / "raw" / "events").glob("*.jsonl")))
    except Exception as exc:
        raw_event_rows = []
        raw_event_errors.append(f"{type(exc).__name__}: {exc}")
    raw_event_hashes = [str(row.get("event_hash")) for row in raw_event_rows]
    store_counts = _store_counts(store)

    acceptance_failures: list[str] = list(timeline_errors)
    if not ledger_validation.valid:
        acceptance_failures.append("RUN_LEDGER_INVALID")
    if archive_errors:
        acceptance_failures.append("SNAPSHOT_ARCHIVE_INVALID")
    if raw_event_errors:
        acceptance_failures.append("RAW_EVENT_ARCHIVE_INVALID")
    if not store.integrity_ok():
        acceptance_failures.append("STORE_INTEGRITY_FAILED")
    if store_counts["event_count"] != store_counts["distinct_event_count"]:
        acceptance_failures.append("STORE_EVENT_DUPLICATES")
    if len(raw_event_hashes) != len(set(raw_event_hashes)):
        acceptance_failures.append("RAW_EVENT_DUPLICATES")
    if not raw_event_errors and len(raw_event_hashes) != store_counts["event_count"]:
        acceptance_failures.append("RAW_EVENT_DB_COUNT_MISMATCH")
    if store_counts["open_session_count"] != 0:
        acceptance_failures.append("OPEN_SESSION_REMAINS")
    if process_duration_ms < minimum_duration_s * 1000:
        acceptance_failures.append("LIVE_DURATION_BELOW_POLICY")
    if reported_elapsed_s is None:
        acceptance_failures.append("PROCESS_ELAPSED_EVIDENCE_MISSING")
    elif not math.isfinite(reported_elapsed_s) or reported_elapsed_s < 0:
        acceptance_failures.append("PROCESS_ELAPSED_INVALID")
    elif reported_elapsed_s + elapsed_duration_tolerance_s < minimum_duration_s:
        acceptance_failures.append("PROCESS_ELAPSED_BELOW_POLICY")
    if controlled_restarts < required_controlled_restarts:
        acceptance_failures.append("CONTROLLED_RESTART_MISSING")
    if not stop_outcomes:
        acceptance_failures.append("PROCESS_STOP_EVIDENCE_MISSING")
    elif stop_outcomes[-1] != "COMPLETED":
        acceptance_failures.append("PROCESS_NOT_COMPLETED")
    if not snapshot_payloads:
        acceptance_failures.append("NO_SNAPSHOTS")
    if coverages and min(coverages) < minimum_coverage_ratio:
        acceptance_failures.append("SNAPSHOT_COVERAGE_BELOW_POLICY")
    if blocked_snapshots:
        acceptance_failures.append("BLOCKED_SNAPSHOT_PRESENT")
    if expected_registry_hash is not None:
        if any(value != expected_registry_hash for value in snapshot_registry_hashes):
            acceptance_failures.append("SOURCE_REGISTRY_HASH_MISMATCH")
    if len(snapshot_times) != len(set(snapshot_times)):
        acceptance_failures.append("SNAPSHOT_TIMESTAMP_DUPLICATE")
    if snapshot_times != sorted(snapshot_times):
        acceptance_failures.append("SNAPSHOT_TIMESTAMPS_NOT_MONOTONIC")
    if start_observed_ms is not None and stop_observed_ms is not None:
        skew_ms = maximum_snapshot_clock_skew_s * 1000
        if any(value < start_observed_ms - skew_ms or value > stop_observed_ms + skew_ms for value in snapshot_times):
            acceptance_failures.append("SNAPSHOT_CLOCK_OUTSIDE_PROCESS_WINDOW")
    expected_snapshot_count: int | None = None
    snapshot_delivery_ratio: float | None = None
    maximum_observed_snapshot_gap_ms: int | None = None
    if snapshot_interval_s is not None:
        if snapshot_interval_s <= 0:
            acceptance_failures.append("SNAPSHOT_INTERVAL_POLICY_INVALID")
        else:
            expected_snapshot_count = max(1, int(minimum_duration_s // snapshot_interval_s))
            snapshot_delivery_ratio = len(snapshot_payloads) / expected_snapshot_count
            if snapshot_delivery_ratio < minimum_snapshot_delivery_ratio:
                acceptance_failures.append("SNAPSHOT_DELIVERY_RATIO_BELOW_POLICY")
            if start_observed_ms is not None and stop_observed_ms is not None and snapshot_times:
                checkpoints = [start_observed_ms, *snapshot_times, stop_observed_ms]
                maximum_observed_snapshot_gap_ms = max(
                    max(0, right - left) for left, right in zip(checkpoints, checkpoints[1:])
                )
                allowed_gap_s = maximum_snapshot_gap_s or snapshot_interval_s * 3
                if maximum_observed_snapshot_gap_ms > allowed_gap_s * 1000:
                    acceptance_failures.append("SNAPSHOT_GAP_ABOVE_POLICY")

    result = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "runtime_root": str(root),
        "ledger_path": str(Path(ledger_path)),
        "process_run_id": selected_process_run_id,
        "ledger": ledger_validation.as_dict(),
        "process_start_observed_ms": start_observed_ms,
        "process_stop_observed_ms": stop_observed_ms,
        "duration_ms": process_duration_ms,
        "reported_elapsed_s": reported_elapsed_s,
        "snapshot_count": len(snapshot_payloads),
        "expected_snapshot_count": expected_snapshot_count,
        "snapshot_delivery_ratio": snapshot_delivery_ratio,
        "maximum_observed_snapshot_gap_ms": maximum_observed_snapshot_gap_ms,
        "valid_snapshot_count": len(valid_snapshots),
        "blocked_snapshot_count": len(blocked_snapshots),
        "minimum_observed_coverage_ratio": min(coverages) if coverages else None,
        "controlled_restart_count": controlled_restarts,
        "process_events": process_names,
        "process_stop_outcomes": stop_outcomes,
        "store_counts": store_counts,
        "raw_event_line_count": len(raw_event_rows),
        "raw_event_errors": raw_event_errors,
        "archive_errors": archive_errors,
        "snapshot_registry_hashes": sorted(set(snapshot_registry_hashes)),
        "acceptance_policy": {
            "minimum_duration_s": minimum_duration_s,
            "minimum_coverage_ratio": minimum_coverage_ratio,
            "required_controlled_restarts": required_controlled_restarts,
            "snapshot_interval_s": snapshot_interval_s,
            "minimum_snapshot_delivery_ratio": minimum_snapshot_delivery_ratio,
            "maximum_snapshot_gap_s": maximum_snapshot_gap_s,
            "maximum_snapshot_clock_skew_s": maximum_snapshot_clock_skew_s,
            "elapsed_duration_tolerance_s": elapsed_duration_tolerance_s,
            "expected_registry_hash": expected_registry_hash,
        },
        "acceptance_failures": sorted(set(acceptance_failures)),
        "decision": "LIVE_SHADOW_PASS" if not acceptance_failures else "LIVE_SHADOW_NOT_YET_PASSED",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    material = dict(result)
    result["evidence_hash"] = sha256_hex(canonical_json_bytes(material))
    return result


def write_evidence_summary(summary: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output
