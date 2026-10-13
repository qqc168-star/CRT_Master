from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REVISION_REF = "radar/RELEASE/CRT_DILUTED_MNAV_SEMANTIC_REVISION_20261013.md"
FORMULA_VERSION = "CRT_DILUTED_MNAV_BTC_MARKET_VALUE_V1"
FORMULA = "(diluted_shares * equity_price_usd) / (btc_holdings * btc_price_usd)"


class FormalMnavSemanticRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.revision = (ROOT / REVISION_REF).read_text(encoding="utf-8")

    def test_user_approval_has_current_formula_without_rewriting_history(self) -> None:
        for required in (
            "`2026-10-13`，日期精度", "CRT 正式 mNAV 唯一定義統一｜使用者批准施工",
            "原始內容", "不倒改歷史批准事實", FORMULA,
            FORMULA_VERSION, "CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.2",
            "BTC_HOLDINGS_MARKET_VALUE_USD", "不批准部署",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.revision)

    def test_current_reading_surfaces_resolve_the_same_formula(self) -> None:
        current_documents = (
            "README.md", "CRT_CORE_CONTRACT.md", "CRT_EVIDENCE_PACK_CONTRACT.md",
            "CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md",
            "CRT_SEASON_THREE_ARMY_COMMANDER_DEPLOYMENT_DOCTRINE_V0.1.md",
            "docs/TREASURY_COMPANY_CT_V0.1.md",
            "docs/TREASURY_VALUATION_CONTEXT_V0.1.md",
            "docs/CRT_PORTFOLIO_ALLOCATION_CONTEXT_V0.1.md",
            "docs/CRT_GOLD_RESEARCH_TREASURY_VALUATION_V0.1.md",
            "radar/STATUS/CRT_ACTIVE_BATON.md",
            "radar/STATUS/CURRENT_WIP_STATE.md",
            "radar/STATUS/CRT_ASSET_INTELLIGENCE_RECOVERY_BACKLOG.md",
        )
        for path in current_documents:
            with self.subTest(path=path):
                text = (ROOT / path).read_text(encoding="utf-8")
                self.assertIn(REVISION_REF, text)
                self.assertIn(FORMULA, text)

    def test_denominator_excludes_residual_adjustments_and_unproved_aliases(self) -> None:
        for required in (
            "分母只能為", "不得扣除債務、優先股或其他索取權",
            "不得加入現金、其他資產或普通股剩餘價值",
            "兩個總額及一個比值本身不能取得正式資格",
            "不得取名或冒充本修訂的 `mNAV`",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.revision)

    def test_shares_and_clocks_cannot_be_invented_or_promoted(self) -> None:
        for required in (
            "`basis_ref`", "`dilution_scope`", "`coverage_state = COMPLETE`",
            "不得自行增減股份", "傳統認股權證排除範圍必須明示",
            "缺失或部分覆蓋不能由接入器推定完整",
            "四項有效時點必須對齊", "四座時鐘順序須有效",
            "擷取時間不得晚於本次驗證時間", "補造有效時間",
            "原始 SHA256（雜湊）", "`BLOCKED`", "未知不當零",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.revision)

    def test_history_keeps_formula_versions_and_research_authority_separate(self) -> None:
        for required in (
            "CRT_DILUTED_EQUITY_MNAV_EVIDENCE_V0.1",
            "不能混入新正式歷史分布", "只更換版本字串",
            "四項原始元件或歷史可見時間無法驗真",
            "公式相同不賦予正式來源權威", "排除當前值",
            "至少二十筆", "100 * count(previous <= current) / count",
            "三十五日前、前後三個日曆日窗口", "較早值優先",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.revision)

    def test_original_formal_seal_content_is_preserved(self) -> None:
        old_seal = (
            ROOT / "radar/RELEASE/CRT_V1.10_FORMAL_SEAL_20260805.md"
        ).read_text(encoding="utf-8")
        normalized_hash = hashlib.sha256(old_seal.encode("utf-8")).hexdigest()
        self.assertEqual(
            normalized_hash,
            "8da6faffb794c4b4b13de5cd4704e3d0c3985f431c15d9ac5d7d137a9a2da6f9",
        )
        self.assertIn("Approval time: `2026-08-05 19:09 +08:00`", old_seal)
        self.assertIn("Unqualified `mNAV`: `Diluted Equity mNAV` only", old_seal)

    def test_season_approval_remains_exact_and_does_not_gain_authority(self) -> None:
        seal = json.loads((ROOT / "radar/CONFIG/BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_SEAL_V0.1.json").read_text(encoding="utf-8"))
        self.assertEqual(seal["approved_artifact"]["mapping_canonical_sha256"],
                         "afe99dfaf4a2023d39c1589252b840b27daab106932b33783316fec71ab05e3a")
        self.assertEqual(seal["approval_scope"]["season_output_authority"], "NONE")
        self.assertEqual(seal["approval_scope"]["production"], "NOT_APPROVED")
        self.assertFalse(seal["gate_effect"]["runtime_promotion_ready"])

    def test_other_formal_locks_and_live_acceptance_are_unchanged(self) -> None:
        for required in (
            "20 / 20 / 17 / 25 / 13 / 5", "-60 / -35 / 35 / 60",
            "四季配置", "production = NOT_APPROVED",
            "external_action_authority = NONE", "capital_decision_authority = USER_ONLY",
            "machine_execution = FORBIDDEN", "7 / 8 = 87.5%",
            "Runtime（執行環境）、排程及 stash（暫存修改）",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.revision)


if __name__ == "__main__":
    unittest.main()
