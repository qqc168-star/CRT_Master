"""TFTC processed research intake into existing asset facts; no formal L3 input."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.request
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .change_engine import HORIZONS_MS

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "TFTC_US_SPOT_BTC_ETF_FLOW"
URL = "https://www.tftc.io/bitcoin-etf-flows/data.json"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
FLOW = "BTC_ETF_NET_FLOW_USD"
BREADTH = "BTC_ETF_FLOW_BREADTH"
BALANCE = "BTC_ETF_BALANCE_BTC"


def _contract(name):
    return json.loads((ROOT / "research" / name).read_text(encoding="utf-8"))


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def capture(path: Path):
    """Archive exact JSON bytes and actual retrieval clock, without credentials."""
    registry = _contract("CRT_EXTERNAL_STRUCTURAL_DEMAND_SOURCE_REGISTRY_V0.1.json")
    source = next(s for s in registry["sources"] if s["source_id"] == SOURCE)
    if source["role"] != "PRIMARY_PROCESSED_FLOW_SOURCE" or source["url"] != URL:
        raise ValueError("TFTC_SOURCE_ROLE_OR_URL_NOT_APPROVED")
    with urllib.request.urlopen(URL, timeout=30) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError("TFTC_TRANSPORT_NOT_LOCKED")
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000 or response.headers.get_content_type() != "application/json":
            raise ValueError("TFTC_RESPONSE_INVALID")
    envelope = {"source_id": SOURCE, "source_url": URL,
                "retrieved_at_ms": int(time.time()*1000), "evidence_hash": _hash(raw),
                "raw_json": raw.decode("utf-8")}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite evidence from an earlier retrieval.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(envelope, handle, ensure_ascii=False)
    return envelope


def normalize(envelope, *, as_of_ms):
    if not isinstance(envelope, dict):
        raise ValueError("TFTC_ARCHIVE_REQUIRED")
    retrieved = envelope.get("retrieved_at_ms")
    if (envelope.get("source_id") != SOURCE or envelope.get("source_url") != URL
            or type(retrieved) is not int or not 0 < retrieved <= as_of_ms):
        raise ValueError("TFTC_PROVENANCE_OR_VISIBILITY_INVALID")
    if not isinstance(envelope.get("raw_json"), str):
        raise ValueError("TFTC_RAW_JSON_REQUIRED")
    raw = envelope["raw_json"].encode("utf-8")
    if _hash(raw) != envelope.get("evidence_hash"):
        raise ValueError("TFTC_RAW_HASH_MISMATCH")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("TFTC_JSON_OBJECT_REQUIRED")
    if (data.get("units") != "USD" or data.get("license") != LICENSE
            or not data.get("sources") or not data.get("attribution")):
        raise ValueError("TFTC_UNIT_LICENSE_PROVENANCE_INVALID")
    profiles = _contract("CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json")["decisions"]["US_SPOT_BTC_ETP_POINT_IN_TIME"]["universe"]["members"]
    members = {p["ticker"]: date.fromisoformat(p["membership_effective_from"]) for p in profiles}
    calendar = _contract("CRT_ETP_PROSPECTIVE_CAPTURE_CONTRACT_V0.1.json")["market_calendar"]
    closed = set(calendar["full_close_dates"])
    def sessions(start, end):
        if start < date.fromisoformat(calendar["valid_from"]) or end > date.fromisoformat(calendar["valid_through"]):
            raise ValueError("MARKET_CALENDAR_OUT_OF_RANGE")
        return [start+timedelta(days=i) for i in range((end-start).days+1)
                if (start+timedelta(days=i)).weekday() < 5
                and (start+timedelta(days=i)).isoformat() not in closed]
    days = data.get("days")
    if not isinstance(days, list) or not days:
        raise ValueError("TFTC_HISTORY_MISSING")
    rows = {}
    for row in days:
        if not isinstance(row, dict):
            raise ValueError("TFTC_ROW_OBJECT_REQUIRED")
        day = date.fromisoformat(row["date"])
        if day in rows or not isinstance(row.get("perEtfUsd"), (dict, type(None))):
            raise ValueError("TFTC_SCHEMA_OR_DUPLICATE_DATE_INVALID")
        values = row["perEtfUsd"] or {}
        if any(v is not None and not _number(v) for v in values.values()):
            raise ValueError("TFTC_NONFINITE_OR_NONNUMERIC_FLOW")
        rows[day] = row
    latest = date.fromisoformat(data["updatedThrough"])
    if not sessions(latest, latest):
        raise ValueError("TFTC_NON_SESSION_DATE")
    if latest != max(rows) or latest >= datetime.fromtimestamp(retrieved/1000, timezone.utc).date():
        raise ValueError("TFTC_COMPLETED_SESSION_REQUIRED")
    # Latest expected completed session before the current UTC date. No stale carry-forward.
    today = datetime.fromtimestamp(as_of_ms/1000, timezone.utc).date()
    expected = sessions(today-timedelta(days=10), today-timedelta(days=1))[-1]
    stale = latest != expected
    window_start = latest-timedelta(days=29)
    excluded = sorted({t for d, row in rows.items() if window_start <= d <= latest
                       for t in (row["perEtfUsd"] or {}) if t not in members})
    if excluded:
        raise ValueError("TFTC_CURRENT_WINDOW_UNIVERSE_CONFLICT")
    common = {"source_id": SOURCE, "source_url": URL, "retrieved_at_ms": retrieved,
              "evidence_hash": envelope["evidence_hash"], "source_as_of_date": latest.isoformat(),
              "source_as_of_precision": "DATE", "license": LICENSE,
              "attribution": data["attribution"], "upstream_sources": data["sources"],
              "availability_semantics": "RETRIEVAL_VINTAGE_AUDIT_NOT_HISTORICAL_PUBLICATION_PROOF",
              "claim_scope": "DECLARED_CRT_ETF_BASKET_RESEARCH_ONLY_NOT_FORMAL_L3",
              "action_output": "NONE", "production": "NOT_APPROVED", "external_action_authority": "NONE"}
    horizons = {}
    for label in ("1D", "7D", "30D"):
        duration = HORIZONS_MS[label.lower()] // HORIZONS_MS["1d"]
        required = sessions(latest-timedelta(days=duration-1), latest)
        expected_scope = {t for t, d in members.items() if d <= latest}
        scope = set(expected_scope)
        for day in required:
            values = (rows.get(day, {}).get("perEtfUsd") or {})
            scope &= {t for t, d in members.items() if d <= day and _number(values.get(t))}
        scope = sorted(scope)
        state = "BLOCKED" if stale or not scope else "COMPLETE" if set(scope) == expected_scope else "PARTIAL"
        value = None if state == "BLOCKED" else math.fsum(rows[d]["perEtfUsd"][t] for d in required for t in scope)
        horizons[label] = {"coverage_state": state, "value": value, "unit": "USD",
            "scope_ids": scope, "missing_fund_ids": sorted(expected_scope-set(scope)),
            "session_dates": [d.isoformat() for d in required],
            "window_semantics": "SUM_REPORTED_FLOWS_OVER_CALENDAR_DAY_WINDOW_CONSTANT_FUND_SCOPE",
            "reason": "STALE_SOURCE" if stale else "MISSING_COMPARABLE_FUND_HISTORY" if state != "COMPLETE" else None}
    scope = horizons["1D"]["scope_ids"]
    state = horizons["1D"]["coverage_state"]
    values = rows[latest]["perEtfUsd"] or {}
    breadth = {"coverage_state": state, "scope_ids": scope,
               "positive_fund_count": None if state == "BLOCKED" else sum(values[t] > 0 for t in scope),
               "negative_fund_count": None if state == "BLOCKED" else sum(values[t] < 0 for t in scope),
               "reported_zero_fund_count": None if state == "BLOCKED" else sum(values[t] == 0 for t in scope)}
    return {"metadata": common, "horizons": horizons, "breadth": breadth,
            "provider_aggregate_usd": rows[latest].get("netFlowUsd"),
            "excluded_provider_fund_ids": excluded,
            "balance": {"coverage_state": "BLOCKED", "current_level": None,
                        "7D_delta": None, "30D_delta": None, "reason": "RELIABLE_FREE_BTC_BALANCE_HISTORY_UNAVAILABLE"},
            "farside": {"role": "NON_BLOCKING_CROSS_CHECK", "state": "LOCAL_FETCH_BLOCKED"}}


def add_to_pack(pack, envelope):
    """Append only to the contract's existing facts/blockers sections before pack hashing."""
    try:
        result = normalize(envelope, as_of_ms=pack["generated_at_ms"])
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        result = {"error": str(exc)}
    facts, blockers = pack["asset_facts"], pack["blockers"]
    def block(metric, reason):
        blockers["items"].append({"blocker_id": SOURCE+":"+metric, "code": reason,
            "scope": "METRIC", "affected_ids": [metric], "reason": reason,
            "coverage_state": "BLOCKED",
            "required_to_clear": ["verified comparable source evidence"], "source_id": SOURCE,
            **({k: result["metadata"][k] for k in ("retrieved_at_ms", "evidence_hash")}
               if "metadata" in result else {})})
    if "error" in result:
        for metric in (FLOW, BREADTH, BALANCE):
            block(metric, result["error"])
    else:
        common = {"asset": "BTC", **result["metadata"]}
        for metric, evidence in ((FLOW, result["horizons"]), (BREADTH, result["breadth"])):
            states = [h["coverage_state"] for h in result["horizons"].values()] if metric == FLOW else [evidence["coverage_state"]]
            coverage = "COMPLETE" if all(s == "COMPLETE" for s in states) else "BLOCKED" if all(s == "BLOCKED" for s in states) else "PARTIAL"
            facts["items"].append({**common, "asset_fact_id": SOURCE+":"+metric,
                "fact_type": metric, "metric_id": metric, "evidence": evidence,
                "coverage_state": coverage,
                "limitation": "PARTIAL_IS_SCOPED_NOT_TOTAL;BALANCE_IS_NOT_DERIVED_FROM_FLOW_OR_AUM"})
        for horizon, value in result["horizons"].items():
            if value["coverage_state"] != "COMPLETE":
                block(FLOW+":"+horizon, value["reason"])
        block(BALANCE, result["balance"]["reason"])
        if result["breadth"]["coverage_state"] != "COMPLETE":
            block(BREADTH, result["horizons"]["1D"]["reason"])
    for section in (facts, blockers):
        if "overlay_hash" in section:
            section["upstream_overlay_hash"] = section.pop("overlay_hash")
        if section["items"]:
            section.pop("empty_reason", None)
    if any(f.get("source_id") == SOURCE and f.get("coverage_state") != "BLOCKED"
           for f in facts["items"]):
        facts["section_state"] = "PARTIAL"
        facts["coverage_state"] = "PARTIAL"
        if "reason_code" in facts:
            facts["upstream_reason_code"] = facts["reason_code"]
        facts["reason_code"] = "BTC_ETF_FLOW_AVAILABLE_BALANCE_BLOCKED"
    blockers["section_state"] = "BLOCKED"


def compact_for_bridge(pack):
    facts = [deepcopy(f) for f in pack.get("asset_facts", {}).get("items", []) if f.get("source_id") == SOURCE]
    blockers = [deepcopy(b) for b in pack.get("blockers", {}).get("items", []) if b.get("source_id") == SOURCE]
    if not facts and not blockers:
        return None
    # Column projection keeps values, coverage and scope; exact daily dates and
    # full attribution remain in the hash-linked pack, not repeated in the bridge.
    if not facts:
        return {"source_id": SOURCE, "blockers": blockers, "formal_model_input": False}
    flow = next(f for f in facts if f["metric_id"] == FLOW)
    breadth = next(f for f in facts if f["metric_id"] == BREADTH)["evidence"]
    scopes = []
    def scope_index(row):
        scope = row["scope_ids"]
        if scope not in scopes:
            scopes.append(scope)
        return scopes.index(scope)
    rows = {h: [r["value"], r["coverage_state"], scope_index(r)]
            for h, r in flow["evidence"].items()}
    result = {k: flow[k] for k in ("source_id", "retrieved_at_ms", "evidence_hash", "source_as_of_date")}
    result.update({
        "scope_ids_by_index": scopes,
        "flow_columns": ["USD", "coverage_state", "scope_index"],
        FLOW: rows,
        "breadth_columns": ["positive_fund_count", "negative_fund_count", "reported_zero_fund_count", "coverage_state", "scope_index"],
        BREADTH: [breadth[k] for k in ("positive_fund_count", "negative_fund_count", "reported_zero_fund_count", "coverage_state")]+[scope_index(breadth)],
        BALANCE: "BLOCKED:RELIABLE_FREE_BTC_BALANCE_HISTORY_UNAVAILABLE",
        "semantics": "Calendar-window sums; research only; retrieval vintage, not historical publication proof; balance not derived from flow/AUM/price.",
        "farside": "NON_BLOCKING:LOCAL_FETCH_BLOCKED",
    })
    gaps = {h: {"missing_fund_ids": r["missing_fund_ids"], "reason": r["reason"]}
            for h, r in flow["evidence"].items() if r["coverage_state"] != "COMPLETE"}
    if gaps:
        result["flow_gaps"] = gaps
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    envelope = capture(args.capture)
    print(json.dumps(normalize(envelope, as_of_ms=envelope["retrieved_at_ms"]), indent=2))


if __name__ == "__main__":
    main()
