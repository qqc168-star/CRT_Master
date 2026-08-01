from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .liquidation_aggregator import LiquidationStore
from .liquidation_collector import PersistentLiquidationCollector
from .live_shadow_evidence import (
    archive_snapshot,
    build_evidence_summary,
    write_evidence_summary,
)
from .run_ledger import RunLedger
from .source_registry import SourceRegistry


HARNESS_VERSION = "CRT-RADAR-LIVE-SHADOW-HARNESS-V0.7-WIP"
EXTERNAL_ACTION_AUTHORITY = "NONE"


@dataclass(frozen=True)
class LiveShadowPolicy:
    duration_s: int = 86_400
    snapshot_interval_s: int = 60
    minimum_coverage_ratio: float = 0.95
    required_controlled_restarts: int = 1
    controlled_restart_after_s: int = 43_200
    controlled_restart_gap_s: float = 2.0
    minimum_snapshot_delivery_ratio: float = 0.95
    maximum_snapshot_gap_s: int = 180
    maximum_snapshot_clock_skew_s: int = 300
    elapsed_duration_tolerance_s: float = 2.0

    @classmethod
    def load(cls, path: str | Path) -> "LiveShadowPolicy":
        row = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            duration_s=int(row["duration_s"]),
            snapshot_interval_s=int(row["snapshot_interval_s"]),
            minimum_coverage_ratio=float(row["minimum_coverage_ratio"]),
            required_controlled_restarts=int(row["required_controlled_restarts"]),
            controlled_restart_after_s=int(row["controlled_restart_after_s"]),
            controlled_restart_gap_s=float(row["controlled_restart_gap_s"]),
            minimum_snapshot_delivery_ratio=float(row.get("minimum_snapshot_delivery_ratio", 0.95)),
            maximum_snapshot_gap_s=int(row.get("maximum_snapshot_gap_s", int(row["snapshot_interval_s"]) * 3)),
            maximum_snapshot_clock_skew_s=int(row.get("maximum_snapshot_clock_skew_s", 300)),
            elapsed_duration_tolerance_s=float(row.get("elapsed_duration_tolerance_s", 2.0)),
        )


class ShadowSnapshotRecorder:
    def __init__(
        self,
        *,
        runtime_root: str | Path,
        ledger: RunLedger,
        registry_hash: str,
        process_run_id: str,
    ):
        self.runtime_root = Path(runtime_root)
        self.ledger = ledger
        self.registry_hash = registry_hash
        self.process_run_id = process_run_id
        self.archive_root = self.runtime_root / "snapshots" / "archive"

    def __call__(self, snapshot: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
        archive = archive_snapshot(snapshot, self.archive_root)
        relative_archive = archive.relative_to(self.runtime_root).as_posix()
        return self.ledger.append_snapshot(
            snapshot,
            registry_hash=self.registry_hash,
            archive_path=relative_archive,
            elapsed_ms=elapsed_ms,
            process_run_id=self.process_run_id,
            observed_ms=int(snapshot["as_of_ms"]),
        )


def default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_registry_path() -> Path:
    return default_root() / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"


def default_policy_path() -> Path:
    return default_root() / "CONFIG" / "LIVE_SHADOW_POLICY_V1.json"


def preflight_report(
    *,
    registry_path: str | Path,
    runtime_root: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    registry = SourceRegistry.load(registry_path)
    runtime = Path(runtime_root)
    store = LiquidationStore(runtime)
    ledger = RunLedger(ledger_path)
    probe = registry.by_input_family("LIQUIDATION_CONNECTIVITY_PROBE")
    aggregate = registry.by_input_family("LIQUIDATION_AGGREGATES")
    checks = {
        "registry_loaded": True,
        "registry_hash": registry.hash,
        "market_route": probe.raw.get("endpoint_category") == "MARKET",
        "public_route_forbidden": "/public/" not in probe.endpoint,
        "aggregate_schema": aggregate.raw.get("snapshot_schema") == "CRT_LIQ_AGGREGATE_SNAPSHOT_V1",
        "store_integrity": store.integrity_ok(),
        "ledger": ledger.validate().as_dict(),
        "runtime_writable": os.access(runtime, os.W_OK),
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
    }
    pass_flags = [
        checks["registry_loaded"],
        checks["market_route"],
        checks["public_route_forbidden"],
        checks["aggregate_schema"],
        checks["store_integrity"],
        checks["ledger"]["valid"],
        checks["runtime_writable"],
        checks["external_action_authority"] == "NONE",
    ]
    return {
        "harness_version": HARNESS_VERSION,
        "decision": "PREFLIGHT_PASS" if all(pass_flags) else "PREFLIGHT_BLOCKED",
        "checks": checks,
        "external_action_performed": False,
    }


def run_live_shadow(
    *,
    registry_path: str | Path,
    runtime_root: str | Path,
    ledger_path: str | Path,
    policy: LiveShadowPolicy,
    duration_s: float | None = None,
    controlled_restart_after_s: float | None = None,
    controlled_restart_gap_s: float | None = None,
) -> dict[str, Any]:
    registry = SourceRegistry.load(registry_path)
    runtime = Path(runtime_root)
    runtime.mkdir(parents=True, exist_ok=True)
    ledger = RunLedger(ledger_path)
    process_run_id = str(uuid.uuid4())
    target_duration = float(policy.duration_s if duration_s is None else duration_s)
    restart_after = float(
        policy.controlled_restart_after_s
        if controlled_restart_after_s is None
        else controlled_restart_after_s
    )
    restart_gap = float(
        policy.controlled_restart_gap_s
        if controlled_restart_gap_s is None
        else controlled_restart_gap_s
    )
    if target_duration <= 0:
        raise ValueError("duration_s must be positive")
    if restart_after <= 0:
        raise ValueError("controlled_restart_after_s must be positive")
    if restart_gap < 0:
        raise ValueError("controlled_restart_gap_s cannot be negative")

    preflight = preflight_report(
        registry_path=registry_path,
        runtime_root=runtime,
        ledger_path=ledger_path,
    )
    if preflight["decision"] != "PREFLIGHT_PASS":
        raise RuntimeError("Live Shadow preflight failed")

    ledger.append_process_event(
        "PROCESS_START",
        process_run_id=process_run_id,
        details={
            "harness_version": HARNESS_VERSION,
            "target_duration_s": target_duration,
            "snapshot_interval_s": policy.snapshot_interval_s,
            "registry_hash": registry.hash,
        },
    )
    started = time.monotonic()
    recorder = ShadowSnapshotRecorder(
        runtime_root=runtime,
        ledger=ledger,
        registry_hash=registry.hash,
        process_run_id=process_run_id,
    )

    segments: list[float]
    if restart_after < target_duration:
        segments = [restart_after, target_duration - restart_after]
    else:
        segments = [target_duration]

    outcome = "COMPLETED"
    error_text: str | None = None
    try:
        for index, segment_duration in enumerate(segments):
            store = LiquidationStore(runtime)
            collector = PersistentLiquidationCollector(
                registry,
                store,
                snapshot_path=runtime / "snapshots" / "latest.json",
                snapshot_interval_s=policy.snapshot_interval_s,
                minimum_coverage_ratio=policy.minimum_coverage_ratio,
                snapshot_callback=recorder,
            )
            ledger.append_process_event(
                "SEGMENT_START",
                process_run_id=process_run_id,
                details={"segment_index": index, "segment_duration_s": segment_duration},
            )
            collector.run_forever(max_runtime_s=segment_duration)
            ledger.append_process_event(
                "SEGMENT_STOP",
                process_run_id=process_run_id,
                details={"segment_index": index},
            )
            if index < len(segments) - 1:
                ledger.append_process_event(
                    "CONTROLLED_RESTART",
                    process_run_id=process_run_id,
                    details={"after_segment_index": index, "planned_gap_s": restart_gap},
                )
                if restart_gap:
                    time.sleep(restart_gap)
    except KeyboardInterrupt:
        outcome = "INTERRUPTED"
        error_text = "KeyboardInterrupt"
    except Exception as exc:
        outcome = "ERROR"
        error_text = f"{type(exc).__name__}: {exc}"
    finally:
        elapsed_s = time.monotonic() - started
        ledger.append_process_event(
            "PROCESS_STOP",
            process_run_id=process_run_id,
            details={
                "outcome": outcome,
                "error": error_text,
                "elapsed_s": elapsed_s,
            },
        )

    summary = build_evidence_summary(
        runtime,
        ledger_path,
        minimum_duration_s=policy.duration_s,
        minimum_coverage_ratio=policy.minimum_coverage_ratio,
        required_controlled_restarts=policy.required_controlled_restarts,
        process_run_id=process_run_id,
        expected_registry_hash=registry.hash,
        snapshot_interval_s=policy.snapshot_interval_s,
        minimum_snapshot_delivery_ratio=policy.minimum_snapshot_delivery_ratio,
        maximum_snapshot_gap_s=policy.maximum_snapshot_gap_s,
        maximum_snapshot_clock_skew_s=policy.maximum_snapshot_clock_skew_s,
        elapsed_duration_tolerance_s=policy.elapsed_duration_tolerance_s,
    )
    write_evidence_summary(summary, runtime / "evidence" / "live_shadow_summary.json")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CRT read-only Liquidation Live Shadow harness")
    parser.add_argument("command", choices=("preflight", "collect", "verify"))
    parser.add_argument("--registry", default=str(default_registry_path()))
    parser.add_argument("--policy", default=str(default_policy_path()))
    parser.add_argument("--runtime-root", default=str(default_root() / "runtime"))
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--duration-s", type=float, default=None)
    parser.add_argument("--controlled-restart-after-s", type=float, default=None)
    parser.add_argument("--controlled-restart-gap-s", type=float, default=None)
    args = parser.parse_args(argv)

    runtime_root = Path(args.runtime_root)
    ledger_path = Path(args.ledger) if args.ledger else runtime_root / "ledger" / "run_ledger.jsonl"
    policy = LiveShadowPolicy.load(args.policy)

    if args.command == "preflight":
        result = preflight_report(
            registry_path=args.registry,
            runtime_root=runtime_root,
            ledger_path=ledger_path,
        )
    elif args.command == "verify":
        registry = SourceRegistry.load(args.registry)
        result = build_evidence_summary(
            runtime_root,
            ledger_path,
            minimum_duration_s=policy.duration_s,
            minimum_coverage_ratio=policy.minimum_coverage_ratio,
            required_controlled_restarts=policy.required_controlled_restarts,
            expected_registry_hash=registry.hash,
            snapshot_interval_s=policy.snapshot_interval_s,
            minimum_snapshot_delivery_ratio=policy.minimum_snapshot_delivery_ratio,
            maximum_snapshot_gap_s=policy.maximum_snapshot_gap_s,
            maximum_snapshot_clock_skew_s=policy.maximum_snapshot_clock_skew_s,
            elapsed_duration_tolerance_s=policy.elapsed_duration_tolerance_s,
        )
        write_evidence_summary(result, runtime_root / "evidence" / "live_shadow_summary.json")
    else:
        result = run_live_shadow(
            registry_path=args.registry,
            runtime_root=runtime_root,
            ledger_path=ledger_path,
            policy=policy,
            duration_s=args.duration_s,
            controlled_restart_after_s=args.controlled_restart_after_s,
            controlled_restart_gap_s=args.controlled_restart_gap_s,
        )

    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if result.get("decision") in {"PREFLIGHT_PASS", "LIVE_SHADOW_PASS"}:
        return 0
    if result.get("decision") == "LIVE_SHADOW_NOT_YET_PASSED":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
