from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.strc_strategy_review import (
    SCHEMA_VERSION,
    build_strc_strategy_review,
    load_strc_strategy_context,
    validate_strc_strategy_context,
)


def strategy_payload() -> dict:
    loaded = load_strc_strategy_context()
    if loaded.get("state") != "AVAILABLE":
        raise AssertionError(f"default strategy context unavailable: {loaded}")
    return loaded


def overlay(*, market_ready: bool = False, blocked: bool = False) -> dict:
    issuer_fact = {
        "asset_fact_id": "FACT-REPURCHASE-CASH",
        "fact_kind": "ISSUER_FACT",
        "fact_type": "REPURCHASE_CASH_CONSIDERATION",
        "value": 81_200_000.0,
        "unit": "USD",
        "quality_state": "VALID_REPORTED",
    }
    average = {
        "asset_fact_id": "CALC-REPURCHASE-AVG",
        "fact_kind": "DETERMINISTIC_CALCULATION",
        "fact_type": "REPURCHASE_AVG_PRICE",
        "value": 94.75,
        "unit": "USD_PER_SHARE",
        "quality_state": "VALID_DETERMINISTIC",
        "causal_interpretation": False,
    }
    rows = [issuer_fact, average]
    if market_ready:
        rows.append(
            {
                "asset_fact_id": "CALC-FIXED-WINDOW-RETURN",
                "fact_kind": "DETERMINISTIC_CALCULATION",
                "fact_type": "FIXED_WINDOW_RETURN",
                "value": 0.03,
                "unit": "RATIO",
                "quality_state": "VALID_DETERMINISTIC",
                "causal_interpretation": False,
            }
        )
    blocker_items = (
        [{"reason_code": "PRICE_OR_VOLUME_UNVERIFIABLE", "scope": "CALCULATION"}]
        if blocked
        else []
    )
    return {
        "asset_facts": {
            "section_state": "BLOCKED" if blocked else "READY",
            "coverage_state": "PARTIAL" if blocked else "COMPLETE",
            "items": rows,
        },
        "decision_relevant_events": {
            "section_state": "READY",
            "coverage_state": "COMPLETE",
            "items": [{"event_id": "EVENT-STRC-REPURCHASE", "event_type": "SECURITY_REPURCHASE"}],
        },
        "blockers": {
            "section_state": "BLOCKED" if blocker_items else "READY",
            "items": blocker_items,
        },
    }


class StrcStrategyReviewTests(unittest.TestCase):
    def test_default_engineering_strategy_context_loads_and_recomputes_spread(self):
        loaded = strategy_payload()
        derived = loaded["context"]["derived"]
        self.assertAlmostEqual(derived["weighted_q3_sell_price_usd"], 98.89, places=2)
        self.assertAlmostEqual(derived["weighted_q4_reentry_price_usd"], 82.10, places=2)
        self.assertAlmostEqual(derived["reference_gross_gap_usd_per_share"], 16.79, places=2)
        self.assertAlmostEqual(
            derived["max_distribution_plus_friction_budget_usd_per_share"],
            6.79,
            places=2,
        )

    def test_invalid_formal_promotion_is_rejected(self):
        loaded = strategy_payload()
        payload = deepcopy(loaded["context"])
        payload.pop("derived", None)
        payload["formal_model_status"] = "FORMAL"
        with self.assertRaises(ValueError):
            validate_strc_strategy_context(payload)

    def test_market_blocker_yields_partial_packet_not_fake_market_handoff(self):
        review = build_strc_strategy_review(strategy_payload(), overlay(blocked=True))
        self.assertEqual(review["schema_version"], SCHEMA_VERSION)
        self.assertEqual(review["state"], "PARTIAL_FOR_ANALYST")
        self.assertEqual(review["issuer_evidence"]["state"], "AVAILABLE")
        self.assertEqual(review["market_handoff_evidence"]["state"], "BLOCKED")
        self.assertEqual(review["guidepost_evaluation"]["state"], "BLOCKED")
        self.assertIn("PRICE_OR_VOLUME_UNVERIFIABLE", review["reflexivity_blocker_codes"])
        self.assertEqual(review["action_output"], "NONE")
        self.assertEqual(review["external_action_authority"], "NONE")
        self.assertEqual(review["capital_decision_authority"], "USER_ONLY")

    def test_verified_market_evidence_makes_packet_ready_for_gpt_not_trade(self):
        review = build_strc_strategy_review(strategy_payload(), overlay(market_ready=True))
        self.assertEqual(review["state"], "READY_FOR_ANALYST")
        self.assertEqual(review["market_handoff_evidence"]["state"], "AVAILABLE")
        self.assertEqual(review["guidepost_evaluation"]["state"], "READY_FOR_GPT_JUDGMENT")
        self.assertFalse(review["guidepost_evaluation"]["automatic_trade_signal"])
        self.assertEqual(review["action_output"], "NONE")

    def test_missing_strategy_context_fails_closed(self):
        review = build_strc_strategy_review(
            {"state": "BLOCKED", "reason": "STRC_STRATEGY_CONTEXT_MISSING"},
            overlay(),
        )
        self.assertEqual(review["state"], "BLOCKED")
        self.assertEqual(review["reason"], "STRC_STRATEGY_CONTEXT_MISSING")
        self.assertTrue(review["analyst_judgment_required"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
