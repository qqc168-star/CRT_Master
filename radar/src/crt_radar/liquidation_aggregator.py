from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "CRT_LIQ_AGGREGATE_SNAPSHOT_V1"
EVENT_SCHEMA_VERSION = "CRT_LIQ_EVENT_V1"
STORE_SCHEMA_VERSION = "CRT_LIQ_STORE_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"
FUTURE_CLOCK_SKEW_MS = 300_000


class LiquidationError(ValueError):
    pass


class SnapshotCorruption(LiquidationError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _finite(value: Any, field: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise LiquidationError(f"{field} missing or invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LiquidationError(f"{field} not numeric") from exc
    if not math.isfinite(number):
        raise LiquidationError(f"{field} not finite")
    if positive and number <= 0:
        raise LiquidationError(f"{field} must be positive")
    return number


def _timestamp_ms(value: Any, field: str) -> int:
    number = int(_finite(value, field, positive=True))
    if number < 1_000_000_000_000:
        raise LiquidationError(f"{field} is not millisecond Unix time")
    return number


def _unwrap_force_order(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LiquidationError("forceOrder payload must be an object")
    if "data" in payload and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if payload.get("e") != "forceOrder":
        raise LiquidationError("event type must be forceOrder")
    order = payload.get("o")
    if not isinstance(order, dict):
        raise LiquidationError("forceOrder order object missing")
    return payload


@dataclass(frozen=True)
class NormalizedLiquidationEvent:
    event_hash: str
    event_time_ms: int
    trade_time_ms: int
    received_ms: int
    symbol: str
    order_side: str
    liquidation_side: str
    price: float
    filled_quantity: float
    notional_usd: float
    out_of_order: bool
    raw_payload: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_hash": self.event_hash,
            "event_time_ms": self.event_time_ms,
            "trade_time_ms": self.trade_time_ms,
            "received_ms": self.received_ms,
            "symbol": self.symbol,
            "order_side": self.order_side,
            "liquidation_side": self.liquidation_side,
            "price": self.price,
            "filled_quantity": self.filled_quantity,
            "notional_usd": self.notional_usd,
            "out_of_order": self.out_of_order,
            "raw_payload": self.raw_payload,
        }


def normalize_force_order(
    payload: Any,
    *,
    received_ms: int,
    last_event_time_ms: int | None = None,
    future_clock_skew_ms: int = FUTURE_CLOCK_SKEW_MS,
) -> NormalizedLiquidationEvent:
    row = _unwrap_force_order(payload)
    order = row["o"]
    symbol = order.get("s")
    if symbol != "BTCUSDT":
        raise LiquidationError("forceOrder symbol must be BTCUSDT")
    order_side = order.get("S")
    if order_side not in {"BUY", "SELL"}:
        raise LiquidationError("forceOrder side must be BUY or SELL")

    event_time_ms = _timestamp_ms(row.get("E"), "E")
    trade_time_ms = _timestamp_ms(order.get("T"), "o.T")
    if event_time_ms > received_ms + future_clock_skew_ms:
        raise LiquidationError("event clock is implausibly in the future")
    if trade_time_ms > received_ms + future_clock_skew_ms:
        raise LiquidationError("trade clock is implausibly in the future")

    price_value = order.get("ap")
    try:
        price = _finite(price_value, "o.ap", positive=True)
    except LiquidationError:
        price = _finite(order.get("p"), "o.p", positive=True)

    quantity: float | None = None
    for field in ("z", "l", "q"):
        try:
            quantity = _finite(order.get(field), f"o.{field}", positive=True)
            break
        except LiquidationError:
            continue
    if quantity is None:
        raise LiquidationError("no positive filled quantity available")

    raw_payload = row
    event_hash = sha256_hex(canonical_json_bytes(raw_payload))
    liquidation_side = "LONG" if order_side == "SELL" else "SHORT"
    out_of_order = last_event_time_ms is not None and event_time_ms < last_event_time_ms
    return NormalizedLiquidationEvent(
        event_hash=event_hash,
        event_time_ms=event_time_ms,
        trade_time_ms=trade_time_ms,
        received_ms=received_ms,
        symbol=symbol,
        order_side=order_side,
        liquidation_side=liquidation_side,
        price=price,
        filled_quantity=quantity,
        notional_usd=price * quantity,
        out_of_order=out_of_order,
        raw_payload=raw_payload,
    )


class LiquidationStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.raw_events_dir = self.root / "raw" / "events"
        self.raw_connections_dir = self.root / "raw" / "connections"
        self.snapshots_dir = self.root / "snapshots"
        self.state_dir = self.root / "state"
        for path in (self.raw_events_dir, self.raw_connections_dir, self.snapshots_dir, self.state_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "liquidation_store.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_hash TEXT PRIMARY KEY,
                    event_time_ms INTEGER NOT NULL,
                    trade_time_ms INTEGER NOT NULL,
                    received_ms INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    order_side TEXT NOT NULL,
                    liquidation_side TEXT NOT NULL,
                    price REAL NOT NULL,
                    filled_quantity REAL NOT NULL,
                    notional_usd REAL NOT NULL,
                    out_of_order INTEGER NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_time ON events(event_time_ms);
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    opened_ms INTEGER NOT NULL,
                    last_heartbeat_ms INTEGER NOT NULL,
                    closed_ms INTEGER,
                    close_reason TEXT,
                    reconnect_index INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(opened_ms);
                CREATE TABLE IF NOT EXISTS anomalies (
                    anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anomaly_type TEXT NOT NULL,
                    observed_ms INTEGER NOT NULL,
                    event_hash TEXT,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_anomalies_time ON anomalies(observed_ms);
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)").fetchall()}
            if "last_heartbeat_ms" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN last_heartbeat_ms INTEGER")
                db.execute("UPDATE sessions SET last_heartbeat_ms=opened_ms WHERE last_heartbeat_ms IS NULL")
            db.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (STORE_SCHEMA_VERSION,),
            )

    @staticmethod
    def _utc_date(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()

    @staticmethod
    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = canonical_json_bytes(record) + b"\n"
        with path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def integrity_ok(self) -> bool:
        with closing(self._connect()) as db, db:
            row = db.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")

    def latest_event_time_ms(self) -> int | None:
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT MAX(event_time_ms) FROM events").fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def record_anomaly(
        self,
        anomaly_type: str,
        *,
        observed_ms: int,
        details: dict[str, Any],
        event_hash: str | None = None,
    ) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO anomalies(anomaly_type, observed_ms, event_hash, details_json) VALUES(?,?,?,?)",
                (anomaly_type, observed_ms, event_hash, canonical_json_bytes(details).decode("utf-8")),
            )

    def ingest_force_order(self, payload: Any, *, received_ms: int | None = None) -> bool:
        received = int(time.time() * 1000) if received_ms is None else received_ms
        raw_hash: str | None = None
        try:
            if isinstance(payload, dict):
                raw_hash = sha256_hex(canonical_json_bytes(payload))
            normalized = normalize_force_order(
                payload,
                received_ms=received,
                last_event_time_ms=self.latest_event_time_ms(),
            )
        except Exception as exc:
            self.record_anomaly(
                "INVALID_OR_CLOCK_ANOMALY",
                observed_ms=received,
                event_hash=raw_hash,
                details={"error": f"{type(exc).__name__}: {exc}", "payload": payload},
            )
            return False

        record = normalized.as_record()
        with closing(self._connect()) as db, db:
            exists = db.execute(
                "SELECT 1 FROM events WHERE event_hash=?",
                (normalized.event_hash,),
            ).fetchone()
            if exists:
                return False
            raw_path = self.raw_events_dir / f"{self._utc_date(normalized.event_time_ms)}.jsonl"
            self._append_jsonl(raw_path, record)
            db.execute(
                """
                INSERT INTO events(
                    event_hash,event_time_ms,trade_time_ms,received_ms,symbol,order_side,
                    liquidation_side,price,filled_quantity,notional_usd,out_of_order,raw_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    normalized.event_hash,
                    normalized.event_time_ms,
                    normalized.trade_time_ms,
                    normalized.received_ms,
                    normalized.symbol,
                    normalized.order_side,
                    normalized.liquidation_side,
                    normalized.price,
                    normalized.filled_quantity,
                    normalized.notional_usd,
                    int(normalized.out_of_order),
                    canonical_json_bytes(normalized.raw_payload).decode("utf-8"),
                ),
            )
        return True

    def begin_session(
        self,
        *,
        opened_ms: int | None = None,
        reconnect_index: int = 0,
        session_id: str | None = None,
    ) -> str:
        opened = int(time.time() * 1000) if opened_ms is None else opened_ms
        sid = session_id or str(uuid.uuid4())
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO sessions(session_id,opened_ms,last_heartbeat_ms,reconnect_index) VALUES(?,?,?,?)",
                (sid, opened, opened, reconnect_index),
            )
        return sid

    def touch_session(self, session_id: str, *, heartbeat_ms: int | None = None) -> None:
        heartbeat = int(time.time() * 1000) if heartbeat_ms is None else heartbeat_ms
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT opened_ms,closed_ms,last_heartbeat_ms FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise LiquidationError(f"unknown session_id: {session_id}")
            if row["closed_ms"] is not None:
                raise LiquidationError(f"cannot heartbeat closed session: {session_id}")
            if heartbeat < int(row["opened_ms"]):
                raise LiquidationError("heartbeat before session open")
            if heartbeat < int(row["last_heartbeat_ms"]):
                raise LiquidationError("heartbeat moved backwards")
            db.execute(
                "UPDATE sessions SET last_heartbeat_ms=? WHERE session_id=?",
                (heartbeat, session_id),
            )

    def recover_orphan_sessions(self) -> int:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                "SELECT session_id,opened_ms,last_heartbeat_ms,reconnect_index FROM sessions WHERE closed_ms IS NULL"
            ).fetchall()
            for row in rows:
                closed = int(row["last_heartbeat_ms"])
                db.execute(
                    "UPDATE sessions SET closed_ms=?,close_reason=? WHERE session_id=?",
                    (closed, "ORPHANED_ON_RESTART", row["session_id"]),
                )
                self._append_jsonl(
                    self.raw_connections_dir / f"{self._utc_date(closed)}.jsonl",
                    {
                        "schema_version": "CRT_LIQ_CONNECTION_INTERVAL_V1",
                        "session_id": row["session_id"],
                        "opened_ms": int(row["opened_ms"]),
                        "closed_ms": closed,
                        "close_reason": "ORPHANED_ON_RESTART",
                        "reconnect_index": int(row["reconnect_index"]),
                    },
                )
        return len(rows)

    def end_session(
        self,
        session_id: str,
        *,
        closed_ms: int | None = None,
        close_reason: str = "NORMAL",
    ) -> None:
        closed = int(time.time() * 1000) if closed_ms is None else closed_ms
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT opened_ms,last_heartbeat_ms,reconnect_index,closed_ms FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise LiquidationError(f"unknown session_id: {session_id}")
            if row["closed_ms"] is not None:
                raise LiquidationError(f"session already closed: {session_id}")
            if closed < int(row["opened_ms"]):
                raise LiquidationError("session closed before it opened")
            db.execute(
                "UPDATE sessions SET closed_ms=?,close_reason=? WHERE session_id=?",
                (closed, close_reason, session_id),
            )
        self._append_jsonl(
            self.raw_connections_dir / f"{self._utc_date(closed)}.jsonl",
            {
                "schema_version": "CRT_LIQ_CONNECTION_INTERVAL_V1",
                "session_id": session_id,
                "opened_ms": int(row["opened_ms"]),
                "closed_ms": closed,
                "close_reason": close_reason,
                "reconnect_index": int(row["reconnect_index"]),
            },
        )

    def close_open_sessions(self, *, closed_ms: int, close_reason: str) -> int:
        with closing(self._connect()) as db, db:
            rows = db.execute("SELECT session_id FROM sessions WHERE closed_ms IS NULL").fetchall()
        for row in rows:
            self.end_session(row["session_id"], closed_ms=closed_ms, close_reason=close_reason)
        return len(rows)

    def events_between(self, start_ms: int, end_ms: int) -> list[sqlite3.Row]:
        with closing(self._connect()) as db, db:
            return db.execute(
                """
                SELECT * FROM events
                WHERE event_time_ms > ? AND event_time_ms <= ?
                ORDER BY event_time_ms,event_hash
                """,
                (start_ms, end_ms),
            ).fetchall()

    def intervals_overlapping(self, start_ms: int, end_ms: int) -> list[tuple[int, int, str]]:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                """
                SELECT session_id,opened_ms,COALESCE(closed_ms, ?) AS effective_closed
                FROM sessions
                WHERE opened_ms < ? AND COALESCE(closed_ms, ?) > ?
                ORDER BY opened_ms,effective_closed
                """,
                (end_ms, end_ms, end_ms, start_ms),
            ).fetchall()
        return [
            (max(start_ms, int(row["opened_ms"])), min(end_ms, int(row["effective_closed"])), row["session_id"])
            for row in rows
            if min(end_ms, int(row["effective_closed"])) > max(start_ms, int(row["opened_ms"]))
        ]

    def anomalies_between(self, start_ms: int, end_ms: int) -> list[sqlite3.Row]:
        with closing(self._connect()) as db, db:
            return db.execute(
                "SELECT * FROM anomalies WHERE observed_ms > ? AND observed_ms <= ? ORDER BY observed_ms",
                (start_ms, end_ms),
            ).fetchall()


def merge_intervals(intervals: Iterable[tuple[int, int, str]]) -> list[tuple[int, int]]:
    ordered = sorted((start, end) for start, end, _ in intervals if end > start)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _window_summary(store: LiquidationStore, *, label: str, seconds: int, as_of_ms: int) -> dict[str, Any]:
    start_ms = as_of_ms - seconds * 1000
    rows = store.events_between(start_ms, as_of_ms)
    long_usd = sum(float(row["notional_usd"]) for row in rows if row["liquidation_side"] == "LONG")
    short_usd = sum(float(row["notional_usd"]) for row in rows if row["liquidation_side"] == "SHORT")
    merged = merge_intervals(store.intervals_overlapping(start_ms, as_of_ms))
    covered_ms = sum(end - start for start, end in merged)
    coverage_ratio = covered_ms / (seconds * 1000)
    return {
        "window": label,
        "window_start_ms": start_ms,
        "window_end_ms": as_of_ms,
        "long_liquidation_usd": long_usd,
        "short_liquidation_usd": short_usd,
        "total_liquidation_usd": long_usd + short_usd,
        "event_count": len(rows),
        "coverage_ratio": coverage_ratio,
        "covered_ms": covered_ms,
        "gap_ms": seconds * 1000 - covered_ms,
        "quiet_window": len(rows) == 0,
        "event_hashes": [row["event_hash"] for row in rows],
        "merged_intervals": [[start, end] for start, end in merged],
    }


def build_snapshot(
    store: LiquidationStore,
    *,
    as_of_ms: int | None = None,
    minimum_coverage_ratio: float = 0.95,
) -> dict[str, Any]:
    as_of = int(time.time() * 1000) if as_of_ms is None else as_of_ms
    if not 0 <= minimum_coverage_ratio <= 1:
        raise LiquidationError("minimum_coverage_ratio must be between 0 and 1")

    windows_raw = {
        "1h": _window_summary(store, label="1h", seconds=3600, as_of_ms=as_of),
        "24h": _window_summary(store, label="24h", seconds=86400, as_of_ms=as_of),
    }
    blocked_reasons: list[str] = []
    if not store.integrity_ok():
        blocked_reasons.append("STORE_INTEGRITY_FAILED")

    coverage_ratio = min(windows_raw["1h"]["coverage_ratio"], windows_raw["24h"]["coverage_ratio"])
    for label, window in windows_raw.items():
        if window["coverage_ratio"] < minimum_coverage_ratio:
            blocked_reasons.append(f"{label.upper()}_COVERAGE_BELOW_{minimum_coverage_ratio:.2f}")

    anomalies = store.anomalies_between(as_of - 86400_000, as_of)
    if anomalies:
        blocked_reasons.append("CLOCK_OR_SCHEMA_ANOMALY_WITHIN_24H")

    event_hashes = sorted(set(windows_raw["24h"]["event_hashes"]))
    interval_material = {
        label: windows_raw[label]["merged_intervals"] for label in ("1h", "24h")
    }
    public_windows: dict[str, Any] = {}
    for label, window in windows_raw.items():
        public_windows[label] = {
            key: value
            for key, value in window.items()
            if key not in {"event_hashes", "merged_intervals", "window"}
        }

    base = {
        "schema_version": SCHEMA_VERSION,
        "store_schema_version": STORE_SCHEMA_VERSION,
        "symbol": "BTCUSDT",
        "as_of_ms": as_of,
        "generated_at_ms": as_of,
        "minimum_coverage_ratio": minimum_coverage_ratio,
        "coverage_ratio": coverage_ratio,
        "quality_state": "BLOCKED" if blocked_reasons else "VALID_FRESH_COMPLETE_COVERAGE",
        "blocked_reasons": sorted(set(blocked_reasons)),
        "windows": public_windows,
        "event_set_hash": sha256_hex(canonical_json_bytes(event_hashes)),
        "connection_set_hash": sha256_hex(canonical_json_bytes(interval_material)),
        "event_count_24h": len(event_hashes),
        "anomaly_count_24h": len(anomalies),
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
    }
    base["snapshot_id"] = sha256_hex(canonical_json_bytes(base))
    base["snapshot_hash"] = sha256_hex(canonical_json_bytes(base))
    return base


def verify_snapshot(snapshot: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict):
        raise SnapshotCorruption("snapshot must be an object")
    expected = snapshot.get("snapshot_hash")
    if not isinstance(expected, str) or len(expected) != 64:
        raise SnapshotCorruption("snapshot_hash missing or invalid")
    material = dict(snapshot)
    material.pop("snapshot_hash", None)
    actual = sha256_hex(canonical_json_bytes(material))
    if actual != expected:
        raise SnapshotCorruption("snapshot hash mismatch")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotCorruption("snapshot schema mismatch")
    if snapshot.get("external_action_authority") != "NONE":
        raise SnapshotCorruption("snapshot cannot have external action authority")


def write_snapshot(snapshot: dict[str, Any], path: str | Path) -> Path:
    verify_snapshot(snapshot)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))
        handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    return output


def load_verified_snapshot(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    verify_snapshot(payload)
    return payload
