from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from crt_radar.capital_posture_context import (
    LOCKS, RAILS, _claim, build_capital_posture_context, flywheel_economics,
    full_cycle_review, main, operating_fund, seasonal_capital_rail,
)
from crt_radar.gold_research_context import _hash, build_gold_research_context
from crt_radar.commander_plan_adapter import CommanderPlanBlocked
from crt_radar.portfolio_allocation_context import build_portfolio_allocation_context
from crt_radar.treasury_company_ct import build_treasury_valuation_context
from crt_radar.deployment_posture_research_gate import translate_research_state_to_posture_constraints
from test_deployment_posture_research_gate import evaluation
from test_gold_research_context import record, NOW, DAY
from test_portfolio_allocation_context import pack_for, private_context, inputs as allocation_inputs
from test_treasury_valuation_context import inputs as treasury_inputs
import test_company_health as health_fixtures


def observation(metric, **changes):
    row = record(metric, NOW, entity="CAPITAL", cycle_id="synthetic-cycle",
                 valid_until_ms=NOW+DAY, basis_ref="synthetic:capital-review-basis")
    row.update(changes)
    return row


def anchor(**changes):
    return observation("OPERATING_PRICE_ANCHOR", approval_ref="synthetic:approved-research-anchor",
        method="EQUAL_WEIGHT_STRC_SATA_9M_AVERAGE", lookback_months=9,
        assets=["STRC", "SATA"], currency="USD", sample_start_ms=NOW-273*DAY,
        sample_end_ms=NOW, price_per_share_usd=96.87, **changes)


def economics(**changes):
    row = observation("FLYWHEEL_SCENARIO", scenario_only=True,
        current_btc_price_usd=100000, expected_winter_btc_price_usd=144000,
        horizon_years=2, crt_forward_cagr=.25, assumption_ids=["synthetic-flywheel"])
    row.update(changes)
    return row


def review(**changes):
    row = observation("FULL_CYCLE_REVIEW", btc_core_start=1, btc_core_end=1.5,
        completed_cycle=True, cycle_start_ms=NOW-1000*DAY, cycle_end_ms=NOW,
        ending_operating_capacity_shares=375, permanent_capital_loss=False,
        loss_assessment_ref="synthetic:analyst-loss-review", crt_realized_cagr=.24,
        btc_benchmark_cagr=.2, same_period_cashflow_adjusted_basis_ref="synthetic:same-period-review")
    row.update(changes)
    return row


def fixture(rail="SPRING", step=0):
    pack = {"generated_at_ms": NOW, "asset_facts": {"items": []}}
    pack.update(build_portfolio_allocation_context(pack=pack_for(), private_context=private_context(), inputs=allocation_inputs()))
    for asset in ("MSTR", "ASST"):
        pack["asset_facts"]["items"].append({"asset_id": asset, "fact_type": "TREASURY_VALUATION_CONTEXT",
            "evidence": build_treasury_valuation_context(asset_id=asset, as_of_ms=NOW, **treasury_inputs(asset))})
    pack["evidence_pack_hash"] = _hash(pack)
    gold = build_gold_research_context({"as_of_ms": NOW}, pack)
    data = {"as_of_ms": NOW, "cycle_id": "synthetic-cycle", "research_evaluation": evaluation(),
        "research_evidence_pack_hash": pack["evidence_pack_hash"],
        "current_rail": observation("CURRENT_CAPITAL_RAIL", rail=rail, step=step, recorded_by="USER",
            parent_evidence_pack_hash=pack["evidence_pack_hash"]),
        "operating_anchor": anchor(), "flywheel_scenario": economics(), "full_cycle_review": review()}
    return data, pack, gold


class CapitalPostureTests(unittest.TestCase):
    def test_real_contexts_compose_deterministically_without_mutation(self):
        data, pack, gold = fixture()
        before = deepcopy((data, pack, gold))
        result = build_capital_posture_context(data, pack, gold)
        self.assertEqual(result, build_capital_posture_context(data, pack, gold))
        self.assertEqual((data, pack, gold), before)
        self.assertEqual(result["state"], "READY_FOR_ANALYST")
        for field, value in LOCKS.items():
            self.assertEqual(result[field], value)
        self.assertEqual(result["context_hash"], _hash({k: v for k, v in result.items() if k != "context_hash"}))

    def test_gate_list_is_exact_existing_producer_list(self):
        data, pack, gold = fixture()
        out = build_capital_posture_context(data, pack, gold)
        canonical = translate_research_state_to_posture_constraints(data["research_evaluation"])
        self.assertEqual(out["required_downstream_gates"], canonical["required_downstream_gates"])
        self.assertEqual(list(out["downstream_gate_status"]), canonical["required_downstream_gates"])
        self.assertEqual(out["research_posture_candidate"]["eligibility_level"], "RESEARCH_POSTURE_CANDIDATE")

    def test_existing_governance_scan_rejects_nested_execution_override(self):
        data, pack, gold = fixture()
        data["flywheel_scenario"]["action_output"] = "BUY"
        with self.assertRaises(CommanderPlanBlocked):
            build_capital_posture_context(data, pack, gold)

    def test_external_plan_and_analyst_do_not_block_economics(self):
        out = build_capital_posture_context(*fixture())
        gates = out["downstream_gate_status"]
        for key in ("ACTIVE_CAPITAL_PLAN_AND_AVAILABLE_TRANCHE", "QUALIFIED_COMMANDER_ATTACK_AND_DEFENSE_LINES"):
            self.assertEqual(gates[key]["status"], "EXTERNAL_TO_CONTEXT")
        self.assertEqual(gates["GPT_ANALYST_JUDGMENT"]["status"], "NOT_EVALUATED")
        self.assertEqual(gates["USER_DECISION"]["status"], "PENDING_USER_DECISION")
        self.assertEqual(gates["INDEPENDENT_EVIDENCE"]["status"], "BLOCKED")
        self.assertEqual(out["flywheel_economics"]["state"], "READY_FOR_ANALYST")
        self.assertEqual(out["final_eligibility"], "NOT_DETERMINED")

    def test_spring_each_explicit_step_exposes_only_next_destination(self):
        for step, expected in enumerate(RAILS["SPRING"]):
            out = build_capital_posture_context(*fixture(step=step))
            self.assertEqual(out["current_rail_step"]["fixed_growth_pct"], expected)
            self.assertEqual(out["eligible_next_posture"]["state"], "NOT_EVALUATED")
            self.assertEqual(out["eligible_next_posture"]["strategic_destination"],
                             RAILS["SPRING"][step+1] if step < 3 else None)
            self.assertNotIn("UPSTREAM_SEASON_ANCHOR_DOCTRINE_MISMATCH",
                             [r["reason"] for r in out["contradictions"]])
            self.assertEqual(out["action_output"], "NONE")
            self.assertEqual(out["final_eligibility"], "NOT_DETERMINED")

    def test_anchor_comparison_uses_doctrine_not_rollover_step(self):
        for rail, anchor in (("SUMMER_HOLD", [55, 45]), ("AUTUMN_PRESERVATION", [80, 20]),
                             ("ANALYST_ROLLOVER", [70, 30]), ("WINTER_SPLIT", [80, 20])):
            data, pack, _ = fixture(rail=rail)
            allocation = pack["portfolio_allocation_context"]
            allocation["fixed_income_target_pct"], allocation["growth_target_pct"] = anchor
            pack["evidence_pack_hash"] = _hash({k: v for k, v in pack.items() if k != "evidence_pack_hash"})
            data["current_rail"]["parent_evidence_pack_hash"] = pack["evidence_pack_hash"]
            out = build_capital_posture_context(data, pack)
            self.assertNotIn("UPSTREAM_SEASON_ANCHOR_DOCTRINE_MISMATCH",
                             [r["reason"] for r in out["contradictions"]])

    def test_season_price_or_candidate_never_advances_recorded_step(self):
        data, pack, gold = fixture(step=1)
        data.update(formal_season="SUMMER", btc_price_usd=999999, harvest_eligible=True)
        for n in range(7):
            data["research_evaluation"] = evaluation(confirmed=n)
            out = build_capital_posture_context(data, pack, gold)
            self.assertEqual(out["current_rail_step"]["step"], 1)
            self.assertEqual(out["action_output"], "NONE")

    def test_missing_rail_does_not_assume_hold_winter_or_old_static_target(self):
        data, pack, gold = fixture()
        data.pop("current_rail")
        out = build_capital_posture_context(data, pack, gold)
        self.assertEqual(out["current_rail_step"], "BLOCKED")
        self.assertIsNone(out["eligible_next_posture"]["strategic_destination"])
        self.assertEqual(out["operating_fund"]["state"], "READY_FOR_ANALYST")

    def test_rail_requires_user_record_cycle_lineage_and_freshness(self):
        for field, value in (("recorded_by", "MACHINE"), ("cycle_id", "old-cycle"),
            ("parent_evidence_pack_hash", "wrong"), ("valid_until_ms", NOW-1),
            ("step", True), ("step", 4), ("verification_state", "SOURCE_CLAIM")):
            data, pack, gold = fixture()
            data["current_rail"][field] = value
            self.assertEqual(build_capital_posture_context(data, pack, gold)["current_rail_step"], "BLOCKED")

    def test_summer_hold_autumn_and_winter_do_not_recycle_core(self):
        for rail in ("SUMMER_HOLD", "AUTUMN_PRESERVATION", "WINTER_SPLIT"):
            out = build_capital_posture_context(*fixture(rail=rail))
            self.assertIsNone(out["eligible_next_posture"]["strategic_destination"])
            self.assertFalse(out["portfolio_implication"]["btc_core_automatic_spring_recycling"])
            self.assertEqual(out["portfolio_implication"]["tactical_denominator"], "FIXED_GROWTH_EXCLUDES_BTC_CORE")

    def test_rollover_path_is_never_machine_confirmed(self):
        for step in range(4):
            out = build_capital_posture_context(*fixture(rail="ANALYST_ROLLOVER", step=step))
            self.assertEqual(out["current_rail_step"]["fixed_growth_pct"], RAILS["ANALYST_ROLLOVER"][step])
            self.assertEqual(out["harvest_judgment_status"], "NOT_EVALUATED")
            for forbidden in ("VALUATION_REALIZED", "ROLLOVER_CONFIRMED", "HARVEST_ELIGIBLE"):
                self.assertNotIn(forbidden, json.dumps(out))

    def test_dual_lane_availability_is_not_harvest_eligibility(self):
        out = build_capital_posture_context(*fixture())
        self.assertEqual(out["harvest_review_state"], "READY_FOR_ANALYST")
        self.assertEqual(out["final_eligibility"], "NOT_DETERMINED")
        data, pack, gold = fixture()
        data.pop("research_evaluation")
        self.assertEqual(build_capital_posture_context(data, pack, gold)["harvest_review_state"], "BLOCKED")

    def test_missing_one_asset_valuation_blocks_only_harvest_review(self):
        data, pack, gold = fixture()
        pack["asset_facts"]["items"].pop()
        pack.pop("evidence_pack_hash")
        pack["evidence_pack_hash"] = _hash(pack)
        data["research_evidence_pack_hash"] = pack["evidence_pack_hash"]
        out = build_capital_posture_context(data, pack)
        self.assertEqual(out["valuation_realization_evidence"]["ASST"]["state"], "BLOCKED")
        self.assertEqual(out["harvest_review_state"], "BLOCKED")
        self.assertEqual(out["flywheel_economics"]["state"], "READY_FOR_ANALYST")

    def test_research_evaluation_is_parent_bound_not_unrelated_candidate(self):
        data, pack, gold = fixture()
        data["research_evidence_pack_hash"] = "unrelated-pack"
        out = build_capital_posture_context(data, pack, gold)
        self.assertEqual(out["research_posture_candidate"]["posture_candidate"], "NONE")
        self.assertEqual(out["structure_rollover_evidence"]["state"], "BLOCKED")

    def test_hurdle_and_margin_use_explicit_prices_time_and_scenario(self):
        out = flywheel_economics(economics(), as_of=NOW, cycle_id="synthetic-cycle")
        self.assertAlmostEqual(out["btc_opportunity_hurdle"], .2)
        self.assertAlmostEqual(out["flywheel_margin"], .05)
        out = flywheel_economics(economics(expected_winter_btc_price_usd=64000), as_of=NOW, cycle_id="synthetic-cycle")
        self.assertAlmostEqual(out["btc_opportunity_hurdle"], -.2)
        self.assertAlmostEqual(out["flywheel_margin"], .45)

    def test_economic_required_values_never_default_or_accept_nonfinite(self):
        for field in ("current_btc_price_usd", "expected_winter_btc_price_usd", "horizon_years", "crt_forward_cagr"):
            for value in (None, True, float("nan"), float("inf")):
                out = _claim(flywheel_economics, economics(**{field: value}), as_of=NOW, cycle_id="synthetic-cycle")
                self.assertEqual(out["state"], "BLOCKED")
        for field in ("current_btc_price_usd", "expected_winter_btc_price_usd", "horizon_years"):
            self.assertEqual(_claim(flywheel_economics, economics(**{field: 0}), as_of=NOW,
                                    cycle_id="synthetic-cycle")["state"], "BLOCKED")

    def test_operating_capacity_is_dynamic_not_permanent_dollars(self):
        row = anchor()
        self.assertAlmostEqual(operating_fund(row, as_of=NOW, cycle_id="synthetic-cycle")["operating_fund_anchor_usd"], 36326.25)
        row["price_per_share_usd"] = 100
        self.assertEqual(operating_fund(row, as_of=NOW, cycle_id="synthetic-cycle")["operating_fund_anchor_usd"], 37500)
        for field, value in (("lookback_months", 8), ("approval_ref", None), ("cycle_id", "old"),
                             ("coverage_state", "PARTIAL"), ("price_per_share_usd", None)):
            changed = {**row, field: value}
            self.assertEqual(_claim(operating_fund, changed, as_of=NOW, cycle_id="synthetic-cycle")["state"], "BLOCKED")

    def test_full_cycle_kpis_and_missing_claims_are_separate(self):
        out = full_cycle_review(review(), as_of=NOW, cycle_id="synthetic-cycle")
        self.assertEqual(out["claims"]["btc_core"]["btc_core_accretion"], .5)
        self.assertTrue(out["claims"]["operating_capacity"]["operating_capacity_preserved"])
        self.assertFalse(out["claims"]["permanent_loss"]["permanent_capital_loss"])
        self.assertAlmostEqual(out["claims"]["realized_cagr_comparison"]["difference"], .04)
        out = full_cycle_review(review(btc_core_start=None, permanent_capital_loss=None), as_of=NOW, cycle_id="synthetic-cycle")
        self.assertEqual(out["claims"]["btc_core"]["state"], "BLOCKED")
        self.assertEqual(out["claims"]["permanent_loss"]["state"], "BLOCKED")
        self.assertEqual(out["claims"]["operating_capacity"]["state"], "READY_FOR_ANALYST")

    def test_gold_lineage_and_hash_mismatch_fail_closed_locally(self):
        for field, value in (("parent_evidence_pack_hash", "wrong"), ("as_of_ms", NOW+1), ("storage", "REMOTE")):
            data, pack, gold = fixture()
            gold[field] = value
            gold["context_hash"] = _hash({k: v for k, v in gold.items() if k != "context_hash"})
            out = build_capital_posture_context(data, pack, gold)
            self.assertIn("GOLD_CONTEXT", out["blockers"])
            self.assertEqual(out["flywheel_economics"]["state"], "READY_FOR_ANALYST")

    def test_existing_assumption_watch_can_veto_linked_math(self):
        data, pack, _ = fixture()
        assumption = {"assumption_id": "synthetic-flywheel", "assumption": "synthetic forward scenario",
            "source": "synthetic:test", "as_of": NOW, "invalidation": "analyst review",
            "observed_reality": record("BTC_PRICE_USD", NOW, 100000, "BTC"),
            "analyst_assessment": record("ASSUMPTION_ASSESSMENT", NOW, entity="BTC",
                assumption_id="synthetic-flywheel", status="INVALIDATED", reason="synthetic:changed reality")}
        gold = build_gold_research_context({"as_of_ms": NOW, "assumptions": [assumption]}, pack)
        out = build_capital_posture_context(data, pack, gold)
        self.assertTrue(out["maintenance"]["recalculation_required"])
        self.assertEqual(out["flywheel_economics"]["state"], "BLOCKED")
        self.assertIsNone(out["flywheel_economics"]["flywheel_margin"])
        self.assertEqual(out["operating_fund"]["state"], "READY_FOR_ANALYST")
        data["flywheel_scenario"]["assumption_ids"] = ["unrelated"]
        self.assertEqual(build_capital_posture_context(data, pack, gold)["flywheel_economics"]["state"], "READY_FOR_ANALYST")

    def test_all_missing_is_blocked_without_invented_metrics(self):
        _, pack, _ = fixture()
        out = build_capital_posture_context({"as_of_ms": NOW, "cycle_id": "synthetic-cycle"}, pack)
        self.assertEqual(out["state"], "BLOCKED")
        self.assertEqual(out["current_rail_step"], "BLOCKED")
        self.assertEqual(out["flywheel_economics"]["state"], "BLOCKED")
        self.assertIsNone(out["maintenance"]["recalculation_required"])

    def test_tampered_parent_and_future_parent_are_rejected(self):
        data, pack, gold = fixture()
        pack["generated_at_ms"] += 1
        with self.assertRaises(ValueError):
            build_capital_posture_context(data, pack, gold)
        pack["evidence_pack_hash"] = _hash({k: v for k, v in pack.items() if k != "evidence_pack_hash"})
        with self.assertRaises(ValueError):
            build_capital_posture_context(data, pack, gold)

    def test_legacy_static_target_not_silently_used_as_current_rail(self):
        out = build_capital_posture_context(*fixture(rail="AUTUMN_PRESERVATION"))
        self.assertEqual(out["current_rail_step"]["fixed_growth_pct"], [80, 20])
        self.assertIn("UPSTREAM_SEASON_ANCHOR_DOCTRINE_MISMATCH",
                      [r["reason"] for r in out["contradictions"]])

    def test_cli_produces_separate_local_file_and_preserves_inputs(self):
        data, pack, gold = fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in (("input", data), ("pack", pack), ("gold", gold)):
                (root/(name+".json")).write_text(json.dumps(value), encoding="utf-8")
            args = ["--input", str(root/"input.json"), "--evidence-pack", str(root/"pack.json"),
                    "--gold-context", str(root/"gold.json"), "--output", str(root/"out.json")]
            self.assertEqual(main(args), 0)
            self.assertEqual(json.loads((root/"out.json").read_text())["storage"], "LOCAL_ONLY")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args[:-1]+[str(root/"pack.json")])
            self.assertEqual(json.loads((root/"pack.json").read_text()), pack)

    def test_full_existing_bridge_budget_unchanged(self):
        fixture = health_fixtures.CompanyHealthTests("test_full_portfolio_and_long_valuation_history_fit_bridge")
        fixture.test_full_portfolio_and_long_valuation_history_fit_bridge()
        self.assertLessEqual(fixture.bridge_payload_bytes, 15 * 1024)

    def test_core_does_not_expand_winter_tactical_split(self):
        data, pack, gold = fixture(rail="WINTER_SPLIT")
        original = build_capital_posture_context(data, pack, gold)["winter_capital_split"]
        pack["portfolio_allocation_context"]["current_allocation"]["strategic_btc_quantity"] = 1000
        pack["evidence_pack_hash"] = _hash({k: v for k, v in pack.items() if k != "evidence_pack_hash"})
        changed = build_capital_posture_context(data, pack)["winter_capital_split"]
        self.assertEqual(original["research_residual_for_btc_accumulation_usd"], changed["research_residual_for_btc_accumulation_usd"])
        self.assertEqual(changed["existing_btc_core_quantity"], 1000)
        self.assertGreater(changed["anchor_shortfall_usd"], 0)
        self.assertEqual(changed["research_residual_for_btc_accumulation_usd"], 0)

    def test_full_cycle_requires_complete_aligned_period(self):
        for field, value in (("completed_cycle", False), ("cycle_end_ms", NOW+1), ("cycle_start_ms", None)):
            self.assertEqual(_claim(full_cycle_review, review(**{field: value}), as_of=NOW,
                                    cycle_id="synthetic-cycle")["state"], "BLOCKED")

    def test_health_mixed_stays_separate_from_valuation(self):
        data, pack, _ = fixture()
        pack["common_equity_health"]["assets"]["MSTR"]["company_health"] = {
            "dimensions": {"per_share_asset_engine": {"direction": "BLOCKED", "interpretation_state": "MIXED",
                                                       "analyst_judgment_required": True}}}
        pack["evidence_pack_hash"] = _hash({k: v for k, v in pack.items() if k != "evidence_pack_hash"})
        out = build_capital_posture_context(data, pack)
        self.assertIn("HEALTH_REQUIRES_ANALYST", [r["reason"] for r in out["contradictions"]])
        self.assertEqual(out["valuation_realization_evidence"]["MSTR"]["state"], "READY_FOR_ANALYST")

    def test_transition_proximity_reuses_momentum_without_inventing_distance(self):
        data, pack, _ = fixture()
        for momentum in ("RISING", "FALLING", "MIXED", "BASELINE_PENDING"):
            pack["season_transition_warning_overlay"] = {"evidence_momentum": momentum}
            pack["evidence_pack_hash"] = _hash({k: v for k, v in pack.items() if k != "evidence_pack_hash"})
            out = build_capital_posture_context(data, pack)["transition_proximity"]
            self.assertEqual(out["upstream_evidence_momentum"], momentum)
            self.assertEqual(out["state"], "BLOCKED" if momentum == "BASELINE_PENDING" else "READY_FOR_ANALYST")


if __name__ == "__main__":
    unittest.main()
