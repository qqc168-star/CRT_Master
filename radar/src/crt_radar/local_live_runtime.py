"""Local read-only supervisor. A bounded child reuses the approved IBKR intake.

Transport captures are observations, never validated premarket snapshots or
Commander inputs. No prior capture is restored as live on process restart.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time

from .daily_evidence_runner import write_json_atomic
from .ibkr_live_market_data_intake import IbkrIntakeConfig, NativeIbkrFeed, _port_open
from .ibkr_observation_journal import AUTHORITY


@dataclass(frozen=True)
class RuntimeConfig:
    intake: IbkrIntakeConfig
    backoff_initial_seconds: float
    backoff_max_seconds: float
    heartbeat_timeout_seconds: float
    journal_retention_days: int

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        intake = IbkrIntakeConfig(**{k: data.pop(k) for k in (
            "host", "port", "client_id", "duration_seconds", "connect_timeout_seconds")}).validate()
        config = cls(intake=intake, **data)
        for value in (config.backoff_initial_seconds, config.backoff_max_seconds,
                      config.heartbeat_timeout_seconds, config.journal_retention_days):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("runtime bounds must be positive and finite")
        if config.backoff_initial_seconds < 5 or config.backoff_max_seconds < config.backoff_initial_seconds:
            raise ValueError("backoff must be bounded and at least five seconds")
        if intake.duration_seconds < 60:
            raise ValueError("capture sessions must be at least 60 seconds to bound subscription pacing")
        return config


class RuntimeJournal:
    def __init__(self, root, retention_days=14):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "lifecycle.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at_ms INTEGER NOT NULL, payload TEXT NOT NULL)")
        self.retention_days = retention_days
        self.last_prune = 0

    def record(self, state, **details):
        now = int(time.time() * 1000)
        record = {"state": state, "at_ms": now, "pid": os.getpid(),
                  "fail_closed": True, "evidence_usable": False,
                  "premarket_pipeline": "PENDING_MARKET_WINDOW", **details, **AUTHORITY}
        with self.db:
            cursor = self.db.execute("INSERT INTO events(at_ms,payload) VALUES (?,?)",
                                     (now, json.dumps(record, allow_nan=False)))
            record["journal_sequence"] = cursor.lastrowid
            if now - self.last_prune > 3600000:
                self.db.execute("DELETE FROM events WHERE at_ms < ?", (now - self.retention_days * 86400000,))
                self.last_prune = now
        # The database commit precedes checkpoint publication; DB remains authoritative.
        checkpoint = {k: v for k, v in record.items() if k != "capture"}
        checkpoint["valid_until_ms"] = now + 5000
        write_json_atomic(self.root / "checkpoint.json", checkpoint)
        return record

    def close(self):
        self.db.close()


def _collect_worker(config, messages):
    def watch_parent():
        parent = mp.parent_process()
        while parent is not None and parent.is_alive():
            time.sleep(1)
        # A killed supervisor must not leave a market-data socket behind.
        os._exit(1)
    threading.Thread(target=watch_parent, daemon=True).start()
    def emit(event, detail):
        messages.put((event, detail), timeout=2)
    try:
        NativeIbkrFeed(lifecycle_sink=emit).collect(config)
    except Exception as exc:
        emit("ERROR", {"reason": f"{type(exc).__name__}: {exc}"})
    finally:
        emit("FINISHED", {})


class CaptureWorker:
    def __init__(self, config):
        context = mp.get_context("spawn")
        self.messages = context.Queue(maxsize=32)
        self.process = context.Process(target=_collect_worker, args=(config, self.messages), daemon=True)
        self.process.start()

    def poll(self):
        try:
            return self.messages.get_nowait()
        except queue.Empty:
            return None

    def alive(self):
        return self.process.is_alive()

    def close(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=3)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=3)
        self.messages.close()


class Runtime:
    def __init__(self, config, journal, *, probe=_port_open, factory=CaptureWorker, clock=time.monotonic):
        self.config, self.journal = config, journal
        self.probe, self.factory, self.clock = probe, factory, clock
        self.worker = None
        self.next_attempt = 0.0
        self.delay = config.backoff_initial_seconds
        self.deadline = 0.0
        self.state = "STARTING"
        self.capture_signature = None
        self.last_heartbeat = 0.0
        self.record("STARTING")

    def record(self, state, **details):
        self.state = state
        self.journal.record(state, endpoint=f"{self.config.intake.host}:{self.config.intake.port}", **details)
        self.last_heartbeat = self.clock()

    def close_worker(self):
        if self.worker:
            self.worker.close()
            self.worker = None
        self.capture_signature = None

    def retry(self, state, reason):
        self.close_worker()
        self.next_attempt = self.clock() + self.delay
        self.record(state, reason=reason, retry_after_seconds=self.delay)
        self.delay = min(self.config.backoff_max_seconds, self.delay * 2)

    def tick(self, *, paused=False):
        now = self.clock()
        if paused:
            if self.state != "PAUSED":
                self.close_worker()  # closes the real socket, never TWS itself
                self.record("PAUSED", reason="LOCAL_CONTROLLED_DISCONNECT")
            return
        if self.state == "PAUSED":
            self.next_attempt = now + self.config.backoff_initial_seconds
            self.record("WAITING_FOR_TWS", reason="LOCAL_CONTROL_RELEASED")
        if self.worker:
            for _ in range(32):
                message = self.worker.poll()
                if message is None:
                    break
                event, detail = message
                if event == "CONNECTED":
                    self.deadline = now + self.config.heartbeat_timeout_seconds
                    self.record("CONNECTED", handshake=True)
                elif event == "CAPTURE":
                    self.deadline = now + self.config.heartbeat_timeout_seconds
                    assets = detail["assets"]
                    live = [name for name, item in assets.items()
                            if item.get("market_data_type") == 1 and item.get("last_received_at_ms")]
                    # Reception time is never represented as exchange trade freshness.
                    signature = [(name, item.get("market_data_type"), item.get("last_received_at_ms"))
                                 for name, item in assets.items()]
                    changed = signature != self.capture_signature
                    if changed or now - self.last_heartbeat >= 3:
                        self.record("RECEIVING" if live else "CONNECTED_NO_DATA",
                                    live_callback_assets=live, capture=detail if changed else None,
                                    exchange_trade_freshness="NOT_VALIDATED")
                    self.capture_signature = signature
                    # Reset only after a healthy session; handshake flapping retains backoff.
                    if now - self.started_at >= 60:
                        self.delay = self.config.backoff_initial_seconds
                elif event == "DISCONNECTED":
                    # Drain the worker's following ERROR/FINISHED message so the
                    # original API failure is not lost behind socket cleanup.
                    self.record("DISCONNECTED")
                    self.deadline = now + 2
                elif event in {"ERROR", "FINISHED"}:
                    self.retry("WAITING_FOR_TWS", detail.get("reason", event))
                    return
            if self.worker and (not self.worker.alive() or now >= self.deadline):
                self.retry("WAITING_FOR_TWS", "WORKER_EXIT_OR_TIMEOUT")
        elif now >= self.next_attempt:
            if not self.probe(self.config.intake.host, self.config.intake.port):
                self.retry("WAITING_FOR_TWS", "ENDPOINT_UNAVAILABLE")
            else:
                self.record("CONNECTING", port_detected=True)
                try:
                    self.worker = self.factory(self.config.intake)
                    self.started_at = now
                    self.deadline = now + self.config.intake.connect_timeout_seconds
                except Exception as exc:
                    self.retry("WAITING_FOR_TWS", f"WORKER_START_FAILED: {exc}")

    def close(self):
        self.close_worker()
        self.record("STOPPED")


@contextmanager
def single_instance(root):
    """OS lock is released on crash; a leftover file cannot block restart."""
    path = Path(root) / "runtime.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args()
    config = RuntimeConfig.load(args.config)
    root = Path(args.runtime_root)
    with single_instance(root):
        journal = RuntimeJournal(root, config.journal_retention_days)
        runtime = Runtime(config, journal)
        try:
            while not (root / "stop.request").exists():
                runtime.tick(paused=(root / "pause.request").exists())
                time.sleep(0.25)
        finally:
            runtime.close()
            journal.close()


if __name__ == "__main__":
    mp.freeze_support()
    main()
