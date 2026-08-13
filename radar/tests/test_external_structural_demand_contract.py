from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "research" / "CRT_EXTERNAL_STRUCTURAL_DEMAND_EVIDENCE_V0.1.json"


class ExternalStructuralDemandContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_governance_stays_non_weighted_and_non_actionable(self):
        governance = self.contract["governance"]
        self.assertEqual(governance["evidence_mode"], "NON_WEIGHTED_ASSET_RISK_EVIDENCE")
        self.assertFalse(governance["new_six_layer"])
        self.assertFalse(governance["new_top_level_evidence_pack_section"])
        self.assertIsNone(governance["formal_score"])
        self.assertIsNone(governance["formal_thresholds"])
        self.assertEqual(governance["action_output"], "NONE")
        self.assertEqual(governance["production"], "NOT_APPROVED")
        self.assertEqual(governance["external_action_authority"], "NONE")


    def test_horizons_reuse_current_crt_change_engine_semantics(self):
        alignment = self.contract["horizon_alignment"]
        self.assertEqual(alignment["canonical_crt_horizons"], ["1D", "7D", "30D"])
        self.assertFalse(alignment["separate_5d_20d_engine"])

    def test_btc_uses_mature_processed_sources_and_locked_horizons(self):
        btc = self.contract["btc"]
        self.assertTrue(btc["source_policy"]["processed_research_sources_allowed"])
        self.assertFalse(btc["source_policy"]["issuer_by_issuer_daily_rebuild_required"])
        metrics = {item["metric_id"]: item for item in btc["core_evidence"]}
        self.assertEqual(metrics["BTC_ETF_NET_FLOW_USD"]["horizons"], ["1D", "7D", "30D"])
        self.assertEqual(metrics["BTC_ETF_BALANCE_BTC"]["delta_horizons"], ["7D", "30D"])
        self.assertEqual(metrics["BTC_ETF_FLOW_BREADTH"]["horizons"], ["1D"])
        self.assertEqual(metrics["BTC_PRICE_RETURN"]["formal_state_until_market_lock"], "BLOCKED")

    def test_btc_institutional_adoption_is_slow_not_daily(self):
        slow = self.contract["btc"]["slow_evidence"]
        self.assertEqual(len(slow), 1)
        self.assertEqual(slow[0]["metric_id"], "BTC_ETF_INSTITUTIONAL_ADOPTION")
        self.assertEqual(slow[0]["cadence"], "QUARTERLY")
        self.assertFalse(slow[0]["required_daily"])

    def test_strc_holder_universe_is_dynamic_not_three_funds(self):
        policy = self.contract["strc"]["holder_universe_policy"]
        self.assertTrue(policy["dynamic_universe"])
        self.assertFalse(policy["fixed_three_fund_universe"])
        self.assertTrue(policy["ticker_only_identity_forbidden"])
        self.assertTrue(policy["inactive_holder_history_retained"])

    def test_strc_core_stays_small_and_reuses_issuer_overlay(self):
        strc = self.contract["strc"]
        metrics = {item["metric_id"]: item for item in strc["core_evidence"]}
        self.assertEqual(
            set(metrics),
            {
                "STRC_VERIFIED_EXTERNAL_FUND_HOLDINGS_SHARES",
                "STRC_HOLDER_BREADTH",
                "STRC_PRICE_RETURN",
            },
        )
        self.assertEqual(metrics["STRC_VERIFIED_EXTERNAL_FUND_HOLDINGS_SHARES"]["delta_horizons"], ["7D", "30D"])
        self.assertEqual(metrics["STRC_HOLDER_BREADTH"]["horizons"], ["7D", "30D"])
        self.assertEqual(metrics["STRC_PRICE_RETURN"]["formal_state_until_market_lock"], "BLOCKED")
        issuer = strc["issuer_context"]
        self.assertEqual(issuer["reuse_overlay_id"], "CRT-ISSUER-001")
        self.assertTrue(issuer["duplicate_repurchase_system_forbidden"])

    def test_evidence_pack_mapping_reuses_existing_sections(self):
        mapping = self.contract["evidence_pack_mapping"]
        self.assertEqual(mapping["verified_stock_flow_breadth_facts"], "asset_facts.items")
        self.assertEqual(mapping["issuer_repurchase_and_other_issuer_actions"], "decision_relevant_events.items")
        self.assertEqual(
            mapping["unresolved_source_freshness_coverage_identity_horizon_or_market_window"],
            "blockers.items",
        )
        self.assertFalse(mapping["new_top_level_section"])

    def test_automation_cannot_emit_gpt_judgments(self):
        judgments = set(self.contract["gpt_only_judgments"])
        self.assertTrue(
            {
                "MARKET_HANDOFF",
                "ISSUER_SUPPORT_DEPENDENCY",
                "ASSET_ROLE",
                "CAPITAL_STRATEGY",
            }.issubset(judgments)
        )
        non_goals = set(self.contract["explicit_non_goals"])
        self.assertIn("NO_BTC_ETF_SCORE", non_goals)
        self.assertIn("NO_STRC_ETF_SCORE", non_goals)
        self.assertIn("NO_NEW_CRT_LAYER", non_goals)
        self.assertIn("NO_CONTINUATION_OF_SUPERSEDED_STRC_SHADOW_PATCH_V0_2", non_goals)

    def test_missing_and_empty_semantics_fail_closed(self):
        rules = self.contract["common_evidence_rules"]
        self.assertIn("BLOCKS", rules["missing_rule"])
        self.assertIn("EMPTY_IS_NOT_ZERO", rules["empty_rule"])
        self.assertIn("market", rules["market_response_lock"].lower())


    def test_precision_follows_use_and_blocking_is_claim_scoped(self):
        repo_root = ROOT.parent
        core = (repo_root / "CRT_CORE_CONTRACT.md").read_text(encoding="utf-8")
        pack_contract = (repo_root / "CRT_EVIDENCE_PACK_CONTRACT.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("## Evidence Precision Constitution", core)
        self.assertIn("Precision follows the claim and decision use", core)
        self.assertIn("Claim-Scoped Fail-Closed Rule", core)
        self.assertIn("must not automatically invalidate independent evidence", core)
        self.assertIn("reduce claim scope or precision", core)

        self.assertIn(
            "smallest affected claim, metric, or calculation scope",
            pack_contract,
        )
        self.assertIn("tracked-basket trends remain usable", pack_contract)
        self.assertIn("`PARTIAL` means limited scope, not unusable evidence", pack_contract)

    def test_external_structural_demand_allows_proportional_time_precision(self):
        rules = self.contract["common_evidence_rules"]

        self.assertNotIn("source_as_of_ms", rules["required_metadata"])
        self.assertIn(
            "DO_NOT_INVENT_HIGHER_PRECISION",
            rules["source_time_rule"],
        )
        self.assertIn(
            "INDEPENDENT_VALID_EVIDENCE_REMAINS_VISIBLE",
            rules["claim_scoped_blocking_rule"],
        )

        tiers = rules["precision_tiers"]
        self.assertTrue(tiers["DIRECTIONAL_RESEARCH"]["tracked_basket_allowed"])
        self.assertFalse(
            tiers["DIRECTIONAL_RESEARCH"]["complete_universe_required"]
        )
        self.assertTrue(
            tiers["DETERMINISTIC_COMPARABLE"]["comparable_scope_required"]
        )
        self.assertTrue(
            tiers["FORMAL_ACTION_CRITICAL"][
                "fail_closed_if_exact_claim_prerequisites_missing"
            ]
        )


if __name__ == "__main__":
    unittest.main()
