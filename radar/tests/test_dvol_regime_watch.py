from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.dvol_regime_watch import (
    evaluate_dvol_regime_watch,
    run_live_dvol_regime_watch,
)


DAY = 86_400_000
HOUR = 3_600_000
BASE = 1_780_000_000_000


def candles(
    values: list[float],
    *,
    start: int,
    step: int,
) -> list[list[float]]:
    return [
        [start + index * step, value, value, value, value]
        for index, value in enumerate(values)
    ]


class DvolRegimeWatchTests(unittest.TestCase):
    def daily_baseline(self, factor: float = 1.0) -> list[list[float]]:
        values = [
            (50.0 + (index % 80) * 0.4) * factor
            for index in range(365)
        ]
        return candles(
            values,
            start=BASE - 365 * DAY,
            step=DAY,
        )

    def test_extreme_compression_is_direction_unknown_and_non_weighted(self):
        hourly = candles(
            [35.5] * (35 * 4) + [35.0],
            start=BASE - 35 * DAY,
            step=6 * HOUR,
        )
        now_ms = hourly[-1][0] + HOUR

        result = evaluate_dvol_regime_watch(
            self.daily_baseline(),
            hourly,
            now_ms=now_ms,
        )

        self.assertEqual(result["state"], "COMPRESSION_EXTREME")
        self.assertEqual(result["direction"], "UNKNOWN")
        self.assertLessEqual(result["level_percentile_1y"], 10.0)
        self.assertEqual(
            result["recommended_wake_operational_percentile"],
            90.0,
        )
        self.assertEqual(result["formal_weight_authority"], "NONE")
        self.assertEqual(result["formal_threshold_authority"], "NONE")
        self.assertEqual(result["action_output"], "NONE")

    def test_expansion_after_extreme_low_requests_more_sensitive_wake_posture(self):
        values = [38.0] * (35 * 4)
        values[-12] = 34.0
        values[-1] = 41.0

        hourly = candles(
            values,
            start=BASE - 35 * DAY,
            step=6 * HOUR,
        )
        now_ms = hourly[-1][0] + HOUR

        result = evaluate_dvol_regime_watch(
            self.daily_baseline(),
            hourly,
            now_ms=now_ms,
        )

        self.assertEqual(result["state"], "EXPANSION_ACTIVATED")
        self.assertGreaterEqual(
            result["rebound_from_30d_low_pct"],
            15.0,
        )
        self.assertEqual(result["direction"], "UNKNOWN")
        self.assertFalse(result["machine_may_confirm_bull_transition"])
        self.assertEqual(
            result["recommended_wake_operational_percentile"],
            90.0,
        )

    def test_fractional_deribit_scale_is_normalized_transparently(self):
        daily = self.daily_baseline(factor=0.01)
        hourly = candles(
            [0.35] * (35 * 4) + [0.35],
            start=BASE - 35 * DAY,
            step=6 * HOUR,
        )
        now_ms = hourly[-1][0] + HOUR

        result = evaluate_dvol_regime_watch(
            daily,
            hourly,
            now_ms=now_ms,
        )

        self.assertEqual(
            result["scale_normalization"],
            "FRACTION_X100",
        )
        self.assertAlmostEqual(result["current_dvol"], 35.0)

    def test_live_fetch_failure_fails_closed_without_trade_authority(self):
        def broken(_: str):
            raise OSError("offline")

        result = run_live_dvol_regime_watch(
            now_ms=BASE,
            http_json=broken,
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(
            result["recommended_wake_operational_percentile"],
            95.0,
        )
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertEqual(result["action_output"], "NONE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
