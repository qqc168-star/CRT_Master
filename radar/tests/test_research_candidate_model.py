from __future__ import annotations

import importlib.util
import json
import math
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
REGISTRY_PATH = RESEARCH / "CRT_SIX_LAYER_CANDIDATE_V0.1.json"
GOLDEN_PATH = RESEARCH / "golden_vectors_v0.1.json"
MODULE_PATH = RESEARCH / "candidate_model.py"

spec = importlib.util.spec_from_file_location("candidate_model", MODULE_PATH)
candidate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(candidate)


def _neutral_observations(registry: dict) -> dict:
    current_ms = 2_000_000_000_000
    observations: dict[str, dict] = {}
    for layer in registry["layers"]:
        for feature in layer["features"]:
            transform = feature["transform"]
            transform_type = transform["type"]
            bounds = feature.get("valid_range", {})
            if "minimum_exclusive" in bounds:
                base = float(bounds["minimum_exclusive"]) + 2.0
            elif bounds.get("minimum_inclusive") == 0:
                base = 1.0
            else:
                base = 0.0
            item = {"as_of_ms": current_ms, "value": base}
            if transform_type != "TANH_FIXED":
                count = transform["minimum_history_observations"]
                midpoint = (count - 1) / 2
                half_span = 0.5 if bounds else max(1.0, midpoint * 0.1)
                step = half_span / max(1.0, midpoint)
                item["history"] = [
                    {
                        "as_of_ms": current_ms - (count - index) * 86_400_000,
                        "value": base + (index - midpoint) * step,
                    }
                    for index in range(count)
                ]
            observations[feature["feature_id"]] = item
    observations["L5_NUPL_OBSERVED"] = {
        "as_of_ms": current_ms,
        "value": 1 - 1 / observations["L5_MVRV_LEVEL"]["value"],
    }
    return observations


class ResearchCandidateModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = candidate.load_registry(REGISTRY_PATH)

    def test_registry_is_research_only_and_preserves_formal_constants(self):
        self.assertEqual(candidate.validate_registry(self.registry), [])
        self.assertEqual(self.registry["status"], "RESEARCH_ONLY_NOT_APPROVED")
        self.assertEqual(self.registry["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(self.registry["authority"]["external_action_authority"], "NONE")
        self.assertFalse(self.registry["authority"]["external_action_performed"])
        self.assertEqual(self.registry["authority"]["action_output"], "NONE")
        self.assertEqual(
            self.registry["inherited_formal_constants"]["layer_weights_percent"],
            {"L1": 20, "L2": 20, "L3": 17, "L4": 25, "L5": 13, "L6": 5},
        )
        self.assertEqual(
            self.registry["inherited_formal_constants"]["light_thresholds"],
            [-60, -35, 35, 60],
        )
        feature_ids = {
            feature["feature_id"]
            for layer in self.registry["layers"]
            for feature in layer["features"]
        }
        self.assertNotIn("L5_NUPL_OBSERVED", feature_ids)
        self.assertEqual(self.registry["validation_rules"][0]["scoring_weight_percent"], 0)

    def test_registry_rejects_formal_constant_drift(self):
        changed = deepcopy(self.registry)
        changed["inherited_formal_constants"]["layer_weights_percent"]["L1"] = 21
        changed["inherited_formal_constants"]["light_thresholds"][0] = -61
        errors = candidate.validate_registry(changed)
        self.assertIn("formal layer weights changed", errors)
        self.assertIn("formal light thresholds changed", errors)

    def test_golden_aggregation_vectors(self):
        payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        for vector in payload["vectors"]:
            with self.subTest(vector=vector["vector_id"]):
                result = candidate.aggregate_feature_scores(
                    self.registry,
                    vector["normalized_feature_scores"],
                )
                self.assertEqual(result, vector["expected"])

    def test_neutral_full_input_is_deterministic_and_has_no_action_authority(self):
        observations = _neutral_observations(self.registry)
        first = candidate.evaluate_candidate(observations, self.registry)
        second = candidate.evaluate_candidate(deepcopy(observations), self.registry)
        self.assertEqual(first, second)
        self.assertEqual(first["model_state"], "VALID_RESEARCH_OUTPUT")
        self.assertEqual(first["candidate_score"], 0.0)
        self.assertEqual(first["threshold_bucket"], "C2_MIXED")
        self.assertEqual(first["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(first["authority"]["external_action_authority"], "NONE")
        self.assertFalse(first["authority"]["external_action_performed"])
        self.assertEqual(first["authority"]["action_output"], "NONE")
        self.assertIsNone(first["capital_decision"])
        self.assertEqual(len(first["candidate_registry_hash"]), 64)
        self.assertEqual(len(first["candidate_input_hash"]), 64)
        self.assertEqual(len(first["candidate_output_hash"]), 64)

        changed = deepcopy(observations)
        changed["L6_CVD_20D_SHARE"]["value"] = 0.1
        changed_result = candidate.evaluate_candidate(changed, self.registry)
        self.assertNotEqual(first["candidate_input_hash"], changed_result["candidate_input_hash"])
        self.assertNotEqual(first["candidate_output_hash"], changed_result["candidate_output_hash"])

    def test_missing_required_feature_blocks_without_reweighting(self):
        observations = _neutral_observations(self.registry)
        del observations["L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM"]
        result = candidate.evaluate_candidate(observations, self.registry)
        self.assertEqual(result["model_state"], "BLOCKED")
        self.assertIsNone(result["candidate_score"])
        self.assertIsNone(result["threshold_bucket"])
        self.assertIn(
            "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM_MISSING",
            result["blocked_reasons"],
        )

    def test_nupl_identity_mismatch_blocks_l5_and_whole_model(self):
        observations = _neutral_observations(self.registry)
        observations["L5_NUPL_OBSERVED"]["value"] += 0.01
        result = candidate.evaluate_candidate(observations, self.registry)
        self.assertEqual(result["model_state"], "BLOCKED")
        self.assertEqual(result["layers"]["L5"]["state"], "BLOCKED")
        self.assertIn("L5_MVRV_NUPL_IDENTITY_MISMATCH", result["blocked_reasons"])

    def test_history_must_be_strictly_prior(self):
        observations = _neutral_observations(self.registry)
        item = observations["L2_BROAD_USD_20D_LOG_CHANGE"]
        item["history"][-1]["as_of_ms"] = item["as_of_ms"]
        result = candidate.evaluate_candidate(observations, self.registry)
        self.assertEqual(result["model_state"], "BLOCKED")
        self.assertIn(
            "L2_BROAD_USD_20D_LOG_CHANGE_HISTORY_NOT_STRICTLY_PRIOR",
            result["blocked_reasons"],
        )

    def test_impossible_mvrv_history_blocks(self):
        observations = _neutral_observations(self.registry)
        observations["L5_MVRV_LEVEL"]["history"][0]["value"] = 0
        result = candidate.evaluate_candidate(observations, self.registry)
        self.assertEqual(result["model_state"], "BLOCKED")
        self.assertIn("L5_MVRV_LEVEL_VALUE_OUT_OF_RANGE", result["blocked_reasons"])

    def test_fixed_transform_is_bounded(self):
        feature = {
            "feature_id": "X",
            "direction": 1,
            "transform": {"type": "TANH_FIXED", "scale": 2.0},
        }
        high = candidate.score_feature(feature, {"as_of_ms": 10, "value": 1e9})
        low = candidate.score_feature(feature, {"as_of_ms": 10, "value": -1e9})
        self.assertTrue(math.isclose(high, 100.0))
        self.assertTrue(math.isclose(low, -100.0))

    def test_every_feature_requires_as_of_timestamp(self):
        observations = _neutral_observations(self.registry)
        del observations["L6_CVD_20D_SHARE"]["as_of_ms"]
        result = candidate.evaluate_candidate(observations, self.registry)
        self.assertEqual(result["model_state"], "BLOCKED")
        self.assertIn("L6_CVD_20D_SHARE_AS_OF_INVALID", result["blocked_reasons"])

    def test_only_v110_adapter_may_reference_candidate_registry_without_importing_research_code(self):
        mentions = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "candidate_model" in text or "CRT_SIX_LAYER_CANDIDATE" in text:
                mentions.append(str(path.relative_to(ROOT)))
                self.assertNotIn("from research", text)
                self.assertNotIn("import research", text)
        self.assertEqual(mentions, [str(Path("src") / "crt_radar" / "v110_candidate.py")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
