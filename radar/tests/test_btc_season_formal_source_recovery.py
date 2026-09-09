from __future__ import annotations

import hashlib
import json
import sys
import unittest
import zipfile
from pathlib import Path

RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

REPORT_PATH = (
    RADAR_ROOT / "research" / "CRT_BTC_SEASON_FORMAL_SOURCE_RECOVERY_V0.1.json"
)
ARCHIVE_PATH = (
    RADAR_ROOT
    / "FORMAL_SOURCES"
    / "CRT-BTC-001_V1.0"
    / "CRT_BTC_001_V1.0_FORMAL_ARCHIVE.zip"
)
ENVELOPE_PATH = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_FORMAL_INPUT_ENVELOPE_CANDIDATE_V0.1.json"
)
MAPPING_PATH = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1.json"
)
SEAL_PATH = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_SEAL_V0.1.json"
)
SOURCE_MATRIX_PATH = RADAR_ROOT / "registry" / "SOURCE_RESPONSIBILITY_MATRIX.md"

PREFIX = "CRT_BTC_001_V1.0_FORMAL_ARCHIVE/"
BODY_MEMBER = PREFIX + "WORKING/CRT-BTC-001_WORKING_BODY.md"

EXPECTED_ARCHIVE_SHA = (
    "4556141b069596b24d78b8c4b5e19071f6b435f9748cd04891e91817e0a34c42"
)
EXPECTED_BODY_SHA = (
    "5ba963b51bcf49839299c3ce4e7649728d3d8caa05d8ca442691689e667f0064"
)
EXPECTED_CH07_SHA = (
    "fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26"
)
EXPECTED_MAPPING_CANONICAL_SHA = (
    "afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a"
)

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical_hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

def canonical_source_bytes(raw: bytes) -> bytes:
    """Hash source content independently of Git checkout line endings."""
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

class BtcSeasonFormalSourceRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_governance_boundary(self):
        self.assertEqual(
            self.report["status"],
            "RESEARCH_RECOVERY_CANDIDATE_NOT_APPROVED",
        )
        authority = self.report["authority"]
        self.assertEqual(authority["formal_model"], "NOT_APPROVED")
        self.assertEqual(authority["runtime_binding"], "NOT_APPROVED")
        self.assertEqual(authority["season_output_authority"], "NONE")
        self.assertEqual(authority["production"], "NOT_APPROVED")
        self.assertEqual(authority["capital_decision_authority"], "USER_ONLY")
        self.assertEqual(authority["external_action_authority"], "NONE")
        self.assertFalse(authority["external_action_performed"])
        self.assertEqual(authority["action_output"], "NONE")
        self.assertFalse(
            self.report["recovery_decision"][
                "may_implement_stage_v_c_s_e_d_runtime_from_this_report_alone"
            ]
        )
        self.assertFalse(
            self.report["recovery_decision"]["may_change_formal_input_binding"]
        )

    def test_formal_archive_and_working_body_identity(self):
        archive_bytes = ARCHIVE_PATH.read_bytes()
        self.assertEqual(sha256(archive_bytes), EXPECTED_ARCHIVE_SHA)
        self.assertEqual(
            self.report["source_archive"]["sha256"],
            EXPECTED_ARCHIVE_SHA,
        )
        with zipfile.ZipFile(ARCHIVE_PATH) as zf:
            self.assertIsNone(zf.testzip())
            body = zf.read(BODY_MEMBER)
        self.assertEqual(sha256(body), EXPECTED_BODY_SHA)
        self.assertEqual(
            self.report["source_archive"]["working_body_sha256"],
            EXPECTED_BODY_SHA,
        )

    def test_chapter_slices_are_reproducible(self):
        with zipfile.ZipFile(ARCHIVE_PATH) as zf:
            body = zf.read(BODY_MEMBER)

        markers = [
            ("CH02", "第二章", "第三章"),
            ("CH03", "第三章", "第四章"),
            ("CH04", "第四章", "第五章"),
            ("CH05", "第五章", "第六章"),
            ("CH06", "第六章", "第七章"),
            ("CH07", "第七章", "第八章"),
        ]
        report_by_id = {
            row["chapter_id"]: row for row in self.report["chapters"]
        }

        self.assertEqual(set(report_by_id), {x[0] for x in markers})

        for chapter_id, start_label, end_label in markers:
            start = body.index(f"## {start_label}".encode("utf-8"))
            end = body.index(f"## {end_label}".encode("utf-8"), start)
            raw = body[start:end]
            row = report_by_id[chapter_id]
            self.assertEqual(len(raw), row["size_bytes"], chapter_id)
            self.assertEqual(sha256(raw), row["sha256"], chapter_id)

        self.assertEqual(report_by_id["CH07"]["sha256"], EXPECTED_CH07_SHA)
        self.assertEqual(report_by_id["CH07"]["size_bytes"], 15_262)

    def test_approved_mapping_and_external_seal_remain_exact(self):
        mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            canonical_hash(mapping),
            EXPECTED_MAPPING_CANONICAL_SHA,
        )

        seal = json.loads(SEAL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(seal["status"], "EXACT_MAPPING_HASH_APPROVED")
        self.assertEqual(
            seal["approved_artifact"]["mapping_canonical_sha256"],
            EXPECTED_MAPPING_CANONICAL_SHA,
        )
        self.assertEqual(
            seal["gate_effect"]["closed_gate"],
            "AG_EXACT_MAPPING_HASH",
        )
        self.assertEqual(
            seal["gate_effect"]["remaining_approval_gates"],
            ["AG_RUNTIME_PROMOTION"],
        )

    def test_protected_files_match_recovery_snapshot(self):
        hashes = self.report["protected_file_hashes_at_recovery"]
        self.assertEqual(
            sha256(canonical_source_bytes(ENVELOPE_PATH.read_bytes())),
            hashes["formal_input_envelope_sha256"],
        )
        self.assertEqual(
            sha256(canonical_source_bytes(MAPPING_PATH.read_bytes())),
            hashes["semantic_mapping_file_sha256"],
        )
        self.assertEqual(
            sha256(canonical_source_bytes(SEAL_PATH.read_bytes())),
            hashes["approval_seal_sha256"],
        )
        self.assertEqual(
            sha256(canonical_source_bytes(SOURCE_MATRIX_PATH.read_bytes())),
            hashes["source_responsibility_matrix_sha256"],
        )

    def test_recovery_hashes_are_portable_across_git_line_endings(self):
        source_lf = b"line one\nline two\n"
        source_crlf = b"line one\r\nline two\r\n"
        self.assertEqual(
            sha256(canonical_source_bytes(source_lf)),
            sha256(canonical_source_bytes(source_crlf)),
        )

    def test_recovery_has_required_formal_families(self):
        roles = " ".join(row["formal_role"] for row in self.report["chapters"])
        for expected in (
            "SEASON_STAGE_BACKGROUND",
            "VALUE_STATE_V",
            "CAPITULATION_STATE_C",
            "STOPPING_STATE_S",
            "EVIDENCE_CONSISTENCY_E",
            "CONFLICT_SEVERITY_D",
            "Season State Transition Contract",
        ):
            self.assertIn(expected, roles)

        for row in self.report["chapters"]:
            self.assertGreater(row["heading_count"], 0, row["chapter_id"])
            self.assertGreater(row["keyword_hit_count"], 0, row["chapter_id"])
            self.assertGreater(len(row["evidence_blocks"]), 0, row["chapter_id"])
            self.assertFalse(row["local_exact_extract_committed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
