from __future__ import annotations

import importlib.util
import json
import math
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
MODULE_PATH = RESEARCH / "candidate_data.py"
MODEL_REGISTRY_PATH = RESEARCH / "CRT_SIX_LAYER_CANDIDATE_V0.1.json"
SOURCE_CONTRACT_PATH = RESEARCH / "CRT_CANDIDATE_SOURCE_CONTRACT_V0.2.json"
PROTOCOL_PATH = RESEARCH / "CRT_CANDIDATE_WALK_FORWARD_PROTOCOL_V0.2.json"

spec = importlib.util.spec_from_file_location("candidate_data", MODULE_PATH)
candidate_data = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(candidate_data)


DAY_MS = 86_400_000
HOUR_MS = 3_600_000
BASE_MS = 1_900_000_000_000


def _point(observed_at_ms: int, value: float, *, period: str | None = None) -> dict:
    item = {
        "observed_at_ms": observed_at_ms,
        "available_at_ms": observed_at_ms + HOUR_MS,
        "value": value,
    }
    if period is not None:
        item["period"] = period
    return item


def _daily(values: list[float], *, step_ms: int = DAY_MS) -> list[dict]:
    start = BASE_MS - (len(values) - 1) * step_ms
    return [_point(start + index * step_ms, value) for index, value in enumerate(values)]


def _monthly(values: list[float], *, start_year: int = 2024, start_month: int = 1) -> list[dict]:
    result = []
    for index, value in enumerate(values):
        absolute_month = start_year * 12 + start_month - 1 + index
        year, month_zero = divmod(absolute_month, 12)
        period = f"{year:04d}-{month_zero + 1:02d}"
        result.append(
            _point(
                BASE_MS - (len(values) - 1 - index) * 30 * DAY_MS,
                value,
                period=period,
            )
        )
    return result


def _raw_fixture() -> tuple[int, dict]:
    as_of_ms = BASE_MS + 2 * HOUR_MS
    stablecoin_rows = []
    for observed_at_ms, values in (
        (BASE_MS - 30 * DAY_MS, {"USDC": 100.0, "USDT": 200.0}),
        (BASE_MS, {"USDC": 110.0, "USDT": 220.0}),
    ):
        for asset_id, value in values.items():
            stablecoin_rows.append(
                {
                    **_point(observed_at_ms, value),
                    "asset_id": asset_id,
                }
            )

    etp_rows = []
    for day_index in range(21):
        observed_at_ms = BASE_MS - (20 - day_index) * DAY_MS
        for fund_id, base_shares, nav in (
            ("FUND_A", 100.0, 10.0),
            ("FUND_B", 200.0, 20.0),
        ):
            etp_rows.append(
                {
                    "observed_at_ms": observed_at_ms,
                    "available_at_ms": observed_at_ms + HOUR_MS,
                    "fund_id": fund_id,
                    "adjusted_shares_outstanding": base_shares + day_index,
                    "nav_per_share": nav,
                    "net_assets": (base_shares + day_index) * nav,
                }
            )

    ohlcv_rows = []
    for index in range(201):
        close = 100.0 + index
        observed_at_ms = BASE_MS - (200 - index) * DAY_MS
        ohlcv_rows.append(
            {
                "observed_at_ms": observed_at_ms,
                "available_at_ms": observed_at_ms + HOUR_MS,
                "open": close - 1.0,
                "high": close + 2.0,
                "low": close - 2.0,
                "close": close,
                "volume": 1_000.0,
                "complete": True,
            }
        )

    aggressor_rows = []
    for index in range(20):
        observed_at_ms = BASE_MS - (19 - index) * DAY_MS
        aggressor_rows.append(
            {
                "observed_at_ms": observed_at_ms,
                "available_at_ms": observed_at_ms + HOUR_MS,
                "buyer_initiated_quote_volume": 60.0,
                "seller_initiated_quote_volume": 40.0,
                "unknown_aggressor_quote_volume": 0.0,
                "total_quote_volume": 100.0,
                "complete": True,
            }
        )

    raw = {
        "schema_version": "CRT_CANDIDATE_RAW_INPUT_V0.2",
        "series": {
            "CPILFESL": _monthly([100.0 + index for index in range(13)]),
            "UNRATE": _monthly([4.0 + 0.1 * index for index in range(15)]),
            "EFFR": _daily([5.0]),
            "PCEPILFE": _monthly([100.0 + index for index in range(13)]),
            "DTWEXBGS": _daily([100.0 + index for index in range(21)]),
            "DFII10": _daily([2.0 + 0.01 * index for index in range(21)]),
            "DGS2": _daily([4.0 + 0.01 * index for index in range(21)]),
            "BAMLH0A0HYM2": _daily([3.0 + 0.01 * index for index in range(21)]),
            "OPEN_INTEREST_NOTIONAL_USD": _daily([5_000_000.0]),
            "MARKET_CAP_USD": _daily([1_000_000_000_000.0]),
            "FUNDING_RATE": _daily([0.0001] * 9, step_ms=8 * HOUR_MS),
            "CAP_MARKET_USD": _daily([300.0, 600.0], step_ms=30 * DAY_MS),
            "CAP_REALIZED_USD": _daily([300.0, 330.0], step_ms=30 * DAY_MS),
        },
        "tables": {
            "STABLECOIN_CAP": stablecoin_rows,
            "SPOT_BTC_ETP": etp_rows,
            "OHLCV_DAILY": ohlcv_rows,
            "AGGRESSOR_DAILY": aggressor_rows,
        },
        "liquidation_24h": {
            "window_end_ms": BASE_MS,
            "available_at_ms": BASE_MS + HOUR_MS,
            "coverage_state": "VERIFIED_COMPLETE",
            "long_liquidation_usd": 400_000.0,
            "short_liquidation_usd": 600_000.0,
            "total_liquidation_usd": 1_000_000.0,
        },
        "parameters": {
            "approved_stablecoin_ids": ["USDC", "USDT"],
            "stablecoin_universe_version": "TEST_ONLY_V1",
            "approved_etp_ids": ["FUND_A", "FUND_B"],
            "etp_universe_version": "TEST_ONLY_V1",
            "cross_source_alignment_tolerance_ms": 5 * 60_000,
        },
    }
    return as_of_ms, raw


class ResearchCandidateDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_registry = json.loads(MODEL_REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.source_contract = candidate_data.load_json(SOURCE_CONTRACT_PATH)
        cls.protocol = candidate_data.load_json(PROTOCOL_PATH)

    def test_source_contract_covers_all_features_and_preserves_authority(self):
        self.assertEqual(
            candidate_data.validate_source_contract(self.source_contract, self.model_registry),
            [],
        )
        model_features = {
            feature["feature_id"]
            for layer in self.model_registry["layers"]
            for feature in layer["features"]
        }
        contract_features = set(self.source_contract["feature_sources"])
        self.assertEqual(len(model_features), 19)
        self.assertEqual(contract_features, model_features)
        self.assertEqual(self.source_contract["status"], "RESEARCH_ONLY_NOT_APPROVED")
        self.assertEqual(self.source_contract["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(self.source_contract["authority"]["external_action_authority"], "NONE")
        self.assertFalse(self.source_contract["authority"]["external_action_performed"])

    def test_walk_forward_protocol_is_frozen_but_not_started(self):
        self.assertEqual(
            candidate_data.validate_walk_forward_protocol(
                self.protocol,
                self.source_contract,
                self.model_registry,
            ),
            [],
        )
        self.assertEqual(self.protocol["status"], "PREREGISTERED_RESEARCH_ONLY_NOT_STARTED")
        self.assertEqual(self.protocol["retrospective_role"], "EXPLORATORY_FALSIFICATION_ONLY")
        self.assertEqual(self.protocol["promotion"]["automatic_promotion"], False)
        self.assertEqual(self.protocol["promotion"]["capital_decision_authority"], "USER_ONLY")

    def test_walk_forward_readiness_fails_closed_without_sources_or_history(self):
        result = candidate_data.assess_walk_forward_readiness(
            self.source_contract,
            self.protocol,
            dataset_manifest=None,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(len(result["blocked_reasons"]), 10)
        self.assertIn("POINT_IN_TIME_DATASET_MISSING", result["blocked_reasons"])
        self.assertFalse(any("APPROVAL_REQUIRED" in item for item in result["blocked_reasons"]))
        self.assertIsNone(result["walk_forward_result"])
        self.assertEqual(result["external_action_authority"], "NONE")

    def test_all_nineteen_raw_feature_calculators_replay_exactly(self):
        as_of_ms, raw = _raw_fixture()
        expected = {
            "L1_CORE_INFLATION_ACCELERATION": 100 * ((112 / 109) ** 4 - 1) - 12,
            "L1_UNEMPLOYMENT_DETERIORATION": 1.2,
            "L1_REAL_POLICY_RATE": -7.0,
            "L2_BROAD_USD_20D_LOG_CHANGE": 100 * math.log(120 / 100),
            "L2_REAL_10Y_YIELD_20D_CHANGE_BP": 20.0,
            "L2_NOMINAL_2Y_YIELD_20D_CHANGE_BP": 20.0,
            "L3_STABLECOIN_SUPPLY_30D_LOG_CHANGE": 100 * math.log(330 / 300),
            "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM": 12.0,
            "L3_HIGH_YIELD_OAS_20D_CHANGE_BP": 20.0,
            "L4_OI_TO_MARKET_CAP": 0.0005,
            "L4_ABS_FUNDING_3D_MEAN_BP": 1.0,
            "L4_LIQUIDATION_INTENSITY_24H": 20.0,
            "L4_SHORT_MINUS_LONG_LIQUIDATION_SHARE_24H": 0.2,
            "L5_MVRV_LEVEL": 600 / 330,
            "L5_REALIZED_CAP_30D_LOG_CHANGE": 100 * math.log(330 / 300),
            "L6_CLOSE_MINUS_SMA200_OVER_ATR20": 24.875,
            "L6_SMA50_MINUS_SMA200_OVER_ATR20": 18.75,
            "L6_RETURN_20D_OVER_ATR_VOL": math.log(300 / 280) / ((4 / 300) * math.sqrt(20)),
            "L6_CVD_20D_SHARE": 0.2,
        }
        self.assertEqual(len(expected), 19)
        for feature_id, expected_value in expected.items():
            with self.subTest(feature_id=feature_id):
                result = candidate_data.calculate_feature(
                    feature_id,
                    raw,
                    as_of_ms=as_of_ms,
                    source_contract=self.source_contract,
                    model_registry=self.model_registry,
                )
                self.assertEqual(result["state"], "MECHANICALLY_CALCULATED_RESEARCH_ONLY")
                self.assertTrue(
                    math.isclose(result["value"], expected_value, rel_tol=1e-10, abs_tol=1e-10),
                    (feature_id, result["value"], expected_value),
                )
                self.assertEqual(result["authority"]["production"], "NOT_APPROVED")
                self.assertEqual(result["authority"]["external_action_authority"], "NONE")
                self.assertEqual(len(result["public_source_authority_hash"]), 64)
                self.assertEqual(len(result["source_contract_hash"]), 64)
                self.assertEqual(len(result["raw_input_hash"]), 64)
                self.assertEqual(len(result["observation_hash"]), 64)

    def test_future_revision_is_not_visible_before_availability(self):
        as_of_ms, raw = _raw_fixture()
        baseline = candidate_data.calculate_feature(
            "L2_BROAD_USD_20D_LOG_CHANGE",
            raw,
            as_of_ms=as_of_ms,
            source_contract=self.source_contract,
            model_registry=self.model_registry,
        )
        changed = deepcopy(raw)
        current = changed["series"]["DTWEXBGS"][-1]
        changed["series"]["DTWEXBGS"].append(
            {
                **current,
                "available_at_ms": as_of_ms + 1,
                "value": 999.0,
            }
        )
        replay = candidate_data.calculate_feature(
            "L2_BROAD_USD_20D_LOG_CHANGE",
            changed,
            as_of_ms=as_of_ms,
            source_contract=self.source_contract,
            model_registry=self.model_registry,
        )
        self.assertEqual(replay["value"], baseline["value"])

    def test_latest_available_revision_wins_only_after_release(self):
        as_of_ms, raw = _raw_fixture()
        current = raw["series"]["CAP_MARKET_USD"][-1]
        raw["series"]["CAP_MARKET_USD"].append(
            {
                **current,
                "available_at_ms": as_of_ms + 1,
                "value": 990.0,
            }
        )
        before = candidate_data.calculate_feature(
            "L5_MVRV_LEVEL",
            raw,
            as_of_ms=as_of_ms,
            source_contract=self.source_contract,
            model_registry=self.model_registry,
        )
        after = candidate_data.calculate_feature(
            "L5_MVRV_LEVEL",
            raw,
            as_of_ms=as_of_ms + 2,
            source_contract=self.source_contract,
            model_registry=self.model_registry,
        )
        self.assertEqual(before["value"], round(600 / 330, 10))
        self.assertEqual(after["value"], 3.0)

    def test_protocol_rejects_source_contract_hash_drift(self):
        changed = deepcopy(self.source_contract)
        changed["source_contracts"]["FRED_MACRO_VINTAGE"]["provider"] = "DRIFTED"
        errors = candidate_data.validate_walk_forward_protocol(
            self.protocol,
            changed,
            self.model_registry,
        )
        self.assertIn("walk-forward source_contract_hash mismatch", errors)

    def test_source_contract_rejects_alignment_tolerance_drift(self):
        changed = deepcopy(self.source_contract)
        changed["calculation_locks"]["cross_source_alignment_tolerance_ms"] = 86_400_000
        errors = candidate_data.validate_source_contract(changed, self.model_registry)
        self.assertIn("calculation lock cross_source_alignment_tolerance_ms drift", errors)

        as_of_ms, raw = _raw_fixture()
        raw["parameters"]["cross_source_alignment_tolerance_ms"] = 86_400_000
        with self.assertRaisesRegex(
            candidate_data.CandidateDataError,
            "CROSS_SOURCE_ALIGNMENT_TOLERANCE_NOT_LOCKED",
        ):
            candidate_data.calculate_feature(
                "L4_OI_TO_MARKET_CAP",
                raw,
                as_of_ms=as_of_ms,
                source_contract=self.source_contract,
                model_registry=self.model_registry,
            )

    def test_unverified_zero_liquidation_window_is_rejected(self):
        as_of_ms, raw = _raw_fixture()
        raw["liquidation_24h"].update(
            {
                "coverage_state": "UNKNOWN",
                "long_liquidation_usd": 0.0,
                "short_liquidation_usd": 0.0,
                "total_liquidation_usd": 0.0,
            }
        )
        with self.assertRaisesRegex(
            candidate_data.CandidateDataError,
            "LIQUIDATION_ZERO_REQUIRES_VERIFIED_COMPLETE_COVERAGE",
        ):
            candidate_data.calculate_feature(
                "L4_SHORT_MINUS_LONG_LIQUIDATION_SHARE_24H",
                raw,
                as_of_ms=as_of_ms,
                source_contract=self.source_contract,
                model_registry=self.model_registry,
            )

    def test_unknown_aggressor_volume_blocks_cvd(self):
        as_of_ms, raw = _raw_fixture()
        raw["tables"]["AGGRESSOR_DAILY"][-1]["unknown_aggressor_quote_volume"] = 1.0
        with self.assertRaisesRegex(
            candidate_data.CandidateDataError,
            "CVD_UNKNOWN_AGGRESSOR_VOLUME",
        ):
            candidate_data.calculate_feature(
                "L6_CVD_20D_SHARE",
                raw,
                as_of_ms=as_of_ms,
                source_contract=self.source_contract,
                model_registry=self.model_registry,
            )

    def test_monthly_gap_blocks_instead_of_using_positional_lag(self):
        as_of_ms, raw = _raw_fixture()
        raw["series"]["CPILFESL"][-2]["period"] = "2099-12"
        with self.assertRaisesRegex(
            candidate_data.CandidateDataError,
            "CPILFESL_MONTHLY_PERIOD_GAP",
        ):
            candidate_data.calculate_feature(
                "L1_CORE_INFLATION_ACCELERATION",
                raw,
                as_of_ms=as_of_ms,
                source_contract=self.source_contract,
                model_registry=self.model_registry,
            )

    def test_runtime_source_does_not_import_candidate_data(self):
        mentions = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "candidate_data" in text or "CRT_CANDIDATE_SOURCE_CONTRACT" in text:
                mentions.append(str(path.relative_to(ROOT)))
        self.assertEqual(mentions, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
