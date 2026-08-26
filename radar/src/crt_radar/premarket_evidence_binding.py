from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .issuer_fact_history import (
    latest_fact,
    latest_previous_delta,
    recent_numeric_changes,
    same_source_bundle,
    select_fact_history,
)

STRATEGY_ISSUER_ID = "CIK-0001050446"
STRC_SECURITY_ID = "SEC-STRC-PERP"
VERIFIED_EMPTY = "VERIFIED_NO_MATCH"


def _blocked(reason: str, value: Any = None) -> dict[str, Any]:
    return {"state": "BLOCKED", "reason": reason, "value": value}


def _available(value: Any, **extra: Any) -> dict[str, Any]:
    return {"state": "AVAILABLE", "value": value, **extra}


def _normalize_evaluation_window(
    evaluation_window: dict[str, Any] | None,
) -> dict[str, int] | None:
    if not isinstance(evaluation_window, dict):
        return None

    start_ms = evaluation_window.get("start_ms")
    end_ms = evaluation_window.get("end_ms")

    if (
        not isinstance(start_ms, int)
        or isinstance(start_ms, bool)
        or not isinstance(end_ms, int)
        or isinstance(end_ms, bool)
        or start_ms <= 0
        or end_ms < start_ms
    ):
        return None

    return {"start_ms": start_ms, "end_ms": end_ms}


def _event_binding(
    overlay: dict[str, Any] | None,
    *,
    evaluation_window: dict[str, Any] | None,
) -> dict[str, Any]:
    window = _normalize_evaluation_window(evaluation_window)
    if window is None:
        return {
            "state": "BLOCKED",
            "event_state": None,
            "reason": "ISSUER_EVENT_EVALUATION_WINDOW_REQUIRED",
        }

    if not isinstance(overlay, dict):
        return {
            "state": "BLOCKED",
            "event_state": None,
            "reason": "REFLEXIVITY_OVERLAY_MISSING",
        }

    section = overlay.get("decision_relevant_events")
    if not isinstance(section, dict):
        return {
            "state": "BLOCKED",
            "event_state": None,
            "reason": "ISSUER_EVENT_SECTION_MISSING",
        }

    if (
        section.get("section_state") != "READY"
        or section.get("coverage_state") != "COMPLETE"
    ):
        return {
            "state": (
                "BLOCKED"
                if section.get("section_state") == "BLOCKED"
                else "PARTIAL"
            ),
            "event_state": None,
            "reason": "ISSUER_EVENT_COVERAGE_INCOMPLETE",
            "items": deepcopy(section.get("items", [])),
        }

    items = section.get("items")
    if not isinstance(items, list):
        return {
            "state": "BLOCKED",
            "event_state": None,
            "reason": "ISSUER_EVENT_ITEMS_MISSING",
        }

    if not items and section.get("empty_reason") != VERIFIED_EMPTY:
        return {
            "state": "BLOCKED",
            "event_state": None,
            "reason": "ISSUER_EVENT_EMPTY_STATE_UNVERIFIED",
        }

    selected = []
    for item in items:
        if not isinstance(item, dict):
            return {
                "state": "BLOCKED",
                "event_state": None,
                "reason": "ISSUER_EVENT_ITEM_INVALID",
            }

        disclosure = item.get("disclosure_window")
        if not isinstance(disclosure, dict):
            return {
                "state": "BLOCKED",
                "event_state": None,
                "reason": "ISSUER_EVENT_DISCLOSURE_WINDOW_MISSING",
            }

        start_ms = disclosure.get("start_ms")
        end_ms = disclosure.get("end_ms")
        if (
            not isinstance(start_ms, int)
            or isinstance(start_ms, bool)
            or not isinstance(end_ms, int)
            or isinstance(end_ms, bool)
            or start_ms <= 0
            or end_ms < start_ms
        ):
            return {
                "state": "BLOCKED",
                "event_state": None,
                "reason": "ISSUER_EVENT_DISCLOSURE_WINDOW_INVALID",
            }

        intersects = (
            end_ms >= window["start_ms"]
            and start_ms <= window["end_ms"]
        )
        if intersects:
            selected.append(deepcopy(item))

    if not selected:
        return {
            "state": "VALID",
            "event_state": "NO_NEW_MATERIAL_ISSUER_EVENT",
            "items": [],
            "evaluation_window": deepcopy(window),
        }

    return {
        "state": "VALID",
        "event_state": "MATERIAL_ISSUER_EVENT_PRESENT",
        "items": selected,
        "evaluation_window": deepcopy(window),
    }


def _latest_wrapper(history: dict[str, Any]) -> dict[str, Any]:
    latest = latest_fact(history)

    if latest.get("state") == "BLOCKED":
        return _blocked(latest.get("reason", "LATEST_FACT_BLOCKED"))

    result = {
        "state": latest.get("state", "PARTIAL"),
        "value": latest.get("value"),
        "effective_at_ms": latest.get("effective_at_ms"),
        "unit": latest.get("unit"),
        "source_refs": deepcopy(latest.get("source_refs", [])),
        "source_hashes": deepcopy(latest.get("source_hashes", [])),
    }

    if latest.get("reason") is not None:
        result["reason"] = latest["reason"]

    return result


def _per_share(
    btc_latest: dict[str, Any],
    shares_latest: dict[str, Any],
) -> dict[str, Any]:
    if (
        btc_latest.get("state") != "AVAILABLE"
        or shares_latest.get("state") != "AVAILABLE"
    ):
        return _blocked("PER_SHARE_INPUT_NOT_AVAILABLE")

    if not same_source_bundle(btc_latest, shares_latest):
        return _blocked("PER_SHARE_SOURCE_BUNDLE_MISMATCH")

    btc = btc_latest.get("value")
    shares = shares_latest.get("value")

    if (
        not isinstance(btc, (int, float))
        or isinstance(btc, bool)
        or not isinstance(shares, (int, float))
        or isinstance(shares, bool)
        or not math.isfinite(float(btc))
        or not math.isfinite(float(shares))
        or float(shares) <= 0
    ):
        return _blocked("PER_SHARE_INPUT_INVALID")

    return _available(float(btc) / float(shares))


def _mnav_wrapper(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return _blocked("MNAV_RESULT_NOT_SUPPLIED")

    if result.get("state") != "AVAILABLE":
        return _blocked(result.get("reason", "MNAV_NOT_AVAILABLE"))

    value = result.get("mnav")

    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        return _blocked("MNAV_RESULT_INVALID")

    return {"state": "AVAILABLE", "mnav": float(value)}


def _issuer_events_for_identity(
    overlay: dict[str, Any] | None,
    *,
    issuer_id: str | None,
    security_id: str | None,
    evaluation_window: dict[str, Any] | None,
) -> dict[str, Any]:
    binding = _event_binding(
        overlay,
        evaluation_window=evaluation_window,
    )

    if binding.get("state") != "VALID":
        return _blocked(
            binding.get("reason", "ISSUER_EVENTS_NOT_AVAILABLE")
        )

    if binding.get("event_state") == "NO_NEW_MATERIAL_ISSUER_EVENT":
        return _available([])

    selected = []

    for item in binding.get("items", []):
        if not isinstance(item, dict):
            continue
        if issuer_id is not None and item.get("issuer_id") != issuer_id:
            continue
        if (
            security_id is not None
            and item.get("security_id") not in {security_id, None}
        ):
            continue

        selected.append(deepcopy(item))

    return _available(selected)


def _bind_growth_asset(
    overlay: dict[str, Any] | None,
    *,
    spec: dict[str, Any] | None,
    mnav_result: dict[str, Any] | None,
    evaluation_window: dict[str, Any] | None,
) -> dict[str, Any]:
    fields = {
        "premarket_price": _blocked("LIVE_MARKET_DATA_OUT_OF_SCOPE"),
        "diluted_mnav": _mnav_wrapper(mnav_result),
        "btc_holdings_current": _blocked("BINDING_SPEC_MISSING"),
        "btc_holdings_last_3": _blocked("BINDING_SPEC_MISSING"),
        "btc_per_diluted_share": _blocked("BINDING_SPEC_MISSING"),
        "diluted_shares": _blocked("BINDING_SPEC_MISSING"),
        "atm_issuance": _blocked("BINDING_SPEC_MISSING"),
        "dilution_accretion": _blocked("BINDING_SPEC_MISSING"),
        "issuer_events": _blocked("BINDING_SPEC_MISSING"),
    }

    if not isinstance(spec, dict):
        return fields

    issuer_id = spec.get("issuer_id")
    security_id = spec.get("security_id")
    btc_type = spec.get("btc_holdings_fact_type")
    shares_type = spec.get("diluted_shares_fact_type")

    if not all(
        isinstance(value, str) and value
        for value in (issuer_id, security_id, btc_type, shares_type)
    ):
        return fields

    btc_history = select_fact_history(
        overlay,
        fact_type=btc_type,
        issuer_id=issuer_id,
        security_id=security_id,
    )

    shares_history = select_fact_history(
        overlay,
        fact_type=shares_type,
        issuer_id=issuer_id,
        security_id=security_id,
    )

    btc_latest = latest_fact(btc_history)
    shares_latest = latest_fact(shares_history)

    fields["btc_holdings_current"] = _latest_wrapper(btc_history)

    changes = recent_numeric_changes(btc_history, changes=3)
    fields["btc_holdings_last_3"] = {
        "state": changes["state"],
        "reason": changes.get("reason"),
        "value": deepcopy(changes.get("value", [])),
    }

    fields["diluted_shares"] = _latest_wrapper(shares_history)
    fields["btc_per_diluted_share"] = _per_share(
        btc_latest,
        shares_latest,
    )

    atm_type = spec.get("atm_issuance_fact_type")
    if isinstance(atm_type, str) and atm_type:
        fields["atm_issuance"] = _latest_wrapper(
            select_fact_history(
                overlay,
                fact_type=atm_type,
                issuer_id=issuer_id,
                security_id=security_id,
            )
        )

    dilution_type = spec.get("dilution_accretion_fact_type")
    if isinstance(dilution_type, str) and dilution_type:
        fields["dilution_accretion"] = _latest_wrapper(
            select_fact_history(
                overlay,
                fact_type=dilution_type,
                issuer_id=issuer_id,
                security_id=security_id,
            )
        )

    fields["issuer_events"] = _issuer_events_for_identity(
        overlay,
        issuer_id=issuer_id,
        security_id=security_id,
        evaluation_window=evaluation_window,
    )

    return fields


def _build_strc_rounds(
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    shares_history = select_fact_history(
        overlay,
        fact_type="REPURCHASED_SHARES",
        issuer_id=STRATEGY_ISSUER_ID,
        security_id=STRC_SECURITY_ID,
    )

    cash_history = select_fact_history(
        overlay,
        fact_type="REPURCHASE_CASH_CONSIDERATION",
        issuer_id=STRATEGY_ISSUER_ID,
        security_id=STRC_SECURITY_ID,
    )

    shares_items = shares_history.get("items", [])
    cash_items = cash_history.get("items", [])

    if not isinstance(shares_items, list) or not isinstance(cash_items, list):
        return _blocked("STRC_REPURCHASE_HISTORY_MISSING", [])

    if not isinstance(overlay, dict):
        return _blocked("STRC_REPURCHASE_EVENT_SECTION_MISSING", [])

    event_section = overlay.get("decision_relevant_events")
    if not isinstance(event_section, dict):
        return _blocked("STRC_REPURCHASE_EVENT_SECTION_MISSING", [])

    events = event_section.get("items")
    if not isinstance(events, list):
        return _blocked("STRC_REPURCHASE_EVENT_ITEMS_MISSING", [])

    cash_by_id = {
        item.get("asset_fact_id"): item
        for item in cash_items
        if isinstance(item, dict)
    }

    event_by_fact_id: dict[str, dict[str, Any]] = {}

    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("issuer_id") != STRATEGY_ISSUER_ID:
            continue
        if event.get("security_id") != STRC_SECURITY_ID:
            continue
        if event.get("event_type") != "SECURITY_REPURCHASE":
            continue
        if event.get("active_for_calculation") is not True:
            continue

        execution = event.get("execution_window")
        if not isinstance(execution, dict):
            continue

        start_ms = execution.get("start_ms")
        end_ms = execution.get("end_ms")
        if (
            not isinstance(start_ms, int)
            or isinstance(start_ms, bool)
            or not isinstance(end_ms, int)
            or isinstance(end_ms, bool)
            or start_ms <= 0
            or end_ms < start_ms
        ):
            continue

        reported = event.get("reported_values")
        if not isinstance(reported, list):
            continue

        for reported_value in reported:
            if not isinstance(reported_value, dict):
                continue
            fact_id = reported_value.get("fact_id")
            if isinstance(fact_id, str) and fact_id:
                event_by_fact_id[fact_id] = event

    rounds = []
    unmatched = 0
    cumulative_shares = 0.0
    cumulative_cash = 0.0

    for share_item in shares_items:
        share_fact_id = share_item.get("asset_fact_id")
        event = event_by_fact_id.get(share_fact_id)

        if not isinstance(event, dict):
            unmatched += 1
            continue

        reported = event.get("reported_values", [])
        cash_fact_ids = [
            row.get("fact_id")
            for row in reported
            if (
                isinstance(row, dict)
                and row.get("unit") == "USD"
                and isinstance(row.get("fact_id"), str)
            )
        ]

        matching_cash = [
            cash_by_id[fact_id]
            for fact_id in cash_fact_ids
            if fact_id in cash_by_id
        ]

        if len(matching_cash) != 1:
            unmatched += 1
            continue

        cash_item = matching_cash[0]

        if not same_source_bundle(share_item, cash_item):
            unmatched += 1
            continue

        shares = share_item.get("value")
        cash = cash_item.get("value")

        if (
            not isinstance(shares, (int, float))
            or isinstance(shares, bool)
            or not isinstance(cash, (int, float))
            or isinstance(cash, bool)
        ):
            unmatched += 1
            continue

        execution = event["execution_window"]
        shares_f = float(shares)
        cash_f = float(cash)

        cumulative_shares += shares_f
        cumulative_cash += cash_f

        rounds.append(
            {
                "round_id": len(rounds) + 1,
                "execution_start_ms": execution["start_ms"],
                "execution_end_ms": execution["end_ms"],
                "effective_at_ms": share_item["effective_at_ms"],
                "shares": shares_f,
                "cash_usd": cash_f,
                "avg_price": (
                    None
                    if shares_f == 0
                    else cash_f / shares_f
                ),
                "cumulative_shares": cumulative_shares,
                "cumulative_cash_usd": cumulative_cash,
                "event_id": event.get("event_id"),
                "source_refs": deepcopy(
                    share_item.get("source_refs", [])
                ),
            }
        )

    if not rounds:
        return _blocked("STRC_REPURCHASE_ROUNDS_NOT_BOUND", [])

    complete = (
        shares_history.get("state") == "AVAILABLE"
        and cash_history.get("state") == "AVAILABLE"
        and len(rounds) >= 5
        and unmatched == 0
    )

    return {
        "state": "AVAILABLE" if complete else "PARTIAL",
        "reason": (
            "STRC_REPURCHASE_ROUNDS_READY"
            if complete
            else "STRC_REPURCHASE_ROUNDS_PARTIAL"
        ),
        "value": rounds,
        "unmatched_round_facts": unmatched,
    }


def _bind_strc(
    overlay: dict[str, Any] | None,
    *,
    evaluation_window: dict[str, Any] | None,
) -> dict[str, Any]:
    rounds = _build_strc_rounds(overlay)
    values = rounds.get("value")

    latest = _blocked("STRC_REPURCHASE_ROUNDS_NOT_AVAILABLE")
    cumulative = _blocked("STRC_REPURCHASE_ROUNDS_NOT_AVAILABLE")

    if isinstance(values, list) and values:
        latest = {
            "state": rounds["state"],
            "reason": rounds.get("reason"),
            "value": deepcopy(values[-1]),
        }

        cumulative = {
            "state": rounds["state"],
            "reason": rounds.get("reason"),
            "value": {
                "shares": values[-1]["cumulative_shares"],
                "cash_usd": values[-1]["cumulative_cash_usd"],
            },
        }

    return {
        "premarket_price": _blocked("LIVE_MARKET_DATA_OUT_OF_SCOPE"),
        "repurchase_rounds": rounds,
        "latest_round": latest,
        "cumulative_repurchase": cumulative,
        "next_ex_dividend_date": _blocked(
            "DIVIDEND_TERMS_ADAPTER_NOT_BOUND"
        ),
        "record_date": _blocked(
            "DIVIDEND_TERMS_ADAPTER_NOT_BOUND"
        ),
        "payment_date": _blocked(
            "DIVIDEND_TERMS_ADAPTER_NOT_BOUND"
        ),
        "distribution_rate": _blocked(
            "DIVIDEND_TERMS_ADAPTER_NOT_BOUND"
        ),
        "market_handoff": _blocked(
            "MARKET_RESPONSE_DATA_OUT_OF_SCOPE"
        ),
        "issuer_events": _issuer_events_for_identity(
            overlay,
            issuer_id=STRATEGY_ISSUER_ID,
            security_id=STRC_SECURITY_ID,
            evaluation_window=evaluation_window,
        ),
    }


def _bind_asst_extra(
    fields: dict[str, Any],
    spec: dict[str, Any] | None,
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(fields)

    result["dilution"] = _blocked(
        "ASST_DILUTION_FACT_NOT_BOUND"
    )
    result["sata_burden"] = _blocked(
        "ASST_SATA_BURDEN_FACT_NOT_BOUND"
    )
    result["warrants"] = _blocked(
        "ASST_WARRANT_FACT_NOT_BOUND"
    )

    result["short_interest"] = _blocked(
        "LIVE_SHORT_DATA_OUT_OF_SCOPE"
    )
    result["gamma"] = _blocked(
        "LIVE_OPTIONS_DATA_OUT_OF_SCOPE"
    )
    result["options_vs_spot"] = _blocked(
        "LIVE_OPTIONS_DATA_OUT_OF_SCOPE"
    )

    if isinstance(spec, dict):
        issuer_id = spec.get("issuer_id")
        security_id = spec.get("security_id")

        mapping = {
            "dilution": "dilution_fact_type",
            "sata_burden": "sata_burden_fact_type",
            "warrants": "warrants_fact_type",
        }

        for field, spec_key in mapping.items():
            fact_type = spec.get(spec_key)

            if (
                isinstance(fact_type, str)
                and fact_type
                and isinstance(issuer_id, str)
                and isinstance(security_id, str)
            ):
                result[field] = _latest_wrapper(
                    select_fact_history(
                        overlay,
                        fact_type=fact_type,
                        issuer_id=issuer_id,
                        security_id=security_id,
                    )
                )

    return result


def _bind_sata(
    overlay: dict[str, Any] | None,
    spec: dict[str, Any] | None,
    *,
    evaluation_window: dict[str, Any] | None,
) -> dict[str, Any]:
    result = {
        "premarket_price": _blocked("LIVE_MARKET_DATA_OUT_OF_SCOPE"),
        "strive_strc_holdings_current": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
        "strive_strc_holdings_previous": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
        "strive_strc_holdings_delta": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
        "strive_strc_fair_value": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
        "distribution_rate": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
        "stated_amount": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
        "liquidation_preference": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
        "issuer_events": _blocked(
            "SATA_BINDING_SPEC_MISSING"
        ),
    }

    if not isinstance(spec, dict):
        return result

    issuer_id = spec.get("issuer_id")
    security_id = spec.get("security_id")
    holdings_type = spec.get(
        "strive_strc_holdings_fact_type"
    )

    if not all(
        isinstance(value, str) and value
        for value in (
            issuer_id,
            security_id,
            holdings_type,
        )
    ):
        return result

    history = select_fact_history(
        overlay,
        fact_type=holdings_type,
        issuer_id=issuer_id,
        security_id=security_id,
    )

    trio = latest_previous_delta(history)

    result["strive_strc_holdings_current"] = trio["current"]
    result["strive_strc_holdings_previous"] = trio["previous"]
    result["strive_strc_holdings_delta"] = trio["delta"]

    for field, key in (
        (
            "strive_strc_fair_value",
            "strive_strc_fair_value_fact_type",
        ),
        (
            "distribution_rate",
            "distribution_rate_fact_type",
        ),
        (
            "stated_amount",
            "stated_amount_fact_type",
        ),
        (
            "liquidation_preference",
            "liquidation_preference_fact_type",
        ),
    ):
        fact_type = spec.get(key)

        if isinstance(fact_type, str) and fact_type:
            result[field] = _latest_wrapper(
                select_fact_history(
                    overlay,
                    fact_type=fact_type,
                    issuer_id=issuer_id,
                    security_id=security_id,
                )
            )

    result["issuer_events"] = _issuer_events_for_identity(
        overlay,
        issuer_id=issuer_id,
        security_id=security_id,
        evaluation_window=evaluation_window,
    )

    return result


def build_premarket_evidence_binding(
    *,
    reflexivity_overlay: dict[str, Any] | None,
    evaluation_window: dict[str, Any] | None = None,
    growth_specs: dict[str, Any] | None = None,
    sata_spec: dict[str, Any] | None = None,
    mnav_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    specs = (
        growth_specs
        if isinstance(growth_specs, dict)
        else {}
    )

    mnav = (
        mnav_results
        if isinstance(mnav_results, dict)
        else {}
    )

    mstr = _bind_growth_asset(
        reflexivity_overlay,
        spec=specs.get("MSTR"),
        mnav_result=mnav.get("MSTR"),
        evaluation_window=evaluation_window,
    )

    asst = _bind_growth_asset(
        reflexivity_overlay,
        spec=specs.get("ASST"),
        mnav_result=mnav.get("ASST"),
        evaluation_window=evaluation_window,
    )

    asst = _bind_asst_extra(
        asst,
        specs.get("ASST"),
        reflexivity_overlay,
    )

    return {
        "issuer_reflexivity": _event_binding(
            reflexivity_overlay,
            evaluation_window=evaluation_window,
        ),
        "asset_facts": {
            "MSTR": mstr,
            "ASST": asst,
            "STRC": _bind_strc(
                reflexivity_overlay,
                evaluation_window=evaluation_window,
            ),
            "SATA": _bind_sata(
                reflexivity_overlay,
                sata_spec,
                evaluation_window=evaluation_window,
            ),
        },
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
    }