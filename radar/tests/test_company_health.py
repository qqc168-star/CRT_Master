from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from crt_radar.company_health import build_health_dimensions, compact_health_dimensions
from crt_radar.portfolio_allocation_context import build_common_equity_health, _health_tilt
from crt_radar.treasury_company_ct import build_treasury_company_ct
from crt_radar.gpt_handoff import build_minimized_bridge_payload, run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice
from test_treasury_company_ct import kwargs, evidence, asset, burden, conversion, T1, T2, ISSUER
from test_gpt_handoff import bridge_pack, pack
from test_treasury_valuation_context import inputs as valuation_inputs, NOW
from test_portfolio_allocation_context import pack_for, inputs as allocation_inputs, private_context
from crt_radar.portfolio_allocation_context import build_portfolio_allocation_context
from crt_radar.treasury_company_ct import add_treasury_valuation_context
from crt_radar.evidence_pack import build_evidence_pack
from test_first_evidence_slice import gate
import test_daily_evidence_runner as daily_fixtures
from crt_radar.daily_evidence_runner import run_daily_evidence


def scenario(strive=False):
    data = kwargs()
    data["asset_history"] = [asset(T1, 100), asset(T2, 120 if strive else 110, 110 if strive else 120)]
    data["burden_previous"] = burden(T1, carry=100, claims=1000)
    data["burden_current"] = burden(T2, carry=120 if strive else 90, claims=1200 if strive else 900)
    for label, cash in (("burden_previous", 1000), ("burden_current", 800)):
        data[label].update(usd_cash_usd=cash, usd_cash_usable_for_carry=True,
                           cash_usability_basis_ref="synthetic:unrestricted-cash")
    instrument = data["funding_instruments"][0]
    instrument.update(instrument_id="SATA" if strive else "STRC", instrument_type="PREFERRED",
                      annual_cost_rate_pct=9,
                      absorption_comparison={label: evidence(at, basis_ref="net-comparable-period",
                          window_ms=T2-T1, net_proceeds_usd=value)
                          for label, at, value in (("previous", T1, 100), ("current", T2, 200))})
    data["capital_conversion_events"] = [
        {**conversion(key="old"), **{k: T1 for k in ("effective_time", "disclosure_time", "first_seen_time", "retrieval_time")}},
        conversion(key="current", source="SATA_ISSUANCE" if strive else "MSTR_COMMON_ISSUANCE",
                   destination="BTC_PURCHASE" if strive else "STRC_REPURCHASE",
                   btc_change=20 if strive else 10, diluted_share_change=10 if strive else 20,
                   senior_claim_change_usd=200 if strive else -100,
                   annual_carry_change_usd=20 if strive else -10, liquidity_change_usd=-200),
    ]
    if strive:
        def reissuer(value):
            if isinstance(value, dict):
                if "issuer_id" in value:
                    value["issuer_id"] = "CIK-0001920406"
                for child in value.values():
                    reissuer(child)
            elif isinstance(value, list):
                for child in value:
                    reissuer(child)
        reissuer(data)
    return data


def health(data, residual=-1):
    ct = build_treasury_company_ct(**data)
    return build_health_dimensions(organs=ct["organs"], issuer_id=data["issuer_id"],
                                   as_of_ms=T2, residual_change=residual)


def aggregate(data, asset_id):
    ct = build_treasury_company_ct(**data)
    before, now = data["asset_history"][-2:]
    bps_before = before["btc_holdings"] / before["diluted_shares"]
    bps_now = now["btc_holdings"] / now["diluted_shares"]
    p = {"generated_at_ms": T2, "asset_facts": {"items": [
        {"issuer_id": data["issuer_id"], "fact_type": "TREASURY_COMPANY_CT", "ct_section": k, "evidence": v}
        for k, v in ct["organs"].items()] + [{"asset_id": asset_id, "fact_type": "TREASURY_VALUATION_CONTEXT",
            "evidence": {"current_btc_per_diluted_share": bps_now,
                         "btc_per_diluted_share_change_pct": bps_now / bps_before - 1}}]}}
    residual = {label: {"btc_price_usd": 1000, "verified_other_liquid_assets_usd": 0,
        "other_senior_claims_usd": 0, "coverage_state": "COMPLETE",
        "capital_structure_coherence_state": "VALIDATED", "capital_structure_scenario_ref": "synthetic"}
        for label in ("previous", "current")}
    return build_common_equity_health(p, {asset_id: residual})["assets"][asset_id]


class CompanyHealthTests(unittest.TestCase):
    def test_strategy_divergence_and_observed_migration(self):
        out = health(scenario())
        self.assertEqual({k: v["direction"] for k, v in out["dimensions"].items()}, {
            "per_share_asset_engine": "DETERIORATING", "common_capital_efficiency": "DETERIORATING",
            "funding_market_acceptance": "IMPROVING", "senior_claims_carry": "IMPROVING",
            "liquidity_buffer": "DETERIORATING", "capital_conversion_efficiency": "BLOCKED"})
        self.assertEqual(out["dimensions"]["capital_conversion_efficiency"]["interpretation_state"], "MIXED")
        engine = out["capital_engine"]
        self.assertEqual(engine["state"], "ANALYST_REQUIRED")
        self.assertEqual(engine["emerging_engine"][0]["destination"], "STRC_REPURCHASE")
        self.assertIn("OPPOSING_HEALTH_DIMENSIONS", engine["contradictions"])
        self.assertIn("FUTURE_FUNDING_CAPACITY_NOT_ESTABLISHED", engine["missing_evidence"])

    def test_strive_accretion_is_not_company_improvement(self):
        data = scenario(True)
        out = health(data, residual=1)
        self.assertEqual(out["dimensions"]["per_share_asset_engine"]["direction"], "IMPROVING")
        self.assertEqual(out["dimensions"]["funding_market_acceptance"]["direction"], "IMPROVING")
        self.assertEqual(out["dimensions"]["senior_claims_carry"]["direction"], "DETERIORATING")
        self.assertEqual(out["dimensions"]["capital_conversion_efficiency"]["direction"], "BLOCKED")
        self.assertEqual(out["dimensions"]["capital_conversion_efficiency"]["interpretation_state"], "MIXED")
        row = aggregate(data, "ASST")
        self.assertEqual(row["health_direction"], "BLOCKED")
        self.assertIn("MULTIDIMENSIONAL_TRADE_OFF_REQUIRES_ANALYST", row["health_reasons"])

    def test_strategy_negative_aggregate_is_also_blocked(self):
        data = scenario()
        data["capital_conversion_events"] = []
        row = aggregate(data, "MSTR")
        self.assertFalse(any(d["interpretation_state"] == "MIXED"
                             for d in row["company_health"]["dimensions"].values()))
        self.assertLess(row["btc_per_diluted_share_change_pct"], 0)
        self.assertLess(row["net_residual_value_per_diluted_share_change_pct"], 0)
        self.assertEqual(row["health_direction"], "BLOCKED")
        self.assertIn("MULTIDIMENSIONAL_TRADE_OFF_REQUIRES_ANALYST", row["health_reasons"])

    def test_trade_off_aggregates_do_not_drive_downstream_tilt(self):
        for asset_id, data, counterpart in (("MSTR", scenario(), "IMPROVING"),
                                             ("ASST", scenario(True), "STABLE")):
            with self.subTest(asset=asset_id):
                data["capital_conversion_events"] = []
                rows = {a: {"health_direction": counterpart} for a in ("MSTR", "ASST")}
                rows[asset_id] = aggregate(data, asset_id)
                for persistent in (False, True):
                    tilt = _health_tilt(65, 35, {"assets": rows},
                                       {"MSTR": "ALLOW_TILT", "ASST": "ALLOW_TILT"}, persistent)
                    self.assertEqual(tilt["health_tilt_pct"], 0)
                    self.assertEqual((tilt["suggested_mstr_pct"], tilt["suggested_asst_pct"]), (65, 35))

    def test_mixed_interpretation_preserves_availability_and_four_directions(self):
        for strive in (False, True):
            out = health(scenario(strive), 1 if strive else -1)
            dimension = out["dimensions"]["capital_conversion_efficiency"]
            self.assertEqual(dimension["direction"], "BLOCKED")
            self.assertEqual(dimension["state"], "AVAILABLE")
            self.assertEqual(dimension["interpretation_state"], "MIXED")
            self.assertTrue(dimension["analyst_judgment_required"])
            self.assertEqual(dimension["reason"], "OPPOSING_VERIFIED_CLAIM_DIRECTIONS")
            for d in out["dimensions"].values():
                for item in (d, *d["claims"].values()):
                    self.assertIn(item["direction"], {"IMPROVING", "STABLE", "DETERIORATING", "BLOCKED"})
        data = scenario()
        data["capital_conversion_events"][-1]["liquidity_change_usd"] = None
        partial = health(data)["dimensions"]["capital_conversion_efficiency"]
        self.assertEqual(partial["state"], "PARTIAL")
        self.assertEqual(partial["interpretation_state"], "MIXED")
        self.assertEqual(partial["direction"], "BLOCKED")

    def test_uniform_dimensions_preserve_legacy_polarity_with_unknown_claims(self):
        for improving in (False, True):
            data = scenario()
            if improving:
                data["asset_history"][-1].update(btc_holdings=120, diluted_shares=110)
                data["burden_current"]["usd_cash_usd"] = 1200
            else:
                data["burden_current"]["debt_principal_usd"] = 1000
                data["burden_current"]["annual_debt_interest_usd"] = 100
            # Missing funding/conversion comparisons must not invent opposition.
            data["funding_instruments"] = []
            data["capital_conversion_events"] = []
            row = aggregate(data, "MSTR")
            self.assertEqual(row["health_direction"], "IMPROVING" if improving else "DETERIORATING")
            self.assertNotIn("MULTIDIMENSIONAL_TRADE_OFF_REQUIRES_ANALYST", row["health_reasons"])

    def test_compact_dimensions_keep_scope_and_interpretation_warnings(self):
        out = health(scenario())
        compact = compact_health_dimensions(out)
        for name, original in out["dimensions"].items():
            row = compact["dimensions"][name]
            for key in ("direction", "state", "interpretation_state", "reason",
                        "analyst_judgment_required", "claim_scope"):
                self.assertEqual(row[key], original[key])
        self.assertEqual(compact["dimensions"]["funding_market_acceptance"]["claim_scope"],
                         "PRIMARY_FUNDING_ABSORPTION_AND_COST_ONLY")

    def test_unknown_cash_and_carry_do_not_become_zero(self):
        data = scenario()
        del data["burden_current"]["annual_preferred_distributions_usd"]
        del data["burden_current"]["cash_usability_basis_ref"]
        out = health(data)
        claims = out["dimensions"]["senior_claims_carry"]["claims"]
        self.assertIsNone(claims["annual_carry_usd"]["value"])
        self.assertEqual(claims["annual_carry_usd"]["direction"], "BLOCKED")
        self.assertEqual(claims["senior_claims_usd"]["direction"], "IMPROVING")
        self.assertEqual(out["dimensions"]["liquidity_buffer"]["direction"], "BLOCKED")

    def test_incompatible_basis_blocks_only_comparison(self):
        data = scenario()
        data["asset_history"][-1]["basis_ref"] = "new-basis"
        out = health(data)
        self.assertEqual(out["dimensions"]["per_share_asset_engine"]["direction"], "BLOCKED")
        self.assertEqual(out["dimensions"]["senior_claims_carry"]["direction"], "IMPROVING")

    def test_future_unvalidated_and_wrong_issuer_cannot_support_claim(self):
        for change in ({"retrieval_time": T2+1}, {"verification_state": "UNVERIFIED"}, {"issuer_id": "other"}):
            data = scenario()
            data["asset_history"][-1].update(change)
            self.assertEqual(health(data)["dimensions"]["per_share_asset_engine"]["direction"], "BLOCKED")

    def test_absorption_requires_equal_windows_and_basis(self):
        for change in ({"window_ms": 1}, {"basis_ref": "other"}, {"net_proceeds_usd": None}):
            data = scenario()
            data["funding_instruments"][0]["absorption_comparison"]["current"].update(change)
            out = health(data)["dimensions"]["funding_market_acceptance"]
            self.assertEqual(out["claims"]["STRC.market_absorption"]["direction"], "BLOCKED")
            self.assertEqual(out["claims"]["STRC.cost"]["direction"], "IMPROVING")

    def test_single_funding_level_is_not_acceptance_trend(self):
        data = scenario()
        data["funding_instruments"][0].pop("absorption_comparison")
        data["funding_instruments"][0].pop("previous_cost")
        self.assertEqual(health(data)["dimensions"]["funding_market_acceptance"]["direction"], "BLOCKED")

    def test_superseded_and_duplicate_events_cannot_establish_migration(self):
        data = scenario()
        data["capital_conversion_events"][-1]["active_for_calculation"] = False
        self.assertEqual(health(data)["capital_engine"]["emerging_engine"], [])
        data = scenario()
        data["capital_conversion_events"].append(deepcopy(data["capital_conversion_events"][-1]))
        self.assertEqual(health(data)["capital_engine"]["emerging_engine"], [])

    def test_no_common_issuance_no_efficiency_claim(self):
        data = scenario()
        data["capital_conversion_events"][-1]["source"] = "CASH"
        self.assertEqual(health(data)["dimensions"]["common_capital_efficiency"]["direction"], "BLOCKED")

    def test_residual_direction_handles_negative_base(self):
        out = health(scenario(True), residual=10)
        self.assertEqual(out["dimensions"]["per_share_asset_engine"]["claims"]["net_residual_value_per_share"]["direction"], "IMPROVING")

    def test_provenance_coverage_and_hash_bind_evidence(self):
        data = scenario()
        out = health(data)
        self.assertTrue(out["provenance"])
        self.assertEqual(out, health(data))
        data["burden_current"]["source_ref"] = "synthetic:revised"
        self.assertNotEqual(out["context_hash"], health(data)["context_hash"])
        data["coverage"].pop("funding")
        self.assertIn("COMPLETE_SCOPE_COVERAGE", health(data)["dimensions"]["funding_market_acceptance"]["missing_evidence"])

    def test_no_mutation_or_action_and_compact_full_bridge(self):
        data = scenario()
        original = deepcopy(data)
        out = health(data)
        self.assertEqual(data, original)
        for k, value in {"action_output": "NONE", "external_action_authority": "NONE",
                         "capital_decision_authority": "USER_ONLY", "machine_execution": "FORBIDDEN",
                         "production": "NOT_APPROVED", "machine_may_determine_btc_season": False}.items():
            self.assertEqual(out[k], value)
        compact = compact_health_dimensions(out)
        self.assertNotIn("provenance", compact)
        self.assertEqual(compact["context_hash"], out["context_hash"])
        p = bridge_pack(pack(evidence_hash="synthetic", requested=True))
        original_season = deepcopy(p.get("model_status"))
        p["common_equity_health"] = {"state": "PARTIAL", "assets": {
            "MSTR": {"company_health": out}, "ASST": {"company_health": health(scenario(True), 1)}}}
        with tempfile.TemporaryDirectory() as folder:
            handoff = run_gpt_handoff_gate(p, build_plain_language_notice(p), ledger_path=Path(folder)/"ledger")
            bridge = build_minimized_bridge_payload(p, handoff)
        self.assertLess(len(json.dumps(bridge, ensure_ascii=False, separators=(",", ":")).encode()), 16384)
        self.assertEqual(p.get("model_status"), original_season)
        self.assertFalse(bridge["authority"]["machine_may_execute_trade"])

    def test_full_portfolio_and_long_valuation_history_fit_bridge(self):
        p = bridge_pack(pack(evidence_hash="synthetic", requested=True))
        p["generated_at_ms"] = NOW
        p["asset_facts"] = {"items": []}
        add_treasury_valuation_context(p, {a: valuation_inputs(a, count=2100) for a in ("MSTR", "ASST")})
        p.update(build_portfolio_allocation_context(pack=pack_for(), private_context=private_context(), inputs=allocation_inputs()))
        for a, strive in (("MSTR", False), ("ASST", True)):
            p["common_equity_health"]["assets"][a]["company_health"] = health(scenario(strive), 1 if strive else -1)
        with tempfile.TemporaryDirectory() as folder:
            handoff = run_gpt_handoff_gate(p, build_plain_language_notice(p), ledger_path=Path(folder)/"ledger")
            bridge = build_minimized_bridge_payload(p, handoff)
        serialized = json.dumps(bridge, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.bridge_payload_bytes = len(serialized.encode())
        self.assertLess(self.bridge_payload_bytes, 16384)
        self.assertIn(p["common_equity_health"]["assets"]["MSTR"]["company_health"]["context_hash"], serialized)
        self.assertIn("PRIMARY_FUNDING_ABSORPTION_AND_COST_ONLY", serialized)
        self.assertIn("OPPOSING_VERIFIED_CLAIM_DIRECTIONS", serialized)
        self.assertNotIn('"mnav_observations":', serialized)

    def test_daily_runner_wires_both_issuers_without_allocation(self):
        fixture = daily_fixtures.DailyEvidenceRunnerTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory() as folder:
            p = run_daily_evidence(fixture.registry, observation_db=Path(folder)/"obs.db",
                fetch_overrides=fixture.overrides, liquidation_aggregate_payload=fixture.aggregate(),
                now_ms=daily_fixtures.NOW_MS, generated_at_ms=daily_fixtures.NOW_MS,
                treasury_company_ct_inputs={"MSTR": scenario(), "ASST": scenario(True)})
        for a, direction in (("MSTR", "DETERIORATING"), ("ASST", "IMPROVING")):
            self.assertEqual(p["common_equity_health"]["assets"][a]["company_health"]["dimensions"]
                             ["per_share_asset_engine"]["direction"], direction)
        self.assertNotIn("portfolio_allocation_context", p)

    def test_batch_issuer_binding_and_tampered_projection_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                build_evidence_pack(gate(0), observation_db=Path(folder)/"obs.db", generated_at_ms=T2,
                    treasury_company_ct_inputs={"ASST": scenario()})
        out = health(scenario())
        out["dimensions"]["per_share_asset_engine"]["direction"] = "IMPROVING"
        with self.assertRaises(ValueError):
            compact_health_dimensions(out)
