from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from .evidence_pack import build_evidence_pack
from .liquidation_aggregator import SnapshotCorruption, load_verified_snapshot
from .source_gate_runner import (
    FetchResult,
    default_liquidation_snapshot_path,
    default_registry_path,
    probe_liquidation_stream,
    run_source_gate,
)
from .source_registry import SourceRegistry, SourceSpec


def default_observation_db_path() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime" / "observations.sqlite3"


def default_evidence_pack_path() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime" / "evidence" / "latest.json"


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run_daily_evidence(
    registry: SourceRegistry,
    *,
    observation_db: str | Path,
    reflexivity_input: dict[str, Any] | None = None,
    fetch_overrides: dict[str, FetchResult] | None = None,
    liquidation_aggregate_payload: dict[str, Any] | None = None,
    probe_fetcher: Callable[[SourceSpec], FetchResult] | None = None,
    now_ms: int | None = None,
    generated_at_ms: int | None = None,
) -> dict[str, Any]:
    source_gate = run_source_gate(
        registry,
        fetch_overrides=fetch_overrides,
        liquidation_aggregate_payload=liquidation_aggregate_payload,
        probe_fetcher=probe_fetcher,
        now_ms=now_ms,
    )
    return build_evidence_pack(
        source_gate,
        observation_db=observation_db,
        generated_at_ms=generated_at_ms,
        reflexivity_input=reflexivity_input,
    )


def _load_liquidation_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return load_verified_snapshot(path)
    except SnapshotCorruption:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the first lean CRT Evidence Pack from the existing Source Gate.")
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument("--liquidation-snapshot", type=Path, default=default_liquidation_snapshot_path())
    parser.add_argument("--observation-db", type=Path, default=default_observation_db_path())
    parser.add_argument("--output", type=Path, default=default_evidence_pack_path())
    args = parser.parse_args(argv)

    registry = SourceRegistry.load(args.registry)
    liquidation_payload = _load_liquidation_snapshot(args.liquidation_snapshot)
    pack = run_daily_evidence(
        registry,
        observation_db=args.observation_db,
        liquidation_aggregate_payload=liquidation_payload,
        probe_fetcher=probe_liquidation_stream,
    )
    write_json_atomic(args.output, pack)
    print(json.dumps(pack, ensure_ascii=False, indent=2))

    return 0 if pack.get("pack_state") in {"READY_FOR_ANALYST", "PARTIAL_FOR_ANALYST", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
