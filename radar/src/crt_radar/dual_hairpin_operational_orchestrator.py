"""Read-only dual-hairpin cycle orchestrator.

This module replays an append-only evidence stream.  It deliberately has no
broker, network, or order API surface.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Iterable

EVENTS = (
    "INTEGRATED_FREEZE",
    "D0_ONE_CARD",
    "D0_EXECUTION_RECORD",
    "D1_GATE",
    "D1_EXECUTION_RECORD",
    "FINAL_SETTLEMENT",
)
SINGLETONS = frozenset(EVENTS[i] for i in (0, 2, 4, 5))
AUTHORITY = {
    "action_output": "NONE",
    "external_action_authority": "NONE",
    "external_action_performed": False,
    "machine_may_execute_trade": False,
    "capital_decision_authority": "USER_ONLY",
}


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode()
    return sha256(raw).hexdigest()


def _event_key(event: dict[str, Any]) -> tuple[str, str]:
    kind = str(event.get("event_type", ""))
    cycle = str(event.get("cycle_id", ""))
    if kind not in EVENTS or not cycle:
        raise ValueError("invalid event identity")
    return cycle, kind


def replay_events(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate order, singleton rules, and return a deterministic projection."""
    rows = list(events)
    seen: set[tuple[str, str]] = set()
    by_cycle: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("event must be an object")
        key = _event_key(row)
        cycle, kind = key
        if key in seen and kind in SINGLETONS:
            raise ValueError(f"singleton event repeated: {kind}")
        seen.add(key)
        by_cycle.setdefault(cycle, []).append(row)

    cycles: dict[str, Any] = {}
    for cycle, cycle_rows in by_cycle.items():
        ordered = sorted(cycle_rows, key=lambda x: (str(x.get("event_at", "")), EVENTS.index(x["event_type"])))
        kinds = [x["event_type"] for x in ordered]
        if any(kinds[i] > kinds[i + 1] for i in range(len(kinds) - 1)):
            # Event sequence is semantic, not merely timestamp order.
            positions = [EVENTS.index(k) for k in kinds]
            if positions != sorted(positions):
                raise ValueError(f"event sequence violation for cycle {cycle}")
        previous = "0" * 64
        audit = []
        for row in ordered:
            body = {k: v for k, v in row.items() if k not in {"event_sha256", "chain_sha256"}}
            event_hash = canonical_sha256(body)
            supplied = row.get("event_sha256")
            if supplied is not None and supplied != event_hash:
                raise ValueError("event hash mismatch")
            chain_hash = canonical_sha256({"previous": previous, "event": event_hash})
            if row.get("chain_sha256") is not None and row["chain_sha256"] != chain_hash:
                raise ValueError("chain hash mismatch")
            audit.append({"event_type": row["event_type"], "event_sha256": event_hash, "chain_sha256": chain_hash})
            previous = chain_hash
        cycles[cycle] = {"event_types": kinds, "complete": kinds == list(EVENTS), "audit": audit, "chain_sha256": previous}
    return {"schema_version": "CRT_DUAL_HAIRPIN_OPERATIONAL_ORCHESTRATOR_V0.2.1", "cycles": cycles, "authority": AUTHORITY}


def build_event(*, cycle_id: str, event_type: str, event_at: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if event_type not in EVENTS:
        raise ValueError("unknown event type")
    body = {"cycle_id": cycle_id, "event_type": event_type, "event_at": event_at, "payload": payload or {}}
    body["event_sha256"] = canonical_sha256(body)
    return body
