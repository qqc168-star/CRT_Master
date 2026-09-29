from copy import deepcopy
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from crt_radar.gold_research_context import (
    DAY, HORIZONS_WEEKS, _hash, _attempt, btc_gold_valuation, liquidity_components,
    liquidity_transmission_replay, institutional_absorption, etf_stickiness_episode,
    pmi_cycle_maturity, historical_gross_multiple_distribution, next_cycle_valuation,
    model_dependency_map, build_gold_research_context, main,
)
from crt_radar.btc_transition_replay_evidence import build_forward_200wma_context
from crt_radar.mstr_asst_full_day_market_intake import build_btc_convexity_research
from crt_radar.assumption_boundary_watch import evaluate_external_research_assumptions
from crt_radar.treasury_company_ct import ISSUERS, build_treasury_valuation_context
from test_treasury_valuation_context import inputs as treasury_inputs, NOW
from test_mstr_asst_full_day_market_intake import bars, btc_marks, sessions, close_ms
import test_company_health as health_fixtures


T = NOW-400*DAY


def record(metric, at, value=100, entity="US", **changes):
    unit = "BTC" if metric in ("BTC_ETF_BALANCE_BTC", "PUBLIC_COMPANY_BTC_HOLDINGS",
                               "SOVEREIGN_OFFICIAL_BTC_HOLDINGS", "BTC_CIRCULATING_SUPPLY") else "USD"
    out = {"issuer_id": entity, "metric_id": metric, "effective_time": at, "disclosure_time": at,
        "first_seen_time": at, "retrieval_time": at, "source_ref": f"synthetic:{metric}:{at}",
        "verification_state": "VALIDATED", "source_class": "OFFICIAL", "coverage_state": "COMPLETE",
        "scope_ref": metric+":synthetic-scope", "basis_ref": metric+":basis-v1", "value": value,
        "source_semantic": {"identity": metric, "version": "1", "effective_from": 1, "effective_to": None},
        "limitation": "SYNTHETIC_TEST_NOT_REAL_WORLD_DATA", "invalidation": "SOURCE_REVISION", "unit": unit}
    out.update(changes)
    return out


def scenario(**changes):
    result = {"scenario_id": "synthetic-path", "scenario_only": True, "frozen_at": NOW,
              "source_ref": "synthetic:scenario", "limitation": "NOT_A_FORECAST", "invalidation": "CHANGED_INPUTS"}
    result.update(changes)
    return result


def forward_inputs():
    start = datetime(2022, 1, 2, tzinfo=timezone.utc)
    history = [{"week_closed_at": (start+timedelta(weeks=i)).isoformat(),
                "available_at": (start+timedelta(weeks=i)).isoformat(), "is_complete": True, "close": 100+i}
               for i in range(200)]
    cutoff = start+timedelta(weeks=199)
    path = {"scenario_id": "synthetic", "source_ref": "synthetic:future", "frozen_at": cutoff.isoformat(),
            "weekly_path": [{"week_closed_at": (cutoff+timedelta(weeks=i)).isoformat(), "close": 300}
                            for i in range(1, 4)]}
    return history, cutoff.isoformat(), path


def macro_inputs():
    monday = datetime(2026, 3, 2, tzinfo=timezone.utc)
    ms = int(monday.timestamp()*1000)
    return {"M2": [record("M2", T, 1000, period="2025-01"), record("M2", T+30*DAY, 1100, period="2025-02")],
            "TGA": [record("TGA", T, 300), record("TGA", T+7*DAY, 250)],
            "RRP": [record("RRP", ms+i*DAY, 10+i) for i in range(5)],
            "RRP_calendar": {"state": "VALIDATED", "source_ref": "synthetic:calendar",
                             "expected_dates": [(monday+timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]}}


def demand_records():
    result = []
    for metric, holder in (("BTC_ETF_BALANCE_BTC", "ETF:one"), ("PUBLIC_COMPANY_BTC_HOLDINGS", "CORP:one"),
                           ("SOVEREIGN_OFFICIAL_BTC_HOLDINGS", "GOV:one")):
        result += [record(metric, at, value, "BTC", holding_scope_ids=[holder])
                   for at, value in ((T, 100), (T+23*DAY, 110), (T+30*DAY, 120))]
    result += [record("BTC_ETF_NET_FLOW_USD", T+23*DAY, -50, "BTC"),
               record("BTC_ETF_NET_FLOW_USD", T+30*DAY, 20, "BTC")]
    result += [record("BTC_ETF_FLOW_BREADTH", T+23*DAY, entity="BTC", positive_fund_count=2, negative_fund_count=4)]
    return result


def episode():
    return {"episode_id": "synthetic-drawdown", "boundary_source_ref": "synthetic:predeclared-episode",
            "start_time": T, "trough_time": T+23*DAY, "end_time": T+30*DAY,
            "market_window_lock_state": "APPROVED", "market_window_lock_ref": "synthetic:approved-window",
            "flow_observation_times": [T+23*DAY, T+30*DAY],
            "flow_calendar_state": "VALIDATED", "flow_calendar_ref": "synthetic:episode-calendar",
            "btc_prices": [record("BTC_PRICE_USD", at, value, "BTC")
                           for at, value in ((T, 100), (T+23*DAY, 60), (T+30*DAY, 90))]}


def history(asset="MSTR"):
    entity = ISSUERS[asset]
    times = [T+i*DAY for i in range(4)]
    rows = [record("HISTORICAL_GROSS_BTC_ASSET_MULTIPLE", at, entity=entity,
                   equity_price_usd=100*(i+1), btc_price_usd=100, btc_per_diluted_share=1,
                   market_alignment_state="EXACT_CLOSE", market_window_lock_ref="synthetic:approved",
                   share_basis_ref="synthetic:split-adjusted") for i, at in enumerate(times)]
    definition = record("GROSS_MULTIPLE_SAMPLE", times[-1], entity=entity,
        sample_scope="ALL_AVAILABLE_HISTORY" if asset == "MSTR" else "POST_STRATEGY_POST_MERGER",
        sample_start=times[0], sample_end=times[-1], expected_observation_times=times)
    binding = record("BULL_WINDOW_RESEARCH_BINDING", times[0], entity=entity,
                     window_start=times[0], window_end=times[1], classification_basis_ref="synthetic:predeclared")
    return {"observations": rows, "sample_definition": definition, "bull_window_binding": binding}


def convexity_inputs():
    dates = sessions(62)
    equity = {a: bars(a, 62) for a in ISSUERS}
    marks = btc_marks(62)
    btc, stock = 100, 100
    returns = [.02, -.01, .03, -.015]
    for i in range(62):
        if i:
            r = returns[(i-1)%4]
            btc *= 1+r
            stock *= 1+2*r
        marks[i]["price_usd"] = btc
        for a in equity:
            equity[a][i]["close"] = stock
    now = close_ms(dates[-1])+1
    contract = {"state": "VALIDATED", "source_ref": "synthetic:approved-calendar-source",
                "share_adjustment_basis": "synthetic:split-adjusted", "available_at_ms": now,
                "expected_session_close_ms": [close_ms(d) for d in dates]}
    return {"equity_bars": equity, "btc_close_marks": marks, "generated_at_ms": now,
            "source_window_contract": contract}


class GoldResearchTests(unittest.TestCase):
    def test_forward_reuses_completed_week_rolling_mean(self):
        rows, at, path = forward_inputs()
        result = build_forward_200wma_context(rows, as_of=at, provenance="synthetic:history", scenario=path)
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertEqual(result["baseline_200wma"], 199.5)
        self.assertEqual(result["path"][0]["scenario_200wma"], 200.5)
        self.assertEqual(result["legacy_research_scenarios_usd"], [120000, 135000, 150000])
        self.assertEqual(result["formal_price_target_authority"], "NONE")

    def test_forward_ignores_later_actual_and_incomplete_bars(self):
        rows, at, path = forward_inputs()
        expected = build_forward_200wma_context(rows, as_of=at, provenance="test", scenario=path)
        rows += [{"week_closed_at": path["weekly_path"][0]["week_closed_at"],
                  "available_at": path["weekly_path"][0]["week_closed_at"], "is_complete": True, "close": 999999}]
        self.assertEqual(expected, build_forward_200wma_context(rows, as_of=at, provenance="test", scenario=path))
        rows[-1].update(available_at=at, is_complete=False)
        self.assertEqual(expected, build_forward_200wma_context(rows, as_of=at, provenance="test", scenario=path))

    def test_forward_rejects_gaps_late_scenario_and_short_history(self):
        for mode in ("gap", "late", "short", "duplicate"):
            rows, at, path = forward_inputs()
            if mode == "gap":
                path["weekly_path"].pop(0)
            elif mode == "late":
                path["frozen_at"] = path["weekly_path"][0]["week_closed_at"]
            elif mode == "short":
                rows.pop()
            else:
                rows[-1] = deepcopy(rows[-2])
            self.assertEqual(build_forward_200wma_context(rows, as_of=at, provenance="test", scenario=path)["state"], "BLOCKED")

    def test_btc_gold_supply_is_explicit_and_scenario_only(self):
        raw = scenario(gold_market_cap_usd=1000, btc_gold_ratio=.1, btc_supply_quantity=10, btc_supply_basis="synthetic:circulating")
        result = btc_gold_valuation(raw, as_of=NOW)
        self.assertEqual(result["scenario_btc_price_usd"], 10)
        self.assertEqual(result["research_state"], "RESEARCH_ONLY")
        for key in ("btc_supply_basis", "btc_supply_quantity", "scenario_only"):
            bad = deepcopy(raw)
            bad.pop(key)
            self.assertEqual(_attempt(btc_gold_valuation, bad, as_of=NOW)["state"], "BLOCKED")

    def test_macro_native_cadence_and_rrp_average_not_sum(self):
        out = liquidity_components(macro_inputs(), as_of=NOW)
        self.assertEqual(out["M2"]["delta"], 100)
        self.assertEqual(out["TGA"]["delta"], -50)
        self.assertEqual(out["RRP"]["weekly"][0]["mean_daily_rrp_usd"], 12)
        self.assertEqual(out["M2"]["cadence"]["collection"], "MONTHLY")
        self.assertEqual(out["RRP"]["cadence"]["surface"], "WEEKLY")

    def test_macro_unknown_missing_days_revisions_and_month_gaps(self):
        raw = macro_inputs()
        raw["M2"][-1]["period"] = "2025-04"
        raw["TGA"][-1]["value"] = None
        raw["RRP"].pop()
        out = liquidity_components(raw, as_of=NOW)
        self.assertIsNone(out["M2"]["delta"])
        self.assertEqual(out["TGA"]["state"], "BLOCKED")
        self.assertIsNone(out["RRP"]["weekly"][0]["mean_daily_rrp_usd"])
        raw = macro_inputs()
        raw["M2"][-1]["retrieval_time"] = NOW+1
        self.assertEqual(liquidity_components(raw, as_of=NOW)["M2"]["state"], "BLOCKED")

    def test_liquidity_replay_fixed_grid_and_future_returns(self):
        liquidity = [record("M2", T+i*28*DAY, value) for i, value in enumerate((100, 110, 140, 150, 200))]
        times = sorted({r["retrieval_time"]+h*7*DAY for r in liquidity for h in (0, *HORIZONS_WEEKS)})
        prices = [record("BTC_PRICE_USD", t, 100+(t-T)/DAY, "BTC") for t in times]
        out = liquidity_transmission_replay({"metric_id": "M2", "liquidity": liquidity, "btc_prices": prices}, as_of=NOW)
        self.assertEqual(out["horizons_weeks"], [4, 8, 12, 26])
        self.assertEqual(set(out["results"]), {"4", "8", "12", "26"})
        pair = out["results"]["4"]["pairs"][0]
        self.assertAlmostEqual(pair["delta_log_liquidity"], __import__("math").log(1.1))
        self.assertAlmostEqual(pair["future_btc_return"], 156/128-1)
        self.assertEqual(out["results"]["4"]["cohorts"]["2013"]["state"], "BLOCKED")
        self.assertEqual(out["promotion_state"], "NOT_ELIGIBLE_FOR_FORMAL_THRESHOLD")

    def test_replay_uses_publication_origin_not_economic_period(self):
        rows = [record("M2", T+i*28*DAY, 100+i*10, disclosure_time=T+i*28*DAY+DAY,
                       first_seen_time=T+i*28*DAY+DAY, retrieval_time=T+i*28*DAY+DAY) for i in range(4)]
        # Only period-end prices supplied: no inference or nearest-date fill.
        prices = [record("BTC_PRICE_USD", T+i*28*DAY, 100+i, "BTC") for i in range(8)]
        out = liquidity_transmission_replay({"metric_id": "M2", "liquidity": rows, "btc_prices": prices}, as_of=NOW)
        self.assertEqual(out["results"]["4"]["pairs"], [])
        self.assertTrue(out["results"]["4"]["omitted"])

    def test_institutional_tracked_total_and_supply_share(self):
        supply = record("BTC_CIRCULATING_SUPPLY", T+30*DAY, 1000, "BTC")
        out = institutional_absorption(demand_records(), as_of=NOW, supply=supply)
        self.assertEqual(out["tracked_total"]["tracked_btc_holdings"], 360)
        self.assertEqual(out["share_of_circulating_supply"]["fraction"], .36)
        etf = out["components"]["BTC_ETF_BALANCE_BTC"]
        self.assertEqual(etf["changes"]["7D"]["change_btc"], 10)
        self.assertEqual(etf["changes"]["30D"]["change_btc"], 20)

    def test_overlapping_universe_blocks_total_not_individual_holdings(self):
        rows = demand_records()
        for r in rows:
            if r["metric_id"] == "PUBLIC_COMPANY_BTC_HOLDINGS":
                r["holding_scope_ids"] = ["ETF:one"]
        out = institutional_absorption(rows, as_of=NOW)
        self.assertEqual(out["tracked_total"]["state"], "BLOCKED")
        self.assertEqual(out["components"]["BTC_ETF_BALANCE_BTC"]["state"], "AVAILABLE")
        self.assertEqual(out["share_of_circulating_supply"]["state"], "BLOCKED")

    def test_episode_preserves_inventory_flow_breadth_and_recovery(self):
        out = etf_stickiness_episode(episode(), demand_records(), as_of=NOW)
        self.assertEqual(out["price"]["btc_drawdown_fraction"], -.4)
        self.assertAlmostEqual(out["inventory"]["episode_inventory_change_fraction"], .2)
        self.assertEqual(out["flow"]["net_flow_usd"], -30)
        self.assertEqual(out["breadth"]["observations"][0]["negative_fund_count"], 4)
        self.assertEqual(out["price"]["recovery_return_fraction"], .5)

    def test_episode_market_lock_and_missing_flow_fail_claim_scoped(self):
        ep = episode()
        ep.pop("market_window_lock_ref")
        rows = [r for r in demand_records() if r["metric_id"] != "BTC_ETF_NET_FLOW_USD"]
        out = etf_stickiness_episode(ep, rows, as_of=NOW)
        self.assertEqual(out["price"]["state"], "BLOCKED")
        self.assertEqual(out["flow"]["state"], "BLOCKED")
        self.assertEqual(out["inventory"]["state"], "AVAILABLE")

    def test_pmi_monthly_maturity_not_trigger(self):
        raw = {metric: [record(metric, T+i*31*DAY, v, period=f"2025-{i+1:02d}")
                        for i, v in enumerate((48, 50, 53, 51))] for metric in ("PMI", "PMI_NEW_ORDERS")}
        out = pmi_cycle_maturity(raw, as_of=NOW)
        self.assertEqual(out["metrics"]["PMI"]["change_1m"], -2)
        self.assertEqual(out["metrics"]["PMI"]["slope_3m_index_points_per_month"], 1)
        self.assertEqual(out["metrics"]["PMI"]["rollover_observation"], "FALLING")
        self.assertEqual(out["action_output"], "NONE")
        raw["PMI_NEW_ORDERS"][-1]["source_class"] = "VERIFIED_PROCESSED"
        raw["PMI"][-1]["period"] = "2025-06"
        out = pmi_cycle_maturity(raw, as_of=NOW)
        self.assertEqual(out["metrics"]["PMI_NEW_ORDERS"]["state"], "BLOCKED")
        self.assertIsNone(out["metrics"]["PMI"]["slope_3m_index_points_per_month"])

    def test_convexity_calculates_beta_from_exact_close_returns(self):
        out = build_btc_convexity_research(**convexity_inputs())
        for asset in ISSUERS:
            data = out["assets"][asset]
            self.assertEqual(data["state"], "AVAILABLE")
            self.assertAlmostEqual(data["full_sample"]["rolling_btc_beta"], 2)
            self.assertEqual(len(data["rolling"]["60"]), 2)
            self.assertGreater(data["full_sample"]["upside_capture"], 1)
            self.assertGreater(data["full_sample"]["downside_capture"], 1)

    def test_convexity_refuses_missing_or_duplicate_btc_close_and_unapproved_scope(self):
        for mode in ("missing", "duplicate", "scope"):
            raw = convexity_inputs()
            if mode == "missing":
                raw["btc_close_marks"].pop(10)
            elif mode == "duplicate":
                raw["btc_close_marks"].append(deepcopy(raw["btc_close_marks"][0]))
            else:
                raw["source_window_contract"]["state"] = "CANDIDATE"
            self.assertEqual(build_btc_convexity_research(**raw)["state"], "BLOCKED")

    def test_convexity_does_not_hardcode_beta_or_zero_fill_no_downside(self):
        raw = convexity_inputs()
        for i, mark in enumerate(raw["btc_close_marks"]):
            mark["price_usd"] = 100+i+i*i
            for a in ISSUERS:
                raw["equity_bars"][a][i]["close"] = 100+i+i*i
        out = build_btc_convexity_research(**raw)["assets"]["MSTR"]["full_sample"]
        self.assertAlmostEqual(out["rolling_btc_beta"], 1)
        self.assertIsNone(out["downside_capture"])

    def test_actual_gross_multiple_quantiles_and_separate_assets(self):
        for asset in ISSUERS:
            out = historical_gross_multiple_distribution(history(asset), asset=asset, as_of=NOW)
            self.assertEqual(out["distribution"]["median"], 2.5)
            self.assertEqual(out["distribution"]["P75"], 3.25)
            self.assertEqual(out["distribution"]["P90"], 3.7)
            self.assertEqual(out["bull_window"]["median"], 1.5)
            self.assertEqual(out["valuation_lane"], "HISTORICAL_GROSS_BTC_ASSET_MULTIPLE")
            if asset == "ASST":
                self.assertIn("LOWER_CONFIDENCE", out["confidence"])

    def test_distribution_blocks_wrong_issuer_incomplete_scope_and_retrospective_bull_window(self):
        raw = history()
        raw["observations"].pop()
        self.assertEqual(_attempt(historical_gross_multiple_distribution, raw, asset="MSTR", as_of=NOW)["state"], "BLOCKED")
        self.assertEqual(_attempt(historical_gross_multiple_distribution, history(), asset="ASST", as_of=NOW)["state"], "BLOCKED")
        raw = history()
        raw["bull_window_binding"]["retrieval_time"] = NOW
        out = historical_gross_multiple_distribution(raw, asset="MSTR", as_of=NOW)
        self.assertEqual(out["distribution"]["state"], "AVAILABLE")
        self.assertEqual(out["bull_window"]["state"], "BLOCKED")

    def test_next_cycle_reuses_treasury_bps_and_keeps_mnav_separate(self):
        for asset in ISSUERS:
            ct = build_treasury_valuation_context(asset_id=asset, as_of_ms=NOW, **treasury_inputs(asset))
            raw = {"history": history(asset), "scenarios": [scenario(future_btc_price_usd=200000,
                   btc_per_share_factor=1.5, multiple_kind="HISTORICAL_DISTRIBUTION", quantile="median")]}
            out = next_cycle_valuation(raw, asset=asset, treasury_context=ct, as_of=NOW)
            self.assertEqual(out["state"], "AVAILABLE")
            self.assertAlmostEqual(out["scenarios"][0]["scenario_equity_price_usd"], 200000*(120/110)*1.5*2.5)
            self.assertEqual(out["formal_diluted_equity_mnav_lane"]["value"], ct["diluted_mnav"])
            self.assertEqual(out["scenarios"][0]["sample_period"], [T, T+3*DAY])

    def test_manual_multiple_is_candidate_never_median_and_missing_history_stays_blocked(self):
        ct = build_treasury_valuation_context(asset_id="MSTR", as_of_ms=NOW, **treasury_inputs())
        raw = {"scenarios": [scenario(future_btc_price_usd=200000, btc_per_share_factor=1,
                    multiple_kind="RESEARCH_SCENARIO_CANDIDATE", gross_btc_asset_multiple=2),
                scenario(future_btc_price_usd=200000, btc_per_share_factor=1,
                    multiple_kind="HISTORICAL_DISTRIBUTION", quantile="median")]}
        out = next_cycle_valuation(raw, asset="MSTR", treasury_context=ct, as_of=NOW)
        self.assertEqual(out["scenarios"][0]["state"], "AVAILABLE")
        self.assertIsNone(out["scenarios"][0]["sample_period"])
        self.assertEqual(out["scenarios"][1]["state"], "BLOCKED")
        self.assertEqual(out["historical_gross_multiple"]["state"], "BLOCKED")
        ct["current_btc_per_diluted_share"] = 100
        self.assertEqual(_attempt(next_cycle_valuation, raw, asset="MSTR", treasury_context=ct, as_of=NOW)["state"], "BLOCKED")

    def test_external_assumption_drift_is_not_calendar_invalidation(self):
        raw = {"assumption_id": "HODL", "assumption": "340K +/-15% hypothesis", "source": "synthetic:attributed-interview",
               "as_of": T, "research_window": "2026Q4-2027Q2", "invalidation": "Analyst checks liquidity/PMI peak without BTC response",
               "reference_value": 340000, "observed_reality": record("BTC_PRICE_USD", NOW, 100000, "BTC")}
        out = evaluate_external_research_assumptions([raw], as_of_ms=NOW+1000*DAY)
        self.assertEqual(out["assumptions"][0]["status"], "WATCHING")
        self.assertAlmostEqual(out["assumptions"][0]["deviation"], 100000/340000-1)
        raw["analyst_assessment"] = record("ASSUMPTION_ASSESSMENT", NOW, entity="BTC",
            assumption_id="HODL", status="INVALIDATED", reason="synthetic:conditions-failed")
        self.assertEqual(evaluate_external_research_assumptions([raw], as_of_ms=NOW)["assumptions"][0]["status"], "INVALIDATED")
        raw.pop("as_of")
        self.assertEqual(evaluate_external_research_assumptions([raw], as_of_ms=NOW)["assumptions"][0]["status"], "BLOCKED")

    def test_model_dependencies_are_not_independent_votes(self):
        dependencies = model_dependency_map()["dependencies"]
        self.assertIn("HISTORICAL_BTC_PRICE", dependencies["forward_200wma"])
        self.assertIn("HISTORICAL_BTC_PRICE", dependencies["next_cycle_valuation"])
        self.assertIn("ETF_INVENTORY", dependencies["etf_stickiness"])

    def test_local_sidecar_does_not_mutate_pack_and_binds_hash(self):
        parent = {"generated_at_ms": NOW, "asset_facts": {"items": demand_records()}, "common_equity_health": {"state": "PARTIAL"}}
        parent["evidence_pack_hash"] = _hash(parent)
        original = deepcopy(parent)
        out = build_gold_research_context({"as_of_ms": NOW}, parent)
        self.assertEqual(parent, original)
        self.assertEqual(out["storage"], "LOCAL_ONLY")
        self.assertEqual(out["bridge_policy"], "LOCAL_ONLY_NO_BRIDGE_BYTES_ADDED")
        self.assertEqual(out["context_hash"], _hash({k: v for k, v in out.items() if k != "context_hash"}))
        self.assertEqual(out["next_cycle_valuation"]["ASST"]["state"], "BLOCKED")
        with self.assertRaises(ValueError):
            build_gold_research_context({"as_of_ms": NOW-1}, parent)
        parent["generated_at_ms"] += 1
        with self.assertRaises(ValueError):
            build_gold_research_context({"as_of_ms": NOW}, parent)

    def test_cli_writes_local_context_and_cannot_overwrite_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parent = {"generated_at_ms": NOW, "asset_facts": {"items": []}}
            parent["evidence_pack_hash"] = _hash(parent)
            (root/"pack.json").write_text(json.dumps(parent), encoding="utf-8")
            (root/"input.json").write_text(json.dumps({"as_of_ms": NOW}), encoding="utf-8")
            args = ["--input", str(root/"input.json"), "--evidence-pack", str(root/"pack.json"), "--output", str(root/"gold.json")]
            self.assertEqual(main(args), 0)
            self.assertEqual(json.loads((root/"gold.json").read_text())["storage"], "LOCAL_ONLY")
            self.assertEqual(json.loads((root/"pack.json").read_text()), parent)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args[:-1]+[str(root/"pack.json")])
            self.assertEqual(json.loads((root/"pack.json").read_text()), parent)

    def test_populated_sidecar_composes_existing_treasury_and_demand_facts(self):
        facts = demand_records()
        next_cycle = {}
        for asset in ISSUERS:
            context = build_treasury_valuation_context(asset_id=asset, as_of_ms=NOW, **treasury_inputs(asset))
            facts.append({"fact_type": "TREASURY_VALUATION_CONTEXT", "asset_id": asset, "evidence": context})
            next_cycle[asset] = {"history": history(asset), "scenarios": [scenario(
                future_btc_price_usd=200000, btc_per_share_factor=1,
                multiple_kind="HISTORICAL_DISTRIBUTION", quantile="P75")]}
        parent = {"generated_at_ms": NOW, "asset_facts": {"items": facts}}
        parent["evidence_pack_hash"] = _hash(parent)
        original = deepcopy(parent)
        inputs = {"as_of_ms": NOW, "liquidity": macro_inputs(), "etf_episodes": [episode()],
                  "next_cycle": next_cycle, "btc_gold": scenario(btc_supply_basis="EXPLICIT_TEST_SUPPLY",
                    btc_supply_quantity=20000000, gold_market_cap_usd=10000000000000, btc_gold_ratio=.2)}
        output = build_gold_research_context(inputs, parent)
        self.assertEqual(output, build_gold_research_context(inputs, parent))
        self.assertEqual(parent, original)
        self.assertEqual(output["btc_gold"]["state"], "AVAILABLE")
        self.assertEqual(output["liquidity_components"]["M2"]["delta"], 100)
        self.assertEqual(output["institutional_absorption"]["tracked_total"]["tracked_btc_holdings"], 360)
        self.assertAlmostEqual(output["etf_stickiness"][0]["price"]["btc_drawdown_fraction"], -.4)
        for asset in ISSUERS:
            self.assertEqual(output["next_cycle_valuation"][asset]["scenarios"][0]["gross_btc_asset_multiple"], 3.25)
        self.assertEqual(output["production"], "NOT_APPROVED")

    def test_existing_full_bridge_still_fits_without_gold_payload(self):
        fixture = health_fixtures.CompanyHealthTests("test_full_portfolio_and_long_valuation_history_fit_bridge")
        fixture.test_full_portfolio_and_long_valuation_history_fit_bridge()
        self.assertEqual(fixture.bridge_payload_bytes, 16155)

    def test_invalid_values_and_unverified_source_fail_closed(self):
        for value in (None, True, float("nan"), float("inf"), -1):
            raw = macro_inputs()
            raw["M2"][-1]["value"] = value
            self.assertEqual(liquidity_components(raw, as_of=NOW)["M2"]["state"], "BLOCKED")
        raw = macro_inputs()
        raw["M2"][-1]["verification_state"] = "SOURCE_CLAIM"
        self.assertEqual(liquidity_components(raw, as_of=NOW)["M2"]["state"], "BLOCKED")

    def test_holdings_do_not_treat_usd_value_as_btc_quantity(self):
        records = demand_records()
        records[0]["unit"] = "USD"
        output = institutional_absorption(records, as_of=NOW)
        self.assertEqual(output["components"]["BTC_ETF_BALANCE_BTC"]["state"], "BLOCKED")
        self.assertEqual(output["tracked_total"]["state"], "BLOCKED")
        self.assertEqual(output["components"]["PUBLIC_COMPANY_BTC_HOLDINGS"]["state"], "AVAILABLE")
