from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.btc_bull_validation import evaluate_btc_bull_validation
from crt_radar.plain_language_notice import build_btc_transition_light


def entry_gate(
    transition_state: str,
    *,
    constructive: bool = False,
    adverse: bool = False,
) -> dict:
    return {
        "state": "READY_FOR_ANALYST",
        "reason": "TEST",
        "transition_state": transition_state,
        "quantitative": {
            "current_price_usd": 71500.0,
            "accepted_lower_by_price_closes": True,
            "accepted_upper_by_price_closes": (
                transition_state == "BULL_ACCEPTANCE_STRENGTHENED"
            ),
            "rejected_lower_by_price_closes": transition_state.startswith("BEAR_"),
            "provisional_sma200_reclaim": not transition_state.startswith("BEAR_"),
            "closed_daily_sma200_reclaim": not transition_state.startswith("BEAR_"),
        },
        "mechanism_support": {
            "constructive": constructive,
            "adverse": adverse,
            "spot_demand_absorption": (
                "SUPPORTED" if constructive else "NOT_SUPPORTED" if adverse else None
            ),
            "spot_demand_persistence": "NOT_YET_CONFIRMED",
            "leverage_quality": (
                "CONSTRUCTIVE" if constructive else "CAUTION" if adverse else None
            ),
            "long_fomo_rebuild": "NOT_SUPPORTED",
        },
    }


class BtcBullValidationTests(unittest.TestCase):
    def test_blocked_pack_forces_blocked_overlay_and_gray_light(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="BLOCKED",
            btc_entry_gate=entry_gate(
                "BULL_ACCEPTANCE_STRENGTHENED",
                constructive=True,
            ),
            transition_diagnostic=None,
            layers={},
            generated_at_ms=1,
        )

        self.assertEqual(overlay["state"], "BLOCKED")
        self.assertFalse(overlay["machine_may_confirm_bull_transition"])
        self.assertEqual(
            overlay["authority"]["formal_threshold_authority"],
            "NONE",
        )

        light = build_btc_transition_light(
            {
                "pack_state": "BLOCKED",
                "btc_bull_validation": overlay,
            }
        )

        self.assertEqual(light["color"], "GRAY")
        self.assertEqual(light["state"], "BLOCKED")

    def test_strengthened_maps_green_without_confirming_bull_market(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=entry_gate(
                "BULL_ACCEPTANCE_STRENGTHENED",
                constructive=True,
            ),
            transition_diagnostic=None,
            layers={
                "L3": {
                    "metrics": {
                        "spot_btc_etp_flow_20d_pct_aum": {
                            "value": 0.25
                        }
                    }
                }
            },
            generated_at_ms=1,
        )

        self.assertEqual(
            overlay["state"],
            "BULL_ACCEPTANCE_STRENGTHENED",
        )
        self.assertIn(
            "PRICE_ACCEPTANCE_AND_SMA200",
            overlay["supportive_checks"],
        )
        self.assertIn(
            "SPOT_BTC_ETP_FLOW",
            overlay["supportive_checks"],
        )
        self.assertFalse(overlay["machine_may_confirm_bull_transition"])
        self.assertEqual(overlay["action_output"], "NONE")

        light = build_btc_transition_light(
            {
                "pack_state": "READY_FOR_ANALYST",
                "btc_bull_validation": overlay,
            }
        )

        self.assertEqual(light["color"], "GREEN")
        self.assertEqual(
            light["state"],
            "BULL_ACCEPTANCE_STRENGTHENED",
        )
        self.assertEqual(
            light["formal_threshold_authority"],
            "NONE",
        )

    def test_developing_maps_yellow(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=entry_gate(
                "BULL_ACCEPTANCE_DEVELOPING",
                constructive=True,
            ),
            transition_diagnostic=None,
            layers={},
            generated_at_ms=1,
        )

        light = build_btc_transition_light(
            {
                "pack_state": "READY_FOR_ANALYST",
                "btc_bull_validation": overlay,
            }
        )

        self.assertEqual(light["color"], "YELLOW")

    def test_bear_rejection_strengthened_maps_red(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=entry_gate(
                "BEAR_REJECTION_STRENGTHENED",
                adverse=True,
            ),
            transition_diagnostic=None,
            layers={},
            generated_at_ms=1,
        )

        light = build_btc_transition_light(
            {
                "pack_state": "READY_FOR_ANALYST",
                "btc_bull_validation": overlay,
            }
        )

        self.assertEqual(light["color"], "RED")

    def test_future_validation_items_remain_pending(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=entry_gate(
                "BULL_ACCEPTANCE_DEVELOPING",
                constructive=True,
            ),
            transition_diagnostic=None,
            layers={},
            generated_at_ms=1,
        )

        pending = set(overlay["pending_checks"])

        self.assertIn("BREAKOUT_VOLUME_QUALITY", pending)
        self.assertIn("TIME_PRICE_OVERBALANCE", pending)
        self.assertIn("MACRO_HIGHER_LOW", pending)
        self.assertIn("BTC_RELATIVE_STRENGTH", pending)

        self.assertEqual(
            overlay["research_coordinates"]["formal_threshold_authority"],
            "NONE",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
