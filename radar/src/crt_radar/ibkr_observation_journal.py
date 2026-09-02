"""Durable, plan-bound journal for Gate 6C-3 IBKR observations.

Each accepted observation is committed locally before it reaches the existing
Gate 6A bridge.  The journal contains market-data-type proof only; it has no
order, account, position, or funds surface.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
from typing import Any, Final

from .ibkr_live_market_data_intake import (
    ASSET_ORDER,
    LIVE_MARKET_DATA_TYPE,
    IbkrObservationSink,
)


JOURNAL_SCHEMA_VERSION: Final = "CRT_GATE6C3_IBKR_OBSERVATION_JOURNAL_V0.1"
RECORD_SCHEMA_VERSION: Final = "CRT_GATE6C3_IBKR_OBSERVATION_RECORD_V0.1"
ZERO_HASH: Final = "0" * 64
ALLOWED_CHANNELS: Final = frozenset({"LAST", "BAR_5S_CLOSE"})
AUTHORITY: Final = {
    "action_output": "NONE",
    "machine_execution": "FORBIDDEN",
    "external_action_authority": "NONE",
    "capital_decision_authority": "USER_ONLY",
    "production": "NOT_APPROVED",
}


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _positive_price(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("journal observed price must be positive")
    return float(value)


def _positive_timestamp_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("journal observed_at_ms must be a positive integer")
    return value


def _live_market_data_types(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("journal market data type proof must be an object")
    if list(value) != list(ASSET_ORDER):
        raise ValueError("journal market data type proof asset order mismatch")
    if any(value[asset] != LIVE_MARKET_DATA_TYPE for asset in ASSET_ORDER):
        raise ValueError("journal observation is not fully live")
    return {asset: LIVE_MARKET_DATA_TYPE for asset in ASSET_ORDER}


def _record_payload(
    *,
    plan_sha: str,
    asset: str,
    sequence: int,
    previous_hash: str,
    channel: str,
    price: float,
    observed_at_ms: int,
    market_data_types: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "plan_sha": plan_sha,
        "asset": asset,
        "sequence": sequence,
        "previous_hash": previous_hash,
        "channel": channel,
        "price": price,
        "observed_at_ms": observed_at_ms,
        "market_data_types": copy.deepcopy(market_data_types),
        **AUTHORITY,
    }


class IbkrObservationJournal:
    """SQLite-backed append-only observation journal with a hash chain."""

    def __init__(self, path: str | Path, *, plan_sha: str, asset: str) -> None:
        if not isinstance(plan_sha, str) or len(plan_sha) != 64:
            raise ValueError("journal plan_sha must be a SHA-256 hex string")
        try:
            int(plan_sha, 16)
        except ValueError as exc:
            raise ValueError("journal plan_sha must be a SHA-256 hex string") from exc
        if asset not in ASSET_ORDER:
            raise ValueError(f"journal asset unsupported:{asset}")
        self.path = Path(path)
        self.plan_sha = plan_sha
        self.asset = asset
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._initialize_schema()
            self.validate()
        except Exception:
            self._connection.close()
            raise

    def __enter__(self) -> "IbkrObservationJournal":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version TEXT NOT NULL,
                plan_sha TEXT NOT NULL,
                asset TEXT NOT NULL,
                action_output TEXT NOT NULL,
                machine_execution TEXT NOT NULL,
                external_action_authority TEXT NOT NULL,
                capital_decision_authority TEXT NOT NULL,
                production TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                sequence INTEGER PRIMARY KEY,
                previous_hash TEXT NOT NULL,
                record_hash TEXT NOT NULL UNIQUE,
                channel TEXT NOT NULL,
                price REAL NOT NULL,
                observed_at_ms INTEGER NOT NULL,
                market_data_types_json TEXT NOT NULL
            )
            """
        )
        row = self._connection.execute(
            "SELECT schema_version, plan_sha, asset, action_output, "
            "machine_execution, external_action_authority, "
            "capital_decision_authority, production "
            "FROM journal_metadata WHERE singleton = 1"
        ).fetchone()
        expected = (
            JOURNAL_SCHEMA_VERSION,
            self.plan_sha,
            self.asset,
            AUTHORITY["action_output"],
            AUTHORITY["machine_execution"],
            AUTHORITY["external_action_authority"],
            AUTHORITY["capital_decision_authority"],
            AUTHORITY["production"],
        )
        if row is None:
            self._connection.execute(
                "INSERT INTO journal_metadata VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
                expected,
            )
        elif tuple(row) != expected:
            raise ValueError("IBKR observation journal metadata mismatch")

    def _rows(self) -> list[tuple[Any, ...]]:
        return list(
            self._connection.execute(
                "SELECT sequence, previous_hash, record_hash, channel, price, "
                "observed_at_ms, market_data_types_json "
                "FROM observations ORDER BY sequence"
            ).fetchall()
        )

    def _record_from_row(self, row: tuple[Any, ...]) -> dict[str, Any]:
        (
            sequence,
            previous_hash,
            record_hash,
            channel,
            price,
            observed_at_ms,
            market_data_types_json,
        ) = row
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
            raise ValueError("IBKR observation journal sequence invalid")
        if not isinstance(previous_hash, str) or len(previous_hash) != 64:
            raise ValueError("IBKR observation journal previous hash invalid")
        if not isinstance(record_hash, str) or len(record_hash) != 64:
            raise ValueError("IBKR observation journal record hash invalid")
        if channel not in ALLOWED_CHANNELS:
            raise ValueError("IBKR observation journal channel invalid")
        try:
            market_data_types = json.loads(market_data_types_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("IBKR observation journal LIVE proof invalid") from exc
        payload = _record_payload(
            plan_sha=self.plan_sha,
            asset=self.asset,
            sequence=sequence,
            previous_hash=previous_hash,
            channel=channel,
            price=_positive_price(price),
            observed_at_ms=_positive_timestamp_ms(observed_at_ms),
            market_data_types=_live_market_data_types(market_data_types),
        )
        payload["record_hash"] = record_hash
        return payload

    def validate(self) -> None:
        with self._lock:
            previous_hash = ZERO_HASH
            expected_sequence = 1
            for row in self._rows():
                record = self._record_from_row(row)
                if record["sequence"] != expected_sequence:
                    raise ValueError("IBKR observation journal sequence gap")
                if record["previous_hash"] != previous_hash:
                    raise ValueError("IBKR observation journal hash chain mismatch")
                unsigned = copy.deepcopy(record)
                record_hash = unsigned.pop("record_hash")
                if record_hash != _canonical_hash(unsigned):
                    raise ValueError("IBKR observation journal record hash mismatch")
                previous_hash = record_hash
                expected_sequence += 1

    def head(self) -> tuple[int, str]:
        with self._lock:
            row = self._connection.execute(
                "SELECT sequence, record_hash FROM observations "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return 0, ZERO_HASH
            return int(row[0]), str(row[1])

    def hash_at(self, sequence: int) -> str:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("journal checkpoint sequence invalid")
        if sequence == 0:
            return ZERO_HASH
        with self._lock:
            row = self._connection.execute(
                "SELECT record_hash FROM observations WHERE sequence = ?",
                (sequence,),
            ).fetchone()
            if row is None:
                raise ValueError("journal checkpoint sequence unavailable")
            return str(row[0])

    def append(
        self,
        *,
        asset: str,
        channel: str,
        price: float,
        observed_at_ms: int,
        market_data_types: object,
    ) -> dict[str, Any]:
        if asset != self.asset:
            raise ValueError("journal observation asset mismatch")
        if channel not in ALLOWED_CHANNELS:
            raise ValueError("journal observation channel unsupported")
        locked_price = _positive_price(price)
        locked_timestamp = _positive_timestamp_ms(observed_at_ms)
        locked_market_data_types = _live_market_data_types(market_data_types)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                sequence, previous_hash = self.head()
                sequence += 1
                payload = _record_payload(
                    plan_sha=self.plan_sha,
                    asset=self.asset,
                    sequence=sequence,
                    previous_hash=previous_hash,
                    channel=channel,
                    price=locked_price,
                    observed_at_ms=locked_timestamp,
                    market_data_types=locked_market_data_types,
                )
                record_hash = _canonical_hash(payload)
                self._connection.execute(
                    "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sequence,
                        previous_hash,
                        record_hash,
                        channel,
                        locked_price,
                        locked_timestamp,
                        json.dumps(
                            locked_market_data_types,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        payload["record_hash"] = record_hash
        return payload

    def records_after(self, sequence: int) -> list[dict[str, Any]]:
        self.validate()
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("journal replay sequence invalid")
        with self._lock:
            rows = self._connection.execute(
                "SELECT sequence, previous_hash, record_hash, channel, price, "
                "observed_at_ms, market_data_types_json FROM observations "
                "WHERE sequence > ? ORDER BY sequence",
                (sequence,),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]


class JournaledIbkrObservationSink:
    """Commit plan-asset observations before forwarding them to Gate 6A."""

    def __init__(
        self,
        journal: IbkrObservationJournal,
        downstream: IbkrObservationSink,
    ) -> None:
        self.journal = journal
        self.downstream = downstream
        self.appended_count = 0

    def _forward(
        self,
        *,
        channel: str,
        asset: str,
        price: float,
        observed_at_ms: int,
        market_data_types: object | None,
    ) -> None:
        if asset == self.journal.asset:
            proof = _live_market_data_types(market_data_types)
            self.journal.append(
                asset=asset,
                channel=channel,
                price=price,
                observed_at_ms=observed_at_ms,
                market_data_types=proof,
            )
            self.appended_count += 1
        if channel == "LAST":
            self.downstream.on_ibkr_last(
                asset,
                price,
                observed_at_ms,
                market_data_types=market_data_types,
            )
        else:
            self.downstream.on_ibkr_5s_close(
                asset,
                price,
                observed_at_ms,
                market_data_types=market_data_types,
            )

    def on_ibkr_last(
        self,
        asset: str,
        price: float,
        observed_at_ms: int,
        *,
        market_data_types: dict[str, int | None] | None = None,
    ) -> None:
        self._forward(
            channel="LAST",
            asset=asset,
            price=price,
            observed_at_ms=observed_at_ms,
            market_data_types=market_data_types,
        )

    def on_ibkr_5s_close(
        self,
        asset: str,
        close: float,
        observed_at_ms: int,
        *,
        market_data_types: dict[str, int | None] | None = None,
    ) -> None:
        self._forward(
            channel="BAR_5S_CLOSE",
            asset=asset,
            price=close,
            observed_at_ms=observed_at_ms,
            market_data_types=market_data_types,
        )


def replay_observations(
    journal: IbkrObservationJournal,
    downstream: IbkrObservationSink,
    *,
    after_sequence: int,
) -> int:
    records = journal.records_after(after_sequence)
    for record in records:
        if record["channel"] == "LAST":
            downstream.on_ibkr_last(
                record["asset"],
                record["price"],
                record["observed_at_ms"],
                market_data_types=record["market_data_types"],
            )
        else:
            downstream.on_ibkr_5s_close(
                record["asset"],
                record["price"],
                record["observed_at_ms"],
                market_data_types=record["market_data_types"],
            )
    return len(records)
