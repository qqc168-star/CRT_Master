"""Non-weighted company evidence; normalized, source-verified inputs only.

No collection, investment diagnosis, formal model change, or external action.
See docs/TREASURY_COMPANY_CT_V0.1.md for the input and comparison contract.
"""
from __future__ import annotations

import math
import hashlib
import json
import csv
from io import StringIO
from collections import Counter
from copy import deepcopy
from typing import Any

from .diluted_equity_mnav import (
    SCHEMA_VERSION as MNAV_SCHEMA_VERSION,
    build_diluted_equity_mnav,
)

SCHEMA_VERSION = "CRT_TREASURY_COMPANY_CT_V0.1.1"
OVERLAY_TYPE = "NON_WEIGHTED_EVIDENCE_OVERLAY"
FORMAL_MNAV_REF = "radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md"
REPLAY_MODES = {"DECISION_REPLAY", "AUDIT_REPLAY"}
MNAV_SEMANTIC_IDENTITIES = {
    "CRT_FORMAL_DILUTED_EQUITY_MNAV",
    "STRATEGYTRACKER_DILUTED_MNAV_RESEARCH",
    "SAYLORTRACKER_DILUTED_MNAV_RESEARCH",
    "STRATEGY_ISSUER_MNAV",
}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _time(value: Any) -> bool:
    return type(value) is int and value > 0


def _block(section: dict, claim: str, code: str) -> None:
    section["blockers"].append({"claim": claim, "code": code})


def _section() -> dict:
    return {"state": "BLOCKED", "blockers": []}


def _finish(section: dict, usable: bool) -> dict:
    section["state"] = (
        "PARTIAL" if section["blockers"] else "AVAILABLE"
    ) if usable else "BLOCKED"
    return section


def _metadata(raw: Any, section: dict, claim: str, issuer: str, as_of: int,
              replay_mode: str = "DECISION_REPLAY") -> dict | None:
    if not isinstance(raw, dict):
        _block(section, claim, "EVIDENCE_MISSING_OR_INVALID")
        return None
    if (raw.get("issuer_id") != issuer or not _text(raw.get("source_ref"))
            or raw.get("verification_state") != "VALIDATED"):
        _block(section, claim, "SOURCE_OR_ISSUER_NOT_VALIDATED")
        return None
    # Four clocks are deliberately distinct.  Old `*_at_ms` names are not
    # accepted here: silently mapping them would make an audit look like a
    # decision-time observation and permits future-information leakage.
    clocks = {key: raw.get(key) for key in (
        "effective_time", "disclosure_time", "first_seen_time", "retrieval_time")}
    if (replay_mode not in REPLAY_MODES or not all(_time(value) for value in clocks.values())
            or not (clocks["effective_time"] <= clocks["disclosure_time"]
                    <= clocks["first_seen_time"] <= clocks["retrieval_time"])):
        _block(section, claim, "PIT_FOUR_CLOCKS_INVALID")
        return None
    visibility = clocks["disclosure_time"] if replay_mode == "DECISION_REPLAY" else clocks["retrieval_time"]
    if visibility > as_of:
        _block(section, claim, "PIT_FUTURE_LEAKAGE_BLOCKED")
        return None
    semantic = raw.get("source_semantic")
    if (not isinstance(semantic, dict) or not _text(semantic.get("identity"))
            or not _text(semantic.get("version")) or not _time(semantic.get("effective_from"))
            or not (_time(semantic.get("effective_to")) or semantic.get("effective_to") is None)
            or semantic["effective_from"] > clocks["effective_time"]
            or (semantic.get("effective_to") is not None and semantic["effective_to"] < clocks["effective_time"])):
        _block(section, claim, "SOURCE_SEMANTIC_UNBOUND_BLOCKED")
        return None
    return {"issuer_id": raw["issuer_id"], "source_ref": raw["source_ref"],
            "verification_state": raw["verification_state"], **clocks,
            "source_semantic": {key: semantic[key] for key in ("identity", "version", "effective_from", "effective_to")}}


def _numeric(raw: dict, key: str, section: dict, claim: str, *, signed: bool = False) -> float | None:
    value = raw.get(key)
    if not _number(value) or (not signed and value < 0):
        _block(section, f"{claim}.{key}", "NUMERIC_EVIDENCE_MISSING_OR_INVALID")
        return None
    return float(value)


def _calc(section: dict, claim: str, values: list, fn) -> float | None:
    if any(value is None for value in values):
        _block(section, claim, "CALCULATION_INPUT_INCOMPLETE")
        return None
    try:
        value = fn(*values)
        if _number(value):
            return value
    except (ZeroDivisionError, OverflowError):
        pass
    _block(section, claim, "CALCULATION_UNDEFINED_OR_NONFINITE")
    return None


def _direction(delta: float | None, *, lower: bool = False) -> str | None:
    if delta is None:
        return None
    if math.isclose(delta, 0, abs_tol=1e-12):
        return "FLAT"
    return "IMPROVING" if (delta < 0 if lower else delta > 0) else "DETERIORATING"


def _comparable(previous: dict | None, current: dict | None) -> bool:
    return bool(previous and current and _text(current.get("basis_ref"))
                and previous.get("basis_ref") == current["basis_ref"]
                and previous["effective_time"] < current["effective_time"])


def _asset(history: Any, issuer: str, as_of: int) -> dict:
    out = _section()
    out.update(observations=[], current=None, previous=None,
               btc_per_diluted_share_change_pct=None, direction=None,
               observation_span_ms=None, growth_observations=[], growth_direction=None)
    if not isinstance(history, list) or not history:
        _block(out, "asset_history", "ASSET_HISTORY_MISSING")
        return out
    dated = [row for row in history if isinstance(row, dict) and _time(row.get("effective_time"))]
    counts = Counter(row["effective_time"] for row in dated)
    invalid_time = len(dated) != len(history)
    if invalid_time:
        _block(out, "current", "ASSET_TIME_UNKNOWN")
    rows = []
    for index, raw in enumerate(sorted(dated, key=lambda row: row["effective_time"])):
        claim = f"asset_history[{index}]"
        row = _metadata(raw, out, claim, issuer, as_of)
        if counts[raw["effective_time"]] != 1:
            _block(out, claim, "DUPLICATE_ASSET_TIME")
            row = None
        if row is not None:
            row["basis_ref"] = raw.get("basis_ref") if _text(raw.get("basis_ref")) else None
            row["btc_holdings"] = _numeric(raw, "btc_holdings", out, claim)
            row["diluted_shares"] = _numeric(raw, "diluted_shares", out, claim)
            # A level also needs a documented dilution / stock-split basis.
            row["btc_per_diluted_share"] = None
            if row["basis_ref"]:
                row["btc_per_diluted_share"] = _calc(out, claim + ".btc_per_diluted_share",
                    [row["btc_holdings"], row["diluted_shares"]], lambda a, b: a / b)
            else:
                _block(out, claim + ".btc_per_diluted_share", "SHARE_BASIS_MISSING")
            out["observations"].append(row)
        # Keep holes: never silently compare across an invalid intervening state.
        rows.append(row)
    if rows and not invalid_time:
        out["current"] = rows[-1]
        out["previous"] = rows[-2] if len(rows) > 1 else None
    for previous, current in zip(rows, rows[1:]):
        if not _comparable(previous, current):
            out["growth_observations"].append(None)
            _block(out, "asset_change", "ASSET_STATES_NOT_COMPARABLE")
            continue
        delta = _calc(out, "asset_change", [previous["btc_per_diluted_share"], current["btc_per_diluted_share"]],
                      lambda before, now: now / before - 1)
        out["growth_observations"].append({
            "from_ms": previous["effective_time"], "to_ms": current["effective_time"],
            "span_ms": current["effective_time"] - previous["effective_time"],
            "change_pct": delta, "source_refs": [previous["source_ref"], current["source_ref"]],
        })
    growth = out["growth_observations"]
    if not invalid_time and growth and growth[-1] is not None:
        out["btc_per_diluted_share_change_pct"] = growth[-1]["change_pct"]
        out["direction"] = _direction(growth[-1]["change_pct"])
        out["observation_span_ms"] = growth[-1]["span_ms"]
    else:
        _block(out, "asset_change", "ASSET_COMPARISON_UNAVAILABLE")
    if (not invalid_time and len(growth) >= 2 and growth[-1] and growth[-2]
            and growth[-1]["span_ms"] == growth[-2]["span_ms"]
            and all(g["change_pct"] is not None for g in growth[-2:])):
        difference = growth[-1]["change_pct"] - growth[-2]["change_pct"]
        out["growth_direction"] = "STABLE" if math.isclose(difference, 0, abs_tol=1e-12) else (
            "DECELERATING" if difference < 0 else "ACCELERATING")
    else:
        _block(out, "growth_direction", "EQUAL_SPAN_GROWTH_HISTORY_UNAVAILABLE")
    return _finish(out, bool(out["observations"]))


def _collection(raw: Any, out: dict, name: str, issuer: str, as_of: int, coverage: Any) -> list:
    """Explicit coverage is separate from the validity of individual observations."""
    out["coverage_state"] = "PARTIAL"
    if isinstance(coverage, dict) and coverage.get("coverage_state") == "COMPLETE":
        meta = _metadata(coverage, out, name + ".coverage", issuer, as_of)
        if meta and _text(coverage.get("scope_ref")):
            out["coverage_state"] = "COMPLETE"
            out["coverage_evidence"] = {**meta, "scope_ref": coverage["scope_ref"]}
        else:
            _block(out, name + ".coverage", "COVERAGE_NOT_VERIFIED")
    if not isinstance(raw, list):
        _block(out, name, "COLLECTION_MISSING_OR_INVALID")
        return []
    if not raw and out["coverage_state"] == "COMPLETE" and coverage.get("empty_reason") == "VERIFIED_NO_MATCH":
        out["empty_reason"] = "VERIFIED_NO_MATCH"
    elif not raw or out["coverage_state"] != "COMPLETE":
        _block(out, name + ".coverage", "COVERAGE_INCOMPLETE")
    return raw


def _funding(raw: Any, issuer: str, as_of: int, coverage: Any) -> dict:
    out = _section()
    out["instruments"] = []
    records = _collection(raw, out, "funding", issuer, as_of, coverage)
    ids = Counter(r.get("instrument_id") for r in records if isinstance(r, dict) and _text(r.get("instrument_id")))
    for index, record in enumerate(records):
        claim = f"funding[{index}]"
        row = _metadata(record, out, claim, issuer, as_of)
        if row is None:
            continue
        key = record.get("instrument_id")
        if not _text(key) or ids[key] != 1 or not _text(record.get("instrument_type")):
            _block(out, claim, "FUNDING_IDENTITY_INVALID_OR_DUPLICATE")
            continue
        row.update(instrument_id=key, instrument_type=record["instrument_type"])
        for field in ("program_capacity_usd", "cumulative_program_usage_usd", "usable_capacity_usd",
                      "observed_funding_use_usd", "annual_cost_rate_pct"):
            row[field] = _numeric(record, field, out, claim)
        capacity, used = row["program_capacity_usd"], row["cumulative_program_usage_usd"]
        row["remaining_nominal_capacity_usd"] = None
        if capacity is not None and used is not None and used <= capacity:
            row["remaining_nominal_capacity_usd"] = capacity - used
        else:
            _block(out, claim + ".remaining_nominal_capacity_usd", "NOMINAL_CAPACITY_NOT_COMPARABLE")
        if row["usable_capacity_usd"] is not None and not _text(record.get("usability_basis_ref")):
            row["usable_capacity_usd"] = None
            _block(out, claim + ".usable_capacity_usd", "USABILITY_BASIS_MISSING")
        row["usability_basis_ref"] = record.get("usability_basis_ref") if row["usable_capacity_usd"] is not None else None
        remaining = row["remaining_nominal_capacity_usd"]
        if remaining is not None and row["usable_capacity_usd"] is not None and row["usable_capacity_usd"] > remaining:
            row["usable_capacity_usd"] = None
            _block(out, claim + ".usable_capacity_usd", "USABLE_CAPACITY_EXCEEDS_NOMINAL_REMAINDER")
        row["cost_direction"] = None
        previous = record.get("previous_cost")
        if previous is not None:
            meta = _metadata(previous, out, claim + ".previous_cost", issuer, as_of)
            if meta and _text(record.get("cost_basis_ref")) and previous.get("cost_basis_ref") == record["cost_basis_ref"] and meta["effective_time"] < row["effective_time"]:
                before = _numeric(previous, "annual_cost_rate_pct", out, claim + ".previous_cost")
                delta = _calc(out, claim + ".cost_direction", [row["annual_cost_rate_pct"], before], lambda a, b: a - b)
                row["cost_direction"] = _direction(delta, lower=True)
                row["previous_cost"] = {**meta, "annual_cost_rate_pct": before, "cost_basis_ref": previous["cost_basis_ref"]}
            else:
                _block(out, claim + ".cost_direction", "COST_STATES_NOT_COMPARABLE")
        row["cost_basis_ref"] = record.get("cost_basis_ref") if _text(record.get("cost_basis_ref")) else None
        if not row["cost_basis_ref"]:
            row["annual_cost_rate_pct"] = None
            _block(out, claim + ".annual_cost_rate_pct", "COST_BASIS_MISSING")
        row["market_absorption_evidence"] = None
        absorption = record.get("market_absorption_evidence")
        if absorption is not None:
            meta = _metadata(absorption, out, claim + ".market_absorption", issuer, as_of)
            if meta and _text(absorption.get("observation_ref")) and absorption.get("evidence_kind") == "ISSUER_REPORTED_FUNDING_OBSERVATION":
                row["market_absorption_evidence"] = {**meta, "observation_ref": absorption["observation_ref"],
                    "evidence_kind": absorption["evidence_kind"]}
            else:
                _block(out, claim + ".market_absorption", "ABSORPTION_EVIDENCE_INVALID")
        out["instruments"].append(row)
    return _finish(out, bool(out["instruments"]) or out.get("empty_reason") == "VERIFIED_NO_MATCH")


def _burden_snapshot(raw: Any, out: dict, claim: str, issuer: str, as_of: int) -> dict | None:
    row = _metadata(raw, out, claim, issuer, as_of)
    if row is None:
        return None
    row["basis_ref"] = raw.get("basis_ref") if _text(raw.get("basis_ref")) else None
    for field in ("debt_principal_usd", "preferred_liquidation_claims_usd", "annual_debt_interest_usd",
                  "annual_preferred_distributions_usd", "usd_cash_usd", "usd_reserve_usd"):
        row[field] = _numeric(raw, field, out, claim)
    for target, fields in (("annual_carry_usd", ("annual_debt_interest_usd", "annual_preferred_distributions_usd")),
                           ("senior_claims_usd", ("debt_principal_usd", "preferred_liquidation_claims_usd"))):
        row[target] = _calc(out, claim + "." + target, [row[f] for f in fields], lambda a, b: a + b) if row["basis_ref"] else None
    if not row["basis_ref"]:
        _block(out, claim + ".derived_burden", "BURDEN_BASIS_MISSING")
    cash, reserve = row["usd_cash_usd"], row["usd_reserve_usd"]
    row["usable_liquidity_usd"] = cash
    row["coverage_basis"] = "USD_CASH_ONLY"
    if reserve is not None and reserve > 0:
        usable, separate = raw.get("reserve_usable_for_carry"), raw.get("reserve_separate_from_cash")
        if usable is True and separate is True:
            row["usable_liquidity_usd"] = _calc(out, claim + ".liquidity", [cash, reserve], lambda a, b: a + b)
            row["coverage_basis"] = "USD_CASH_PLUS_SEPARATE_USABLE_RESERVE"
        elif usable is not False:
            _block(out, claim + ".reserve", "RESERVE_USABILITY_OR_NONOVERLAP_UNVERIFIED")
    row["carry_coverage_years"] = _calc(out, claim + ".carry_coverage_years",
        [row["usable_liquidity_usd"], row["annual_carry_usd"]], lambda a, b: a / b)
    return row


def _burden(current: Any, previous: Any, maturities: Any, issuer: str, as_of: int, coverage: Any) -> dict:
    out = _section()
    out["current"] = _burden_snapshot(current, out, "burden_current", issuer, as_of)
    out["previous"] = _burden_snapshot(previous, out, "burden_previous", issuer, as_of) if previous is not None else None
    for metric, lower in (("annual_carry", True), ("senior_claims", True), ("carry_coverage", False)):
        field = metric + ("_years" if metric == "carry_coverage" else "_usd")
        out[metric + "_change_pct"] = None
        out[metric + "_direction"] = None
        before, now = out["previous"], out["current"]
        if _comparable(before, now) and (metric != "carry_coverage" or before["coverage_basis"] == now["coverage_basis"]):
            delta = _calc(out, metric + "_change", [before[field], now[field]], lambda a, b: b / a - 1)
            out[metric + "_change_pct"] = delta
            out[metric + "_direction"] = _direction(delta, lower=lower)
        else:
            _block(out, metric + "_change", "BURDEN_STATES_NOT_COMPARABLE")
    out["maturities"] = []
    records = _collection(maturities, out, "maturities", issuer, as_of, coverage)
    ids = Counter(r.get("maturity_id") for r in records if isinstance(r, dict) and _text(r.get("maturity_id")))
    for index, raw in enumerate(records):
        claim = f"maturities[{index}]"
        row = _metadata(raw, out, claim, issuer, as_of)
        if row is None:
            continue
        key, due = raw.get("maturity_id"), raw.get("due_at_ms")
        if not _text(key) or ids[key] != 1 or not _time(due):
            _block(out, claim, "MATURITY_ID_OR_TIME_INVALID")
            continue
        amount = _numeric(raw, "principal_due_usd", out, claim)
        row.update(maturity_id=key, due_at_ms=due, principal_due_usd=amount,
                   days_to_maturity=(due - as_of) / 86_400_000)
        out["maturities"].append(row)
    return _finish(out, out["current"] is not None or out["previous"] is not None or bool(out["maturities"]))


def _events(raw: Any, issuer: str, as_of: int, coverage: Any, *, management: bool) -> dict:
    out = _section()
    out["events"] = []
    records = _collection(raw, out, "events", issuer, as_of, coverage)
    ids = Counter(r.get("event_id") for r in records if isinstance(r, dict) and _text(r.get("event_id")))
    for index, record in enumerate(records):
        claim = f"events[{index}]"
        row = _metadata(record, out, claim, issuer, as_of)
        if row is None:
            continue
        key = record.get("event_id")
        fields = ("action_type", "action_ref") if management else ("source", "destination")
        if not _text(key) or ids[key] != 1 or any(not _text(record.get(f)) for f in fields):
            _block(out, claim, "EVENT_IDENTITY_OR_ROUTE_INVALID")
            continue
        row.update(event_id=key, **{f: record[f] for f in fields})
        # Superseded actions remain traceable but never enter active calculations.
        active = record.get("active_for_calculation")
        row["active_for_calculation"] = active is True
        if type(active) is not bool:
            _block(out, claim, "EVENT_ACTIVE_STATE_UNKNOWN")
        if not management:
            row["amount_usd"] = _numeric(record, "amount_usd", out, claim)
            basis = record.get("consequence_basis_ref")
            row["consequence_basis_ref"] = basis if _text(basis) else None
            for field in ("btc_change", "diluted_share_change", "senior_claim_change_usd",
                          "annual_carry_change_usd", "liquidity_change_usd"):
                row[field] = _numeric(record, field, out, claim, signed=True) if row["consequence_basis_ref"] else None
            if not row["consequence_basis_ref"]:
                _block(out, claim + ".economic_consequences", "CONSEQUENCE_BASIS_MISSING")
        out["events"].append(row)
    out["events"].sort(key=lambda row: (row["effective_time"], row["event_id"]))
    # No cross-event sum: accounting scopes may overlap even when IDs differ.
    return _finish(out, bool(out["events"]) or out.get("empty_reason") == "VERIFIED_NO_MATCH")


def _price(raw: Any, issuer: str, as_of: int) -> dict:
    out = _section()
    out.update(mnav=None, semantic_ref=None)
    meta = _metadata(raw, out, "price_financing_state", issuer, as_of)
    if meta is None:
        return out
    semantic = meta["source_semantic"]
    if semantic["identity"] != "CRT_FORMAL_DILUTED_EQUITY_MNAV":
        _block(out, "mnav", "MNAV_SEMANTIC_LINE_NOT_FORMAL_CRT")
        return out
    valid = (raw.get("schema_version") == MNAV_SCHEMA_VERSION and raw.get("state") == "AVAILABLE"
             and raw.get("semantic_ref") == FORMAL_MNAV_REF and raw.get("evidence_alignment_state") == "VALIDATED"
             and raw.get("action_output") == "NONE" and raw.get("external_action_authority") == "NONE"
             and raw.get("external_action_performed") is False
             and raw.get("asset_id") in ("MSTR", "ASST"))
    value = raw.get("mnav")
    if not valid or not _number(value) or value <= 0:
        _block(out, "mnav", "FORMAL_MNAV_EVIDENCE_NOT_VALIDATED")
        return out
    cap, nav = raw.get("diluted_equity_market_cap_usd"), raw.get("asset_nav_usd")
    if not _number(cap) or not _number(nav) or cap <= 0 or nav <= 0:
        _block(out, "mnav", "MNAV_UPSTREAM_INPUTS_INVALID")
        return out
    upstream = build_diluted_equity_mnav(
        asset_id=raw["asset_id"], diluted_equity_market_cap_usd=cap,
        asset_nav_usd=nav, semantic_ref=FORMAL_MNAV_REF,
        evidence_alignment_state="VALIDATED",
    )
    if not _number(upstream["mnav"]) or not math.isclose(value, upstream["mnav"], rel_tol=1e-12):
        _block(out, "mnav", "MNAV_UPSTREAM_RESULT_MISMATCH")
        return out
    out.update(meta, mnav=float(value), semantic_ref=FORMAL_MNAV_REF,
               asset_id=raw["asset_id"], evidence_alignment_state="VALIDATED")
    return _finish(out, True)


def build_net_bps_attribution(*, opening_btc: Any, closing_btc: Any,
                              opening_shares: Any, closing_shares: Any,
                              components: Any, semantic_state: str = "FORMAL") -> dict:
    """Evidence-only bridge from two verified per-share levels to explicit causes.

    It intentionally does not infer a missing residual: an unbound issuer
    semantic (notably Strive) is a blocked research candidate, never a metric.
    """
    labels = ("Market Translation", "Asset Action", "Claim Action", "Reserve Action", "Share Denominator")
    out = {"state": "BLOCKED", "unit": "NET_BPS", "components": {label: None for label in labels},
           "net_bps_change": None, "blockers": [], "classification": None}
    if semantic_state not in ("FORMAL", "RESEARCH_CANDIDATE"):
        out["blockers"].append("NET_BPS_SEMANTIC_UNBOUND_BLOCKED")
        return out
    out["classification"] = semantic_state
    numbers = (opening_btc, closing_btc, opening_shares, closing_shares)
    if not all(_number(value) and value >= 0 for value in numbers) or opening_shares <= 0 or closing_shares <= 0:
        out["blockers"].append("NET_BPS_LEVELS_INVALID")
        return out
    if not isinstance(components, dict) or any(not _number(components.get(label)) for label in labels):
        out["blockers"].append("NET_BPS_ATTRIBUTION_COMPONENTS_INCOMPLETE")
        return out
    out["components"] = {label: float(components[label]) for label in labels}
    out["net_bps_change"] = (closing_btc / closing_shares - opening_btc / opening_shares) * 10_000
    out["state"] = "RESEARCH_CANDIDATE" if semantic_state == "RESEARCH_CANDIDATE" else "AVAILABLE"
    return out


def validate_pit_replay(record: dict, *, issuer_id: str, replay_at: int, mode: str) -> dict:
    """Validate one record at a replay cutoff without calculating a claim."""
    section = _section()
    metadata = _metadata(record, section, "replay", issuer_id, replay_at, mode)
    return {"state": "AVAILABLE" if metadata else "BLOCKED", "mode": mode,
            "record": metadata, "blockers": section["blockers"]}


def admit_saylortracker_sensor(record: Any) -> dict:
    """Admit only a human-approved, offline research sensor; no crawler exists."""
    required = ("sensor_id", "admission_ref", "approved_by", "approved_at", "coverage")
    if not isinstance(record, dict) or any(not _text(record.get(key)) for key in required):
        return {"state": "BLOCKED", "code": "SENSOR_ADMISSION_RECORD_INVALID"}
    if record.get("source_class") != "RESEARCH_SECONDARY" or record.get("collection_method") != "OFFLINE_CSV_IMPORT":
        return {"state": "BLOCKED", "code": "SAYLORTRACKER_RESEARCH_ONLY_OFFLINE_ONLY"}
    return {"state": "ADMITTED", **{key: record[key] for key in required},
            "source_class": "RESEARCH_SECONDARY", "collection_method": "OFFLINE_CSV_IMPORT"}


def import_saylortracker_offline_csv(csv_text: str, admission_record: dict, *, retrieval_time: int) -> dict:
    """Parse supplied bytes only; provenance and raw hash make it audit-replayable."""
    admission = admit_saylortracker_sensor(admission_record)
    if admission["state"] != "ADMITTED" or not isinstance(csv_text, str) or not _time(retrieval_time):
        return {"state": "BLOCKED", "code": "OFFLINE_CSV_IMPORT_INVALID"}
    digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    rows = []
    for row in csv.DictReader(StringIO(csv_text)):
        try:
            effective = int(row["effective_time"])
            disclosure = int(row["disclosure_time"])
            first_seen = int(row["first_seen_time"])
        except (KeyError, TypeError, ValueError):
            return {"state": "BLOCKED", "code": "OFFLINE_CSV_CLOCKS_INVALID"}
        rows.append({**row, "effective_time": effective, "disclosure_time": disclosure,
                     "first_seen_time": first_seen, "retrieval_time": retrieval_time,
                     "provenance": admission["admission_ref"], "raw_hash": digest,
                     "coverage": admission["coverage"], "source_class": "RESEARCH_SECONDARY",
                     "source_semantic": {"identity": "STRATEGYTRACKER_DILUTED_MNAV_RESEARCH", "version": "OFFLINE_CSV_V1",
                         "effective_from": effective, "effective_to": None}})
    return {"state": "RESEARCH_SECONDARY", "sensor": admission, "raw_hash": digest,
            "retrieval_time": retrieval_time, "first_seen_time": min((row["first_seen_time"] for row in rows), default=None),
            "coverage": admission["coverage"], "rows": rows, "trading_threshold_eligible": False}


# Historical call sites remain callable; newly imported records use the corrected
# source identity. Existing stored legacy observations are not rewritten.
admit_strategytracker_sensor = admit_saylortracker_sensor
import_strategytracker_offline_csv = import_saylortracker_offline_csv


def build_treasury_company_ct(*, issuer_id: str, as_of_ms: int,
        asset_history: Any = None, funding_instruments: Any = None,
        burden_current: Any = None, burden_previous: Any = None,
        maturities: Any = None, capital_conversion_events: Any = None,
        management_events: Any = None, price_financing_state: Any = None,
        coverage: Any = None) -> dict:
    """Synthesize five independent organs. `_pct` changes are fractions (0.1 = 10%)."""
    if not _text(issuer_id) or not _time(as_of_ms):
        raise ValueError("issuer_id and positive integer as_of_ms are required")
    issuer_id = issuer_id.strip()
    coverage = coverage if isinstance(coverage, dict) else {}
    organs = {
        "per_share_asset_engine": _asset(asset_history, issuer_id, as_of_ms),
        "funding_engine": _funding(funding_instruments, issuer_id, as_of_ms, coverage.get("funding")),
        "capital_burden_resilience": _burden(burden_current, burden_previous, maturities, issuer_id, as_of_ms, coverage.get("maturities")),
        "capital_conversion": _events(capital_conversion_events, issuer_id, as_of_ms, coverage.get("capital_conversion"), management=False),
        "management_evidence": _events(management_events, issuer_id, as_of_ms, coverage.get("management"), management=True),
    }
    price = _price(price_financing_state, issuer_id, as_of_ms)
    sections = {**organs, "price_financing_state": price}
    blockers = [{"section": name, **blocker} for name, section in sections.items() for blocker in section["blockers"]]
    states = [section["state"] for section in sections.values()]
    return {"schema_version": SCHEMA_VERSION, "issuer_id": issuer_id, "as_of_ms": as_of_ms,
            "state": "COMPLETE" if all(s == "AVAILABLE" for s in states) else (
                "BLOCKED" if all(s == "BLOCKED" for s in states) else "PARTIAL"),
            "organs": organs, "price_financing_state": price, "blockers": blockers,
            "reflexivity_diagnosis": {"state": "GPT_JUDGMENT_REQUIRED"},
            "action_output": "NONE", "external_action_authority": "NONE", "external_action_performed": False}


def add_treasury_company_ct(pack: dict, ct_input: dict) -> None:
    """Called by the pack builder before hashing; no parallel top-level surface."""
    ct = build_treasury_company_ct(**ct_input)
    if ct["as_of_ms"] > pack["generated_at_ms"]:
        raise ValueError("CT as-of must not be later than Evidence Pack generation")
    common = {"overlay_id": SCHEMA_VERSION, "overlay_type": OVERLAY_TYPE,
              "issuer_id": ct["issuer_id"], "as_of_ms": ct["as_of_ms"]}
    for name, section in {**ct["organs"], "price_financing_state": ct["price_financing_state"]}.items():
        if name in ("capital_conversion", "management_evidence"):
            for event in section["events"]:
                pack["decision_relevant_events"]["items"].append({
                    **common, "ct_section": name, **deepcopy(event),
                    "source_event_id": event["event_id"],
                    "event_id": f"{SCHEMA_VERSION}:{ct['issuer_id']}:{name}:{event['event_id']}",
                })
        pack["asset_facts"]["items"].append({**common,
            "asset_fact_id": f"{SCHEMA_VERSION}:{ct['issuer_id']}:{name}",
            "fact_type": "TREASURY_COMPANY_CT", "ct_section": name, "evidence": deepcopy(section)})
    for blocker in ct["blockers"]:
        pack["blockers"]["items"].append({**common, **blocker, "scope": "CALCULATION",
            "affected_ids": [f"{ct['issuer_id']}:{blocker['section']}:{blocker['claim']}"],
            "reason": blocker["code"]})
    for name in ("asset_facts", "decision_relevant_events", "blockers"):
        section = pack[name]
        relevant = ([ct["organs"][key] for key in ("capital_conversion", "management_evidence")]
                    if name == "decision_relevant_events" else [*ct["organs"].values(), ct["price_financing_state"]])
        complete = all(row["state"] == "AVAILABLE" for row in relevant)
        # Keep the original contributor hash explicit; it must not masquerade
        # as a digest of a section whose items have now changed.
        if "overlay_hash" in section:
            section["upstream_overlay_hash"] = section.pop("overlay_hash")
        section["ct_contribution"] = {**common, "state": "COMPLETE" if complete else "PARTIAL",
                                      "reflexivity_diagnosis": ct["reflexivity_diagnosis"]}
        if section["items"]:
            section.pop("empty_reason", None)
        if name == "blockers" and ct["blockers"]:
            section["section_state"] = "BLOCKED"
        elif name != "blockers" and not complete and section["section_state"] == "READY":
            section["section_state"] = "PARTIAL"
        if name != "blockers" and section.get("coverage_state") == "COMPLETE" and any(
                row.get("coverage_state", "COMPLETE") != "COMPLETE" for row in relevant):
            section["coverage_state"] = "PARTIAL"
    material = {name: pack[name] for name in ("asset_facts", "decision_relevant_events", "blockers")}
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    for section in material.values():
        section["overlay_hash"] = digest


# Context extends CT's validated organs; it owns neither NAV composition nor a
# second fact store. Change percentages remain fractions; CDF ranks are 0..100.
VALUATION_VERSION = "CRT_TREASURY_VALUATION_CONTEXT_V0.1"
DAY_MS = 86_400_000
MIN_BASELINE_COUNT = 20
FORMAL_IDENTITY = "CRT_FORMAL_DILUTED_EQUITY_MNAV"
RESEARCH_IDENTITY = "STRATEGYTRACKER_DILUTED_MNAV_RESEARCH"
LEGACY_RESEARCH_IDENTITY = "SAYLORTRACKER_DILUTED_MNAV_RESEARCH"
OFFICIAL_CLASSES = {"ISSUER", "SEC", "VERIFIED_DETERMINISTIC"}
ISSUERS = {"MSTR": "CIK-0001050446", "ASST": "CIK-0001920406"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _claim(reason: str) -> dict:
    return {"state": "BLOCKED", "value": None, "reason": reason}


def _valuation_row(raw: Any, asset: str, as_of: int, out: dict) -> dict | None:
    meta = _metadata(raw, out, "mnav_history", ISSUERS[asset], as_of, "AUDIT_REPLAY")
    if meta is None:
        return None
    identity = meta["source_semantic"]["identity"]
    if identity not in {FORMAL_IDENTITY, RESEARCH_IDENTITY, LEGACY_RESEARCH_IDENTITY}:
        _block(out, "mnav_history", "DILUTED_MNAV_SEMANTIC_MISMATCH")
        return None
    if not _text(raw.get("basis_ref")) or raw.get("asset_id") != asset:
        _block(out, "mnav_history", "MNAV_ASSET_OR_BASIS_UNBOUND")
        return None
    if identity == FORMAL_IDENTITY:
        if raw.get("source_class") not in OFFICIAL_CLASSES:
            _block(out, "mnav_history", "OFFICIAL_INPUTS_REQUIRED")
            return None
        price = _price(raw, ISSUERS[asset], as_of)
        out["blockers"].extend(price["blockers"])
        value = price["mnav"]
        authority = "FORMAL_ACTION_CRITICAL"
    else:
        value = raw.get("mnav")
        authority = "RESEARCH_SECONDARY_EVIDENCE"
    if not _number(value) or value <= 0:
        _block(out, "mnav_history", "MNAV_VALUE_INVALID")
        return None
    return {**meta, "asset_id": asset, "basis_ref": raw["basis_ref"],
            "mnav": value, "evidence_authority": authority}


def _valuation_history(raw: Any, asset: str, as_of: int, out: dict) -> list:
    if not isinstance(raw, list):
        _block(out, "mnav_history", "MNAV_HISTORY_MISSING")
        return []
    # Only already retrieved records enter this local, reproducible view. Future
    # records are not holes in the current view; invalid visible records are.
    visible = [r for r in raw if not isinstance(r, dict) or
               not _time(r.get("retrieval_time")) or r["retrieval_time"] <= as_of]
    if any(not isinstance(r, dict) or not _time(r.get("effective_time")) for r in visible):
        _block(out, "mnav_history", "MNAV_HISTORY_TIME_UNKNOWN")
        return []
    counts = Counter(r["effective_time"] for r in visible)
    rows = []
    for r in sorted(visible, key=lambda r: r["effective_time"]):
        row = _valuation_row(r, asset, as_of, out)
        if counts[r["effective_time"]] != 1:
            _block(out, "mnav_history", "DUPLICATE_MNAV_TIME")
            row = None
        rows.append(row)
    return rows


def _same_valuation_basis(a: dict, b: dict) -> bool:
    # The legacy label stays valid but is not silently pooled with new history.
    return (a["basis_ref"] == b["basis_ref"] and
            all(a["source_semantic"][k] == b["source_semantic"][k]
                for k in ("identity", "version")))


def _cdf(current: dict | None, baseline: list, *, reason: str = "INSUFFICIENT_BASELINE") -> dict:
    result = {**_claim(reason), "baseline_count": len(baseline),
        "history_start": baseline[0]["effective_time"] if baseline else None,
        "history_end": baseline[-1]["effective_time"] if baseline else None,
        "current_value": current["mnav"] if current else None,
        "source_semantic": current["source_semantic"] if current else None,
        "calculation_version": "EMPIRICAL_CDF_LE_V1_MIN20",
        "baseline": deepcopy(baseline)}
    if current and len(baseline) >= MIN_BASELINE_COUNT:
        result.update(state="AVAILABLE", reason="PIT_COMPARABLE_BASELINE",
            value=100 * sum(r["mnav"] <= current["mnav"] for r in baseline) / len(baseline))
    return result


def build_preferred_funding_attribution(*, events: Any, issuer_id: str, as_of_ms: int) -> dict:
    """Per-event research accounting, never aggregate possibly overlapping events."""
    out = _section()
    out.update(research_only=True, events=[])
    if not isinstance(events, list) or not events:
        _block(out, "preferred_funding_attribution", "VERIFIED_PREFERRED_EVENTS_MISSING")
        return out
    ids = Counter(r.get("event_id") for r in events if isinstance(r, dict) and _text(r.get("event_id")))
    for raw in events:
        meta = _metadata(raw, out, "preferred_event", issuer_id, as_of_ms, "AUDIT_REPLAY")
        if meta is None:
            continue
        key = raw.get("event_id")
        if (not _text(key) or ids[key] != 1 or raw.get("source_class") not in OFFICIAL_CLASSES
                or meta["source_semantic"]["identity"] in {RESEARCH_IDENTITY, LEGACY_RESEARCH_IDENTITY}
                or raw.get("active_for_calculation") is not True
                or not _text(raw.get("consequence_basis_ref"))):
            _block(out, "preferred_event", "PREFERRED_EVENT_UNBOUND")
            continue
        row = {**meta, "event_id": key, "basis_ref": raw["consequence_basis_ref"],
               "calculation_inputs": {}, "effective_preferred_funding_cost": None,
               "claim_adjusted_reserve_delta_usd": None, "components": {}}
        for label, field in (("ASSET_ACTION", "btc_change"), ("CLAIM_ACTION", "senior_claim_change_usd"),
                ("CARRY", "annual_carry_change_usd"), ("RESERVE_ACTION", "liquidity_change_usd"),
                ("SHARE_DENOMINATOR", "diluted_share_change")):
            row["components"][label] = _numeric(raw, field, out, key, signed=True)
            row["calculation_inputs"][field] = row["components"][label]
        proceeds = raw.get("verified_net_proceeds_usd")
        annual = raw.get("annual_preferred_distributions_usd")
        if (raw.get("net_proceeds_verification_state") == "VALIDATED"
                and _text(raw.get("net_proceeds_basis_ref"))
                and _text(raw.get("cost_basis_ref"))
                and _number(proceeds) and proceeds > 0 and _number(annual) and annual >= 0):
            row["effective_preferred_funding_cost"] = _calc(out, key + ".cost",
                [annual, proceeds], lambda a, b: a / b)
            row["calculation_inputs"].update(verified_net_proceeds_usd=proceeds,
                annual_preferred_distributions_usd=annual,
                net_proceeds_basis_ref=raw["net_proceeds_basis_ref"], cost_basis_ref=raw["cost_basis_ref"])
        else:
            _block(out, key + ".cost", "VERIFIED_NET_PROCEEDS_AND_COST_BASIS_REQUIRED")
        # Annual run-rate is context, not today's liability. No future carry is
        # subtracted; only explicitly verified, realized reserve/claim deltas.
        if raw.get("reserve_change_state") == "REALIZED_VERIFIED":
            row["claim_adjusted_reserve_delta_usd"] = _calc(out, key + ".reserve",
                [row["components"]["RESERVE_ACTION"], row["components"]["CLAIM_ACTION"]], lambda a, b: a - b)
        else:
            _block(out, key + ".reserve", "REALIZED_RESERVE_CHANGE_REQUIRED")
        out["events"].append(row)
    return _finish(out, bool(out["events"]))


def build_treasury_valuation_context(*, asset_id: str, as_of_ms: int,
        mnav_history: Any = None, asset_history: Any = None,
        preferred_funding_events: Any = None, benchmark: Any = None,
        history_coverage: str = "UNSPECIFIED") -> dict:
    if asset_id not in ISSUERS or not _time(as_of_ms):
        raise ValueError("MSTR/ASST and positive as-of required")
    out = _section()
    out.update(schema_version=VALUATION_VERSION, asset_id=asset_id,
        as_of=as_of_ms, action_output="NONE", external_action_authority="NONE",
        capital_decision_authority="USER_ONLY", machine_execution="FORBIDDEN",
        production="NOT_APPROVED", calculation_version=VALUATION_VERSION)
    out["history_coverage"] = history_coverage
    rows = _valuation_history(mnav_history, asset_id, as_of_ms, out)
    current = rows[-1] if rows else None
    out["mnav_observations"] = rows
    out["current_observation"] = current
    out["diluted_mnav"] = current["mnav"] if current else None
    out["source_semantic"] = current["source_semantic"] if current else None
    out["evidence_authority"] = current["evidence_authority"] if current else "BLOCKED"
    out["formal_action_critical_state"] = (
        "AVAILABLE" if current and current["evidence_authority"] == "FORMAL_ACTION_CRITICAL" else "BLOCKED")
    baseline = [r for r in rows[:-1] if r and current and _same_valuation_basis(r, current)]
    out["own_history_empirical_cdf_pct"] = _cdf(current, baseline)
    # Main has candidate weather outputs but no PIT history binding to issuer
    # mNAV observations. Never synthesize a bull/bear router from those outputs.
    out["regime_empirical_cdf_pct"] = {**_cdf(None, [], reason="PIT_REGIME_BINDING_UNAVAILABLE"),
        "regime_identity": None}
    benchmark_id = benchmark.get("identity") if isinstance(benchmark, dict) else None
    b_rows = []
    if _text(benchmark_id) and benchmark.get("asset_id") in ISSUERS:
        b_rows = _valuation_history(benchmark.get("history"), benchmark["asset_id"], as_of_ms, out)
    b_rows = [r for r in b_rows if r and current and r["effective_time"] < current["effective_time"]
              and _same_valuation_basis(r, current)]
    out["benchmark_empirical_cdf_pct"] = {**_cdf(current, b_rows,
        reason="COMPARABLE_BENCHMARK_HISTORY_UNAVAILABLE"), "benchmark_identity": benchmark_id}
    five = _claim("FIVE_WEEK_COMPARABLE_OBSERVATION_UNAVAILABLE")
    five["policy"] = "NEAREST_35D_PLUS_MINUS_3D_TIE_EARLIER_NO_INTERPOLATION"
    if current:
        target = current["effective_time"] - 35 * DAY_MS
        candidates = [r for r in baseline if abs(r["effective_time"] - target) <= 3 * DAY_MS]
        if candidates:
            prior = min(candidates, key=lambda r: (abs(r["effective_time"] - target), r["effective_time"]))
            delta = _calc(out, "five_week_mnav_change_pct", [current["mnav"], prior["mnav"]], lambda a, b: a / b - 1)
            if delta is not None:
                five.update(state="AVAILABLE", value=delta, reason="COMPARABLE_OBSERVATIONS",
                    previous=prior, current=current, observation_span_ms=current["effective_time"] - prior["effective_time"])
    out["five_week_mnav_change_pct"] = five
    # Reuse CT's ratio and comparison algorithm. Research rows cannot provide
    # official holdings/shares; invalid visible rows remain holes, not fallbacks.
    official_assets = []
    for raw in asset_history if isinstance(asset_history, list) else []:
        if isinstance(raw, dict) and _time(raw.get("retrieval_time")) and raw["retrieval_time"] > as_of_ms:
            continue
        record = deepcopy(raw)
        check = _section()
        valid = _metadata(raw, check, "btc_share", ISSUERS[asset_id], as_of_ms, "AUDIT_REPLAY")
        if (not valid or raw.get("source_class") not in OFFICIAL_CLASSES or
                (raw.get("source_semantic") or {}).get("identity") in {RESEARCH_IDENTITY, LEGACY_RESEARCH_IDENTITY}):
            record = {**raw, "verification_state": "BLOCKED"} if isinstance(raw, dict) else raw
        official_assets.append(record)
    per_share = _asset(official_assets, ISSUERS[asset_id], as_of_ms)
    out["btc_per_diluted_share"] = per_share
    for label in ("current", "previous"):
        out[label + "_btc_per_diluted_share"] = (per_share[label] or {}).get("btc_per_diluted_share")
    out["btc_per_diluted_share_change_pct"] = per_share["btc_per_diluted_share_change_pct"]
    out["preferred_funding_attribution"] = build_preferred_funding_attribution(
        events=preferred_funding_events, issuer_id=ISSUERS[asset_id], as_of_ms=as_of_ms)
    for field in ("own_history_empirical_cdf_pct", "regime_empirical_cdf_pct",
                  "benchmark_empirical_cdf_pct", "five_week_mnav_change_pct"):
        if out[field]["state"] == "BLOCKED":
            _block(out, field, out[field]["reason"])
    if out["formal_action_critical_state"] == "BLOCKED":
        _block(out, "formal_action_critical", "OFFICIAL_COMPARABLE_MNAV_INPUTS_REQUIRED")
    for name, section in (("btc_per_diluted_share", per_share),
                          ("preferred_funding_attribution", out["preferred_funding_attribution"])):
        out["blockers"].extend({**b, "claim": name + "." + b["claim"]} for b in section["blockers"])
    _finish(out, current is not None or out["current_btc_per_diluted_share"] is not None)
    out["context_hash"] = _digest(out)
    return out


def add_treasury_valuation_context(pack: dict, inputs: dict) -> None:
    if not isinstance(inputs, dict) or set(inputs) - set(ISSUERS):
        raise ValueError("Treasury context input must map MSTR/ASST")
    for asset in ISSUERS:
        context = build_treasury_valuation_context(asset_id=asset,
            as_of_ms=pack["generated_at_ms"], **inputs.get(asset, {}))
        pack["asset_facts"]["items"].append({"asset_fact_id": VALUATION_VERSION + ":" + asset,
            "fact_type": "TREASURY_VALUATION_CONTEXT", "issuer_id": ISSUERS[asset],
            "asset_id": asset, "evidence": context})
    pack["asset_facts"].pop("empty_reason", None)
    if pack["asset_facts"].get("section_state") == "READY":
        pack["asset_facts"]["section_state"] = "PARTIAL"
    # Preserve contributor provenance without claiming its old hash covers the
    # newly attached evidence; the enclosing pack is hashed after this call.
    if "overlay_hash" in pack["asset_facts"]:
        pack["asset_facts"]["upstream_overlay_hash"] = pack["asset_facts"].pop("overlay_hash")


def compact_treasury_valuation_context(pack: dict) -> dict:
    result = {}
    for fact in pack.get("asset_facts", {}).get("items", []):
        if fact.get("fact_type") != "TREASURY_VALUATION_CONTEXT":
            continue
        context = deepcopy(fact["evidence"])
        digest = context.pop("context_hash", None)
        if digest != _digest(context):
            raise ValueError("Treasury valuation context hash mismatch")
        asset = context["asset_id"]
        if asset in result or asset not in ISSUERS:
            raise ValueError("Duplicate or unsupported Treasury context")
        row = {k: context[k] for k in ("diluted_mnav", "source_semantic", "as_of",
            "evidence_authority", "formal_action_critical_state", "current_btc_per_diluted_share",
            "previous_btc_per_diluted_share", "btc_per_diluted_share_change_pct")}
        row["source_semantic"] = (context["source_semantic"] or {}).get("identity")
        current_bps = context["btc_per_diluted_share"]["current"] or {}
        row["btc_share_basis"] = current_bps.get("basis_ref")
        row["btc_share_as_of"] = current_bps.get("effective_time")
        row["mnav_as_of"] = (context["current_observation"] or {}).get("effective_time")
        row["baseline_counts"] = {}
        for label, name in (("own", "own_history_empirical_cdf_pct"),
                ("regime", "regime_empirical_cdf_pct"), ("benchmark", "benchmark_empirical_cdf_pct")):
            row[name] = context[name]["value"]
            row["baseline_counts"][label] = context[name]["baseline_count"]
        row["benchmark_identity"] = context["benchmark_empirical_cdf_pct"]["benchmark_identity"]
        row["five_week_mnav_change_pct"] = context["five_week_mnav_change_pct"]["value"]
        funding = context["preferred_funding_attribution"]
        row["preferred_funding_attribution_summary"] = {"state": funding["state"], "research_only": True,
            "events": [{k: e[k] for k in ("event_id", "components", "effective_preferred_funding_cost",
                "claim_adjusted_reserve_delta_usd")} for e in funding["events"]]}
        row.update(quality_state=context["state"], context_hash=digest,
            blockers=sorted({b["code"] for b in context["blockers"]
                if b["claim"] != "btc_per_diluted_share.growth_direction"}))
        result[asset] = row
    return result
