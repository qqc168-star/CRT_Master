from __future__ import annotations

import copy
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

from crt_radar.btc_transition_replay_evidence import (
    build_btc_long_horizon_context,
    build_cycle_drawdown_context,
    build_cycle_envelope_scenarios,
    build_long_horizon_50wma_context,
    build_long_horizon_200wma_context,
    build_structure_measurements,
    build_transition_replay_snapshot,
)


def structure_bar(at: str, *, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "available_at": at,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }


SYNTHETIC_REPLAY_BARS = [
    structure_bar(
        "2026-09-02T00:00:00Z",
        open_=77_000.0,
        high=78_100.0,
        low=76_217.25,
        close=77_600.0,
    ),
    structure_bar(
        "2026-09-05T00:00:00Z",
        open_=77_600.0,
        high=82_298.0,
        low=77_200.0,
        close=81_900.0,
    ),
    structure_bar(
        "2026-09-10T00:00:00Z",
        open_=80_000.0,
        high=80_500.0,
        low=74_894.0,
        close=76_000.0,
    ),
    structure_bar(
        "2026-09-19T00:00:00Z",
        open_=76_000.0,
        high=81_718.5,
        low=75_500.0,
        close=81_000.0,
    ),
]


def structure_result(bars: list[dict], *, as_of: str) -> dict:
    return build_structure_measurements(
        bars,
        as_of=as_of,
        old_control_high=82_298.0,
        old_control_zone_lower=76_000.0,
        old_control_zone_upper=78_000.0,
        candidate_invalidation_anchor=76_217.25,
        references_frozen_at="2026-09-05T00:00:00Z",
        reference_provenance="DETERMINISTIC_SYNTHETIC_TEST",
        candidate_breakout_at="2026-09-05T00:00:00Z",
    )


def weekly_bars(*, complete_count: int = 52, include_incomplete: bool = False) -> list[dict]:
    start = datetime(2025, 1, 5, tzinfo=timezone.utc)
    rows: list[dict] = []
    closes = [100.0] * 50 + [101.0, 102.0]
    for index in range(complete_count):
        closed_at = start + timedelta(weeks=index)
        rows.append(
            {
                "week_closed_at": closed_at.isoformat(),
                "available_at": closed_at.isoformat(),
                "close": closes[index] if index < len(closes) else 102.0,
                "is_complete": True,
            }
        )
    if include_incomplete:
        next_close = start + timedelta(weeks=complete_count)
        rows.append(
            {
                "week_closed_at": next_close.isoformat(),
                "available_at": (next_close - timedelta(days=3)).isoformat(),
                "close": 1_000.0,
                "is_complete": False,
            }
        )
    return rows


class BtcTransitionReplayEvidenceTests(unittest.TestCase):
    def test_future_bar_mutations_do_not_change_past_snapshot(self):
        original = copy.deepcopy(SYNTHETIC_REPLAY_BARS)
        mutated = copy.deepcopy(SYNTHETIC_REPLAY_BARS)
        mutated[2].update(open=9.0, high=10.0, low=1.0, close=2.0)
        mutated[3].update(open=900_000.0, high=999_999.0, low=800_000.0, close=950_000.0)

        first = structure_result(original, as_of="2026-09-05T00:00:00Z")
        second = structure_result(mutated, as_of="2026-09-05T00:00:00Z")

        self.assertEqual(first, second)
        self.assertEqual(first["visible_bar_count"], 2)
        self.assertFalse(
            first["measurements"]["candidate_invalidation_anchor_raw_breach"]
        )

    def test_synthetic_replay_exposes_invalidation_only_after_lower_low(self):
        first_attack = structure_result(
            SYNTHETIC_REPLAY_BARS,
            as_of="2026-09-05T00:00:00Z",
        )
        lower_low = structure_result(
            SYNTHETIC_REPLAY_BARS,
            as_of="2026-09-10T00:00:00Z",
        )

        self.assertFalse(
            first_attack["measurements"][
                "candidate_invalidation_anchor_raw_breach"
            ]
        )
        self.assertTrue(
            lower_low["measurements"][
                "candidate_invalidation_anchor_raw_breach"
            ]
        )
        self.assertEqual(
            lower_low["measurements"][
                "candidate_invalidation_anchor_raw_breach_at"
            ],
            "2026-09-10T00:00:00Z",
        )
        self.assertTrue(
            lower_low["measurements"][
                "lower_low_vs_candidate_invalidation_anchor"
            ]
        )

    def test_second_attack_below_frozen_high_is_not_measured_as_break(self):
        result = structure_result(
            SYNTHETIC_REPLAY_BARS,
            as_of="2026-09-19T00:00:00Z",
        )

        self.assertEqual(result["state"], "READY_FOR_ANALYST")
        self.assertEqual(result["measurements"]["post_candidate_high"], 82_298.0)
        self.assertFalse(result["measurements"]["prior_control_high_raw_break"])
        self.assertFalse(result["measurements"]["prior_control_high_close_break"])

    def test_raw_cross_and_close_above_are_separate_facts(self):
        bars = [
            structure_bar(
                "2026-09-05T00:00:00Z",
                open_=81_000.0,
                high=82_500.0,
                low=80_500.0,
                close=82_000.0,
            )
        ]
        result = structure_result(bars, as_of="2026-09-05T00:00:00Z")

        self.assertEqual(
            result["measurements"]["first_raw_cross_above_old_control_high_at"],
            "2026-09-05T00:00:00Z",
        )
        self.assertIsNone(
            result["measurements"]["first_close_above_old_control_high_at"]
        )

    def test_zone_breach_and_later_close_reclaim_are_ordered(self):
        result = structure_result(
            SYNTHETIC_REPLAY_BARS,
            as_of="2026-09-19T00:00:00Z",
        )

        self.assertEqual(
            result["measurements"]["first_raw_breach_below_old_control_zone_at"],
            "2026-09-10T00:00:00Z",
        )
        self.assertEqual(
            result["measurements"]["first_close_reclaim_of_old_control_zone_at"],
            "2026-09-19T00:00:00Z",
        )

    def test_visible_unsorted_duplicate_and_naive_times_fail_closed(self):
        cases = []
        duplicate = copy.deepcopy(SYNTHETIC_REPLAY_BARS[:2])
        duplicate[1]["available_at"] = duplicate[0]["available_at"]
        cases.append((duplicate, "DUPLICATE_STRUCTURE_BAR_TIME"))

        unsorted = list(reversed(copy.deepcopy(SYNTHETIC_REPLAY_BARS[:2])))
        cases.append((unsorted, "UNSORTED_STRUCTURE_BARS"))

        naive = copy.deepcopy(SYNTHETIC_REPLAY_BARS[:1])
        naive[0]["available_at"] = "2026-09-02T00:00:00"
        cases.append((naive, "TIMESTAMP_TIMEZONE_REQUIRED"))

        for bars, reason in cases:
            with self.subTest(reason=reason):
                result = structure_result(bars, as_of="2026-09-05T00:00:00Z")
                self.assertEqual(result["state"], "BLOCKED")
                self.assertIn(reason, result["reason"])

    def test_references_frozen_after_as_of_fail_closed(self):
        result = build_structure_measurements(
            SYNTHETIC_REPLAY_BARS,
            as_of="2026-09-02T00:00:00Z",
            old_control_high=82_298.0,
            old_control_zone_lower=76_000.0,
            old_control_zone_upper=78_000.0,
            candidate_invalidation_anchor=76_217.25,
            references_frozen_at="2026-09-05T00:00:00Z",
            reference_provenance="DETERMINISTIC_SYNTHETIC_TEST",
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "REFERENCES_NOT_VISIBLE_AT_AS_OF")

    def test_candidate_window_before_breakout_is_unavailable_not_false(self):
        result = build_structure_measurements(
            SYNTHETIC_REPLAY_BARS,
            as_of="2026-09-02T00:00:00Z",
            old_control_high=82_298.0,
            old_control_zone_lower=76_000.0,
            old_control_zone_upper=78_000.0,
            candidate_invalidation_anchor=76_217.25,
            references_frozen_at="2026-09-02T00:00:00Z",
            reference_provenance="DETERMINISTIC_SYNTHETIC_TEST",
            candidate_breakout_at="2026-09-05T00:00:00Z",
        )

        self.assertEqual(result["state"], "READY_FOR_ANALYST")
        self.assertFalse(result["measurements"]["candidate_window_visible"])
        self.assertIsNone(
            result["measurements"]["prior_control_high_raw_break"]
        )
        self.assertIsNone(
            result["measurements"][
                "candidate_invalidation_anchor_raw_breach"
            ]
        )

    def test_references_frozen_after_candidate_fail_closed(self):
        result = build_structure_measurements(
            SYNTHETIC_REPLAY_BARS,
            as_of="2026-09-10T00:00:00Z",
            old_control_high=82_298.0,
            old_control_zone_lower=76_000.0,
            old_control_zone_upper=78_000.0,
            candidate_invalidation_anchor=76_217.25,
            references_frozen_at="2026-09-06T00:00:00Z",
            reference_provenance="DETERMINISTIC_SYNTHETIC_TEST",
            candidate_breakout_at="2026-09-05T00:00:00Z",
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "REFERENCES_FROZEN_AFTER_CANDIDATE")

    def test_completed_week_context_uses_contemporaneous_50wma(self):
        rows = weekly_bars()
        result = build_long_horizon_50wma_context(
            rows,
            as_of=rows[-1]["available_at"],
            provenance="DETERMINISTIC_SYNTHETIC_TEST",
        )

        self.assertEqual(result["state"], "READY_FOR_ANALYST")
        self.assertAlmostEqual(result["latest_completed_50wma"], 100.06)
        self.assertEqual(result["consecutive_completed_closes_above_50wma"], 2)
        self.assertFalse(result["streak_left_censored"])

    def test_incomplete_current_week_never_increments_completed_streak(self):
        rows = weekly_bars(include_incomplete=True)
        as_of = rows[-1]["available_at"]
        result = build_long_horizon_50wma_context(
            rows,
            as_of=as_of,
            provenance="DETERMINISTIC_SYNTHETIC_TEST",
            current_price=1_000.0,
            current_price_at=as_of,
        )

        self.assertEqual(result["completed_week_count"], 52)
        self.assertEqual(result["consecutive_completed_closes_above_50wma"], 2)
        self.assertEqual(result["latest_completed_weekly_close"], 102.0)
        self.assertFalse(
            result["current_price_context"]["counts_as_completed_week"]
        )

    def test_future_week_mutations_do_not_change_past_context(self):
        rows = weekly_bars()
        future_close = datetime.fromisoformat(rows[-1]["week_closed_at"]) + timedelta(
            weeks=1
        )
        rows.append(
            {
                "week_closed_at": future_close.isoformat(),
                "available_at": future_close.isoformat(),
                "close": 103.0,
                "is_complete": True,
            }
        )
        mutated = copy.deepcopy(rows)
        mutated[-1]["close"] = "FUTURE_VALUE_MUST_REMAIN_INVISIBLE"
        mutated[-1]["is_complete"] = "FUTURE_FLAG_MUST_REMAIN_INVISIBLE"
        as_of = rows[-2]["available_at"]

        first = build_long_horizon_50wma_context(
            rows,
            as_of=as_of,
            provenance="DETERMINISTIC_SYNTHETIC_TEST",
        )
        second = build_long_horizon_50wma_context(
            mutated,
            as_of=as_of,
            provenance="DETERMINISTIC_SYNTHETIC_TEST",
        )

        self.assertEqual(first, second)

    def test_fewer_than_fifty_completed_weeks_fail_closed(self):
        rows = weekly_bars(complete_count=49)
        result = build_long_horizon_50wma_context(
            rows,
            as_of=rows[-1]["available_at"],
            provenance="DETERMINISTIC_SYNTHETIC_TEST",
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["completed_week_count"], 49)
        self.assertIn("FIFTY_COMPLETED_WEEKS_REQUIRED", result["blockers"])

    def test_week_marked_complete_before_its_close_fails_closed(self):
        rows = weekly_bars()
        as_of = datetime.fromisoformat(rows[-1]["available_at"]) + timedelta(days=1)
        future_close = as_of + timedelta(days=5)
        rows.append(
            {
                "week_closed_at": future_close.isoformat(),
                "available_at": as_of.isoformat(),
                "close": 103.0,
                "is_complete": True,
            }
        )
        result = build_long_horizon_50wma_context(
            rows,
            as_of=as_of,
            provenance="DETERMINISTIC_SYNTHETIC_TEST",
        )

        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("COMPLETED_WEEK_CLOSES_AFTER_AS_OF", result["reason"])

    def test_exactly_fifty_above_weeks_marks_streak_left_censored(self):
        rows = weekly_bars(complete_count=50)
        rows[-1]["close"] = 101.0
        result = build_long_horizon_50wma_context(
            rows,
            as_of=rows[-1]["available_at"],
            provenance="DETERMINISTIC_SYNTHETIC_TEST",
        )

        self.assertEqual(result["consecutive_completed_closes_above_50wma"], 1)
        self.assertTrue(result["streak_left_censored"])

    def test_combined_snapshot_preserves_authority_and_analyst_placeholders(self):
        weeks = weekly_bars()
        snapshot = build_transition_replay_snapshot(
            structure_bars=SYNTHETIC_REPLAY_BARS,
            weekly_bars=weeks,
            as_of="2026-09-19T00:00:00Z",
            old_control_high=82_298.0,
            old_control_zone_lower=76_000.0,
            old_control_zone_upper=78_000.0,
            candidate_invalidation_anchor=76_217.25,
            references_frozen_at="2026-09-05T00:00:00Z",
            reference_provenance="DETERMINISTIC_SYNTHETIC_TEST",
            weekly_provenance="DETERMINISTIC_SYNTHETIC_TEST",
            candidate_breakout_at="2026-09-05T00:00:00Z",
        )

        self.assertEqual(snapshot["state"], "READY_FOR_ANALYST")
        self.assertTrue(all(value is None for value in snapshot["analyst_classifications"].values()))
        self.assertIsNone(snapshot["formal_season"])
        self.assertEqual(snapshot["formal_model_authority"], "NONE")
        self.assertEqual(snapshot["formal_weight_authority"], "NONE")
        self.assertEqual(snapshot["formal_threshold_authority"], "NONE")
        self.assertEqual(snapshot["season_transition_authority"], "NONE")
        self.assertEqual(snapshot["action_output"], "NONE")
        self.assertEqual(snapshot["external_action_authority"], "NONE")
        self.assertFalse(snapshot["external_action_performed"])
        self.assertFalse(snapshot["machine_may_determine_btc_season"])
        self.assertFalse(snapshot["machine_may_confirm_bull_transition"])
        self.assertTrue(snapshot["analyst_judgment_required"])
        self.assertNotIn("BUY", repr(snapshot))
        self.assertNotIn("SELL", repr(snapshot))


class BtcLongHorizonContextTests(
    unittest.TestCase
):
    def test_199_completed_weeks_block_200wma(
        self,
    ):
        rows = weekly_bars(
            complete_count=199
        )

        result = (
            build_long_horizon_200wma_context(
                rows,
                as_of=rows[-1][
                    "available_at"
                ],
                provenance=(
                    "DETERMINISTIC_SYNTHETIC_TEST"
                ),
            )
        )

        self.assertEqual(
            result["state"],
            "BLOCKED",
        )
        self.assertIn(
            "TWO_HUNDRED_COMPLETED_WEEKS_REQUIRED",
            result["blockers"],
        )

    def test_200wma_excludes_incomplete_week_and_has_exact_yoy(
        self,
    ):
        rows = weekly_bars(
            complete_count=252,
            include_incomplete=True,
        )

        as_of = rows[-1][
            "available_at"
        ]

        result = (
            build_long_horizon_200wma_context(
                rows,
                as_of=as_of,
                provenance=(
                    "DETERMINISTIC_SYNTHETIC_TEST"
                ),
                current_price=500.0,
                current_price_at=as_of,
            )
        )

        self.assertEqual(
            result["state"],
            "READY_FOR_ANALYST",
        )
        self.assertEqual(
            result[
                "completed_week_count"
            ],
            252,
        )
        self.assertIsNotNone(
            result[
                "latest_completed_200wma"
            ]
        )
        self.assertIsNotNone(
            result[
                "wma_200_growth_yoy_pct"
            ]
        )
        self.assertFalse(
            result[
                "current_price_context"
            ][
                "counts_as_completed_week"
            ]
        )
        self.assertEqual(
            result[
                "formal_price_target_authority"
            ],
            "NONE",
        )

    def test_cycle_envelope_is_scenario_only(
        self,
    ):
        result = (
            build_cycle_envelope_scenarios(
                [
                    {
                        "scenario_id": (
                            "CONSERVATIVE"
                        ),
                        "future_bear_floor_usd": (
                            120000
                        ),
                        "assumed_drawdown_pct": (
                            40
                        ),
                    },
                    {
                        "scenario_id": "MID",
                        "future_bear_floor_usd": (
                            135000
                        ),
                        "assumed_drawdown_pct": (
                            45
                        ),
                    },
                    {
                        "scenario_id": (
                            "OPTIMISTIC"
                        ),
                        "future_bear_floor_usd": (
                            150000
                        ),
                        "assumed_drawdown_pct": (
                            50
                        ),
                    },
                ]
            )
        )

        values = [
            row[
                "implied_cycle_peak_usd"
            ]
            for row in result[
                "scenarios"
            ]
        ]

        self.assertAlmostEqual(
            values[0],
            200000.0,
        )
        self.assertAlmostEqual(
            values[1],
            245454.54545454544,
        )
        self.assertAlmostEqual(
            values[2],
            300000.0,
        )
        self.assertTrue(
            result["scenario_only"]
        )
        self.assertEqual(
            result[
                "formal_price_target_authority"
            ],
            "NONE",
        )

    def test_current_cycle_drawdown_can_remain_provisional(
        self,
    ):
        result = (
            build_cycle_drawdown_context(
                {
                    "historical_cycles": [
                        {
                            "cycle_id": "2015",
                            "peak_price_usd": 100,
                            "trough_price_usd": 14,
                            "final": True,
                        },
                        {
                            "cycle_id": "2018",
                            "peak_price_usd": 100,
                            "trough_price_usd": 16,
                            "final": True,
                        },
                        {
                            "cycle_id": "2022",
                            "peak_price_usd": 100,
                            "trough_price_usd": 23,
                            "final": True,
                        },
                    ],
                    "current_cycle": {
                        "cycle_id": "2026",
                        "peak_price_usd": 100,
                        "trough_price_usd": 45.5,
                        "final": False,
                    },
                }
            )
        )

        self.assertEqual(
            result["state"],
            "READY_FOR_ANALYST",
        )
        self.assertFalse(
            result[
                "current_cycle"
            ][
                "current_cycle_drawdown_final"
            ]
        )
        self.assertIsNone(
            result[
                "next_cycle_drawdown_prediction"
            ]
        )

    def test_composite_long_horizon_has_no_trade_authority(
        self,
    ):
        rows = weekly_bars(
            complete_count=252
        )

        result = (
            build_btc_long_horizon_context(
                {
                    "as_of": rows[-1][
                        "available_at"
                    ],
                    "weekly_bars": rows,
                    "weekly_provenance": (
                        "DETERMINISTIC_SYNTHETIC_TEST"
                    ),
                    "cycle_drawdown_context": {
                        "historical_cycles": [
                            {
                                "cycle_id": (
                                    "2022"
                                ),
                                "peak_price_usd": (
                                    100
                                ),
                                "trough_price_usd": (
                                    23
                                ),
                                "final": True,
                            }
                        ]
                    },
                    "cycle_envelope_scenarios": [
                        {
                            "scenario_id": (
                                "MID"
                            ),
                            "future_bear_floor_usd": (
                                135000
                            ),
                            "assumed_drawdown_pct": (
                                45
                            ),
                        }
                    ],
                }
            )
        )

        self.assertEqual(
            result["state"],
            "READY_FOR_ANALYST",
        )
        self.assertEqual(
            result["action_output"],
            "NONE",
        )
        self.assertEqual(
            result[
                "external_action_authority"
            ],
            "NONE",
        )
        self.assertEqual(
            result[
                "formal_price_target_authority"
            ],
            "NONE",
        )
        self.assertNotIn(
            "BUY",
            repr(result),
        )
        self.assertNotIn(
            "SELL",
            repr(result),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
