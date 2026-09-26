from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.gpt_handoff import (
    build_minimized_bridge_payload,
    run_gpt_handoff_gate,
)
from crt_radar.plain_language_notice import build_plain_language_notice
from test_first_evidence_slice import gate
from test_gpt_handoff import bridge_pack, pack


class PortfolioAllocationWiringTests(unittest.TestCase):
    def test_evidence_pack_attaches_context_without_action_authority(self):
        allocation_inputs = {
            "season_context": {
                "season_source": "LABELED_ANALYST_HYPOTHESIS",
                "analyst_hypothesis_evidence_state": "INDEPENDENTLY_EVIDENCED",
                "season_posture": "SPRING",
                "allocation_destination": "SUMMER",
                "deployment_phase": "REINFORCEMENT",
                "cash_target_pct": 5.0,
            },
            "valuation_constraints": {
                "MSTR": "BRAKE",
                "ASST": "BRAKE",
            },
            "side_job_context": {
                "strc_dividend_per_share": 0.50,
                "sata_daily_distribution": 0.0516,
                "d1_entry_price": 99.0,
                "trading_friction_per_share": 0.01,
                "tax_friction_per_share": 0.0,
                "required_edge_per_share": 0.0,
                "foregone_sata_distribution_days": 1,
                "window_stage": "OUTSIDE_WINDOW",
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            result = build_evidence_pack(
                gate(0),
                observation_db=Path(folder) / "obs.db",
                generated_at_ms=1_790_000_000_000,
                portfolio_allocation_inputs=allocation_inputs,
            )
        self.assertIn("common_equity_health", result)
        self.assertIn("portfolio_allocation_context", result)
        self.assertEqual(
            result["portfolio_allocation_context"]["allocation_destination"],
            "SUMMER",
        )
        self.assertEqual(result["portfolio_allocation_context"]["action_output"], "NONE")
        self.assertEqual(result["authority"]["external_action_authority"], "NONE")

    def test_gpt_bridge_receives_compact_context(self):
        p = bridge_pack(pack(evidence_hash="portfolio-context", requested=True))
        p["common_equity_health"] = {
            "schema_version": "CRT_COMMON_EQUITY_HEALTH_V0.1",
            "state": "AVAILABLE",
            "assets": {
                "MSTR": {
                    "net_residual_value_per_diluted_share": 100.0,
                    "net_residual_value_per_diluted_share_change_pct": 0.05,
                    "btc_per_diluted_share": 0.003,
                    "btc_per_diluted_share_change_pct": 0.03,
                    "diluted_share_change": 1.0,
                    "senior_claim_change_usd": 0.0,
                    "annual_carry_change_usd": 0.0,
                    "liquidity_change_usd": 10.0,
                    "cash_coverage_context": {"carry_coverage_years": 2.0},
                    "capital_conversion_evidence": [],
                    "health_direction": "IMPROVING",
                    "blockers": [],
                },
                "ASST": {
                    "net_residual_value_per_diluted_share": 50.0,
                    "net_residual_value_per_diluted_share_change_pct": 0.0,
                    "btc_per_diluted_share": 0.001,
                    "btc_per_diluted_share_change_pct": 0.0,
                    "diluted_share_change": 0.0,
                    "senior_claim_change_usd": 0.0,
                    "annual_carry_change_usd": 0.0,
                    "liquidity_change_usd": 0.0,
                    "cash_coverage_context": {"carry_coverage_years": 1.5},
                    "capital_conversion_evidence": [],
                    "health_direction": "STABLE",
                    "blockers": [],
                },
            },
            "action_output": "NONE",
        }
        p["portfolio_allocation_context"] = {
            "schema_version": "CRT_PORTFOLIO_ALLOCATION_CONTEXT_V0.1",
            "state": "READY_FOR_ANALYST",
            "season_source": "LABELED_ANALYST_HYPOTHESIS",
            "season_posture": "SPRING",
            "allocation_destination": "SUMMER",
            "deployment_phase": "REINFORCEMENT",
            "cash_target_range": [5.0, 7.0],
            "fixed_income_target_pct": 60.0,
            "growth_target_pct": 40.0,
            "mstr_growth_base_pct": 55.0,
            "asst_growth_base_pct": 45.0,
            "mstr_health": "IMPROVING",
            "asst_health": "STABLE",
            "health_tilt_pct": 5.0,
            "health_tilt_reason": "MSTR_RELATIVE_HEALTH_TILT",
            "valuation_constraint": {"MSTR": "ALLOW_TILT", "ASST": "ALLOW_TILT"},
            "suggested_mstr_pct": 60.0,
            "suggested_asst_pct": 40.0,
            "side_job": {
                "state": "SKIP",
                "fixed_income_carrier": "SATA",
                "return_destination": "SATA",
                "side_job_eligibility": "SKIP",
                "action_output": "NONE",
            },
            "blockers": [],
            "action_output": "NONE",
        }
        with tempfile.TemporaryDirectory() as folder:
            handoff = run_gpt_handoff_gate(
                p,
                build_plain_language_notice(p),
                ledger_path=Path(folder) / "ledger",
            )
            bridge = build_minimized_bridge_payload(p, handoff)
        market = bridge["market_context"]
        self.assertIn("common_equity_health", market)
        self.assertIn("portfolio_allocation_context", market)
        self.assertEqual(
            market["portfolio_allocation_context"]["allocation_destination"],
            "SUMMER",
        )
        self.assertEqual(bridge["authority"]["action_output"], "NONE")


    def test_btc_long_horizon_context_reaches_gpt_bridge_without_action_authority(
        self,
    ):
        p = bridge_pack(
            pack(
                evidence_hash=(
                    "btc-long-horizon"
                ),
                requested=True,
            )
        )

        p[
            "btc_long_horizon_context"
        ] = {
            "schema_version": (
                "CRT_BTC_LONG_HORIZON_CONTEXT_V0.1"
            ),
            "state": "READY_FOR_ANALYST",
            "long_horizon_200wma_context": {
                "state": (
                    "READY_FOR_ANALYST"
                ),
                "latest_completed_200wma": (
                    62000.0
                ),
            },
            "cycle_drawdown_context": {
                "state": (
                    "READY_FOR_ANALYST"
                ),
            },
            "cycle_envelope_scenarios": {
                "state": (
                    "READY_FOR_ANALYST"
                ),
                "scenario_only": True,
            },
            "formal_price_target_authority": (
                "NONE"
            ),
            "action_output": "NONE",
            "external_action_authority": (
                "NONE"
            ),
        }

        with tempfile.TemporaryDirectory() as folder:
            handoff = run_gpt_handoff_gate(
                p,
                build_plain_language_notice(
                    p
                ),
                ledger_path=(
                    Path(folder)
                    / "ledger"
                ),
            )

            bridge = (
                build_minimized_bridge_payload(
                    p,
                    handoff,
                )
            )

        market = bridge[
            "market_context"
        ]

        self.assertIn(
            "btc_long_horizon_context",
            market,
        )
        self.assertEqual(
            market[
                "btc_long_horizon_context"
            ][
                "formal_price_target_authority"
            ],
            "NONE",
        )
        self.assertEqual(
            bridge[
                "authority"
            ][
                "action_output"
            ],
            "NONE",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
