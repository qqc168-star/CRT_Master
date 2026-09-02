from __future__ import annotations

import argparse
import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .daily_evidence_runner import write_json_atomic
from .mstr_asst_full_day_market_intake import (
    build_mstr_asst_full_day_market_intake,
)
from .mstr_asst_market_health import (
    evaluate_mstr_asst_market_health,
    validate_mstr_asst_market_health,
)
from .mstr_asst_options_daily_snapshot import (
    build_mstr_asst_options_daily_snapshot,
)


SCHEMA_VERSION = "CRT_MSTR_ASST_MARKET_HEALTH_RUNTIME_INPUT_V0.1"
EXPECTED_SOURCES = {
    "equity_daily": "CRT-CONN-MSTR-ASST-IBKR-EQUITY-DAILY-001",
    "btc_exact_close": "CRT-CONN-BTC-BINANCE-EXACT-CLOSE-001",
    "options_daily": "CRT-CONN-MSTR-ASST-IBKR-OPTIONS-LIMITED-001",
    "issuer_btc_per_diluted_share": (
        "CRT-CONN-MSTR-ASST-OFFICIAL-ISSUER-RATIO-001"
    ),
    "commander_lines": "CRT-CONN-MSTR-ASST-COMMANDER-LINES-001",
}
AUTHORITY = {
    "action_output": "NONE",
    "external_action_authority": "NONE",
    "external_action_performed": False,
}


def canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def seal_runtime_source(
    *,
    source_key: str,
    data: Any,
    observed_at_ms: int,
    validation_state: str = "VALID",
) -> dict[str, Any]:
    """Create a replayable local source proof without granting any action authority."""
    if source_key not in EXPECTED_SOURCES:
        raise ValueError(f"unknown Market Health source key: {source_key}")
    return {
        "source_id": EXPECTED_SOURCES[source_key],
        "validation_state": validation_state,
        "observed_at_ms": observed_at_ms,
        "data_hash": canonical_hash(data),
        "data": deepcopy(data),
        **AUTHORITY,
    }


def _assert_authority(payload: dict[str, Any], label: str) -> None:
    for key, expected in AUTHORITY.items():
        if payload.get(key) != expected:
            raise ValueError(f"{label} {key} must remain {expected!r}")


def _validated_source(
    source_key: str,
    raw: Any,
    *,
    generated_at_ms: int,
) -> Any:
    if not isinstance(raw, dict):
        raise ValueError(f"{source_key} source proof must be an object")
    if raw.get("source_id") != EXPECTED_SOURCES[source_key]:
        raise ValueError(f"{source_key} source_id mismatch")
    if raw.get("validation_state") != "VALID":
        raise ValueError(f"{source_key} source proof must be VALID")
    _assert_authority(raw, f"{source_key} source proof")
    observed_at_ms = raw.get("observed_at_ms")
    if not isinstance(observed_at_ms, int):
        raise ValueError(f"{source_key} observed_at_ms must be an integer")
    if observed_at_ms > generated_at_ms:
        raise ValueError(f"{source_key} observed_at_ms cannot be in the future")
    if "data" not in raw:
        raise ValueError(f"{source_key} source proof data is missing")
    if raw.get("data_hash") != canonical_hash(raw["data"]):
        raise ValueError(f"{source_key} source proof data_hash mismatch")
    return deepcopy(raw["data"])


def build_market_health_runtime_outputs(bundle: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(bundle, dict):
        raise ValueError("Market Health runtime input must be an object")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Market Health runtime input schema_version mismatch")
    _assert_authority(bundle, "Market Health runtime input")
    generated_at_ms = bundle.get("generated_at_ms")
    if not isinstance(generated_at_ms, int):
        raise ValueError("generated_at_ms must be an integer")
    source_proofs = bundle.get("source_proofs")
    if not isinstance(source_proofs, dict):
        raise ValueError("source_proofs must be an object")
    if set(source_proofs) != set(EXPECTED_SOURCES):
        raise ValueError("source_proofs must contain exactly the five contracted sources")

    source_data = {
        key: _validated_source(
            key,
            source_proofs[key],
            generated_at_ms=generated_at_ms,
        )
        for key in EXPECTED_SOURCES
    }
    full_day = build_mstr_asst_full_day_market_intake(
        equity_bars=source_data["equity_daily"],
        btc_close_marks=source_data["btc_exact_close"],
        generated_at_ms=generated_at_ms,
    )
    if full_day.get("state") != "VALID":
        raise ValueError("full-day Market Intake is BLOCKED")
    options = build_mstr_asst_options_daily_snapshot(
        asset_inputs=source_data["options_daily"],
        generated_at_ms=generated_at_ms,
    )
    market_health = evaluate_mstr_asst_market_health(
        full_day_market_intake=full_day,
        options_daily_snapshot=options,
        commander_lines=source_data["commander_lines"],
        issuer_btc_per_diluted_share=source_data[
            "issuer_btc_per_diluted_share"
        ],
        generated_at_ms=generated_at_ms,
    )
    validate_mstr_asst_market_health(market_health)

    manifest: dict[str, Any] = {
        "schema_version": "CRT_MSTR_ASST_MARKET_HEALTH_RUNTIME_MANIFEST_V0.1",
        "state": "VALID",
        "generated_at_ms": generated_at_ms,
        "source_proof_hashes": {
            key: source_proofs[key]["data_hash"] for key in EXPECTED_SOURCES
        },
        "full_day_market_intake_hash": full_day["snapshot_hash"],
        "options_daily_snapshot_hash": options["snapshot_hash"],
        "market_health_hash": market_health["market_health_hash"],
        **AUTHORITY,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    return {
        "full_day_market_intake": full_day,
        "options_daily_snapshot": options,
        "market_health": market_health,
        "manifest": manifest,
    }


def build_runtime_input_from_source_proofs(
    source_proofs: dict[str, Any],
    *,
    generated_at_ms: int,
) -> dict[str, Any]:
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": generated_at_ms,
        "source_proofs": deepcopy(source_proofs),
        **AUTHORITY,
    }
    # Reuse the complete evaluator as the contract validation boundary.
    build_market_health_runtime_outputs(bundle)
    return bundle


def write_market_health_runtime_outputs(
    outputs: dict[str, dict[str, Any]],
    *,
    full_day_output: str | Path,
    options_output: str | Path,
    market_health_output: str | Path,
    manifest_output: str | Path,
) -> None:
    """Atomically replace each artifact only after the complete build validates."""
    validate_mstr_asst_market_health(outputs["market_health"])
    write_json_atomic(full_day_output, outputs["full_day_market_intake"])
    write_json_atomic(options_output, outputs["options_daily_snapshot"])
    write_json_atomic(market_health_output, outputs["market_health"])
    write_json_atomic(manifest_output, outputs["manifest"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the read-only MSTR/ASST Market Health runtime artifacts."
    )
    parser.add_argument("--input")
    parser.add_argument("--equity-proof")
    parser.add_argument("--btc-proof")
    parser.add_argument("--options-proof")
    parser.add_argument("--issuer-proof")
    parser.add_argument("--commander-proof")
    parser.add_argument("--runtime-input-output")
    parser.add_argument("--full-day-output", required=True)
    parser.add_argument("--options-output", required=True)
    parser.add_argument("--market-health-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.input:
        bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        proof_paths = {
            "equity_daily": args.equity_proof,
            "btc_exact_close": args.btc_proof,
            "options_daily": args.options_proof,
            "issuer_btc_per_diluted_share": args.issuer_proof,
            "commander_lines": args.commander_proof,
        }
        missing = [key for key, path in proof_paths.items() if not path]
        if missing:
            raise ValueError(
                "--input or all five source proof paths are required: "
                + ", ".join(missing)
            )
        source_proofs = {
            key: json.loads(Path(path).read_text(encoding="utf-8"))
            for key, path in proof_paths.items()
        }
        bundle = build_runtime_input_from_source_proofs(
            source_proofs,
            generated_at_ms=int(time.time() * 1000),
        )
    outputs = build_market_health_runtime_outputs(bundle)
    if args.runtime_input_output:
        write_json_atomic(args.runtime_input_output, bundle)
    write_market_health_runtime_outputs(
        outputs,
        full_day_output=args.full_day_output,
        options_output=args.options_output,
        market_health_output=args.market_health_output,
        manifest_output=args.manifest_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
