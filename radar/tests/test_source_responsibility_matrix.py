import json
import unittest
from pathlib import Path


RADAR_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = RADAR_ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"
ENVELOPE_PATH = (
    RADAR_ROOT / "CONFIG" / "BTC_SEASON_FORMAL_INPUT_ENVELOPE_CANDIDATE_V0.1.json"
)
MATRIX_PATH = RADAR_ROOT / "registry" / "SOURCE_RESPONSIBILITY_MATRIX.md"


class SourceResponsibilityMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.envelope = json.loads(ENVELOPE_PATH.read_text(encoding="utf-8"))
        cls.matrix = MATRIX_PATH.read_text(encoding="utf-8")

    def test_registry_identity_and_count_are_current(self):
        self.assertIn(f"`{self.registry['registry_id']}`", self.matrix)
        self.assertIn(f"`{self.registry['version']}`", self.matrix)
        self.assertIn(f"`{self.registry['status']}`", self.matrix)
        self.assertIn(f"| Registered sources | `{len(self.registry['sources'])}` |", self.matrix)
        self.assertNotIn("registry payload version `1.3-wip`", self.matrix)

    def test_every_registered_source_is_represented_exactly(self):
        for source in self.registry["sources"]:
            with self.subTest(source_id=source["source_id"]):
                for field in (
                    "namespace",
                    "input_family",
                    "source_id",
                    "parser_id",
                    "criticality",
                    "max_age_seconds",
                ):
                    self.assertIn(f"`{source[field]}`", self.matrix)

    def test_context_families_are_not_reported_as_wholly_missing(self):
        for family in (
            "MACRO_CONTEXT",
            "CREDIT_LIQUIDITY_CONTEXT",
            "PRICE_STRUCTURE_CONTEXT",
        ):
            self.assertIn(f"`{family}`", self.matrix)
        self.assertNotIn("Current missing families:", self.matrix)
        self.assertNotIn("AS-L1 official macro release engine", self.matrix)
        self.assertNotIn("AS-L6 price / volume / averages / ATR / CVD engine", self.matrix)

    def test_formal_input_families_remain_explicitly_unbound(self):
        families = self.envelope["required_family_bindings"]
        self.assertEqual(len(families), 12)
        for family in families:
            with self.subTest(family_id=family["family_id"]):
                self.assertEqual(family["binding_status"], "UNBOUND_BLOCKED")
                row_prefix = f"| `{family['family_id']}` | `UNBOUND_BLOCKED` |"
                self.assertIn(row_prefix, self.matrix)

    def test_authority_and_fail_closed_boundaries_are_explicit(self):
        required_phrases = (
            "does not grant Production, formal scoring, runtime binding, or Season-output authority",
            "Missing, stale, conflicting, or formally unbound evidence must fail closed.",
            "Runtime binding, Production approval, and Season output remain not approved.",
            "`action_output` remains `NONE`; External Action Authority remains `NONE`.",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, self.matrix)


if __name__ == "__main__":
    unittest.main(verbosity=2)
