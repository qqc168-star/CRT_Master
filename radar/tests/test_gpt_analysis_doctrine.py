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
        self.assertIn("CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md", self.readme)

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
