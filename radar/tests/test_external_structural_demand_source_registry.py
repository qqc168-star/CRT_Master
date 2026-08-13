from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    ROOT / "research" / "CRT_EXTERNAL_STRUCTURAL_DEMAND_SOURCE_REGISTRY_V0.1.json"
)


class ExternalStructuralDemandSourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.sources = {
            item["source_id"]: item for item in cls.registry["sources"]
        }

    def test_registry_reuses_external_structural_demand_contract(self):
        self.assertEqual(
            self.registry["contract_id"],
            "CRT-EXTERNAL-STRUCTURAL-DEMAND-EVIDENCE-V0.1",
        )
        self.assertEqual(self.registry["status"], "SOURCE_PROOF_PARTIAL_READY")

    def test_btc_primary_source_is_glassnode_and_farside_is_non_blocking(self):
        glassnode = self.sources["GLASSNODE_US_SPOT_BTC_ETF"]
        farside = self.sources["FARSIDE_US_BTC_ETF_FLOW"]

        self.assertEqual(glassnode["role"], "PRIMARY_PROCESSED_SOURCE")
        self.assertEqual(glassnode["state"], "READY_CANDIDATE")
        self.assertTrue(glassnode["local_transport_proven"])

        self.assertEqual(farside["role"], "NON_BLOCKING_CROSS_CHECK")
        self.assertEqual(farside["state"], "LOCAL_FETCH_BLOCKED")
        self.assertFalse(farside["local_transport_proven"])

    def test_strc_stxt_identity_is_proven(self):
        stxt = self.sources["STRIVE_STXT"]

        self.assertEqual(stxt["state"], "READY_CANDIDATE")
        self.assertEqual(stxt["security_identity"]["cusip"], "594972853")
        self.assertTrue(stxt["identity_proven"])
        self.assertTrue(stxt["local_transport_proven"])

    def test_strc_partial_and_blocked_sources_fail_closed(self):
        pff = self.sources["ISHARES_PFF"]
        pfxf = self.sources["VANECK_PFXF"]

        self.assertEqual(pff["state"], "PARTIAL_IDENTITY_LOCK_REQUIRED")
        self.assertFalse(pff["identity_proven_on_local_csv"])

        self.assertEqual(pfxf["state"], "BLOCKED_REDIRECT_LOOP")
        self.assertFalse(pfxf["local_transport_proven"])
        self.assertEqual(pfxf["metrics"], [])

    def test_coverage_and_governance_remain_non_actionable(self):
        self.assertEqual(self.registry["coverage"]["btc"], "PARTIAL")
        self.assertEqual(self.registry["coverage"]["strc"], "PARTIAL")

        governance = self.registry["governance"]
        self.assertIsNone(governance["formal_score"])
        self.assertIsNone(governance["formal_threshold"])
        self.assertEqual(governance["action_output"], "NONE")
        self.assertEqual(governance["production"], "NOT_APPROVED")
        self.assertEqual(governance["external_action_authority"], "NONE")


if __name__ == "__main__":
    unittest.main()