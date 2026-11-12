from __future__ import annotations

import math
from copy import deepcopy
from typing import Any
import hashlib
import json
import time

VALID_QUALITY_STATES = {"VALID_REPORTED", "VALID_DETERMINISTIC"}


def guard_company_source_versions(store, *, ct_inputs, valuation_inputs, archive, as_of_ms, require_archive=False):
    """Public issuer intake: reparse original archives before advancing versions.

    Versions live in the existing immutable ObservationStore, not yesterday's
    pack. Stored values are comparison evidence only, never current CT inputs.
    Normalized calculation-only callers cannot establish source authority.
    """
    from .issuer_ratio_market_health_source import build_archived_issuer_ct_inputs
    from .treasury_company_ct import ISSUERS, validate_pit_replay
    supplied = deepcopy(ct_inputs or {})
    try:
        verified = build_archived_issuer_ct_inputs(archive, as_of_ms=as_of_ms) if archive is not None else {}
    except (OSError,ValueError,UnicodeError):
        # An unreadable company archive is not a BTC market-source failure.
        verified = {a:dict(issuer_id=i,as_of_ms=as_of_ms,source_binding={"observations":[],
            "blockers":[dict(claim="SEC_ARCHIVE",code="SEC_ARCHIVE_REVALIDATION_FAILED")]}) for a,i in ISSUERS.items()}
    if archive is not None:
        if ct_inputs is not None:
            raise ValueError("SUPPLY_ARCHIVE_OR_NORMALIZED_CT_NOT_BOTH")
        supplied = deepcopy(verified)
    valuations = deepcopy(valuation_inputs)
    reports = {}
    pending = []
    fields = ("btc_holdings", "diluted_shares", "usd_cash_usd", "usd_reserve_usd")

    def field_name(asset, key):
        return "usd_cash_usd" if key == "cash_and_cash_equivalents_usd" else key

    def records(data):
        return (list(data.get("asset_history") or [])
            + [data[k] for k in ("burden_current", "burden_previous") if isinstance(data.get(k), dict)]
            + list((data.get("source_binding") or {}).get("observations") or []))

    def official_claim(value):
        if isinstance(value, dict):
            return "source_binding" in value or any(official_claim(v) for v in value.values())
        if isinstance(value, list): return any(official_claim(v) for v in value)
        return isinstance(value, str) and "sec.gov/" in value

    # Serialize the read/compare/append operation with the existing SQLite
    # transaction. A second caller must see the first caller's committed version.
    store.conn.execute("BEGIN IMMEDIATE")
    try:
        for asset, issuer in ISSUERS.items():
            kind = "issuer_source_versions:" + issuer
            previous = store.latest_research_event(kind) or {"issuer_id":issuer,"fields":{}}
            if previous.get("issuer_id") != issuer or not isinstance(previous.get("fields"),dict):
                raise ValueError("ISSUER_SOURCE_VERSION_HISTORY_INVALID")
            prior = previous["fields"]
            data = supplied.get(asset)
            needs_guard = (archive is not None or bool(prior) or official_claim(data)
                or (require_archive and (data is not None or asset in (valuations or {}))))
            if not needs_guard:
                # Existing normalized research/calculation API is not a source
                # verification entry point and never writes a high watermark.
                continue
            candidates = {}
            for record in records(verified.get(asset, {})):
                if validate_pit_replay(record,issuer_id=issuer,replay_at=as_of_ms,mode="AUDIT_REPLAY")["state"] != "AVAILABLE":
                    continue
                proof = record.get("source_evidence") or {}
                digest = proof.get("raw_sha256")
                if not isinstance(digest,str) or len(digest)!=64: continue
                values = {k:record[k] for k in fields if k in record}
                values.update(record.get("reported_fields") or {})
                for key,value in values.items():
                    key = field_name(asset,key)
                    if key not in fields or type(value) not in (int,float) or not math.isfinite(value) or value<0:
                        continue
                    if key in {"btc_holdings","diluted_shares"} and value<=0: continue
                    candidates.setdefault(key,[]).append(dict(value=value,
                        effective_time=record["effective_time"], disclosure_time=record["disclosure_time"],
                        first_seen_time=record["first_seen_time"],retrieval_time=record["retrieval_time"],
                        source_ref=record["source_ref"],raw_sha256=digest,accession=proof.get("accession")))
            incoming = {field_name(asset,k) for r in records(data or {})
                for k in set(r) | set(r.get("reported_fields") or {}) if field_name(asset,k) in fields}
            valuation_attempt=(valuations or {}).get(asset) or {}
            if valuation_attempt.get("mnav_history") or valuation_attempt.get("asset_history"):
                incoming.update({"btc_holdings","diluted_shares"})
            blocked = {}
            updated = deepcopy(prior)
            for field in sorted(incoming | set(candidates)):
                rows = candidates.get(field,[])
                if not rows:
                    blocked[field] = "ISSUER_SOURCE_NOT_ARCHIVE_VERIFIED"
                    continue
                at = max(r["effective_time"] for r in rows)
                latest = [r for r in rows if r["effective_time"]==at]
                old = prior.get(field)
                if old and at < old["effective_time"]:
                    blocked[field] = "ISSUER_SOURCE_REGRESSION_BLOCKED"
                    continue
                conflict = len({r["value"] for r in latest})>1 or (old and at==old["effective_time"]
                    and (old.get("conflicted") or any(r["value"]!=old["value"] for r in latest)))
                if conflict:
                    blocked[field] = "ISSUER_SAME_DATE_CONFLICT_CORRECTION_UNPROVEN"
                    # Caller flags/names cannot authorize corrections. Keep the
                    # authentic conflicting source versions for explicit review.
                    updated[field] = dict(old or latest[0],conflicted=True,
                        conflicting_sources=sorted({r["raw_sha256"] for r in latest}
                            | set((old or {}).get("conflicting_sources",[]))))
                elif not old or at>old["effective_time"]:
                    updated[field] = max(latest,key=lambda r:(r["disclosure_time"],r["raw_sha256"]))
            source_blocked = dict(blocked)
            # A freshly parsed reported snapshot may be newer than the subset
            # eligible for CT (e.g. an unresolved AFDS scope). Do not let CT
            # silently select an older comparable pair instead.
            ct_stale = {}
            if data is not None:
                for field in fields:
                    engine_rows = data.get("asset_history",[]) if field in {"btc_holdings","diluted_shares"} else [data.get("burden_current") or {}]
                    times = [r["effective_time"] for r in engine_rows if r.get(field) is not None and type(r.get("effective_time")) is int]
                    if times and field in updated and max(times)<updated[field]["effective_time"]:
                        ct_stale[field] = "CURRENT_CT_BEHIND_VERIFIED_SOURCE_VERSION"
            blocked.update(ct_stale)
            if data is None and not valuation_attempt:
                state,reason = "NOT_RUN","ISSUER_SOURCE_NOT_REFRESHED_NO_CACHED_VALUES_REUSED"
            else:
                state,reason = (("BLOCKED","ISSUER_FIELDS_QUARANTINED") if blocked else
                    ("SOURCE_BOUND","SEC_ARCHIVE_REPARSED") if candidates else
                    ("BLOCKED","NO_ARCHIVE_VERIFIED_ISSUER_FIELDS"))
            reports[asset] = dict(issuer_id=issuer,state=state,reason=reason,blocked_fields=blocked,
                version_validated_at_ms=previous.get("validated_at_ms"),
                source_blockers=deepcopy((data or {}).get("source_binding",{}).get("blockers",[])),
                watermarks={k:{f:v.get(f) for f in ("effective_time","raw_sha256","accession","conflicted")}
                    for k,v in updated.items()})
            if updated != prior:
                payload = dict(issuer_id=issuer,fields=updated,validated_at_ms=int(time.time()*1000))
                reports[asset]["version_validated_at_ms"]=payload["validated_at_ms"]
                digest = hashlib.sha256(json.dumps(updated,sort_keys=True).encode()).hexdigest()
                pending.append((kind+":"+digest,kind,payload))
            if blocked and data is not None:
                history = deepcopy(records(data))
                normalized = list(data.get("asset_history") or []) + [data[k] for k in ("burden_current","burden_previous") if isinstance(data.get(k),dict)]
                for record in normalized:
                    for key in fields:
                        if key in blocked and key in record: record[key]=None
                for record in (data.get("source_binding") or {}).get("observations",[]):
                    for key in fields:
                        if key in source_blocked and key in record: record[key]=None
                    for key in list(record.get("reported_fields") or {}):
                        if field_name(asset,key) in source_blocked: record["reported_fields"][key]=None
                data.setdefault("source_binding",{}).setdefault("historical_observations",[]).extend(history)
                data["source_binding"]["historical_use"]="RESEARCH_ONLY_NOT_CURRENT_INPUT"
                data["source_binding"].setdefault("blockers",[]).extend(
                    dict(claim=field,code=code) for field,code in blocked.items())
                if set(blocked)&{"btc_holdings","diluted_shares"}:
                    data["price_financing_state"]=None
            # A persisted version does not authorize supplied valuation inputs.
            # Current corporate components must match today's reverified raw
            # evidence; neither metadata labels nor a cached version suffice.
            if isinstance(valuations,dict) and asset in valuations:
                def component_ok(row,field):
                    proof=(row or {}).get("input_evidence",{}).get(field,{})
                    raw_hash=proof.get("raw_sha256") or (proof.get("source_evidence") or {}).get("raw_sha256")
                    matches=any(r["value"]==row.get(field) and r["effective_time"]==proof.get("effective_time")
                        and r["raw_sha256"]==raw_hash for r in candidates.get(field,[])) and field not in source_blocked
                    if field=="diluted_shares":
                        # A reported number cannot certify a caller-invented
                        # COMPLETE dilution scope using that filing's hash.
                        matches = matches and any(r.get("dilution_scope") and r.get("coverage_state")=="COMPLETE"
                            and r.get("dilution_scope")==proof.get("dilution_scope")
                            and r.get("basis_ref")==proof.get("basis_ref")
                            for r in verified.get(asset,{}).get("asset_history",[]))
                    return matches
                val=valuations[asset]
                historical=deepcopy(val.get("mnav_history",[]))
                val["mnav_history"]=[r for r in val.get("mnav_history",[]) if isinstance(r,dict)
                    and all(component_ok(r,f) for f in ("btc_holdings","diluted_shares"))]
                latest=max((r.get("effective_time",0) for r in val["mnav_history"]),default=0)
                if any(latest<updated[f]["effective_time"] for f in ("btc_holdings","diluted_shares") if f in updated):
                    val["mnav_history"]=[]
                if set(blocked)&{"btc_holdings","diluted_shares"} or archive is None:
                    val["asset_history"]=[]
                if historical != val["mnav_history"]:
                    reports[asset]["historical_valuation_observations"]=historical
                    reports[asset]["historical_use"]="RESEARCH_ONLY_NOT_CURRENT_FORMAL_VALUATION"
            for other in (valuations or {}).values():
                if blocked and (other.get("benchmark") or {}).get("asset_id")==asset:
                    other["benchmark"]["history"]=[]
        store.record_research_events(pending)
        store.conn.commit()
    except Exception:
        store.conn.rollback()
        raise
    return (supplied if ct_inputs is not None or archive is not None else None),valuations,reports


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
    if coverage not in {"COMPLETE", "PARTIAL"}:
        return {"state": "BLOCKED", "reason": "ASSET_FACT_SECTION_BLOCKED", "items": []}

    raw_items = section.get("items")
    if not isinstance(raw_items, list):
        return {"state": "BLOCKED", "reason": "ASSET_FACT_ITEMS_MISSING", "items": []}

    # A section can be blocked by an unrelated claim. Only explicit scoped
    # blockers may be excluded; unknown/global blockers remain fail closed.
    blocker_section = overlay.get("blockers", {})
    blockers = blocker_section.get("items", []) if isinstance(blocker_section, dict) else None
    if not isinstance(blockers, list) or (
        section.get("section_state") == "BLOCKED" and not blockers
    ):
        return {"state": "BLOCKED", "reason": "UNSCOPED_FACT_BLOCKER", "items": []}
    selected_ids = {
        raw.get("asset_fact_id") for raw in raw_items
        if isinstance(raw, dict) and raw.get("fact_type") == fact_type
        and (issuer_id is None or raw.get("issuer_id") == issuer_id)
        and (security_id is None or raw.get("security_id") == security_id)
    }
    claim_ids = selected_ids | {fact_type, issuer_id, security_id, "issuer_facts", "asset_facts"}
    for blocker in blockers:
        if not isinstance(blocker, dict):
            return {"state": "BLOCKED", "reason": "INVALID_FACT_BLOCKER", "items": []}
        scope = blocker.get("scope")
        affected = blocker.get("affected_ids")
        if scope in {"EVENT", "JUDGMENT"}:
            continue
        if (scope not in {"FACT", "CALCULATION"} or not isinstance(affected, list)
                or not affected or any(not isinstance(x, str) for x in affected)
                or claim_ids.intersection(affected)):
            return {"state": "BLOCKED", "reason": "CLAIM_SCOPED_FACT_BLOCKED", "items": []}

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
