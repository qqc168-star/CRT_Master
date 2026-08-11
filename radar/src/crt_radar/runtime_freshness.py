from __future__ import annotations

import time
from pathlib import Path
from typing import Any


FUTURE_CLOCK_SKEW_S = 300


def assess_file_freshness(
    path: str | Path,
    *,
    max_age_seconds: int,
    now_ms: int | None = None,
    reason_prefix: str = "PHONE_L4",
) -> dict[str, Any]:
    """Assess transport freshness from a local file's modification time.

    This check does not grant metric authority and does not replace the Source
    Gate's timestamp/schema/coverage validation. It only detects a missing or
    stopped local handoff such as the Mobile L4 -> Syncthing -> laptop bridge.
    """
    if int(max_age_seconds) <= 0:
        raise ValueError("max_age_seconds must be positive")
    if not isinstance(reason_prefix, str) or not reason_prefix.strip():
        raise ValueError("reason_prefix must be a non-empty string")

    target = Path(path)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    base = {
        "check_id": f"{reason_prefix}_FILE_FRESHNESS",
        "path": str(target),
        "max_age_seconds": int(max_age_seconds),
        "authority": "TRANSPORT_ONLY",
        "metric_authority": "NONE",
        "external_action_authority": "NONE",
        "blocker": None,
    }

    try:
        stat = target.stat()
    except FileNotFoundError:
        return {
            **base,
            "state": "MISSING",
            "mtime_ms": None,
            "age_seconds": None,
            "blocker": f"{reason_prefix}_MISSING",
        }

    mtime_ms = int(stat.st_mtime_ns // 1_000_000)
    if mtime_ms > now + FUTURE_CLOCK_SKEW_S * 1000:
        return {
            **base,
            "state": "CLOCK_SKEW",
            "mtime_ms": mtime_ms,
            "age_seconds": None,
            "blocker": f"{reason_prefix}_CLOCK_SKEW",
        }

    age_ms = max(0, now - mtime_ms)
    age_seconds = age_ms / 1000.0
    if age_ms > int(max_age_seconds) * 1000:
        return {
            **base,
            "state": "STALE",
            "mtime_ms": mtime_ms,
            "age_seconds": age_seconds,
            "blocker": f"{reason_prefix}_STALE",
        }

    return {
        **base,
        "state": "FRESH",
        "mtime_ms": mtime_ms,
        "age_seconds": age_seconds,
    }


def _validated_runtime_check(check: dict[str, Any]) -> dict[str, Any]:
    """Enforce the transport-only authority boundary for runtime freshness checks."""
    if not isinstance(check, dict):
        raise ValueError("runtime check must be an object")
    if check.get("authority") != "TRANSPORT_ONLY":
        raise ValueError("runtime check authority must be TRANSPORT_ONLY")
    if check.get("metric_authority") != "NONE":
        raise ValueError("runtime check metric_authority must be NONE")
    if check.get("external_action_authority") != "NONE":
        raise ValueError("runtime check external_action_authority must be NONE")
    check_id = check.get("check_id")
    state = check.get("state")
    if not isinstance(check_id, str) or not check_id:
        raise ValueError("runtime check check_id missing")
    if not isinstance(state, str) or not state:
        raise ValueError("runtime check state missing")
    blocker = check.get("blocker")
    if blocker is not None and (not isinstance(blocker, str) or not blocker):
        raise ValueError("runtime check blocker must be null or a non-empty string")
    return dict(check)


def apply_runtime_checks(
    source_gate: dict[str, Any],
    runtime_checks: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Attach transport-only checks and fail closed when one returns a blocker."""
    if not runtime_checks:
        return source_gate

    normalized = [_validated_runtime_check(check) for check in runtime_checks]
    blockers = [str(value) for value in source_gate.get("blocked_reasons", [])]
    for check in normalized:
        blocker = check.get("blocker")
        if isinstance(blocker, str) and blocker:
            blockers.append(blocker)

    result = dict(source_gate)
    result["runtime_checks"] = normalized
    result["blocked_reasons"] = sorted(set(blockers))
    if result["blocked_reasons"]:
        result["formal_state"] = "BLOCKED"
    return result
