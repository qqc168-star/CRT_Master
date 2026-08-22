from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

from crt_radar import btc_season_semantic_mapping as semantic


MAPPING_PATH = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1.json"
)
V110_CONTRACT_PATH = RADAR_ROOT / "CONFIG" / "V110_FORMAL_CANDIDATE_RUNTIME_V0.1.json"
EXPECTED_MAPPING_HASH = "afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a"


class BtcSeasonSemanticMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = semantic.load_mapping(MAPPING_PATH)

    def test_exact_formal_source_and_candidate_structure_validate(self):
        self.assertEqual(semantic.validate_mapping(self.mapping), [])
        self.assertEqual(semantic.validate_source_bytes(self.mapping), [])
        self.assertEqual(semantic.canonical_hash(self.mapping), EXPECTED_MAPPING_HASH)
        self.assertEqual(
            semantic.EXPECTED_MAPPING_CANONICAL_SHA256,
            EXPECTED_MAPPING_HASH,
        )
        self.assertEqual(
            self.mapping["source_contract"]["chapter_sha256"],
            "fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26",
        )
        self.assertEqual(
            self.mapping["authority"]["candidate_build"],
            "USER_APPROVED_CORRECTIVE_DELTA_2026-08-22",
        )

    def test_validation_report_is_deterministic_and_fail_closed(self):
        first = semantic.build_validation_report(self.mapping)
        second = semantic.build_validation_report(deepcopy(self.mapping))

        self.assertEqual(first, second)
        self.assertEqual(
            first["state"],
            "VALID_CORRECTED_CANDIDATE_FAIL_CLOSED",
        )
        self.assertEqual(first["mapping_errors"], [])
        self.assertFalse(first["runtime_binding_ready"])
        self.assertFalse(first["machine_may_determine_btc_season"])
        self.assertIsNone(first["season"])
        self.assertEqual(first["formal_model"], "NOT_APPROVED")
        self.assertEqual(first["production"], "NOT_APPROVED")
        self.assertEqual(first["action_output"], "NONE")
        self.assertEqual(first["external_action_authority"], "NONE")
        self.assertFalse(first["external_action_performed"])
        self.assertEqual(len(first["mapping_hash"]), 64)
        self.assertEqual(len(first["validation_report_hash"]), 64)

    def test_formal_state_catalog_and_declared_topology_are_exact(self):
        actual_states = [row["state_id"] for row in self.mapping["state_catalog"]]
        self.assertEqual(
            actual_states,
            [
                "SE-WI",
                "SE-WI-SPC",
                "SE-SP",
                "SE-SP-SUC",
                "SE-SU",
                "SE-SU-AUC",
                "SE-AU",
                "SE-AU-WTC",
                "SE-X",
            ],
        )

        edges = {
            row["edge_id"]: (
                row["from_state"],
                row["to_state"],
                row["phase"],
            )
            for row in self.mapping["declared_edges"]
        }
        self.assertEqual(
            edges["WI_TO_WI_SPC"],
            ("SE-WI", "SE-WI-SPC", "CANDIDATE_FORMATION"),
        )
        self.assertEqual(
            edges["WI_SPC_TO_SP"],
            ("SE-WI-SPC", "SE-SP", "CANDIDATE_CONFIRMATION"),
        )
        self.assertEqual(
            edges["WI_SPC_TO_WI"],
            ("SE-WI-SPC", "SE-WI", "CANDIDATE_FAILURE"),
        )
        self.assertEqual(
            edges["SP_TO_WI_REVIEWED_ROLLBACK"],
            (
                "SE-SP",
                "SE-WI",
                "CONFIRMED_STATE_ROLLBACK_AFTER_REVIEW",
            ),
        )
        self.assertEqual(
            {
                row["qualifier_id"]: row["kind"]
                for row in self.mapping["output_qualifiers"]
            },
            {
                "SEASON_UNDER_REVIEW": "CONFIRMED_STATE_REVIEW_FLAG",
                "CANDIDATE_FAILED": "CANDIDATE_FAILURE_RESULT",
                "DATA_INCOMPLETE": "SE_X_REASON",
                "DATA_CONFLICT": "SE_X_REASON",
            },
        )

    def test_candidate_confirmation_hysteresis_is_preserved_symbolically(self):
        invariants = {
            row["invariant_id"] for row in self.mapping["global_invariants"]
        }
        self.assertIn(
            "INV_CANDIDATE_AND_CONFIRMATION_REQUIRE_DIFFERENT_EVENTS",
            invariants,
        )
        self.assertIn(
            "INV_CANDIDATE_DOES_NOT_AUTHORIZE_FULL_EXPOSURE_SWITCH",
            invariants,
        )
        self.assertIn(
            "INV_CONFIRMATION_REQUIRES_INDEPENDENT_LATER_VALIDATION",
            invariants,
        )
        self.assertIn(
            "INV_CONFIRMED_SEASON_THREAT_REQUIRES_REVIEW_BEFORE_ROLLBACK",
            invariants,
        )
        self.assertIn(
            "INV_DATA_INCOMPLETE_OR_CONFLICT_OUTPUTS_SE_X",
            invariants,
        )

        predicates = {
            row["predicate_id"]: row
            for row in self.mapping["symbolic_predicate_contracts"]
        }
        candidate = predicates["PRED_WI_TO_WI_SPC_VALUE_SUPPORTED"]
        confirmation = predicates["PRED_WI_SPC_TO_SP_CONFIRMATION"]
        rollback = predicates["PRED_SP_TO_WI_REVIEWED_ROLLBACK"]
        self.assertIn("C3", candidate["required_symbols"])
        self.assertIn("S2_OR_S3", candidate["required_symbols"])
        self.assertIn("E2_OR_E3", candidate["required_symbols"])
        self.assertIn(
            "INDEPENDENT_LATER_VALIDATION_COMPLETE",
            confirmation["required_symbols"],
        )
        self.assertIn("S3", confirmation["required_symbols"])
        self.assertIn("E3", confirmation["required_symbols"])
        self.assertIn("SEASON_UNDER_REVIEW_ENTERED", rollback["required_symbols"])
        self.assertTrue(
            all(
                row["status"] == "SYMBOLIC_ONLY_NOT_RUNTIME_BOUND"
                for row in predicates.values()
            )
        )

    def test_value_supported_and_high_level_base_routes_are_not_collapsed(self):
        predicates = {
            row["predicate_id"]: row
            for row in self.mapping["symbolic_predicate_contracts"]
        }
        value_supported = predicates["PRED_WI_TO_WI_SPC_VALUE_SUPPORTED"]
        high_level_base = predicates["PRED_WI_TO_WI_SPC_HIGH_LEVEL_BASE"]

        self.assertEqual(value_supported["edge_id"], "WI_TO_WI_SPC")
        self.assertEqual(high_level_base["edge_id"], "WI_TO_WI_SPC")
        self.assertIn("VALUE_STATE_V1_TO_V5", value_supported["required_symbols"])
        self.assertIn("S2_OR_S3", value_supported["required_symbols"])
        self.assertIn("E2_OR_E3", value_supported["required_symbols"])

        strict_symbols = set(high_level_base["required_symbols"])
        self.assertIn("VALUE_STATE_V0", strict_symbols)
        self.assertIn("S3", strict_symbols)
        self.assertIn("E3", strict_symbols)
        self.assertNotIn("S2_OR_S3", strict_symbols)
        self.assertNotIn("E2_OR_E3", strict_symbols)
        self.assertIn(
            "SPOT_VOLUME_CVD_AND_INSTITUTIONAL_SPOT_FLOW_PERSISTENT_ACROSS_WINDOWS",
            strict_symbols,
        )
        self.assertIn(
            "LEVERAGE_EXPANSION_NOT_AHEAD_OF_SPOT_DEMAND",
            strict_symbols,
        )
        self.assertIn(
            "FOLLOW_UP_WEEKLY_VALIDATION_OR_SUCCESSFUL_RETEST_COMPLETE",
            strict_symbols,
        )

    def test_macro_structure_and_output_contracts_are_explicit_and_non_runtime(self):
        macro = {
            row["overlay_state_id"]: row
            for row in self.mapping["macro_overlay_catalog"]
        }
        self.assertEqual(set(macro), {"M+", "M0", "M-", "MX"})
        self.assertTrue(all(row["may_declare_season"] is False for row in macro.values()))
        self.assertEqual(macro["MX"]["formal_effect"], "PAUSE_FORMAL_TRANSITION")

        structure_rules = {
            row["rule_id"]: row for row in self.mapping["symbolic_structure_rules"]
        }
        self.assertEqual(
            set(structure_rules),
            {"RULE_BREAKOUT", "RULE_HOLD", "RULE_RETEST", "RULE_DEMAND_CONFIRMATION"},
        )
        self.assertIn(
            "DERIVATIVES_NOT_SOLE_ENGINE",
            structure_rules["RULE_DEMAND_CONFIRMATION"]["required_symbols"],
        )

        output = self.mapping["formal_output_contract"]
        self.assertEqual(output["status"], "SCHEMA_ONLY_NOT_RUNTIME_BOUND")
        self.assertEqual(len(output["required_fields"]), 13)
        self.assertIn("chapter_8_action_interface", output["required_fields"])
        self.assertEqual(output["action_interface_authority"], "NONE")

    def test_calendar_and_data_quality_fail_closed_rules_are_explicit(self):
        invariants = {
            row["invariant_id"] for row in self.mapping["global_invariants"]
        }
        self.assertIn("INV_CALENDAR_CANNOT_TRIGGER_SEASON", invariants)
        self.assertIn(
            "INV_FIXED_PRICE_CANNOT_BE_PERMANENT_TRANSITION_THRESHOLD",
            invariants,
        )
        self.assertIn(
            "INV_HIGH_LEVEL_BASE_REQUIRES_STRICTER_ROUTE_GATES",
            invariants,
        )
        self.assertIn(
            "INV_E2_ONLY_ALLOWS_WINTER_TO_SPRING_CANDIDATE",
            invariants,
        )
        self.assertIn(
            "INV_UNTOUCHED_REALIZED_PRICE_OR_CVDD_IS_NOT_AUTOMATIC_VETO",
            invariants,
        )

        rules = {row["rule_id"]: row for row in self.mapping["data_quality_rules"]}
        self.assertEqual(set(rules), semantic.EXPECTED_DATA_QUALITY_RULE_IDS)
        self.assertTrue(
            all(row["effect"] == "BLOCK_FORMAL_TRANSITION" for row in rules.values())
        )
        self.assertIn(
            "DQ_SINGLE_DAY_SINGLE_VENUE_OR_INTRADAY_SIGNAL_BLOCK",
            rules,
        )

    def test_route_or_coverage_regression_invalidates_corrected_candidate(self):
        changed = deepcopy(self.mapping)
        predicates = {
            row["predicate_id"]: row
            for row in changed["symbolic_predicate_contracts"]
        }
        predicates["PRED_WI_TO_WI_SPC_HIGH_LEVEL_BASE"][
            "required_symbols"
        ].remove("E3")
        changed["macro_overlay_catalog"] = changed["macro_overlay_catalog"][:-1]
        changed["formal_output_contract"]["required_fields"] = changed[
            "formal_output_contract"
        ]["required_fields"][:-1]

        errors = semantic.validate_mapping(changed)
        self.assertIn(
            "PRED_WI_TO_WI_SPC_HIGH_LEVEL_BASE symbolic requirements changed",
            errors,
        )
        self.assertIn("formal macro overlay catalog changed", errors)
        self.assertIn("formal Season output contract changed", errors)

    def test_all_real_semantic_gaps_remain_explicit_blockers(self):
        expected = semantic.EXPECTED_UNMAPPED_IDS
        rows = self.mapping["unmapped_requirements"]
        self.assertEqual({row["requirement_id"] for row in rows}, expected)
        self.assertTrue(all(row["status"] == "UNMAPPED_BLOCKED" for row in rows))
        self.assertTrue(all(row["research_delta_may_fill"] is False for row in rows))

        report = semantic.build_validation_report(self.mapping)
        self.assertEqual(set(report["unmapped_requirements"]), expected)
        for requirement_id in expected:
            self.assertIn(f"UNMAPPED:{requirement_id}", report["blocked_reasons"])
        self.assertEqual(
            set(report["approval_gates"]),
            {"AG_EXACT_MAPPING_HASH", "AG_RUNTIME_PROMOTION"},
        )
        self.assertIn(
            "APPROVAL_GATE:AG_EXACT_MAPPING_HASH",
            report["blocked_reasons"],
        )
        self.assertIn(
            "APPROVAL_GATE:AG_RUNTIME_PROMOTION",
            report["blocked_reasons"],
        )

    def test_research_delta_has_no_semantic_authority(self):
        firewall = self.mapping["research_firewall"]
        self.assertEqual(firewall["research_delta_authority"], "NONE")
        for key, value in firewall.items():
            if key == "research_delta_authority":
                continue
            self.assertIs(value, False, key)
        self.assertTrue(
            all(
                gate["research_delta_may_approve"] is False
                for gate in self.mapping["approval_gates"]
            )
        )
        serialized = json.dumps(self.mapping, ensure_ascii=False)
        self.assertNotIn("CRT_SEASON_ROUTER_RESEARCH_DELTA_20260822.md", serialized)

    def test_authority_or_formal_constant_drift_invalidates_candidate(self):
        changed = deepcopy(self.mapping)
        changed["authority"]["runtime_binding"] = "APPROVED"
        changed["runtime_boundary"]["may_emit_season"] = True
        changed["inherited_formal_constants"]["layer_weights_percent"]["L1"] = 21
        changed["inherited_formal_constants"]["light_thresholds"][0] = -61

        errors = semantic.validate_mapping(changed)
        self.assertIn("candidate authority boundary changed", errors)
        self.assertIn("runtime fail-closed boundary changed", errors)
        self.assertIn("inherited formal constants changed", errors)

        report = semantic.build_validation_report(changed)
        self.assertEqual(
            report["state"],
            "INVALID_CORRECTED_CANDIDATE_FAIL_CLOSED",
        )
        self.assertFalse(report["runtime_binding_ready"])
        self.assertIsNone(report["season"])

    def test_topology_or_unmapped_blocker_removal_invalidates_candidate(self):
        changed = deepcopy(self.mapping)
        changed["declared_edges"] = changed["declared_edges"][:-1]
        changed["unmapped_requirements"] = changed["unmapped_requirements"][:-1]
        errors = semantic.validate_mapping(changed)
        self.assertIn("declared transition topology changed", errors)
        self.assertIn("unmapped blocker set changed", errors)

    def test_source_byte_tampering_fails_closed(self):
        source = self.mapping["source_contract"]
        artifact = RADAR_ROOT / source["artifact_path"]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            copied = temp_root / source["artifact_path"]
            copied.parent.mkdir(parents=True)
            shutil.copyfile(artifact, copied)
            payload = bytearray(copied.read_bytes())
            payload[-1] ^= 1
            copied.write_bytes(payload)
            errors = semantic.validate_source_bytes(
                self.mapping,
                radar_root=temp_root,
            )
        self.assertIn("formal source archive hash mismatch", errors)

    def test_current_runtime_is_unchanged_and_does_not_import_candidate(self):
        runtime = json.loads(V110_CONTRACT_PATH.read_text(encoding="utf-8"))
        router = runtime["season_router"]
        self.assertEqual(
            router["status"],
            "SPEC_NOT_RECOVERED_CANDIDATE_FAIL_CLOSED",
        )
        self.assertFalse(router["score_may_determine_btc_season"])
        self.assertEqual(
            router["blocked_reason"],
            "V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED",
        )

        importing_files = []
        for path in sorted((RADAR_ROOT / "src" / "crt_radar").glob("*.py")):
            if path.name == "btc_season_semantic_mapping.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "btc_season_semantic_mapping" in text:
                importing_files.append(path.name)
        self.assertEqual(importing_files, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
