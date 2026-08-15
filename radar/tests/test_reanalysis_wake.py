from __future__ import annotations

import unittest

from crt_radar.observation_store import Observation
from crt_radar.reanalysis_wake import evaluate_intraday_reanalysis_wake


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
