from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.btc_bull_validation import evaluate_btc_bull_validation
from crt_radar.plain_language_notice import build_btc_transition_light
from crt_radar.source_gate_runner import parse_price_structure


def entry_gate(
    transition_state: str,
    *,
    constructive: bool = False,
    adverse: bool = False,
    closed_loop: bool | None = None,
) -> dict:
    if closed_loop is None:
        closed_loop = transition_state == "BULL_ACCEPTANCE_STRENGTHENED"
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
        "control_transfer_validation": {
            "state": "READY_FOR_ANALYST",
            "reason": (
                "BREAKOUT_PULLBACK_HIGHER_LOW_REATTACK_LOOP_CLOSED"
                if closed_loop
                else "BREAKOUT_OBSERVED_BUT_DEFENSIVE_PULLBACK_NOT_TESTED"
            ),
            "research_state": (
                "CONTROL_TRANSFER_CANDIDATE"
                if closed_loop
                else "ATTACK_STRENGTHENED_DEFENSE_PENDING"
            ),
            "control_transfer_loop_closed": closed_loop,
            "observations": {
                "higher_low": "CONFIRMED" if closed_loop else "UNAVAILABLE",
            },
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

    def test_closed_loop_strengthened_maps_green_without_confirming_bull_market(self):
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

    def test_strengthened_without_closed_loop_is_downgraded_to_yellow(self):
        gate = entry_gate(
            "BULL_ACCEPTANCE_STRENGTHENED",
            constructive=True,
            closed_loop=False,
        )
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=gate,
            transition_diagnostic=None,
            layers={},
            generated_at_ms=1,
        )
        self.assertEqual(overlay["raw_entry_transition_state"], "BULL_ACCEPTANCE_STRENGTHENED")
        self.assertEqual(overlay["state"], "BULL_ACCEPTANCE_DEVELOPING")
        self.assertFalse(overlay["control_transfer_loop_closed"])

        light = build_btc_transition_light(
            {
                "pack_state": "READY_FOR_ANALYST",
                "btc_bull_validation": overlay,
            }
        )
        self.assertEqual(light["color"], "YELLOW")
        self.assertEqual(light["state"], "BULL_ACCEPTANCE_DEVELOPING")
        self.assertFalse(light["control_transfer_loop_closed"])

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

    def test_price_structure_derives_breakout_volume_research_metrics(self):
        start_ms = 1_700_000_000_000
        day_ms = 86_400_000
        payload = []

        for index in range(201):
            close = 10_000.0 + index
            quote_volume = 200.0 if index == 200 else 100.0
            taker_buy_quote = 120.0 if index == 200 else 50.0
            open_ms = start_ms + index * day_ms
            close_ms = open_ms + day_ms - 1

            payload.append(
                [
                    open_ms,
                    str(close - 1.0),
                    str(close + 10.0),
                    str(close - 10.0),
                    str(close),
                    "1.0",
                    close_ms,
                    str(quote_volume),
                    100,
                    "0.5",
                    str(taker_buy_quote),
                    "0",
                ]
            )

        result = parse_price_structure(payload)

        self.assertAlmostEqual(
            result["quote_volume_rvol20"],
            2.0,
            places=12,
        )
        self.assertAlmostEqual(
            result["taker_buy_quote_share_1d"],
            0.6,
            places=12,
        )
        self.assertGreater(result["cvd_20d_share"], 0.0)
        self.assertEqual(
            result["formal_composite_authority"],
            "NONE",
        )

    def test_breakout_volume_quality_supportive(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=entry_gate(
                "BULL_ACCEPTANCE_DEVELOPING",
                constructive=True,
            ),
            transition_diagnostic=None,
            layers={
                "L6": {
                    "metrics": {
                        "quote_volume_rvol20": {"value": 1.25},
                        "taker_buy_quote_share_1d": {"value": 0.58},
                        "cvd_20d_share": {"value": 0.08},
                    }
                }
            },
            generated_at_ms=1,
        )

        row = next(
            item
            for item in overlay["checks"]
            if item["check_id"] == "BREAKOUT_VOLUME_QUALITY"
        )

        self.assertEqual(row["status"], "SUPPORTIVE")
        self.assertIn(
            "BREAKOUT_VOLUME_QUALITY",
            overlay["supportive_checks"],
        )
        self.assertNotIn(
            "BREAKOUT_VOLUME_QUALITY",
            overlay["pending_checks"],
        )
        self.assertEqual(
            row["value"]["formal_threshold_authority"],
            "NONE",
        )

    def test_breakout_volume_quality_adverse(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=entry_gate(
                "TRANSITION_UNRESOLVED",
            ),
            transition_diagnostic=None,
            layers={
                "L6": {
                    "metrics": {
                        "quote_volume_rvol20": {"value": 1.30},
                        "taker_buy_quote_share_1d": {"value": 0.42},
                        "cvd_20d_share": {"value": -0.10},
                    }
                }
            },
            generated_at_ms=1,
        )

        row = next(
            item
            for item in overlay["checks"]
            if item["check_id"] == "BREAKOUT_VOLUME_QUALITY"
        )

        self.assertEqual(row["status"], "ADVERSE")
        self.assertIn(
            "BREAKOUT_VOLUME_QUALITY",
            overlay["adverse_checks"],
        )

    def test_breakout_volume_quality_mixed_when_volume_does_not_expand(self):
        overlay = evaluate_btc_bull_validation(
            pack_state="READY_FOR_ANALYST",
            btc_entry_gate=entry_gate(
                "BULL_ACCEPTANCE_DEVELOPING",
                constructive=True,
            ),
            transition_diagnostic=None,
            layers={
                "L6": {
                    "metrics": {
                        "quote_volume_rvol20": {"value": 0.85},
                        "taker_buy_quote_share_1d": {"value": 0.57},
                        "cvd_20d_share": {"value": 0.06},
                    }
                }
            },
            generated_at_ms=1,
        )

        row = next(
            item
            for item in overlay["checks"]
            if item["check_id"] == "BREAKOUT_VOLUME_QUALITY"
        )

        self.assertEqual(row["status"], "MIXED")
        self.assertIn(
            "BREAKOUT_VOLUME_QUALITY",
            overlay["mixed_checks"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
