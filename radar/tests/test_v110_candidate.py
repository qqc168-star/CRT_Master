from __future__ import annotations

import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from crt_radar.observation_store import Observation, ObservationStore
from crt_radar.v110_candidate import (
    evaluate_v110_candidate,
    load_contract,
    load_locked_registry,
    validate_contract,
)


CURRENT_MS = 2_000_000_000_000


def _base_value(feature: dict) -> float:
    bounds = feature.get("valid_range", {})
    if "minimum_exclusive" in bounds:
        return float(bounds["minimum_exclusive"]) + 2.0
    if bounds.get("minimum_inclusive") == 0:
        return 1.0
    return 0.0


def _history_values(feature: dict) -> list[float]:
    transform = feature["transform"]
    count = transform["minimum_history_observations"]
    base = _base_value(feature)
    midpoint = (count - 1) / 2
    bounds = feature.get("valid_range", {})
    half_span = 0.5 if bounds else max(1.0, midpoint * 0.1)
    step = half_span / max(1.0, midpoint)
    return [base + (index - midpoint) * step for index in range(count)]


def _metric_item(binding: dict, value: float) -> dict:
    return {
        "value": value,
        "as_of_ms": CURRENT_MS,
        "input_family": binding["input_family"],
        "source_id": binding["allowed_source_ids"][0],
        "quality_state": "VALID_FRESH",
        "evidence_hash": hashlib.sha256(binding["feature_id"].encode()).hexdigest(),
    }


def _complete_surface(
    store: ObservationStore,
    contract: dict,
    registry: dict,
    *,
    populate_history: bool,
) -> dict:
    feature_index = {
        feature["feature_id"]: feature
        for layer in registry["layers"]
        for feature in layer["features"]
    }
    layers = {
        layer_id: {"status": "VALID", "metrics": {}}
        for layer_id in ("L1", "L2", "L3", "L4", "L5", "L6")
    }
    history_rows: list[Observation] = []
    for binding in contract["feature_bindings"]:
        feature = feature_index[binding["feature_id"]]
        layers[binding["layer_id"]]["metrics"][binding["metric"]] = _metric_item(
            binding,
            _base_value(feature),
        )
        if populate_history and feature["transform"]["type"] != "TANH_FIXED":
            values = _history_values(feature)
            for index, value in enumerate(values):
                history_rows.append(
                    Observation(
                        layer_id=f"AS-{binding['layer_id']}",
                        input_family=binding["input_family"],
                        metric=binding["metric"],
                        as_of_ms=CURRENT_MS - (len(values) - index) * 86_400_000,
                        value_num=value,
                        source_id=binding["allowed_source_ids"][0],
                        quality_state="VALID_FRESH",
                        evidence_hash=hashlib.sha256(
                            f"{binding['feature_id']}:{index}".encode()
                        ).hexdigest(),
                        registry_hash="1" * 64,
                        recorded_run_id=f"history-{binding['feature_id']}-{index}",
                        recorded_at_ms=CURRENT_MS - 1,
                    )
                )
    if history_rows:
        store.record(history_rows)

    validation = contract["validation_bindings"][0]
    mvrv = layers["L5"]["metrics"]["mvrv"]["value"]
    layers["L5"]["metrics"][validation["metric"]] = {
        "value": 1.0 - 1.0 / mvrv,
        "as_of_ms": CURRENT_MS,
        "input_family": validation["input_family"],
        "source_id": validation["allowed_source_ids"][0],
        "quality_state": "VALID_FRESH",
        "evidence_hash": hashlib.sha256(b"L5_NUPL_OBSERVED").hexdigest(),
    }
    return layers


class V110FormalCandidateTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_contract()
        self.registry = load_locked_registry()

    def test_contract_binds_exact_locked_constants_and_parent_registry(self):
        self.assertEqual(validate_contract(self.contract, self.registry), [])
        self.assertEqual(self.contract["status"], "FORMAL_CANDIDATE_NOT_APPROVED")
        self.assertEqual(
            self.contract["inherited_formal_constants"]["layer_weights_percent"],
            {"L1": 20, "L2": 20, "L3": 17, "L4": 25, "L5": 13, "L6": 5},
        )
        self.assertEqual(
            self.contract["inherited_formal_constants"]["light_thresholds"],
            [-60, -35, 35, 60],
        )
        self.assertEqual(
            self.contract["inherited_formal_constants"]["mnav_semantics"],
            "Diluted Equity mNAV",
        )
        self.assertEqual(self.contract["approval"]["formal_model"], "NOT_APPROVED")
        self.assertEqual(self.contract["approval"]["production"], "NOT_APPROVED")
        self.assertEqual(self.contract["approval"]["external_action_authority"], "NONE")

    def test_complete_neutral_surface_replays_candidate_score_but_not_formal_score(self):
        with tempfile.TemporaryDirectory() as td:
            with ObservationStore(Path(td) / "observations.sqlite3") as store:
                layers = _complete_surface(
                    store,
                    self.contract,
                    self.registry,
                    populate_history=True,
                )
                first = evaluate_v110_candidate(layers, store)
                second = evaluate_v110_candidate(deepcopy(layers), store)

        self.assertEqual(first, second)
        self.assertEqual(first["input_state"], "COMPLETE")
        self.assertEqual(first["model_state"], "VALID_CANDIDATE_OUTPUT")
        self.assertEqual(first["candidate_score"], 0.0)
        self.assertEqual(first["threshold_bucket"], "C2_MIXED")
        self.assertIsNone(first["formal_score"])
        self.assertEqual(first["formal_model"], "NOT_APPROVED")
        self.assertEqual(first["production"], "NOT_APPROVED")
        self.assertIsNone(first["season"])
        self.assertEqual(first["season_router"]["state"], "BLOCKED")
        self.assertEqual(
            first["season_router"]["reason"],
            "V110_SEASON_STATE_TRANSITION_CONTRACT_NOT_RECOVERED",
        )
        self.assertEqual(first["season_router"]["candidate_weather_bucket"], "C2_MIXED")
        self.assertEqual(first["action_output"], "NONE")
        self.assertEqual(first["external_action_authority"], "NONE")
        self.assertFalse(first["external_action_performed"])

    def test_missing_l3_etp_blocks_without_reweighting(self):
        with tempfile.TemporaryDirectory() as td:
            with ObservationStore(Path(td) / "observations.sqlite3") as store:
                layers = _complete_surface(
                    store,
                    self.contract,
                    self.registry,
                    populate_history=True,
                )
                del layers["L3"]["metrics"]["spot_btc_etp_flow_20d_pct_aum"]
                result = evaluate_v110_candidate(layers, store)

        self.assertEqual(result["input_state"], "BLOCKED")
        self.assertEqual(result["model_state"], "BLOCKED")
        self.assertIsNone(result["candidate_score"])
        self.assertIn(
            "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM_METRIC_MISSING",
            result["input_blocked_reasons"],
        )
        self.assertIn(
            "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM_MISSING",
            result["scoring_blocked_reasons"],
        )

    def test_l6_proxy_is_not_accepted_as_formal_candidate_composite(self):
        with tempfile.TemporaryDirectory() as td:
            with ObservationStore(Path(td) / "observations.sqlite3") as store:
                layers = _complete_surface(
                    store,
                    self.contract,
                    self.registry,
                    populate_history=True,
                )
                for item in layers["L6"]["metrics"].values():
                    item["input_family"] = "PRICE_STRUCTURE_CONTEXT"
                    item["source_id"] = "CRT-CONN-BTC-SPOT-PRICE-STRUCTURE-PROXY-001"
                result = evaluate_v110_candidate(layers, store)

        self.assertEqual(result["input_state"], "BLOCKED")
        self.assertIsNone(result["candidate_score"])
        self.assertTrue(
            any(reason.startswith("L6_") and reason.endswith("_SOURCE_NOT_APPROVED")
                for reason in result["input_blocked_reasons"])
        )
        self.assertIsNone(result["season"])

    def test_complete_current_inputs_still_block_when_history_is_insufficient(self):
        with tempfile.TemporaryDirectory() as td:
            with ObservationStore(Path(td) / "observations.sqlite3") as store:
                layers = _complete_surface(
                    store,
                    self.contract,
                    self.registry,
                    populate_history=False,
                )
                result = evaluate_v110_candidate(layers, store)

        self.assertEqual(result["input_state"], "COMPLETE")
        self.assertEqual(result["model_state"], "BLOCKED")
        self.assertTrue(
            any(reason.endswith("_HISTORY_INSUFFICIENT") for reason in result["scoring_blocked_reasons"])
        )
        self.assertIsNone(result["candidate_score"])

    def test_constant_drift_and_season_promotion_are_rejected(self):
        changed = deepcopy(self.contract)
        changed["candidate_id"] = "OTHER"
        changed["base_main_sha"] = "0" * 40
        changed["parent_research_registry"]["path"] = "research/other.json"
        changed["inherited_formal_constants"]["source"] = "RELEASE/other.md"
        changed["inherited_formal_constants"]["layer_weights_percent"]["L1"] = 21
        changed["season_router"]["score_may_determine_btc_season"] = True
        errors = validate_contract(changed, self.registry)
        self.assertIn("candidate id changed", errors)
        self.assertIn("candidate base main SHA changed", errors)
        self.assertIn("parent registry path changed", errors)
        self.assertIn("formal seal source changed", errors)
        self.assertIn("V1.10 layer weights changed", errors)
        self.assertIn("candidate score cannot determine BTC season", errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
