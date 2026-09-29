"""Synthetic research fixtures, not sourced historical OHLC or trading rules."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from crt_radar.btc_transition_replay_evidence import (
    FrozenRallyReference, build_price_time_overbalance_measurement as measure,
    build_transition_replay_snapshot,
)
from test_btc_transition_replay_evidence import weekly_bars
from test_deployment_posture_research_gate import evaluation


def fixture(highs=(105, 109, 111), start="2023-01-01"):
    base = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    stamp = lambda day: (base+timedelta(days=day)).isoformat().replace("+00:00", "Z")
    reference = FrozenRallyReference(stamp(0), stamp(2), 100, 110, stamp(2),
                                     "SYNTHETIC_RESEARCH_FIXTURE_NOT_HISTORICAL_DATA", stamp(3), 100)
    bars = []
    for day, high in [(1, 105), (2, 110)]+[(i+4, value) for i, value in enumerate(highs)]:
        bars.append({"day_closed_at": stamp(day), "available_at": stamp(day), "is_complete": True,
                     "open": min(100, high), "high": high, "low": min(99, high), "close": min(100, high)})
    return bars, reference, stamp


def snapshot(bars, ref, at, *, include_overbalance=True):
    return build_transition_replay_snapshot(structure_bars=bars, weekly_bars=weekly_bars(), as_of=at,
        old_control_high=120, old_control_zone_lower=99, old_control_zone_upper=101,
        candidate_invalidation_anchor=95, references_frozen_at=ref.reference_frozen_at,
        reference_provenance=ref.reference_provenance, weekly_provenance="SYNTHETIC_RESEARCH",
        candidate_breakout_at=ref.candidate_start_at,
        **({"overbalance_daily_bars": bars, "overbalance_reference": ref} if include_overbalance else {}))


class OverbalanceReplayTests(unittest.TestCase):
    def test_both_exceeded_strictly_and_first_crossings_retained(self):
        bars, ref, at = fixture()
        out = measure(bars, reference=ref, as_of=at(6))
        self.assertEqual(out["state"], "READY_FOR_ANALYST")
        self.assertAlmostEqual(out["reference_gain_pct"], 10)
        self.assertEqual(out["reference_duration_bars"], 2)
        self.assertAlmostEqual(out["candidate_gain_pct"], 11)
        self.assertEqual(out["candidate_duration_bars"], 3)
        self.assertAlmostEqual(out["price_overbalance_ratio"], 1.1)
        self.assertEqual(out["time_overbalance_ratio"], 1.5)
        self.assertEqual(out["price_overbalance_first_at"], at(6))
        self.assertEqual(out["time_overbalance_first_at"], at(6))
        self.assertEqual(out["prior_rally_price_time_envelope_exceeded_at"], at(6))
        self.assertTrue(out["prior_rally_price_time_envelope_exceeded"])
        self.assertEqual(out["interpretation"], "EARLY_TRANSITION_PRESSURE_AVAILABLE_FOR_ANALYST")

    def test_price_only_is_not_both(self):
        bars, ref, at = fixture((111, 108, 107, 106))
        out = measure(bars, reference=ref, as_of=at(7))
        self.assertGreater(out["price_overbalance_ratio"], 1)
        self.assertEqual(out["candidate_duration_bars"], 1)
        self.assertIsNone(out["time_overbalance_first_at"])
        self.assertFalse(out["prior_rally_price_time_envelope_exceeded"])

    def test_time_only_is_not_both(self):
        bars, ref, at = fixture((102, 103, 104))
        out = measure(bars, reference=ref, as_of=at(6))
        self.assertGreater(out["time_overbalance_ratio"], 1)
        self.assertLess(out["price_overbalance_ratio"], 1)
        self.assertIsNone(out["price_overbalance_first_at"])
        self.assertFalse(out["prior_rally_price_time_envelope_exceeded"])

    def test_equality_is_not_crossing(self):
        for highs, day in (((105, 110), 5), ((103, 107, 110), 6)):
            bars, ref, at = fixture(highs)
            out = measure(bars, reference=ref, as_of=at(day))
            self.assertEqual(out["price_overbalance_ratio"], 1)
            self.assertIsNone(out["price_overbalance_first_at"])
            self.assertFalse(out["prior_rally_price_time_envelope_exceeded"])

    def test_decimal_price_equality_does_not_cross_due_to_float_rounding(self):
        bars, ref, at = fixture((102, 105, 110))
        for row in bars[:2]:
            for key in ("open", "high", "low", "close"):
                row[key] = round(row[key]*.03, 8)
        ref = replace(ref, reference_start_price=3, reference_high_price=3.3)
        out = measure(bars, reference=ref, as_of=at(6))
        self.assertEqual(out["price_overbalance_ratio"], 1)
        self.assertFalse(out["prior_rally_price_time_envelope_exceeded"])

    def test_high_occurrence_not_as_of_and_equal_highs_do_not_extend_duration(self):
        bars, ref, at = fixture((111, 109, 111, 100, 90))
        early = measure(bars, reference=ref, as_of=at(4))
        later = measure(bars, reference=ref, as_of=at(8), previous_measurement=early)
        self.assertEqual(later["candidate_duration_bars"], 1)
        self.assertEqual(later["running_high_first_at"], at(4))
        self.assertEqual(later["time_overbalance_ratio"], early["time_overbalance_ratio"])

    def test_reference_duration_ends_at_first_high_not_reference_end(self):
        bars, ref, at = fixture()
        bars.insert(2, {**bars[0], "day_closed_at": at(3), "available_at": at(3), "high": 110})
        ref = replace(ref, reference_end_at=at(3), reference_frozen_at=at(3))
        self.assertEqual(measure(bars, reference=ref, as_of=at(6))["reference_duration_bars"], 2)

    def test_frozen_reference_cannot_mutate_or_change_across_replay(self):
        bars, ref, at = fixture()
        with self.assertRaises(FrozenInstanceError):
            ref.reference_high_price = 120
        early = measure(bars, reference=ref, as_of=at(4))
        for changed in (replace(ref, reference_start_price=99), replace(ref, reference_provenance="RESELECTED")):
            out = measure(bars, reference=changed, as_of=at(6), previous_measurement=early)
            self.assertEqual(out["state"], "BLOCKED")
            self.assertIn("FROZEN_REFERENCE", out["reason"])

    def test_future_bars_and_mutations_cannot_change_past(self):
        bars, ref, at = fixture()
        before = measure(bars[:3], reference=ref, as_of=at(4))
        bars[-1]["high"] = 999999
        self.assertEqual(measure(bars, reference=ref, as_of=at(4)), before)

    def test_incomplete_daily_high_is_not_used(self):
        bars, ref, at = fixture((105,))
        before = measure(bars, reference=ref, as_of=at(4))
        bars.append({**bars[-1], "day_closed_at": at(5), "available_at": at(4), "high": 999999,
                     "is_complete": False})
        self.assertEqual(measure(bars, reference=ref, as_of=at(4)), before)

    def test_future_completion_and_missing_completion_marker_block(self):
        bars, ref, at = fixture()
        bars[-1]["available_at"] = at(5)
        self.assertEqual(measure(bars, reference=ref, as_of=at(5))["state"], "BLOCKED")
        bars, ref, at = fixture()
        bars[0].pop("is_complete")
        self.assertEqual(measure(bars, reference=ref, as_of=at(6))["state"], "BLOCKED")

    def test_nonpositive_reference_gain_and_zero_duration_block(self):
        bars, ref, at = fixture()
        for changed in (replace(ref, reference_start_at=ref.reference_end_at),
                        replace(ref, reference_start_price=110), replace(ref, reference_start_price=120)):
            self.assertEqual(measure(bars, reference=changed, as_of=at(6))["state"], "BLOCKED")

    def test_freeze_and_candidate_clock_order(self):
        bars, ref, at = fixture()
        for changed in (replace(ref, reference_frozen_at=at(4)), replace(ref, reference_end_at=at(0)),
                        replace(ref, candidate_start_at=at(8)), replace(ref, reference_start_at=at(8))):
            self.assertEqual(measure(bars, reference=changed, as_of=at(6))["state"], "BLOCKED")

    def test_frozen_high_and_availability_need_historical_support(self):
        bars, ref, at = fixture()
        self.assertEqual(measure(bars, reference=replace(ref, reference_high_price=111), as_of=at(6))["state"], "BLOCKED")
        bars[1]["available_at"] = at(3)
        self.assertEqual(measure(bars, reference=ref, as_of=at(6))["state"], "BLOCKED")

    def test_duplicate_gap_and_missing_latest_completed_day_block(self):
        bars, ref, at = fixture()
        for changed in (bars[:3]+bars[4:], bars+[deepcopy(bars[-1])], bars[:-1]):
            self.assertEqual(measure(changed, reference=ref, as_of=at(6))["state"], "BLOCKED")

    def test_checkpoint_prevents_backdated_history_rewrite(self):
        bars, ref, at = fixture()
        early = measure(bars, reference=ref, as_of=at(4))
        bars[2]["high"] = 106
        self.assertEqual(measure(bars, reference=ref, as_of=at(6), previous_measurement=early)["state"], "BLOCKED")

    def test_future_checkpoint_is_rejected(self):
        bars, ref, at = fixture()
        later = measure(bars, reference=ref, as_of=at(6))
        self.assertEqual(measure(bars, reference=ref, as_of=at(4), previous_measurement=later)["state"], "BLOCKED")

    def test_research_2023_early_transition_intent_before_complete_closure(self):
        # Archetype only: prices and dates are synthetic, not a historical claim.
        bars, ref, at = fixture((105, 109, 111, 125), "2023-01-01")
        early = measure(bars, reference=ref, as_of=at(6))
        self.assertTrue(early["prior_rally_price_time_envelope_exceeded"])
        self.assertFalse(evaluation(confirmed=2)["control_transfer_loop_closed"])
        self.assertTrue(evaluation(confirmed=99)["control_transfer_loop_closed"])
        self.assertLess(early["prior_rally_price_time_envelope_exceeded_at"], at(7))

    def test_research_march_2022_failed_candidate_retains_historical_true(self):
        bars, ref, at = fixture((105, 109, 111, 90), "2022-03-01")
        early = snapshot(bars, ref, at(6))
        later = snapshot(bars, ref, at(7))
        first = early["price_time_overbalance_measurement"]
        last = later["price_time_overbalance_measurement"]
        self.assertTrue(first["prior_rally_price_time_envelope_exceeded"])
        self.assertTrue(last["prior_rally_price_time_envelope_exceeded"])
        self.assertEqual(first["prior_rally_price_time_envelope_exceeded_at"], last["prior_rally_price_time_envelope_exceeded_at"])
        self.assertEqual(later["overbalance_existing_structure_invalidation"]["candidate_invalidation_anchor_raw_breach_at"], at(7))

    def test_research_2022_momentum_trap_cannot_be_forced_to_both(self):
        bars, ref, at = fixture((115, 109, 103, 90), "2022-08-01")
        out = measure(bars, reference=ref, as_of=at(7))
        self.assertGreater(out["price_overbalance_ratio"], 1)
        self.assertFalse(out["prior_rally_price_time_envelope_exceeded"])

    def test_authorities_and_existing_snapshot_components_are_unchanged(self):
        bars, ref, at = fixture()
        out = snapshot(bars, ref, at(6))
        m = out["price_time_overbalance_measurement"]
        for key in ("formal_model_authority", "formal_weight_authority", "formal_threshold_authority",
                    "season_transition_authority", "action_output", "external_action_authority"):
            self.assertEqual(m[key], "NONE")
        for key in ("external_action_performed", "machine_may_determine_btc_season", "machine_may_confirm_bull_transition"):
            self.assertFalse(m[key])
        self.assertEqual(m["capital_decision_authority"], "USER_ONLY")
        self.assertEqual(m["production"], "NOT_APPROVED")
        self.assertTrue(all(v is None for v in out["analyst_classifications"].values()))
        original = snapshot(bars, ref, at(6), include_overbalance=False)
        self.assertEqual(original, {k: v for k, v in out.items() if k not in {
            "price_time_overbalance_measurement", "overbalance_existing_structure_invalidation"}})


if __name__ == "__main__":
    unittest.main()
