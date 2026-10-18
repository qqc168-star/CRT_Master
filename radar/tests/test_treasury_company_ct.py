from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from crt_radar.diluted_equity_mnav import (
    FORMULA_VERSION, DENOMINATOR_BASIS, SCHEMA_VERSION as MNAV_SCHEMA_VERSION,
    build_diluted_equity_mnav,
)
from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.treasury_company_ct import (FORMAL_MNAV_REF, admit_saylortracker_sensor,
    build_net_bps_attribution, build_treasury_company_ct, import_saylortracker_offline_csv,
    validate_pit_replay)
from crt_radar.treasury_company_ct import build_fixed_obligation_windows
from test_first_evidence_slice import gate
from test_reflexivity_overlay import empty_section

T0 = 1_780_000_000_000
DAY = 86_400_000
T1, T2 = T0 + 7 * DAY, T0 + 14 * DAY
ISSUER = "CIK-0001050446"


def evidence(at=T2, **fields):
    base = dict(issuer_id=ISSUER, effective_time=at, disclosure_time=at,
                first_seen_time=at, retrieval_time=at,
                source_ref=f"synthetic-fixture:{at}", verification_state="VALIDATED",
                source_semantic={"identity": "ISSUER_VERIFIED_FACT", "version": "V1",
                    "effective_from": 1, "effective_to": None})
    base.update(fields)
    return base


def asset(at, btc, shares=100, basis="diluted-split-adjusted-v1"):
    return evidence(at, btc_holdings=btc, diluted_shares=shares, basis_ref=basis)


def burden(at=T2, carry=100, claims=1000, **fields):
    return evidence(at, basis_ref="USD-current-annual-run-rate-v1",
                    debt_principal_usd=claims * .4, preferred_liquidation_claims_usd=claims * .6,
                    annual_debt_interest_usd=carry * .2, annual_preferred_distributions_usd=carry * .8,
                    usd_cash_usd=100, usd_reserve_usd=0, **fields)


def funding():
    return evidence(instrument_id="MSTR-ATM", instrument_type="COMMON_ATM",
                    program_capacity_usd=1000, cumulative_program_usage_usd=300,
                    usable_capacity_usd=500, usability_basis_ref="documented-availability",
                    observed_funding_use_usd=300, annual_cost_rate_pct=12,
                    cost_basis_ref="normalized-annual-funding-cost",
                    previous_cost=evidence(T1, annual_cost_rate_pct=10, cost_basis_ref="normalized-annual-funding-cost"),
                    market_absorption_evidence=evidence(observation_ref="issuer-reported-proceeds",
                        evidence_kind="ISSUER_REPORTED_FUNDING_OBSERVATION"))


def conversion(key="buy", source="MSTR_COMMON_ISSUANCE", destination="BTC_PURCHASE", **changes):
    deltas = dict(btc_change=10, diluted_share_change=1, senior_claim_change_usd=0,
                  annual_carry_change_usd=0, liquidity_change_usd=0)
    deltas.update(changes)
    return evidence(event_id=key, source=source, destination=destination, amount_usd=100,
                    active_for_calculation=True, consequence_basis_ref="verified-event-accounting", **deltas)


def qualified_mnav(at=T2, *, asset_id="MSTR"):
    values = dict(diluted_shares=100, equity_price_usd=.65,
                  btc_holdings=100, btc_price_usd=1)
    issuer = {"MSTR": ISSUER, "ASST": "CIK-0001920406"}[asset_id]
    proof = {}
    for key, value in values.items():
        row = evidence(at, value=value, asset_id="BTC" if key == "btc_price_usd" else asset_id,
            issuer_id=issuer, source_ref=f"synthetic-fixture:mnav:{key}:{at}",
            raw_sha256=hashlib.sha256(key.encode()).hexdigest())
        if key in ("equity_price_usd", "btc_price_usd"):
            row["currency"] = "USD"
        if key == "diluted_shares":
            row.update(basis_ref="diluted-split-adjusted-v1",
                       coverage_state="COMPLETE",
                       dilution_scope="SYNTHETIC_FULLY_DILUTED_ORIGINAL_SCOPE")
        proof[key] = row
    return build_diluted_equity_mnav(asset_id=asset_id, **values,
        share_basis_ref="diluted-split-adjusted-v1", input_evidence=proof, as_of_ms=at,
        semantic_ref=FORMAL_MNAV_REF, evidence_alignment_state="VALIDATED")


def kwargs():
    mnav = qualified_mnav()
    return dict(issuer_id=ISSUER, as_of_ms=T2,
                asset_history=[asset(T0, 100), asset(T1, 110), asset(T2, 121)],
                funding_instruments=[funding()], burden_current=burden(), burden_previous=burden(T1),
                maturities=[], capital_conversion_events=[], management_events=[],
                price_financing_state={**mnav, **evidence(source_semantic={"identity": "CRT_FORMAL_DILUTED_EQUITY_MNAV", "version": "V1", "effective_from": 1, "effective_to": None})},
                coverage={key: evidence(coverage_state="COMPLETE", scope_ref="issuer-explicit-test-scope",
                    empty_reason="VERIFIED_NO_MATCH") for key in ("funding", "maturities", "capital_conversion", "management")})


class TreasuryCompanyCtTests(unittest.TestCase):
    def test_carry_only_reserve_cannot_certify_principal_funding(self):
        cash = burden(
            reserve_usable_for_carry=True, reserve_separate_from_cash=True,
            usd_cash_usable_for_carry=True, cash_usability_basis_ref='synthetic:carry-only',
            liquidity_coverage_state='COMPLETE', liquidity_scope_ref='ALL_USABLE_LIQUIDITY',
            liquidity_valid_until_ms=T2+DAY, liquidity_validity_basis_ref='synthetic:current')
        cash.update(usd_cash_usd=0, usd_reserve_usd=200)
        result = self.windows(burden=cash)
        self.assertEqual(result['confirmed'][0]['amount_usd'], 120)
        self.assertEqual(result['qualified_usable_liquidity_usd'], 200)
        self.assertIsNone(result['windows'][0]['complete_schedule_balance_usd'])
        self.assertIsNone(result['windows'][0]['proven_minimum_shortfall_usd'])
        self.assertIsNone(result['first_proven_shortfall_date_ms'])
        self.assertFalse(result['principal_liquidity_qualified'])
        self.assertFalse(result['windows'][0]['liquidity_use_qualified'])

    def test_principal_basis_is_required_but_carry_only_payments_remain_independent(self):
        for change in ({'liquidity_usable_for_principal': False}, {'liquidity_usable_for_principal': 1},
                       {'principal_usability_basis_ref': None}, {'principal_usability_basis_ref': ''}):
            # Reuse the input helper, not its normalized output or a fake clock.
            cash = burden(usd_cash_usable_for_carry=True, cash_usability_basis_ref='synthetic:free',
                liquidity_coverage_state='COMPLETE', liquidity_scope_ref='ALL_USABLE_LIQUIDITY',
                liquidity_valid_until_ms=T2+DAY, liquidity_validity_basis_ref='synthetic:current',
                liquidity_usable_for_principal=True, principal_usability_basis_ref='synthetic:all-included-pool')
            cash.update(change)
            principal = self.windows(burden=cash)
            self.assertIsNone(principal['windows'][0]['proven_minimum_shortfall_usd'])
            self.assertEqual(principal['confirmed'][0]['amount_usd'], 120)
            interest = evidence(source_class='SEC', payment_reference='interest-only', due_at_ms=T2+20*DAY,
                amount_usd=120, obligation_kind='DEBT_INTEREST', recognition='CONFIRMED', amount_basis_ref='contract')
            self.assertEqual(self.windows(burden=cash, obligations=[interest])['windows'][0]['proven_minimum_shortfall_usd'], 20)

    def windows(self, **changes):
        args = dict(issuer_id=ISSUER, as_of_ms=T2,
            burden=burden(usd_cash_usable_for_carry=True, cash_usability_basis_ref="unrestricted",
                liquidity_usable_for_principal=True, principal_usability_basis_ref="synthetic:unrestricted-all-included-pool",
                liquidity_coverage_state="COMPLETE", liquidity_scope_ref="ALL_USABLE_LIQUIDITY",
                liquidity_valid_until_ms=T2+DAY, liquidity_validity_basis_ref="current-cash-proof"),
            obligations=[evidence(source_class="SEC", payment_reference="debt-1:payment-1", due_at_ms=T2+20*DAY,
                amount_usd=120, obligation_kind="DEBT_PRINCIPAL", recognition="CONFIRMED", amount_basis_ref="contract")],
            coverage=evidence(coverage_state="COMPLETE", scope_ref="ALL_FIXED_OBLIGATIONS", covered_until_ms=T2+180*DAY))
        args.update(changes)
        return build_fixed_obligation_windows(**args)

    def test_fixed_dates_prove_shortfall_without_survival_forecast(self):
        result = self.windows()
        self.assertEqual([r["days"] for r in result["windows"]], [30, 90, 180])
        self.assertEqual(result["qualified_usable_liquidity_usd"], 100)
        self.assertEqual(result["windows"][0]["proven_minimum_shortfall_usd"], 20)
        self.assertEqual(result["first_proven_shortfall_date_ms"], T2+20*DAY)

    def test_existing_maturity_is_reused_but_duplicate_principal_is_not_added_twice(self):
        maturity = evidence(source_class="SEC", maturity_id="bond", payment_reference="bond:final-principal",
            due_at_ms=T2+50*DAY, principal_due_usd=150, basis_ref="bond-contract")
        result = self.windows(obligations=[], maturities=[maturity])
        self.assertEqual(result["windows"][1]["confirmed_total_usd"], 150)
        duplicate = {**maturity, "amount_usd": 150, "amount_basis_ref": "bond-contract",
            "recognition": "CONFIRMED", "obligation_kind": "DEBT_PRINCIPAL"}
        result = self.windows(obligations=[duplicate], maturities=[maturity])
        self.assertFalse(result["schedule_complete"])
        self.assertEqual(result["confirmed"], [])
        self.assertFalse(self.windows(obligations=[], maturities={})["schedule_complete"])

    def test_incomplete_schedule_preserves_known_due_but_cannot_claim_funded(self):
        result = self.windows(coverage=None)
        self.assertEqual(result["windows"][0]["known_confirmed_subtotal_usd"], 120)
        self.assertIsNone(result["windows"][0]["confirmed_total_usd"])
        self.assertIsNone(result["windows"][0]["complete_schedule_balance_usd"])
        self.assertEqual(result["windows"][0]["proven_minimum_shortfall_usd"], 20)

    def test_undeclared_dividend_scenario_not_confirmed_obligation(self):
        dividend = evidence(source_class="SEC", payment_reference="SATA:future", due_at_ms=T2+60*DAY,
            amount_usd=30, obligation_kind="PREFERRED_DIVIDEND", recognition="UNDECLARED_TERMS_SCENARIO",
            security_outstanding_at_ms=T1, security_id="SATA", amount_basis_ref="future-terms-scenario")
        result = self.windows(obligations=[dividend])
        self.assertEqual(result["windows"][1]["confirmed_total_usd"], 0)
        self.assertEqual(result["windows"][1]["undeclared_terms_scenario_usd"], 30)
        dividend["security_outstanding_at_ms"] = T2+DAY
        self.assertFalse(self.windows(obligations=[dividend])["schedule_complete"])

    def test_unknown_cash_and_stale_cash_do_not_become_zero(self):
        for cash in (burden(), burden(usd_cash_usable_for_carry=True, cash_usability_basis_ref="cash",
                liquidity_valid_until_ms=T2-1, liquidity_validity_basis_ref="expired")):
            result = self.windows(burden=cash)
            self.assertIsNone(result["qualified_usable_liquidity_usd"])
            self.assertIsNone(result["windows"][0]["proven_minimum_shortfall_usd"])

    def test_known_cash_insufficiency_not_company_shortfall_without_complete_liquidity(self):
        cash = burden(usd_cash_usable_for_carry=True, cash_usability_basis_ref="cash",
                liquidity_usable_for_principal=True, principal_usability_basis_ref="synthetic:free-cash",
                liquidity_valid_until_ms=T2+DAY, liquidity_validity_basis_ref="current")
        result = self.windows(burden=cash)
        self.assertEqual(result["windows"][0]["known_cash_only_gap_usd"], 20)
        self.assertIsNone(result["windows"][0]["proven_minimum_shortfall_usd"])
        self.assertIsNone(result["first_proven_shortfall_date_ms"])

    def test_duplicate_payments_or_future_visibility_cannot_fill_schedule(self):
        row = evidence(source_class="SEC", payment_reference="one-payment", due_at_ms=T2+DAY,
            amount_usd=10, obligation_kind="DEBT_INTEREST", recognition="CONFIRMED", amount_basis_ref="contract")
        result = self.windows(obligations=[row, deepcopy(row)])
        self.assertEqual(result["confirmed"], [])
        self.assertFalse(result["schedule_complete"])
        row["retrieval_time"] = T2+1
        self.assertEqual(self.windows(obligations=[row])["confirmed"], [])

    def test_priced_funding_cannot_enter_conversion_health_route(self):
        raw = conversion(funding_stage="PRICED")
        data = kwargs()
        data["capital_conversion_events"] = [raw]
        result = build_treasury_company_ct(**data)
        self.assertEqual(result["organs"]["capital_conversion"]["events"], [])

    def test_v011_pit_semantics_and_future_leakage_are_fail_closed(self):
        row = evidence(T1, disclosure_time=T1 + 1, first_seen_time=T1 + 2, retrieval_time=T1 + 3)
        self.assertEqual(validate_pit_replay(row, issuer_id=ISSUER, replay_at=T1, mode="DECISION_REPLAY")["state"], "BLOCKED")
        self.assertEqual(validate_pit_replay(row, issuer_id=ISSUER, replay_at=T1 + 3, mode="AUDIT_REPLAY")["state"], "AVAILABLE")
        row.pop("first_seen_time")
        self.assertEqual(validate_pit_replay(row, issuer_id=ISSUER, replay_at=T2, mode="AUDIT_REPLAY")["state"], "BLOCKED")

    def test_v011_semantic_lines_sensor_import_and_net_bps_are_nontrading(self):
        data = kwargs()
        data["price_financing_state"]["source_semantic"]["identity"] = "SAYLORTRACKER_DILUTED_MNAV_RESEARCH"
        self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])
        admitted = admit_saylortracker_sensor({"sensor_id": "st-1", "admission_ref": "manual-review",
            "approved_by": "analyst", "approved_at": "2026-09-14", "coverage": "MSTR diluted mNAV",
            "source_class": "RESEARCH_SECONDARY", "collection_method": "OFFLINE_CSV_IMPORT"})
        imported = import_saylortracker_offline_csv("effective_time,disclosure_time,first_seen_time,mnav\n10,11,12,1.2\n", admitted, retrieval_time=13)
        self.assertEqual(imported["state"], "RESEARCH_SECONDARY")
        self.assertFalse(imported["trading_threshold_eligible"])
        self.assertFalse(imported["formal_history_eligible"])
        self.assertEqual(imported["rows"][0]["formula_version"], "LEGACY_UNQUALIFIED")
        attribution = build_net_bps_attribution(opening_btc=100, closing_btc=120, opening_shares=100,
            closing_shares=110, components={key: 0 for key in ("Market Translation", "Asset Action", "Claim Action", "Reserve Action", "Share Denominator")}, semantic_state="RESEARCH_CANDIDATE")
        self.assertEqual(attribution["state"], "RESEARCH_CANDIDATE")
        self.assertEqual(build_net_bps_attribution(opening_btc=1, closing_btc=1, opening_shares=1, closing_shares=1, components={}, semantic_state="UNBOUND")["state"], "BLOCKED")
    def test_case_a_holdings_growth_does_not_hide_dilution(self):
        data = kwargs()
        data["asset_history"] = [asset(T1, 100), asset(T2, 110, 115)]
        result = build_treasury_company_ct(**data)["organs"]["per_share_asset_engine"]
        self.assertAlmostEqual(result["btc_per_diluted_share_change_pct"], 1.1 / 1.15 - 1)
        self.assertEqual(result["direction"], "DETERIORATING")

    def test_case_b_divergent_asset_and_burden(self):
        data = kwargs()
        data.update(asset_history=[asset(T1, 100), asset(T2, 99)], burden_current=burden(carry=85, claims=900))
        organs = build_treasury_company_ct(**data)["organs"]
        self.assertEqual(organs["per_share_asset_engine"]["direction"], "DETERIORATING")
        self.assertAlmostEqual(organs["capital_burden_resilience"]["annual_carry_change_pct"], -.15)
        self.assertAlmostEqual(organs["capital_burden_resilience"]["senior_claims_change_pct"], -.10)
        self.assertEqual(organs["capital_burden_resilience"]["annual_carry_direction"], "IMPROVING")

    def test_case_c_positive_accretion_decelerates_and_funding_deteriorates(self):
        data = kwargs()
        data["asset_history"] = [asset(T0, 100), asset(T1, 110), asset(T2, 111)]
        organs = build_treasury_company_ct(**data)["organs"]
        self.assertEqual(organs["per_share_asset_engine"]["direction"], "IMPROVING")
        self.assertEqual(organs["per_share_asset_engine"]["growth_direction"], "DECELERATING")
        self.assertEqual(organs["funding_engine"]["instruments"][0]["cost_direction"], "DETERIORATING")

    def test_case_d_funding_absorption_conversion_and_accretion(self):
        data = kwargs()
        data["capital_conversion_events"] = [conversion()]
        result = build_treasury_company_ct(**data)
        organs = result["organs"]
        self.assertEqual(organs["funding_engine"]["instruments"][0]["observed_funding_use_usd"], 300)
        self.assertIsNotNone(organs["funding_engine"]["instruments"][0]["market_absorption_evidence"])
        self.assertEqual(organs["capital_conversion"]["events"][0]["btc_change"], 10)
        self.assertEqual(organs["per_share_asset_engine"]["direction"], "IMPROVING")
        self.assertEqual(result["reflexivity_diagnosis"], {"state": "GPT_JUDGMENT_REQUIRED"})

    def test_case_e_asset_improves_while_carry_and_claims_rise(self):
        data = kwargs()
        data["burden_current"] = burden(carry=120, claims=1300)
        organs = build_treasury_company_ct(**data)["organs"]
        self.assertEqual(organs["per_share_asset_engine"]["direction"], "IMPROVING")
        for field in ("annual_carry_direction", "senior_claims_direction"):
            self.assertEqual(organs["capital_burden_resilience"][field], "DETERIORATING")

    def test_case_f_all_four_routes_retain_explicit_consequences(self):
        data = kwargs()
        data["capital_conversion_events"] = [conversion(),
            conversion("dividend", destination="STRC_DIVIDEND", btc_change=0),
            conversion("cash-repurchase", "USD_CASH", "STRC_REPURCHASE", btc_change=0,
                       senior_claim_change_usd=-100, annual_carry_change_usd=-10),
            conversion("btc-repurchase", "BTC_SALE", "STRC_REPURCHASE", btc_change=-1,
                       senior_claim_change_usd=-100, annual_carry_change_usd=-10)]
        events = build_treasury_company_ct(**data)["organs"]["capital_conversion"]["events"]
        by_id = {e["event_id"]: e for e in events}
        self.assertEqual(len(events), 4)
        self.assertEqual(by_id["dividend"]["annual_carry_change_usd"], 0)
        for key in ("cash-repurchase", "btc-repurchase"):
            self.assertEqual(by_id[key]["annual_carry_change_usd"], -10)
            self.assertEqual(by_id[key]["senior_claim_change_usd"], -100)

    def test_missing_source_time_issuer_or_validation_blocks_only_affected_record(self):
        for key, value in (("source_ref", ""), ("verification_state", "UNKNOWN"),
                           ("issuer_id", "wrong"), ("disclosure_time", T2 + 1),
                           ("effective_time", T2 + 1)):
            with self.subTest(key=key):
                data = kwargs()
                data["burden_current"][key] = value
                result = build_treasury_company_ct(**data)
                self.assertIsNone(result["organs"]["capital_burden_resilience"]["current"])
                self.assertEqual(result["organs"]["per_share_asset_engine"]["direction"], "IMPROVING")

    def test_single_asset_level_survives_missing_history(self):
        data = kwargs()
        data["asset_history"] = [asset(T2, 100)]
        result = build_treasury_company_ct(**data)["organs"]["per_share_asset_engine"]
        self.assertEqual(result["current"]["btc_per_diluted_share"], 1)
        self.assertIsNone(result["direction"])
        self.assertEqual(result["state"], "PARTIAL")

    def test_invalid_intervening_or_latest_observation_is_not_silently_skipped(self):
        for index in (1, 2):
            data = kwargs()
            data["asset_history"][index]["source_ref"] = ""
            result = build_treasury_company_ct(**data)["organs"]["per_share_asset_engine"]
            self.assertIsNone(result["direction"])
            self.assertIsNone(result["growth_direction"])
            self.assertEqual(len(result["observations"]), 2)

    def test_basis_mismatch_and_duplicate_times_keep_levels_but_block_comparison(self):
        for change in ({"basis_ref": "different-split-basis"}, {"effective_time": T1}):
            data = kwargs()
            data["asset_history"][-1].update(change)
            result = build_treasury_company_ct(**data)["organs"]["per_share_asset_engine"]
            self.assertIsNone(result["direction"])
            self.assertTrue(result["observations"])

    def test_unequal_spans_do_not_invent_deceleration_or_horizons(self):
        data = kwargs()
        data["asset_history"][0]["effective_time"] -= DAY
        result = build_treasury_company_ct(**data)["organs"]["per_share_asset_engine"]
        self.assertIsNone(result["growth_direction"])
        self.assertIsNotNone(result["direction"])
        self.assertNotIn("90D", result)

    def test_invalid_numeric_and_zero_denominator_never_emit_nonfinite_values(self):
        for value in (True, [], float("nan"), float("inf"), -1, 10 ** 1000, 0):
            data = kwargs()
            data["asset_history"][-1]["diluted_shares"] = value
            result = build_treasury_company_ct(**data)
            self.assertIsNone(result["organs"]["per_share_asset_engine"]["direction"])
            json.dumps(result, allow_nan=False)

    def test_zero_btc_is_valid_level_but_zero_base_change_is_blocked(self):
        data = kwargs()
        data["asset_history"] = [asset(T1, 0), asset(T2, 10)]
        result = build_treasury_company_ct(**data)["organs"]["per_share_asset_engine"]
        self.assertEqual(result["previous"]["btc_per_diluted_share"], 0)
        self.assertIsNone(result["direction"])

    def test_unknown_reserve_and_overlapping_cash_are_excluded(self):
        for flag in (None, 1, [], True):
            data = kwargs()
            data["burden_current"].update(usd_reserve_usd=900, reserve_usable_for_carry=flag)
            result = build_treasury_company_ct(**data)["organs"]["capital_burden_resilience"]["current"]
            self.assertEqual(result["usable_liquidity_usd"], 100)
            self.assertEqual(result["carry_coverage_years"], 1)
        data["burden_current"]["reserve_separate_from_cash"] = True
        result = build_treasury_company_ct(**data)["organs"]["capital_burden_resilience"]["current"]
        self.assertEqual(result["usable_liquidity_usd"], 1000)

    def test_missing_burden_component_preserves_independent_fields(self):
        data = kwargs()
        del data["burden_current"]["annual_preferred_distributions_usd"]
        result = build_treasury_company_ct(**data)["organs"]["capital_burden_resilience"]["current"]
        self.assertIsNone(result["annual_carry_usd"])
        self.assertEqual(result["senior_claims_usd"], 1000)

    def test_nominal_capacity_never_becomes_usable_by_subtraction(self):
        data = kwargs()
        del data["funding_instruments"][0]["usability_basis_ref"]
        row = build_treasury_company_ct(**data)["organs"]["funding_engine"]["instruments"][0]
        self.assertEqual(row["remaining_nominal_capacity_usd"], 700)
        self.assertIsNone(row["usable_capacity_usd"])
        self.assertEqual(row["observed_funding_use_usd"], 300)

    def test_market_dependent_absorption_remains_locked(self):
        data = kwargs()
        data["funding_instruments"][0]["market_absorption_evidence"]["evidence_kind"] = "MARKET_REACTION"
        row = build_treasury_company_ct(**data)["organs"]["funding_engine"]["instruments"][0]
        self.assertIsNone(row["market_absorption_evidence"])

    def test_maturities_report_amount_and_time_without_total_or_score(self):
        data = kwargs()
        data["maturities"] = [evidence(maturity_id="bond-1", principal_due_usd=200, due_at_ms=T2 + 30 * DAY)]
        row = build_treasury_company_ct(**data)["organs"]["capital_burden_resilience"]["maturities"][0]
        self.assertEqual(row["days_to_maturity"], 30)
        self.assertEqual(row["principal_due_usd"], 200)

    def test_empty_lists_need_verified_coverage(self):
        data = kwargs()
        data["coverage"] = {}
        result = build_treasury_company_ct(**data)["organs"]
        self.assertEqual(result["capital_conversion"]["state"], "BLOCKED")
        self.assertEqual(result["funding_engine"]["state"], "PARTIAL")

    def test_duplicate_events_and_unverified_consequences_fail_closed(self):
        data = kwargs()
        data["capital_conversion_events"] = [conversion(), conversion()]
        self.assertEqual(build_treasury_company_ct(**data)["organs"]["capital_conversion"]["events"], [])
        data["capital_conversion_events"] = [conversion()]
        del data["capital_conversion_events"][0]["consequence_basis_ref"]
        row = build_treasury_company_ct(**data)["organs"]["capital_conversion"]["events"][0]
        self.assertEqual(row["destination"], "BTC_PURCHASE")
        self.assertIsNone(row["btc_change"])

    def test_management_supersession_keeps_action_not_quality_score(self):
        data = kwargs()
        data["management_events"] = [evidence(event_id="repurchase", action_type="PREFERRED_REPURCHASE",
            action_ref="verified-announcement", active_for_calculation=False, score=99)]
        row = build_treasury_company_ct(**data)["organs"]["management_evidence"]["events"][0]
        self.assertFalse(row["active_for_calculation"])
        self.assertNotIn("score", row)

    def test_formal_mnav_ref_and_upstream_state_are_required(self):
        for key, value in (("semantic_ref", "invented"), ("evidence_alignment_state", "PARTIAL"),
                           ("schema_version", "invented"), ("state", "BLOCKED")):
            data = kwargs()
            data["price_financing_state"][key] = value
            result = build_treasury_company_ct(**data)
            self.assertIsNone(result["price_financing_state"]["mnav"])
            self.assertEqual(result["organs"]["per_share_asset_engine"]["state"], "AVAILABLE")
        self.assertEqual(build_treasury_company_ct(**kwargs())["price_financing_state"]["mnav"], .65)

    def test_no_mutation_deterministic_and_no_machine_decision(self):
        data = kwargs()
        before = deepcopy(data)
        result = build_treasury_company_ct(**data)
        self.assertEqual(data, before)
        self.assertEqual(result, build_treasury_company_ct(**data))
        self.assertEqual(result["state"], "COMPLETE")
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertFalse(result["external_action_performed"])
        text = json.dumps(result)
        for forbidden in ('"health_score"', '"reflexivity_score"', '"BUY"', '"SELL"', '"ROTATE"', '"HOLD"'):
            self.assertNotIn(forbidden, text)

    def test_pack_integration_reuses_sections_and_hashes_contribution(self):
        data = kwargs()
        data["capital_conversion_events"] = [conversion()]
        reflexivity = {key: empty_section() for key in (
            "issuer_facts", "issuer_events", "market_reaction_facts", "reflexivity_blockers")}
        with tempfile.TemporaryDirectory() as folder:
            baseline = build_evidence_pack(gate(0), observation_db=Path(folder) / "a.db", generated_at_ms=T2, reflexivity_input=reflexivity)
            result = build_evidence_pack(gate(0), observation_db=Path(folder) / "b.db", generated_at_ms=T2,
                reflexivity_input=reflexivity, treasury_company_ct_input=data)
        self.assertEqual(set(result), set(baseline) | {"common_equity_health"})
        self.assertIn("company_health", result["common_equity_health"]["assets"]["MSTR"])
        self.assertEqual(len(result["asset_facts"]["items"]), 6)
        self.assertEqual(len(result["decision_relevant_events"]["items"]), 1)
        self.assertNotIn("empty_reason", result["decision_relevant_events"])
        self.assertNotEqual(result["evidence_pack_hash"], baseline["evidence_pack_hash"])
        digest = result.pop("evidence_pack_hash")
        self.assertEqual(digest, hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        self.assertEqual(result["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(result["decision_relevant_events"]["items"][0]["source_event_id"], "buy")
        material = {key: deepcopy(result[key]) for key in ("asset_facts", "decision_relevant_events", "blockers")}
        for section in material.values():
            overlay_hash = section.pop("overlay_hash")
        self.assertEqual(overlay_hash, hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_mnav_ratio_tampering_blocks_only_price(self):
        data = kwargs()
        data["price_financing_state"]["mnav"] = 99
        result = build_treasury_company_ct(**data)
        self.assertIsNone(result["price_financing_state"]["mnav"])
        self.assertEqual(result["organs"]["per_share_asset_engine"]["state"], "AVAILABLE")

    def test_mnav_components_and_formula_are_retained_in_ct(self):
        result = build_treasury_company_ct(**kwargs())["price_financing_state"]
        self.assertEqual(result["schema_version"], MNAV_SCHEMA_VERSION)
        self.assertEqual(result["formula_version"], FORMULA_VERSION)
        self.assertEqual(result["denominator_basis"], DENOMINATOR_BASIS)
        self.assertEqual(result["btc_market_value_usd"], 100)
        self.assertEqual(result["input_evidence"]["diluted_shares"]["dilution_scope"],
                         "SYNTHETIC_FULLY_DILUTED_ORIGINAL_SCOPE")
        self.assertEqual(result["mnav"], .65)

    def test_self_consistent_claim_adjusted_denominator_cannot_pass(self):
        data = kwargs()
        row = data["price_financing_state"]
        row.update(asset_nav_usd=80, btc_market_value_usd=80, mnav=65/80)
        result = build_treasury_company_ct(**data)
        self.assertIsNone(result["price_financing_state"]["mnav"])
        self.assertEqual(result["organs"]["per_share_asset_engine"]["state"], "AVAILABLE")

    def test_legacy_schema_or_formula_cannot_be_relabelled_formal(self):
        for key, value in (("schema_version", "CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.1"),
                           ("formula_version", "CLAIM_ADJUSTED_NAV_V1"),
                           ("denominator_basis", "NET_ASSETS_AFTER_CLAIMS")):
            with self.subTest(key=key):
                data = kwargs()
                data["price_financing_state"][key] = value
                self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])

    def test_missing_component_proof_blocks_price_without_erasing_btc_facts(self):
        for key in ("diluted_shares", "equity_price_usd", "btc_holdings", "btc_price_usd"):
            with self.subTest(key=key):
                data = kwargs()
                del data["price_financing_state"]["input_evidence"][key]
                result = build_treasury_company_ct(**data)
                self.assertIsNone(result["price_financing_state"]["mnav"])
                self.assertEqual(result["organs"]["per_share_asset_engine"]["state"], "AVAILABLE")

    def test_mnav_asset_and_ct_issuer_cannot_disagree(self):
        data = kwargs()
        data["price_financing_state"]["asset_id"] = "ASST"
        self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])

    def test_mnav_future_retrieval_and_cross_date_components_block(self):
        for key, value in (("retrieval_time", T2+1), ("effective_time", T1)):
            with self.subTest(key=key):
                data = kwargs()
                data["price_financing_state"]["input_evidence"]["btc_holdings"][key] = value
                self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])
        data = kwargs()
        data["price_financing_state"]["retrieval_time"] = T2+1
        self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])

    def test_mnav_scope_and_ct_snapshot_time_must_match_components(self):
        for change in ({"share_basis_ref": "silently-excluding-warrants"},
                       {"effective_time": T1}):
            with self.subTest(change=change):
                data = kwargs()
                data["price_financing_state"].update(change)
                self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])

    def test_partial_original_share_scope_is_preserved_and_cannot_pass(self):
        data = kwargs()
        row = data["price_financing_state"]["input_evidence"]["diluted_shares"]
        row.update(coverage_state="PARTIAL", dilution_scope="AFDS_EXCLUDES_TRADITIONAL_WARRANTS")
        before = deepcopy(data)
        result = build_treasury_company_ct(**data)
        self.assertIsNone(result["price_financing_state"]["mnav"])
        self.assertEqual(data, before)

    def test_mnav_zero_and_unknown_components_fail_closed(self):
        for value in (0, None):
            with self.subTest(value=value):
                data = kwargs()
                data["price_financing_state"]["btc_holdings"] = value
                data["price_financing_state"]["input_evidence"]["btc_holdings"]["value"] = value
                self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])

    def test_btc_market_value_receipt_cannot_be_tampered(self):
        data = kwargs()
        data["price_financing_state"]["btc_market_value_usd"] = 1234
        self.assertIsNone(build_treasury_company_ct(**data)["price_financing_state"]["mnav"])

    def test_pack_preserves_existing_blockers_and_independent_ct_facts(self):
        data = kwargs()
        data["price_financing_state"] = None
        with tempfile.TemporaryDirectory() as folder:
            result = build_evidence_pack(gate(0), observation_db=Path(folder) / "a.db",
                generated_at_ms=T2, treasury_company_ct_input=data)
        self.assertTrue(any(row["code"] == "REFLEXIVITY_INPUT_MISSING" for row in result["blockers"]["items"]))
        asset = next(row for row in result["asset_facts"]["items"] if row["ct_section"] == "per_share_asset_engine")
        self.assertEqual(asset["evidence"]["state"], "AVAILABLE")
        self.assertEqual(result["asset_facts"]["section_state"], "BLOCKED")

    def test_pack_rejects_ct_from_future(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            build_evidence_pack(gate(0), observation_db=Path(folder) / "a.db",
                generated_at_ms=T1, treasury_company_ct_input=kwargs())

    def test_invalid_collection_shapes_are_claim_scoped(self):
        for key in ("asset_history", "funding_instruments", "maturities", "capital_conversion_events", "management_events"):
            data = kwargs()
            data[key] = {"bad": True}
            result = build_treasury_company_ct(**data)
            self.assertEqual(result["price_financing_state"]["state"], "AVAILABLE")
            self.assertTrue(result["blockers"])

    def test_numeric_overflow_and_missing_share_basis_preserve_holdings(self):
        for change in ({"diluted_shares": 1e-300, "btc_holdings": 1e300}, {"basis_ref": None}):
            data = kwargs()
            data["asset_history"][-1].update(change)
            result = build_treasury_company_ct(**data)["organs"]["per_share_asset_engine"]
            self.assertIsNone(result["current"]["btc_per_diluted_share"])
            self.assertIsNotNone(result["current"]["btc_holdings"])
            json.dumps(result, allow_nan=False)

    def test_reversed_burden_time_and_changed_cost_basis_block_only_comparisons(self):
        data = kwargs()
        data["burden_previous"] = burden(T2)
        data["funding_instruments"][0]["previous_cost"]["cost_basis_ref"] = "different"
        organs = build_treasury_company_ct(**data)["organs"]
        self.assertIsNone(organs["capital_burden_resilience"]["annual_carry_direction"])
        self.assertEqual(organs["capital_burden_resilience"]["current"]["annual_carry_usd"], 100)
        self.assertIsNone(organs["funding_engine"]["instruments"][0]["cost_direction"])

    def test_usable_capacity_cannot_exceed_nominal_remainder(self):
        data = kwargs()
        data["funding_instruments"][0]["usable_capacity_usd"] = 800
        row = build_treasury_company_ct(**data)["organs"]["funding_engine"]["instruments"][0]
        self.assertIsNone(row["usable_capacity_usd"])
        self.assertEqual(row["remaining_nominal_capacity_usd"], 700)


if __name__ == "__main__":
    unittest.main()
