"""Typed PRE/POST research records in ObservationStore, not a forecast model.

Hashes prove content integrity, not market/source truth or cloud accessibility.
No collector, scheduler, model, notification or trading entry point is invoked.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time
import hashlib
import json
import math
import re

from .ibkr_market_health_sources import _four_asset_market_calendar
from .mstr_asst_full_day_market_intake import NEW_YORK, _session_close_ms
from .observation_store import ObservationRevisionConflict, ObservationStore


SCHEMA = "CRT_BTC_TACTICAL_FORECAST_V0.1"
PRE = "BTC_TACTICAL_PRE"
POST = "BTC_TACTICAL_POST"
ANCHOR = "BTC_TACTICAL_ANCHOR"
DAY_MS = 86_400_000


def content_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def session_schedule(session_date: str) -> dict:
    """Reuse the tracked US equity calendar; DST and early closes are explicit."""
    calendar = _four_asset_market_calendar()
    day = date.fromisoformat(session_date)
    if (not calendar["valid_from"] <= session_date <= calendar["valid_through"]
            or day.weekday() not in calendar["weekday_sessions"]
            or session_date in calendar["full_close_dates"]):
        raise ValueError("US_EQUITY_SESSION_NOT_COVERED")
    opening = int(datetime.combine(day, time(9, 30), NEW_YORK).timestamp() * 1000)
    closing = _session_close_ms(
        session_date, early_close_dates=frozenset(calendar["early_close_dates"]))
    return {
        "session_date": session_date, "timezone": calendar["timezone"],
        "calendar_id": calendar["calendar_id"], "calendar_hash": content_hash(calendar),
        "open_ms": opening, "close_ms": closing,
        "pre_due_ms": opening - 3_600_000, "post_due_ms": closing + 21_600_000,
    }


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("REQUIRED_TEXT_MISSING")


def _clock(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("CLOCK_INVALID")


def _hash(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("CONTENT_HASH_INVALID")


def _sources(rows: object, cutoff_ms: int) -> set[str]:
    """Preserve upstream qualifications; never manufacture source qualification."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("SOURCE_REFERENCES_MISSING")
    ids = set()
    for row in rows:
        for field in ("source_id", "source_ref", "validation_ref"):
            _text(row.get(field))
        _hash(row.get("evidence_hash"))
        for field in ("observed_at_ms", "available_at_ms", "retrieved_at_ms",
                      "validated_at_ms"):
            _clock(row.get(field))
            if row[field] > cutoff_ms:
                raise ValueError("SOURCE_NOT_VISIBLE_AT_CUTOFF")
        if row["observed_at_ms"] > row["available_at_ms"]:
            raise ValueError("SOURCE_CLOCK_ORDER_INVALID")
        if row["retrieved_at_ms"] > row["validated_at_ms"]:
            raise ValueError("SOURCE_CLOCK_ORDER_INVALID")
        if row["available_at_ms"] > row["validated_at_ms"]:
            raise ValueError("SOURCE_CLOCK_ORDER_INVALID")
        if row.get("quality_state") not in {"VALID", "RESEARCH_ONLY", "BLOCKED", "STALE"}:
            raise ValueError("UPSTREAM_QUALIFICATION_REQUIRED")
        if row["source_ref"] in ids:
            raise ValueError("DUPLICATE_SOURCE_REFERENCE")
        ids.add(row["source_ref"])
    return ids


def _anchor(anchor: dict, refs: set[str], cutoff_ms: int) -> None:
    value = anchor.get("price")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError("PRICE_ANCHOR_INVALID")
    if anchor.get("currency") not in {"USD", "USDT"}:
        raise ValueError("PRICE_CURRENCY_REQUIRED")
    if anchor.get("price_basis") not in {"COMPLETED_CLOSE", "SPOT_OBSERVATION", "BID_ASK"}:
        raise ValueError("PRICE_BASIS_REQUIRED")
    _clock(anchor.get("observed_at_ms"))
    if anchor["observed_at_ms"] > cutoff_ms or anchor.get("source_ref") not in refs:
        raise ValueError("PRICE_ANCHOR_SOURCE_INVALID")


def _append(store: ObservationStore, kind: str, payload: dict, now_ms: int) -> dict:
    _clock(now_ms)
    identity = payload["id"]
    _text(identity)
    digest = content_hash(payload)
    prior = store.research_event(identity, kind=kind)
    if prior:
        if prior["content_hash"] != digest:
            raise ObservationRevisionConflict("FROZEN_RESEARCH_EVENT_CONFLICT")
        return prior
    record = {
        "schema_version": SCHEMA, "kind": kind, "content": deepcopy(payload),
        "content_hash": digest, "recorded_at_ms": now_ms,
        "assessment_authority": "RESEARCH_ONLY", "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }
    store.record_research_event(identity, kind, record)
    return record


def read_pre(store: ObservationStore, pre_id: str, expected_hash: str) -> dict:
    record = store.research_event(pre_id, kind=PRE)
    if record is None:
        raise ValueError("PRE_NOT_FOUND")
    if (record["content_hash"] != expected_hash
            or content_hash(record["content"]) != expected_hash):
        raise ValueError("PRE_HASH_MISMATCH")
    return record


def freeze_pre(store: ObservationStore, pre: dict, *, now_ms: int) -> dict:
    """Freeze the analyst's original text and falsifiable claims, never infer them."""
    _clock(now_ms)
    for field in ("generated_at_ms", "market_cutoff_ms"):
        _clock(pre.get(field))
    if not pre["market_cutoff_ms"] <= pre["generated_at_ms"] <= now_ms:
        raise ValueError("PRE_CLOCK_ORDER_INVALID")
    for field in ("original_text", "main_scenario", "invalidation_line",
                  "strongest_counterevidence", "change_conditions", "analyst_ref",
                  "program_version"):
        _text(pre.get(field))
    schedule = session_schedule(pre["session_date"])
    refs = _sources(pre.get("sources"), pre["market_cutoff_ms"])
    _anchor(pre["price_anchor"], refs, pre["market_cutoff_ms"])
    claims = pre.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("FALSIFIABLE_CLAIMS_REQUIRED")
    ids = set()
    for claim in claims:
        for field in ("claim_id", "statement", "verification_condition"):
            _text(claim.get(field))
        _clock(claim.get("target_at_ms"))
        horizon = claim["target_at_ms"] - pre["generated_at_ms"]
        if not 7 * DAY_MS <= horizon <= 21 * DAY_MS:
            raise ValueError("FORECAST_HORIZON_OUTSIDE_1_TO_3_WEEKS")
        if claim["claim_id"] in ids:
            raise ValueError("DUPLICATE_CLAIM_ID")
        ids.add(claim["claim_id"])
    payload = deepcopy(pre)
    payload["schedule"] = schedule
    # A late local import must not masquerade as a pre-open frozen forecast.
    prior = store.research_event(pre["id"], kind=PRE)
    frozen_at = prior["recorded_at_ms"] if prior else now_ms
    payload["timing_state"] = (
        "PRE_WINDOW" if schedule["pre_due_ms"] <= pre["generated_at_ms"]
        <= frozen_at < schedule["open_ms"] else "OUTSIDE_PRE_WINDOW")
    payload["original_text_hash"] = hashlib.sha256(pre["original_text"].encode()).hexdigest()
    return _append(store, PRE, payload, now_ms)


def freeze_post(store: ObservationStore, post: dict, *, now_ms: int) -> dict:
    """Verify linkage/completeness only; the stored assessments remain research."""
    _clock(now_ms)
    pre = read_pre(store, post["pre_id"], post["pre_hash"])
    original = pre["content"]
    for field in ("generated_at_ms", "market_cutoff_ms"):
        _clock(post.get(field))
    if not (pre["recorded_at_ms"] <= post["market_cutoff_ms"]
            <= post["generated_at_ms"] <= now_ms):
        raise ValueError("POST_CLOCK_ORDER_INVALID")
    schedule = session_schedule(post["session_date"])
    if (post["session_date"] < original["session_date"]
            or post["generated_at_ms"] < schedule["post_due_ms"]
            or post["market_cutoff_ms"] < schedule["close_ms"]):
        raise ValueError("POST_BEFORE_SESSION_REVIEW")
    for field in ("original_text", "analyst_ref", "program_version"):
        _text(post.get(field))
    refs = _sources(post.get("sources"), post["market_cutoff_ms"])
    targets = {row["claim_id"]: row["target_at_ms"] for row in original["claims"]}
    reviews = post.get("reviews")
    if (not isinstance(reviews, list) or len(reviews) != len(targets)
            or {row.get("claim_id") for row in reviews} != set(targets)):
        raise ValueError("POST_MUST_REVIEW_EACH_ORIGINAL_CLAIM")
    quality = {row["source_ref"]: row["quality_state"] for row in post["sources"]}
    observed = {row["source_ref"]: row["observed_at_ms"] for row in post["sources"]}
    for row in reviews:
        if set(row) != {"claim_id", "result", "source_refs", "reason"}:
            raise ValueError("REVIEW_CANNOT_REDEFINE_ORIGINAL_TARGET")
        _text(row.get("reason"))
        if row.get("result") not in {"SUPPORTED", "REFUTED", "INCONCLUSIVE", "PENDING"}:
            raise ValueError("REVIEW_RESULT_INVALID")
        used = row.get("source_refs")
        if not isinstance(used, list) or not set(used) <= refs:
            raise ValueError("REVIEW_SOURCE_UNKNOWN")
        if row["result"] in {"SUPPORTED", "REFUTED"}:
            if not used or any(quality[ref] not in {"VALID", "RESEARCH_ONLY"} for ref in used):
                raise ValueError("REVIEW_EVIDENCE_BLOCKED")
            required_time = (targets[row["claim_id"]] if row["result"] == "SUPPORTED"
                             else pre["recorded_at_ms"])
            if not any(observed[ref] >= required_time for ref in used):
                raise ValueError("REVIEW_OUTCOME_OBSERVATION_MISSING")
        if (row["result"] == "SUPPORTED"
                and post["market_cutoff_ms"] < targets[row["claim_id"]]):
            raise ValueError("FORECAST_HORIZON_NOT_COMPLETE")
    payload = deepcopy(post)
    payload["linkage_state"] = "PRE_LINK_VERIFIED"
    payload["forecast_timing_state"] = original["timing_state"]
    payload["original_text_hash"] = hashlib.sha256(post["original_text"].encode()).hexdigest()
    return _append(store, POST, payload, now_ms)


def revise_price_anchor(store: ObservationStore, revision: dict, *, now_ms: int) -> dict:
    """Append an anchor change; the original forecast/targets are never rewritten."""
    _clock(now_ms)
    pre = read_pre(store, revision["pre_id"], revision["pre_hash"])
    _text(revision.get("reason"))
    _clock(revision.get("changed_at_ms"))
    if not pre["recorded_at_ms"] <= revision["changed_at_ms"] <= now_ms:
        raise ValueError("ANCHOR_REVISION_CLOCK_INVALID")
    refs = _sources(revision.get("sources"), revision["changed_at_ms"])
    _anchor(revision["new_anchor"], refs, revision["changed_at_ms"])
    kind = f"{ANCHOR}:{revision['pre_id']}"
    prior = store.research_event(revision["id"], kind=kind)
    if prior:
        return _append(store, kind, revision, now_ms)
    # Serialize the latest-anchor check with the append in the same SQLite writer.
    store.conn.execute("BEGIN IMMEDIATE")
    try:
        last = store.latest_research_event(kind)
        parent_id = last["content"]["id"] if last else revision["pre_id"]
        old = last["content"]["new_anchor"] if last else pre["content"]["price_anchor"]
        last_time = last["content"]["changed_at_ms"] if last else pre["recorded_at_ms"]
        if (revision.get("previous_id") != parent_id or revision.get("old_anchor") != old
                or revision["changed_at_ms"] < last_time):
            raise ValueError("ANCHOR_HISTORY_MISMATCH")
        return _append(store, kind, revision, now_ms)
    except Exception:
        store.conn.rollback()
        raise
