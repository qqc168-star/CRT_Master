"""Entirely synthetic, read-only income facts; never real account acceptance."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crt_radar.asset_strategy_delta import INCOME_INPUT_SCHEMA, build_fixed_income_summary, build_asset_strategy_delta
from crt_radar.broker_capital_observation import _hash, seal_broker_observation
from crt_radar.issuer_announcement_runner import OUTPUT_SCHEMA, _normalized_official_facts
from crt_radar.strategy_capital_fact_adapter import build_strategy_capital_reflexivity_input
from crt_radar.strive_capital_fact_adapter import build_strive_capital_reflexivity_input
from crt_radar.plain_language_notice import _position_line
from tests.test_broker_capital_observation import synthetic_observation


def ms(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp() * 1000)


NOW = ms("2026-10-10")
PERIOD = {"start_ms": NOW, "end_ms": ms("2027-04-10")}


def seal(record):
    record.pop("proof_hash", None)
    record["proof_hash"] = _hash(record)
    return record


def record(source, **fields):
    state = {"IBKR_STATEMENT": "AVAILABLE", "TAX_EVIDENCE": "AVAILABLE", "USER_CONFIRMED": "CONFIRMED", "ANALYST_ASSUMPTIONS": "ASSUMPTIONS_ONLY"}[source]
    return seal({"source": source, "state": state, "as_of_ms": NOW, "valid_until_ms": NOW + 240_000,
                 "period": deepcopy(PERIOD), "source_ref": {"source_as_of_ms": NOW,
                 "evidence_hash": sha256(f"synthetic {source}".encode()).hexdigest()}, **fields})


def official_event(asset, *, rate=12, start="October 1, 2026", end="October 31, 2026", declared=True, proposed=False,
                   document=None, accepted=ms("2026-09-30")):
    document = document or f"synthetic-{asset}-october"
    text = (f"{asset} annualized dividend rate of {rate}%. Stated amount is $100 per share. "
            f"The rate is effective as of {start}. The rate is valid through {end}. "
            "Ex-dividend date is October 9, 2026. Record date is October 9, 2026. Payment date is October 31, 2026. ")
    if declared:
        text += "The board declared a dividend of $1.00 per share. "
    if proposed:
        text += "This is a proposal subject to shareholder approval."
    event = {"event_id": document, "issuer_id": "STRATEGY_INC" if asset == "STRC" else "STRIVE_INC",
             "accepted_at": datetime.fromtimestamp(accepted / 1000, timezone.utc).isoformat(),
             "source_type": "SEC_FILING", "source_id": "SYNTHETIC_OFFICIAL_FIXTURE", "source_url": "https://www.sec.gov/synthetic",
             "classification": "DIVIDEND", "document_state": "VALID", "document_evidence_hash": sha256(text.encode()).hexdigest(),
             "policy_stage": "PROPOSED" if proposed else "EFFECTIVE"}
    event["normalized_facts"] = _normalized_official_facts(event, text.encode(), observed_at_ms=NOW)
    event["event_hash"] = _hash(event)
    return event


def wake(*events):
    value = {"schema_version": OUTPUT_SCHEMA, "observed_at_ms": NOW, "state": "REANALYSIS_REQUESTED",
             "reason": "NEW_OFFICIAL_ISSUER_ANNOUNCEMENT", "analyst_reanalysis_requested": True,
             "new_events": list(events), "new_event_count": len(events), "coverage_state": "COMPLETE", "action_output": "NONE",
             "external_action_authority": "NONE", "external_action_performed": False}
    value["wake_hash"] = _hash(value)
    return value


def fixture():
    holdings = [{"asset": asset, "quantity": qty, "average_cost_usd": 100, "currency": "USD", "security_type": "STK"}
                for asset, qty in (("STRC", 100), ("SATA", 50))]
    broker = synthetic_observation(NOW, holdings=holdings)
    private = {"state": "AVAILABLE", "profile": {"capital_reconciliation": {"broker_observed": broker},
               "strc": {"shares": 999, "current_annual_distribution_rate": 0.99},
               "derived": {"six_month_cash_usd": 49000, "minimum_shares_for_target": 1},
               "cash_goal": {"six_month_target_usd": 1500}}}
    entitlements = [{"asset": asset, "distribution_document_id": f"synthetic-{asset}-october",
                     "ex_dividend_date_ms": ms("2026-10-09"), "eligible_quantity": qty, "eligibility_verified": True}
                    for asset, qty in (("STRC", 100), ("SATA", 50))]
    inputs = {"schema_version": INCOME_INPUT_SCHEMA, "period": deepcopy(PERIOD),
              "issuer_announcement_wake": wake(official_event("STRC"), official_event("SATA", rate=10)),
              "broker_statement": record("IBKR_STATEMENT", observation_hash=broker["observation_hash"], same_account_verified=True,
                                         currency="USD", ledger_complete=True, entitlements_complete=True,
                                         transactions=[], entitlements=entitlements),
              "tax": record("TAX_EVIDENCE", verification_state="EVIDENCE_VERIFIED", withholding_rates={"STRC": 0.1, "SATA": 0.2}),
              "forecast_assumptions": record("ANALYST_ASSUMPTIONS", basis="SIX_MONTH_FLAT_RATE", constant_holdings=True,
                                             constant_rate=True, invalidation=["RATE_CHANGE", "POSITION_CHANGE", "TAX_CHANGE", "ISSUER_NONPAYMENT"]),
              "income_goal": record("USER_CONFIRMED", version="synthetic-current-intent", confirmed_at_ms=NOW,
                                    target_usd=1500, basis="NET", first_remittance_date_ms=ms("2026-11-15"))}
    return private, inputs


class FixedIncomeTests(unittest.TestCase):
    def setUp(self):
        self.private, self.inputs = fixture()

    def build(self, at=NOW):
        return build_fixed_income_summary(private_context=self.private, inputs=self.inputs, at_ms=at)

    def test_dual_current_terms_and_estimates_do_not_qualify_self_signed_ledger(self):
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["shares"], 100)
        self.assertEqual(result["assets"]["SATA"]["shares"], 50)
        self.assertIsNone(result["totals"]["receivable"]["gross_usd"])
        self.assertEqual(result["assets"]["STRC"]["receivable"]["claimed_gross_usd"], 100)
        self.assertEqual(result["assets"]["SATA"]["receivable"]["claimed_gross_usd"], 50)
        self.assertIsNone(result["totals"]["receivable"]["net_usd"])
        self.assertEqual(result["totals"]["future_undeclared"]["gross_usd"], 700)
        self.assertIsNone(result["totals"]["future_undeclared"]["net_usd"])
        self.assertNotIn("six_month_income_usd", result["income_goal"])
        self.assertIsNone(result["income_goal"]["gap_usd"])
        self.assertEqual(result["income_goal"]["state"], "BLOCKED")
        self.assertIsNone(result["totals"]["credited"]["available_cash_usd"])
        self.assertIsNone(result["six_month_cash_usd"])

    def test_confirmed_zero_current_holding_is_not_unknown(self):
        broker = self.private["profile"]["capital_reconciliation"]["broker_observed"]
        broker["holdings"] = [r for r in broker["holdings"] if r["asset"] != "SATA"]
        broker = seal_broker_observation(broker)
        self.private["profile"]["capital_reconciliation"]["broker_observed"] = broker
        statement = self.inputs["broker_statement"]
        statement["observation_hash"] = broker["observation_hash"]
        statement["entitlements"][1]["eligible_quantity"] = 0
        seal(statement)
        sata = self.build()["assets"]["SATA"]
        self.assertEqual(sata["shares"], 0)
        self.assertEqual(sata["future_undeclared"]["gross_usd"], 0)
        self.assertEqual(sata["receivable"]["claimed_gross_usd"], 0)
        self.assertIsNone(sata["receivable"]["gross_usd"])

    def test_unknown_partial_stale_and_tampered_holdings_never_use_history(self):
        original = deepcopy(self.private)
        for kind in ("MISSING", "PARTIAL", "STALE", "TAMPERED"):
            with self.subTest(kind=kind):
                self.private = deepcopy(original)
                capital = self.private["profile"]["capital_reconciliation"]
                broker = capital["broker_observed"]
                if kind == "MISSING":
                    capital.pop("broker_observed")
                elif kind == "PARTIAL":
                    broker["scope"]["positions_complete"] = False
                    capital["broker_observed"] = seal_broker_observation(broker)
                elif kind == "STALE":
                    broker["observed_at_ms"] -= 400_000
                    broker["started_at_ms"] -= 400_000
                    capital["broker_observed"] = seal_broker_observation(broker)
                else:
                    broker["holdings"][0]["quantity"] = 999
                result = self.build()
                self.assertIsNone(result["assets"]["STRC"]["shares"])
                self.assertIsNone(result["totals"]["future_undeclared"]["gross_usd"])
                self.assertNotIn("legacy_strc_derived", result)
                self.assertEqual(self.private["profile"]["derived"]["six_month_cash_usd"], 49000)

    def test_historical_rate_cannot_become_current(self):
        self.inputs["issuer_announcement_wake"] = wake(official_event("STRC", start="September 1, 2026", end="September 30, 2026"), official_event("SATA"))
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["current_terms"]["state"], "BLOCKED")
        self.assertIsNone(result["totals"]["future_undeclared"]["gross_usd"])
        self.assertIsNotNone(result["totals"]["future_undeclared"]["known_subtotal_gross_usd"])

    def test_proposal_is_neither_effective_rate_nor_certain_receivable(self):
        self.inputs["issuer_announcement_wake"] = wake(official_event("STRC", proposed=True), official_event("SATA"))
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["current_terms"]["state"], "BLOCKED")
        self.assertIsNone(result["assets"]["STRC"]["future_undeclared"]["gross_usd"])
        self.assertIsNone(result["assets"]["STRC"]["receivable"]["gross_usd"])

    def test_accepted_time_does_not_activate_future_rate(self):
        self.inputs["issuer_announcement_wake"] = wake(official_event("STRC", start="November 1, 2026", end="November 30, 2026"), official_event("SATA"))
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["current_terms"]["state"], "BLOCKED")

    def test_explicit_rate_change_uses_effective_period_not_latest_acceptance(self):
        old = official_event("STRC", rate=8, start="September 1, 2026", end="September 30, 2026", document="synthetic-old", declared=False)
        self.inputs["issuer_announcement_wake"] = wake(old, official_event("STRC", rate=14), official_event("SATA"))
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["current_terms"]["annual_rate"], 0.14)
        self.assertEqual(result["assets"]["STRC"]["future_undeclared"]["gross_usd"], 600)

    def test_conflicting_effective_rates_block_only_affected_asset(self):
        self.inputs["issuer_announcement_wake"] = wake(official_event("STRC"), official_event("STRC", rate=14, document="synthetic-conflict"), official_event("SATA"))
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["current_terms"]["state"], "BLOCKED")
        self.assertEqual(result["assets"]["SATA"]["current_terms"]["state"], "AVAILABLE")

    def test_credited_cash_is_separate_from_receivable_and_payment_clock(self):
        statement = self.inputs["broker_statement"]
        statement["transactions"] = [{"asset": "STRC", "transaction_type": "DIVIDEND", "distribution_document_id": "synthetic-STRC-october",
                                      "gross_usd": 100, "net_usd": 90, "available_cash_usd": 40, "credited_at_ms": NOW}]
        seal(statement)
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["credited"]["claimed_net_usd"], 90)
        self.assertIsNone(result["assets"]["STRC"]["credited"]["net_usd"])
        self.assertIsNone(result["assets"]["STRC"]["credited"]["available_cash_usd"])
        self.assertEqual(result["assets"]["STRC"]["receivable"]["claimed_gross_usd"], 0)
        self.assertEqual(result["assets"]["SATA"]["receivable"]["claimed_gross_usd"], 50)
        self.assertIsNone(result["assets"]["SATA"]["receivable"]["gross_usd"])
        self.assertEqual(result["assets"]["STRC"]["credited"]["credited_at_ms"], [NOW])
        self.assertNotIn("six_month_income_usd", result["income_goal"])

    def test_no_ex_date_eligibility_cannot_recognize_receivable(self):
        self.inputs["broker_statement"]["entitlements"][0]["eligibility_verified"] = False
        seal(self.inputs["broker_statement"])
        result = self.build()
        self.assertIsNone(result["assets"]["STRC"]["receivable"]["gross_usd"])
        self.assertEqual(result["assets"]["STRC"]["credited"]["claimed_gross_usd"], 0)
        self.assertEqual(result["assets"]["SATA"]["receivable"]["claimed_gross_usd"], 50)
        self.assertIsNone(result["assets"]["SATA"]["receivable"]["gross_usd"])

    def test_tax_unknown_blocks_net_and_net_goal_preserving_gross(self):
        self.inputs.pop("tax")
        result = self.build()
        self.assertIsNone(result["totals"]["receivable"]["gross_usd"])
        self.assertEqual(result["assets"]["STRC"]["receivable"]["claimed_gross_usd"], 100)
        self.assertEqual(result["assets"]["SATA"]["receivable"]["claimed_gross_usd"], 50)
        self.assertIsNone(result["totals"]["receivable"]["net_usd"])
        self.assertIsNone(result["income_goal"]["gap_usd"])

    def test_unverified_tax_setting_cannot_produce_net_cash(self):
        self.inputs["tax"]["verification_state"] = "USER_SETTING_ONLY"
        seal(self.inputs["tax"])
        result = self.build()
        self.assertIsNone(result["assets"]["STRC"]["future_undeclared"]["net_usd"])

    def test_unqualified_and_historical_broker_statement_not_promoted(self):
        for defect in ("BLOCKED", "PARTIAL", "STALE", "OLD_SOURCE_CLOCK"):
            with self.subTest(defect=defect):
                private, inputs = fixture()
                statement = inputs["broker_statement"]
                if defect == "OLD_SOURCE_CLOCK":
                    statement["source_ref"]["source_as_of_ms"] -= 86_400_000
                else:
                    statement["state"] = defect
                seal(statement)
                result = build_fixed_income_summary(private_context=private, inputs=inputs, at_ms=NOW)
                self.assertIsNone(result["assets"]["STRC"]["credited"]["gross_usd"])

    def test_missing_entitlements_preserves_separate_credit_claims(self):
        statement = self.inputs["broker_statement"]
        statement.pop("entitlements")
        statement["entitlements_complete"] = False
        statement["transactions"] = [{"asset": "STRC", "transaction_type": "DIVIDEND", "distribution_document_id": "synthetic-STRC-october",
                                      "gross_usd": 100, "net_usd": 90, "available_cash_usd": 40, "credited_at_ms": NOW}]
        seal(statement)
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["credited"]["claimed_gross_usd"], 100)
        self.assertIsNone(result["assets"]["STRC"]["credited"]["gross_usd"])
        self.assertIsNone(result["assets"]["STRC"]["receivable"]["gross_usd"])

    def test_unsourced_ex_date_position_cannot_be_current_position_substitute(self):
        self.inputs["broker_statement"]["entitlements"] = []
        seal(self.inputs["broker_statement"])
        result = self.build()
        self.assertEqual(result["assets"]["STRC"]["shares"], 100)
        self.assertIsNone(result["assets"]["STRC"]["receivable"]["gross_usd"])

    def test_official_hash_wrong_asset_and_ambiguous_rates_are_rejected(self):
        for defect in ("hash", "asset", "ambiguity"):
            with self.subTest(defect=defect):
                event = official_event("STRC")
                fact = next(r for r in event["normalized_facts"] if r["fact_type"] == "DISTRIBUTION_RATE")
                if defect == "hash":
                    fact["source_ref"]["evidence_hash"] = "f" * 64
                elif defect == "asset":
                    fact["security_id"] = "SATA"
                else:
                    fact["distribution_terms"]["state"] = "AMBIGUOUS"
                event.pop("event_hash")
                event["event_hash"] = _hash(event)
                self.inputs["issuer_announcement_wake"] = wake(event, official_event("SATA"))
                self.assertEqual(self.build()["assets"]["STRC"]["current_terms"]["state"], "BLOCKED")

    def test_sata_disclosure_strc_issuer_holdings_not_user_holdings_or_wrong_terms(self):
        text = ("Strive holds 999 STRC shares. SATA annualized dividend rate of 10%. "
                "Stated amount is $100 per share. The rate is effective as of October 1, 2026. The rate is valid through October 31, 2026.")
        result = build_strive_capital_reflexivity_input(text, mode="SATA_TERMS", accepted_at_ms=NOW, retrieved_at_ms=NOW)
        rate = next(r for r in result["issuer_facts"]["items"] if r["fact_type"] == "DISTRIBUTION_RATE")
        self.assertEqual(rate["distribution_terms"]["state"], "REPORTED")
        self.assertEqual(self.build()["assets"]["STRC"]["shares"], 100)

    def test_missing_effective_date_does_not_fallback_to_legacy_fact_clock(self):
        event = official_event("STRC")
        fact = next(r for r in event["normalized_facts"] if r["fact_type"] == "DISTRIBUTION_RATE")
        self.assertIsNotNone(fact["effective_at_ms"])
        fact["distribution_terms"]["rate_effective_at_ms"] = None
        event.pop("event_hash")
        event["event_hash"] = _hash(event)
        self.inputs["issuer_announcement_wake"] = wake(event, official_event("SATA"))
        self.assertEqual(self.build()["assets"]["STRC"]["current_terms"]["state"], "BLOCKED")

    def test_another_assets_stated_amount_cannot_support_this_assets_yield(self):
        text = ("SATA stated amount is $777 per share. STRC annualized dividend rate of 12%. "
                "The rate is effective as of October 1, 2026. The rate is valid through October 31, 2026.")
        result = build_strategy_capital_reflexivity_input(text, mode="STRC_DIVIDEND", accepted_at_ms=NOW, retrieved_at_ms=NOW)
        rate = next(r for r in result["issuer_facts"]["items"] if r["fact_type"] == "DISTRIBUTION_RATE")
        self.assertIsNone(rate["distribution_terms"]["stated_amount_usd"])

    def test_sale_principal_never_enters_income(self):
        self.inputs["broker_statement"]["transactions"] = [{"asset": "STRC", "transaction_type": "SALE", "gross_usd": 10000}]
        seal(self.inputs["broker_statement"])
        result = self.build()
        self.assertIsNone(result["totals"]["credited"]["gross_usd"])
        self.assertEqual(result["assets"]["STRC"]["credited"]["claimed_gross_usd"], 0)
        self.assertIsNone(result["income_goal"]["gap_usd"])

    def test_historical_goal_and_remittance_not_current_approval(self):
        self.inputs.pop("income_goal")
        result = self.build()
        self.assertIsNone(result["income_goal"]["target_usd"])
        self.assertIsNone(result["income_goal"]["first_remittance_date_ms"])
        self.assertIsNone(result["income_goal"]["gap_usd"])

    def test_confirmed_gross_goal_without_tax_and_unconfirmed_remittance(self):
        self.inputs.pop("tax")
        self.inputs["income_goal"]["basis"] = "GROSS"
        self.inputs["income_goal"].pop("first_remittance_date_ms")
        seal(self.inputs["income_goal"])
        goal = self.build()["income_goal"]
        self.assertNotIn("six_month_income_usd", goal)
        self.assertIsNone(goal["gap_usd"])
        self.assertIsNone(goal["first_remittance_date_ms"])

    def test_specified_period_credits_independent_of_six_month_forecast(self):
        period = {"start_ms": ms("2026-10-01"), "end_ms": ms("2026-11-01")}
        self.inputs["period"] = period
        for key in ("broker_statement", "tax", "forecast_assumptions", "income_goal"):
            self.inputs[key]["period"] = deepcopy(period)
            seal(self.inputs[key])
        result = self.build()
        self.assertIsNone(result["totals"]["receivable"]["gross_usd"])
        self.assertEqual(result["assets"]["STRC"]["receivable"]["claimed_gross_usd"], 100)
        self.assertEqual(result["assets"]["SATA"]["receivable"]["claimed_gross_usd"], 50)
        self.assertIsNone(result["income_goal"]["target_usd"])
        self.assertIsNone(result["totals"]["future_undeclared"]["gross_usd"])

    def test_proof_extras_not_exported_as_private_data(self):
        self.inputs["broker_statement"]["account_identifier"] = "synthetic-secret-account"
        self.inputs["tax"]["private_path"] = "synthetic-secret-path"
        seal(self.inputs["broker_statement"])
        seal(self.inputs["tax"])
        encoded = json.dumps(self.build())
        self.assertNotIn("synthetic-secret", encoded)

    def test_six_month_period_and_source_binding_fail_closed(self):
        for mutate in ("period", "hash", "observation", "expiry"):
            with self.subTest(mutate=mutate):
                private, inputs = fixture()
                if mutate == "period":
                    inputs["period"]["end_ms"] += 1
                elif mutate == "hash":
                    inputs["broker_statement"]["transactions"].append({"asset": "SATA", "transaction_type": "DIVIDEND"})
                elif mutate == "observation":
                    inputs["broker_statement"]["observation_hash"] = "b" * 64
                    seal(inputs["broker_statement"])
                else:
                    inputs["broker_statement"]["valid_until_ms"] = NOW
                    seal(inputs["broker_statement"])
                result = build_fixed_income_summary(private_context=private, inputs=inputs, at_ms=NOW)
                self.assertIsNone(result["totals"]["credited"]["gross_usd"])

    def test_missing_btc_does_not_erase_income_and_locks(self):
        result = build_asset_strategy_delta(btc_entry_gate=None, assumption_watch=None, private_context=self.private,
                                            fixed_income_inputs=self.inputs, at_ms=NOW)
        self.assertEqual(result["income_engine"]["assets"]["STRC"]["current_terms"]["annual_rate"], 0.12)
        self.assertEqual(result["income_engine"]["totals"]["future_undeclared"]["gross_usd"], 700)
        self.assertEqual(result["assets"]["BTC"]["decision_support"], "WAIT")
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")
        self.assertFalse(result["machine_may_execute_trade"])
        self.assertEqual(result["income_engine"]["machine_execution"], "FORBIDDEN")

    def test_legacy_derived_unchanged_and_notice_cannot_call_history_current(self):
        original = deepcopy(self.private)
        result = self.build()
        self.assertEqual(self.private, original)
        self.assertNotIn("legacy_strc_derived", result)
        notice = _position_line(self.private, result)
        self.assertIn("STRC", notice)
        self.assertIn("SATA", notice)
        self.assertIn("未知", _position_line(self.private, build_fixed_income_summary(private_context=self.private, at_ms=NOW)))
        self.assertNotIn("49000", notice)
        self.assertNotIn("至少", notice)

    def test_self_signed_source_and_verified_labels_do_not_establish_real_credits(self):
        statement = self.inputs["broker_statement"]
        statement["transactions"] = [{"asset": "STRC", "transaction_type": "DIVIDEND",
            "distribution_document_id": "synthetic-STRC-october", "credited_at_ms": NOW,
            "gross_usd": 100, "net_usd": 90, "available_cash_usd": 90}]
        for labels in ({}, {"source_trust": "VERIFIED", "verification_state": "EVIDENCE_VERIFIED",
                            "original_evidence_verified": True}):
            with self.subTest(labels=labels):
                statement.update(labels)
                seal(statement)
                result = self.build()
                credit = result["assets"]["STRC"]["credited"]
                self.assertEqual(credit["source"]["content_integrity"], "VALID")
                self.assertEqual(credit["source"]["source_trust"], "NOT_EXTERNALLY_VERIFIED")
                self.assertEqual(credit["state"], "SOURCE_UNVERIFIED")
                self.assertEqual(credit["claimed_gross_usd"], 100)
                self.assertEqual(credit["claimed_net_usd"], 90)
                self.assertIsNone(credit["gross_usd"])
                self.assertIsNone(credit["net_usd"])
                self.assertIsNone(credit["available_cash_usd"])
                self.assertIsNone(result["totals"]["credited"]["gross_usd"])
                self.assertIsNone(result["income_goal"]["gap_usd"])
                notice = _position_line(self.private, result)
                self.assertIn("僅為未經原始帳務驗證的來源主張", notice)
                self.assertIn("其中仍可用 未知", notice)

    def test_unspent_cash_claim_cannot_erase_independent_reported_income(self):
        statement = self.inputs["broker_statement"]
        receipt = {"asset": "STRC", "transaction_type": "DIVIDEND",
                   "distribution_document_id": "synthetic-STRC-october", "credited_at_ms": NOW,
                   "gross_usd": 100, "net_usd": 90}
        for cash in (None, 40, 1000000, "invalid-self-claim"):
            with self.subTest(cash=cash):
                statement["transactions"] = [{**receipt, "available_cash_usd": cash}]
                seal(statement)
                credit = self.build()["assets"]["STRC"]["credited"]
                self.assertEqual(credit["claimed_gross_usd"], 100)
                self.assertEqual(credit["claimed_net_usd"], 90)
                self.assertIsNone(credit["available_cash_usd"])

    def test_all_zero_current_holdings_preserve_independent_zero_forecast(self):
        broker = self.private["profile"]["capital_reconciliation"]["broker_observed"]
        broker["holdings"] = []
        self.private["profile"]["capital_reconciliation"]["broker_observed"] = seal_broker_observation(broker)
        self.inputs.pop("broker_statement")
        result = self.build()
        self.assertEqual(result["totals"]["future_undeclared"]["gross_usd"], 0)
        self.assertEqual(result["totals"]["future_undeclared"]["net_usd"], 0)
        self.assertIsNone(result["totals"]["credited"]["gross_usd"])

    def test_sufficient_broker_cash_never_proves_dividend_still_available(self):
        broker = self.private["profile"]["capital_reconciliation"]["broker_observed"]
        broker["funds"]["cash_usd"] = broker["funds"]["available_funds_usd"] = 1000000
        broker = seal_broker_observation(broker)
        self.private["profile"]["capital_reconciliation"]["broker_observed"] = broker
        statement = self.inputs["broker_statement"]
        statement["observation_hash"] = broker["observation_hash"]
        statement["transactions"] = [{"asset": "STRC", "transaction_type": "DIVIDEND",
            "distribution_document_id": "synthetic-STRC-october", "credited_at_ms": NOW,
            "gross_usd": 100, "net_usd": 90, "available_cash_usd": 90}]
        seal(statement)
        self.assertIsNone(self.build()["assets"]["STRC"]["credited"]["available_cash_usd"])

    def test_self_signed_tax_cannot_produce_qualified_net_forecast(self):
        tax = self.inputs["tax"]
        tax.update(source_trust="VERIFIED", original_evidence_verified=True)
        seal(tax)
        result = self.build()
        self.assertEqual(result["totals"]["future_undeclared"]["gross_usd"], 700)
        self.assertIsNone(result["totals"]["future_undeclared"]["net_usd"])
        self.assertEqual(result["assets"]["STRC"]["future_undeclared"]["net_state"], "BLOCKED_TAX_UNKNOWN")

    def test_goal_coverage_and_side_job_cannot_assign_income_roles(self):
        # Hypothetical qualified coverage isolates the strategy implication;
        # this fixture does not pretend to authenticate a broker ledger.
        income = self.build()
        income["income_goal"].update(state="ESTIMATE", gap_usd=0)
        for side_state in ("EXECUTE", "EXIT_PENDING", "WAIT"):
            with self.subTest(side_state=side_state):
                allocation = {"state": "READY_FOR_ANALYST", "mstr_health": "DETERIORATING",
                              "asst_health": "STABLE", "valuation_constraint": {"MSTR": "BRAKE", "ASST": "BRAKE"},
                              "side_job": {"state": side_state, "window_stage": "D", "capital_scope_state": "AVAILABLE"}}
                original = deepcopy(allocation)
                with patch("crt_radar.asset_strategy_delta.build_fixed_income_summary", return_value=income):
                    result = build_asset_strategy_delta(
                        btc_entry_gate={"transition_state": "BEAR_REJECTION_STRENGTHENED", "decision_eligibility": "WAIT"},
                        assumption_watch=None, private_context=self.private, portfolio_allocation_context=allocation)
                for asset in ("STRC", "SATA"):
                    row = result["assets"][asset]
                    self.assertEqual(row["role"], "INCOME_ENGINE")
                    self.assertEqual(row["strategy_delta"], "INCOME_GAP_REVIEW")
                    self.assertEqual(row["decision_support"], "READY_FOR_ANALYST")
                    self.assertEqual(row["quantitative"], income["assets"][asset])
                    self.assertEqual(row["short_cycle_side_job"]["decision_support"], "RESEARCH_ONLY")
                    self.assertEqual(row["short_cycle_side_job"]["action_output"], "NONE")
                self.assertEqual(result["assets"]["MSTR"]["strategy_delta"], "WEAKEN")
                self.assertEqual(result["assets"]["MSTR"]["valuation_constraint"], "BRAKE")
                self.assertEqual(allocation, original)

    def test_missing_income_keeps_neutral_roles_without_choosing_allocation(self):
        result = build_asset_strategy_delta(btc_entry_gate=None, assumption_watch=None, private_context=None)
        for asset in ("STRC", "SATA"):
            self.assertEqual(result["assets"][asset]["role"], "INCOME_ENGINE")
            self.assertEqual(result["assets"][asset]["strategy_delta"], "BLOCKED_INCOME_PROFILE")
        self.assertEqual(result["action_output"], "NONE")

    def test_model_instructions_preserve_source_and_capital_qualification(self):
        from crt_radar.capital_decision_closure import INSTRUCTIONS, REFERENCE_INSTRUCTIONS
        for instructions in (INSTRUCTIONS, REFERENCE_INSTRUCTIONS):
            self.assertIn("not source authenticity", instructions)
            self.assertIn("not additional capital", instructions)
            self.assertIn("does not select a core, backup", instructions)
            self.assertIn("not an approved rotation", instructions)

    def test_notice_separates_current_capital_and_refuses_stale_cash(self):
        from crt_radar.broker_capital_observation import reconcile_capital
        profile = self.private["profile"]
        broker = profile["capital_reconciliation"]["broker_observed"]
        profile["capital_reconciliation"] = reconcile_capital(
            broker, {"source": "USER_CONFIRMED", "confirmed_at_ms": NOW, "reserved_usd": 0,
                     "plan_policy": "CANCEL_ALL_NO_REPLACEMENT", "asset_roles": {}}, at_ms=NOW)
        capital = profile["capital_reconciliation"]
        self.assertEqual(capital["state"], "AVAILABLE")
        budget_before = capital["analysis_cash_budget_usd"]
        result = self.build()
        notice = _position_line(self.private, result)
        self.assertIn(f"當前券商現金 ${broker['funds']['cash_usd']:,.2f}", notice)
        self.assertIn(f"當前資本分析預算 ${budget_before:,.2f}", notice)
        self.assertIn("配息不另加預算", notice)
        self.assertEqual(capital["analysis_cash_budget_usd"], budget_before)
        stale_broker = deepcopy(broker)
        stale_broker["observed_at_ms"] -= 400000
        stale_broker["started_at_ms"] -= 400000
        capital["broker_observed"] = seal_broker_observation(stale_broker)
        # Even a saved AVAILABLE reconciliation must not show expired cash.
        self.assertNotIn("當前券商現金", _position_line(self.private, self.build()))

    def test_independent_summary_enters_same_evidence_pack_full_gpt_projection(self):
        from crt_radar.daily_evidence_runner import run_daily_evidence
        from crt_radar import gpt_handoff as h, capital_decision_closure as c
        from tests.test_daily_evidence_runner import DailyEvidenceRunnerTests
        from crt_radar.plain_language_notice import build_plain_language_notice
        from tests.test_capital_decision_closure import source_fixture
        daily = DailyEvidenceRunnerTests()
        daily.setUp()
        # Use fixture market clocks, same broker/statement clock and six-month period.
        shifted = deepcopy(self.inputs)
        # Running at NOW avoids any fabricated rebinding; market inputs are stale.
        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(daily.registry, observation_db=Path(td) / "obs.sqlite3", fetch_overrides=daily.overrides,
                                      probe_fetcher=lambda _: daily.overrides[daily.probe.source_id],
                                      now_ms=NOW, generated_at_ms=NOW, private_context=self.private, fixed_income_inputs=shifted,
                                      issuer_announcement_wake=shifted["issuer_announcement_wake"])
            income = pack["asset_strategy_delta"]["income_engine"]
            self.assertEqual(income["totals"]["future_undeclared"]["gross_usd"], 700)
            handoff = h.run_gpt_handoff_gate(pack, build_plain_language_notice(pack), ledger_path=Path(td) / "handoff.jsonl", full_decision=True)
            payload = h.build_full_decision_bridge_payload(pack, handoff)
            source = source_fixture(payload, NOW)
            source["broker_observation"] = deepcopy(self.private["profile"]["capital_reconciliation"]["broker_observed"])
            source["qualification"]["observation_hash"] = source["broker_observation"]["observation_hash"]
            projection = c.build_projection(payload, source, at_ms=NOW)
            market = projection["market_context"]
            self.assertEqual(market["asset_strategy_delta"]["income_engine"]["summary_hash"], income["summary_hash"])
            self.assertEqual(market["asset_strategy_delta"]["income_engine"]["totals"]["future_undeclared"]["state"], "ESTIMATE")
            self.assertEqual(source["governance"], c.LOCKS)
            self.assertNotIn("IBKR_ACCOUNT", json.dumps(projection))
            encoded = json.dumps(projection)
            self.assertNotIn("49000", encoded)
            self.assertNotIn("legacy_strc_derived", encoded)
            self.assertEqual(market["asset_strategy_delta"]["income_engine"]["assets"]["SATA"]["current_terms"]["annual_rate"], 0.10)
            self.assertEqual(market["asset_strategy_delta"]["income_engine"]["assets"]["STRC"]["future_undeclared"]["source_ref"], income["assets"]["STRC"]["current_terms"]["source_ref"])
            # Re-project an older immutable summary; only the model copy loses
            # history, and the existing capital validator accepts its new hash.
            old_pack = deepcopy(pack)
            old_income = old_pack["asset_strategy_delta"]["income_engine"]
            old_income["legacy_strc_derived"] = deepcopy(self.private["profile"]["derived"])
            old_income["summary_hash"] = _hash({k: v for k, v in old_income.items() if k != "summary_hash"})
            original_pack = deepcopy(old_pack)
            old_payload = h.build_full_decision_bridge_payload(old_pack, handoff)
            old_source = deepcopy(source)
            old_source["bridge_payload_hash"] = old_payload["bridge_payload_hash"]
            old_projection = c.build_projection(old_payload, old_source, at_ms=NOW)
            self.assertNotIn("49000", json.dumps(old_projection))
            self.assertEqual(old_pack, original_pack)
            self.assertEqual(old_projection["capital"], projection["capital"])
            self.assertEqual(old_projection["spending_cap"], projection["spending_cap"])
            claim_payload = deepcopy(payload)
            claim_income = claim_payload["market_context"]["asset_strategy_delta"]["income_engine"]
            claim_income["assets"]["STRC"]["credited"].update(claimed_gross_usd=100, claimed_net_usd=90)
            claim_income["summary_hash"] = c.digest({k: v for k, v in claim_income.items() if k != "summary_hash"})
            claim_payload["bridge_payload_hash"] = c.digest({k: v for k, v in claim_payload.items() if k != "bridge_payload_hash"})
            claim_source = deepcopy(source)
            claim_source["bridge_payload_hash"] = claim_payload["bridge_payload_hash"]
            claim_projection = c.build_projection(claim_payload, claim_source, at_ms=NOW)
            self.assertEqual(claim_projection["capital"], projection["capital"])
            self.assertEqual(claim_projection["spending_cap"], projection["spending_cap"])
            old_income["legacy_strc_derived"]["six_month_cash_usd"] = 99999
            with self.assertRaisesRegex(ValueError, "INCOME_SUMMARY_HASH_INVALID"):
                h.build_full_decision_bridge_payload(old_pack, handoff)
            # A recomputed summary/bridge hash does not authenticate income or
            # create additional budget; legacy actual-credit claims are refused.
            bad_payload = deepcopy(payload)
            bad_income = bad_payload["market_context"]["asset_strategy_delta"]["income_engine"]
            for component, error in (("credited", "INCOME_ORIGINAL_LEDGER_UNVERIFIED"),
                                     ("receivable", "INCOME_ORIGINAL_ENTITLEMENT_UNVERIFIED")):
                bad_income["assets"]["STRC"][component]["gross_usd"] = 100
                bad_income["summary_hash"] = c.digest({k: v for k, v in bad_income.items() if k != "summary_hash"})
                bad_payload["bridge_payload_hash"] = c.digest({k: v for k, v in bad_payload.items() if k != "bridge_payload_hash"})
                bad_source = deepcopy(source)
                bad_source["bridge_payload_hash"] = bad_payload["bridge_payload_hash"]
                with self.assertRaisesRegex(ValueError, error):
                    c.build_projection(bad_payload, bad_source, at_ms=NOW)
                bad_income["assets"]["STRC"][component]["gross_usd"] = None
            wrong_source = source_fixture(payload, NOW)
            with self.assertRaisesRegex(ValueError, "INCOME_BROKER_LINEAGE_MISMATCH"):
                c.build_projection(payload, wrong_source, at_ms=NOW)


if __name__ == "__main__":
    unittest.main()
