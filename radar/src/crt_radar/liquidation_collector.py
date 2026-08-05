from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Callable

from .liquidation_aggregator import (
    EXTERNAL_ACTION_AUTHORITY,
    LiquidationStore,
    build_snapshot,
    write_snapshot,
)
from .source_registry import SourceRegistry


USER_AGENT = "CRT-Radar/0.4-RC1 read-only liquidation collector"


class PersistentLiquidationCollector:
    external_action_authority = EXTERNAL_ACTION_AUTHORITY

    def __init__(
        self,
        registry: SourceRegistry,
        store: LiquidationStore,
        *,
        snapshot_path: str | Path,
        snapshot_interval_s: float = 60.0,
        minimum_coverage_ratio: float = 0.95,
        snapshot_callback: Callable[[dict[str, Any], int], None] | None = None,
    ):
        self.registry = registry
        self.store = store
        self.snapshot_path = Path(snapshot_path)
        self.snapshot_interval_s = snapshot_interval_s
        self.minimum_coverage_ratio = minimum_coverage_ratio
        self.snapshot_callback = snapshot_callback
        self.spec = registry.by_input_family("LIQUIDATION_CONNECTIVITY_PROBE")
        if self.spec.raw.get("endpoint_category") != "MARKET":
            raise ValueError("forceOrder collector requires Binance MARKET route")

    def _emit_snapshot(self, now_ms: int | None = None) -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        snapshot = build_snapshot(
            self.store,
            as_of_ms=now_ms,
            minimum_coverage_ratio=self.minimum_coverage_ratio,
        )
        write_snapshot(snapshot, self.snapshot_path)
        elapsed_ms = max(0, int((time.perf_counter_ns() - started_ns) / 1_000_000))
        if self.snapshot_callback is not None:
            self.snapshot_callback(snapshot, elapsed_ms)
        return snapshot

    def run_forever(
        self,
        *,
        max_runtime_s: float | None = None,
        open_timeout_s: float = 10.0,
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
    ) -> None:
        from websockets.sync.client import connect

        self.store.recover_orphan_sessions()
        started = time.monotonic()
        reconnect_index = 0
        next_snapshot = time.monotonic() + self.snapshot_interval_s
        while max_runtime_s is None or time.monotonic() - started < max_runtime_s:
            if time.monotonic() >= next_snapshot:
                self._emit_snapshot()
                next_snapshot = time.monotonic() + self.snapshot_interval_s
            session_id: str | None = None
            try:
                with connect(
                    self.spec.endpoint,
                    open_timeout=open_timeout_s,
                    close_timeout=2.0,
                    user_agent_header=USER_AGENT,
                ) as websocket:
                    opened_ms = int(time.time() * 1000)
                    session_id = self.store.begin_session(
                        opened_ms=opened_ms,
                        reconnect_index=reconnect_index,
                    )
                    while max_runtime_s is None or time.monotonic() - started < max_runtime_s:
                        timeout = max(0.1, min(5.0, next_snapshot - time.monotonic()))
                        try:
                            message = websocket.recv(timeout=timeout)
                            if message is None:
                                raise ConnectionError("liquidation stream closed")
                            received_ms = int(time.time() * 1000)
                            try:
                                decoded = json.loads(message)
                            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
                                if isinstance(message, str):
                                    raw = message.encode("utf-8", errors="replace")
                                elif isinstance(message, bytes):
                                    raw = message
                                else:
                                    raw = repr(message).encode("utf-8", errors="replace")
                                self.store.record_anomaly(
                                    "INVALID_WEBSOCKET_MESSAGE",
                                    observed_ms=received_ms,
                                    details={
                                        "error": f"{type(exc).__name__}: {exc}",
                                        "message_sha256": hashlib.sha256(raw).hexdigest(),
                                        "message_bytes": len(raw),
                                    },
                                )
                                continue
                            self.store.ingest_force_order(decoded, received_ms=received_ms)
                        except TimeoutError:
                            pass
                        self.store.touch_session(
                            session_id,
                            heartbeat_ms=int(time.time() * 1000),
                        )
                        if time.monotonic() >= next_snapshot:
                            self._emit_snapshot()
                            next_snapshot = time.monotonic() + self.snapshot_interval_s
                if session_id is not None:
                    self.store.end_session(session_id, close_reason="NORMAL_RECONNECT")
            except KeyboardInterrupt:
                if session_id is not None:
                    self.store.end_session(session_id, close_reason="INTERRUPTED")
                self._emit_snapshot()
                raise
            except Exception as exc:
                if session_id is not None:
                    try:
                        self.store.end_session(
                            session_id,
                            close_reason=f"ERROR:{type(exc).__name__}",
                        )
                    except Exception:
                        pass
                reconnect_index += 1
                exponent = min(max(0, reconnect_index - 1), 6)
                backoff = min(max_backoff_s, base_backoff_s * (2 ** exponent))
                delay = backoff + random.random() * base_backoff_s
                if max_runtime_s is not None:
                    remaining = max(0.0, max_runtime_s - (time.monotonic() - started))
                    delay = min(delay, remaining)
                delay = min(delay, max(0.0, next_snapshot - time.monotonic()))
                if delay > 0:
                    time.sleep(delay)

        self.store.close_open_sessions(
            closed_ms=int(time.time() * 1000),
            close_reason="MAX_RUNTIME_REACHED",
        )
        self._emit_snapshot()


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"


def default_runtime_root() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CRT read-only persistent liquidation collector")
    parser.add_argument("command", choices=("collect", "snapshot"))
    parser.add_argument("--registry", default=str(default_registry_path()))
    parser.add_argument("--runtime-root", default=str(default_runtime_root()))
    parser.add_argument("--snapshot-path", default=None)
    parser.add_argument("--max-runtime-s", type=float, default=None)
    args = parser.parse_args(argv)

    registry = SourceRegistry.load(args.registry)
    root = Path(args.runtime_root)
    snapshot_path = Path(args.snapshot_path) if args.snapshot_path else root / "snapshots" / "latest.json"
    store = LiquidationStore(root)
    if args.command == "snapshot":
        snapshot = build_snapshot(store)
        write_snapshot(snapshot, snapshot_path)
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0

    collector = PersistentLiquidationCollector(
        registry,
        store,
        snapshot_path=snapshot_path,
    )
    collector.run_forever(max_runtime_s=args.max_runtime_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
