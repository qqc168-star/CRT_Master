from __future__ import annotations

import unittest

from crt_radar.mstr_asst_market_health import evaluate_mstr_asst_market_health


AUTHORITY = {
    "action_output": "NONE",
    "external_action_authority": "NONE",
    "external_action_performed": False,
}


def market_asset(close: float = 105.0, high: float = 108.0, rvol: float = 0.9) -> dict:
    return {
        "state": "VALID",
        "latest_complete_session": {
            "session_date": "2026-08-28",
            "close": close,
            "high": high,
        },
        "previous_complete_session": {
            "session_date": "2026-08-27",
            "close": 104.0,
            "high": 106.0,
        },
        "rvol20": rvol,
        "relative_btc": {
            "state": "VALID",
            "btc_excess_return_1d_pct": -4.0,
        },
    }


def options_asset() -> dict:
    return {
        "aggregate_volume": {"put_call_volume_ratio": 1.4},
        "covered_open_interest": {"put_call_open_interest_ratio": 1.2},
        "top_call_oi_strikes": [{"strike": 130, "open_interest": 800}],
        "top_put_oi_strikes": [{"strike": 110, "open_interest": 900}],
    }


def evaluate(
    *,
    mstr_market: dict | None = None,
    mstr_issuer: dict | None = None,
    mstr_lines: dict | None = None,
):
    market = {
        "assets": {
            "MSTR": mstr_market or market_asset(),
            "ASST": market_asset(),
        },
        **AUTHORITY,
    }
    options = {
        "assets": {"MSTR": options_asset(), "ASST": options_asset()},
        **AUTHORITY,
    }
    lines = {
        "MSTR": mstr_lines
        or {
            "source": "THREE_ARMY_COMMANDER",
            "approval_state": "APPROVED",
            "attack_line": 110,
            "first_defense": 100,
            "invalidation_line": 90,
        },
        "ASST": {
            "source": "THREE_ARMY_COMMANDER",
            "approval_state": "APPROVED",
            "attack_line": 30,
            "first_defense": 20,
            "invalidation_line": 15,
        },
    }
    issuer = {
        "MSTR": mstr_issuer
        or {
            "current_btc_per_diluted_share": 0.001,
            "previous_btc_per_diluted_share": 0.001,
        },
        "ASST": {
            "current_btc_per_diluted_share": 0.0001,
            "previous_btc_per_diluted_share": 0.0001,
        },
    }
    return evaluate_mstr_asst_market_health(
        full_day_market_intake=market,
        options_daily_snapshot=options,
        commander_lines=lines,
        issuer_btc_per_diluted_share=issuer,
        generated_at_ms=1_787_950_900_001,
    )


class MarketHealthTests(unittest.TestCase):

    def test_volume_confirmed_false_breakout_requests_reanalysis(self):
        result = evaluate(mstr_market=market_asset(close=109, high=112, rvol=1.5))
        self.assertIn("MSTR:FALSE_BREAKOUT_CONFIRMED", result["wake_reasons"])

    def test_first_defense_breach_requests_reanalysis(self):
        result = evaluate(mstr_market=market_asset(close=99, high=101, rvol=0.8))
        self.assertIn("MSTR:FIRST_DEFENSE_BREACHED", result["wake_reasons"])

    def test_tactical_invalidation_breach_requests_reanalysis(self):
        result = evaluate(mstr_market=market_asset(close=89, high=91, rvol=0.8))
        self.assertIn("MSTR:TACTICAL_INVALIDATION_BREACHED", result["wake_reasons"])

    def test_btc_per_diluted_share_decrease_requests_reanalysis(self):
        result = evaluate(
            mstr_issuer={
                "current_btc_per_diluted_share": 0.0009,
                "previous_btc_per_diluted_share": 0.001,
            }
        )
        self.assertIn(
            "MSTR:BTC_PER_DILUTED_SHARE_DECREASED",
            result["wake_reasons"],
        )

    def test_relative_btc_and_options_are_observation_only(self):
        result = evaluate()
        self.assertEqual(result["state"], "NO_WAKE")
        self.assertFalse(result["reanalysis_required"])
        self.assertIn("RELATIVE_BTC", result["observation_only_fields"])

    def test_lines_must_be_commander_approved(self):
        with self.assertRaises(ValueError):
            evaluate(
                mstr_lines={
                    "source": "MACHINE_INVENTED",
                    "approval_state": "APPROVED",
                    "attack_line": 110,
                    "first_defense": 100,
                    "invalidation_line": 90,
                }
            )

    def test_asset_specific_reason_is_preserved(self):
        result = evaluate(mstr_market=market_asset(close=99, high=101, rvol=0.8))
        self.assertEqual(result["reason"], "MSTR:FIRST_DEFENSE_BREACHED")
        self.assertTrue(result["assets"]["MSTR"]["reanalysis_required"])
        self.assertFalse(result["assets"]["ASST"]["reanalysis_required"])

    def test_preserves_no_action_and_gpt_notification_boundary(self):
        result = evaluate(mstr_market=market_asset(close=99, high=101, rvol=0.8))
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertFalse(result["external_action_performed"])
        self.assertEqual(result["notification_authority"], "GPT_JUDGMENT_REQUIRED")
        self.assertEqual(len(result["market_health_hash"]), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
