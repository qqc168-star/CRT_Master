from copy import deepcopy
import json
import unittest

from crt_radar.diluted_equity_mnav import (
    COMPONENTS, DENOMINATOR_BASIS, FORMULA_VERSION, ISSUERS, SEMANTIC_REF,
    build_diluted_equity_mnav, validate_diluted_mnav_evidence,
)


def qualified_inputs(asset="MSTR", at=1000, ratio=0.8):
    values = dict(diluted_shares=100, equity_price_usd=ratio, btc_holdings=100, btc_price_usd=1)
    evidence = {key: dict(value=value, asset_id="BTC" if key == "btc_price_usd" else asset,
        issuer_id=ISSUERS[asset], currency="USD", verification_state="VALIDATED",
        source_ref="synthetic:qualified:" + key, raw_sha256="a" * 64,
        effective_time=at, disclosure_time=at, first_seen_time=at, retrieval_time=at)
        for key, value in values.items()}
    evidence["diluted_shares"].update(basis_ref="all-approved-dilution-v1",
        dilution_scope="Synthetic complete common shares and approved dilutive instruments",
        coverage_state="COMPLETE")
    return dict(asset_id=asset, semantic_ref=SEMANTIC_REF, evidence_alignment_state="VALIDATED",
        **values, share_basis_ref="all-approved-dilution-v1", input_evidence=evidence, as_of_ms=at)


def compact_qualified_mnav(asset="MSTR", at=1000, ratio=0.8):
    raw = build_diluted_equity_mnav(**qualified_inputs(asset, at, ratio))
    return dict(diluted_mnav=raw["mnav"], source_semantic="CRT_FORMAL_DILUTED_EQUITY_MNAV",
        source_semantic_version="synthetic-v1", evidence_authority="FORMAL_ACTION_CRITICAL",
        formal_action_critical_state="AVAILABLE", formula_version=raw["formula_version"],
        denominator_basis=raw["denominator_basis"], semantic_ref=raw["semantic_ref"],
        mnav_schema_version=raw["schema_version"],
        mnav_evidence_alignment_state=raw["evidence_alignment_state"],
        share_basis_ref=raw["share_basis_ref"], mnav_input_evidence=raw["input_evidence"],
        mnav_as_of=raw["effective_time"], mnav_calculation_inputs={k:raw[k] for k in (
            *COMPONENTS, "diluted_equity_market_cap_usd", "btc_market_value_usd")})


class DilutedEquityMnavTests(unittest.TestCase):
    def test_four_components_define_the_only_formal_formula(self):
        for asset in ISSUERS:
            result = build_diluted_equity_mnav(**qualified_inputs(asset))
            self.assertEqual(result["state"], "AVAILABLE")
            self.assertAlmostEqual(result["mnav"], 0.8)
            self.assertEqual(result["diluted_equity_market_cap_usd"], 80)
            self.assertEqual(result["btc_market_value_usd"], 100)
            self.assertEqual(result["asset_nav_usd"], result["btc_market_value_usd"])
            self.assertEqual(result["formula_version"], FORMULA_VERSION)
            self.assertEqual(result["denominator_basis"], DENOMINATOR_BASIS)
            self.assertEqual(result["action_output"], "NONE")
            self.assertEqual(result["external_action_authority"], "NONE")

    def test_legacy_cap_nav_alone_cannot_establish_formal_ratio(self):
        result = build_diluted_equity_mnav(asset_id="MSTR", diluted_equity_market_cap_usd=80,
            asset_nav_usd=100, semantic_ref=SEMANTIC_REF, evidence_alignment_state="VALIDATED")
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIsNone(result["mnav"])
        self.assertIsNone(result["asset_nav_usd"])

    def test_net_asset_denominator_or_unmatched_cap_is_rejected(self):
        for field, value in (("asset_nav_usd", 90), ("asset_nav_usd", 110),
                             ("diluted_equity_market_cap_usd", 75)):
            args = qualified_inputs()
            args[field] = value
            self.assertEqual(build_diluted_equity_mnav(**args)["reason"], "MNAV_REPORTED_AGGREGATE_MISMATCH")

    def test_matching_aliases_are_checked_not_another_definition(self):
        args = qualified_inputs()
        args.update(asset_nav_usd=100, diluted_equity_market_cap_usd=80)
        self.assertEqual(build_diluted_equity_mnav(**args)["mnav"], 0.8)

    def test_missing_semantic_ref_fails_closed(self):
        args = qualified_inputs()
        args["semantic_ref"] = None
        self.assertEqual(build_diluted_equity_mnav(**args)["reason"], "FORMAL_MNAV_SEMANTIC_REF_REQUIRED")

    def test_old_semantic_ref_is_not_current_formal_approval(self):
        args = qualified_inputs()
        args["semantic_ref"] = "radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md"
        self.assertEqual(build_diluted_equity_mnav(**args)["reason"], "FORMAL_MNAV_SEMANTIC_VERSION_MISMATCH")

    def test_unvalidated_alignment_fails_closed(self):
        args = qualified_inputs()
        args["evidence_alignment_state"] = "PARTIAL"
        self.assertEqual(build_diluted_equity_mnav(**args)["reason"], "MNAV_EVIDENCE_ALIGNMENT_NOT_VALIDATED")

    def test_every_missing_or_invalid_component_is_blocked(self):
        for field in COMPONENTS:
            for value in (None, 0, -1, True, float("nan"), float("inf"), 10**1000):
                with self.subTest(field=field, value_type=type(value).__name__):
                    args = qualified_inputs()
                    args[field] = value
                    self.assertEqual(build_diluted_equity_mnav(**args)["state"], "BLOCKED")

    def test_missing_component_proof_is_blocked(self):
        for field in COMPONENTS:
            args = qualified_inputs()
            args["input_evidence"].pop(field)
            self.assertEqual(build_diluted_equity_mnav(**args)["state"], "BLOCKED")

    def test_source_hash_and_qualification_are_required(self):
        for key, value in (("source_ref", ""), ("raw_sha256", None), ("verification_state", "PARTIAL")):
            args = qualified_inputs()
            args["input_evidence"]["btc_holdings"][key] = value
            self.assertEqual(build_diluted_equity_mnav(**args)["state"], "BLOCKED")

    def test_declared_staleness_or_expiry_is_not_erased_by_validated_flag(self):
        for key, value in (("quality_state", "STALE"), ("quality_state", "PARTIAL"), ("valid_until_ms", 1000)):
            args = qualified_inputs()
            args["input_evidence"]["equity_price_usd"][key] = value
            self.assertEqual(build_diluted_equity_mnav(**args)["state"], "BLOCKED")

    def test_different_value_source_asset_or_issuer_cannot_be_bound(self):
        for key, value in (("value", 99), ("asset_id", "ASST"), ("issuer_id", ISSUERS["ASST"])):
            args = qualified_inputs()
            args["input_evidence"]["btc_holdings"][key] = value
            self.assertEqual(build_diluted_equity_mnav(**args)["state"], "BLOCKED")

    def test_usdt_is_not_implicitly_usd(self):
        args = qualified_inputs()
        args["input_evidence"]["btc_price_usd"]["currency"] = "USDT"
        self.assertEqual(build_diluted_equity_mnav(**args)["reason"], "MNAV_PRICE_CURRENCY_NOT_USD")

    def test_effective_times_must_match_without_rewriting_clocks(self):
        args = qualified_inputs()
        args["input_evidence"]["btc_holdings"]["effective_time"] = 999
        self.assertEqual(build_diluted_equity_mnav(**args)["reason"], "MNAV_COMPONENT_EFFECTIVE_TIME_MISMATCH")
        self.assertEqual(args["input_evidence"]["btc_holdings"]["effective_time"], 999)

    def test_future_or_inverted_source_clock_is_blocked(self):
        for clock, value in (("retrieval_time", 1001), ("first_seen_time", 999), ("effective_time", None)):
            args = qualified_inputs()
            args["input_evidence"]["btc_price_usd"][clock] = value
            self.assertEqual(build_diluted_equity_mnav(**args)["state"], "BLOCKED")

    def test_original_dilution_scope_is_required_and_preserved(self):
        args = qualified_inputs()
        expected = deepcopy(args["input_evidence"]["diluted_shares"])
        result = build_diluted_equity_mnav(**args)
        args["input_evidence"]["diluted_shares"]["dilution_scope"] = "changed after build"
        self.assertEqual(result["input_evidence"]["diluted_shares"], expected)
        for field, value in (("basis_ref", "another-scope"), ("dilution_scope", None), ("coverage_state", "PARTIAL")):
            args = qualified_inputs()
            args["input_evidence"]["diluted_shares"][field] = value
            self.assertEqual(build_diluted_equity_mnav(**args)["reason"], "MNAV_DILUTION_SCOPE_NOT_QUALIFIED")

    def test_receipt_revalidation_detects_tampering_not_only_ratio(self):
        original = build_diluted_equity_mnav(**qualified_inputs())
        self.assertEqual(validate_diluted_mnav_evidence(original, as_of_ms=1000)["state"], "AVAILABLE")
        for field, value in (("asset_nav_usd", 90), ("btc_market_value_usd", 90),
                             ("formula_version", "LEGACY_NAV"), ("mnav", 0.9), ("effective_time", 999)):
            row = deepcopy(original)
            row[field] = value
            self.assertEqual(validate_diluted_mnav_evidence(row, as_of_ms=1000)["state"], "BLOCKED")
        self.assertEqual(validate_diluted_mnav_evidence(original, as_of_ms=1000, asset_id="ASST")["state"], "BLOCKED")

    def test_non_growth_asset_is_rejected(self):
        args = qualified_inputs()
        args["asset_id"] = "STRC"
        with self.assertRaises(ValueError):
            build_diluted_equity_mnav(**args)

    def test_invalid_numeric_diagnostics_remain_json_safe_and_claim_blocked(self):
        args = qualified_inputs()
        args["btc_holdings"] = float("nan")
        args["input_evidence"]["btc_holdings"]["value"] = float("nan")
        result = build_diluted_equity_mnav(**args)
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIsNone(result["btc_holdings"])
        self.assertIsNone(result["mnav"])
        self.assertEqual(validate_diluted_mnav_evidence({"asset_id": []}, as_of_ms=1000)["state"], "BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
