from __future__ import annotations

import hashlib
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
from crt_radar import btc_season_semantic_mapping_approval as approval


SEAL_PATH = (
    RADAR_ROOT
    / "CONFIG"
    / "BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_SEAL_V0.1.json"
)
MAPPING_PATH = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1.json"
)
V110_CONTRACT_PATH = RADAR_ROOT / "CONFIG" / "V110_FORMAL_CANDIDATE_RUNTIME_V0.1.json"
EXPECTED_MAPPING_HASH = "afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a"
EXPECTED_SEAL_HASH = "6af3c17c263df8b4434e85078e95b9d506f6efb19acb484ac39745355322f75a"
EXPECTED_REPORT_HASH = "22cfa653fae3759ea1bcfc82858c39ff74ac10a8a98f633757b8081cc9c22385"


class BtcSeasonSemanticMappingApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seal = approval.load_seal(SEAL_PATH)
        cls.mapping = semantic.load_mapping(MAPPING_PATH)

    def test_exact_external_seal_and_approved_candidate_validate(self):
        self.assertEqual(approval.canonical_hash(self.seal), EXPECTED_SEAL_HASH)
        self.assertEqual(
            approval.EXPECTED_SEAL_CANONICAL_SHA256,
            EXPECTED_SEAL_HASH,
        )
        self.assertEqual(approval.validate_approval_seal(self.seal), [])
        self.assertEqual(semantic.validate_mapping(self.mapping), [])
        self.assertEqual(semantic.validate_source_bytes(self.mapping), [])
        self.assertEqual(semantic.canonical_hash(self.mapping), EXPECTED_MAPPING_HASH)

    def test_approval_is_external_and_does_not_mutate_candidate(self):
        self.assertEqual(
            self.mapping["authority"]["exact_mapping_hash"],
            "NOT_YET_APPROVED",
        )
        exact_gate = next(
            row
            for row in self.mapping["approval_gates"]
            if row["gate_id"] == "AG_EXACT_MAPPING_HASH"
        )
        self.assertEqual(exact_gate["status"], "NOT_YET_APPROVED")
        self.assertTrue(
            self.seal["immutability_boundary"][
                "approval_record_is_external_to_candidate"
            ]
        )
        self.assertFalse(
            self.seal["immutability_boundary"]["candidate_json_modified_by_approval"]
        )
        self.assertEqual(
            self.seal["approved_artifact"]["mapping_canonical_sha256"],
            semantic.canonical_hash(self.mapping),
        )

    def test_valid_seal_closes_only_exact_hash_gate_and_stays_fail_closed(self):
        report = approval.build_approval_validation_report(self.seal, self.mapping)
        self.assertEqual(report["state"], "VALID_HASH_APPROVAL_SEAL_FAIL_CLOSED")
        self.assertEqual(report["seal_errors"], [])
        self.assertTrue(report["exact_mapping_hash_approved"])
        self.assertEqual(
            report["remaining_approval_gates"],
            ["AG_RUNTIME_PROMOTION"],
        )
        self.assertNotIn(
            "APPROVAL_GATE:AG_EXACT_MAPPING_HASH",
            report["blocked_reasons"],
        )
        self.assertIn(
            "APPROVAL_GATE:AG_RUNTIME_PROMOTION",
            report["blocked_reasons"],
        )
        self.assertEqual(len(report["remaining_unmapped_requirements"]), 14)
        self.assertEqual(len(report["blocked_reasons"]), 15)
        self.assertEqual(report["formal_model"], "NOT_APPROVED")
        self.assertFalse(report["runtime_binding_ready"])
        self.assertFalse(report["machine_may_determine_btc_season"])
        self.assertIsNone(report["season"])
        self.assertEqual(report["production"], "NOT_APPROVED")
        self.assertEqual(report["action_output"], "NONE")
        self.assertEqual(report["external_action_authority"], "NONE")

    def test_seal_and_report_hashes_are_independently_reproducible(self):
        canonical_seal = json.dumps(
            self.seal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical_seal).hexdigest(), EXPECTED_SEAL_HASH)

        first = approval.build_approval_validation_report(self.seal, self.mapping)
        second = approval.build_approval_validation_report(
            deepcopy(self.seal),
            deepcopy(self.mapping),
        )
        self.assertEqual(first, second)
        self.assertEqual(first["validation_report_hash"], EXPECTED_REPORT_HASH)

    def test_approved_artifact_or_seal_identity_tampering_fails_closed(self):
        changed = deepcopy(self.seal)
        changed["approved_artifact"]["mapping_canonical_sha256"] = "0" * 64
        errors = approval.validate_approval_seal(changed, self.mapping)
        self.assertIn("approval seal canonical hash changed", errors)
        self.assertIn("approved artifact identity changed", errors)

        report = approval.build_approval_validation_report(changed, self.mapping)
        self.assertFalse(report["exact_mapping_hash_approved"])
        self.assertIn(
            "AG_EXACT_MAPPING_HASH",
            report["remaining_approval_gates"],
        )
        self.assertFalse(report["runtime_binding_ready"])
        self.assertIsNone(report["season"])

    def test_runtime_or_research_authority_escalation_fails_closed(self):
        changed = deepcopy(self.seal)
        changed["approval_scope"]["runtime_binding"] = "APPROVED"
        changed["approval_scope"]["season_output_authority"] = "FORMAL"
        changed["gate_effect"]["remaining_approval_gates"] = []
        changed["gate_effect"]["runtime_promotion_ready"] = True
        changed["research_firewall"]["research_delta_may_approve_hash"] = True
        errors = approval.validate_approval_seal(changed, self.mapping)
        self.assertIn("approval scope or authority boundary changed", errors)
        self.assertIn("approval gate effect changed", errors)
        self.assertIn("approval research firewall changed", errors)

        report = approval.build_approval_validation_report(changed, self.mapping)
        self.assertFalse(report["exact_mapping_hash_approved"])
        self.assertEqual(report["formal_model"], "NOT_APPROVED")
        self.assertFalse(report["runtime_binding_ready"])
        self.assertEqual(report["external_action_authority"], "NONE")

    def test_mutating_the_approved_mapping_invalidates_the_seal(self):
        changed = deepcopy(self.mapping)
        route = next(
            row
            for row in changed["symbolic_predicate_contracts"]
            if row["predicate_id"] == "PRED_WI_TO_WI_SPC_HIGH_LEVEL_BASE"
        )
        route["required_symbols"][route["required_symbols"].index("E3")] = "E2_OR_E3"

        errors = approval.validate_approval_seal(self.seal, changed)
        self.assertIn("approved mapping canonical hash mismatch", errors)

        mapping_errors = semantic.validate_mapping(changed)
        self.assertIn("candidate canonical hash changed", mapping_errors)
        self.assertIn(
            "PRED_WI_TO_WI_SPC_HIGH_LEVEL_BASE symbolic requirements changed",
            mapping_errors,
        )

    def test_formal_source_tampering_invalidates_the_seal(self):
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
            errors = approval.validate_approval_seal(
                self.seal,
                self.mapping,
                radar_root=temp_root,
            )
            report = approval.build_approval_validation_report(
                self.seal,
                self.mapping,
                radar_root=temp_root,
            )
        self.assertIn("approved formal source archive hash mismatch", errors)
        self.assertFalse(report["exact_mapping_hash_approved"])
        self.assertIn("AG_EXACT_MAPPING_HASH", report["remaining_approval_gates"])
        self.assertFalse(report["runtime_binding_ready"])
        self.assertIsNone(report["season"])

    def test_current_runtime_remains_unchanged_and_does_not_import_seal(self):
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
            if path.name == "btc_season_semantic_mapping_approval.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "btc_season_semantic_mapping_approval" in text:
                importing_files.append(path.name)
        self.assertEqual(importing_files, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
