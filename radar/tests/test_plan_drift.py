from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.plan_drift import evaluate_plan_drift


FIELD = "mstr_asst_relative_value_validation_status"


def wait_context(
    value: str = "NOT_YET_VALIDATED",
) -> dict:
    condition = {
        "field": FIELD,
        "operator": "EQ",
        "value": "NOT_YET_VALIDATED",
    }

    return {
        "state": "AVAILABLE",
        "profile": {
            "capital_state": {
                "contract_version": "CRT_CAPITAL_STATE_V0.1",
                "source": "USER_CONFIRMED",
                "base_currency": "USD",
                FIELD: value,
            },
            "plans": [
                {
                    "plan_id": "ATTACK_CAPITAL_WAIT",
                    "asset": "USD",
                    "side": "WAIT",
                    "status": "ACTIVE",
                    "tranches": [
                        {
                            "tranche_id": "T1",
                            "status": "PENDING",
                            "validity_conditions": [
                                copy.deepcopy(condition)
                            ],
                        },
                        {
                            "tranche_id": "T2",
                            "status": "PENDING",
                            "validity_conditions": [
                                copy.deepcopy(condition)
                            ],
                        },
                        {
                            "tranche_id": "T3",
                            "status": "PENDING",
                            "validity_conditions": [
                                copy.deepcopy(condition)
                            ],
                        },
                    ],
                }
            ],
        },
    }


def btc_context() -> dict:
    context = wait_context()

    plan = context["profile"]["plans"][0]
    plan["plan_id"] = "BTC_ENTRY"
    plan["asset"] = "BTC"
    plan["side"] = "BUY"

    for tranche in plan["tranches"]:
        tranche["validity_conditions"] = [
            {
                "field": "btc_spot_price_usd",
                "operator": "LTE",
                "value": 80000,
            }
        ]

    return context


def minimal_source_gate() -> dict:
    return {
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "formal_state": "BLOCKED",
        "blocked_reasons": [
            "PLAN_DRIFT_INTEGRATION_TEST"
        ],
        "evidence": [],
        "parsed": {},
        "runtime_checks": [],
        "source_registry_hash": "0" * 64,
        "run_id": "PLAN-DRIFT-TEST",
        "idempotency_key": "PLAN-DRIFT-TEST",
    }


class PlanDriftTests(unittest.TestCase):
    def test_current_wait_plan_is_stable(self) -> None:
        result = evaluate_plan_drift(
            private_context=wait_context(),
            layers={},
        )

        self.assertEqual(result["state"], "STABLE")
        self.assertFalse(result["reanalysis_required"])
        self.assertEqual(result["condition_count"], 3)
        self.assertEqual(
            result["satisfied_condition_count"],
            3,
        )
        self.assertEqual(
            result["violated_condition_count"],
            0,
        )
        self.assertEqual(
            result["blocked_condition_count"],
            0,
        )

        rows = result["plans"][0]["conditions"]

        self.assertTrue(
            all(
                row["source_kind"] == "CAPITAL_STATE"
                for row in rows
            )
        )

        self.assertEqual(
            result["external_action_authority"],
            "NONE",
        )
        self.assertEqual(
            result["action_output"],
            "NONE",
        )

    def test_changed_decision_state_requires_reanalysis(self) -> None:
        result = evaluate_plan_drift(
            private_context=wait_context("VALIDATED"),
            layers={},
        )

        self.assertEqual(
            result["state"],
            "REANALYSIS_REQUIRED",
        )
        self.assertTrue(result["reanalysis_required"])
        self.assertEqual(
            result["violated_condition_count"],
            3,
        )

    def test_market_metric_source_can_be_stable(self) -> None:
        layers = {
            "L3": {
                "metrics": {
                    "btc_spot_price_usd": {
                        "value": 76318.0,
                    }
                }
            }
        }

        result = evaluate_plan_drift(
            private_context=btc_context(),
            layers=layers,
        )

        self.assertEqual(result["state"], "STABLE")

        rows = result["plans"][0]["conditions"]

        self.assertTrue(
            all(
                row["source_kind"] == "MARKET_METRIC"
                for row in rows
            )
        )

    def test_market_metric_violation_requires_reanalysis(self) -> None:
        context = btc_context()

        for tranche in context["profile"]["plans"][0]["tranches"]:
            tranche["validity_conditions"][0]["value"] = 70000

        layers = {
            "L3": {
                "metrics": {
                    "btc_spot_price_usd": {
                        "value": 76318.0,
                    }
                }
            }
        }

        result = evaluate_plan_drift(
            private_context=context,
            layers=layers,
        )

        self.assertEqual(
            result["state"],
            "REANALYSIS_REQUIRED",
        )
        self.assertEqual(
            result["violated_condition_count"],
            3,
        )

    def test_unbound_source_fails_closed(self) -> None:
        context = wait_context()

        del context["profile"]["capital_state"][FIELD]

        result = evaluate_plan_drift(
            private_context=context,
            layers={},
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertIsNone(result["reanalysis_required"])
        self.assertEqual(
            result["blocked_condition_count"],
            3,
        )

    def test_ambiguous_source_fails_closed(self) -> None:
        layers = {
            "L3": {
                "metrics": {
                    FIELD: {
                        "value": "NOT_YET_VALIDATED",
                    }
                }
            }
        }

        result = evaluate_plan_drift(
            private_context=wait_context(),
            layers=layers,
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(
            result["blocked_condition_count"],
            3,
        )

    def test_missing_private_context_fails_closed(self) -> None:
        result = evaluate_plan_drift(
            private_context=None,
            layers={},
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(
            result["reason"],
            "PRIVATE_CONTEXT_UNAVAILABLE",
        )

    def test_no_active_plan_is_not_drift(self) -> None:
        context = wait_context()
        context["profile"]["plans"][0]["status"] = "COMPLETE"

        result = evaluate_plan_drift(
            private_context=context,
            layers={},
        )

        self.assertEqual(
            result["state"],
            "NO_ACTIVE_PLAN",
        )
        self.assertFalse(
            result["reanalysis_required"]
        )

    def test_evidence_pack_contains_stable_plan_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "observations.sqlite3"

            pack = build_evidence_pack(
                minimal_source_gate(),
                observation_db=db,
                generated_at_ms=1_700_000_000_000,
                private_context=wait_context(),
                dvol_regime_watch={
                    "state": "TEST_DVOL_STATE",
                },
            )

        self.assertIn(
            "plan_drift",
            pack,
        )
        self.assertEqual(
            pack["plan_drift"]["state"],
            "STABLE",
        )
        self.assertEqual(
            pack["plan_drift"][
                "satisfied_condition_count"
            ],
            3,
        )
        self.assertEqual(
            pack["plan_drift"][
                "violated_condition_count"
            ],
            0,
        )
        self.assertFalse(
            pack["plan_drift"][
                "reanalysis_required"
            ]
        )

        self.assertEqual(
            pack["dvol_regime_watch"],
            {
                "state": "TEST_DVOL_STATE",
            },
        )

        self.assertIn(
            "evidence_pack_hash",
            pack,
        )

    def test_evidence_pack_plan_drift_fails_closed_without_private_context(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "observations.sqlite3"

            pack = build_evidence_pack(
                minimal_source_gate(),
                observation_db=db,
                generated_at_ms=1_700_000_000_000,
            )

        self.assertIn(
            "plan_drift",
            pack,
        )
        self.assertEqual(
            pack["plan_drift"]["state"],
            "BLOCKED",
        )
        self.assertEqual(
            pack["plan_drift"]["reason"],
            "PRIVATE_CONTEXT_UNAVAILABLE",
        )
        self.assertIsNone(
            pack["plan_drift"][
                "reanalysis_required"
            ]
        )

        self.assertEqual(
            pack["plan_drift"][
                "external_action_authority"
            ],
            "NONE",
        )
        self.assertEqual(
            pack["plan_drift"]["action_output"],
            "NONE",
        )


if __name__ == "__main__":
    unittest.main()
