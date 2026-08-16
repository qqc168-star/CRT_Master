from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from .evidence_pack import build_evidence_pack
from .intraday_reanalysis_runner import run_intraday_reanalysis
from .liquidation_aggregator import SnapshotCorruption, load_verified_snapshot
from .maturity_tracker import record_maturity_attempt
from .observation_store import ObservationStore, extract_observations
from .plain_language_notice import build_plain_language_notice
from .private_profile import default_private_profile_path, load_private_profile
from .runtime_freshness import apply_runtime_checks, assess_file_freshness
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
    runtime_checks: list[dict[str, Any]] | None = None,
    now_ms: int | None = None,
    generated_at_ms: int | None = None,
    private_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_gate = run_source_gate(
        registry,
        fetch_overrides=fetch_overrides,
        liquidation_aggregate_payload=liquidation_aggregate_payload,
        probe_fetcher=probe_fetcher,
        now_ms=now_ms,
    )
    source_gate = apply_runtime_checks(source_gate, runtime_checks)
    recorded_at_ms = int(generated_at_ms) if generated_at_ms is not None else None
    current_observations = extract_observations(source_gate, recorded_at_ms=recorded_at_ms)
    btc_rows = [
        row
        for row in current_observations
        if row.input_family == "BTC_SPOT_PRICE" and row.metric == "btc_spot_price_usd"
    ]
    if btc_rows:
        current_btc = max(btc_rows, key=lambda row: row.as_of_ms)
        with ObservationStore(observation_db) as store:
            reanalysis_wake = run_intraday_reanalysis(store, current_btc)
    else:
        reanalysis_wake = {
            "state": "NO_WAKE",
            "reason": "BTC_SPOT_OBSERVATION_UNAVAILABLE",
            "metric": "btc_spot_price_usd",
            "input_family": "BTC_SPOT_PRICE",
            "current_value": None,
            "previous_value": None,
            "percent_change": None,
            "historical_percentile": None,
            "baseline_count": 0,
            "analyst_reanalysis_requested": False,
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
    return build_evidence_pack(
        source_gate,
        observation_db=observation_db,
        generated_at_ms=generated_at_ms,
        reflexivity_input=reflexivity_input,
        reanalysis_wake=reanalysis_wake,
        private_context=private_context,
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
    parser.add_argument("--private-profile", type=Path, default=default_private_profile_path())
    parser.add_argument("--wake-output", type=Path, default=None)
    parser.add_argument("--notice-output", type=Path, default=None)
    parser.add_argument("--maturity-ledger", type=Path, default=None)
    parser.add_argument("--maturity-status", type=Path, default=None)
    parser.add_argument(
        "--phone-l4-freshness-path",
        type=Path,
        default=None,
        help="Optional Mobile L4 handoff file whose local mtime is checked before the Evidence Pack is built.",
    )
    parser.add_argument(
        "--phone-l4-max-age-seconds",
        type=int,
        default=300,
        help="Transport-only freshness limit for --phone-l4-freshness-path. Source-level freshness remains authoritative.",
    )
    args = parser.parse_args(argv)

    registry = SourceRegistry.load(args.registry)
    liquidation_payload = _load_liquidation_snapshot(args.liquidation_snapshot)
    runtime_checks: list[dict[str, Any]] = []
    if args.phone_l4_freshness_path is not None:
        runtime_checks.append(
            assess_file_freshness(
                args.phone_l4_freshness_path,
                max_age_seconds=args.phone_l4_max_age_seconds,
                reason_prefix="PHONE_L4",
            )
        )

    private_context = load_private_profile(args.private_profile)
    pack = run_daily_evidence(
        registry,
        observation_db=args.observation_db,
        liquidation_aggregate_payload=liquidation_payload,
        probe_fetcher=probe_liquidation_stream,
        runtime_checks=runtime_checks,
        private_context=private_context,
    )
    write_json_atomic(args.output, pack)
    if args.wake_output is not None:
        write_json_atomic(args.wake_output, pack["reanalysis_wake"])
    if args.notice_output is not None:
        write_json_atomic(args.notice_output, build_plain_language_notice(pack))
    if (args.maturity_ledger is None) != (args.maturity_status is None):
        raise ValueError("--maturity-ledger and --maturity-status must be supplied together")
    if args.maturity_ledger is not None and args.maturity_status is not None:
        record_maturity_attempt(args.maturity_ledger, args.maturity_status, pack)
    print(json.dumps(pack, ensure_ascii=False, indent=2))

    return 0 if pack.get("pack_state") in {"READY_FOR_ANALYST", "PARTIAL_FOR_ANALYST", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
