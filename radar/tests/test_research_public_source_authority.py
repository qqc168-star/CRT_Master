from __future__ import annotations

import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
MODULE_PATH = RESEARCH / "candidate_data.py"
MODEL_REGISTRY_PATH = RESEARCH / "CRT_SIX_LAYER_CANDIDATE_V0.1.json"
AUTHORITY_PATH = RESEARCH / "CRT_PUBLIC_SOURCE_AUTHORITY_LOCK_V0.1.json"
SOURCE_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2.json"
PROTOCOL_PATH = RESEARCH / "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2.json"

spec = importlib.util.spec_from_file_location("candidate_data_public_sources", MODULE_PATH)
candidate_data = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(candidate_data)


class ResearchPublicSourceAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_registry = json.loads(MODEL_REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
        cls.source_contract = json.loads(SOURCE_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))

    def test_public_source_authority_lock_is_valid_and_research_only(self):
        self.assertEqual(
            candidate_data.validate_public_source_authority(
                self.authority,
                self.model_registry,
            ),
            [],
        )
        self.assertEqual(self.authority["status"], "PUBLIC_RESEARCH_ROUTE_LOCKED_DATA_NOT_READY")
        self.assertEqual(self.authority["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(self.authority["authority"]["external_action_authority"], "NONE")
        self.assertFalse(self.authority["authority"]["external_action_performed"])

    def test_five_public_route_decisions_are_explicit(self):
        decisions = self.authority["decisions"]
        self.assertEqual(
            set(decisions),
            {
                "STABLECOIN_POINT_IN_TIME_UNIVERSE",
                "US_SPOT_BTC_ETP_POINT_IN_TIME",
                "BINANCE_BTCUSDT_CONTRACT_MULTIPLIER",
                "BTC_SPOT_COMPOSITE_OHLCV",
                "BTC_SPOT_AGGRESSOR_DAILY",
            },
        )
        self.assertEqual(
            decisions["BINANCE_BTCUSDT_CONTRACT_MULTIPLIER"]["decision_state"],
            "ELIMINATED_BY_OFFICIAL_NOTIONAL_FIELD",
        )
        for source_id in (
            "STABLECOIN_POINT_IN_TIME_UNIVERSE",
            "US_SPOT_BTC_ETP_POINT_IN_TIME",
            "BTC_SPOT_COMPOSITE_OHLCV",
            "BTC_SPOT_AGGRESSOR_DAILY",
        ):
            self.assertEqual(decisions[source_id]["decision_state"], "LOCKED_RESEARCH_SOURCE")

    def test_selected_methods_are_fail_closed_and_non_substitutable(self):
        decisions = self.authority["decisions"]
        stablecoin = decisions["STABLECOIN_POINT_IN_TIME_UNIVERSE"]
        self.assertEqual(
            stablecoin["universe"]["members"],
            [
                {"provider_id": "1", "symbol": "USDT"},
                {"provider_id": "2", "symbol": "USDC"},
            ],
        )
        self.assertEqual(stablecoin["fallback_policy"], "NONE_BLOCK_ON_SOURCE_OR_COVERAGE_FAILURE")

        etp = decisions["US_SPOT_BTC_ETP_POINT_IN_TIME"]
        self.assertEqual(etp["calculation_authority"], "OFFICIAL_ISSUER_DAILY_SNAPSHOT")
        self.assertEqual(etp["farside_role"], "CROSS_CHECK_ONLY_NOT_CALCULATION_AUTHORITY")
        self.assertEqual(
            {
                member["ticker"]: (
                    member["membership_effective_from"],
                    member["official_product_url"],
                )
                for member in etp["universe"]["members"]
            },
            {
                ticker: (effective_from, product_url)
                for ticker, (_, effective_from, product_url) in (
                    candidate_data.EXPECTED_ETP_PRODUCT_REGISTRY.items()
                )
            },
        )
        self.assertEqual(
            etp["registry_binding"]["sec_identity_state"],
            "CIK_AND_ACCESSION_BINDING_REQUIRED_BEFORE_ACQUISITION",
        )
        self.assertEqual(
            etp["registry_binding"]["daily_snapshot_adapter_state"],
            "NOT_IMPLEMENTED_BLOCKED",
        )

        composite = decisions["BTC_SPOT_COMPOSITE_OHLCV"]
        self.assertEqual(
            [venue["venue_id"] for venue in composite["venue_universe"]],
            ["COINBASE_BTC_USD", "KRAKEN_XBT_USD", "BITSTAMP_BTC_USD"],
        )
        self.assertEqual(composite["minimum_venue_count"], 3)
        self.assertEqual(composite["aggregation"], "COORDINATE_WISE_MEDIAN_OHLC")

        aggressor = decisions["BTC_SPOT_AGGRESSOR_DAILY"]
        self.assertEqual(aggressor["symbol"], "BTCUSDT")
        self.assertEqual(aggressor["buyer_initiated_when_is_buyer_maker"], False)
        self.assertEqual(aggressor["seller_initiated_when_is_buyer_maker"], True)

    def test_v02_source_contract_binds_authority_and_removes_multiplier_source(self):
        self.assertEqual(
            candidate_data.validate_source_contract(
                self.source_contract,
                self.model_registry,
                self.authority,
            ),
            [],
        )
        self.assertEqual(self.source_contract["schema_version"], "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2")
        self.assertEqual(
            self.source_contract["public_source_authority_hash"],
            candidate_data.canonical_hash(self.authority),
        )
        sources = self.source_contract["source_contracts"]
        self.assertNotIn("BINANCE_BTCUSDT_CONTRACT_MULTIPLIER", sources)
        self.assertEqual(len(sources), 9)
        self.assertTrue(
            all(item["approval_state"] == "LOCKED_RESEARCH_INPUT" for item in sources.values())
        )
        self.assertEqual(
            sources["BINANCE_USDM_MARKET_HISTORY"]["series"],
            ["OPEN_INTEREST_NOTIONAL_USD", "FUNDING_RATE"],
        )

    def test_v02_protocol_hash_chain_and_readiness_remain_blocked_by_data(self):
        self.assertEqual(
            candidate_data.validate_walk_forward_protocol(
                self.protocol,
                self.source_contract,
                self.model_registry,
                self.authority,
            ),
            [],
        )
        result = candidate_data.assess_walk_forward_readiness(
            self.source_contract,
            self.protocol,
            dataset_manifest=None,
            public_source_authority=self.authority,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(len(result["blocked_reasons"]), 10)
        self.assertIn("POINT_IN_TIME_DATASET_MISSING", result["blocked_reasons"])
        self.assertFalse(any("APPROVAL_REQUIRED" in item for item in result["blocked_reasons"]))
        self.assertEqual(
            result["public_source_authority_hash"],
            candidate_data.canonical_hash(self.authority),
        )

    def test_oi_uses_official_notional_field_without_multiplier_parameter(self):
        observed_at_ms = 1_900_000_000_000
        as_of_ms = observed_at_ms + 1
        raw = {
            "schema_version": "CRT_CANDIDATE_RAW_INPUT_V0.2",
            "series": {
                "OPEN_INTEREST_NOTIONAL_USD": [
                    {
                        "observed_at_ms": observed_at_ms,
                        "available_at_ms": observed_at_ms,
                        "value": 5_000_000.0,
                    }
                ],
                "MARKET_CAP_USD": [
                    {
                        "observed_at_ms": observed_at_ms,
                        "available_at_ms": observed_at_ms,
                        "value": 1_000_000_000_000.0,
                    }
                ],
            },
            "tables": {},
            "parameters": {"cross_source_alignment_tolerance_ms": 300_000},
        }
        result = candidate_data.calculate_feature(
            "L4_OI_TO_MARKET_CAP",
            raw,
            as_of_ms=as_of_ms,
            source_contract=self.source_contract,
            model_registry=self.model_registry,
            public_source_authority=self.authority,
        )
        self.assertEqual(result["value"], 0.0005)

    def test_authority_and_source_hash_drift_fail_closed(self):
        changed_authority = deepcopy(self.authority)
        changed_authority["decisions"]["BTC_SPOT_COMPOSITE_OHLCV"]["minimum_venue_count"] = 2
        errors = candidate_data.validate_public_source_authority(
            changed_authority,
            self.model_registry,
        )
        self.assertIn("public source authority composite minimum_venue_count drift", errors)

        errors = candidate_data.validate_source_contract(
            self.source_contract,
            self.model_registry,
            changed_authority,
        )
        self.assertIn("source contract public_source_authority_hash mismatch", errors)

        changed_authority = deepcopy(self.authority)
        changed_authority["decisions"]["US_SPOT_BTC_ETP_POINT_IN_TIME"]["universe"][
            "members"
        ][0]["official_product_url"] = "https://example.invalid/ibit"
        errors = candidate_data.validate_public_source_authority(
            changed_authority,
            self.model_registry,
        )
        self.assertIn("public source authority ETP product registry drift", errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
