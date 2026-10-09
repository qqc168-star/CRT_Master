from __future__ import annotations

import unittest
from copy import deepcopy

from crt_radar.observation_store import Observation
from crt_radar.reanalysis_wake import (
    apply_capital_reanalysis_wake, capital_state_identity,
    evaluate_intraday_reanalysis_wake, fuse_reanalysis_wake,
)
from crt_radar.broker_capital_observation import reconcile_capital
from tests.test_broker_capital_observation import NOW, order, synthetic_intent, synthetic_observation


def obs(index: int, value: float) -> Observation:
    return Observation(
        layer_id="AS-L3",
        input_family="BTC_SPOT_PRICE",
        metric="btc_spot_price_usd",
        as_of_ms=1_800_000_000_000 + index * 300_000,
        value_num=value,
        source_id="TEST-BTC-SPOT",
        quality_state="VALID_FRESH",
        evidence_hash=f"{index:064x}"[-64:],
        registry_hash="a" * 64,
        recorded_run_id=f"run-{index}",
        recorded_at_ms=1_800_000_000_000 + index * 300_000,
    )


class ReanalysisWakeTests(unittest.TestCase):

    def test_no_history_does_not_invent_wake(self):
        result = evaluate_intraday_reanalysis_wake(obs(1, 100.0), [])
        self.assertEqual(result.state, "NO_WAKE")
        self.assertEqual(result.reason, "NO_PRIOR_OBSERVATION")

    def test_insufficient_history_does_not_wake(self):
        history = [obs(i, 100 + i * 0.1) for i in range(5)]
        current = obs(5, 96.0)

        result = evaluate_intraday_reanalysis_wake(current, history)

        self.assertEqual(result.state, "NO_WAKE")
        self.assertEqual(result.reason, "INSUFFICIENT_INTRADAY_HISTORY")

    def test_large_relative_move_requests_reanalysis_only(self):
        values = [
            100.00,
            100.10,
            100.00,
            100.15,
            100.05,
            100.20,
            100.10,
            100.25,
            100.15,
            100.30,
        ]
        history = [obs(i, value) for i, value in enumerate(values)]
        current = obs(len(values), 96.0)

        result = evaluate_intraday_reanalysis_wake(
            current,
            history,
            minimum_baseline_count=8,
            operational_percentile=95.0,
        )

        self.assertEqual(result.state, "REANALYSIS_REQUESTED")
        payload = result.to_dict()
        self.assertTrue(payload["analyst_reanalysis_requested"])
        self.assertEqual(payload["action_output"], "NONE")

    def test_normal_move_stays_silent(self):
        values = [
            100.0,
            100.2,
            100.1,
            100.3,
            100.2,
            100.4,
            100.3,
            100.5,
            100.4,
            100.6,
        ]
        history = [obs(i, value) for i, value in enumerate(values)]
        current = obs(len(values), 100.7)

        result = evaluate_intraday_reanalysis_wake(
            current,
            history,
            minimum_baseline_count=8,
            operational_percentile=95.0,
        )

        self.assertEqual(result.state, "NO_WAKE")
        self.assertFalse(result.to_dict()["analyst_reanalysis_requested"])


class CapitalReanalysisWakeTests(unittest.TestCase):
    def reconciled(self, at=NOW, **changes):
        return reconcile_capital(synthetic_observation(at=at, **changes), synthetic_intent(at=at), at_ms=at)

    def quiet(self):
        return {"state": "NO_WAKE", "reason": "CHANGE_WITHIN_INTRADAY_HISTORY",
                "input_family": "BTC_SPOT_PRICE", "action_output": "NONE"}

    def full_intent(self, at=NOW, version="confirmed-1"):
        return {"version": version, "source": "USER_CONFIRMED", "confirmed_at_ms": at - 1000,
                "reserved_usd": 0, "no_leverage": True}

    def test_initial_qualified_capital_reaches_existing_fusion(self):
        result = apply_capital_reanalysis_wake(self.quiet(), self.reconciled(), at_ms=NOW)
        self.assertEqual(result["state"], "REANALYSIS_REQUESTED")
        self.assertEqual(result["reason"], "INITIAL_QUALIFIED_CAPITAL_STATE")
        self.assertEqual(result["wake_sources"], ["BROKER_CAPITAL_STATE"])
        # Evidence-pack fusion occurs later and must retain the actual wake.
        fused = fuse_reanalysis_wake(result, plan_drift={"state": "STABLE", "reanalysis_required": False})
        self.assertEqual(fused["wake_sources"], ["BROKER_CAPITAL_STATE"])
        self.assertEqual(fused["capital_change"], result["capital_change"])
        self.assertEqual(fused["external_action_authority"], "NONE")

    def test_cash_position_order_and_confirmed_intent_changes_wake_without_market_change(self):
        previous = self.reconciled()
        cash = self.reconciled(funds={"cash_usd": 1200, "available_funds_usd": 800, "settled_cash_usd": None})
        holdings = deepcopy(synthetic_observation()["holdings"])
        holdings[0]["quantity"] += 1
        position = self.reconciled(holdings=holdings)
        cost_basis = deepcopy(synthetic_observation()["holdings"])
        cost_basis[0]["average_cost_usd"] += 1
        cost_changed = self.reconciled(holdings=cost_basis)
        orders = self.reconciled(open_orders=[order()])
        intent = synthetic_intent(); intent["reserved_usd"] = 50
        user_changed = reconcile_capital(synthetic_observation(), intent, at_ms=NOW)
        for current in (cash, position, cost_changed, orders, user_changed):
            with self.subTest(capital=current):
                result = apply_capital_reanalysis_wake(self.quiet(), current, at_ms=NOW,
                    previous_reconciliation=previous, previous_at_ms=NOW)
                self.assertEqual(result["state"], "REANALYSIS_REQUESTED")
                self.assertEqual(result["reason"], "CAPITAL_STATE_CHANGED")
                self.assertNotEqual(result["capital_change"]["current_state_hash"],
                                    result["capital_change"]["previous_state_hash"])

    def test_clock_only_refresh_has_no_capital_wake_even_after_old_snapshot_expired(self):
        refreshed_at = NOW + 400_000
        result = apply_capital_reanalysis_wake(self.quiet(), self.reconciled(at=refreshed_at), at_ms=refreshed_at,
            previous_reconciliation=self.reconciled(), previous_at_ms=NOW,
            decision_intent=self.full_intent(at=refreshed_at), previous_decision_intent=self.full_intent())
        self.assertEqual(result["state"], "NO_WAKE")
        self.assertEqual(result["capital_change"]["reason"], "CAPITAL_STATE_UNCHANGED")
        self.assertEqual(result["wake_sources"], [])

    def test_complete_decision_intent_version_change_has_semantic_identity(self):
        current = self.reconciled()
        result = apply_capital_reanalysis_wake(self.quiet(), current, at_ms=NOW,
            previous_reconciliation=current, previous_at_ms=NOW,
            decision_intent=self.full_intent(version="confirmed-2"), previous_decision_intent=self.full_intent())
        self.assertEqual(result["state"], "REANALYSIS_REQUESTED")

    def test_missing_partial_stale_or_unconfirmed_sources_never_gain_capital_identity(self):
        partial = synthetic_observation(scope={**synthetic_observation()["scope"], "funds_complete": False})
        stale = reconcile_capital(synthetic_observation(), synthetic_intent(), at_ms=NOW + 400_000)
        unconfirmed = reconcile_capital(synthetic_observation(), None, at_ms=NOW)
        for current, at in ((None, NOW), (reconcile_capital(partial, synthetic_intent(), at_ms=NOW), NOW),
                            (stale, NOW + 400_000), (unconfirmed, NOW)):
            with self.subTest(source=current):
                result = apply_capital_reanalysis_wake(self.quiet(), current, at_ms=at)
                self.assertEqual(result["state"], "NO_WAKE")
                self.assertIsNone(result["capital_change"]["current_state_hash"])

    def test_tampered_reconciliation_or_unconfirmed_full_intent_cannot_wake(self):
        current = self.reconciled()
        current["analysis_cash_budget_usd"] = 99999
        self.assertIsNone(capital_state_identity(current, at_ms=NOW))
        for key, value in (("source", "GENERATED"), ("no_leverage", False), ("reserved_usd", 123),
                           ("confirmed_at_ms", NOW + 1)):
            intent = self.full_intent(); intent[key] = value
            with self.subTest(key=key):
                self.assertIsNone(capital_state_identity(self.reconciled(), at_ms=NOW, decision_intent=intent))


if __name__ == "__main__":
    unittest.main(verbosity=2)
