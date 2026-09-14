from __future__ import annotations

import unittest
from pathlib import Path


class DualHairpinCapitalRotationMentalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.research = (
            cls.root
            / "radar"
            / "research"
            / "CRT_DUAL_HAIRPIN_CAPITAL_ROTATION_MENTAL_MODEL_V0.1.md"
        ).read_text(encoding="utf-8")
        cls.doctrine = (cls.root / "CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md").read_text(
            encoding="utf-8"
        )

    def test_research_anchor_has_the_exact_capital_preservation_relation(self) -> None:
        equations = (
            "q_B = (q_A * A0_bid - C_out) / B0_ask",
            "q_A_back = (q_B * (B1_bid + d_cash) - C_back) / A1_ask",
            "R_cap = q_A_back / q_A",
        )
        offsets = [self.research.index(equation) for equation in equations]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("Capital Preservation Ratio（資本保全比）", self.research)
        self.assertIn("`R_cap < 1`", self.research)
        self.assertIn("`R_cap = 1`", self.research)
        self.assertIn("`R_cap > 1`", self.research)

    def test_cash_clock_is_required_for_return_purchase_power(self) -> None:
        self.assertIn("Entitlement Clock（權利時鐘）", self.research)
        self.assertIn("Cash Clock（現金時鐘）", self.research)
        self.assertIn("不能納入 `d_cash`、回程購買力或 `R_cap`", self.research)

    def test_modes_handoff_and_partial_roll_are_explicit(self) -> None:
        for text in (
            "Market Handoff Test（市場接棒檢查）",
            "independent demand（獨立市場需求）",
            "issuer dependence（發行人依賴）",
            "Par Recovery Mode（面額修復模式）",
            "Carry Harvest Mode（收益收割模式）",
            "Partial Roll（部分輪動）",
            "returnability（可回復性）",
        ):
            self.assertIn(text, self.research)

    def test_issuer_health_translation_preserves_allocation_separation(self) -> None:
        for text in (
            "Fact -> Issuer Health -> Investor Risk -> Asset Role -> Portfolio Impact -> Capital Judgment",
            "Risk Improvement（風險改善）不等於 Allocation Increase（配置增加）",
            "Risk-Budget Release（風險預算釋放）",
            "Liability Relief（負債減壓）",
            "Liquidity Burn（流動性燃燒）",
            "designated / protected reserve（指定／受保護準備金）",
            "unrestricted / free cash（非受限／自由現金）",
        ):
            self.assertIn(text, self.research)
            self.assertIn(text, self.doctrine)

    def test_approximation_is_not_substituted_for_returnability(self) -> None:
        for text in (
            "G0 = B0_ask - A0_bid",
            "G1 = B1_bid - A1_ask",
            "E_approx ≈ d_cash + G1 - G0 - c",
            "不能取代 `R_cap`",
        ):
            self.assertIn(text, self.research)

    def test_anchor_is_nonformal_and_has_no_ephemeral_quotes(self) -> None:
        self.assertIn("`NON_FORMAL_RESEARCH_ANCHOR`", self.research)
        self.assertIn("不得新增第七層", self.research)
        self.assertIn("不得讓機器產生交易、下單、資金移動或帳戶操作權限", self.research)
        for short_lived_value in ("98.58", "99.85", "0.80", "273.9"):
            self.assertNotIn(short_lived_value, self.research)


if __name__ == "__main__":
    unittest.main()
