
from __future__ import annotations

import unittest

from crt_radar.portfolio_allocation_context import (
    build_common_equity_health,
    build_portfolio_allocation_context,
    compact_portfolio_allocation_context_for_bridge,
)

ISSUER = {"MSTR": "CIK-0001050446", "ASST": "CIK-0001920406"}
PREVIOUS_TIME = 1_700_000_000_000
CURRENT_TIME = PREVIOUS_TIME + 86_400_000
REPLAY_TIME = CURRENT_TIME + 1_000


def pack_for(
    *,
    mstr_btc=(100.0, 120.0),
    mstr_shares=(100.0, 110.0),
    mstr_claims=(1_000.0, 1_000.0),
    mstr_carry=(100.0, 100.0),
    mstr_liquidity=(450.0, 500.0),
    asst_btc=(100.0, 110.0),
    asst_shares=(100.0, 110.0),
    asst_claims=(1_000.0, 1_000.0),
    asst_carry=(100.0, 100.0),
    asst_liquidity=(450.0, 500.0),
):
    rows = []
    config = {
        "MSTR": (mstr_btc, mstr_shares, mstr_claims, mstr_carry, mstr_liquidity),
        "ASST": (asst_btc, asst_shares, asst_claims, asst_carry, asst_liquidity),
    }
    for asset, (btc, shares, claims, carry, liquidity) in config.items():
        prev_bps = btc[0] / shares[0]
        cur_bps = btc[1] / shares[1]
        rows.extend([
            {
                "issuer_id": ISSUER[asset],
                "fact_type": "TREASURY_COMPANY_CT",
                "ct_section": "per_share_asset_engine",
                "evidence": {
                    "previous": {
                        "btc_holdings": btc[0],
                        "diluted_shares": shares[0],
                    },
                    "current": {
                        "btc_holdings": btc[1],
                        "diluted_shares": shares[1],
                    },
                },
            },
            {
                "issuer_id": ISSUER[asset],
                "fact_type": "TREASURY_COMPANY_CT",
                "ct_section": "capital_burden_resilience",
                "evidence": {
                    "previous": {
                        "senior_claims_usd": claims[0],
                        "annual_carry_usd": carry[0],
                        "usable_liquidity_usd": liquidity[0],
                        "coverage_basis": "USD_CASH_ONLY",
                        "carry_coverage_years": liquidity[0] / carry[0],
                    },
                    "current": {
                        "senior_claims_usd": claims[1],
                        "annual_carry_usd": carry[1],
                        "usable_liquidity_usd": liquidity[1],
                        "coverage_basis": "USD_CASH_ONLY",
                        "carry_coverage_years": liquidity[1] / carry[1],
                    },
                },
            },
            {
                "issuer_id": ISSUER[asset],
                "fact_type": "TREASURY_COMPANY_CT",
                "ct_section": "capital_conversion",
                "evidence": {"events": []},
            },
            {
                "asset_id": asset,
                "issuer_id": ISSUER[asset],
                "fact_type": "TREASURY_VALUATION_CONTEXT",
                "evidence": {
                    "current_btc_per_diluted_share": cur_bps,
                    "btc_per_diluted_share_change_pct": cur_bps / prev_bps - 1.0,
                    "diluted_mnav": 1.05 if asset == "MSTR" else 1.10,
                    "own_history_empirical_cdf_pct": {"value": 40.0},
                    "five_week_mnav_change_pct": {"value": -0.04},
                    "benchmark_empirical_cdf_pct": {"value": 50.0},
                    "formal_action_critical_state": "AVAILABLE",
                    "evidence_authority": "FORMAL_ACTION_CRITICAL",
                },
            },
        ])
    for fact in rows:
        if fact.get("fact_type") != "TREASURY_COMPANY_CT" or fact.get("ct_section") == "capital_conversion":
            continue
        section = fact["ct_section"]
        basis = "synthetic:share-dilution-v1" if section == "per_share_asset_engine" else "synthetic:senior-claims-scope-v1"
        for label, at in (("previous", PREVIOUS_TIME), ("current", CURRENT_TIME)):
            snapshot = fact["evidence"][label]
            snapshot.update(
                issuer_id=fact["issuer_id"], source_ref=f"synthetic:{fact['issuer_id']}:{section}:{label}",
                verification_state="VALIDATED", effective_time=at, disclosure_time=at + 10,
                first_seen_time=at + 20, retrieval_time=at + 30, basis_ref=basis,
                source_semantic={"identity": basis, "version": "V1", "effective_from": 1, "effective_to": None},
            )
            if section == "per_share_asset_engine":
                snapshot["btc_per_diluted_share"] = snapshot["btc_holdings"] / snapshot["diluted_shares"]
            else:
                snapshot["cash_usability_basis_ref"] = "synthetic:verified-unrestricted-cash-v1"
        if section == "per_share_asset_engine":
            fact["evidence"]["btc_per_diluted_share_change_pct"] = (
                fact["evidence"]["current"]["btc_per_diluted_share"]
                / fact["evidence"]["previous"]["btc_per_diluted_share"] - 1
            )
    return {"generated_at_ms": REPLAY_TIME, "asset_facts": {"items": rows}}


def residual_inputs(
    *,
    mstr_prices=(80_000.0, 83_000.0),
    asst_prices=(80_000.0, 83_000.0),
):
    def pair(prices):
        return {
            "previous": {
                "btc_price_usd": prices[0],
                "verified_other_liquid_assets_usd": 0.0,
                "other_senior_claims_usd": 0.0,
                "coverage_state": "COMPLETE",
                "capital_structure_coherence_state": "VALIDATED",
                "capital_structure_scenario_ref": "synthetic:coherent-capital-structure-v1",
            },
            "current": {
                "btc_price_usd": prices[1],
                "verified_other_liquid_assets_usd": 0.0,
                "other_senior_claims_usd": 0.0,
                "coverage_state": "COMPLETE",
                "capital_structure_coherence_state": "VALIDATED",
                "capital_structure_scenario_ref": "synthetic:coherent-capital-structure-v1",
            },
        }
    return {"MSTR": pair(mstr_prices), "ASST": pair(asst_prices)}


def season(
    destination="SPRING",
    *,
    posture="SPRING",
    phase="BRIDGEHEAD",
    cash_target_pct=None,
    spring_stage=None,
    severe_stress=False,
    extreme_summer=False,
):
    result = {
        "season_source": "LABELED_ANALYST_HYPOTHESIS",
        "analyst_hypothesis_evidence_state": "INDEPENDENTLY_EVIDENCED",
        "season_posture": posture,
        "allocation_destination": destination,
        "deployment_phase": phase,
        "severe_stress": severe_stress,
        "extreme_summer_research_candidate": extreme_summer,
    }
    if cash_target_pct is not None:
        result["cash_target_pct"] = cash_target_pct
    if spring_stage is not None:
        result["spring_stage"] = spring_stage
    return result


def private_context():
    return {
        "state": "AVAILABLE",
        "profile": {
            "capital_state_status": {"state": "AVAILABLE"},
            "holdings": [
                {"asset": "MSTR", "quantity": 40.0},
                {"asset": "ASST", "quantity": 112.0},
                {"asset": "STRC", "quantity": 250.0},
                {"asset": "SATA", "quantity": 0.0},
            ],
            "cash": {"available_usd": 791.35, "reserved_usd": 0.0},
        },
    }


def side_job(**changes):
    result = {
        "strc_dividend_per_share": 0.50,
        "sata_daily_distribution": 0.0516,
        "d1_entry_price": 99.00,
        "trading_friction_per_share": 0.01,
        "tax_friction_per_share": 0.0,
        "required_edge_per_share": 0.0,
        "foregone_sata_distribution_days": 1,
        "window_stage": "D_MINUS_1",
        "window_binding_state": "VALIDATED",
        "window_basis_ref": "synthetic:strc-corporate-action-plus-trading-calendar",
        "evaluation_date": "2026-09-29",
        "strc_ex_date": "2026-09-30",
        "d_minus_1_trade_date": "2026-09-29",
        "analyst_entry_gate_state": "PASS",
        "legacy_strc_inventory_shares": 250.0,
        "side_job_capital_usd": 5_000.0,
    }
    result.update(changes)
    return result


def inputs(**changes):
    result = {
        "residual_value_inputs": residual_inputs(),
        "season_context": season("SPRING", cash_target_pct=8.0, spring_stage="CENTER"),
        "valuation_constraints": {"MSTR": "ALLOW_TILT", "ASST": "ALLOW_TILT"},
        "market_prices": {"MSTR": 160.0, "ASST": 30.0, "STRC": 99.0, "SATA": 100.0},
        "side_job_context": side_job(),
    }
    result.update(changes)
    return result


class PortfolioAllocationAcceptanceTests(unittest.TestCase):
    def test_01_three_pool_math_closes(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(), inputs=inputs()
        )["portfolio_allocation_context"]
        math = result["target_portfolio_math"]
        self.assertAlmostEqual(
            math["cash_pct"] + math["fixed_income_portfolio_pct"] + math["growth_portfolio_pct"],
            100.0,
        )
        self.assertAlmostEqual(
            math["mstr_portfolio_pct"] + math["asst_portfolio_pct"],
            math["growth_portfolio_pct"],
        )

    def test_02_four_seasons_cash_fixed_growth_are_reproducible(self):
        expected = {
            "WINTER": ((12.0, 15.0), 80.0, 20.0),
            "SPRING": ((8.0, 10.0), 70.0, 30.0),
            "SUMMER": ((5.0, 7.0), 55.0, 45.0),
            "AUTUMN": ((10.0, 15.0), 80.0, 20.0),
        }
        for name, (cash, fixed, growth) in expected.items():
            result = build_portfolio_allocation_context(
                pack=pack_for(),
                private_context=private_context(),
                inputs=inputs(season_context=season(name)),
            )["portfolio_allocation_context"]
            self.assertEqual(tuple(result["cash_target_range"]), cash)
            self.assertEqual(result["fixed_income_target_pct"], fixed)
            self.assertEqual(result["growth_target_pct"], growth)

    def test_03_four_seasons_growth_split_is_reproducible(self):
        expected = {
            "WINTER": (80.0, 20.0),
            "SPRING": (65.0, 35.0),
            "SUMMER": (55.0, 45.0),
            "AUTUMN": (75.0, 25.0),
        }
        for name, split in expected.items():
            result = build_portfolio_allocation_context(
                pack=pack_for(),
                private_context=private_context(),
                inputs=inputs(
                    season_context=season(name),
                    valuation_constraints={"MSTR": "BRAKE", "ASST": "BRAKE"},
                ),
            )["portfolio_allocation_context"]
            self.assertEqual(
                (result["mstr_growth_base_pct"], result["asst_growth_base_pct"]),
                split,
            )

    def test_04_destination_can_lead_confirmation(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(),
            private_context=private_context(),
            inputs=inputs(
                season_context=season(
                    "SUMMER",
                    posture="SPRING",
                    phase="REINFORCEMENT",
                    cash_target_pct=5.0,
                )
            ),
        )["portfolio_allocation_context"]
        self.assertEqual(result["season_posture"], "SPRING")
        self.assertEqual(result["allocation_destination"], "SUMMER")

    def test_05_preferred_to_common_linkage_is_visible(self):
        health = build_common_equity_health(pack_for(), residual_inputs())["assets"]["MSTR"]
        self.assertIsNotNone(health["senior_claim_change_usd"])
        self.assertIsNotNone(health["annual_carry_change_usd"])
        self.assertIsNotNone(health["cash_coverage_context"])

    def test_06_residual_value_correct_or_blocked(self):
        health = build_common_equity_health(pack_for(), residual_inputs())["assets"]["MSTR"]
        expected = (120.0 * 83_000.0 + 500.0 - 1_000.0) / 110.0
        self.assertAlmostEqual(health["net_residual_value_per_diluted_share"], expected)
        blocked = build_common_equity_health(pack_for(), {})["assets"]["MSTR"]
        self.assertIsNone(blocked["net_residual_value_per_diluted_share"])
        self.assertEqual(blocked["health_direction"], "BLOCKED")

    def test_07_health_states_cover_improving_stable_deteriorating_blocked(self):
        improving = build_common_equity_health(pack_for(), residual_inputs())["assets"]["MSTR"]
        self.assertEqual(improving["health_direction"], "IMPROVING")

        flat_pack = pack_for(mstr_btc=(100, 100), mstr_shares=(100, 100), mstr_liquidity=(500, 500))
        flat_residual = residual_inputs(mstr_prices=(80_000, 80_000))
        stable = build_common_equity_health(flat_pack, flat_residual)["assets"]["MSTR"]
        self.assertEqual(stable["health_direction"], "STABLE")

        bad_pack = pack_for(mstr_btc=(120, 100), mstr_shares=(100, 110),
                            mstr_claims=(1_000, 3_000_000), mstr_liquidity=(500, 450))
        deteriorating = build_common_equity_health(bad_pack, residual_inputs())["assets"]["MSTR"]
        self.assertEqual(deteriorating["health_direction"], "DETERIORATING")

        blocked = build_common_equity_health(pack_for(), {})["assets"]["MSTR"]
        self.assertEqual(blocked["health_direction"], "BLOCKED")

    def test_08_health_tilt_is_five_points_normally(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(),
            private_context=private_context(),
            inputs=inputs(
                season_context=season("SPRING", spring_stage="CENTER"),
                valuation_constraints={"MSTR": "ALLOW_TILT", "ASST": "ALLOW_TILT"},
            ),
        )["portfolio_allocation_context"]
        self.assertEqual(result["health_tilt_pct"], 5.0)
        self.assertEqual((result["suggested_mstr_pct"], result["suggested_asst_pct"]), (70.0, 30.0))

    def test_09_valuation_brake_blocks_tilt(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(),
            private_context=private_context(),
            inputs=inputs(
                valuation_constraints={"MSTR": "BRAKE", "ASST": "ALLOW_TILT"},
            ),
        )["portfolio_allocation_context"]
        self.assertEqual(result["health_tilt_pct"], 0.0)
        self.assertIn("VALUATION", result["health_tilt_reason"])
        self.assertEqual(result["suggested_mstr_pct"], result["mstr_growth_base_pct"])

    def test_10_summer_cash_never_targets_zero(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("SUMMER")),
        )["portfolio_allocation_context"]
        self.assertEqual(result["cash_target_range"], [5.0, 7.0])

    def test_11_severe_stress_allows_cash_to_twenty_not_above(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("WINTER", severe_stress=True, cash_target_pct=20.0)),
        )["portfolio_allocation_context"]
        self.assertEqual(result["cash_target_pct"], 20.0)
        with self.assertRaises(ValueError):
            build_portfolio_allocation_context(
                pack=pack_for(), private_context=private_context(),
                inputs=inputs(season_context=season("WINTER", severe_stress=True, cash_target_pct=20.1)),
            )

    def test_12_normal_summer_growth_is_forty_five(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("SUMMER")),
        )["portfolio_allocation_context"]
        self.assertEqual(result["growth_target_pct"], 45.0)

    def test_13_extreme_summer_flag_is_deprecated_noop(self):
        normal = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("SUMMER")),
        )["portfolio_allocation_context"]
        extreme = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("SUMMER", extreme_summer=True)),
        )["portfolio_allocation_context"]
        self.assertEqual(normal["growth_target_pct"], 45.0)
        self.assertEqual(extreme["growth_target_pct"], 45.0)
        self.assertEqual(normal, extreme)

    def test_14_user_holdings_do_not_change_issuer_health(self):
        health_a = build_common_equity_health(pack_for(), residual_inputs())
        private_a = private_context()
        private_b = private_context()
        private_b["profile"]["holdings"][0]["quantity"] = 4_000
        self.assertEqual(
            health_a,
            build_common_equity_health(pack_for(), residual_inputs()),
        )
        self.assertNotEqual(
            build_portfolio_allocation_context(
                pack=pack_for(), private_context=private_a, inputs=inputs()
            )["portfolio_allocation_context"]["current_allocation"]["total_portfolio_usd"],
            build_portfolio_allocation_context(
                pack=pack_for(), private_context=private_b, inputs=inputs()
            )["portfolio_allocation_context"]["current_allocation"]["total_portfolio_usd"],
        )

    def test_15_issuer_preferred_burden_changes_health_facts(self):
        base = build_common_equity_health(pack_for(), residual_inputs())["assets"]["MSTR"]
        changed = build_common_equity_health(
            pack_for(mstr_claims=(1_000, 900), mstr_carry=(100, 90), mstr_liquidity=(500, 400)),
            residual_inputs(),
        )["assets"]["MSTR"]
        self.assertNotEqual(base["senior_claim_change_usd"], changed["senior_claim_change_usd"])
        self.assertNotEqual(base["annual_carry_change_usd"], changed["annual_carry_change_usd"])
        self.assertNotEqual(base["liquidity_change_usd"], changed["liquidity_change_usd"])

    def test_16_mature_spring_can_predeploy_summer(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("SUMMER", posture="SPRING", phase="REINFORCEMENT")),
        )["portfolio_allocation_context"]
        self.assertEqual((result["season_posture"], result["allocation_destination"]), ("SPRING", "SUMMER"))

    def test_17_late_summer_can_preharvest_autumn(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("AUTUMN", posture="SUMMER", phase="TREND_HOLD_HARVEST")),
        )["portfolio_allocation_context"]
        self.assertEqual(result["allocation_destination"], "AUTUMN")

    def test_18_late_autumn_can_predeploy_winter(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(season_context=season("WINTER", posture="AUTUMN", phase="RESERVE")),
        )["portfolio_allocation_context"]
        self.assertEqual(result["allocation_destination"], "WINTER")

    def test_19_bucket_pct_and_portfolio_pct_are_distinct_and_close(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(
                season_context=season("SUMMER", cash_target_pct=5.0),
                valuation_constraints={"MSTR": "BRAKE", "ASST": "BRAKE"},
            ),
        )["portfolio_allocation_context"]
        math = result["target_portfolio_math"]
        self.assertEqual(result["fixed_income_target_pct"], 55.0)
        self.assertAlmostEqual(math["fixed_income_portfolio_pct"], 52.25)
        self.assertAlmostEqual(math["growth_portfolio_pct"], 42.75)
        self.assertAlmostEqual(math["mstr_portfolio_pct"], 23.5125)
        self.assertAlmostEqual(math["asst_portfolio_pct"], 19.2375)

    def test_20_unknown_never_becomes_zero(self):
        cfg = inputs()
        cfg["residual_value_inputs"]["MSTR"]["current"].pop("other_senior_claims_usd")
        health = build_common_equity_health(pack_for(), cfg["residual_value_inputs"])["assets"]["MSTR"]
        self.assertIsNone(health["net_residual_value_per_diluted_share"])
        self.assertEqual(health["health_direction"], "BLOCKED")

    def test_d_minus_1_requires_analyst_gate_not_machine_price_forecast(self):
        for gate_state, expected in (("PASS", "EXECUTE"), ("FAIL", "SKIP")):
            result = build_portfolio_allocation_context(
                pack=pack_for(),
                private_context=private_context(),
                inputs=inputs(side_job_context=side_job(analyst_entry_gate_state=gate_state)),
            )["portfolio_allocation_context"]["side_job"]
            self.assertEqual(result["state"], expected)
        raw = side_job()
        raw.pop("analyst_entry_gate_state")
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(),
            inputs=inputs(side_job_context=raw),
        )["portfolio_allocation_context"]["side_job"]
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "D_MINUS_1_ANALYST_ENTRY_GATE_UNAVAILABLE")

    def test_residual_requires_explicit_capital_structure_coherence(self):
        cfg = inputs()
        cfg["residual_value_inputs"]["MSTR"]["current"].pop("capital_structure_coherence_state")
        health = build_common_equity_health(pack_for(), cfg["residual_value_inputs"])["assets"]["MSTR"]
        self.assertIsNone(health["net_residual_value_per_diluted_share"])
        self.assertEqual(health["health_direction"], "BLOCKED")
        self.assertIn("NET_RESIDUAL_VALUE_PER_DILUTED_SHARE_UNAVAILABLE", health["blockers"])

    def test_side_job_capital_scope_is_separate_from_legacy_inventory(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(), inputs=inputs()
        )["portfolio_allocation_context"]["side_job"]
        self.assertEqual(result["legacy_strc_inventory_shares"], 250.0)
        self.assertEqual(result["side_job_capital_usd"], 5_000.0)
        self.assertEqual(result["capital_scope_state"], "AVAILABLE")
        cfg = inputs(side_job_context=side_job(side_job_capital_usd=None))
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(), inputs=cfg
        )["portfolio_allocation_context"]["side_job"]
        self.assertEqual(result["state"], "EXECUTE")
        self.assertEqual(result["capital_scope_state"], "BLOCKED")

    def test_side_job_break_even_and_exit_pending(self):
        cfg = inputs(
            side_job_context=side_job(
                window_stage="D",
                evaluation_date="2026-09-30",
                d1_entry_price=98.91,
                current_strc_bid=98.32,
                entitlement_secured=True,
            )
        )
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(), inputs=cfg
        )["portfolio_allocation_context"]["side_job"]
        self.assertAlmostEqual(result["d_exit_floor"], 98.4716)
        self.assertEqual(result["state"], "EXIT_PENDING")

    def test_formal_season_blocked_never_defaults_to_winter(self):
        cfg = inputs()
        cfg["season_context"] = {
            "season_source": "FORMAL",
            "formal_state": "BLOCKED",
            "season_posture": "WINTER",
            "allocation_destination": "WINTER",
            "deployment_phase": "RESERVE",
        }
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(), inputs=cfg
        )["portfolio_allocation_context"]
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("FORMAL_SEASON_NOT_AVAILABLE", result["blockers"])

    def test_formal_season_cannot_be_spoofed_by_local_input(self):
        p = pack_for()
        p["model_status"] = {
            "btc_season_router": {
                "state": "CANDIDATE_BLOCKED",
                "season": None,
                "formal_model": "NOT_APPROVED",
            }
        }
        cfg = inputs()
        cfg["season_context"] = {
            "season_source": "FORMAL",
            "formal_state": "AVAILABLE",
            "season_posture": "SPRING",
            "allocation_destination": "SPRING",
            "deployment_phase": "BRIDGEHEAD",
        }
        result = build_portfolio_allocation_context(
            pack=p, private_context=private_context(), inputs=cfg
        )["portfolio_allocation_context"]
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("FORMAL_SEASON_NOT_AVAILABLE", result["blockers"])

    def test_formal_season_must_match_router_lineage(self):
        p = pack_for()
        p["model_status"] = {
            "btc_season_router": {
                "state": "AVAILABLE",
                "season": "SPRING",
                "formal_model": "APPROVED",
            }
        }
        cfg = inputs()
        cfg["season_context"] = {
            "season_source": "FORMAL",
            "formal_state": "AVAILABLE",
            "season_posture": "WINTER",
            "allocation_destination": "SPRING",
            "deployment_phase": "BRIDGEHEAD",
        }
        result = build_portfolio_allocation_context(
            pack=p, private_context=private_context(), inputs=cfg
        )["portfolio_allocation_context"]
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("FORMAL_SEASON_LINEAGE_MISMATCH", result["blockers"])

    def test_outside_window_does_not_require_d1_economics(self):
        raw = side_job(window_stage="OUTSIDE_WINDOW", evaluation_date="2026-09-25")
        for field in (
            "strc_dividend_per_share",
            "sata_daily_distribution",
            "d1_entry_price",
            "trading_friction_per_share",
            "tax_friction_per_share",
            "required_edge_per_share",
        ):
            raw.pop(field)
        result = build_portfolio_allocation_context(
            pack=pack_for(),
            private_context=private_context(),
            inputs=inputs(side_job_context=raw),
        )["portfolio_allocation_context"]["side_job"]
        self.assertEqual(result["state"], "SKIP")
        self.assertEqual(result["fixed_income_carrier"], "SATA")
        self.assertIsNone(result["d_exit_floor"])

    def test_entitlement_window_stage_must_match_validated_dates(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(),
            private_context=private_context(),
            inputs=inputs(
                side_job_context=side_job(
                    window_stage="D",
                    evaluation_date="2026-09-29",
                    entitlement_secured=True,
                    current_strc_bid=99.0,
                )
            ),
        )["portfolio_allocation_context"]["side_job"]
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "ENTITLEMENT_WINDOW_STAGE_DATE_MISMATCH")

    def test_side_job_negative_friction_fails_closed(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(),
            private_context=private_context(),
            inputs=inputs(
                side_job_context=side_job(trading_friction_per_share=-0.01)
            ),
        )["portfolio_allocation_context"]["side_job"]
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "SIDE_JOB_INPUT_INVALID")

    def test_capital_scope_blocked_does_not_route_sata_out(self):
        from crt_radar.asset_strategy_delta import build_asset_strategy_delta
        private = {
            "state": "AVAILABLE",
            "profile": {
                "cash_goal": {"six_month_target_usd": 1500.0},
                "derived": {
                    "six_month_cash_usd": 1643.4,
                    "goal_covered_at_current_rate": True,
                },
            },
        }
        allocation = {
            "state": "READY_FOR_ANALYST",
            "mstr_health": "STABLE",
            "asst_health": "STABLE",
            "valuation_constraint": {"MSTR": "BRAKE", "ASST": "BRAKE"},
            "side_job": {
                "state": "EXECUTE",
                "window_stage": "D_MINUS_1",
                "capital_scope_state": "BLOCKED",
            },
        }
        result = build_asset_strategy_delta(
            btc_entry_gate={
                "transition_state": "TRANSITION_UNRESOLVED",
                "decision_eligibility": "WAIT",
            },
            assumption_watch={"state": "VALID"},
            private_context=private,
            portfolio_allocation_context=allocation,
        )
        self.assertEqual(
            result["assets"]["STRC"]["strategy_delta"],
            "BLOCKED_INCOME_PROFILE",
        )
        self.assertEqual(
            result["assets"]["SATA"]["strategy_delta"],
            "BLOCKED_INCOME_PROFILE",
        )

    def test_action_output_and_authority_stay_locked(self):
        result = build_portfolio_allocation_context(
            pack=pack_for(), private_context=private_context(), inputs=inputs()
        )["portfolio_allocation_context"]
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")
        self.assertEqual(result["production"], "NOT_APPROVED")


class AssetStrategyDeltaPortfolioIntegrationTests(unittest.TestCase):
    def test_no_context_preserves_legacy_blockers(self):
        from crt_radar.asset_strategy_delta import build_asset_strategy_delta
        private = {
            "state": "AVAILABLE",
            "profile": {
                "cash_goal": {"six_month_target_usd": 1500.0},
                "derived": {
                    "six_month_cash_usd": 1643.4,
                    "goal_covered_at_current_rate": True,
                },
            },
        }
        result = build_asset_strategy_delta(
            btc_entry_gate={
                "transition_state": "TRANSITION_UNRESOLVED",
                "decision_eligibility": "WAIT",
            },
            assumption_watch={"state": "VALID"},
            private_context=private,
        )
        self.assertEqual(result["assets"]["STRC"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")
        self.assertIsNone(result["income_engine"]["coverage_ratio"])
        self.assertEqual(result["assets"]["SATA"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")
        self.assertEqual(result["assets"]["MSTR"]["decision_support"], "BLOCKED")

    def test_d_research_does_not_choose_either_income_role(self):
        from crt_radar.asset_strategy_delta import build_asset_strategy_delta
        private = {
            "state": "AVAILABLE",
            "profile": {
                "cash_goal": {"six_month_target_usd": 1500.0},
                "derived": {"six_month_cash_usd": 1643.4, "goal_covered_at_current_rate": True},
            },
        }
        allocation = {
            "state": "READY_FOR_ANALYST",
            "mstr_health": "STABLE",
            "asst_health": "STABLE",
            "valuation_constraint": {"MSTR": "BRAKE", "ASST": "BRAKE"},
            "side_job": {"state": "EXECUTE", "window_stage": "D", "capital_scope_state": "AVAILABLE"},
        }
        result = build_asset_strategy_delta(
            btc_entry_gate={"transition_state": "TRANSITION_UNRESOLVED", "decision_eligibility": "WAIT"},
            assumption_watch={"state": "VALID"},
            private_context=private,
            portfolio_allocation_context=allocation,
        )
        self.assertEqual(result["assets"]["STRC"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")
        self.assertEqual(result["assets"]["SATA"]["strategy_delta"], "BLOCKED_INCOME_PROFILE")

    def test_research_context_preserves_income_neutrality_and_health_review(self):
        from crt_radar.asset_strategy_delta import build_asset_strategy_delta
        private = {
            "state": "AVAILABLE",
            "profile": {
                "cash_goal": {"six_month_target_usd": 1500.0},
                "derived": {
                    "six_month_cash_usd": 1643.4,
                    "goal_covered_at_current_rate": True,
                },
            },
        }
        allocation = {
            "state": "READY_FOR_ANALYST",
            "mstr_health": "IMPROVING",
            "asst_health": "STABLE",
            "valuation_constraint": {
                "MSTR": "ALLOW_TILT",
                "ASST": "ALLOW_TILT",
            },
            "side_job": {
                "state": "EXECUTE",
                "window_stage": "D_MINUS_1",
                "capital_scope_state": "AVAILABLE",
            },
        }
        result = build_asset_strategy_delta(
            btc_entry_gate={
                "transition_state": "BULL_ACCEPTANCE_STRENGTHENED",
                "decision_eligibility": "PROBE_ELIGIBLE",
                "control_transfer_validation": {
                    "control_transfer_loop_closed": True,
                },
            },
            assumption_watch={"state": "VALID"},
            private_context=private,
            portfolio_allocation_context=allocation,
        )
        self.assertEqual(
            result["assets"]["STRC"]["strategy_delta"],
            "BLOCKED_INCOME_PROFILE",
        )
        self.assertEqual(
            result["assets"]["SATA"]["strategy_delta"],
            "BLOCKED_INCOME_PROFILE",
        )
        self.assertEqual(result["assets"]["MSTR"]["decision_support"], "READY_FOR_ANALYST")
        self.assertEqual(result["assets"]["ASST"]["decision_support"], "READY_FOR_ANALYST")


class ResidualSnapshotQualificationTests(unittest.TestCase):
    @staticmethod
    def snapshot(pack, section, label, asset="MSTR"):
        return next(fact["evidence"][label] for fact in pack["asset_facts"]["items"]
                    if fact.get("issuer_id") == ISSUER[asset] and fact.get("ct_section") == section)

    def test_same_date_distinct_share_and_burden_bases_are_usable(self):
        p = pack_for()
        self.assertNotEqual(self.snapshot(p, "per_share_asset_engine", "current")["basis_ref"],
                            self.snapshot(p, "capital_burden_resilience", "current")["basis_ref"])
        row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
        self.assertAlmostEqual(row["net_residual_value_per_diluted_share"],
                               (120 * 83_000 + 500 - 1_000) / 110)
        self.assertEqual(row["health_direction"], "IMPROVING")

    def test_different_dates_block_residual_but_preserve_independent_btc_per_share(self):
        p = pack_for()
        p["asset_facts"]["items"] = [fact for fact in p["asset_facts"]["items"]
                                     if fact.get("fact_type") != "TREASURY_VALUATION_CONTEXT"]
        self.snapshot(p, "capital_burden_resilience", "current")["effective_time"] += 1
        row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
        self.assertIsNone(row["net_residual_value_per_diluted_share"])
        self.assertIsNone(row["net_residual_value_per_diluted_share_change_pct"])
        self.assertIn("RESIDUAL_SNAPSHOT_EFFECTIVE_TIME_MISMATCH", row["blockers"])
        self.assertAlmostEqual(row["btc_per_diluted_share"], 120 / 110)
        self.assertAlmostEqual(row["btc_per_diluted_share_change_pct"], 120 / 110 - 1)
        self.assertEqual(row["health_direction"], "BLOCKED")

    def test_cross_company_unverified_missing_source_and_invalid_clocks_block(self):
        changes = (
            {"issuer_id": ISSUER["ASST"]}, {"verification_state": "UNVERIFIED"},
            {"source_ref": ""}, {"first_seen_time": None},
            {"disclosure_time": CURRENT_TIME - 1},
            {"first_seen_time": REPLAY_TIME + 1, "retrieval_time": REPLAY_TIME + 2},
        )
        for section in ("per_share_asset_engine", "capital_burden_resilience"):
            for change in changes:
                with self.subTest(section=section, change=change):
                    p = pack_for()
                    self.snapshot(p, section, "current").update(change)
                    row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
                    self.assertIsNone(row["net_residual_value_per_diluted_share"])
                    self.assertIn("RESIDUAL_SNAPSHOT_NOT_LOCALLY_VALIDATED", row["blockers"])
                    self.assertEqual(row["health_direction"], "BLOCKED")

    def test_missing_replay_clock_cannot_promote_residual(self):
        p = pack_for()
        p.pop("generated_at_ms")
        row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
        self.assertIsNone(row["net_residual_value_per_diluted_share"])
        self.assertIn("RESIDUAL_REPLAY_TIME_UNAVAILABLE", row["blockers"])

    def test_changed_share_basis_or_burden_scope_blocks_only_comparison(self):
        for section in ("per_share_asset_engine", "capital_burden_resilience"):
            with self.subTest(section=section):
                p = pack_for()
                self.snapshot(p, section, "current")["basis_ref"] = "synthetic:changed-basis"
                row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
                self.assertIsNotNone(row["net_residual_value_per_diluted_share"])
                self.assertIsNotNone(row["previous_net_residual_value_per_diluted_share"])
                self.assertIsNone(row["net_residual_value_per_diluted_share_change_pct"])
                self.assertIn("RESIDUAL_VALUE_SCENARIOS_NOT_COMPARABLE", row["blockers"])
                self.assertEqual(row["health_direction"], "BLOCKED")

    def test_changed_dilution_scenario_does_not_support_improvement(self):
        r = residual_inputs()
        r["MSTR"]["current"]["capital_structure_scenario_ref"] = "synthetic:converted-debt-scenario"
        row = build_common_equity_health(pack_for(), r)["assets"]["MSTR"]
        self.assertIsNotNone(row["net_residual_value_per_diluted_share"])
        self.assertIsNone(row["net_residual_value_per_diluted_share_change_pct"])
        self.assertIn("RESIDUAL_VALUE_SCENARIOS_NOT_COMPARABLE", row["blockers"])
        self.assertEqual(row["health_direction"], "BLOCKED")

    def test_nonincreasing_snapshot_order_cannot_support_comparison(self):
        p = pack_for()
        for section in ("per_share_asset_engine", "capital_burden_resilience"):
            row = self.snapshot(p, section, "previous")
            row.update(effective_time=CURRENT_TIME + 100, disclosure_time=CURRENT_TIME + 110,
                       first_seen_time=CURRENT_TIME + 120, retrieval_time=CURRENT_TIME + 130)
        row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
        self.assertIsNotNone(row["net_residual_value_per_diluted_share"])
        self.assertIsNone(row["net_residual_value_per_diluted_share_change_pct"])
        self.assertIn("RESIDUAL_VALUE_SCENARIOS_NOT_COMPARABLE", row["blockers"])

    def test_btc_accretion_and_residual_deterioration_require_analyst(self):
        row = build_common_equity_health(pack_for(mstr_claims=(1_000, 3_000_000)),
                                         residual_inputs())["assets"]["MSTR"]
        self.assertGreater(row["btc_per_diluted_share_change_pct"], 0)
        self.assertLess(row["net_residual_value_per_diluted_share_change_pct"], 0)
        self.assertEqual(row["health_direction"], "BLOCKED")
        self.assertIn("MULTIDIMENSIONAL_TRADE_OFF_REQUIRES_ANALYST", row["health_reasons"])

    def test_negative_residual_recovery_preserves_absolute_improvement_not_percent_rank(self):
        p = pack_for(mstr_btc=(100, 110), mstr_shares=(100, 100),
                     mstr_claims=(1100, 610), mstr_liquidity=(0, 0))
        row = build_common_equity_health(p, residual_inputs(mstr_prices=(1, 1)))["assets"]["MSTR"]
        self.assertEqual(row["previous_net_residual_value_per_diluted_share"], -10)
        self.assertEqual(row["net_residual_value_per_diluted_share"], -5)
        self.assertIsNone(row["net_residual_value_per_diluted_share_change_pct"])
        self.assertIn("PREVIOUS_RESIDUAL_VALUE_NEGATIVE", row["blockers"])
        self.assertEqual(row["health_direction"], "BLOCKED")
        self.assertNotIn("NET_RESIDUAL_VALUE_PER_DILUTED_SHARE_DECREASED", row["health_reasons"])
        claim = row["company_health"]["dimensions"]["per_share_asset_engine"]["claims"]["net_residual_value_per_share"]
        self.assertEqual(claim["value"], 5)
        self.assertEqual(claim["direction"], "IMPROVING")

    def test_negative_residual_loss_cannot_reverse_into_improvement(self):
        p = pack_for(mstr_btc=(100, 110), mstr_shares=(100, 100),
                     mstr_claims=(1100, 1610), mstr_liquidity=(0, 0))
        row = build_common_equity_health(p, residual_inputs(mstr_prices=(1, 1)))["assets"]["MSTR"]
        self.assertEqual(row["previous_net_residual_value_per_diluted_share"], -10)
        self.assertEqual(row["net_residual_value_per_diluted_share"], -15)
        self.assertIsNone(row["net_residual_value_per_diluted_share_change_pct"])
        self.assertIn("PREVIOUS_RESIDUAL_VALUE_NEGATIVE", row["blockers"])
        self.assertEqual(row["health_direction"], "BLOCKED")
        self.assertNotIn("NET_RESIDUAL_VALUE_PER_DILUTED_SHARE_INCREASED", row["health_reasons"])
        claim = row["company_health"]["dimensions"]["per_share_asset_engine"]["claims"]["net_residual_value_per_share"]
        self.assertEqual(claim["value"], -5)
        self.assertEqual(claim["direction"], "DETERIORATING")

    def test_legacy_changes_match_qualified_dimension_claims(self):
        p = pack_for(mstr_claims=(1000, 900), mstr_carry=(100, 90), mstr_liquidity=(450, 500))
        health = build_common_equity_health(p, residual_inputs())
        row = health["assets"]["MSTR"]
        self.assertEqual(row["senior_claim_change_usd"], -100)
        self.assertEqual(row["annual_carry_change_usd"], -10)
        self.assertEqual(row["liquidity_change_usd"], 50)
        self.assertEqual(row["cash_coverage_context"]["usable_liquidity_usd"], 500)
        compact = compact_portfolio_allocation_context_for_bridge({"common_equity_health": health})
        self.assertEqual(compact["common_equity_health"]["assets"]["MSTR"]["liquidity_change_usd"], 50)

    def test_changed_burden_basis_cannot_leak_legacy_changes(self):
        p = pack_for(mstr_claims=(1000, 900), mstr_carry=(100, 90), mstr_liquidity=(450, 500))
        self.snapshot(p, "capital_burden_resilience", "current")["basis_ref"] = "synthetic:new-burden-scope"
        row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
        for field, blocker in (("senior_claim_change_usd", "SENIOR_CLAIM_CHANGE_UNAVAILABLE"),
                               ("annual_carry_change_usd", "ANNUAL_CARRY_CHANGE_UNAVAILABLE"),
                               ("liquidity_change_usd", "LIQUIDITY_CHANGE_UNAVAILABLE")):
            self.assertIsNone(row[field])
            self.assertIn(blocker, row["blockers"])

    def test_changed_cash_coverage_scope_blocks_liquidity_only(self):
        p = pack_for(mstr_claims=(1000, 900), mstr_carry=(100, 90), mstr_liquidity=(450, 500))
        self.snapshot(p, "capital_burden_resilience", "previous")["coverage_basis"] = "USD_CASH_PLUS_SEPARATE_USABLE_RESERVE"
        row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
        self.assertIsNone(row["liquidity_change_usd"])
        self.assertIn("LIQUIDITY_CHANGE_UNAVAILABLE", row["blockers"])
        self.assertEqual(row["senior_claim_change_usd"], -100)
        self.assertEqual(row["annual_carry_change_usd"], -10)
        self.assertEqual(row["cash_coverage_context"]["usable_liquidity_usd"], 500)

    def test_missing_current_cash_usability_keeps_reported_fact_but_blocks_context(self):
        p = pack_for()
        current = self.snapshot(p, "capital_burden_resilience", "current")
        current.pop("cash_usability_basis_ref")
        row = build_common_equity_health(p, residual_inputs())["assets"]["MSTR"]
        self.assertIsNone(row["liquidity_change_usd"])
        self.assertIsNone(row["cash_coverage_context"])
        self.assertIn("LIQUIDITY_CHANGE_UNAVAILABLE", row["blockers"])
        self.assertIn("CASH_COVERAGE_CONTEXT_INCOMPLETE", row["blockers"])
        self.assertEqual(current["usable_liquidity_usd"], 500)
        self.assertEqual(row["senior_claim_change_usd"], 0)

    def test_compact_projection_does_not_reintroduce_unqualified_cash_delta(self):
        p = pack_for(mstr_liquidity=(5_713_400_000, 640_500_000))
        self.snapshot(p, "capital_burden_resilience", "previous")["coverage_basis"] = "USD_CASH_PLUS_SEPARATE_USABLE_RESERVE"
        self.snapshot(p, "capital_burden_resilience", "current").pop("cash_usability_basis_ref")
        health = build_common_equity_health(p, residual_inputs())
        compact = compact_portfolio_allocation_context_for_bridge({"common_equity_health": health})
        row = compact["common_equity_health"]["assets"]["MSTR"]
        self.assertIsNone(row["liquidity_change_usd"])
        self.assertIsNone(row["carry_coverage_years"])
        self.assertIn("LIQUIDITY_CHANGE_UNAVAILABLE", row["blockers"])
        self.assertIn("CASH_COVERAGE_CONTEXT_INCOMPLETE", row["blockers"])


class StrategicBtcPortfolioIntegrationTests(
    unittest.TestCase
):
    def test_direct_btc_holding_does_not_block_existing_policy_math(
        self,
    ):
        baseline = (
            build_portfolio_allocation_context(
                pack=pack_for(),
                private_context=private_context(),
                inputs=inputs(),
            )[
                "portfolio_allocation_context"
            ]
        )

        private = private_context()

        private[
            "profile"
        ][
            "holdings"
        ].append(
            {
                "asset": "BTC",
                "quantity": 0.25,
            }
        )

        private[
            "profile"
        ][
            "btc_strategy"
        ] = {
            "strategic_target_btc": 1.0,
            "target_basis_ref": (
                "USER_DEFINED_FIRST_BTC_OBJECTIVE"
            ),
        }

        p = pack_for()

        p[
            "btc_long_horizon_context"
        ] = {
            "state": "READY_FOR_ANALYST",
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "formal_price_target_authority": "NONE",
        }

        result = (
            build_portfolio_allocation_context(
                pack=p,
                private_context=private,
                inputs=inputs(),
            )[
                "portfolio_allocation_context"
            ]
        )

        current = result[
            "current_allocation"
        ]

        strategic = result[
            "strategic_btc_context"
        ]

        self.assertEqual(
            current["state"],
            "AVAILABLE",
        )
        self.assertEqual(
            current[
                "strategic_btc_quantity"
            ],
            0.25,
        )
        self.assertTrue(
            current[
                "strategic_btc_excluded_from_policy_math"
            ]
        )
        self.assertAlmostEqual(
            current[
                "fixed_income_usd"
            ],
            baseline[
                "current_allocation"
            ][
                "fixed_income_usd"
            ],
        )
        self.assertAlmostEqual(
            current[
                "growth_usd"
            ],
            baseline[
                "current_allocation"
            ][
                "growth_usd"
            ],
        )
        self.assertAlmostEqual(
            strategic[
                "btc_acquisition_gap"
            ],
            0.75,
        )

    def test_summer_posture_can_lead_autumn_harvest_destination(
        self,
    ):
        private = private_context()

        private[
            "profile"
        ][
            "holdings"
        ].append(
            {
                "asset": "BTC",
                "quantity": 0.25,
            }
        )

        private[
            "profile"
        ][
            "btc_strategy"
        ] = {
            "strategic_target_btc": 1.0,
            "target_basis_ref": (
                "USER_DEFINED_FIRST_BTC_OBJECTIVE"
            ),
        }

        result = (
            build_portfolio_allocation_context(
                pack=pack_for(),
                private_context=private,
                inputs=inputs(
                    season_context=season(
                        "AUTUMN",
                        posture="SUMMER",
                        phase=(
                            "TREND_HOLD_HARVEST"
                        ),
                    )
                ),
            )[
                "portfolio_allocation_context"
            ]
        )

        route = result[
            "btc_acquisition_route_context"
        ]

        self.assertTrue(
            route[
                "peak_harvest_zone"
            ][
                "summer_posture_autumn_destination"
            ]
        )
        self.assertFalse(
            route[
                "peak_harvest_zone"
            ][
                "machine_peak_tick_detection"
            ]
        )
        self.assertEqual(
            route[
                "reserve_purpose"
            ],
            "FUTURE_BTC_ACQUISITION",
        )
        self.assertEqual(
            route[
                "carrier_candidates"
            ],
            [
                "SATA",
                "STRC",
                "CASH",
            ],
        )
        self.assertEqual(
            route["action_output"],
            "NONE",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
