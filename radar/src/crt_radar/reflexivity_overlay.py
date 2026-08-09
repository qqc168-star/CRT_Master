from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any


OVERLAY_ID = "CRT-ISSUER-001"
OVERLAY_TYPE = "NON_WEIGHTED_EVIDENCE_OVERLAY"
EXTERNAL_ACTION_AUTHORITY = "NONE"

COVERAGE_STATES = {"COMPLETE", "PARTIAL", "BLOCKED", "NOT_EVALUATED"}
EMPTY_REASON = "VERIFIED_NO_MATCH"
ACTIVE_SUPERSESSION_STATE = "ACTIVE"
SUPERSESSION_STATES = {"ACTIVE", "SUPERSEDED", "PARTIAL", "UNKNOWN"}
BLOCKER_SCOPES = {"FACT", "EVENT", "CALCULATION", "JUDGMENT", "OVERLAY", "SOURCE_GATE"}
PROHIBITED_FIELDS = {
    "asset_role",
    "asset_roles",
    "capital_strategy",
    "reflexivity_score",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# No current-main contract or registry formally approves a market-data source or
# observation-window spec for this overlay. These locks therefore stay empty and
# market-response calculations fail closed until a later approved change supplies
# an explicit registry-backed allowlist.
APPROVED_MARKET_SOURCE_IDS: frozenset[str] = frozenset()
APPROVED_MARKET_WINDOW_SPEC_IDS: frozenset[str] = frozenset()

FORMULA_READY_SPECS = frozenset(
    {
        "REPURCHASE_AVG_PRICE",
        "OPEN_MARKET_PARTICIPATION",
        "REPURCHASE_SHARE_RATIO",
        "GROSS_ISSUANCE_RATIO",
        "NET_SHARE_COUNT_CHANGE",
        "REMAINING_AUTHORIZATION",
        "REMAINING_ATM_CAPACITY",
        "BTC_NET_FLOW",
        "LIQUIDATION_PREFERENCE_RETIRED",
        "DISTRIBUTION_RUN_RATE_REMOVED",
        "FIXED_WINDOW_RETURN",
        "BTC_EXCESS_RETURN",
        "VOLUME_MULTIPLE",
    }
)
MARKET_LOCKED_SPECS = frozenset(
    {
        "OPEN_MARKET_PARTICIPATION",
        "FIXED_WINDOW_RETURN",
        "BTC_EXCESS_RETURN",
        "VOLUME_MULTIPLE",
    }
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() != "UNKNOWN"


def _blocker(
    code: str,
    scope: str,
    affected_ids: list[str],
    reason: str,
    required_to_clear: list[str],
) -> dict[str, Any]:
    stable_body = {
        "code": code,
        "scope": scope,
        "affected_ids": sorted({value for value in affected_ids if _is_id(value)}),
        "reason": reason,
        "required_to_clear": sorted({value for value in required_to_clear if _is_id(value)}),
    }
    return {
        "blocker_id": f"CRT-REFLEX-{_sha256(stable_body)[:20]}",
        "overlay_id": OVERLAY_ID,
        "reason_code": code,
        **stable_body,
    }


def _add_blocker(
    blockers: list[dict[str, Any]],
    code: str,
    scope: str,
    affected_ids: list[str],
    reason: str,
    required_to_clear: list[str],
) -> None:
    blockers.append(_blocker(code, scope, affected_ids, reason, required_to_clear))


def _dedupe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["blocker_id"]: item for item in blockers}
    return sorted(
        by_id.values(),
        key=lambda item: (
            item["scope"],
            item["reason_code"],
            tuple(item["affected_ids"]),
            item["blocker_id"],
        ),
    )


def _scan_prohibited(value: Any, blockers: list[dict[str, Any]], path: str = "reflexivity_input") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in PROHIBITED_FIELDS:
                _add_blocker(
                    blockers,
                    "PROHIBITED_ANALYST_OUTPUT",
                    "OVERLAY",
                    [child_path],
                    f"{key} belongs to GPT or the user, not deterministic overlay evidence.",
                    [f"remove {child_path}"],
                )
            if key == "action_output" and child != "NONE":
                _add_blocker(
                    blockers,
                    "ACTION_OUTPUT_NOT_NONE",
                    "OVERLAY",
                    [child_path],
                    "The overlay cannot emit an action.",
                    ["set action_output to NONE"],
                )
            _scan_prohibited(child, blockers, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_prohibited(child, blockers, f"{path}[{index}]")


def _read_section(
    payload: dict[str, Any],
    name: str,
    blockers: list[dict[str, Any]],
    *,
    blocker_scope: str,
) -> dict[str, Any]:
    section = payload.get(name)
    if not isinstance(section, dict):
        _add_blocker(
            blockers,
            "SECTION_MISSING",
            blocker_scope,
            [name],
            f"{name} must be an explicit object; absence is not verified zero.",
            [f"provide {name}.coverage_state, scope, and items"],
        )
        return {"coverage_state": "BLOCKED", "scope": {}, "items": []}

    coverage_state = section.get("coverage_state")
    if coverage_state not in COVERAGE_STATES:
        _add_blocker(
            blockers,
            "COVERAGE_STATE_INVALID",
            blocker_scope,
            [name],
            f"{name}.coverage_state is missing or invalid.",
            [f"set {name}.coverage_state to a contract value"],
        )
        coverage_state = "BLOCKED"

    scope = section.get("scope")
    if not isinstance(scope, dict):
        _add_blocker(
            blockers,
            "SCOPE_MISSING",
            blocker_scope,
            [name],
            f"{name}.scope must be explicit.",
            [f"provide {name}.scope"],
        )
        scope = {}

    items = section.get("items")
    if not isinstance(items, list):
        _add_blocker(
            blockers,
            "ITEMS_MISSING",
            blocker_scope,
            [name],
            f"{name}.items must be a list; a missing field is not an empty result.",
            [f"provide {name}.items"],
        )
        items = []

    if coverage_state != "COMPLETE":
        _add_blocker(
            blockers,
            "SECTION_COVERAGE_INCOMPLETE",
            blocker_scope,
            [name],
            f"{name} coverage is {coverage_state}, so absence or completeness cannot be concluded.",
            [f"complete and verify {name} coverage"],
        )
    elif not items and section.get("empty_reason") != EMPTY_REASON:
        _add_blocker(
            blockers,
            "EMPTY_STATE_UNVERIFIED",
            blocker_scope,
            [name],
            f"An empty {name}.items list is not evidence of no matching facts or events.",
            [f"set {name}.empty_reason to {EMPTY_REASON} after complete verification"],
        )

    return {
        "coverage_state": coverage_state,
        "scope": deepcopy(scope),
        "items": deepcopy(items),
        "empty_reason": section.get("empty_reason"),
    }


def _normalize_source_ref(
    value: Any,
    blockers: list[dict[str, Any]],
    affected_id: str,
    *,
    blocker_scope: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _add_blocker(
            blockers,
            "SOURCE_EVIDENCE_UNVERIFIABLE",
            blocker_scope,
            [affected_id],
            "A source reference is missing or malformed.",
            ["provide a source_id, source_as_of_ms, and evidence_hash"],
        )
        return None

    source_id = value.get("source_id")
    source_as_of_ms = value.get("source_as_of_ms")
    evidence_hash = value.get("evidence_hash")
    valid = True
    if not _is_id(source_id):
        valid = False
        _add_blocker(
            blockers,
            "SOURCE_EVIDENCE_UNVERIFIABLE",
            blocker_scope,
            [affected_id],
            "source_id is missing or unresolved.",
            ["provide a stable source_id"],
        )
    if not isinstance(source_as_of_ms, int) or isinstance(source_as_of_ms, bool) or source_as_of_ms <= 0:
        valid = False
        _add_blocker(
            blockers,
            "SOURCE_AS_OF_UNKNOWN",
            blocker_scope,
            [affected_id],
            "source_as_of_ms is missing or invalid.",
            ["provide the source effective timestamp in milliseconds"],
        )
    if not isinstance(evidence_hash, str) or SHA256_RE.fullmatch(evidence_hash) is None:
        valid = False
        _add_blocker(
            blockers,
            "SOURCE_EVIDENCE_UNVERIFIABLE",
            blocker_scope,
            [affected_id],
            "evidence_hash must be a lowercase SHA-256 digest.",
            ["provide a verified evidence SHA-256"],
        )
    if not valid:
        return None

    normalized = {
        "source_id": source_id,
        "source_as_of_ms": source_as_of_ms,
        "evidence_hash": evidence_hash,
    }
    for key in ("document_id", "published_at_ms", "retrieved_at_ms", "registry_hash"):
        if key in value:
            normalized[key] = deepcopy(value[key])
    return normalized


def _scope_ids(
    section: dict[str, Any],
    blockers: list[dict[str, Any]],
    name: str,
    *,
    require_issuer: bool = True,
) -> tuple[set[str], set[str]]:
    scope = section["scope"]
    issuer_values = scope.get("issuer_ids")
    security_values = scope.get("security_ids")
    issuer_ids = {value for value in issuer_values if _is_id(value)} if isinstance(issuer_values, list) else set()
    security_ids = {value for value in security_values if _is_id(value)} if isinstance(security_values, list) else set()
    if require_issuer and not issuer_ids:
        _add_blocker(
            blockers,
            "ISSUER_IDENTITY_UNRESOLVED",
            "OVERLAY",
            [name],
            f"{name}.scope has no stable issuer identity.",
            ["provide at least one stable issuer_id"],
        )
    if not isinstance(security_values, list):
        _add_blocker(
            blockers,
            "SECURITY_IDENTITY_UNRESOLVED",
            "OVERLAY",
            [name],
            f"{name}.scope.security_ids is missing.",
            ["provide the evaluated security_ids list, even when empty by design"],
        )
    return issuer_ids, security_ids


def _normalize_issuer_facts(section: dict[str, Any], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issuer_ids, security_ids = _scope_ids(section, blockers, "issuer_facts")
    result: list[dict[str, Any]] = []
    seen_fact_ids: set[str] = set()
    for index, item in enumerate(section["items"]):
        label = f"issuer_facts[{index}]"
        if not isinstance(item, dict):
            _add_blocker(blockers, "FACT_INVALID", "FACT", [label], "Issuer fact must be an object.", ["provide a valid fact object"])
            continue
        fact_id = item.get("fact_id")
        issuer_id = item.get("issuer_id")
        security_id = item.get("security_id")
        if not _is_id(fact_id):
            _add_blocker(blockers, "FACT_INVALID", "FACT", [label], "fact_id is missing.", ["provide a stable fact_id"])
            continue
        if fact_id in seen_fact_ids:
            _add_blocker(blockers, "FACT_ID_DUPLICATE", "FACT", [fact_id], "fact_id must be unique within the overlay.", ["assign a unique fact_id"])
            continue
        seen_fact_ids.add(fact_id)
        valid = True
        if issuer_id not in issuer_ids:
            valid = False
            _add_blocker(blockers, "ISSUER_IDENTITY_UNRESOLVED", "FACT", [fact_id], "Fact issuer_id is outside the verified scope.", ["resolve issuer identity and scope"])
        if security_id is not None and security_id not in security_ids:
            valid = False
            _add_blocker(blockers, "SECURITY_IDENTITY_UNRESOLVED", "FACT", [fact_id], "Fact security_id is outside the verified scope.", ["resolve security identity and scope"])
        if not _is_id(item.get("fact_type")) or "value" not in item or not _is_id(item.get("unit")):
            valid = False
            _add_blocker(blockers, "FACT_INVALID", "FACT", [fact_id], "fact_type, value, and unit are required.", ["provide typed fact fields"])
        if not isinstance(item.get("effective_at_ms"), int) or isinstance(item.get("effective_at_ms"), bool) or item.get("effective_at_ms", 0) <= 0:
            valid = False
            _add_blocker(blockers, "SOURCE_AS_OF_UNKNOWN", "FACT", [fact_id], "Fact effective_at_ms is missing or invalid.", ["provide the fact effective timestamp"])
        if item.get("origin") != "REPORTED":
            valid = False
            _add_blocker(blockers, "FACT_ORIGIN_INVALID", "FACT", [fact_id], "Input facts must be REPORTED; deterministic facts are produced only by this module.", ["use origin REPORTED or submit a calculation_request"])
        if item.get("value") == 0 and item.get("zero_state") != "VERIFIED_REPORTED_ZERO":
            valid = False
            _add_blocker(blockers, "VERIFIED_ZERO_NOT_ESTABLISHED", "FACT", [fact_id], "Reported zero lacks explicit complete-coverage verification.", ["set zero_state to VERIFIED_REPORTED_ZERO after source verification"])
        source_ref = _normalize_source_ref(item.get("source_ref"), blockers, fact_id, blocker_scope="FACT")
        if source_ref is None:
            valid = False
        if valid:
            normalized = {
                "asset_fact_id": fact_id,
                "overlay_id": OVERLAY_ID,
                "overlay_type": OVERLAY_TYPE,
                "fact_kind": "ISSUER_FACT",
                "issuer_id": issuer_id,
                "security_id": security_id,
                "fact_type": item["fact_type"],
                "value": deepcopy(item["value"]),
                "unit": item["unit"],
                "effective_at_ms": item["effective_at_ms"],
                "origin": "REPORTED",
                "source_refs": [source_ref],
                "quality_state": item.get("quality_state", "VALID_REPORTED"),
            }
            if item.get("zero_state") is not None:
                normalized["zero_state"] = item["zero_state"]
            result.append(normalized)
    return result


def _normalize_window(
    value: Any,
    expected_kind: str,
    blockers: list[dict[str, Any]],
    event_id: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("kind") != expected_kind:
        _add_blocker(
            blockers,
            "EXECUTION_DISCLOSURE_MIXED",
            "EVENT",
            [event_id],
            f"{expected_kind.lower()} window is missing or has the wrong semantic kind.",
            [f"provide a distinct {expected_kind} window"],
        )
        return None
    start_ms = value.get("start_ms")
    end_ms = value.get("end_ms")
    if not isinstance(start_ms, int) or isinstance(start_ms, bool) or not isinstance(end_ms, int) or isinstance(end_ms, bool) or start_ms <= 0 or end_ms < start_ms:
        code = "EXECUTION_WINDOW_INCOMPLETE" if expected_kind == "EXECUTION" else "DISCLOSURE_TIMESTAMP_UNKNOWN"
        _add_blocker(blockers, code, "EVENT", [event_id], f"{expected_kind.lower()} window timestamps are incomplete or invalid.", [f"provide valid {expected_kind} start_ms and end_ms"])
        return None
    precision = value.get("precision")
    if not _is_id(precision):
        code = "EXECUTION_WINDOW_INCOMPLETE" if expected_kind == "EXECUTION" else "DISCLOSURE_TIMESTAMP_UNKNOWN"
        _add_blocker(blockers, code, "EVENT", [event_id], f"{expected_kind.lower()} window precision is missing.", [f"provide {expected_kind} precision"])
        return None
    return {"kind": expected_kind, "start_ms": start_ms, "end_ms": end_ms, "precision": precision}


def _normalize_events(section: dict[str, Any], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issuer_ids, security_ids = _scope_ids(section, blockers, "issuer_events")
    result: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for index, item in enumerate(section["items"]):
        label = f"issuer_events[{index}]"
        if not isinstance(item, dict):
            _add_blocker(blockers, "EVENT_INVALID", "EVENT", [label], "Issuer event must be an object.", ["provide a valid event object"])
            continue
        event_id = item.get("event_id")
        if not _is_id(event_id):
            _add_blocker(blockers, "EVENT_INVALID", "EVENT", [label], "event_id is missing.", ["provide a stable event_id"])
            continue
        if event_id in seen_event_ids:
            _add_blocker(blockers, "EVENT_ID_DUPLICATE", "EVENT", [event_id], "event_id must be unique within the overlay.", ["assign a unique event_id"])
            continue
        seen_event_ids.add(event_id)
        valid = True
        issuer_id = item.get("issuer_id")
        security_id = item.get("security_id")
        if issuer_id not in issuer_ids:
            valid = False
            _add_blocker(blockers, "ISSUER_IDENTITY_UNRESOLVED", "EVENT", [event_id], "Event issuer_id is outside the verified scope.", ["resolve issuer identity and scope"])
        if security_id is not None and security_id not in security_ids:
            valid = False
            _add_blocker(blockers, "SECURITY_IDENTITY_UNRESOLVED", "EVENT", [event_id], "Event security_id is outside the verified scope.", ["resolve security identity and scope"])
        if not _is_id(item.get("event_type")):
            valid = False
            _add_blocker(blockers, "EVENT_INVALID", "EVENT", [event_id], "event_type is missing.", ["provide an event_type"])
        execution_window = _normalize_window(item.get("execution_window"), "EXECUTION", blockers, event_id)
        disclosure_window = _normalize_window(item.get("disclosure_window"), "DISCLOSURE", blockers, event_id)
        if execution_window is None or disclosure_window is None:
            valid = False
        reported_values = item.get("reported_values")
        if not isinstance(reported_values, list) or not reported_values:
            valid = False
            _add_blocker(blockers, "EVENT_INVALID", "EVENT", [event_id], "reported_values must contain at least one reported value.", ["provide source-backed reported_values"])
        source_ref = _normalize_source_ref(item.get("source_ref"), blockers, event_id, blocker_scope="EVENT")
        if source_ref is None:
            valid = False
        supersession = item.get("supersession")
        if not isinstance(supersession, dict) or supersession.get("state") not in SUPERSESSION_STATES:
            valid = False
            supersession = {"state": "UNKNOWN", "superseded_by_event_id": None}
            _add_blocker(blockers, "SUPERSESSION_UNRESOLVED", "EVENT", [event_id], "Event supersession state is missing or invalid.", ["resolve the active filing or event version"])
        else:
            state = supersession["state"]
            target = supersession.get("superseded_by_event_id")
            if state in {"PARTIAL", "UNKNOWN"} or (state == "SUPERSEDED" and not _is_id(target)):
                valid = False
                _add_blocker(blockers, "SUPERSESSION_UNRESOLVED", "EVENT", [event_id], "Event supersession cannot be resolved to an active version.", ["link the superseding event or verify ACTIVE state"])
        if valid:
            result.append(
                {
                    "event_id": event_id,
                    "overlay_id": OVERLAY_ID,
                    "overlay_type": OVERLAY_TYPE,
                    "issuer_id": issuer_id,
                    "security_id": security_id,
                    "event_type": item["event_type"],
                    "execution_window": execution_window,
                    "disclosure_window": disclosure_window,
                    "reported_values": deepcopy(reported_values),
                    "source_refs": [source_ref],
                    "supersession": {
                        "state": supersession["state"],
                        "superseded_by_event_id": supersession.get("superseded_by_event_id"),
                    },
                    "active_for_calculation": supersession["state"] == ACTIVE_SUPERSESSION_STATE,
                }
            )
    return result


def _normalize_market_reactions(section: dict[str, Any], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, security_ids = _scope_ids(section, blockers, "market_reaction_facts", require_issuer=False)
    result: list[dict[str, Any]] = []
    for index, item in enumerate(section["items"]):
        label = f"market_reaction_facts[{index}]"
        if not isinstance(item, dict):
            _add_blocker(blockers, "FACT_INVALID", "FACT", [label], "Market reaction fact must be an object.", ["provide a valid market fact"])
            continue
        fact_id = item.get("reaction_fact_id")
        if not _is_id(fact_id):
            _add_blocker(blockers, "FACT_INVALID", "FACT", [label], "reaction_fact_id is missing.", ["provide a stable reaction_fact_id"])
            continue
        security_id = item.get("security_id")
        if security_id not in security_ids:
            _add_blocker(blockers, "SECURITY_IDENTITY_UNRESOLVED", "FACT", [fact_id], "Market fact security_id is outside the verified scope.", ["resolve security identity and scope"])
        window = item.get("window")
        window_spec_id = window.get("window_spec_id") if isinstance(window, dict) else None
        source_refs = item.get("source_refs")
        normalized_sources = []
        if isinstance(source_refs, list):
            for source_ref in source_refs:
                normalized = _normalize_source_ref(source_ref, blockers, fact_id, blocker_scope="FACT")
                if normalized is not None:
                    normalized_sources.append(normalized)
        else:
            _normalize_source_ref(None, blockers, fact_id, blocker_scope="FACT")
        approved_sources = bool(normalized_sources) and all(
            source_ref["source_id"] in APPROVED_MARKET_SOURCE_IDS for source_ref in normalized_sources
        )
        if not _is_id(window_spec_id) or window_spec_id not in APPROVED_MARKET_WINDOW_SPEC_IDS:
            _add_blocker(blockers, "WINDOW_SPEC_NOT_APPROVED", "FACT", [fact_id], "No current-main observation-window lock approves this market reaction fact.", ["approve and register the window_spec_id"])
        if not approved_sources:
            _add_blocker(blockers, "PRICE_OR_VOLUME_UNVERIFIABLE", "FACT", [fact_id], "No current-main market-data source lock approves this reaction fact.", ["approve and register the market source_id"])
        # This branch is intentionally unreachable until both formal allowlists are
        # populated by a later approved contract change.
        if window_spec_id in APPROVED_MARKET_WINDOW_SPEC_IDS and approved_sources:
            result.append(
                {
                    "asset_fact_id": fact_id,
                    "overlay_id": OVERLAY_ID,
                    "overlay_type": OVERLAY_TYPE,
                    "fact_kind": "MARKET_REACTION_FACT",
                    "event_id": item.get("event_id"),
                    "security_id": security_id,
                    "fact_type": item.get("metric"),
                    "value": deepcopy(item.get("value")),
                    "unit": item.get("unit"),
                    "window_type": item.get("window_type"),
                    "window": deepcopy(window),
                    "benchmark_security_id": item.get("benchmark_security_id"),
                    "calculation_spec_id": item.get("calculation_spec_id"),
                    "input_fact_ids": deepcopy(item.get("input_fact_ids", [])),
                    "source_refs": normalized_sources,
                    "quality_state": item.get("quality_state", "VALID_REPORTED"),
                }
            )
    return result


def _number_input(inputs: dict[str, Any], key: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    value = inputs.get(key)
    if not _is_number(value):
        raise ValueError(f"{key} must be a finite number")
    result = float(value)
    if positive and result <= 0:
        raise ValueError(f"{key} must be greater than zero")
    if nonnegative and result < 0:
        raise ValueError(f"{key} must be nonnegative")
    return result


def _require_prerequisites(prerequisites: Any, required: dict[str, Any]) -> None:
    if not isinstance(prerequisites, dict):
        raise ValueError("prerequisites must be an object")
    for key, expected in required.items():
        if prerequisites.get(key) != expected:
            raise ValueError(f"prerequisite {key} must equal {expected!r}")


def _calculate_value(spec_id: str, inputs: dict[str, Any], prerequisites: Any) -> float:
    if spec_id == "REPURCHASE_AVG_PRICE":
        _require_prerequisites(prerequisites, {"same_event": True, "same_currency": True})
        return _number_input(inputs, "eligible_cash_consideration", nonnegative=True) / _number_input(inputs, "repurchased_shares", positive=True)
    if spec_id == "REPURCHASE_SHARE_RATIO":
        _require_prerequisites(prerequisites, {"same_security_class": True, "share_count_basis": "CLASS_BASIC"})
        return _number_input(inputs, "repurchased_class_shares", nonnegative=True) / _number_input(inputs, "pre_event_class_basic_shares", positive=True)
    if spec_id == "GROSS_ISSUANCE_RATIO":
        _require_prerequisites(prerequisites, {"same_security_class": True, "share_count_basis": "CLASS_BASIC", "gross_issuance_not_net": True})
        return _number_input(inputs, "gross_issued_class_shares", nonnegative=True) / _number_input(inputs, "pre_event_class_basic_shares", positive=True)
    if spec_id == "NET_SHARE_COUNT_CHANGE":
        _require_prerequisites(prerequisites, {"same_security_class": True, "pre_share_count_basis": "CLASS_BASIC", "post_share_count_basis": "CLASS_BASIC"})
        before = _number_input(inputs, "pre_basic_shares", positive=True)
        after = _number_input(inputs, "post_basic_shares", nonnegative=True)
        return (after - before) / before
    if spec_id == "REMAINING_AUTHORIZATION":
        _require_prerequisites(prerequisites, {"same_authorization": True, "same_currency": True, "authorization_scope_known": True, "supersession_state": "ACTIVE"})
        result = _number_input(inputs, "active_authorization", nonnegative=True) - _number_input(inputs, "cumulative_eligible_spend", nonnegative=True)
        if result < 0:
            raise ValueError("cumulative_eligible_spend exceeds active_authorization")
        return result
    if spec_id == "REMAINING_ATM_CAPACITY":
        _require_prerequisites(prerequisites, {"same_program": True, "same_unit": True, "supersession_state": "ACTIVE"})
        result = _number_input(inputs, "active_program_capacity", nonnegative=True) - _number_input(inputs, "cumulative_program_usage", nonnegative=True)
        if result < 0:
            raise ValueError("cumulative_program_usage exceeds active_program_capacity")
        return result
    if spec_id == "BTC_NET_FLOW":
        _require_prerequisites(prerequisites, {"same_period": True})
        return _number_input(inputs, "btc_bought", nonnegative=True) - _number_input(inputs, "btc_sold", nonnegative=True)
    if spec_id == "LIQUIDATION_PREFERENCE_RETIRED":
        _require_prerequisites(prerequisites, {"same_security_class": True, "terms_current": True})
        return _number_input(inputs, "retired_shares", nonnegative=True) * _number_input(inputs, "liquidation_preference_per_share", nonnegative=True)
    if spec_id == "DISTRIBUTION_RUN_RATE_REMOVED":
        _require_prerequisites(prerequisites, {"same_security_class": True, "terms_current": True, "output_semantics": "CURRENT_RUN_RATE_ONLY"})
        return _number_input(inputs, "retired_shares", nonnegative=True) * _number_input(inputs, "current_annual_distribution_per_share", nonnegative=True)
    if spec_id == "OPEN_MARKET_PARTICIPATION":
        _require_prerequisites(prerequisites, {"same_security": True, "same_execution_window": True, "open_market_channel_verified": True, "volume_scope_comparable": True})
        return _number_input(inputs, "verified_open_market_repurchased_shares", nonnegative=True) / _number_input(inputs, "comparable_consolidated_volume", positive=True)
    if spec_id == "FIXED_WINDOW_RETURN":
        _require_prerequisites(prerequisites, {"same_security": True, "corporate_action_adjustment_verified": True})
        return _number_input(inputs, "adjusted_end_price", positive=True) / _number_input(inputs, "adjusted_start_price", positive=True) - 1.0
    if spec_id == "BTC_EXCESS_RETURN":
        _require_prerequisites(prerequisites, {"same_window": True, "same_time_basis": True, "benchmark_security_id_verified": True})
        return _number_input(inputs, "security_return") - _number_input(inputs, "btc_return")
    if spec_id == "VOLUME_MULTIPLE":
        _require_prerequisites(prerequisites, {"same_volume_scope": True, "baseline_spec_approved": True, "window_spec_approved": True})
        return _number_input(inputs, "event_window_adv", nonnegative=True) / _number_input(inputs, "locked_baseline_adv", positive=True)
    raise ValueError(f"{spec_id} is not executable without a formally approved market lock")


def _calculate_requests(
    payload: dict[str, Any],
    blockers: list[dict[str, Any]],
    *,
    issuer_ids: set[str],
    security_ids: set[str],
    available_fact_ids: set[str],
    event_active_state: dict[str, bool],
) -> list[dict[str, Any]]:
    requests = payload.get("calculation_requests", [])
    if not isinstance(requests, list):
        _add_blocker(blockers, "CALCULATION_REQUESTS_INVALID", "CALCULATION", ["calculation_requests"], "calculation_requests must be a list.", ["provide a calculation request list"])
        return []
    result: list[dict[str, Any]] = []
    calculation_ids: set[str] = set()
    for index, request in enumerate(requests):
        label = f"calculation_requests[{index}]"
        if not isinstance(request, dict):
            _add_blocker(blockers, "CALCULATION_REQUEST_INVALID", "CALCULATION", [label], "Calculation request must be an object.", ["provide a valid calculation request"])
            continue
        calculation_id = request.get("calculation_id")
        spec_id = request.get("calculation_spec_id")
        affected_id = calculation_id if _is_id(calculation_id) else label
        if not _is_id(calculation_id) or spec_id not in FORMULA_READY_SPECS:
            _add_blocker(blockers, "CALCULATION_SPEC_NOT_APPROVED", "CALCULATION", [affected_id], "Calculation ID or approved formula spec is missing.", ["use a FORMULA_READY calculation_spec_id and stable calculation_id"])
            continue
        issuer_id = request.get("issuer_id")
        security_id = request.get("security_id")
        input_fact_ids = request.get("input_fact_ids")
        input_event_ids = request.get("input_event_ids")
        output_unit = request.get("output_unit")
        inputs = request.get("inputs")
        if not _is_id(issuer_id) or not isinstance(input_fact_ids, list) or not input_fact_ids or not all(_is_id(value) for value in input_fact_ids) or not isinstance(input_event_ids, list) or not input_event_ids or not all(_is_id(value) for value in input_event_ids) or not _is_id(output_unit) or not isinstance(inputs, dict):
            _add_blocker(blockers, "CALCULATION_INPUT_MISSING", "CALCULATION", [calculation_id], "Calculation identity, input facts, input events, output unit, or numeric inputs are incomplete.", ["provide issuer_id, input_fact_ids, input_event_ids, inputs, and output_unit"])
            continue
        if calculation_id in available_fact_ids or calculation_id in calculation_ids:
            _add_blocker(blockers, "FACT_ID_DUPLICATE", "CALCULATION", [calculation_id], "Calculation output ID duplicates another asset fact.", ["assign a unique calculation_id"])
            continue
        missing_fact_ids = sorted(set(input_fact_ids) - available_fact_ids)
        if missing_fact_ids:
            _add_blocker(blockers, "CALCULATION_INPUT_MISSING", "CALCULATION", [calculation_id, *missing_fact_ids], "Calculation references facts that are not present as verified overlay evidence.", ["include and verify every input fact"])
            continue
        unknown_event_ids = sorted(set(input_event_ids) - set(event_active_state))
        if unknown_event_ids:
            _add_blocker(blockers, "CALCULATION_INPUT_MISSING", "CALCULATION", [calculation_id, *unknown_event_ids], "Calculation references events that are not present as verified overlay evidence.", ["include and verify every input event"])
            continue
        inactive_event_ids = sorted(event_id for event_id in set(input_event_ids) if not event_active_state[event_id])
        if inactive_event_ids:
            _add_blocker(blockers, "SUPERSESSION_UNRESOLVED", "CALCULATION", [calculation_id, *inactive_event_ids], "Superseded events cannot participate in active calculations.", ["link calculation inputs to ACTIVE events"])
            continue
        if issuer_id not in issuer_ids:
            _add_blocker(blockers, "ISSUER_IDENTITY_UNRESOLVED", "CALCULATION", [calculation_id], "Calculation issuer_id is outside the verified fact scope.", ["resolve issuer identity and calculation scope"])
            continue
        if security_id is not None and security_id not in security_ids:
            _add_blocker(blockers, "SECURITY_IDENTITY_UNRESOLVED", "CALCULATION", [calculation_id], "Calculation security_id is outside the verified fact scope.", ["resolve security identity and calculation scope"])
            continue
        source_refs = request.get("source_refs")
        normalized_sources: list[dict[str, Any]] = []
        if isinstance(source_refs, list) and source_refs:
            for source_ref in source_refs:
                normalized = _normalize_source_ref(source_ref, blockers, calculation_id, blocker_scope="CALCULATION")
                if normalized is not None:
                    normalized_sources.append(normalized)
        if not normalized_sources or len(normalized_sources) != len(source_refs or []):
            _add_blocker(blockers, "CALCULATION_INPUT_MISSING", "CALCULATION", [calculation_id], "Every deterministic calculation input must retain a verified source reference.", ["provide valid source_refs for all inputs"])
            continue
        if spec_id in MARKET_LOCKED_SPECS:
            market_blocked = False
            window_spec_id = request.get("window_spec_id")
            if window_spec_id not in APPROVED_MARKET_WINDOW_SPEC_IDS:
                market_blocked = True
                _add_blocker(blockers, "WINDOW_SPEC_NOT_APPROVED", "CALCULATION", [calculation_id], f"{spec_id} has no approved current-main observation-window lock.", ["approve and register the window_spec_id"])
            if not all(source_ref["source_id"] in APPROVED_MARKET_SOURCE_IDS for source_ref in normalized_sources):
                market_blocked = True
                _add_blocker(blockers, "PRICE_OR_VOLUME_UNVERIFIABLE", "CALCULATION", [calculation_id], f"{spec_id} has no approved current-main market-data source lock.", ["approve and register the market source_id"])
            if spec_id == "OPEN_MARKET_PARTICIPATION":
                prerequisites = request.get("prerequisites")
                if not isinstance(prerequisites, dict) or prerequisites.get("open_market_channel_verified") is not True:
                    market_blocked = True
                    _add_blocker(blockers, "ACTION_CHANNEL_UNKNOWN", "CALCULATION", [calculation_id], "Open-market execution channel is not verified.", ["separate and verify the open-market transaction channel"])
                if not isinstance(prerequisites, dict) or prerequisites.get("volume_scope_comparable") is not True:
                    market_blocked = True
                    _add_blocker(blockers, "MARKET_VOLUME_SCOPE_MISMATCH", "CALCULATION", [calculation_id], "Issuer transactions and market volume do not have a verified comparable scope.", ["align security, execution window, and consolidated-volume scope"])
            if market_blocked:
                continue
        try:
            value = _calculate_value(spec_id, inputs, request.get("prerequisites"))
        except ValueError as exc:
            code = "SHARE_COUNT_BASIS_MISMATCH" if spec_id in {"REPURCHASE_SHARE_RATIO", "GROSS_ISSUANCE_RATIO", "NET_SHARE_COUNT_CHANGE"} and "basis" in str(exc) else "CALCULATION_PREREQUISITE_UNMET"
            _add_blocker(blockers, code, "CALCULATION", [calculation_id], str(exc), ["supply verified, semantically aligned formula inputs"])
            continue
        result.append(
            {
                "asset_fact_id": calculation_id,
                "overlay_id": OVERLAY_ID,
                "overlay_type": OVERLAY_TYPE,
                "fact_kind": "DETERMINISTIC_CALCULATION",
                "issuer_id": issuer_id,
                "security_id": security_id,
                "fact_type": spec_id,
                "value": value,
                "unit": output_unit,
                "origin": "DETERMINISTIC",
                "input_fact_ids": sorted(set(input_fact_ids)),
                "input_event_ids": sorted(set(input_event_ids)),
                "calculation_spec_id": spec_id,
                "source_refs": normalized_sources,
                "quality_state": "VALID_DETERMINISTIC",
                "causal_interpretation": False,
            }
        )
        calculation_ids.add(calculation_id)
    return result


def _normalize_declared_blockers(section: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    for index, item in enumerate(section["items"]):
        label = f"reflexivity_blockers[{index}]"
        if not isinstance(item, dict):
            _add_blocker(blockers, "BLOCKER_INVALID", "OVERLAY", [label], "Declared blocker must be an object.", ["provide a structured blocker"])
            continue
        code = item.get("code") or item.get("reason_code")
        scope = item.get("scope")
        affected_ids = item.get("affected_ids")
        required = item.get("required_to_clear")
        reason = item.get("reason")
        if not _is_id(code) or scope not in BLOCKER_SCOPES or not isinstance(affected_ids, list) or not isinstance(required, list) or not isinstance(reason, str) or not reason:
            _add_blocker(blockers, "BLOCKER_INVALID", "OVERLAY", [label], "Declared blocker fields are incomplete or invalid.", ["provide code, scope, affected_ids, reason, and required_to_clear"])
            continue
        _add_blocker(blockers, code, scope, affected_ids, reason, required)


def _coverage_state(*sections: dict[str, Any]) -> str:
    states = {section["coverage_state"] for section in sections}
    if "BLOCKED" in states or "NOT_EVALUATED" in states:
        return "BLOCKED"
    if "PARTIAL" in states:
        return "PARTIAL"
    return "COMPLETE"


def _section_state(coverage_state: str, blockers: list[dict[str, Any]], scopes: set[str]) -> str:
    if any(item["scope"] in scopes or item["scope"] == "OVERLAY" for item in blockers):
        return "BLOCKED"
    if coverage_state == "COMPLETE":
        return "READY"
    if coverage_state == "PARTIAL":
        return "PARTIAL"
    if coverage_state == "NOT_EVALUATED":
        return "NOT_EVALUATED"
    return "BLOCKED"


def build_reflexivity_overlay(
    reflexivity_input: dict[str, Any] | None,
    *,
    source_gate_blocked_reasons: list[Any] | None = None,
) -> dict[str, Any]:
    """Validate and calculate the evidence-only issuer/market reflexivity overlay.

    The return value maps into the existing Evidence Pack V0.2 generic sections.
    It never emits a score, asset role, capital strategy, or external action.
    """

    blockers: list[dict[str, Any]] = []
    for reason in sorted({value for value in (source_gate_blocked_reasons or []) if _is_id(value)}):
        _add_blocker(
            blockers,
            reason,
            "SOURCE_GATE",
            ["source_gate"],
            "Source Gate reported a blocking reason.",
            ["clear the Source Gate blocker"],
        )

    if not isinstance(reflexivity_input, dict):
        _add_blocker(
            blockers,
            "REFLEXIVITY_INPUT_MISSING",
            "OVERLAY",
            [OVERLAY_ID],
            "No reflexivity evidence input was supplied; absence cannot be treated as no issuer action or no market response.",
            ["provide all four explicit reflexivity input sections"],
        )
        blockers = _dedupe_blockers(blockers)
        return {
            "asset_facts": {
                "section_state": "BLOCKED",
                "coverage_state": "BLOCKED",
                "reason_code": "REFLEXIVITY_INPUT_MISSING",
                "overlay_id": OVERLAY_ID,
                "overlay_type": OVERLAY_TYPE,
                "items": [],
            },
            "decision_relevant_events": {
                "section_state": "BLOCKED",
                "coverage_state": "BLOCKED",
                "reason_code": "REFLEXIVITY_INPUT_MISSING",
                "overlay_id": OVERLAY_ID,
                "overlay_type": OVERLAY_TYPE,
                "items": [],
            },
            "blockers": {
                "section_state": "BLOCKED",
                "reason_code": "REFLEXIVITY_INPUT_MISSING",
                "overlay_id": OVERLAY_ID,
                "overlay_type": OVERLAY_TYPE,
                "items": blockers,
            },
        }

    _scan_prohibited(reflexivity_input, blockers)
    if reflexivity_input.get("external_action_authority", EXTERNAL_ACTION_AUTHORITY) != EXTERNAL_ACTION_AUTHORITY:
        _add_blocker(blockers, "EXTERNAL_ACTION_AUTHORITY_NOT_NONE", "OVERLAY", [OVERLAY_ID], "External Action Authority must remain NONE.", ["set external_action_authority to NONE"])

    issuer_facts = _read_section(reflexivity_input, "issuer_facts", blockers, blocker_scope="FACT")
    issuer_events = _read_section(reflexivity_input, "issuer_events", blockers, blocker_scope="EVENT")
    market_reactions = _read_section(reflexivity_input, "market_reaction_facts", blockers, blocker_scope="FACT")
    declared_blockers = _read_section(reflexivity_input, "reflexivity_blockers", blockers, blocker_scope="OVERLAY")

    asset_items = _normalize_issuer_facts(issuer_facts, blockers)
    event_items = _normalize_events(issuer_events, blockers)
    asset_items.extend(_normalize_market_reactions(market_reactions, blockers))
    available_fact_ids = {item["asset_fact_id"] for item in asset_items}
    event_active_state = {
        item["event_id"]: item["active_for_calculation"]
        for item in event_items
    }
    calculation_issuer_ids = {
        value
        for value in issuer_facts["scope"].get("issuer_ids", [])
        if _is_id(value)
    }
    calculation_security_ids = {
        value
        for value in issuer_facts["scope"].get("security_ids", [])
        if _is_id(value)
    }
    asset_items.extend(
        _calculate_requests(
            reflexivity_input,
            blockers,
            issuer_ids=calculation_issuer_ids,
            security_ids=calculation_security_ids,
            available_fact_ids=available_fact_ids,
            event_active_state=event_active_state,
        )
    )
    _normalize_declared_blockers(declared_blockers, blockers)

    blockers = _dedupe_blockers(blockers)
    asset_coverage = _coverage_state(issuer_facts, market_reactions)
    event_coverage = issuer_events["coverage_state"]
    asset_items = sorted(asset_items, key=lambda item: item["asset_fact_id"])
    event_items = sorted(event_items, key=lambda item: item["event_id"])

    asset_section: dict[str, Any] = {
        "section_state": _section_state(asset_coverage, blockers, {"FACT", "CALCULATION"}),
        "coverage_state": asset_coverage,
        "overlay_id": OVERLAY_ID,
        "overlay_type": OVERLAY_TYPE,
        "items": asset_items,
    }
    event_section: dict[str, Any] = {
        "section_state": _section_state(event_coverage, blockers, {"EVENT"}),
        "coverage_state": event_coverage,
        "overlay_id": OVERLAY_ID,
        "overlay_type": OVERLAY_TYPE,
        "items": event_items,
    }
    blocker_section: dict[str, Any] = {
        "section_state": "BLOCKED" if blockers else "READY",
        "overlay_id": OVERLAY_ID,
        "overlay_type": OVERLAY_TYPE,
        "items": blockers,
    }
    if not asset_items and asset_section["section_state"] == "READY":
        asset_section["empty_reason"] = EMPTY_REASON
    if not event_items and event_section["section_state"] == "READY":
        event_section["empty_reason"] = EMPTY_REASON
    if not blockers:
        blocker_section["empty_reason"] = EMPTY_REASON
    else:
        blocker_section["reason_code"] = "REFLEXIVITY_BLOCKED"

    overlay_for_hash = {
        "asset_facts": asset_section,
        "decision_relevant_events": event_section,
        "blockers": blocker_section,
    }
    overlay_hash = _sha256(overlay_for_hash)
    for section in overlay_for_hash.values():
        section["overlay_hash"] = overlay_hash
    return overlay_for_hash
