from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from crt_radar.diluted_equity_mnav import (
    DENOMINATOR_BASIS, FORMULA_VERSION, SCHEMA_VERSION as MNAV_VERSION, build_diluted_equity_mnav,
)
from crt_radar.evidence_pack import build_evidence_pack, _sha256
from crt_radar.gpt_handoff import build_minimized_bridge_payload, run_gpt_handoff_gate, _compact_treasury_bridge
from crt_radar.openai_responses_adapter_contract import build_request_envelope, SMOKE_MODEL
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.treasury_company_ct import (
    DAY_MS, FORMAL_IDENTITY, FORMAL_MNAV_REF, ISSUERS, RESEARCH_IDENTITY,
    LEGACY_RESEARCH_IDENTITY, add_treasury_valuation_context,
    build_treasury_valuation_context, compact_treasury_valuation_context,
    build_preferred_funding_attribution,
)
from test_first_evidence_slice import gate
from test_gpt_handoff import bridge_pack, pack

NOW = 1_790_000_000_000


def metadata(asset, at, **fields):
    return dict(issuer_id=ISSUERS[asset], source_ref="synthetic:verified",
        effective_time=at, disclosure_time=at, first_seen_time=at, retrieval_time=at,
        verification_state="VALIDATED", source_class="SEC",
        source_semantic=dict(identity=FORMAL_IDENTITY, version="1", effective_from=1, effective_to=None),
        **fields)


def observation(asset="MSTR", at=NOW, value=1.5, basis="same-basis", research=False):
    components = dict(diluted_shares=10, equity_price_usd=value*10,
        btc_holdings=1, btc_price_usd=100)
    input_evidence = {}
    for key, component in components.items():
        record = {**metadata(asset, at), "asset_id": "BTC" if key == "btc_price_usd" else asset,
            "value": component, "raw_sha256": "a"*64}
        if key.endswith("price_usd"):
            record["currency"] = "USD"
        if key == "diluted_shares":
            record.update(basis_ref=basis, dilution_scope="SYNTHETIC_FULLY_DILUTED_SHARE_SCOPE", coverage_state="COMPLETE")
        input_evidence[key] = record
    row = {**build_diluted_equity_mnav(asset_id=asset, diluted_equity_market_cap_usd=value*100,
        asset_nav_usd=100, semantic_ref=FORMAL_MNAV_REF, evidence_alignment_state="VALIDATED",
        **components, share_basis_ref=basis, input_evidence=input_evidence, as_of_ms=at),
        **metadata(asset, at), "basis_ref": basis}
    if research:
        row["source_class"] = "RESEARCH_SECONDARY"
        row["source_semantic"]["identity"] = RESEARCH_IDENTITY
    return row


def inputs(asset="MSTR", research=False, count=40):
    return dict(mnav_history=[observation(asset, NOW - (count-i)*DAY_MS, 1+i/count, research=research)
                             for i in range(count)] + [observation(asset, research=research)],
        asset_history=[metadata(asset, NOW-7*DAY_MS, btc_holdings=100, diluted_shares=100, basis_ref="diluted-v1"),
                       metadata(asset, NOW, btc_holdings=120, diluted_shares=110, basis_ref="diluted-v1")])


def context(asset="MSTR", **changes):
    data = inputs(asset)
    data.update(changes)
    return build_treasury_valuation_context(asset_id=asset, as_of_ms=NOW, **data)


def funding():
    return metadata("MSTR", NOW, event_id="preferred-1", active_for_calculation=True,
        consequence_basis_ref="verified-realized-period", btc_change=5, diluted_share_change=0,
        senior_claim_change_usd=100, annual_carry_change_usd=10, liquidity_change_usd=90,
        reserve_change_state="REALIZED_VERIFIED", verified_net_proceeds_usd=90,
        annual_preferred_distributions_usd=10, net_proceeds_verification_state="VALIDATED",
        net_proceeds_basis_ref="net-after-fees", cost_basis_ref="current-annual-run-rate")


class TreasuryValuationTests(unittest.TestCase):
    def test_priced_or_announced_cannot_smuggle_realized_cash_or_cost(self):
        for stage in ("ANNOUNCED", "PRICED", "UNKNOWN", "SETTLED"):
            raw = funding()
            raw.update(funding_stage=stage, conditional_terms={"offered_shares": 7_000_000})
            row = build_preferred_funding_attribution(events=[raw], issuer_id=ISSUERS["MSTR"], as_of_ms=NOW)["events"][0]
            self.assertEqual(row["realized_accounting_state"], "BLOCKED")
            self.assertTrue(all(v is None for v in row["components"].values()))
            self.assertIsNone(row["effective_preferred_funding_cost"])
            self.assertIsNone(row["claim_adjusted_reserve_delta_usd"])

    def test_settled_round_reconciles_net_uses_and_claims_without_duplicate_deduction(self):
        raw = funding()
        raw.update(funding_stage="SETTLED", settlement_time=NOW, settlement_basis_ref="synthetic-closing",
            round_accounting=dict(funding_round_id="synthetic-round", attribution_basis_ref="synthetic-official-use",
                gross_proceeds_usd=100, fees_usd=10, new_claims_usd=120, extinguished_claims_usd=20,
                btc_purchase_usd=50, other_asset_deployment_usd=5, old_claim_retirement_cash_usd=20,
                undeployed_cash_usd=15))
        def result():
            return build_preferred_funding_attribution(events=[raw], issuer_id=ISSUERS["MSTR"], as_of_ms=NOW)["events"][0]
        self.assertEqual(result()["deployment_attribution_state"], "SOURCE_BOUND_RECONCILED")
        self.assertAlmostEqual(result()["effective_preferred_funding_cost"], 10/90)
        raw["round_accounting"]["undeployed_cash_usd"] = 16
        self.assertEqual(result()["deployment_attribution_state"], "BLOCKED")
        raw["round_accounting"]["undeployed_cash_usd"] = 15
        raw["round_accounting"].pop("attribution_basis_ref")
        self.assertEqual(result()["deployment_attribution_state"], "BLOCKED")
        raw["settlement_time"] = NOW + 1
        self.assertEqual(result()["realized_accounting_state"], "BLOCKED")

    def test_balanced_round_requires_verified_net_proceeds_basis(self):
        raw = funding()
        raw.update(funding_stage="SETTLED", settlement_time=NOW, settlement_basis_ref="synthetic-closing",
            round_accounting=dict(funding_round_id="synthetic-round", attribution_basis_ref="synthetic-official-use",
                gross_proceeds_usd=100, fees_usd=10, new_claims_usd=120, extinguished_claims_usd=20,
                btc_purchase_usd=50, other_asset_deployment_usd=5, old_claim_retirement_cash_usd=20,
                undeployed_cash_usd=15))
        for field, value in (("net_proceeds_verification_state", None),
                             ("net_proceeds_verification_state", "BLOCKED"),
                             ("net_proceeds_basis_ref", None), ("net_proceeds_basis_ref", " ")):
            with self.subTest(field=field, value=value):
                case = deepcopy(raw)
                if value is None:
                    case.pop(field)
                else:
                    case[field] = value
                row = build_preferred_funding_attribution(events=[case], issuer_id=ISSUERS["MSTR"], as_of_ms=NOW)["events"][0]
                self.assertEqual(row["deployment_attribution_state"], "BLOCKED")
                self.assertEqual(row["components"]["ASSET_ACTION"], 5)
                self.assertEqual(row["components"]["CLAIM_ACTION"], 100)
                self.assertEqual(row["claim_adjusted_reserve_delta_usd"], -10)
                self.assertEqual(row["round_accounting"], raw["round_accounting"])

    def test_legacy_and_recomputed_versions_same_day_do_not_collide(self):
        data = inputs()
        old = deepcopy(data["mnav_history"][-1])
        old.update(schema_version="CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.1",
                   formula_version="LEGACY_UNPROVEN_NAV", mnav=9)
        data["mnav_history"].append(old)
        result = build_treasury_valuation_context(asset_id="MSTR", as_of_ms=NOW, **data)
        self.assertEqual(result["diluted_mnav"], 1.5)
        self.assertEqual(result["formal_action_critical_state"], "AVAILABLE")
        self.assertEqual(result["legacy_mnav_observations"][0]["reported_mnav"], 9)
        self.assertNotIn(9, [r["mnav"] for r in result["own_history_empirical_cdf_pct"]["baseline"]])

    def test_two_current_formula_declarations_same_day_remain_blocked(self):
        data = inputs()
        data["mnav_history"].append(deepcopy(data["mnav_history"][-1]))
        result = build_treasury_valuation_context(asset_id="MSTR", as_of_ms=NOW, **data)
        self.assertIsNone(result["diluted_mnav"])
        self.assertEqual(result["formal_action_critical_state"], "BLOCKED")
        self.assertTrue(any(r["code"] == "DUPLICATE_MNAV_TIME" for r in result["blockers"]))

    def test_compact_dictionaries_recover_exact_claim_values(self):
        p = {"generated_at_ms": NOW, "asset_facts": {"items": []}}
        add_treasury_valuation_context(p, {a: inputs(a, research=True) for a in ISSUERS})
        expected = compact_treasury_valuation_context(p)
        bridge = {"market_context": {"treasury_valuation_context": deepcopy(expected),
                    "minimization": {}, "layers": {}},
                  "authority": {"action_output": "NONE", "external_action_authority": "NONE"},
                  "event": {}, "analysis_contract": {}, "capital_state": {}}
        _compact_treasury_bridge(bridge)
        market = bridge["market_context"]
        keys, strings = market.get("field_names", []), market.get("literal_strings", [])
        def expand(value):
            if isinstance(value, dict):
                value = {(keys[int(k[1:])] if k.startswith("@") else k): expand(v) for k,v in value.items()}
                if set(value) == {"text_ref"}:
                    return strings[value["text_ref"]]
                return value
            if isinstance(value, list):
                return [expand(v) for v in value]
            return value
        encoded = expand(market)["treasury_valuation_context"]
        if "common" in encoded:
            actual = {}
            for asset, fields in encoded["assets"].items():
                row = {**encoded["common"], **fields}
                row["blockers"] = sorted(row.get("blockers", []) + row.pop("additional_blockers", []))
                actual[asset] = row
        elif "columns" in encoded:
            def record(v):
                if isinstance(v, dict) and set(v) == {"record"}:
                    index, *values = v["record"]
                    return dict(zip(encoded["columns"][index], map(record, values)))
                if isinstance(v, list):
                    return list(map(record, v))
                return v
            actual = {a:record(v) for a,v in encoded["assets"].items()}
        else:
            actual = encoded
        # Shared subtrees are explicit references; all essential scalars and
        # baselines must retain their original precision and authority.
        for asset in ISSUERS:
            for key in ("diluted_mnav", "five_week_mnav_change_pct", "current_btc_per_diluted_share",
                        "btc_per_diluted_share_change_pct", "evidence_authority", "context_hash"):
                self.assertEqual(actual[asset][key], expected[asset][key])
        self.assertEqual(actual, expected)

    def test_both_formal_issuers_reuse_mnav(self):
        for asset in ISSUERS:
            c = context(asset)
            self.assertEqual(c["diluted_mnav"], 1.5)
            self.assertEqual(c["formal_action_critical_state"], "AVAILABLE")

    def test_asst_research_cannot_be_promoted(self):
        c = build_treasury_valuation_context(asset_id="ASST", as_of_ms=NOW, **inputs("ASST", research=True))
        self.assertEqual(c["evidence_authority"], "RESEARCH_SECONDARY_EVIDENCE")
        self.assertEqual(c["formal_action_critical_state"], "BLOCKED")
        self.assertEqual(c["diluted_mnav"], 1.5)
        data = inputs("ASST")
        data["mnav_history"][-1]["source_class"] = "RESEARCH_SECONDARY"
        self.assertIsNone(build_treasury_valuation_context(asset_id="ASST", as_of_ms=NOW, **data)["diluted_mnav"])

    def test_semantics_mismatch_does_not_mix(self):
        data = inputs()
        data["mnav_history"][-1]["source_semantic"]["identity"] = "STRATEGY_ISSUER_MNAV"
        self.assertIsNone(context(mnav_history=data["mnav_history"])["diluted_mnav"])
        data["mnav_history"][-1] = observation(research=True)
        c = context(mnav_history=data["mnav_history"])
        self.assertEqual(c["own_history_empirical_cdf_pct"]["baseline_count"], 0)

    def test_legacy_nav_denominator_kept_explicitly_out_of_current_history(self):
        legacy = observation()
        legacy.update(schema_version="CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.1",
            semantic_ref="radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md", asset_nav_usd=90)
        legacy.pop("formula_version")
        legacy.pop("denominator_basis")
        original = deepcopy(legacy)
        c = context(mnav_history=[legacy])
        self.assertIsNone(c["diluted_mnav"])
        self.assertEqual(c["mnav_observations"], [None])
        self.assertEqual(c["legacy_mnav_observations"][0]["reported_mnav"], 1.5)
        self.assertEqual(c["legacy_mnav_observations"][0]["qualification"],
            "LEGACY_RESEARCH_ONLY_NOT_CURRENT_FORMAL_MNAV")
        self.assertEqual(c["formal_action_critical_state"], "BLOCKED")
        self.assertEqual(legacy, original)

    def test_version_switch_keeps_cdf_and_five_week_algorithm_without_legacy_pooling(self):
        data = inputs()
        old = [observation(at=NOW-(90-i)*DAY_MS, value=99) for i in range(25)]
        for row in old:
            row["formula_version"] = "LEGACY_NET_ASSETS_RATIO_V0"
        c = context(mnav_history=old + data["mnav_history"])
        self.assertEqual(len(c["legacy_mnav_observations"]), 25)
        self.assertEqual(c["own_history_empirical_cdf_pct"]["baseline_count"], 40)
        self.assertEqual(c["own_history_empirical_cdf_pct"]["value"], 52.5)
        self.assertAlmostEqual(c["five_week_mnav_change_pct"]["value"], 1.5/1.125-1)

    def test_current_legacy_row_does_not_fall_back_to_an_older_new_formula(self):
        old = observation()
        old["formula_version"] = "LEGACY_NET_ASSETS_RATIO_V0"
        c = context(mnav_history=[observation(at=NOW-DAY_MS), old])
        self.assertIsNone(c["diluted_mnav"])
        self.assertEqual(c["formal_action_critical_state"], "BLOCKED")

    def test_same_formula_research_components_are_recomputed_and_remain_secondary(self):
        row = observation(research=True)
        c = context(mnav_history=[row])
        self.assertEqual(c["diluted_mnav"], 1.5)
        self.assertEqual(c["formula_version"], FORMULA_VERSION)
        self.assertEqual(c["evidence_authority"], "RESEARCH_SECONDARY_EVIDENCE")
        self.assertEqual(c["formal_action_critical_state"], "BLOCKED")
        row["asset_nav_usd"] = 90
        self.assertIsNone(context(mnav_history=[row])["diluted_mnav"])

    def test_same_formula_different_dilution_scope_is_not_a_comparable_series(self):
        data = inputs()
        data["mnav_history"][-1]["input_evidence"]["diluted_shares"]["dilution_scope"] = "EXCLUDES_TRADITIONAL_WARRANTS"
        c = context(**data)
        self.assertEqual(c["diluted_mnav"], 1.5)
        self.assertEqual(c["own_history_empirical_cdf_pct"]["baseline_count"], 0)
        self.assertEqual(c["five_week_mnav_change_pct"]["state"], "BLOCKED")

    def test_formula_version_and_components_survive_pack_and_compact_projection(self):
        p = {"generated_at_ms": NOW, "asset_facts": {"items": []}}
        add_treasury_valuation_context(p, {a: inputs(a) for a in ISSUERS})
        compact = compact_treasury_valuation_context(p)
        for asset in ISSUERS:
            self.assertEqual(compact[asset]["formula_version"], FORMULA_VERSION)
            self.assertEqual(compact[asset]["denominator_basis"], DENOMINATOR_BASIS)
            self.assertEqual(compact[asset]["semantic_ref"], FORMAL_MNAV_REF)
            self.assertEqual(compact[asset]["mnav_schema_version"], MNAV_VERSION)
            self.assertEqual(compact[asset]["mnav_evidence_alignment_state"], "VALIDATED")
            self.assertEqual(compact[asset]["source_semantic_version"], "1")
            self.assertEqual(compact[asset]["share_basis_ref"], "same-basis")
            self.assertEqual(compact[asset]["mnav_calculation_inputs"]["btc_market_value_usd"], 100)
            self.assertEqual(compact[asset]["mnav_input_evidence"]["diluted_shares"]["value"], 10)

    def test_share_and_mnav_basis_fail_closed(self):
        data = inputs()
        data["mnav_history"][-1]["basis_ref"] = "changed"
        data["asset_history"][-1]["basis_ref"] = "changed"
        c = context(**data)
        self.assertEqual(c["own_history_empirical_cdf_pct"]["baseline_count"], 0)
        self.assertEqual(c["five_week_mnav_change_pct"]["state"], "BLOCKED")
        self.assertIsNone(c["btc_per_diluted_share_change_pct"])

    def test_empirical_cdf_ties_and_minimum(self):
        c = context()
        self.assertEqual(c["own_history_empirical_cdf_pct"]["baseline_count"], 40)
        self.assertEqual(c["own_history_empirical_cdf_pct"]["value"], 52.5)
        c = context(**inputs(count=19))
        self.assertIsNone(c["own_history_empirical_cdf_pct"]["value"])

    def test_future_effective_or_retrieval_not_in_baseline(self):
        data = inputs()
        data["mnav_history"].append(observation(at=NOW+DAY_MS, value=99))
        data["mnav_history"][0]["retrieval_time"] = NOW+1
        c = context(**data)
        self.assertEqual(c["diluted_mnav"], 1.5)
        self.assertEqual(c["own_history_empirical_cdf_pct"]["baseline_count"], 39)

    def test_regime_and_missing_benchmark_explicitly_blocked(self):
        c = context()
        for field in ("regime_empirical_cdf_pct", "benchmark_empirical_cdf_pct"):
            self.assertEqual(c[field]["state"], "BLOCKED")
            self.assertIsNone(c[field]["value"])

    def test_explicit_benchmark_and_semantic_basis(self):
        b = dict(identity="MSTR-formal-reference", asset_id="MSTR", history=inputs()["mnav_history"][:-1])
        c = context("ASST", benchmark=b)
        self.assertEqual(c["benchmark_empirical_cdf_pct"]["value"], 52.5)
        self.assertEqual(c["benchmark_empirical_cdf_pct"]["benchmark_identity"], b["identity"])
        for r in b["history"]:
            r["basis_ref"] = "incompatible"
        self.assertIsNone(context("ASST", benchmark=b)["benchmark_empirical_cdf_pct"]["value"])

    def test_five_week_exact_and_nearest_no_interpolation(self):
        c = context()
        self.assertAlmostEqual(c["five_week_mnav_change_pct"]["value"], 1.5/1.125-1)
        rows = [observation(at=NOW-36*DAY_MS, value=1), observation(at=NOW-34*DAY_MS, value=2), observation()]
        c = context(mnav_history=rows)
        self.assertEqual(c["five_week_mnav_change_pct"]["value"], .5)
        self.assertEqual(c["five_week_mnav_change_pct"]["observation_span_ms"], 36*DAY_MS)
        rows = [observation(at=NOW-39*DAY_MS), observation()]
        self.assertIsNone(context(mnav_history=rows)["five_week_mnav_change_pct"]["value"])

    def test_btc_share_accretion_and_dilution(self):
        c = context()
        self.assertAlmostEqual(c["btc_per_diluted_share_change_pct"], 120/110-1)
        data = inputs()
        data["asset_history"][-1]["diluted_shares"] = 140
        c = context(**data)
        self.assertLess(c["btc_per_diluted_share_change_pct"], 0)
        self.assertEqual(c["btc_per_diluted_share"]["direction"], "DETERIORATING")

    def test_research_holdings_cannot_supply_official_btc_share(self):
        data = inputs()
        data["asset_history"][-1]["source_class"] = "RESEARCH_SECONDARY"
        self.assertIsNone(context(**data)["current_btc_per_diluted_share"])

    def test_funding_verified_net_proceeds_only(self):
        c = context(preferred_funding_events=[funding()])
        f = c["preferred_funding_attribution"]
        self.assertTrue(f["research_only"])
        self.assertEqual(f["state"], "AVAILABLE")
        self.assertAlmostEqual(f["events"][0]["effective_preferred_funding_cost"], 10/90)
        for key in ("verified_net_proceeds_usd", "net_proceeds_verification_state", "cost_basis_ref"):
            raw = funding()
            raw.pop(key)
            raw.update(gross_authorization=1000, unused_capacity=1000, atm_ceiling=1000)
            f = context(preferred_funding_events=[raw])["preferred_funding_attribution"]
            self.assertIsNone(f["events"][0]["effective_preferred_funding_cost"])

    def test_future_carry_never_deducted(self):
        raw = funding()
        raw["future_carry_usd"] = 1000000
        f = context(preferred_funding_events=[raw])["preferred_funding_attribution"]
        self.assertEqual(f["events"][0]["claim_adjusted_reserve_delta_usd"], -10)
        raw["reserve_change_state"] = "PROJECTED"
        f = context(preferred_funding_events=[raw])["preferred_funding_attribution"]
        self.assertIsNone(f["events"][0]["claim_adjusted_reserve_delta_usd"])

    def test_duplicate_funding_and_future_clocks_fail_closed(self):
        raw = funding()
        for events in ([raw, raw], [{**raw, "retrieval_time": NOW+1}]):
            f = build_preferred_funding_attribution(events=events, issuer_id=ISSUERS["MSTR"], as_of_ms=NOW)
            self.assertFalse(f["events"])

    def test_legacy_identity_still_valid_without_pooling(self):
        row = observation(research=True)
        row["source_semantic"]["identity"] = LEGACY_RESEARCH_IDENTITY
        self.assertEqual(context(mnav_history=[row])["diluted_mnav"], 1.5)

    def test_pack_hash_binding_and_tamper(self):
        with tempfile.TemporaryDirectory() as folder:
            p = build_evidence_pack(gate(0), observation_db=Path(folder)/"a.db", generated_at_ms=NOW,
                treasury_valuation_inputs={a: inputs(a) for a in ISSUERS})
        before = deepcopy(p)
        digest = p.pop("evidence_pack_hash")
        self.assertEqual(digest, _sha256(p))
        compact = compact_treasury_valuation_context(p)
        self.assertEqual(compact["MSTR"]["diluted_mnav"], 1.5)
        fact = next(f for f in p["asset_facts"]["items"] if f.get("fact_type") == "TREASURY_VALUATION_CONTEXT")
        fact["evidence"]["diluted_mnav"] = 2
        with self.assertRaises(ValueError):
            compact_treasury_valuation_context(p)
        self.assertEqual(before["authority"]["production"], "NOT_APPROVED")

    def test_bridge_two_thousand_days_stays_local_and_locks(self):
        p = bridge_pack(pack(evidence_hash="synthetic", requested=True))
        p["generated_at_ms"] = NOW
        p["asset_facts"] = {"items": []}
        add_treasury_valuation_context(p, {a: inputs(a, count=2100) for a in ISSUERS})
        with tempfile.TemporaryDirectory() as folder:
            handoff = run_gpt_handoff_gate(p, build_plain_language_notice(p), ledger_path=Path(folder)/"ledger")
            bridge = build_minimized_bridge_payload(p, handoff)
        serialized = json.dumps(bridge, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertLess(len(serialized.encode()), 16384)
        envelope = build_request_envelope(bridge, model=SMOKE_MODEL)
        self.assertEqual(envelope["request_body"]["input"], serialized)
        self.assertNotIn('"baseline":', serialized)
        self.assertNotIn('"mnav_observations":', serialized)
        for c in compact_treasury_valuation_context(p).values():
            self.assertEqual(c["baseline_counts"]["own"], 2100)
        self.assertFalse(bridge["authority"]["machine_may_execute_trade"])
        self.assertEqual(bridge["authority"]["external_action_authority"], "NONE")
        for forbidden in ('"BUY"', '"SELL"'):
            self.assertNotIn(forbidden, json.dumps(context()))

    def test_oversize_never_truncated_or_authorized_for_transport(self):
        p = bridge_pack(pack(evidence_hash="synthetic", requested=True))
        p["generated_at_ms"] = NOW
        p["asset_facts"] = {"items": []}
        add_treasury_valuation_context(p, {a: inputs(a) for a in ISSUERS})
        p["data_health"] = {"critical_blockers": ["UNCOMPRESSIBLE_EVIDENCE_" + str(i) for i in range(1500)]}
        with tempfile.TemporaryDirectory() as folder:
            h = run_gpt_handoff_gate(p, build_plain_language_notice(p), ledger_path=Path(folder)/"ledger")
            with self.assertRaisesRegex(ValueError, "16 KiB"):
                build_minimized_bridge_payload(p,h)


if __name__ == "__main__":
    unittest.main()
