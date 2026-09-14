"""Non-weighted company evidence; normalized, source-verified inputs only.

No collection, investment diagnosis, formal model change, or external action.
See docs/TREASURY_COMPANY_CT_V0.1.md for the input and comparison contract.
"""
from __future__ import annotations

import math
import hashlib
import json
from collections import Counter
from copy import deepcopy
from typing import Any

from .diluted_equity_mnav import (
    SCHEMA_VERSION as MNAV_SCHEMA_VERSION,
    build_diluted_equity_mnav,
)

SCHEMA_VERSION = "CRT_TREASURY_COMPANY_CT_V0.1"
OVERLAY_TYPE = "NON_WEIGHTED_EVIDENCE_OVERLAY"
FORMAL_MNAV_REF = "radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md"


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


def _metadata(raw: Any, section: dict, claim: str, issuer: str, as_of: int) -> dict | None:
    if not isinstance(raw, dict):
        _block(section, claim, "EVIDENCE_MISSING_OR_INVALID")
        return None
    if (raw.get("issuer_id") != issuer or not _text(raw.get("source_ref"))
            or raw.get("verification_state") != "VALIDATED"):
        _block(section, claim, "SOURCE_OR_ISSUER_NOT_VALIDATED")
        return None
    effective, available = raw.get("effective_at_ms"), raw.get("available_at_ms")
    if not (_time(effective) and _time(available) and effective <= available <= as_of):
        _block(section, claim, "EVIDENCE_TIME_INVALID_OR_FUTURE")
        return None
    return {key: raw[key] for key in (
        "issuer_id", "source_ref", "verification_state", "effective_at_ms", "available_at_ms"
    )}


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
                and previous["effective_at_ms"] < current["effective_at_ms"])


def _asset(history: Any, issuer: str, as_of: int) -> dict:
    out = _section()
    out.update(observations=[], current=None, previous=None,
               btc_per_diluted_share_change_pct=None, direction=None,
               observation_span_ms=None, growth_observations=[], growth_direction=None)
    if not isinstance(history, list) or not history:
        _block(out, "asset_history", "ASSET_HISTORY_MISSING")
        return out
    dated = [row for row in history if isinstance(row, dict) and _time(row.get("effective_at_ms"))]
    counts = Counter(row["effective_at_ms"] for row in dated)
    invalid_time = len(dated) != len(history)
    if invalid_time:
        _block(out, "current", "ASSET_TIME_UNKNOWN")
    rows = []
    for index, raw in enumerate(sorted(dated, key=lambda row: row["effective_at_ms"])):
        claim = f"asset_history[{index}]"
        row = _metadata(raw, out, claim, issuer, as_of)
        if counts[raw["effective_at_ms"]] != 1:
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
            "from_ms": previous["effective_at_ms"], "to_ms": current["effective_at_ms"],
            "span_ms": current["effective_at_ms"] - previous["effective_at_ms"],
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
            if meta and _text(record.get("cost_basis_ref")) and previous.get("cost_basis_ref") == record["cost_basis_ref"] and meta["effective_at_ms"] < row["effective_at_ms"]:
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
    out["events"].sort(key=lambda row: (row["effective_at_ms"], row["event_id"]))
    # No cross-event sum: accounting scopes may overlap even when IDs differ.
    return _finish(out, bool(out["events"]) or out.get("empty_reason") == "VERIFIED_NO_MATCH")


def _price(raw: Any, issuer: str, as_of: int) -> dict:
    out = _section()
    out.update(mnav=None, semantic_ref=None)
    meta = _metadata(raw, out, "price_financing_state", issuer, as_of)
    if meta is None:
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
