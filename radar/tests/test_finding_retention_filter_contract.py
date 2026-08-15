from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "CRT_CORE_CONTRACT.md"


class FindingRetentionFilterContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = CORE.read_text(encoding="utf-8")

    def test_three_question_filter_exists(self):
        self.assertIn("## Finding Retention Filter", self.text)
        self.assertIn("Necessity", self.text)
        self.assertIn("Purpose", self.text)
        self.assertIn("Specificity", self.text)

    def test_filter_required_before_promotion(self):
        self.assertIn(
            "must be re-examined through all three questions before promotion",
            self.text,
        )

    def test_pass_does_not_auto_promote(self):
        self.assertIn(
            "Passing all three questions grants only eligibility for verification",
            self.text,
        )

    def test_failed_item_can_remain_research_or_observation(self):
        self.assertIn("Research / Observation", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
