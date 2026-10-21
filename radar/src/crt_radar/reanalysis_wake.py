from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable

from .mstr_asst_market_health import (
    validate_mstr_asst_market_health, validate_issuer_ratio_observation,
)
from .issuer_announcement_runner import (
    validate_issuer_announcement_wake,
)
from .observation_store import Observation
from .broker_capital_observation import reconcile_capital


def capital_state_identity(
    reconciliation: dict[str, Any] | None,
    *,
    at_ms: int,
    decision_intent: dict[str, Any] | None = None,
) -> str | None:
    """Qualified observation identity, never spending or trading authority.

    Observation/confirmation clocks remain in their source evidence. They do
    not make identical capital facts a new reanalysis episode.
    """
    if not isinstance(reconciliation, dict):
        return None
    checked = reconcile_capital(
        reconciliation.get("broker_observed"),
        reconciliation.get("user_confirmed"),
        at_ms=at_ms,
    )
    if checked != reconciliation or checked["state"] != "AVAILABLE":
        return None
    observed = checked["broker_observed"]
    confirmed = checked["user_confirmed"]
    if not isinstance(observed, dict) or not isinstance(confirmed, dict):
        return None
    full_intent = None
    if decision_intent is not None:
        if (not isinstance(decision_intent, dict)
                or set(decision_intent) != {"version", "source", "confirmed_at_ms", "reserved_usd", "no_leverage"}
                or decision_intent.get("source") != "USER_CONFIRMED"
                or not isinstance(decision_intent.get("version"), str)
                or not decision_intent["version"].strip()
                or decision_intent.get("no_leverage") is not True
                or type(decision_intent.get("confirmed_at_ms")) is not int
                or decision_intent["confirmed_at_ms"] != confirmed["confirmed_at_ms"]
                or decision_intent["confirmed_at_ms"] > at_ms
                or isinstance(decision_intent.get("reserved_usd"), bool)
                or not isinstance(decision_intent.get("reserved_usd"), (int, float))
                or not math.isfinite(decision_intent["reserved_usd"])
                or decision_intent["reserved_usd"] != confirmed["reserved_usd"]):
            return None
        full_intent = {key: decision_intent[key] for key in ("version", "source", "reserved_usd", "no_leverage")}
        full_intent["reserved_usd"] = confirmed["reserved_usd"]
    semantic = {
        "scope": checked["scope"],
        "source": observed["source"],
        "observation_scope": observed["scope"],
        "funds": observed["funds"],
        "holdings": [{key: row[key] for key in ("asset", "quantity", "currency", "security_type", "average_cost_usd")}
                     for row in observed["holdings"]],
        "open_orders": observed["open_orders"],
        "user_confirmed": {key: confirmed[key] for key in ("source", "reserved_usd", "plan_policy", "asset_roles")},
        "decision_intent": full_intent,
    }
    raw = json.dumps(semantic, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def apply_capital_reanalysis_wake(
    base_wake: dict[str, Any] | None,
    reconciliation: dict[str, Any] | None,
    *,
    at_ms: int,
    previous_reconciliation: dict[str, Any] | None = None,
    previous_at_ms: int | None = None,
    decision_intent: dict[str, Any] | None = None,
    previous_decision_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Feed material qualified capital changes into the existing wake fusion."""
    current = capital_state_identity(reconciliation, at_ms=at_ms, decision_intent=decision_intent)
    previous = (capital_state_identity(previous_reconciliation, at_ms=previous_at_ms,
                                       decision_intent=previous_decision_intent)
                if type(previous_at_ms) is int and previous_at_ms <= at_ms else None)
    requested = current is not None and current != previous
    qualification = (reconciliation.get("state", "BLOCKED")
                     if isinstance(reconciliation, dict) else "BLOCKED")
    qualification_reason = (reconciliation.get("reason", "CAPITAL_STATE_MISSING")
                            if isinstance(reconciliation, dict) else "CAPITAL_STATE_MISSING")
    qualification_lost = previous is not None and current is None
    change = {
        "state": "REANALYSIS_REQUESTED" if requested else "NO_WAKE",
        "reason": ("INITIAL_QUALIFIED_CAPITAL_STATE" if previous is None else "CAPITAL_STATE_CHANGED")
                  if requested else "CAPITAL_STATE_UNCHANGED" if current else "CAPITAL_STATE_NOT_QUALIFIED",
        "current_state_hash": current,
        "previous_state_hash": previous,
        "qualification_state": qualification,
        "qualification_reason": qualification_reason,
        "qualification_lost": qualification_lost,
        "action_output": "NONE", "external_action_authority": "NONE", "external_action_performed": False,
    }
    result = fuse_reanalysis_wake(base_wake, plan_drift=None, capital_change=change)
    assert result is not None
    return result


@dataclass(frozen=True)
class ReanalysisWakeDecision:
    state: str
    reason: str
    metric: str | None
    input_family: str | None
    current_value: float | None
    previous_value: float | None
    percent_change: float | None
    historical_percentile: float | None
    baseline_count: int

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "metric": self.metric,
            "input_family": self.input_family,
            "current_value": self.current_value,
            "previous_value": self.previous_value,
            "percent_change": self.percent_change,
            "historical_percentile": self.historical_percentile,
            "baseline_count": self.baseline_count,
            "action_output": "NONE",
            "analyst_reanalysis_requested": self.state == "REANALYSIS_REQUESTED",
        }


def _percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def _percentile(value: float, values: list[float]) -> float | None:
    if not values:
        return None
    count = sum(1 for item in values if item <= value)
    return (count / len(values)) * 100.0


def evaluate_intraday_reanalysis_wake(
    current: Observation,
    history: Iterable[Observation],
    *,
    minimum_baseline_count: int = 8,
    operational_percentile: float = 95.0,
) -> ReanalysisWakeDecision:
    """
    Read-only operational wake-up logic.

    operational_percentile is an operational sensitivity setting,
    not an investment threshold, formal CRT score, or trading signal.
    """

    series = [
        row
        for row in history
        if row.input_family == current.input_family
        and row.metric == current.metric
        and row.as_of_ms < current.as_of_ms
    ]
    series.sort(key=lambda row: row.as_of_ms)

    if not series:
        return ReanalysisWakeDecision(
            state="NO_WAKE",
            reason="NO_PRIOR_OBSERVATION",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=None,
            percent_change=None,
            historical_percentile=None,
            baseline_count=0,
        )

    previous = series[-1]

    historical_moves: list[float] = []
    for left, right in zip(series, series[1:]):
        delta = _percent_change(right.value_num, left.value_num)
        if delta is not None:
            historical_moves.append(abs(delta))

    current_change = _percent_change(current.value_num, previous.value_num)

    if current_change is None:
        return ReanalysisWakeDecision(
            state="NO_WAKE",
            reason="NON_COMPARABLE_PREVIOUS_VALUE",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=previous.value_num,
            percent_change=None,
            historical_percentile=None,
            baseline_count=len(historical_moves),
        )

    if len(historical_moves) < minimum_baseline_count:
        return ReanalysisWakeDecision(
            state="NO_WAKE",
            reason="INSUFFICIENT_INTRADAY_HISTORY",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=previous.value_num,
            percent_change=current_change,
            historical_percentile=None,
            baseline_count=len(historical_moves),
        )

    percentile = _percentile(abs(current_change), historical_moves)

    if percentile is not None and percentile >= operational_percentile:
        return ReanalysisWakeDecision(
            state="REANALYSIS_REQUESTED",
            reason="MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY",
            metric=current.metric,
            input_family=current.input_family,
            current_value=current.value_num,
            previous_value=previous.value_num,
            percent_change=current_change,
            historical_percentile=percentile,
            baseline_count=len(historical_moves),
        )

    return ReanalysisWakeDecision(
        state="NO_WAKE",
        reason="CHANGE_WITHIN_INTRADAY_HISTORY",
        metric=current.metric,
        input_family=current.input_family,
        current_value=current.value_num,
        previous_value=previous.value_num,
        percent_change=current_change,
        historical_percentile=percentile,
        baseline_count=len(historical_moves),
    )


def _assert_optional_authority(
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    expected = {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }

    for key, expected_value in expected.items():
        if key in payload and payload.get(key) != expected_value:
            raise ValueError(
                f"{label} {key} must remain {expected_value!r}"
            )


def liquidation_evidence_identity(event: Any, source_id: str) -> str:
    """Source-observation fingerprint, NOT an order or independent-trade ID.

    forceOrder z is cumulative. A changed z/price/time can change this fingerprint
    without proving another independent execution. Keep the existing fingerprints
    for immutable-history compatibility; never use novelty alone to upgrade.
    """
    return hashlib.sha256(json.dumps([
        source_id, event.symbol, event.trade_time_ms,
        event.order_side, event.price, event.filled_quantity,
    ], separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def apply_liquidation_research_wake(base_wake, *, store, candidate, source_gate,
                                    snapshot, registry, at_ms):
    """Consume an explicit local research classification, never detect one.

    The caller supplies a dated, traceable analyst classification, not just a
    rule/version. Source-observation identity does not establish trade identity.
    Existing Source Gate and immutable research storage own qualification and
    history. Full raw event-set membership is required; rolling totals alone
    cannot create events. No model, transport or notification is called here.
    """
    if candidate is None:
        return deepcopy(base_wake)
    from .liquidation_aggregator import canonical_json_bytes, normalize_force_order, sha256_hex
    from .source_gate_runner import parse_liquidation_aggregate

    result = deepcopy(base_wake)
    outcome = dict(state="BLOCKED", reason="LIQUIDATION_CANDIDATE_INVALID",
                   research_only=True, formal_season=None, action_output="NONE",
                   evidence_semantics="SOURCE_OBSERVATIONS_NOT_INDEPENDENT_TRADES",
                   independent_execution_state="NOT_PROVEN", order_level_deduplication="NOT_PROVEN",
                   classification_quality="ANALYST_JUDGMENT_NOT_MACHINE_PROVEN",
                   external_action_authority="NONE", external_action_performed=False)
    try:
        def require(condition, reason):
            if not condition:
                raise ValueError(reason)

        spec = registry.by_input_family("LIQUIDATION_AGGREGATES")
        require(spec.source_id == "CRT-CONN-BTC-DERIV-LIQ-AGGREGATOR-001",
                "LIQUIDATION_SOURCE_NOT_APPROVED")
        require(candidate["source_id"] == spec.source_id and candidate["symbol"] == "BTCUSDT",
                "LIQUIDATION_CANDIDATE_SOURCE_MISMATCH")
        require(candidate["direction"] in {"LONG", "SHORT"}, "LIQUIDATION_DIRECTION_INVALID")
        rule = candidate["candidate_rule_version"]
        require(isinstance(rule, str) and bool(rule.strip()), "CANDIDATE_RULE_VERSION_MISSING")
        require(type(at_ms) is int, "EVALUATION_CLOCK_INVALID")
        parsed = parse_liquidation_aggregate(snapshot, spec)
        cutoff = parsed["as_of_ms"]
        require(0 <= at_ms - cutoff <= spec.max_age_seconds * 1000,
                "LIQUIDATION_SNAPSHOT_STALE_OR_FUTURE")
        require(snapshot["generated_at_ms"] == cutoff, "LIQUIDATION_SNAPSHOT_CLOCK_MISMATCH")
        envelope, = [e for e in source_gate["evidence"]
                     if e.get("input_family") == "LIQUIDATION_AGGREGATES"]
        material = {k: v for k, v in envelope.items() if k != "evidence_hash"}
        require(envelope["source_id"] == spec.source_id
                and envelope["quality_state"] == "VALID_FRESH_COMPLETE_COVERAGE"
                and envelope["payload_hash"] == sha256_hex(canonical_json_bytes(snapshot))
                and envelope["evidence_hash"] == sha256_hex(canonical_json_bytes(material))
                and envelope["registry_hash"] == registry.with_l6_candidate_sources().hash
                and envelope["as_of_ms"] == cutoff,
                "LIQUIDATION_SOURCE_GATE_BINDING_INVALID")
        history = store.scoring_series("LIQUIDATION_AGGREGATES", "liquidation_24h_total_usd",
            visible_at_ms=at_ms, expected_layer_id=spec.namespace,
            allowed_source_ids=[spec.source_id], before_as_of_ms=cutoff)
        require(bool(history), "LIQUIDATION_HISTORY_BASELINE_MISSING")
        records = candidate["event_records"]
        require(isinstance(records, list) and bool(records), "RAW_EXECUTION_EVIDENCE_MISSING")
        events, raw_hashes, evidence = [], set(), {}
        for record in records:
            received = record["received_ms"]
            require(type(received) is int and received <= cutoff, "EXECUTION_NOT_YET_VISIBLE")
            event = normalize_force_order(record["raw_payload"], received_ms=received)
            require(cutoff - 86400_000 < event.event_time_ms <= cutoff
                    and max(event.event_time_ms, event.trade_time_ms) <= received,
                    "EXECUTION_CLOCK_OR_WINDOW_INVALID")
            require(record["event_hash"] == event.event_hash and event.event_hash not in raw_hashes,
                    "RAW_EXECUTION_HASH_OR_DUPLICATE_INVALID")
            identity = liquidation_evidence_identity(event, spec.source_id)
            require(identity not in evidence, "DUPLICATE_UNDERLYING_EXECUTION")
            evidence[identity] = event
            raw_hashes.add(event.event_hash)
            events.append(event)
        require(snapshot["event_set_hash"] == sha256_hex(canonical_json_bytes(sorted(raw_hashes)))
                and snapshot["event_count_24h"] == len(events), "EXECUTION_SET_BINDING_INVALID")
        for label, duration in (("1h", 3600_000), ("24h", 86400_000)):
            rows = [e for e in events if e.event_time_ms > cutoff - duration]
            bucket = parsed["windows"][label]
            require(len(rows) == bucket["event_count"], "EXECUTION_COUNT_MISMATCH")
            for direction, field in (("LONG", "long_liquidation_usd"), ("SHORT", "short_liquidation_usd")):
                require(math.isclose(sum(e.notional_usd for e in rows if e.liquidation_side == direction),
                                     bucket[field], rel_tol=1e-9, abs_tol=0.01),
                        "EXECUTION_NOTIONAL_MISMATCH")
        selected = candidate["supporting_evidence_ids"]
        require(isinstance(selected, list) and bool(selected) and len(set(selected)) == len(selected),
                "SUPPORTING_EVIDENCE_INVALID")
        require(all(e in evidence and evidence[e].liquidation_side == candidate["direction"]
                    for e in selected), "SUPPORTING_DIRECTION_OR_IDENTITY_INVALID")
        anchor = candidate["anchor_evidence_id"]
        require(anchor in selected, "CANDIDATE_ANCHOR_NOT_VISIBLE")
        identity = dict(source_id=spec.source_id, symbol="BTCUSDT",
                        direction=candidate["direction"], anchor_evidence_id=anchor)
        event_id = sha256_hex(canonical_json_bytes(identity))
        kind = "LIQUIDATION_RESEARCH_CANDIDATE"
        frozen = store.research_event(event_id, kind=kind)
        if frozen:
            require(frozen["candidate_rule_version"] == rule, "FROZEN_CANDIDATE_RULE_CONFLICT")
        classification = {key: candidate.get(key) for key in (
            "formed_at_ms", "classification_provenance", "classification_basis")}
        require(all(isinstance(classification[key], str) and bool(classification[key].strip())
                    for key in ("classification_provenance", "classification_basis")),
                "EXPLICIT_ANALYST_CLASSIFICATION_REQUIRED")
        formed = classification["formed_at_ms"]
        require(type(formed) is int and 0 < formed <= at_ms, "CLASSIFICATION_CLOCK_INVALID")
        if frozen:
            require(all(frozen.get(key) == value for key, value in classification.items())
                    and isinstance(frozen.get("classification_evidence_ids"), list),
                    "FROZEN_CLASSIFICATION_CONFLICT")
        classification_ids = frozen["classification_evidence_ids"] if frozen else sorted(selected)
        require(bool(classification_ids) and set(classification_ids) <= set(selected),
                "CLASSIFICATION_EVIDENCE_MISMATCH")
        require(all(evidence[key].received_ms <= formed for key in classification_ids),
                "CLASSIFICATION_PRECEDES_VISIBLE_EVIDENCE")
        revision = candidate["revision"]
        require(type(revision) is int and revision >= 1, "CANDIDATE_REVISION_INVALID")
        revision_kind = "LIQUIDATION_RESEARCH_REVISION:" + event_id
        prior = store.latest_research_event(revision_kind)
        outcome.update(event_id=event_id, candidate_rule_version=rule,
                       first_qualified_at_ms=frozen["first_qualified_at_ms"] if frozen else at_ms,
                       evidence_ids=sorted(selected), revision=revision, **classification)
        if prior and revision <= prior["revision"]:
            outcome.update(state="NO_WAKE", reason="LIQUIDATION_EVENT_ALREADY_RECORDED")
        else:
            require(revision == (prior["revision"] + 1 if prior else 1), "REVISION_SEQUENCE_INVALID")
            novel = set(selected) - set(prior["evidence_ids"] if prior else [])
            require(bool(novel), "UPGRADE_HAS_NO_NEW_EXECUTION_EVIDENCE")
            if prior:
                require(isinstance(candidate.get("upgrade_basis"), str)
                        and bool(candidate["upgrade_basis"].strip()), "UPGRADE_CLASSIFICATION_MISSING")
                require(all(evidence[e].received_ms > prior["qualified_at_ms"]
                            and evidence[e].event_time_ms > prior["latest_event_time_ms"] for e in novel),
                        "UPGRADE_EVIDENCE_NOT_NEW")
                # The existing source has no verifiable order/trade identifiers.
                # Later timestamps or cumulative z increases prove observations,
                # not independent trades. Do not invent grouping or accept a
                # caller-supplied flag as proof; this upgrade stays unavailable.
                raise ValueError("INDEPENDENT_EXECUTION_NOT_PROVEN")
            # Globally bind a source observation to one research event, even if a caller
            # renames its anchor or changes capture hashes to evade deduplication.
            # The legacy EXECUTION_CLAIM kind is retained, not an order-level claim.
            for evidence_id in selected:
                claim = store.research_event(evidence_id, kind="LIQUIDATION_EXECUTION_CLAIM")
                require(claim is None or claim["event_id"] == event_id, "EXECUTION_ALREADY_CLAIMED")
            if frozen is None:
                store.record_research_event(event_id, kind, {
                    **identity, "candidate_rule_version": rule, "first_qualified_at_ms": at_ms,
                    **classification, "classification_evidence_ids": classification_ids})
            for evidence_id in selected:
                store.record_research_event(evidence_id, "LIQUIDATION_EXECUTION_CLAIM", {"event_id": event_id})
            wake_id = sha256_hex(canonical_json_bytes([event_id, revision]))
            recorded = store.record_research_event(wake_id, revision_kind, {
                "event_id": event_id, "revision": revision, "qualified_at_ms": at_ms,
                "evidence_ids": sorted(set(selected) | set(prior["evidence_ids"] if prior else [])),
                "latest_event_time_ms": max(evidence[e].event_time_ms for e in selected),
                "source_gate_evidence_hash": envelope["evidence_hash"],
                "snapshot_hash": snapshot["snapshot_hash"], "candidate": deepcopy(candidate),
            })
            outcome.update(state="REANALYSIS_REQUESTED" if recorded else "NO_WAKE",
                           reason="QUALIFIED_LIQUIDATION_RESEARCH_EVENT" if recorded else "LIQUIDATION_EVENT_ALREADY_RECORDED",
                           wake_id=wake_id)
    except (ValueError, KeyError, TypeError) as exc:
        outcome.update(state="BLOCKED", reason=str(exc))
    result["liquidation_research"] = outcome
    if outcome["state"] == "REANALYSIS_REQUESTED" and result.get("state") != "REANALYSIS_REQUESTED":
        result.update(state="REANALYSIS_REQUESTED", reason=outcome["reason"],
                      input_family="LIQUIDATION_RESEARCH", metric="research_event",
                      current_value=None, previous_value=None, percent_change=None,
                      historical_percentile=None, baseline_count=len(history))
    return fuse_reanalysis_wake(result, plan_drift=None)


def fuse_reanalysis_wake(
    base_wake: dict[str, Any] | None,
    *,
    plan_drift: dict[str, Any] | None,
    mstr_asst_market_health: dict[str, Any] | None = None,
    issuer_ratio_observation: dict[str, Any] | None = None,
    issuer_announcement_wake: dict[str, Any] | None = None,
    capital_change: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fuse read-only BTC, plan-drift, equity-health and issuer observation wakes."""

    if base_wake is not None and not isinstance(base_wake, dict):
        raise ValueError("base_wake must be an object or None")

    if plan_drift is not None and not isinstance(plan_drift, dict):
        raise ValueError("plan_drift must be an object or None")

    if capital_change is None and isinstance(base_wake, dict):
        capital_change = base_wake.get("capital_change")
    if capital_change is not None:
        if not isinstance(capital_change, dict):
            raise ValueError("capital_change must be an object or None")
        _assert_optional_authority(capital_change, label="capital_change")
        for key in ("current_state_hash", "previous_state_hash"):
            value = capital_change.get(key)
            if value is not None and (not isinstance(value, str) or len(value) != 64
                                      or any(char not in "0123456789abcdef" for char in value)):
                raise ValueError("capital_change identity must be a sha256 hash")
        if (capital_change.get("state") == "REANALYSIS_REQUESTED"
                and (capital_change.get("current_state_hash") is None
                     or capital_change.get("current_state_hash") == capital_change.get("previous_state_hash"))):
            raise ValueError("capital_change wake requires changed qualified identity")

    market_health = None
    if mstr_asst_market_health is not None:
        market_health = validate_mstr_asst_market_health(
            mstr_asst_market_health
        )

    issuer_announcement = (
        validate_issuer_announcement_wake(
            issuer_announcement_wake
        )
        if issuer_announcement_wake is not None
        else None
    )

    if isinstance(base_wake, dict):
        _assert_optional_authority(
            base_wake,
            label="base_wake",
        )

    if isinstance(plan_drift, dict):
        _assert_optional_authority(
            plan_drift,
            label="plan_drift",
        )

    plan_requested = bool(
        isinstance(plan_drift, dict)
        and plan_drift.get("reanalysis_required") is True
    )

    market_requested = bool(
        isinstance(market_health, dict)
        and market_health.get("reanalysis_required") is True
    )

    issuer = (validate_issuer_ratio_observation(issuer_ratio_observation)
              if issuer_ratio_observation is not None else None)
    issuer_assets = [asset for asset, row in issuer["observations"].items()
                     if row["current_btc_per_diluted_share"] < row["previous_btc_per_diluted_share"]] if issuer else []
    issuer_requested = bool(issuer_assets)
    announcement_requested = bool(
        isinstance(issuer_announcement, dict)
        and issuer_announcement.get("state") == "REANALYSIS_REQUESTED"
    )

    if (
        base_wake is None
        and not plan_requested
        and not market_requested
        and not issuer_requested
        and not announcement_requested
        and capital_change is None
    ):
        return None

    if base_wake is None:
        result: dict[str, Any] = {
            "state": "NO_WAKE",
            "reason": "WAKE_NOT_EVALUATED",
            "metric": None,
            "input_family": None,
            "current_value": None,
            "previous_value": None,
            "percent_change": None,
            "historical_percentile": None,
            "baseline_count": 0,
        }
    else:
        result = deepcopy(base_wake)

    base_requested = (
        result.get("state") == "REANALYSIS_REQUESTED"
    )

    wake_sources: list[str] = []
    wake_reasons: list[str] = []

    if base_requested:
        base_reason = str(
            result.get(
                "reason",
                "BASE_REANALYSIS_REQUESTED",
            )
        )

        if base_reason == "DVOL_EXPANSION_ACTIVATED":
            base_source = "DVOL"
        elif result.get("input_family") == "LIQUIDATION_RESEARCH":
            base_source = "LIQUIDATION_RESEARCH"
        elif result.get("input_family") == "BTC_SPOT_PRICE":
            base_source = "BTC_INTRADAY"
        elif result.get("input_family") == "COMMANDER_PLAN_OBSERVATION":
            base_source = "COMMANDER_PLAN_OBSERVATION"
        elif result.get("input_family") == "BROKER_CAPITAL_STATE":
            base_source = "BROKER_CAPITAL_STATE"
        else:
            base_source = "BASE_WAKE"

        wake_sources.append(base_source)
        wake_reasons.append(base_reason)

    if market_requested:
        market_reasons = market_health.get("wake_reasons", [])
        wake_sources.append("MSTR_ASST_MARKET_HEALTH")
        wake_reasons.extend(str(reason) for reason in market_reasons)

        if not base_requested:
            result.update(
                {
                    "state": "REANALYSIS_REQUESTED",
                    "reason": str(market_health.get("reason")),
                    "metric": "mstr_asst_market_health",
                    "input_family": "MSTR_ASST_MARKET_HEALTH",
                    "current_value": None,
                    "previous_value": None,
                    "percent_change": None,
                    "historical_percentile": None,
                    "baseline_count": 0,
                }
            )

    if issuer_requested:
        issuer_reasons = [f"{asset}:BTC_PER_DILUTED_SHARE_DECREASED" for asset in issuer_assets]
        wake_sources.extend(f"{asset}_ISSUER_RATIO_OBSERVATION" for asset in issuer_assets)
        wake_reasons.extend(issuer_reasons)
        if not base_requested and not market_requested:
            result.update({
                "state": "REANALYSIS_REQUESTED", "reason": issuer_reasons[0],
                "metric": "issuer_btc_per_diluted_share", "input_family": "ISSUER_RATIO_OBSERVATION",
                "current_value": None, "previous_value": None, "percent_change": None,
                "historical_percentile": None, "baseline_count": 0,
            })

    if announcement_requested:
        announcement_reason = str(
            issuer_announcement.get(
                "reason",
                "NEW_OFFICIAL_ISSUER_ANNOUNCEMENT",
            )
        )
        wake_sources.append("ISSUER_ANNOUNCEMENT")
        wake_reasons.append(announcement_reason)
        if not base_requested and not market_requested and not issuer_requested:
            result.update(
                {
                    "state": "REANALYSIS_REQUESTED",
                    "reason": announcement_reason,
                    "metric": "official_issuer_announcement",
                    "input_family": "ISSUER_ANNOUNCEMENT",
                    "current_value": None,
                    "previous_value": None,
                    "percent_change": None,
                    "historical_percentile": None,
                    "baseline_count": 0,
                }
            )

    if plan_requested:
        plan_reason = str(
            plan_drift.get(
                "reason",
                "ACTIVE_PLAN_CONDITION_VIOLATED",
            )
        )

        wake_sources.append("PLAN_DRIFT")
        wake_reasons.append(plan_reason)

        if (
            not base_requested
            and not market_requested
            and not issuer_requested
            and not announcement_requested
        ):
            result.update(
                {
                    "state": "REANALYSIS_REQUESTED",
                    "reason": plan_reason,
                    "metric": "plan_drift",
                    "input_family": "CAPITAL_PLAN",
                    "current_value": None,
                    "previous_value": None,
                    "percent_change": None,
                    "historical_percentile": None,
                    "baseline_count": 0,
                }
            )

    capital_requested = bool(capital_change and capital_change.get("state") == "REANALYSIS_REQUESTED")
    if capital_requested:
        wake_sources.append("BROKER_CAPITAL_STATE")
        wake_reasons.append(capital_change["reason"])
        if result.get("state") != "REANALYSIS_REQUESTED":
            result.update({
                "state": "REANALYSIS_REQUESTED", "reason": capital_change["reason"],
                "metric": "capital_state", "input_family": "BROKER_CAPITAL_STATE",
                "current_value": None, "previous_value": None, "percent_change": None,
                "historical_percentile": None, "baseline_count": 0,
            })
    if capital_change is not None:
        result["capital_change"] = deepcopy(capital_change)

    liquidation = result.get("liquidation_research")
    if isinstance(liquidation, dict) and liquidation.get("state") == "REANALYSIS_REQUESTED":
        _assert_optional_authority(liquidation, label="liquidation_research")
        wake_sources.append("LIQUIDATION_RESEARCH")
        wake_reasons.append(liquidation["reason"])

    requested = (
        result.get("state") == "REANALYSIS_REQUESTED"
    )

    result["analyst_reanalysis_requested"] = requested
    result["wake_sources"] = list(dict.fromkeys(wake_sources))
    result["wake_reasons"] = list(dict.fromkeys(wake_reasons))

    result["plan_drift_state"] = (
        plan_drift.get("state")
        if isinstance(plan_drift, dict)
        else None
    )

    result["plan_drift_reanalysis_required"] = (
        plan_drift.get("reanalysis_required")
        if isinstance(plan_drift, dict)
        else None
    )

    result["mstr_asst_market_health_state"] = (
        market_health.get("state")
        if isinstance(market_health, dict)
        else None
    )

    result["mstr_asst_market_health_reanalysis_required"] = (
        market_health.get("reanalysis_required")
        if isinstance(market_health, dict)
        else None
    )

    result["issuer_announcement_reanalysis_requested"] = (
        announcement_requested
    )

    result["action_output"] = "NONE"
    result["external_action_authority"] = "NONE"
    result["external_action_performed"] = False

    return result
