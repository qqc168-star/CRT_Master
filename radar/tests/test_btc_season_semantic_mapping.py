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
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.json"
)
V110_CONTRACT_PATH = RADAR_ROOT / "CONFIG" / "V110_FORMAL_CANDIDATE_RUNTIME_V0.1.json"
EXPECTED_MAPPING_HASH = "9ddfa4137fff446403bca922274b6c95be27bd55b91db735745ba79e4948b965"


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
            "USER_APPROVED_2026-08-22",
        )

    def test_validation_report_is_deterministic_and_fail_closed(self):
        first = semantic.build_validation_report(self.mapping)
        second = semantic.build_validation_report(deepcopy(self.mapping))

        self.assertEqual(first, second)
        self.assertEqual(first["state"], "VALID_CANDIDATE_FAIL_CLOSED")
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
        candidate = predicates["PRED_WI_TO_WI_SPC_STANDARD"]
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
        self.assertIn("EXACT_MAPPING_HASH_NOT_APPROVED", report["blocked_reasons"])
        self.assertIn("FORMAL_RUNTIME_BINDING_NOT_APPROVED", report["blocked_reasons"])

    def test_research_delta_has_no_semantic_authority(self):
        firewall = self.mapping["research_firewall"]
        self.assertEqual(firewall["research_delta_authority"], "NONE")
        for key, value in firewall.items():
            if key == "research_delta_authority":
                continue
            self.assertIs(value, False, key)
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
        self.assertEqual(report["state"], "INVALID_CANDIDATE_FAIL_CLOSED")
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
