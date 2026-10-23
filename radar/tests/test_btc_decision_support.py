from __future__ import annotations

import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.btc_decision_support import (
    build_signal_role_classification,
    evaluate_btc_entry_gate,
    load_btc_entry_gate_context,
)
from crt_radar.btc_transition_diagnostics import evaluate_transition_mechanisms


class BtcDecisionSupportTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "state": "AVAILABLE",
            "context": {
                "schema_version": "CRT_BTC_ENTRY_GATE_RESEARCH_CONTEXT_V0.1",
                "lower_usd": 69000.0,
                "upper_usd": 71000.0,
                "valid_until_ms": 1789862400000,
                "formal_threshold_authority": "NONE",
                "external_action_authority": "NONE",
            },
        }
        self.transition = {
            "state": "READY_FOR_ANALYST",
            "mechanism_findings": {
                "short_squeeze": "SUPPORTED",
                "long_fomo_rebuild": "NOT_SUPPORTED",
                "spot_demand_absorption": "SUPPORTED",
                "spot_demand_persistence": "NOT_YET_CONFIRMED",
                "leverage_quality": "CONSTRUCTIVE",
            },
        }

    def closed_loop_evidence(self):
        return {
            "schema_version": "CRT_BTC_CONTROL_TRANSFER_EVIDENCE_V0.1",
            "authority": {
                "formal_model_authority": "NONE",
                "formal_weight_authority": "NONE",
                "formal_threshold_authority": "NONE",
                "season_transition_authority": "NONE",
                "external_action_authority": "NONE",
                "external_action_performed": False,
            },
            "observations": {
                "meaningful_breakout": "CONFIRMED",
                "meaningful_pullback": "CONFIRMED",
                "higher_low": "CONFIRMED",
                "reattack": "CONFIRMED",
                "prior_control_high_break": "CONFIRMED",
                "invalidating_lower_low": "NOT_OBSERVED",
            },
        }

    def test_lower_corridor_acceptance_is_watch_not_probe(self):
        structure = {
            "current_price_usd": 69500.0,
            "last_closed_1h_usd": 69400.0,
            "last_closed_4h_usd": 69200.0,
            "last_closed_daily_usd": 69300.0,
            "sma200_closed_usd": 69000.0,
            "sma200_provisional_usd": 68950.0,
            "current_vs_sma200_provisional_pct": 0.80,
            "daily_close_vs_sma200_closed_pct": 0.43,
        }
        result = evaluate_btc_entry_gate(
            transition_diagnostic=self.transition,
            structure=structure,
            research_context=self.context,
        )
        self.assertEqual(result["transition_state"], "BULL_ACCEPTANCE_DEVELOPING")
        self.assertEqual(result["decision_eligibility"], "WATCH")
        self.assertFalse(result["machine_may_output_trade_action"])
        self.assertEqual(result["external_action_authority"], "NONE")

    def test_upper_corridor_attack_without_defense_remains_watch(self):
        structure = {
            "current_price_usd": 71500.0,
            "last_closed_1h_usd": 71300.0,
            "last_closed_4h_usd": 71150.0,
            "last_closed_daily_usd": 70500.0,
            "sma200_closed_usd": 69000.0,
            "sma200_provisional_usd": 69050.0,
            "current_vs_sma200_provisional_pct": 3.55,
            "daily_close_vs_sma200_closed_pct": 2.17,
        }
        result = evaluate_btc_entry_gate(
            transition_diagnostic=self.transition,
            structure=structure,
            research_context=self.context,
        )
        self.assertEqual(result["transition_state"], "BULL_ACCEPTANCE_DEVELOPING")
        self.assertEqual(result["decision_eligibility"], "WATCH")
        self.assertEqual(
            result["control_transfer_validation"]["state"],
            "NOT_AVAILABLE",
        )
        self.assertFalse(result["machine_may_confirm_bull_transition"])

    def test_closed_control_transfer_loop_can_be_probe_eligible(self):
        structure = {
            "current_price_usd": 71500.0,
            "last_closed_1h_usd": 71300.0,
            "last_closed_4h_usd": 71150.0,
            "last_closed_daily_usd": 70500.0,
            "sma200_closed_usd": 69000.0,
            "sma200_provisional_usd": 69050.0,
            "current_vs_sma200_provisional_pct": 3.55,
            "daily_close_vs_sma200_closed_pct": 2.17,
        }
        result = evaluate_btc_entry_gate(
            transition_diagnostic=self.transition,
            structure=structure,
            research_context=self.context,
            control_transfer_evidence=self.closed_loop_evidence(),
        )
        self.assertEqual(result["transition_state"], "BULL_ACCEPTANCE_STRENGTHENED")
        self.assertEqual(result["decision_eligibility"], "PROBE_ELIGIBLE")
        self.assertTrue(
            result["control_transfer_validation"]["control_transfer_loop_closed"]
        )
        self.assertFalse(result["machine_may_confirm_bull_transition"])

    def test_bear_rejection_strengthens_only_with_adverse_mechanism(self):
        transition = {
            "state": "READY_FOR_ANALYST",
            "mechanism_findings": {
                "long_fomo_rebuild": "SUPPORTED",
                "spot_demand_absorption": "NOT_SUPPORTED",
                "spot_demand_persistence": "NOT_YET_CONFIRMED",
                "leverage_quality": "CAUTION",
            },
        }
        structure = {
            "current_price_usd": 68000.0,
            "last_closed_1h_usd": 68200.0,
            "last_closed_4h_usd": 68500.0,
            "last_closed_daily_usd": 68800.0,
            "sma200_closed_usd": 69000.0,
            "sma200_provisional_usd": 68950.0,
            "current_vs_sma200_provisional_pct": -1.38,
            "daily_close_vs_sma200_closed_pct": -0.29,
        }
        result = evaluate_btc_entry_gate(
            transition_diagnostic=transition,
            structure=structure,
            research_context=self.context,
        )
        self.assertEqual(result["transition_state"], "BEAR_REJECTION_STRENGTHENED")
        self.assertEqual(result["decision_eligibility"], "WAIT")

    def test_missing_mechanism_never_promotes_price_only_to_probe(self):
        structure = {
            "current_price_usd": 72000.0,
            "last_closed_1h_usd": 71800.0,
            "last_closed_4h_usd": 71500.0,
            "last_closed_daily_usd": 70500.0,
            "sma200_closed_usd": 69000.0,
            "sma200_provisional_usd": 69100.0,
            "current_vs_sma200_provisional_pct": 4.20,
            "daily_close_vs_sma200_closed_pct": 2.17,
        }
        result = evaluate_btc_entry_gate(
            transition_diagnostic={"state": "NOT_REQUESTED"},
            structure=structure,
            research_context=self.context,
        )
        self.assertEqual(result["decision_eligibility"], "WAIT")
        self.assertEqual(result["transition_state"], "TRANSITION_UNRESOLVED")

    def test_roles_distinguish_leading_coincident_lagging_and_gate(self):
        roles = build_signal_role_classification(
            self.transition,
            {"current_vs_sma200_provisional_pct": 0.5},
        )["roles"]
        timing = {row["timing_role"] for row in roles}
        decision = {row["decision_role"] for row in roles}
        self.assertIn("LEADING", timing)
        self.assertIn("COINCIDENT", timing)
        self.assertIn("LAGGING", timing)
        self.assertIn("ENTRY_GATE", decision)

    def test_expired_context_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "context.json"
            path.write_text(
                """{
  "schema_version": "CRT_BTC_ENTRY_GATE_RESEARCH_CONTEXT_V0.1",
  "lower_usd": 69000,
  "upper_usd": 71000,
  "valid_until_ms": 1000,
  "formal_threshold_authority": "NONE",
  "external_action_authority": "NONE"
}""",
                encoding="utf-8",
            )
            loaded = load_btc_entry_gate_context(path, now_ms=2000)
            self.assertEqual(loaded["state"], "BLOCKED")
            self.assertEqual(loaded["reason"], "BTC_ENTRY_GATE_RESEARCH_CONTEXT_EXPIRED")

    def cvd_case(self, cvd, price):
        diagnostic = {"mechanism_findings": evaluate_transition_mechanisms(
            {"recent_60m": {
                "oi_change_pct": 1.0,
                "premium_mean_bp": -1.0,
                "spot_buy_share_pct": 55.0 if cvd > 0 else 45.0,
                "spot_cvd_proxy_usd": cvd,
            }}, funding_latest_bp=-1.0,
        )}
        structure = {
            "current_price_usd": price,
            "last_closed_1h_usd": price,
            "last_closed_4h_usd": price,
            "current_vs_sma200_provisional_pct": (price / 69000.0 - 1) * 100,
            "daily_close_vs_sma200_closed_pct": 0.0,
        }
        return diagnostic, structure

    def test_negative_cvd_with_price_holding_stays_unresolved_without_buy(self):
        diagnostic, structure = self.cvd_case(-1_000_000.0, 71500.0)
        result = evaluate_btc_entry_gate(
            transition_diagnostic=diagnostic, structure=structure,
            research_context=self.context,
        )
        self.assertEqual(result["mechanism_support"]["spot_demand_absorption"], "INCONCLUSIVE")
        self.assertFalse(result["mechanism_support"]["adverse"])
        self.assertEqual(result["transition_state"], "TRANSITION_UNRESOLVED")
        self.assertEqual(result["decision_eligibility"], "WAIT")
        self.assertEqual(result["action_output"], "NONE")

    def test_negative_cvd_with_unreclaimed_break_keeps_structural_bear_case(self):
        diagnostic, structure = self.cvd_case(-1_000_000.0, 68000.0)
        result = evaluate_btc_entry_gate(
            transition_diagnostic=diagnostic, structure=structure,
            research_context=self.context,
        )
        self.assertEqual(result["transition_state"], "BEAR_REJECTION_PLAUSIBLE")
        self.assertTrue(result["quantitative"]["rejected_lower_by_price_closes"])
        self.assertEqual(result["decision_eligibility"], "WAIT")

    def test_positive_cvd_rebound_cannot_bypass_control_transfer_validation(self):
        diagnostic, structure = self.cvd_case(1_000_000.0, 71500.0)
        failed = self.closed_loop_evidence()
        failed["observations"]["invalidating_lower_low"] = "CONFIRMED"
        for evidence in (None, failed):
            with self.subTest(evidence=evidence):
                result = evaluate_btc_entry_gate(
                    transition_diagnostic=diagnostic, structure=structure,
                    research_context=self.context, control_transfer_evidence=evidence,
                )
                self.assertEqual(result["mechanism_support"]["spot_demand_absorption"], "SUPPORTED")
                self.assertEqual(result["decision_eligibility"], "WATCH")
                self.assertFalse(result["control_transfer_validation"]["control_transfer_loop_closed"])
                self.assertFalse(result["machine_may_confirm_bull_transition"])
                self.assertEqual(result["action_output"], "NONE")

    def test_legacy_absorption_label_alone_is_not_adverse_or_rewritten(self):
        diagnostic, structure = self.cvd_case(-1_000_000.0, 68000.0)
        diagnostic["mechanism_findings"]["spot_demand_absorption"] = "NOT_SUPPORTED"
        original = deepcopy(diagnostic)
        result = evaluate_btc_entry_gate(
            transition_diagnostic=diagnostic, structure=structure,
            research_context=self.context,
        )
        self.assertFalse(result["mechanism_support"]["adverse"])
        self.assertEqual(result["transition_state"], "BEAR_REJECTION_PLAUSIBLE")
        self.assertEqual(diagnostic, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
