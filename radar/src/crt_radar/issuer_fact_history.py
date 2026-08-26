from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

VALID_QUALITY_STATES = {"VALID_REPORTED", "VALID_DETERMINISTIC"}


def _source_hashes(item: dict[str, Any]) -> set[str]:
    refs = item.get("source_refs")
    if not isinstance(refs, list):
        return set()
    result = set()
    for ref in refs:
        if isinstance(ref, dict):
            value = ref.get("evidence_hash")
            if isinstance(value, str) and value:
                result.add(value)
    return result


def select_fact_history(
    overlay: dict[str, Any] | None,
    *,
    fact_type: str,
    issuer_id: str | None = None,
    security_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(overlay, dict):
        return {"state": "BLOCKED", "reason": "OVERLAY_MISSING", "items": []}

    section = overlay.get("asset_facts")
    if not isinstance(section, dict):
        return {"state": "BLOCKED", "reason": "ASSET_FACT_SECTION_MISSING", "items": []}

    coverage = section.get("coverage_state")
    if section.get("section_state") == "BLOCKED" or coverage == "BLOCKED":
        return {"state": "BLOCKED", "reason": "ASSET_FACT_SECTION_BLOCKED", "items": []}

    raw_items = section.get("items")
    if not isinstance(raw_items, list):
        return {"state": "BLOCKED", "reason": "ASSET_FACT_ITEMS_MISSING", "items": []}

    candidates = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        if raw.get("fact_type") != fact_type:
            continue
        if issuer_id is not None and raw.get("issuer_id") != issuer_id:
            continue
        if security_id is not None and raw.get("security_id") != security_id:
            continue
        if raw.get("quality_state") not in VALID_QUALITY_STATES:
            continue

        ts = raw.get("effective_at_ms")
        if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
            continue

        hashes = _source_hashes(raw)
        if not hashes:
            continue

        candidates.append(
            {
                "asset_fact_id": raw.get("asset_fact_id"),
                "effective_at_ms": ts,
                "value": deepcopy(raw.get("value")),
                "unit": raw.get("unit"),
                "source_refs": deepcopy(raw.get("source_refs")),
                "source_hashes": sorted(hashes),
            }
        )

    if not candidates:
        state = "BLOCKED" if coverage == "COMPLETE" else "PARTIAL"
        return {"state": state, "reason": "FACT_HISTORY_NOT_FOUND", "items": []}

    by_ts = {}
    for item in candidates:
        by_ts.setdefault(item["effective_at_ms"], []).append(item)

    normalized = []
    for ts, group in by_ts.items():
        distinct = {(repr(item["value"]), item["unit"]) for item in group}
        if len(distinct) > 1:
            return {
                "state": "BLOCKED",
                "reason": "CONFLICTING_FACTS_AT_SAME_EFFECTIVE_TIME",
                "conflict_effective_at_ms": ts,
                "items": sorted(
                    candidates,
                    key=lambda x: (x["effective_at_ms"], str(x["asset_fact_id"])),
                ),
            }

        normalized.append(
            sorted(group, key=lambda x: str(x["asset_fact_id"]))[-1]
        )

    normalized.sort(key=lambda x: (x["effective_at_ms"], str(x["asset_fact_id"])))

    return {
        "state": "AVAILABLE" if coverage == "COMPLETE" else "PARTIAL",
        "reason": (
            "FACT_HISTORY_READY"
            if coverage == "COMPLETE"
            else "FACT_HISTORY_COVERAGE_INCOMPLETE"
        ),
        "items": normalized,
        "coverage_state": coverage,
    }


def latest_fact(history: dict[str, Any]) -> dict[str, Any]:
    items = history.get("items")
    if not isinstance(items, list) or not items:
        return {
            "state": (
                "BLOCKED"
                if history.get("state") == "BLOCKED"
                else "PARTIAL"
            ),
            "reason": history.get("reason", "HISTORY_MISSING"),
            "value": None,
        }

    item = deepcopy(items[-1])
    return {
        "state": history.get("state", "PARTIAL"),
        "reason": history.get("reason"),
        "value": item["value"],
        "effective_at_ms": item["effective_at_ms"],
        "unit": item.get("unit"),
        "source_refs": item.get("source_refs", []),
        "source_hashes": item.get("source_hashes", []),
    }


def recent_numeric_changes(
    history: dict[str, Any],
    *,
    changes: int = 3,
) -> dict[str, Any]:
    if changes < 1:
        raise ValueError("changes must be >= 1")

    items = history.get("items")
    if not isinstance(items, list) or len(items) < 2:
        return {
            "state": "BLOCKED",
            "reason": "INSUFFICIENT_HISTORY_FOR_CHANGE_SERIES",
            "value": [],
        }

    for item in items:
        value = item.get("value")
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            return {
                "state": "BLOCKED",
                "reason": "NON_NUMERIC_HISTORY_VALUE",
                "value": [],
            }

    available_changes = len(items) - 1
    use = min(changes, available_changes)
    start = len(items) - use

    result = []
    for idx in range(start, len(items)):
        current = items[idx]
        previous = items[idx - 1]
        result.append(
            {
                "effective_at_ms": current["effective_at_ms"],
                "total": float(current["value"]),
                "delta": float(current["value"]) - float(previous["value"]),
                "unit": current.get("unit"),
                "source_refs": deepcopy(current.get("source_refs", [])),
            }
        )

    available = available_changes >= changes and history.get("state") == "AVAILABLE"

    return {
        "state": "AVAILABLE" if available else "PARTIAL",
        "reason": (
            "RECENT_CHANGES_READY"
            if available
            else "RECENT_CHANGES_PARTIAL"
        ),
        "value": result,
    }


def latest_previous_delta(history: dict[str, Any]) -> dict[str, Any]:
    items = history.get("items")

    if not isinstance(items, list) or not items:
        blocked = {"state": "BLOCKED", "reason": "NO_HISTORY", "value": None}
        return {"current": blocked, "previous": blocked, "delta": blocked}

    current = items[-1]
    current_state = history.get("state", "PARTIAL")

    current_out = {
        "state": current_state,
        "value": deepcopy(current.get("value")),
        "effective_at_ms": current.get("effective_at_ms"),
        "unit": current.get("unit"),
        "source_refs": deepcopy(current.get("source_refs", [])),
    }

    if len(items) < 2:
        return {
            "current": current_out,
            "previous": {
                "state": "PARTIAL",
                "reason": "PREVIOUS_HISTORY_NOT_AVAILABLE",
                "value": None,
            },
            "delta": {
                "state": "PARTIAL",
                "reason": "DELTA_HISTORY_NOT_AVAILABLE",
                "value": None,
            },
        }

    previous = items[-2]
    previous_out = {
        "state": current_state,
        "value": deepcopy(previous.get("value")),
        "effective_at_ms": previous.get("effective_at_ms"),
        "unit": previous.get("unit"),
        "source_refs": deepcopy(previous.get("source_refs", [])),
    }

    a = current.get("value")
    b = previous.get("value")

    if (
        isinstance(a, (int, float))
        and not isinstance(a, bool)
        and isinstance(b, (int, float))
        and not isinstance(b, bool)
        and math.isfinite(float(a))
        and math.isfinite(float(b))
    ):
        delta_out = {
            "state": current_state,
            "value": float(a) - float(b),
            "unit": current.get("unit"),
        }
    else:
        delta_out = {
            "state": "BLOCKED",
            "reason": "NON_NUMERIC_HISTORY_VALUE",
            "value": None,
        }

    return {
        "current": current_out,
        "previous": previous_out,
        "delta": delta_out,
    }


def same_source_bundle(*facts: dict[str, Any]) -> bool:
    sets = []

    for fact in facts:
        hashes = fact.get("source_hashes")
        if not isinstance(hashes, list) or not hashes:
            return False
        sets.append(set(hashes))

    common = sets[0]
    for item in sets[1:]:
        common &= item

    return bool(common)