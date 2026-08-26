from __future__ import annotations

import unittest

from crt_radar.diluted_equity_mnav import build_diluted_equity_mnav


class DilutedEquityMnavTests(unittest.TestCase):
    def test_validated_inputs_produce_ratio_without_defining_nav_composition(self):
        result = build_diluted_equity_mnav(
            asset_id="MSTR",
            diluted_equity_market_cap_usd=80.0,
            asset_nav_usd=100.0,
            semantic_ref="CRT_FORMAL_MNAV_SEMANTICS_CURRENT",
            evidence_alignment_state="VALIDATED",
        )
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertAlmostEqual(result["mnav"], 0.8)
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["external_action_authority"], "NONE")

    def test_missing_semantic_ref_fails_closed(self):
        result = build_diluted_equity_mnav(
            asset_id="ASST",
            diluted_equity_market_cap_usd=80.0,
            asset_nav_usd=100.0,
            semantic_ref=None,
            evidence_alignment_state="VALIDATED",
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "FORMAL_MNAV_SEMANTIC_REF_REQUIRED")
        self.assertIsNone(result["mnav"])

    def test_unvalidated_alignment_fails_closed(self):
        result = build_diluted_equity_mnav(
            asset_id="MSTR",
            diluted_equity_market_cap_usd=80.0,
            asset_nav_usd=100.0,
            semantic_ref="CRT_FORMAL_MNAV_SEMANTICS_CURRENT",
            evidence_alignment_state="PARTIAL",
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "MNAV_EVIDENCE_ALIGNMENT_NOT_VALIDATED")

    def test_missing_numeric_input_fails_closed(self):
        result = build_diluted_equity_mnav(
            asset_id="MSTR",
            diluted_equity_market_cap_usd=None,
            asset_nav_usd=100.0,
            semantic_ref="CRT_FORMAL_MNAV_SEMANTICS_CURRENT",
            evidence_alignment_state="VALIDATED",
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "MNAV_INPUT_MISSING")

    def test_invalid_numeric_input_is_rejected(self):
        with self.assertRaises(ValueError):
            build_diluted_equity_mnav(
                asset_id="MSTR",
                diluted_equity_market_cap_usd=80.0,
                asset_nav_usd=0.0,
                semantic_ref="CRT_FORMAL_MNAV_SEMANTICS_CURRENT",
                evidence_alignment_state="VALIDATED",
            )

    def test_non_growth_asset_is_rejected(self):
        with self.assertRaises(ValueError):
            build_diluted_equity_mnav(
                asset_id="STRC",
                diluted_equity_market_cap_usd=80.0,
                asset_nav_usd=100.0,
                semantic_ref="CRT_FORMAL_MNAV_SEMANTICS_CURRENT",
                evidence_alignment_state="VALIDATED",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)