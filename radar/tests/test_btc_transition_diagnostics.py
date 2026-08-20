from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.btc_transition_diagnostics import (
    blocked_transition_diagnostic,
    evaluate_transition_mechanisms,
    not_requested_transition_diagnostic,
)


class BtcTransitionDiagnosticsTests(unittest.TestCase):
    def test_2026_08_19_golden_replay_supports_absorption_without_bull_confirmation(self):
        summaries = {
            "impulse_window": {
                "oi_change_pct": -2.40,
            },
            "recent_60m": {
                "oi_change_pct": 1.891,
                "premium_mean_bp": -1.948,
                "spot_buy_share_pct": 56.24,
                "spot_cvd_proxy_usd": 41_600_000.0,
                "price_change_pct": 0.879,
            },
        }
        liquidation = {
            "state": "VALID",
            "time_resolution": "EVENT_WINDOW",
            "short_liquidation_usd": 142_333_169.57,
            "long_liquidation_usd": 3_187_249.39,
            "short_share_pct": 97.81,
        }

        result = evaluate_transition_mechanisms(
            summaries,
            funding_latest_bp=-1.0,
            liquidation_context=liquidation,
        )

        self.assertEqual(result["short_squeeze"], "SUPPORTED")
        self.assertEqual(result["long_fomo_rebuild"], "NOT_SUPPORTED")
        self.assertEqual(result["spot_demand_absorption"], "SUPPORTED")
        self.assertEqual(result["spot_demand_persistence"], "NOT_YET_CONFIRMED")
        self.assertEqual(result["leverage_quality"], "CONSTRUCTIVE")
        self.assertIsNone(result["machine_regime_judgment"])
        self.assertFalse(result["machine_may_confirm_bull_transition"])
        self.assertTrue(result["analyst_judgment_required"])

    def test_positive_oi_positive_premium_positive_funding_flags_long_fomo(self):
        summaries = {
            "impulse_window": {"oi_change_pct": 0.2},
            "recent_60m": {
                "oi_change_pct": 2.0,
                "premium_mean_bp": 3.0,
                "spot_buy_share_pct": 49.0,
                "spot_cvd_proxy_usd": -1_000_000.0,
            },
        }
        result = evaluate_transition_mechanisms(
            summaries,
            funding_latest_bp=2.0,
            liquidation_context=None,
        )
        self.assertEqual(result["long_fomo_rebuild"], "SUPPORTED")
        self.assertEqual(result["spot_demand_absorption"], "NOT_SUPPORTED")
        self.assertEqual(result["leverage_quality"], "CAUTION")

    def test_persistence_requires_both_half_hour_windows(self):
        summaries = {
            "impulse_window": {"oi_change_pct": -1.0},
            "recent_60m": {
                "oi_change_pct": 1.0,
                "premium_mean_bp": -1.0,
                "spot_buy_share_pct": 54.0,
                "spot_cvd_proxy_usd": 10_000_000.0,
            },
            "prior_30m": {
                "spot_buy_share_pct": 52.0,
                "spot_cvd_proxy_usd": 4_000_000.0,
            },
            "recent_30m": {
                "spot_buy_share_pct": 55.0,
                "spot_cvd_proxy_usd": 5_000_000.0,
            },
        }
        result = evaluate_transition_mechanisms(
            summaries,
            funding_latest_bp=-0.5,
            liquidation_context=None,
        )
        self.assertEqual(result["spot_demand_persistence"], "SUPPORTED")

    def test_safety_envelopes_never_emit_action_or_regime(self):
        for payload in (
            not_requested_transition_diagnostic("TEST"),
            blocked_transition_diagnostic("TEST"),
        ):
            self.assertEqual(payload["action_output"], "NONE")
            self.assertEqual(payload["external_action_authority"], "NONE")
            self.assertFalse(payload["external_action_performed"])
            self.assertIsNone(payload["machine_regime_judgment"])
            self.assertFalse(payload["machine_may_confirm_bull_transition"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
