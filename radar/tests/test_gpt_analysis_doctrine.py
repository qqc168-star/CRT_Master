from __future__ import annotations

import unittest
from pathlib import Path


class GptAnalysisDoctrineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.doctrine_path = cls.root / "CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md"
        cls.readme_path = cls.root / "README.md"
        cls.doctrine = cls.doctrine_path.read_text(encoding="utf-8")
        cls.readme = cls.readme_path.read_text(encoding="utf-8")

    def test_doctrine_is_boot_discoverable(self) -> None:
        boot = self.readme.split("## Boot sequence for a fresh GPT", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Read `CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md`", boot)

    def identity_lock(self) -> str:
        return self.doctrine.split("### 1.1 Project Identity Lock（專案身份鎖）", 1)[1].split(
            "## 2. 權限與正式邊界", 1
        )[0]

    def test_project_identity_lock_binds_ns_to_current_main_and_crt_chain(self) -> None:
        lock = self.identity_lock()
        for text in (
            "`🎯 第一顆比特幣｜CRT`",
            "固定分析／統帥身份為 `N.S.`",
            "commander identity（統帥身份）",
            "必須先讀取 current GitHub `main`",
            "Engineering SSOT（工程唯一真實來源）",
            "不得沿用聊天記憶、舊 SHA（提交雜湊）或舊工程狀態",
            "必須先服從 current `main`",
            "`CRT_CORE_CONTRACT.md`",
            "`CRT_EVIDENCE_PACK_CONTRACT.md`",
            "最新可用 Evidence Pack（證據包）",
            "再依本準則與 `CRT_SEASON_THREE_ARMY_COMMANDER_DEPLOYMENT_DOCTRINE_V0.1.md`",
            "不得讓一般助理人格越過 CRT",
            "不得自行建立第二套簡化框架",
        ):
            with self.subTest(required=text):
                self.assertIn(text, lock)

    def test_project_identity_lock_fails_closed_without_fabricated_formal_claims(self) -> None:
        lock = self.identity_lock()
        for text in (
            "current `main`（目前主分支）無法讀取時",
            "判斷必須標示 `BLOCKED`",
            "證據缺失、過期、無效或無法驗真時",
            "受影響主張必須 `BLOCKED`",
            "`WAIT`（等待）",
            "不得自行補數",
            "不得假裝正式點燈或正式季節已確認",
            "claim-scoped（主張範圍限定）",
            "獨立有效證據仍可支持",
            "不得用降低精度取代受阻正式主張",
        ):
            with self.subTest(required=text):
                self.assertIn(text, lock)

    def test_project_identity_lock_preserves_capital_and_formal_authority(self) -> None:
        lock = self.identity_lock()
        for text in (
            "User（使用者）保有最終資本決定權",
            "身份鎖不授予任何正式交易權限",
            "project-level analysis routing（專案層分析路由）",
            "不新增第七層",
            "不修改正式六層權重、燈號閾值、`mNAV` 語義",
            "Season Router（季節路由器）",
            "Production approval（正式生產批准）",
            "External Action Authority（外部行動權限）",
        ):
            with self.subTest(required=text):
                self.assertIn(text, lock)

    def test_existing_reanalysis_sequence_is_preserved_in_order(self) -> None:
        sequence = (
            "CATALYST",
            "AMPLIFIER",
            "PERSISTENCE",
            "ACCEPTANCE",
            "CONTRADICTIONS",
            "MISSING_EVIDENCE",
        )
        offsets = [self.doctrine.index(item) for item in sequence]
        self.assertEqual(offsets, sorted(offsets))

    def test_governance_authority_remains_read_only(self) -> None:
        required = (
            "Production（正式生產）：`NOT_APPROVED`",
            "External Action Authority（外部行動權限）：`NONE`",
            "Capital Decision Authority（資本決策權限）：`USER_ONLY`",
            'action_output`：`"NONE"`',
        )
        for text in required:
            self.assertIn(text, self.doctrine)

    def test_doctrine_does_not_create_a_seventh_layer(self) -> None:
        self.assertIn("不新增第七層", self.doctrine)
        self.assertNotIn("L7 ", self.doctrine)
        self.assertNotIn("L7（", self.doctrine)

    def test_claim_scoped_fail_closed_and_evidence_independence_are_explicit(self) -> None:
        self.assertIn("claim-scoped", self.doctrine)
        self.assertIn("Evidence Independence", self.doctrine)
        self.assertIn("不得把多個由同一底層變數衍生的指標當成多票獨立支持", self.doctrine)
        self.assertIn("獨立證據家族", self.doctrine)

    def test_capital_judgment_requires_invalidation_and_portfolio_impact(self) -> None:
        self.assertIn("Invalidation（失效條件）", self.doctrine)
        self.assertIn("Portfolio impact（投資組合影響）", self.doctrine)
        self.assertIn("BUY / SELL / HOLD / WAIT / ROTATE", self.doctrine)

    def test_decision_asymmetry_check_is_actionable_and_non_formulaic(self) -> None:
        self.assertIn("Decision Asymmetry Check（決策不對稱檢查）", self.doctrine)
        for text in (
            "Thesis confidence（論點信心）",
            "Price concession（價格讓步）",
            "Remaining upside（剩餘上行）",
            "Damage if wrong（判錯損失）",
            "Asymmetry（不對稱性）",
        ):
            self.assertIn(text, self.doctrine)
        self.assertIn("Confirmation（確認）不是免費的", self.doctrine)
        self.assertIn("不是新分數、機率模型、權重或門檻", self.doctrine)

    def test_shared_shock_propagation_is_scenario_only_without_fake_beta(self) -> None:
        self.assertIn("Shared Shock Propagation（共同衝擊傳播）", self.doctrine)
        self.assertIn("不同 ticker（資產代號）不得自動視為不同風險來源", self.doctrine)
        self.assertIn("scenario stress（情境壓力）", self.doctrine)
        self.assertIn("固定跌幅倍數不得被發明", self.doctrine)

    def test_relative_opportunity_cost_requires_role_compatible_evidence(self) -> None:
        self.assertIn("Relative Opportunity Cost（相對機會成本）", self.doctrine)
        self.assertIn("role-compatible alternatives（角色相容替代方案）", self.doctrine)
        self.assertIn("不得假造排序", self.doctrine)

    def test_issuer_health_translation_and_reversible_rotation_preservation_are_explicit(self) -> None:
        for text in (
            "Issuer Health -> Allocation Translation（發行人健康到配置轉譯）",
            "Fact -> Issuer Health -> Investor Risk -> Asset Role -> Portfolio Impact -> Capital Judgment",
            "Risk Improvement（風險改善）不等於 Allocation Increase（配置增加）",
            "Risk-Budget Release（風險預算釋放）",
            "Liability Relief（負債減壓）",
            "Liquidity Burn（流動性燃燒）",
            "Market Handoff Test（市場接棒檢查）",
            "Reversible Rotation Preservation Check（可逆輪動保全檢查）",
            "Capital Preservation Ratio（資本保全比）",
            "Entitlement Clock（權利時鐘）",
            "Cash Clock（現金時鐘）",
        ):
            self.assertIn(text, self.doctrine)
        self.assertIn("不是正式六層分數、燈號、交易 gate（關卡）或機器執行授權", self.doctrine)

    def test_finding_admission_keeps_formal_three_and_adds_applicability_locally(self) -> None:
        for text in (
            "Necessity（必要性）",
            "Purpose（目的性）",
            "Specificity（針對性）",
            "Applicability（落地應用性）",
            "Trigger（觸發點）",
            "Inputs（輸入）",
            "Judgment effect（判斷作用）",
            "Output effect（輸出作用）",
            "Validation（驗證）",
        ):
            self.assertIn(text, self.doctrine)
        self.assertIn("不修改 `CRT_CORE_CONTRACT.md` 的正式三項", self.doctrine)
        self.assertIn("這些是驗證問題，不另長成", self.doctrine)


if __name__ == "__main__":
    unittest.main()
