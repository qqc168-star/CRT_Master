from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DOCTRINE_PATH = (
    ROOT
    / "CRT_SEASON_THREE_ARMY_COMMANDER_DEPLOYMENT_DOCTRINE_V0.1.md"
)
README_PATH = ROOT / "README.md"


class SeasonThreeArmyCommanderDeploymentDoctrineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doctrine = DOCTRINE_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_non_formal_scope_and_authority_are_locked(self) -> None:
        required_literals = (
            "doctrine_status: NON_FORMAL",
            "formal_model_status: NON_FORMAL",
            "season_scope: STRATEGIC_RISK_POSTURE_ONLY",
            "bull_foundation_scope: TRANSITION_CREDIBILITY_ONLY",
            "commander_map_scope: TACTICAL_LINES_AND_CAPITAL_DEPLOYMENT",
            "season_may_emit_trade_action: false",
            "bull_foundation_may_emit_trade_action: false",
            "formal_season_auto_update: false",
            "production: NOT_APPROVED",
            "external_action_authority: NONE",
            "capital_decision_authority: USER_ONLY",
            "action_output: NONE",
        )
        for literal in required_literals:
            with self.subTest(literal=literal):
                self.assertIn(literal, self.doctrine)

    def test_four_postures_and_closed_loop_projection_are_present(self) -> None:
        required_literals = (
            "Winter（冬季）",
            "Spring（春季）",
            "Summer（夏季）",
            "Autumn（秋季）",
            "`entry_condition`",
            "`ACTION_MAP.analyst_judgment`",
            "`exit_condition.stop_loss`",
            "`exit_condition.take_profit`",
            "`entry_shares_delta`",
            "`exit_shares_delta`",
        )
        for literal in required_literals:
            with self.subTest(literal=literal):
                self.assertIn(literal, self.doctrine)

    def test_preserved_formal_locks_are_explicit(self) -> None:
        required_literals = (
            "`20 / 20 / 17 / 25 / 13 / 5`",
            "`-60 / -35 / 35 / 60`",
            "`Diluted Equity mNAV`",
            "`BLOCKED / null`",
            "`6 / 8 = 75%`",
        )
        for literal in required_literals:
            with self.subTest(literal=literal):
                self.assertIn(literal, self.doctrine)

    def test_bootloader_references_the_doctrine(self) -> None:
        self.assertIn(DOCTRINE_PATH.name, self.readme)


if __name__ == "__main__":
    unittest.main()
