from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.reanalysis_wake import fuse_reanalysis_wake


FIELD = "mstr_asst_relative_value_validation_status"


def authority() -> dict:
    return {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def no_wake() -> dict:
    return {
        "state": "NO_WAKE",
        "reason": "CHANGE_WITHIN_INTRADAY_HISTORY",
        "metric": "btc_spot_price_usd",
        "input_family": "BTC_SPOT_PRICE",
        "current_value": 77084.0,
        "previous_value": 76318.0,
        "percent_change": 1.0037,
        "historical_percentile": 50.0,
        "baseline_count": 20,
        "operational_percentile": 95.0,
        "analyst_reanalysis_requested": False,
        **authority(),
    }


def market_wake() -> dict:
    return {
        "state": "REANALYSIS_REQUESTED",
        "reason": "MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY",
        "metric": "btc_spot_price_usd",
        "input_family": "BTC_SPOT_PRICE",
        "current_value": 72000.0,
        "previous_value": 77000.0,
        "percent_change": -6.4935,
        "historical_percentile": 99.0,
        "baseline_count": 20,
        "operational_percentile": 95.0,
        "analyst_reanalysis_requested": True,
        **authority(),
    }


def plan_drift(requested: bool) -> dict:
    return {
        "state": (
            "REANALYSIS_REQUIRED"
            if requested
            else "STABLE"
        ),
        "reason": (
            "ACTIVE_PLAN_CONDITION_VIOLATED"
            if requested
            else "ACTIVE_PLAN_CONDITIONS_SATISFIED"
        ),
        "reanalysis_required": requested,
        "violated_condition_count": 3 if requested else 0,
        **authority(),
    }


def private_context(value: str) -> dict:
    condition = {
        "field": FIELD,
        "operator": "EQ",
        "value": "NOT_YET_VALIDATED",
    }

    tranches = []

    for index in range(1, 4):
        tranches.append(
            {
                "tranche_id": f"T{index}",
                "status": "PENDING",
                "validity_conditions": [dict(condition)],
            }
        )

    return {
        "state": "AVAILABLE",
        "profile": {
            "capital_state": {
                FIELD: value,
            },
            "plans": [
                {
                    "plan_id": "ATTACK_CAPITAL_WAIT",
                    "asset": "USD",
                    "side": "WAIT",
                    "status": "ACTIVE",
                    "tranches": tranches,
                }
            ],
        },
    }


def minimal_source_gate() -> dict:
    return {
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "formal_state": "BLOCKED",
        "blocked_reasons": ["WAKE_FUSION_TEST"],
        "evidence": [],
        "parsed": {},
        "runtime_checks": [],
        "source_registry_hash": "0" * 64,
        "run_id": "WAKE-FUSION-TEST",
        "idempotency_key": "WAKE-FUSION-TEST",
    }


class WakeFusionTests(unittest.TestCase):

    def test_stable_plan_does_not_create_wake(self) -> None:
        result = fuse_reanalysis_wake(
            no_wake(),
            plan_drift=plan_drift(False),
        )

        self.assertIsNotNone(result)
        assert result is not None

        self.assertEqual(result["state"], "NO_WAKE")
        self.assertFalse(
            result["analyst_reanalysis_requested"]
        )
        self.assertEqual(result["wake_sources"], [])
        self.assertEqual(
            result["plan_drift_state"],
            "STABLE",
        )

    def test_plan_drift_promotes_no_wake(self) -> None:
        result = fuse_reanalysis_wake(
            no_wake(),
            plan_drift=plan_drift(True),
        )

        self.assertIsNotNone(result)
        assert result is not None

        self.assertEqual(
            result["state"],
            "REANALYSIS_REQUESTED",
        )
        self.assertEqual(
            result["reason"],
            "ACTIVE_PLAN_CONDITION_VIOLATED",
        )
        self.assertEqual(
            result["wake_sources"],
            ["PLAN_DRIFT"],
        )
        self.assertTrue(
            result["analyst_reanalysis_requested"]
        )
        self.assertEqual(
            result["external_action_authority"],
            "NONE",
        )
        self.assertEqual(
            result["action_output"],
            "NONE",
        )

    def test_existing_market_wake_remains_primary(self) -> None:
        result = fuse_reanalysis_wake(
            market_wake(),
            plan_drift=plan_drift(True),
        )

        self.assertIsNotNone(result)
        assert result is not None

        self.assertEqual(
            result["state"],
            "REANALYSIS_REQUESTED",
        )
        self.assertEqual(
            result["reason"],
            "MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY",
        )
        self.assertEqual(
            result["wake_sources"],
            ["BTC_INTRADAY", "PLAN_DRIFT"],
        )

    def test_evidence_pack_fuses_plan_drift_before_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(
                minimal_source_gate(),
                observation_db=(
                    Path(td) / "observations.sqlite3"
                ),
                generated_at_ms=1_700_000_000_000,
                private_context=private_context("VALIDATED"),
                reanalysis_wake=no_wake(),
            )

        self.assertEqual(
            pack["plan_drift"]["state"],
            "REANALYSIS_REQUIRED",
        )

        wake = pack["reanalysis_wake"]

        self.assertEqual(
            wake["state"],
            "REANALYSIS_REQUESTED",
        )
        self.assertEqual(
            wake["wake_sources"],
            ["PLAN_DRIFT"],
        )
        self.assertTrue(
            wake["plan_drift_reanalysis_required"]
        )
        self.assertIn("evidence_pack_hash", pack)
        self.assertEqual(
            wake["external_action_authority"],
            "NONE",
        )


if __name__ == "__main__":
    unittest.main()
