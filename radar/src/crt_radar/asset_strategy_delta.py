from __future__ import annotations

import calendar
import re
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .broker_capital_observation import _hash, validate_broker_observation
from .issuer_announcement_runner import validate_issuer_announcement_wake

SCHEMA_VERSION = "CRT_ASSET_STRATEGY_DELTA_V0.2"
INCOME_INPUT_SCHEMA = "CRT_FIXED_INCOME_INPUTS_V0.1"
INCOME_SCHEMA = "CRT_DUAL_FIXED_INCOME_V0.1"
_ISSUERS = {"STRC": ("STRATEGY_INC", "CIK-0001050446", "SEC-STRC-PERP", "STRATEGY_OFFICIAL_CAPITAL_DISCLOSURE"),
            "SATA": ("STRIVE_INC", "CIK-0001920406", "SATA", "STRIVE_OFFICIAL_CAPITAL_DISCLOSURE")}
_FORECAST_INVALIDATION = {"RATE_CHANGE", "POSITION_CHANGE", "TAX_CHANGE", "ISSUER_NONPAYMENT", "CAPITAL_QUALIFICATION_LOST"}


def _amount(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("INCOME_AMOUNT_INVALID")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("INCOME_AMOUNT_INVALID") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("INCOME_AMOUNT_INVALID")
    return number


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _component(reason: str) -> dict[str, Any]:
    return {"state": "BLOCKED", "gross_usd": None, "net_usd": None, "reason": reason}


def _period(inputs: dict[str, Any]) -> dict[str, int] | None:
    period = inputs.get("period") or {}
    try:
        start, end = period["start_ms"], period["end_ms"]
        if type(start) is not int or type(end) is not int or not 0 < start < end:
            return None
        return {"start_ms": start, "end_ms": end}
    except (KeyError, TypeError, ValueError):
        return None


def _six_month_period(period: dict[str, int] | None) -> bool:
    if period is None:
        return False
    try:
        start, end = period["start_ms"], period["end_ms"]
        date = datetime.fromtimestamp(start / 1000, timezone.utc)
        month = date.month + 6
        year = date.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        six_month_end = date.replace(year=year, month=month, day=min(date.day, calendar.monthrange(year, month)[1]))
        return end == int(six_month_end.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError, OSError):
        return False


def _content_valid(record: Any, *, source: str, at_ms: int, period: dict[str, int] | None) -> bool:
    """Check content integrity and binding, never external source authenticity."""
    expected_state = {"IBKR_STATEMENT": "AVAILABLE", "TAX_EVIDENCE": "AVAILABLE",
                      "USER_CONFIRMED": "CONFIRMED", "ANALYST_ASSUMPTIONS": "ASSUMPTIONS_ONLY"}[source]
    if (not isinstance(record, dict) or period is None or record.get("source") != source
            or record.get("state") != expected_state):
        return False
    try:
        ref = record["source_ref"]
        return (record.get("proof_hash") == _hash({k: v for k, v in record.items() if k != "proof_hash"})
                and record.get("period") == period
                and type(record.get("as_of_ms")) is int and 0 < record["as_of_ms"] <= at_ms
                and type(record.get("valid_until_ms")) is int and at_ms < record["valid_until_ms"]
                and isinstance(ref, dict) and re.fullmatch(r"[0-9a-f]{64}", ref.get("evidence_hash", "")) is not None
                and type(ref.get("source_as_of_ms")) is int and 0 < ref["source_as_of_ms"] <= record["as_of_ms"])
    except (ValueError, TypeError, KeyError):
        return False


def _public_proof(record: dict[str, Any]) -> dict[str, Any]:
    # Never export broker account identifiers, paths or full statement rows.
    return {"source": record["source"], "proof_hash": record["proof_hash"],
            "evidence_hash": record["source_ref"]["evidence_hash"],
            "source_as_of_ms": record["source_ref"]["source_as_of_ms"],
            "content_integrity": "VALID", "source_trust": "NOT_EXTERNALLY_VERIFIED"}


def _official_terms(wakes: list[Any], *, at_ms: int) -> dict[str, list[dict[str, Any]]]:
    terms = {asset: [] for asset in _ISSUERS}
    seen = set()
    for wake in wakes:
        if wake is None:
            continue
        try:
            validated = validate_issuer_announcement_wake(wake, generated_at_ms=at_ms)
        except ValueError:
            continue
        for event in validated["new_events"]:
            if event.get("source_type") != "SEC_FILING" or event.get("document_state") != "VALID" or event.get("policy_stage") == "PROPOSED":
                continue
            for fact in event.get("normalized_facts", []):
                if not isinstance(fact, dict):
                    continue
                for asset, (event_issuer, issuer, security, source) in _ISSUERS.items():
                    ref = fact.get("source_ref") or {}
                    metadata = fact.get("distribution_terms") or {}
                    if not isinstance(ref, dict) or not isinstance(metadata, dict):
                        continue
                    if (event["issuer_id"] != event_issuer or fact.get("issuer_id") != issuer or fact.get("security_id") != security
                            or fact.get("fact_type") != "DISTRIBUTION_RATE" or fact.get("unit") != "PERCENT_APR"
                            or fact.get("quality_state") != "VALID_REPORTED" or ref.get("source_id") != source
                            or ref.get("evidence_hash") != event.get("document_evidence_hash")
                            or not re.fullmatch(r"[0-9a-f]{64}", ref.get("evidence_hash", ""))
                            or type(ref.get("source_as_of_ms")) is not int or not 0 < ref["source_as_of_ms"] <= at_ms
                            or metadata.get("state") != "REPORTED" or not isinstance(ref.get("document_id"), str)):
                        continue
                    key = (asset, ref["document_id"], ref["evidence_hash"])
                    if key in seen:
                        continue
                    try:
                        rate = _amount(fact["value"])
                        if rate > 100:
                            continue
                    except (ValueError, KeyError):
                        continue
                    seen.add(key)
                    allowed = ("state", "rate_effective_at_ms", "rate_valid_until_ms", "stated_amount_usd",
                               "declared_dividend_per_share_usd", "ex_dividend_date_ms", "record_date_ms", "payment_date_ms")
                    terms[asset].append({**{k: deepcopy(metadata.get(k)) for k in allowed}, "annual_rate": float(rate / 100),
                                         "source_ref": deepcopy(ref), "announcement_at_ms": ref["source_as_of_ms"]})
    return terms


def _tax_rate(inputs: dict[str, Any], asset: str, period: Any, at_ms: int) -> Decimal | None:
    # This input contract has no authenticated tax-document verifier. A supplied
    # EVIDENCE_VERIFIED label and a self-computed hash cannot establish tax facts.
    return None


def build_fixed_income_summary(*, private_context: Any, issuer_announcement_wake: Any = None,
                               inputs: Any = None, at_ms: int = 0) -> dict[str, Any]:
    """Extend the existing income engine; independent of BTC research or trades.

    Inputs are read-only, source-bound records, never synthesized from legacy
    settings. An integrity hash is not proof of real-world tax/issuer accuracy.
    """
    inputs = inputs if isinstance(inputs, dict) and inputs.get("schema_version") == INCOME_INPUT_SCHEMA else {}
    period = _period(inputs)
    profile = _private_profile(private_context) or {}
    broker = validate_broker_observation((profile.get("capital_reconciliation") or {}).get("broker_observed"), at_ms=at_ms)
    observation = broker.get("observation") if broker["state"] == "AVAILABLE" else None
    terms = _official_terms([issuer_announcement_wake, inputs.get("issuer_announcement_wake")], at_ms=at_ms)
    statement = inputs.get("broker_statement")
    statement_ok = (observation is not None and _content_valid(statement, source="IBKR_STATEMENT", at_ms=at_ms, period=period)
                    and statement.get("observation_hash") == observation["observation_hash"]
                    and statement["source_ref"]["source_as_of_ms"] == statement["as_of_ms"] == observation["observed_at_ms"]
                    and statement.get("same_account_verified") is True and statement.get("currency") == "USD"
                    and statement.get("ledger_complete") is True
                    and isinstance(statement.get("transactions"), list))
    forecast = inputs.get("forecast_assumptions")
    forecast_ok = (_content_valid(forecast, source="ANALYST_ASSUMPTIONS", at_ms=at_ms, period=period)
                   and _six_month_period(period)
                   and forecast.get("basis") == "SIX_MONTH_FLAT_RATE"
                   and forecast.get("constant_holdings") is True and forecast.get("constant_rate") is True
                   and isinstance(forecast.get("invalidation"), list) and bool(forecast["invalidation"])
                   and all(isinstance(v, str) and v in _FORECAST_INVALIDATION for v in forecast["invalidation"])
                   and period["start_ms"] <= at_ms < period["end_ms"])
    assets = {}
    for asset in _ISSUERS:
        quantity = None if observation is None else next((r["quantity"] for r in observation["holdings"] if r["asset"] == asset), 0.0)
        if quantity is not None and quantity < 0:
            quantity = None
        active = [t for t in terms[asset] if type(t.get("rate_effective_at_ms")) is int
                  and type(t.get("rate_valid_until_ms")) is int
                  and 0 < t["rate_effective_at_ms"] <= at_ms < t["rate_valid_until_ms"]]
        distinct = {(t["annual_rate"], t.get("stated_amount_usd")) for t in active}
        current = active[0] if len(distinct) == 1 else None
        row = {"holding_state": "AVAILABLE" if quantity is not None else "BLOCKED", "holding_reason": broker["reason"], "shares": quantity,
               "observation_hash": observation["observation_hash"] if observation else None,
               "current_terms": {**current, "state": "AVAILABLE"} if current else
                                {"state": "BLOCKED", "reason": "OFFICIAL_EFFECTIVE_RATE_MISSING_OR_CONFLICTING"},
               "credited": {**_component("BROKER_DIVIDEND_LEDGER_UNQUALIFIED"), "available_cash_usd": None},
               "receivable": _component("EX_DATE_ENTITLEMENT_UNQUALIFIED"),
               "future_undeclared": _component("FORECAST_INPUTS_UNQUALIFIED")}
        tax_rate = _tax_rate(inputs, asset, period, at_ms)
        declared_future = Decimal(0)
        if statement_ok:
            try:
                transactions = [r for r in statement["transactions"] if r.get("asset") == asset and r.get("transaction_type") == "DIVIDEND"]
                identities = [r["distribution_document_id"] for r in transactions]
                if len(set(identities)) != len(identities):
                    raise ValueError("DUPLICATE_DIVIDEND_CREDIT")
                received_gross = received_net = Decimal(0)
                credited_documents = set()
                for receipt in transactions:
                    clock = receipt["credited_at_ms"]
                    if type(clock) is not int or not period["start_ms"] <= clock <= at_ms or clock >= period["end_ms"]:
                        raise ValueError("DIVIDEND_CREDIT_CLOCK_INVALID")
                    gross, net = (_amount(receipt[key]) for key in ("gross_usd", "net_usd"))
                    if net > gross:
                        raise ValueError("DIVIDEND_CASH_INVALID")
                    received_gross += gross
                    received_net += net
                    credited_documents.add(receipt["distribution_document_id"])
                # The existing read-only broker snapshot contains no dividend
                # ledger. Retain claims without promoting them to actual income.
                # Neither a statement label nor current total cash proves that
                # these funds were credited, taxed, or remain unspent.
                row["credited"] = {"state": "SOURCE_UNVERIFIED", "gross_usd": None, "net_usd": None,
                                   "claimed_gross_usd": _money(received_gross), "claimed_net_usd": _money(received_net),
                                   "available_cash_usd": None, "available_cash_state": "BLOCKED_FUND_ATTRIBUTION_UNPROVEN",
                                   "reason": "ORIGINAL_BROKER_LEDGER_NOT_VERIFIED", "source": _public_proof(statement),
                                   "credited_at_ms": [r["credited_at_ms"] for r in transactions]}
                if statement.get("entitlements_complete") is not True or not isinstance(statement.get("entitlements"), list):
                    raise ValueError("EX_DATE_ENTITLEMENT_UNQUALIFIED")
                receivable = Decimal(0)
                declarations = []
                supplied_entitlements = [e for e in statement["entitlements"] if e.get("asset") == asset]
                declared_documents = {t["source_ref"]["document_id"] for t in terms[asset]
                                      if t.get("declared_dividend_per_share_usd") is not None}
                if any(e.get("distribution_document_id") not in declared_documents | credited_documents for e in supplied_entitlements):
                    raise ValueError("DECLARED_DISTRIBUTION_SOURCE_UNQUALIFIED")
                seen_declarations = set()
                for term in terms[asset]:
                    payment = term.get("payment_date_ms")
                    if type(payment) is not int or not period["start_ms"] <= payment < period["end_ms"] or term.get("declared_dividend_per_share_usd") is None:
                        continue
                    document = term["source_ref"]["document_id"]
                    if document in seen_declarations:
                        raise ValueError("DISTRIBUTION_DOCUMENT_CONFLICT")
                    seen_declarations.add(document)
                    if document in credited_documents:
                        if payment >= at_ms:
                            declared_future += sum((_amount(r["gross_usd"]) for r in transactions
                                                    if r["distribution_document_id"] == document), Decimal(0))
                        continue
                    matches = [e for e in statement["entitlements"] if e.get("asset") == asset and e.get("distribution_document_id") == document]
                    if len(matches) != 1 or matches[0].get("ex_dividend_date_ms") != term.get("ex_dividend_date_ms") or type(term.get("ex_dividend_date_ms")) is not int or term["ex_dividend_date_ms"] > at_ms:
                        raise ValueError("EX_DATE_ENTITLEMENT_UNQUALIFIED")
                    entitlement = matches[0]
                    qty = _amount(entitlement["eligible_quantity"])
                    if entitlement.get("eligibility_verified") is not True:
                        raise ValueError("EX_DATE_ENTITLEMENT_UNQUALIFIED")
                    record_date = term.get("record_date_ms")
                    if type(record_date) is not int or not term["ex_dividend_date_ms"] <= record_date <= payment:
                        raise ValueError("DISTRIBUTION_DATE_ORDER_INVALID")
                    gross = qty * _amount(term["declared_dividend_per_share_usd"])
                    receivable += gross
                    if payment >= at_ms:
                        declared_future += gross
                    declarations.append({"source_ref": term["source_ref"], "gross_usd": _money(gross),
                                         "ex_dividend_date_ms": term["ex_dividend_date_ms"], "payment_date_ms": payment,
                                         "record_date_ms": term.get("record_date_ms"), "eligible_quantity": float(qty)})
                row["receivable"] = {"state": "SOURCE_UNVERIFIED", "gross_usd": None,
                                     "claimed_gross_usd": _money(receivable), "reason": "ORIGINAL_EX_DATE_ENTITLEMENT_NOT_VERIFIED",
                                     "net_usd": _money(receivable * (1 - tax_rate)) if tax_rate is not None else None,
                                     "net_state": "ESTIMATE" if tax_rate is not None else "BLOCKED_TAX_UNKNOWN",
                                     "tax_source": _public_proof(inputs["tax"]) if tax_rate is not None else None,
                                     "declarations": declarations, "source": _public_proof(statement)}
            except (KeyError, TypeError, ValueError) as exc:
                # Receipt facts already established remain independent of missing entitlements.
                row["receivable"] = _component(str(exc))
        if quantity is not None and forecast_ok:
            if quantity == 0:
                row["future_undeclared"] = {"state": "ESTIMATE", "gross_usd": 0.0, "net_usd": 0.0,
                                           "reason": "CONFIRMED_ZERO_CURRENT_HOLDING", "assumptions": _public_proof(forecast)}
            elif current is not None and current.get("stated_amount_usd") is not None and row["receivable"]["state"] in {"AVAILABLE", "SOURCE_UNVERIFIED"}:
                try:
                    remainder = Decimal(period["end_ms"] - at_ms) / Decimal(period["end_ms"] - period["start_ms"])
                    estimate = (_amount(quantity) * _amount(current["stated_amount_usd"]) * _amount(current["annual_rate"]) / 2 * remainder)
                    future = max(Decimal(0), estimate - declared_future)
                    row["future_undeclared"] = {"state": "ESTIMATE", "gross_usd": _money(future),
                                               "entitlement_basis": row["receivable"]["state"],
                                               "net_usd": _money(future * (1 - tax_rate)) if tax_rate is not None else None,
                                               "net_state": "ESTIMATE" if tax_rate is not None else "BLOCKED_TAX_UNKNOWN",
                                               "tax_source": _public_proof(inputs["tax"]) if tax_rate is not None else None,
                                               "assumptions": _public_proof(forecast), "invalidation": deepcopy(forecast["invalidation"]),
                                               "formula": "shares * stated_amount * annual_rate / 2 * remaining_period_fraction - declared_future_gross",
                                               "source_ref": current["source_ref"], "is_guaranteed": False}
                except ValueError:
                    row["future_undeclared"] = _component("FORECAST_AMOUNT_INVALID")
        assets[asset] = row
    totals = {}
    for component in ("credited", "receivable", "future_undeclared"):
        total = {}
        for basis in ("gross_usd", "net_usd") + (("available_cash_usd",) if component == "credited" else ()):
            known = [r[component].get(basis) for r in assets.values() if r[component].get(basis) is not None]
            total[basis] = _money(sum((_amount(v) for v in known), Decimal(0))) if len(known) == 2 else None
            total[f"known_subtotal_{basis}"] = _money(sum((_amount(v) for v in known), Decimal(0))) if known else None
        total["missing_assets"] = [a for a, r in assets.items() if r[component].get("gross_usd") is None]
        total["state"] = "BLOCKED" if total["missing_assets"] else "ESTIMATE" if component == "future_undeclared" else "AVAILABLE"
        totals[component] = total
    goal = inputs.get("income_goal")
    goal_result = {"state": "BLOCKED", "reason": "CURRENT_USER_INCOME_GOAL_UNCONFIRMED", "target_usd": None,
                   "gap_usd": None, "coverage_ratio": None, "first_remittance_date_ms": None}
    if (_content_valid(goal, source="USER_CONFIRMED", at_ms=at_ms, period=period)
            and _six_month_period(period) and period["start_ms"] <= at_ms < period["end_ms"]
            and type(goal.get("confirmed_at_ms")) is int and goal["confirmed_at_ms"] == goal["source_ref"]["source_as_of_ms"]
            and isinstance(goal.get("version"), str) and bool(goal["version"])):
        try:
            target = _amount(goal["target_usd"])
            basis = {"GROSS": "gross_usd", "NET": "net_usd"}.get(goal.get("basis"))
            if target <= 0 or basis is None:
                raise ValueError("INCOME_GOAL_INVALID")
            remittance = goal.get("first_remittance_date_ms")
            if type(remittance) is not int or remittance < at_ms:
                remittance = None
            goal_result.update(target_usd=float(target), basis=goal["basis"], source=_public_proof(goal), first_remittance_date_ms=remittance)
            goal_result["reason"] = "INCOME_COMPONENTS_OR_NET_QUALIFICATION_INCOMPLETE"
            goal_result["first_remittance_state"] = "CONFIRMED" if remittance is not None else "UNCONFIRMED"
            values = [totals[c][basis] for c in totals]
            if all(v is not None for v in values):
                cash = sum((_amount(v) for v in values), Decimal(0))
                goal_result.update(state="ESTIMATE", reason="CONDITIONAL_INCOME_NOT_SPENDABLE_CASH", six_month_income_usd=_money(cash),
                                   gap_usd=_money(max(Decimal(0), target - cash)), coverage_ratio=float(cash / target))
        except (KeyError, ValueError):
            goal_result["reason"] = "INCOME_GOAL_INVALID"
    result = {"schema_version": INCOME_SCHEMA, "state": "AVAILABLE" if all(r["state"] != "BLOCKED" for r in totals.values()) else "PARTIAL",
              "as_of_ms": at_ms, "period": period, "assets": assets, "totals": totals, "income_goal": goal_result,
              "six_month_target_usd": goal_result["target_usd"], "six_month_cash_usd": None, "coverage_ratio": goal_result["coverage_ratio"],
              "goal_covered": None, "reason": "SOURCE_QUALIFIED_FACTS_WITH_SEPARATE_ESTIMATES",
              "legacy_policy_state": "HISTORICAL_USER_PROFILE_INPUTS_EXCLUDED",
              "action_output": "NONE", "capital_decision_authority": "USER_ONLY", "machine_execution": "FORBIDDEN"}
    result["summary_hash"] = _hash(result)
    return result


def _private_profile(private_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(private_context, dict) or private_context.get("state") != "AVAILABLE":
        return None
    profile = private_context.get("profile")
    return profile if isinstance(profile, dict) else None


def build_asset_strategy_delta(
    *,
    btc_entry_gate: dict[str, Any] | None,
    assumption_watch: dict[str, Any] | None,
    private_context: dict[str, Any] | None,
    portfolio_allocation_context: dict[str, Any] | None = None,
    issuer_announcement_wake: dict[str, Any] | None = None,
    fixed_income_inputs: dict[str, Any] | None = None,
    qualified_equity_prices: dict[str, Any] | None = None,
    at_ms: int = 0,
) -> dict[str, Any]:
    gate = btc_entry_gate if isinstance(btc_entry_gate, dict) else {}
    transition = str(gate.get("transition_state", "TRANSITION_UNRESOLVED"))
    raw_eligibility = str(gate.get("decision_eligibility", "WAIT"))
    control_transfer = (
        gate.get("control_transfer_validation")
        if isinstance(gate.get("control_transfer_validation"), dict)
        else {}
    )
    control_transfer_loop_closed = bool(
        control_transfer.get("control_transfer_loop_closed")
    )
    eligibility = raw_eligibility
    eligibility_guard_reason = "UNCHANGED"
    if raw_eligibility == "PROBE_ELIGIBLE" and not control_transfer_loop_closed:
        eligibility = "WATCH"
        eligibility_guard_reason = "PROBE_DOWNGRADED_UNTIL_CONTROL_TRANSFER_LOOP_CLOSES"
    watch = assumption_watch if isinstance(assumption_watch, dict) else {}
    allocation = (
        portfolio_allocation_context
        if isinstance(portfolio_allocation_context, dict)
        and portfolio_allocation_context.get("state") == "READY_FOR_ANALYST"
        else None
    )

    btc_delta = "KEEP_WAIT"
    if eligibility == "PROBE_ELIGIBLE":
        btc_delta = "STRENGTHEN_TO_PROBE_ELIGIBLE"
    elif transition.startswith("BEAR_REJECTION"):
        btc_delta = "WEAKEN_GROWTH_ENTRY"
    elif transition.startswith("BULL_ACCEPTANCE"):
        btc_delta = "STRENGTHEN_WATCH"

    income = build_fixed_income_summary(private_context=private_context, issuer_announcement_wake=issuer_announcement_wake,
                                        inputs=fixed_income_inputs, at_ms=at_ms)

    strc_delta = "BLOCKED_INCOME_PROFILE"
    sata_delta = "BLOCKED_INCOME_PROFILE"
    if income["income_goal"]["state"] == "ESTIMATE":
        strc_delta = sata_delta = "INCOME_COVERAGE_REVIEW"

    # Growth engines inherit BTC direction, but asset-specific gates remain fail-closed.
    mstr_direction = "WAIT"
    asst_direction = "WAIT"
    if eligibility == "PROBE_ELIGIBLE":
        mstr_direction = "DIRECTION_STRENGTHENED_BUT_BLOCKED"
        asst_direction = "DIRECTION_STRENGTHENED_BUT_BLOCKED"
    elif transition.startswith("BEAR_REJECTION"):
        mstr_direction = "WEAKEN"
        asst_direction = "WEAKEN"
    elif transition.startswith("BULL_ACCEPTANCE"):
        mstr_direction = "WATCH_STRENGTHENED"
        asst_direction = "WATCH_STRENGTHENED"

    result = {
        "schema_version": SCHEMA_VERSION,
        "state": "READY_FOR_ANALYST" if gate else "PARTIAL_INDEPENDENT_INCOME_FACTS",
        "btc_transition_state": transition,
        "btc_decision_eligibility": eligibility,
        "raw_btc_decision_eligibility": raw_eligibility,
        "eligibility_guard_reason": eligibility_guard_reason,
        "control_transfer_loop_closed": control_transfer_loop_closed,
        "assumption_watch_state": watch.get("state"),
        "income_engine": income,
        "assets": {
            "BTC": {
                "role": "CAPITAL_CORE_DIRECTION",
                "strategy_delta": btc_delta,
                "decision_support": eligibility,
            },
            "STRC": {
                "role": "INCOME_ENGINE",
                "strategy_delta": strc_delta,
                "decision_support": "READY_FOR_ANALYST",
                "quantitative": income["assets"]["STRC"],
            },
            "SATA": {
                "role": "INCOME_ENGINE",
                "strategy_delta": sata_delta,
                "decision_support": "READY_FOR_ANALYST",
                "quantitative": income["assets"]["SATA"],
            },
            "MSTR": {
                "role": "GROWTH_ENGINE",
                "strategy_delta": mstr_direction,
                "decision_support": "BLOCKED",
                "blocked_reasons": [
                    "DILUTED_EQUITY_MNAV_NOT_VALIDATED_IN_THIS_SLICE",
                    "SAME_DAY_BTC_HOLDINGS_AND_DILUTED_SHARES_REQUIRED",
                ],
            },
            "ASST": {
                "role": "GROWTH_ENGINE",
                "strategy_delta": asst_direction,
                "decision_support": "BLOCKED",
                "blocked_reasons": [
                    "ISSUER_SHARE_COUNT_ATM_DILUTION_NOT_VALIDATED_IN_THIS_SLICE",
                    "PER_SHARE_BTC_OR_EQUIVALENT_ACCRETION_NOT_VALIDATED",
                ],
            },
        },
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
        "analyst_judgment_required": True,
    }

    if qualified_equity_prices is not None:
        # Sourced price facts supplement review; they grant no role, budget or
        # trade eligibility and cannot replace formal treasury valuation.
        for asset in ("MSTR", "ASST", "STRC", "SATA"):
            result["assets"][asset]["price_evidence"] = deepcopy(
                qualified_equity_prices["assets"][asset]
            )

    if allocation is None:
        return result

    side_job = (
        allocation.get("side_job")
        if isinstance(allocation.get("side_job"), dict)
        else {}
    )
    # Preserve the existing research output as context, never as a role or
    # trade instruction. Income coverage and a short-cycle setup cannot choose
    # which security deserves retained or additional capital.
    for asset in ("STRC", "SATA"):
        result["assets"][asset]["short_cycle_side_job"] = {
            **deepcopy(side_job), "decision_support": "RESEARCH_ONLY",
            "action_output": "NONE", "capital_decision_authority": "USER_ONLY",
        }

    valuation = allocation.get("valuation_constraint")
    valuation = valuation if isinstance(valuation, dict) else {}
    for asset in ("MSTR", "ASST"):
        health = allocation.get(f"{asset.lower()}_health")
        constraint = valuation.get(asset)
        ready = (
            health in {"IMPROVING", "STABLE", "DETERIORATING"}
            and constraint in {"ALLOW_TILT", "BRAKE"}
        )
        row = result["assets"][asset]
        row["decision_support"] = (
            "READY_FOR_ANALYST" if ready else "BLOCKED"
        )
        row["health_direction"] = health
        row["valuation_constraint"] = constraint
        row["blocked_reasons"] = (
            []
            if ready
            else ["PORTFOLIO_HEALTH_OR_VALUATION_CONTEXT_BLOCKED"]
        )

    return result
