from __future__ import annotations

import unittest

from crt_radar.mstr_asst_options_daily_snapshot import (
    build_mstr_asst_options_daily_snapshot,
)


def asset_input(asset: str, *, coverage_state: str = "LIMITED") -> dict:
    base_strike = 130.0 if asset == "MSTR" else 23.0
    return {
        "session_date": "2026-08-28",
        "aggregate_volume": {
            "call_volume": 600.0,
            "put_volume": 300.0,
            "source_state": "REALTIME",
            "observed_at_ms": 1_787_950_800_000,
        },
        "contracts": [
            {
                "expiry": "2026-09-18",
                "strike": base_strike,
                "right": "CALL",
                "volume": 100,
                "open_interest": 800,
                "implied_volatility": 0.75,
                "volume_state": "DELAYED",
                "open_interest_state": "DELAYED",
                "implied_volatility_state": "DELAYED",
                "observed_at_ms": 1_787_950_900_000,
                "oi_effective_at": "2026-08-28",
            },
            {
                "expiry": "2026-09-18",
                "strike": base_strike - 5,
                "right": "PUT",
                "volume": 60,
                "open_interest": 400,
                "implied_volatility": 0.8,
                "volume_state": "DELAYED",
                "open_interest_state": "DELAYED",
                "implied_volatility_state": "DELAYED",
                "observed_at_ms": 1_787_950_900_000,
                "oi_effective_at": "2026-08-28",
            },
        ],
        "coverage": {
            "state": coverage_state,
            "expiry_count": 1,
            "strike_min": base_strike - 5,
            "strike_max": base_strike,
        },
    }


def build(**overrides):
    inputs = {
        "MSTR": asset_input("MSTR"),
        "ASST": asset_input("ASST"),
    }
    inputs.update(overrides.pop("asset_inputs", {}))
    return build_mstr_asst_options_daily_snapshot(
        asset_inputs=inputs,
        generated_at_ms=1_787_950_900_001,
        **overrides,
    )


class OptionsDailySnapshotTests(unittest.TestCase):

    def test_computes_put_call_volume_ratio(self):
        row = build()["assets"]["MSTR"]["aggregate_volume"]
        self.assertEqual(row["put_call_volume_ratio"], 0.5)

    def test_computes_covered_oi_ratio_and_top_strikes(self):
        row = build()["assets"]["MSTR"]
        self.assertEqual(
            row["covered_open_interest"]["put_call_open_interest_ratio"],
            0.5,
        )
        self.assertEqual(row["top_call_oi_strikes"][0]["strike"], 130.0)

    def test_preserves_field_level_market_data_states(self):
        row = build()["assets"]["MSTR"]
        self.assertEqual(row["aggregate_volume"]["source_state"], "REALTIME")
        self.assertEqual(row["contracts"][0]["open_interest_state"], "DELAYED")

    def test_allows_explicitly_blocked_contract_volume(self):
        inputs = {
            "MSTR": asset_input("MSTR"),
            "ASST": asset_input("ASST"),
        }
        inputs["MSTR"]["contracts"][0]["volume"] = None
        inputs["MSTR"]["contracts"][0]["volume_state"] = "BLOCKED_NOT_AVAILABLE"
        result = build_mstr_asst_options_daily_snapshot(
            asset_inputs=inputs,
            generated_at_ms=1_787_950_900_001,
        )
        self.assertIsNone(result["assets"]["MSTR"]["contracts"][0]["volume"])

    def test_allows_explicitly_blocked_implied_volatility(self):
        inputs = {
            "MSTR": asset_input("MSTR"),
            "ASST": asset_input("ASST"),
        }
        contract = inputs["MSTR"]["contracts"][0]
        contract["implied_volatility"] = None
        contract["implied_volatility_state"] = "BLOCKED_NOT_AVAILABLE"

        result = build_mstr_asst_options_daily_snapshot(
            asset_inputs=inputs,
            generated_at_ms=1_787_950_900_001,
        )

        output = result["assets"]["MSTR"]["contracts"][0]
        self.assertIsNone(output["implied_volatility"])
        self.assertEqual(
            output["implied_volatility_state"],
            "BLOCKED_NOT_AVAILABLE",
        )

    def test_rejects_unlabelled_missing_implied_volatility(self):
        inputs = {
            "MSTR": asset_input("MSTR"),
            "ASST": asset_input("ASST"),
        }
        contract = inputs["MSTR"]["contracts"][0]
        contract["implied_volatility"] = None
        contract["implied_volatility_state"] = "DELAYED"

        with self.assertRaisesRegex(
            ValueError,
            "implied_volatility must be explicitly BLOCKED",
        ):
            build_mstr_asst_options_daily_snapshot(
                asset_inputs=inputs,
                generated_at_ms=1_787_950_900_001,
            )

    def test_still_rejects_missing_open_interest(self):
        inputs = {
            "MSTR": asset_input("MSTR"),
            "ASST": asset_input("ASST"),
        }
        inputs["MSTR"]["contracts"][0]["open_interest"] = None

        with self.assertRaisesRegex(
            ValueError,
            "open_interest must be numeric",
        ):
            build_mstr_asst_options_daily_snapshot(
                asset_inputs=inputs,
                generated_at_ms=1_787_950_900_001,
            )

    def test_limited_coverage_never_claims_full_chain(self):
        row = build()["assets"]["MSTR"]
        self.assertEqual(
            row["covered_open_interest"]["claim_scope"],
            "COVERED_CONTRACTS_ONLY",
        )

    def test_dealer_gamma_stays_blocked(self):
        row = build()["assets"]["MSTR"]["dealer_gamma_gex"]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertIn("OI_IV_ARE_INSUFFICIENT", row["reason"])

    def test_short_interest_stays_blocked(self):
        self.assertEqual(
            build()["assets"]["ASST"]["short_interest"]["state"],
            "BLOCKED",
        )

    def test_keeps_volume_and_oi_clocks_separate(self):
        result = build()
        contract = result["assets"]["MSTR"]["contracts"][0]
        self.assertIsInstance(contract["observed_at_ms"], int)
        self.assertEqual(contract["oi_effective_at"], "2026-08-28")
        self.assertIn("REMAIN_SEPARATE", result["clock_policy"])

    def test_preserves_no_external_action_authority(self):
        result = build()
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertFalse(result["external_action_performed"])
        self.assertEqual(len(result["snapshot_hash"]), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
