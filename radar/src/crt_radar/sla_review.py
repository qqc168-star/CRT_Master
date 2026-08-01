from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from .liquidation_aggregator import canonical_json_bytes, sha256_hex


SLA_REVIEW_SCHEMA_VERSION = "CRT_RADAR_SLA_REVIEW_V1"
EXTERNAL_ACTION_AUTHORITY = "NONE"


@dataclass(frozen=True)
class EligibleRun:
    run_id: str
    outcome: str
    elapsed_s: float
    minimum_coverage_ratio: float | None
    blocked_snapshot_count: int
    acceptance_failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.outcome == "COMPLETED"
            and not self.acceptance_failures
            and self.blocked_snapshot_count == 0
        )


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def normalize_run(summary: dict[str, Any]) -> EligibleRun:
    if not isinstance(summary, dict):
        raise ValueError("run summary must be an object")
    run_id = str(summary.get("run_id") or summary.get("process_run_id") or "")
    if not run_id:
        raise ValueError("run summary requires run_id")
    outcomes = summary.get("process_stop_outcomes") or []
    outcome = str(outcomes[-1]) if isinstance(outcomes, list) and outcomes else str(summary.get("outcome", "UNKNOWN"))
    duration_ms = _finite(summary.get("duration_ms", 0), "duration_ms")
    coverage = summary.get("minimum_observed_coverage_ratio")
    coverage_value = None if coverage is None else _finite(coverage, "minimum_observed_coverage_ratio")
    failures = summary.get("acceptance_failures") or []
    if not isinstance(failures, list):
        raise ValueError("acceptance_failures must be a list")
    return EligibleRun(
        run_id=run_id,
        outcome=outcome,
        elapsed_s=duration_ms / 1000,
        minimum_coverage_ratio=coverage_value,
        blocked_snapshot_count=int(summary.get("blocked_snapshot_count", 0)),
        acceptance_failures=tuple(sorted(str(item) for item in failures)),
    )


def build_sla_review(
    summaries: Iterable[dict[str, Any]],
    *,
    required_runs: int = 20,
) -> dict[str, Any]:
    if required_runs <= 0:
        raise ValueError("required_runs must be positive")
    runs = [normalize_run(item) for item in summaries]
    run_ids = [item.run_id for item in runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("duplicate run_id in SLA review")

    passed = [item for item in runs if item.passed]
    failed = [item for item in runs if not item.passed]
    elapsed = [item.elapsed_s for item in runs]
    coverages = [item.minimum_coverage_ratio for item in runs if item.minimum_coverage_ratio is not None]
    decision = "READY_FOR_MATURITY_REVIEW" if len(passed) >= required_runs else "MATURITY_REVIEW_PENDING"
    result = {
        "schema_version": SLA_REVIEW_SCHEMA_VERSION,
        "required_runs": required_runs,
        "observed_runs": len(runs),
        "passed_runs": len(passed),
        "failed_runs": len(failed),
        "pass_rate": (len(passed) / len(runs)) if runs else None,
        "elapsed_s": {
            "p50": _percentile(elapsed, 0.50),
            "p90": _percentile(elapsed, 0.90),
            "p99": _percentile(elapsed, 0.99),
            "max": max(elapsed) if elapsed else None,
        },
        "minimum_coverage_ratio": {
            "min": min(coverages) if coverages else None,
            "p50": _percentile(coverages, 0.50),
        },
        "failed_run_ids": [item.run_id for item in failed],
        "failed_run_reasons": {
            item.run_id: list(item.acceptance_failures) or [item.outcome]
            for item in failed
        },
        "decision": decision,
        "promotion_authority": "USER_EXPLICIT_APPROVAL_REQUIRED",
        "external_action_authority": EXTERNAL_ACTION_AUTHORITY,
        "external_action_performed": False,
    }
    result["review_hash"] = sha256_hex(canonical_json_bytes(result))
    return result
