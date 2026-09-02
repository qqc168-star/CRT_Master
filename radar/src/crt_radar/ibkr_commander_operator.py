"""Fail-closed Gate 6C-3 operator for verified plan observation runs.

This module only orchestrates the existing Commander adapter, Gate 6A state
machine, IBKR market-data intake, reanalysis wake, notice, and GPT handoff.
It has no order, position, account, or funds surface.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Final

from .commander_plan_adapter import (
    ALLOWED_ASSETS,
    CommanderPlanBlocked,
    SIMULATION_ONLY,
    seal_commander_plan,
    validate_commander_plan,
)
from .daily_evidence_runner import write_json_atomic
from .gpt_handoff import run_gpt_handoff_gate
from .ibkr_commander_observation import (
    IbkrCommanderObservationBridge,
    build_commander_reanalysis_wake,
)
from .ibkr_live_market_data_intake import (
    ASSET_ORDER,
    LIVE_MARKET_DATA_TYPE,
    IbkrFeed,
    IbkrIntakeConfig,
    IbkrObservationSink,
    NativeIbkrFeed,
)
from .ibkr_observation_journal import (
    ZERO_HASH,
    IbkrObservationJournal,
    JournaledIbkrObservationSink,
    replay_observations,
)
from .plain_language_notice import build_plain_language_notice
from .reanalysis_wake import fuse_reanalysis_wake


SCHEMA_VERSION: Final = "CRT_GATE6C3_OPERATOR_V0.3"
DEDUPE_SCHEMA_VERSION: Final = "CRT_GATE6C3_RUNTIME_CHECKPOINT_V0.3"
PREVIOUS_DEDUPE_SCHEMA_VERSION: Final = "CRT_GATE6C3_RUNTIME_CHECKPOINT_V0.2"
LEGACY_DEDUPE_SCHEMA_VERSION: Final = "CRT_GATE6C3_EVENT_DEDUPE_V0.1"
RESTART_CONTINUITY: Final = (
    "DURABLE_OBSERVATION_JOURNAL_GATE6A_STATE_AND_EVENT_DEDUPE"
)
CHECKPOINT_COMMIT_SCOPE: Final = "JOURNALED_OBSERVATION_PREFIX"
AUTHORITY: Final = {
    "action_output": "NONE",
    "machine_execution": "FORBIDDEN",
    "external_action_authority": "NONE",
    "capital_decision_authority": "USER_ONLY",
    "production": "NOT_APPROVED",
}

FeedFactory = Callable[[IbkrObservationSink], IbkrFeed]


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _simulation_level(reference_price: float, offset_bps: int) -> float:
    if not math.isfinite(reference_price) or reference_price <= 0:
        raise ValueError("simulation reference price must be positive")
    reference = Decimal(str(reference_price))
    multiplier = Decimal(1) + Decimal(offset_bps) / Decimal(10_000)
    level = (reference * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cent = Decimal("0.01")
    if offset_bps > 0 and level <= reference:
        level = (reference + cent).quantize(cent, rounding=ROUND_HALF_UP)
    if offset_bps < 0 and level >= reference:
        level = (reference - cent).quantize(cent, rounding=ROUND_HALF_UP)
    if level <= 0:
        raise ValueError("simulation level must remain positive")
    return float(level)


def build_sealed_simulation_plan(
    *,
    asset: str,
    reference_price: float,
    reference_at: datetime,
    current_main_sha: str,
    valid_for_minutes: int = 60,
    reference_source: str = "IBKR_LIVE_LAST",
) -> dict[str, Any]:
    """Build an explicitly simulated, non-TEST_ONLY observation plan."""

    if asset not in ALLOWED_ASSETS:
        raise ValueError(f"unsupported simulation asset:{asset}")
    if reference_source not in {
        "IBKR_LIVE_LAST",
        "IBKR_L1_CLOSE_CLOSED_MARKET",
    }:
        raise ValueError("unsupported simulation reference source")
    if reference_at.tzinfo is None:
        raise ValueError("simulation reference_at must include a timezone")
    reference_at = reference_at.astimezone(timezone.utc)
    if (
        isinstance(valid_for_minutes, bool)
        or not isinstance(valid_for_minutes, int)
        or not 5 <= valid_for_minutes <= 1_440
    ):
        raise ValueError("simulation validity must be 5..1440 minutes")
    offsets = {
        "ATTACK": 5,
        "FIRST_DEFENSE": -50,
        "INVALIDATION": -200,
        "HARVEST": 200,
    }
    directions = {
        "ATTACK": "UP",
        "FIRST_DEFENSE": "DOWN",
        "INVALIDATION": "DOWN",
        "HARVEST": "UP",
    }
    timestamp_id = reference_at.strftime("%Y%m%dT%H%M%SZ")
    plan = seal_commander_plan(
        {
            "plan_id": f"CRT-GATE6C3-SIM-{asset}-{timestamp_id}",
            "plan_version": "0.1-simulation",
            "plan_mode": "OBSERVATION_ONLY",
            "generated_at": _iso_z(reference_at),
            "valid_until": _iso_z(
                reference_at + timedelta(minutes=valid_for_minutes)
            ),
            "asset": asset,
            "source_main_sha": current_main_sha,
            "price_classification": SIMULATION_ONLY,
            "simulation_basis": {
                "purpose": "GATE_6C3_LIVE_OBSERVATION_E2E",
                "source": reference_source,
                "reference_price": float(reference_price),
                "reference_received_at": _iso_z(reference_at),
                "line_generation_rule_bps": offsets,
                "commander_judgment": "SIMULATED_NOT_FORMAL",
                "capital_decision_authority": "USER_ONLY",
            },
            "lines": [
                {
                    "line_id": f"sim-{line_type.lower().replace('_', '-')}",
                    "line_type": line_type,
                    "price": _simulation_level(reference_price, offset_bps),
                    "direction": directions[line_type],
                    "price_classification": SIMULATION_ONLY,
                }
                for line_type, offset_bps in offsets.items()
            ],
            "governance": {
                "action_output": "NONE",
                "machine_execution": "FORBIDDEN",
                "external_action_authority": "NONE",
                "capital_decision_authority": "USER_ONLY",
            },
        }
    )
    valid, blockers = validate_commander_plan(
        plan,
        current_main_sha=current_main_sha,
        now=reference_at,
    )
    if not valid:
        raise ValueError("generated simulation plan blocked:" + ",".join(blockers))
    return plan


def build_simulation_plan_from_capture(
    capture: object,
    *,
    asset: str,
    current_main_sha: str,
    valid_for_minutes: int = 60,
    allow_closed_market_close: bool = False,
) -> dict[str, Any]:
    if asset not in ALLOWED_ASSETS:
        raise ValueError(f"unsupported simulation asset:{asset}")
    locked_capture = _assert_capture(capture)
    captured_at_ms = locked_capture.get("captured_at_ms")
    if (
        isinstance(captured_at_ms, bool)
        or not isinstance(captured_at_ms, int)
        or captured_at_ms <= 0
    ):
        raise ValueError("IBKR capture timestamp unavailable")
    asset_capture = locked_capture["assets"][asset]
    reference_price = asset_capture["l1"].get("last")
    reference_source = "IBKR_LIVE_LAST"
    if reference_price is None and allow_closed_market_close:
        if asset_capture["bars_5s"]:
            raise ValueError(
                f"closed-market close fallback forbidden with 5s activity:{asset}"
            )
        reference_price = asset_capture["l1"].get("close")
        reference_source = "IBKR_L1_CLOSE_CLOSED_MARKET"
    if (
        isinstance(reference_price, bool)
        or not isinstance(reference_price, (int, float))
        or not math.isfinite(float(reference_price))
        or float(reference_price) <= 0
    ):
        raise ValueError(f"IBKR LAST unavailable for simulation:{asset}")
    return build_sealed_simulation_plan(
        asset=asset,
        reference_price=float(reference_price),
        reference_at=datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc),
        current_main_sha=current_main_sha,
        valid_for_minutes=valid_for_minutes,
        reference_source=reference_source,
    )


def _assert_capture(capture: object) -> dict[str, Any]:
    if not isinstance(capture, dict):
        raise ValueError("IBKR capture must be an object")
    assets = capture.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("IBKR capture assets unavailable")
    if list(assets) != list(ASSET_ORDER):
        raise ValueError("IBKR capture asset order mismatch")
    for asset in ASSET_ORDER:
        payload = assets.get(asset)
        if not isinstance(payload, dict):
            raise ValueError(f"IBKR capture asset unavailable:{asset}")
        if payload.get("market_data_type") != LIVE_MARKET_DATA_TYPE:
            raise ValueError(f"IBKR market data is not live:{asset}")
        if not isinstance(payload.get("l1"), dict):
            raise ValueError(f"IBKR L1 capture unavailable:{asset}")
        if not isinstance(payload.get("bars_5s"), list):
            raise ValueError(f"IBKR 5-second bar capture unavailable:{asset}")
    return capture


def _event_fingerprint(event: dict[str, Any]) -> str:
    fields = {
        "plan_sha": event.get("plan_sha"),
        "asset": event.get("asset"),
        "line_id": event.get("line_id"),
        "line_type": event.get("line_type"),
        "level_price": event.get("level_price"),
        "observed_price": event.get("observed_price"),
        "event_type": event.get("event_type"),
        "observation_channel": event.get("observation_channel"),
    }
    return _canonical_hash(fields)


def _dedupe_payload(plan_sha: str) -> dict[str, Any]:
    return {
        "schema_version": DEDUPE_SCHEMA_VERSION,
        "plan_sha": plan_sha,
        "lines": {},
        "gate6a_state": None,
        "restart_continuity": RESTART_CONTINUITY,
        "checkpoint_commit_scope": CHECKPOINT_COMMIT_SCOPE,
        "journal_applied_through": 0,
        "journal_applied_hash": ZERO_HASH,
        **AUTHORITY,
    }


def _seal_dedupe_state(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed.pop("state_hash", None)
    sealed["state_hash"] = _canonical_hash(sealed)
    return sealed


def _load_dedupe_state(path: Path, plan_sha: str) -> dict[str, Any]:
    if not path.exists():
        return _dedupe_payload(plan_sha)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Gate 6C-3 dedupe state must be an object")
    state_hash = payload.get("state_hash")
    unsigned = copy.deepcopy(payload)
    unsigned.pop("state_hash", None)
    if state_hash != _canonical_hash(unsigned):
        raise ValueError("Gate 6C-3 dedupe state hash mismatch")
    schema_version = payload.get("schema_version")
    if schema_version not in {
        DEDUPE_SCHEMA_VERSION,
        PREVIOUS_DEDUPE_SCHEMA_VERSION,
        LEGACY_DEDUPE_SCHEMA_VERSION,
    }:
        raise ValueError("Gate 6C-3 checkpoint schema mismatch")
    expected_fields = {
        "schema_version",
        "plan_sha",
        "lines",
        "restart_continuity",
        "state_hash",
        *AUTHORITY,
    }
    if schema_version == DEDUPE_SCHEMA_VERSION:
        expected_fields.update(
            {
                "gate6a_state",
                "checkpoint_commit_scope",
                "journal_applied_through",
                "journal_applied_hash",
            }
        )
    elif schema_version == PREVIOUS_DEDUPE_SCHEMA_VERSION:
        expected_fields.update({"gate6a_state", "checkpoint_commit_scope"})
    if set(payload) != expected_fields:
        raise ValueError("Gate 6C-3 checkpoint fields mismatch")
    expected_continuity = {
        DEDUPE_SCHEMA_VERSION: RESTART_CONTINUITY,
        PREVIOUS_DEDUPE_SCHEMA_VERSION: (
            "COMPLETED_CYCLE_GATE6A_STATE_AND_EVENT_DEDUPE"
        ),
        LEGACY_DEDUPE_SCHEMA_VERSION: "EVENT_DEDUPE_ONLY",
    }[schema_version]
    if payload.get("restart_continuity") != expected_continuity:
        raise ValueError("Gate 6C-3 checkpoint continuity mismatch")
    if (
        schema_version in {
            DEDUPE_SCHEMA_VERSION,
            PREVIOUS_DEDUPE_SCHEMA_VERSION,
        }
        and payload.get("checkpoint_commit_scope")
        != (
            CHECKPOINT_COMMIT_SCOPE
            if schema_version == DEDUPE_SCHEMA_VERSION
            else "LAST_COMPLETED_OPERATOR_CYCLE"
        )
    ):
        raise ValueError("Gate 6C-3 checkpoint commit scope mismatch")
    for key, expected in AUTHORITY.items():
        if payload.get(key) != expected:
            raise ValueError(f"Gate 6C-3 dedupe authority mismatch:{key}")
    if not isinstance(payload.get("lines"), dict):
        raise ValueError("Gate 6C-3 dedupe line state unavailable")
    if payload.get("plan_sha") != plan_sha:
        return _dedupe_payload(plan_sha)
    if schema_version in {
        LEGACY_DEDUPE_SCHEMA_VERSION,
        PREVIOUS_DEDUPE_SCHEMA_VERSION,
    }:
        migrated = _dedupe_payload(plan_sha)
        migrated["lines"] = copy.deepcopy(payload["lines"])
        if schema_version == PREVIOUS_DEDUPE_SCHEMA_VERSION:
            migrated["gate6a_state"] = copy.deepcopy(payload["gate6a_state"])
        return migrated
    gate6a_state = payload.get("gate6a_state")
    if gate6a_state is not None and not isinstance(gate6a_state, dict):
        raise ValueError("Gate 6C-3 Gate 6A state unavailable")
    journal_applied_through = payload.get("journal_applied_through")
    if (
        isinstance(journal_applied_through, bool)
        or not isinstance(journal_applied_through, int)
        or journal_applied_through < 0
    ):
        raise ValueError("Gate 6C-3 journal cursor invalid")
    journal_applied_hash = payload.get("journal_applied_hash")
    if not isinstance(journal_applied_hash, str) or len(journal_applied_hash) != 64:
        raise ValueError("Gate 6C-3 journal cursor hash invalid")
    try:
        int(journal_applied_hash, 16)
    except ValueError as exc:
        raise ValueError("Gate 6C-3 journal cursor hash invalid") from exc
    return payload


def _validate_checkpoint_journal_alignment(
    state: dict[str, Any],
    journal: IbkrObservationJournal,
) -> None:
    journal.validate()
    applied_through = state["journal_applied_through"]
    head_sequence, _ = journal.head()
    if applied_through > head_sequence:
        raise ValueError("Gate 6C-3 journal is behind checkpoint")
    if journal.hash_at(applied_through) != state["journal_applied_hash"]:
        raise ValueError("Gate 6C-3 journal checkpoint hash mismatch")


def _dedupe_events(
    events: list[dict[str, Any]],
    *,
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    state = copy.deepcopy(state)
    line_state = state["lines"]
    new_events: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    commit_states: list[dict[str, Any]] = []

    for event in events:
        fingerprint = _event_fingerprint(event)
        line_key = f"{event['asset']}:{event['line_id']}"
        previous = line_state.get(line_key)
        if isinstance(previous, dict) and previous.get("fingerprint") == fingerprint:
            duplicate = copy.deepcopy(event)
            duplicate["operator_disposition"] = "DUPLICATE_SKIPPED"
            duplicates.append(duplicate)
            continue
        accepted = copy.deepcopy(event)
        accepted["operator_disposition"] = "NEW"
        accepted["operator_event_fingerprint"] = fingerprint
        new_events.append(accepted)
        line_state[line_key] = {
            "fingerprint": fingerprint,
            "event_type": event["event_type"],
            "event_timestamp": event["timestamp"],
        }
        commit_states.append(_seal_dedupe_state(state))

    return new_events, duplicates, commit_states


def _plan_drift_not_evaluated() -> dict[str, Any]:
    return {
        "state": "NOT_EVALUATED",
        "reason": "PLAN_DRIFT_NOT_EVALUATED_BY_GATE_6C3_OPERATOR",
        "reanalysis_required": False,
        "plans": [],
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def _handoff_for_event(
    event: dict[str, Any],
    *,
    plan: dict[str, Any],
    ledger_path: Path,
) -> dict[str, Any]:
    plan_drift = _plan_drift_not_evaluated()
    wake = fuse_reanalysis_wake(
        build_commander_reanalysis_wake(event),
        plan_drift=plan_drift,
    )
    if wake is None:
        raise ValueError("Commander event failed to produce a reanalysis wake")
    blockers: list[str] = []
    if plan.get("price_classification") == SIMULATION_ONLY:
        blockers.append("SIMULATED_COMMANDER_PLAN_NOT_FORMAL_CAPITAL_AUTHORITY")
    pack: dict[str, Any] = {
        "pack_state": "READY_FOR_ANALYST",
        "authority": {
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "production": "NOT_APPROVED",
        },
        "reanalysis_wake": wake,
        "plan_drift": plan_drift,
        "data_health": {"critical_blockers": blockers},
        "commander_plan": {
            "plan_id": plan["plan_id"],
            "plan_sha": plan["plan_sha"],
            "price_classification": plan.get("price_classification"),
        },
    }
    pack["evidence_pack_hash"] = _canonical_hash(pack)
    notice = build_plain_language_notice(pack)
    handoff = run_gpt_handoff_gate(
        pack,
        notice,
        ledger_path=ledger_path,
    )
    return {
        "commander_event_id": wake["commander_event_id"],
        "wake": wake,
        "notice": notice,
        "handoff": handoff,
    }


def _capture_summary(capture: dict[str, Any]) -> dict[str, Any]:
    return {
        asset: {
            "market_data_type": capture["assets"][asset]["market_data_type"],
            "last": capture["assets"][asset]["l1"].get("last"),
            "bar_5s_count": len(capture["assets"][asset]["bars_5s"]),
        }
        for asset in ASSET_ORDER
    }


def run_gate6c3_operator(
    plan: dict[str, Any],
    *,
    current_main_sha: str,
    config: IbkrIntakeConfig,
    ledger_path: str | Path,
    dedupe_state_path: str | Path,
    observation_journal_path: str | Path | None = None,
    report_path: str | Path | None = None,
    now: datetime | None = None,
    feed_factory: FeedFactory = NativeIbkrFeed,
) -> dict[str, Any]:
    """Run one bounded, observation-only Gate 6C-3 operator cycle."""

    valid, blockers = validate_commander_plan(
        plan,
        current_main_sha=current_main_sha,
        now=now,
    )
    if not valid:
        raise CommanderPlanBlocked(blockers)
    dedupe_path = Path(dedupe_state_path)
    runtime_state = _load_dedupe_state(dedupe_path, plan["plan_sha"])
    gate6a_state_restored = runtime_state.get("gate6a_state") is not None
    journal_path = (
        Path(observation_journal_path)
        if observation_journal_path is not None
        else dedupe_path.with_name(dedupe_path.stem + ".observations.sqlite3")
    )
    with IbkrObservationJournal(
        journal_path,
        plan_sha=plan["plan_sha"],
        asset=plan["asset"],
    ) as journal:
        _validate_checkpoint_journal_alignment(runtime_state, journal)
        bridge = IbkrCommanderObservationBridge.arm(
            plan,
            current_main_sha=current_main_sha,
            now=now,
            gate6a_state=runtime_state.get("gate6a_state"),
        )
        replayed_observation_count = replay_observations(
            journal,
            bridge,
            after_sequence=runtime_state["journal_applied_through"],
        )
        journaled_sink = JournaledIbkrObservationSink(journal, bridge)
        capture = _assert_capture(feed_factory(journaled_sink).collect(config))
        journal_head_sequence, journal_head_hash = journal.head()
        raw_events = list(bridge.events)
        new_events, duplicates, dedupe_commit_states = _dedupe_events(
            raw_events,
            state=runtime_state,
        )
        handoffs: list[dict[str, Any]] = []
        for event, commit_state in zip(
            new_events,
            dedupe_commit_states,
            strict=True,
        ):
            handoffs.append(
                _handoff_for_event(event, plan=plan, ledger_path=Path(ledger_path))
            )
            write_json_atomic(dedupe_path, commit_state)

        completed_state = copy.deepcopy(
            dedupe_commit_states[-1] if dedupe_commit_states else runtime_state
        )
        completed_state.pop("state_hash", None)
        completed_state["gate6a_state"] = bridge.gate6a_state()
        completed_state["restart_continuity"] = RESTART_CONTINUITY
        completed_state["checkpoint_commit_scope"] = CHECKPOINT_COMMIT_SCOPE
        completed_state["journal_applied_through"] = journal_head_sequence
        completed_state["journal_applied_hash"] = journal_head_hash
        write_json_atomic(dedupe_path, _seal_dedupe_state(completed_state))

        if new_events:
            state = "OBSERVATION_EVENTS_HANDOFF_READY"
        elif duplicates:
            state = "DUPLICATE_EVENTS_SKIPPED"
        elif (
            bridge.last_observation_count > 0
            or bridge.bar_close_observation_count > 0
        ):
            state = "MONITORING_NO_EVENT"
        else:
            state = "WAITING_FOR_MARKET_ACTIVITY"

        result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "state": state,
            "plan": {
                "plan_id": plan["plan_id"],
                "plan_sha": plan["plan_sha"],
                "asset": plan["asset"],
                "valid_until": plan["valid_until"],
                "source_main_sha": plan["source_main_sha"],
                "price_classification": plan.get("price_classification"),
            },
            "capture": _capture_summary(capture),
            "gate_summary": bridge.gate_summary(),
            "observation_journal": {
                "state": "DURABLE_REPLAY_READY",
                "replayed_observation_count": replayed_observation_count,
                "appended_observation_count": journaled_sink.appended_count,
                "applied_through": journal_head_sequence,
                "applied_hash": journal_head_hash,
                **AUTHORITY,
            },
            "raw_events": raw_events,
            "new_events": new_events,
            "duplicate_events": duplicates,
            "handoffs": handoffs,
            "restart_continuity": RESTART_CONTINUITY,
            "checkpoint_commit_scope": CHECKPOINT_COMMIT_SCOPE,
            "delivery_semantics": (
                "DURABLE_AT_LEAST_ONCE_OBSERVATION_REPLAY_WITH_EVENT_DEDUPE"
            ),
            "gate6a_state_restored": gate6a_state_restored,
            "checkpoint_schema_version": DEDUPE_SCHEMA_VERSION,
            "unresolved_restart_boundary": None,
            "current_main_verification": (
                "CALLER_SUPPLIED_READ_ONLY_PRECHECK_REQUIRED"
            ),
            "plan_source_main_match": plan["source_main_sha"] == current_main_sha,
            **AUTHORITY,
        }
        result["report_hash"] = _canonical_hash(result)
        if report_path is not None:
            write_json_atomic(report_path, result)
        return result


def _load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Commander Plan must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one bounded Gate 6C-3 IBKR observation cycle."
    )
    plan_source = parser.add_mutually_exclusive_group(required=True)
    plan_source.add_argument("--plan")
    plan_source.add_argument("--simulation-plan-output")
    parser.add_argument("--simulate-asset", choices=sorted(ALLOWED_ASSETS))
    parser.add_argument("--simulation-valid-minutes", type=int, default=60)
    parser.add_argument("--allow-closed-market-close", action="store_true")
    parser.add_argument("--current-main-sha", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--dedupe-state", required=True)
    parser.add_argument("--observation-journal")
    parser.add_argument("--report", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=168)
    parser.add_argument("--duration-seconds", type=float, default=12.0)
    parser.add_argument("--baseline-duration-seconds", type=float, default=8.0)
    parser.add_argument("--connect-timeout-seconds", type=float, default=8.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = IbkrIntakeConfig(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        duration_seconds=args.duration_seconds,
        connect_timeout_seconds=args.connect_timeout_seconds,
    )
    if args.plan is not None:
        plan = _load_json(args.plan)
    else:
        if args.simulate_asset is None:
            raise ValueError("--simulate-asset is required for simulation plan mode")
        baseline_capture = NativeIbkrFeed().collect(
            IbkrIntakeConfig(
                host=args.host,
                port=args.port,
                client_id=args.client_id,
                duration_seconds=args.baseline_duration_seconds,
                connect_timeout_seconds=args.connect_timeout_seconds,
            )
        )
        plan = build_simulation_plan_from_capture(
            baseline_capture,
            asset=args.simulate_asset,
            current_main_sha=args.current_main_sha,
            valid_for_minutes=args.simulation_valid_minutes,
            allow_closed_market_close=args.allow_closed_market_close,
        )
        write_json_atomic(args.simulation_plan_output, plan)
        config = IbkrIntakeConfig(
            host=args.host,
            port=args.port,
            client_id=args.client_id + 1,
            duration_seconds=args.duration_seconds,
            connect_timeout_seconds=args.connect_timeout_seconds,
        )
    result = run_gate6c3_operator(
        plan,
        current_main_sha=args.current_main_sha,
        config=config,
        ledger_path=args.ledger,
        dedupe_state_path=args.dedupe_state,
        observation_journal_path=args.observation_journal,
        report_path=args.report,
    )
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
