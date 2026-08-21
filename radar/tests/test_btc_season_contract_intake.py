from __future__ import annotations

import hashlib
import json
import sys
import unittest
import zipfile
from pathlib import Path


RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

from crt_radar.btc_bull_validation import evaluate_btc_bull_validation


SOURCE_ROOT = RADAR_ROOT / "FORMAL_SOURCES" / "CRT-BTC-001_V1.0"
ARTIFACT = SOURCE_ROOT / "CRT_BTC_001_V1.0_FORMAL_ARCHIVE.zip"
INTAKE_RECORD = SOURCE_ROOT / "CRT_BTC_001_V1.0_SOURCE_INTAKE_RECORD_V0.1.md"
PREFIX = "CRT_BTC_001_V1.0_FORMAL_ARCHIVE/"

ARCHIVE_SIZE = 300_152
ARCHIVE_SHA256 = "4556141b069596b24d78b8c4b5e19071f6b435f9748cd04891e91817e0a34c42"
BODY_SIZE = 174_760
BODY_SHA256 = "5ba963b51bcf49839299c3ce4e7649728d3d8caa05d8ca442691689e667f0064"
CHAPTER_SEVEN_SIZE = 15_262
CHAPTER_SEVEN_SHA256 = (
    "fb872d4ee4a9abb6697214b4d7f17e85459259f715199ffb0ce502420d754a26"
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class BtcSeasonContractIntakeTests(unittest.TestCase):
    def test_archive_bytes_and_internal_manifests_match(self):
        artifact_bytes = ARTIFACT.read_bytes()
        self.assertEqual(len(artifact_bytes), ARCHIVE_SIZE)
        self.assertEqual(sha256(artifact_bytes), ARCHIVE_SHA256)

        with zipfile.ZipFile(ARTIFACT) as archive:
            self.assertIsNone(archive.testzip())

            manifest_bytes = archive.read(
                PREFIX + "MANIFEST/PACKAGE_MANIFEST.json"
            )
            manifest = json.loads(manifest_bytes)
            self.assertEqual(
                {
                    "package": manifest["package"],
                    "version": manifest["version"],
                    "type": manifest["type"],
                    "scope": manifest["scope"],
                    "status": manifest["status"],
                    "acceptance": manifest["acceptance"],
                },
                {
                    "package": "CRT_BTC_001_V1.0_FORMAL_ARCHIVE",
                    "version": "V1.0",
                    "type": "formal_archive",
                    "scope": "CH01-12",
                    "status": "FORMAL_ARCHIVE",
                    "acceptance": "AG-0_TO_AG-9_PASS",
                },
            )

            self.assertEqual(len(manifest["files"]), 37)
            for entry in manifest["files"]:
                payload = archive.read(PREFIX + entry["path"])
                self.assertEqual(len(payload), entry["size"], entry["path"])
                self.assertEqual(sha256(payload), entry["sha256"], entry["path"])

            sums_text = archive.read(
                PREFIX + "MANIFEST/SHA256SUMS.txt"
            ).decode("utf-8")
            sums = {}
            for line in sums_text.splitlines():
                digest, relative_path = line.split("  ", maxsplit=1)
                sums[relative_path] = digest

            self.assertEqual(len(sums), 38)
            for relative_path, expected_digest in sums.items():
                payload = archive.read(PREFIX + relative_path)
                self.assertEqual(
                    sha256(payload),
                    expected_digest,
                    relative_path,
                )

    def test_formal_release_acceptance_and_minimum_tests_are_present(self):
        with zipfile.ZipFile(ARTIFACT) as archive:
            release = archive.read(
                PREFIX + "RELEASE/CRT-BTC-001_RELEASE_RECORD_V1.0.md"
            ).decode("utf-8")
            acceptance = archive.read(
                PREFIX
                + "RELEASE/CRT-BTC-001_USER_ACCEPTANCE_2026-07-21.md"
            ).decode("utf-8")
            minimum_tests = archive.read(
                PREFIX + "RELEASE/CRT-BTC-001_MINIMUM_TEST_SET_V1.0.md"
            ).decode("utf-8")

        self.assertIn("正式版本：V1.0", release)
        self.assertIn("狀態：FORMAL_ARCHIVE", release)
        self.assertIn("驗收：AG-0 至 AG-9 全部 PASS", release)
        self.assertIn("AG-9：PASS", acceptance)
        self.assertIn("升格 CRT-BTC-001 V1.0／FORMAL_ARCHIVE", acceptance)

        for index in range(1, 16):
            test_id = f"TST-{index:02d}"
            matching_lines = [
                line for line in minimum_tests.splitlines() if test_id in line
            ]
            self.assertEqual(len(matching_lines), 1, test_id)
            self.assertTrue(matching_lines[0].rstrip().endswith("| PASS |"), test_id)

    def test_chapter_seven_contract_is_exact_and_complete(self):
        with zipfile.ZipFile(ARTIFACT) as archive:
            body = archive.read(
                PREFIX + "WORKING/CRT-BTC-001_WORKING_BODY.md"
            )

        self.assertEqual(len(body), BODY_SIZE)
        self.assertEqual(sha256(body), BODY_SHA256)

        chapter_start = body.index("## 第七章".encode())
        chapter_end = body.index("## 第八章".encode(), chapter_start)
        chapter_bytes = body[chapter_start:chapter_end]
        chapter = chapter_bytes.decode("utf-8")

        self.assertEqual(len(chapter_bytes), CHAPTER_SEVEN_SIZE)
        self.assertEqual(sha256(chapter_bytes), CHAPTER_SEVEN_SHA256)

        for state in (
            "SE-WI",
            "SE-WI-SPC",
            "SE-SP",
            "SE-SP-SUC",
            "SE-SU",
            "SE-SU-AUC",
            "SE-AU",
            "SE-AU-WTC",
            "SE-X",
        ):
            self.assertIn(state, chapter)

        for heading in (
            "### 7.4 換季的五步程序",
            "### 7.5 冬季轉春季：標準路徑",
            "### 7.6 春季正式確認",
            "### 7.9 候選失效與冬季回復",
            "### 7.10 已確認春季的重驗與回退",
            "### 7.14 相鄰切換與緊急行動",
            "### 7.19 本章固定契約",
        ):
            self.assertIn(heading, chapter)

        for required_rule in (
            "熊市處於 Stage 3 或已具備等同的成熟清洗背景",
            "投降軸達 C3",
            "止跌軸達 S2 以上",
            "第六章合成等級至少 E2",
            "E2 只允許建立春季候選，不允許直接確認春季",
            "第六章合成等級達 E3",
            "S3 成立，P1 週線與 P2 現貨兩項必要門檻持續有效",
            "至少完成一次獨立的後續驗證",
            "SEASON_UNDER_REVIEW",
            "季節只允許向相鄰狀態切換",
        ):
            self.assertIn(required_rule, chapter)

    def test_current_runtime_and_overlay_remain_fail_closed(self):
        contract = json.loads(
            (RADAR_ROOT / "CONFIG" / "V110_FORMAL_CANDIDATE_RUNTIME_V0.1.json")
            .read_text(encoding="utf-8")
        )

        self.assertEqual(contract["status"], "FORMAL_CANDIDATE_NOT_APPROVED")
        self.assertEqual(contract["approval"]["formal_model"], "NOT_APPROVED")
        self.assertEqual(contract["approval"]["production"], "NOT_APPROVED")
        self.assertEqual(contract["approval"]["external_action_authority"], "NONE")
        self.assertEqual(
            contract["inherited_formal_constants"]["layer_weights_percent"],
            {"L1": 20, "L2": 20, "L3": 17, "L4": 25, "L5": 13, "L6": 5},
        )
        self.assertEqual(
            contract["inherited_formal_constants"]["light_thresholds"],
            [-60, -35, 35, 60],
        )
        self.assertEqual(
            contract["inherited_formal_constants"]["mnav_semantics"],
            "Diluted Equity mNAV",
        )

        router = contract["season_router"]
        self.assertEqual(
            router["status"],
            "SPEC_NOT_RECOVERED_CANDIDATE_FAIL_CLOSED",
        )
        self.assertTrue(router["score_may_supply_weather_bucket"])
        self.assertFalse(router["score_may_determine_btc_season"])
        self.assertEqual(
            router["blocked_reason"],
            "V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED",
        )

        overlay = evaluate_btc_bull_validation(
            pack_state="BLOCKED",
            btc_entry_gate=None,
            transition_diagnostic=None,
            layers={},
            generated_at_ms=1,
        )
        self.assertEqual(overlay["scope"], "NON_WEIGHTED_EVIDENCE_OVERLAY")
        self.assertEqual(
            overlay["authority"],
            {
                "formal_model_authority": "NONE",
                "formal_weight_authority": "NONE",
                "formal_threshold_authority": "NONE",
                "external_action_authority": "NONE",
                "external_action_performed": False,
            },
        )
        self.assertFalse(overlay["machine_may_confirm_bull_transition"])
        self.assertEqual(overlay["action_output"], "NONE")

    def test_intake_record_quarantines_promotion_and_research_delta(self):
        record = INTAKE_RECORD.read_text(encoding="utf-8")

        for marker in (
            "`SOURCE_ARTIFACT_FOUND = PASS`",
            "`SOURCE_INTEGRITY = PASS`",
            "`FORMAL_ACCEPTANCE_EVIDENCE = PASS`",
            "`RUNTIME_PROMOTION = BLOCKED`",
            "`SEASON_OUTPUT = null`",
            "`RESEARCH_DELTA_AUTHORITY = NONE`",
        ):
            self.assertIn(marker, record)

        self.assertIn(
            "does not claim recovery of the lost historical wording verbatim",
            record,
        )
        self.assertIn("It supplied no rule, state,", record)
        self.assertIn("weight, threshold, confirmation, or inference", record)


if __name__ == "__main__":
    unittest.main()
