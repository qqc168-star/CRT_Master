from __future__ import annotations

import unittest
from copy import deepcopy

from crt_radar.candidate_engine import (
    CandidateModelError,
    EXPECTED_LIGHT_THRESHOLDS,
    threshold_bucket,
)
from crt_radar.season_transition_warning_overlay import (
    SCHEMA_VERSION,
    build_season_transition_warning_overlay,
    classify_institutional_flow_pattern,
    validate_season_transition_warning_overlay,
)


NOW_MS = 1_788_800_000_000


def candidate(
    *,
    price_scores: tuple[float, float, float] = (60.0, 50.0, 40.0),
    cvd_score: float = 63.0,
    etp_score: float = 58.0,
    l4_score: float = 24.0,
) -> dict:
    return {
        "layers": {
            "L3": {
                "state": "VALID_RESEARCH_LAYER",
                "score": 58.0,
                "feature_scores": {
                    "L3_SPOT_BTC_ETP_FLOW_20D_PCT_AUM": etp_score,
                },
            },
            "L4": {
                "state": "VALID_RESEARCH_LAYER",
                "score": l4_score,
                "feature_scores": {},
            },
            "L6": {
                "state": "VALID_RESEARCH_LAYER",
                "score": 52.0,
                "feature_scores": {
                    "L6_CLOSE_MINUS_SMA200_OVER_ATR20": price_scores[0],
                    "L6_SMA50_MINUS_SMA200_OVER_ATR20": price_scores[1],
                    "L6_RETURN_20D_OVER_ATR_VOL": price_scores[2],
                    "L6_CVD_20D_SHARE": cvd_score,
                },
            },
        },
        "season_router": {
            "state": "BLOCKED",
            "season": None,
            "score_may_determine_btc_season": False,
        },
        "formal_model": "NOT_APPROVED",
        "production": "NOT_APPROVED",
    }


def layers(*, etp_flow_20d_pct_aum: float = 1.0) -> dict:
    def metric(value: float) -> dict:
        return {"value": value, "as_of_ms": NOW_MS}

    return {
        "L3": {
            "metrics": {
                "spot_btc_etp_flow_20d_pct_aum": metric(
                    etp_flow_20d_pct_aum
                ),
            },
        },
        "L4": {
            "metrics": {
                "funding_rate": metric(0.0001),
                "funding_3d_mean_bp": metric(0.75),
                "abs_funding_3d_mean_bp": metric(0.75),
                "liquidation_24h_long_usd": metric(1_500_000.0),
                "liquidation_24h_short_usd": metric(2_500_000.0),
            },
        },
        "L6": {
            "metrics": {
                "close_minus_sma200_over_atr20": metric(1.2),
                "sma50_minus_sma200_over_atr20": metric(0.8),
                "return_20d_over_atr_vol": metric(0.7),
                "cvd_20d_share": metric(0.11),
            },
        },
    }


def changes() -> dict:
    return {
        "open_interest_notional_usd": {
            "horizons": {
                "1d": {
                    "history_state": "AVAILABLE",
                    "percent_change": 2.5,
                    "absolute_change": 500_000_000.0,
                    "previous_as_of_ms": NOW_MS - 86_400_000,
                },
                "3d": {
                    "history_state": "AVAILABLE",
                    "percent_change": 4.0,
                    "absolute_change": 750_000_000.0,
                    "previous_as_of_ms": NOW_MS - 3 * 86_400_000,
                },
            },
        },
    }


def transition_diagnostic() -> dict:
    return {
        "state": "READY_FOR_ANALYST",
        "windows": {
            "recent_60m": {
                "spot_buy_share_pct": 53.7,
                "spot_cvd_proxy_usd": 12_000_000.0,
            },
            "prior_30m": {
                "spot_buy_share_pct": 52.0,
                "spot_cvd_proxy_usd": 5_000_000.0,
            },
            "recent_30m": {
                "spot_buy_share_pct": 55.0,
                "spot_cvd_proxy_usd": 7_000_000.0,
            },
        },
        "mechanism_findings": {
            "spot_demand_absorption": "SUPPORTED",
            "spot_demand_persistence": "SUPPORTED",
            "leverage_quality": "CONSTRUCTIVE",
        },
    }


def entry_gate(transition_state: str = "BULL_ACCEPTANCE_DEVELOPING") -> dict:
    return {
        "state": "READY_FOR_ANALYST",
        "transition_state": transition_state,
        "control_transfer_validation": {
            "state": "READY_FOR_ANALYST",
            "research_state": "CONTROL_TRANSFER_CANDIDATE",
            "control_transfer_loop_closed": True,
        },
    }


def bull_validation(
    *,
    state: str = "BULL_ACCEPTANCE_DEVELOPING",
    adverse: tuple[str, ...] = (),
) -> dict:
    return {
        "state": state,
        "checks": [
            {
                "check_id": check_id,
                "status": "ADVERSE",
                "reason": "TEST_ADVERSE",
            }
            for check_id in adverse
        ],
        "adverse_checks": list(adverse),
    }


def flow_context(
    signs: tuple[int, int, int] = (1, 1, 1),
) -> dict:
    values = {
        "1d": 250_000_000.0,
        "5d": signs[0] * 500_000_000.0,
        "20d": signs[1] * 1_000_000_000.0,
        "60d": signs[2] * 2_000_000_000.0,
        "120d": 3_000_000_000.0,
    }
    return {
        "state": "AVAILABLE",
        "windows": {
            name: {
                "flow_usd": value,
                "starting_aum_usd": 100_000_000_000.0,
            }
            for name, value in values.items()
        },
    }


def build(**overrides) -> dict:
    values = {
        "formal_candidate": candidate(),
        "layers": layers(),
        "changes": changes(),
        "btc_bull_validation": bull_validation(),
        "btc_entry_gate": entry_gate(),
        "transition_diagnostic": transition_diagnostic(),
        "generated_at_ms": NOW_MS,
        "institutional_flow_context": flow_context(),
    }
    values.update(overrides)
    return build_season_transition_warning_overlay(**values)


class SeasonTransitionWarningOverlayTests(unittest.TestCase):
    def test_locked_threshold_boundaries_are_reused(self) -> None:
        self.assertEqual(EXPECTED_LIGHT_THRESHOLDS, [-60, -35, 35, 60])
        expected = {
            -100: "C0_VERY_UNSUPPORTIVE",
            -60.0001: "C0_VERY_UNSUPPORTIVE",
            -60: "C1_UNSUPPORTIVE",
            -35.0001: "C1_UNSUPPORTIVE",
            -35: "C2_MIXED",
            34.9999: "C2_MIXED",
            35: "C3_SUPPORTIVE",
            59.9999: "C3_SUPPORTIVE",
            60: "C4_VERY_SUPPORTIVE",
            100: "C4_VERY_SUPPORTIVE",
        }
        for value, bucket in expected.items():
            with self.subTest(value=value):
                self.assertEqual(threshold_bucket(value), bucket)
        with self.assertRaises(CandidateModelError):
            threshold_bucket(0, [-50, -25, 25, 50])

    def test_scenario_one_uses_gate_core_veto_not_all_green(self) -> None:
        overlay = build()

        self.assertEqual(overlay["scenario"]["id"], "SCENARIO_1")
        self.assertEqual(overlay["scenario"]["label"], "情境 1｜春季證據強升級")
        self.assertEqual(overlay["gate_core_veto"]["gate"]["state"], "OPEN")
        self.assertEqual(overlay["gate_core_veto"]["core"]["state"], "STRONG")
        self.assertFalse(overlay["gate_core_veto"]["vote_counting_used"])
        self.assertEqual(overlay["lights"]["leverage_quality"]["light"], "YELLOW")
        self.assertEqual(
            overlay["lights"]["conflict_veto"]["threshold_bucket"],
            "NO_DECISIVE_VETO",
        )

    def test_price_excludes_cvd_and_spot_directly_reuses_it(self) -> None:
        positive = build(formal_candidate=candidate(cvd_score=63.0))
        negative = build(formal_candidate=candidate(cvd_score=-90.0))

        self.assertEqual(
            positive["lights"]["price_structure"]["score"],
            negative["lights"]["price_structure"]["score"],
        )
        self.assertEqual(positive["lights"]["spot_demand"]["score"], 63.0)
        self.assertEqual(negative["lights"]["spot_demand"]["score"], -90.0)
        self.assertEqual(
            positive["lights"]["price_structure"]["raw_metrics"]["excluded_from_price_light"],
            ["L6_CVD_20D_SHARE"],
        )

    def test_institutional_window_roles_and_sign_patterns(self) -> None:
        expectations = {
            (1, -1, -1): "EARLY_TURN",
            (1, 1, -1): "WINTER_END_SPRING_BUD_FORMING",
            (1, 1, 1): "INSTITUTIONAL_PERSISTENCE_CONFIRMED",
            (-1, 1, 1): "SHORT_TERM_COOLING_NOT_WINTER_REVERSAL",
        }
        for signs, expected in expectations.items():
            with self.subTest(signs=signs):
                overlay = build(institutional_flow_context=flow_context(signs))
                raw = overlay["lights"]["institutional_flow"]["raw_metrics"]
                self.assertEqual(raw["flow_pattern_5d_20d_60d"], expected)
                self.assertEqual(
                    classify_institutional_flow_pattern(raw["windows"]),
                    expected,
                )
                self.assertFalse(raw["windows"]["1d"]["used_in_main_light_score"])
                self.assertTrue(raw["windows"]["20d"]["used_in_main_light_score"])
                self.assertFalse(raw["windows"]["120d"]["used_in_main_light_score"])
                self.assertEqual(
                    raw["windows"]["20d"]["flow_pct_starting_aum"],
                    float(signs[1]),
                )

    def test_early_turn_selects_scenario_two(self) -> None:
        overlay = build(
            formal_candidate=candidate(etp_score=-40.0),
            layers=layers(etp_flow_20d_pct_aum=-1.0),
            institutional_flow_context=flow_context((1, -1, -1)),
        )
        self.assertEqual(overlay["scenario"]["id"], "SCENARIO_2")
        self.assertEqual(overlay["scenario"]["label"], "情境 2｜春芽存在、仍在拉扯")
        self.assertEqual(
            overlay["lights"]["conflict_veto"]["threshold_bucket"],
            "NO_DECISIVE_VETO",
        )

    def test_short_term_cooling_does_not_route_back_to_winter(self) -> None:
        overlay = build(institutional_flow_context=flow_context((-1, 1, 1)))
        raw = overlay["lights"]["institutional_flow"]["raw_metrics"]
        self.assertEqual(
            raw["flow_pattern_5d_20d_60d"],
            "SHORT_TERM_COOLING_NOT_WINTER_REVERSAL",
        )
        self.assertEqual(overlay["scenario"]["id"], "SCENARIO_2")
        self.assertNotIn("WINTER", overlay["scenario"]["label"])

    def test_institutional_context_mismatch_surfaces_as_conflict(self) -> None:
        overlay = build(institutional_flow_context=flow_context((1, -1, -1)))
        veto = overlay["lights"]["conflict_veto"]
        self.assertEqual(veto["threshold_bucket"], "CONFLICT_PRESENT")
        self.assertIn(
            "INSTITUTIONAL_20D_CONTEXT_CONFLICT",
            veto["raw_metrics"]["conflict_evidence"],
        )

    def test_decisive_veto_overrides_four_supportive_lights(self) -> None:
        overlay = build(
            btc_entry_gate=entry_gate("BEAR_REJECTION_STRENGTHENED"),
            btc_bull_validation=bull_validation(
                state="BEAR_REJECTION_STRENGTHENED"
            ),
        )

        self.assertEqual(overlay["scenario"]["id"], "SCENARIO_3")
        self.assertEqual(overlay["scenario"]["label"], "情境 3｜假春風險升高")
        veto = overlay["lights"]["conflict_veto"]
        self.assertEqual(veto["threshold_bucket"], "DECISIVE_VETO")
        self.assertIsNone(veto["score"])
        self.assertTrue(overlay["gate_core_veto"]["veto"]["upgrade_blocked"])

    def test_control_transfer_rejection_is_decisive(self) -> None:
        entry = entry_gate()
        entry["control_transfer_validation"]["research_state"] = (
            "FALSE_POSITIVE_REJECTED"
        )
        overlay = build(btc_entry_gate=entry)
        self.assertEqual(
            overlay["lights"]["conflict_veto"]["threshold_bucket"],
            "DECISIVE_VETO",
        )

    def test_post_c_control_transfer_failure_is_decisive(self) -> None:
        overlay = build(
            btc_control_transfer_validation={
                "state": "READY_FOR_ANALYST",
                "research_state": "CONTROL_TRANSFER_CANDIDATE_FAILED",
                "current_validation_status": None,
            }
        )
        veto = overlay["lights"]["conflict_veto"]
        self.assertEqual(veto["threshold_bucket"], "DECISIVE_VETO")
        self.assertIn(
            "POST_C_CONTROL_TRANSFER_CANDIDATE_FAILED",
            veto["raw_metrics"]["decisive_veto_evidence"],
        )

    def test_every_light_has_required_fields_and_l4_raw_metrics(self) -> None:
        overlay = build()
        required = {
            "score",
            "threshold_bucket",
            "light",
            "direction",
            "delta_score",
            "delta_light",
            "raw_metrics",
            "evidence_status",
        }
        self.assertEqual(len(overlay["lights"]), 5)
        for name, light in overlay["lights"].items():
            with self.subTest(light=name):
                self.assertTrue(required <= set(light))
        raw = overlay["lights"]["leverage_quality"]["raw_metrics"]
        self.assertEqual(raw["oi_24h_change"]["percent_change"], 2.5)
        self.assertEqual(raw["oi_3d_change"]["percent_change"], 4.0)
        self.assertEqual(raw["latest_funding_bp"], 1.0)
        self.assertEqual(raw["funding_3d_mean_bp"], 0.75)
        self.assertEqual(raw["long_liquidation_24h_usd"], 1_500_000.0)
        self.assertEqual(raw["short_liquidation_24h_usd"], 2_500_000.0)

    def test_previous_overlay_populates_delta_and_momentum(self) -> None:
        previous = build_season_transition_warning_overlay(
            formal_candidate=candidate(
                price_scores=(40.0, 35.0, 35.0),
                cvd_score=40.0,
                etp_score=36.0,
                l4_score=10.0,
            ),
            layers=layers(),
            changes=changes(),
            btc_bull_validation=bull_validation(),
            btc_entry_gate=entry_gate(),
            transition_diagnostic=transition_diagnostic(),
            generated_at_ms=NOW_MS - 60_000,
            institutional_flow_context=flow_context(),
        )
        overlay = build(previous_overlay=previous)

        self.assertEqual(overlay["evidence_momentum"], "RISING")
        for name in (
            "price_structure",
            "spot_demand",
            "institutional_flow",
            "leverage_quality",
        ):
            with self.subTest(light=name):
                self.assertGreater(overlay["lights"][name]["delta_score"], 0)

    def test_missing_evidence_stays_explicit_and_fail_closed(self) -> None:
        overlay = build_season_transition_warning_overlay(
            formal_candidate={},
            layers={},
            changes={},
            btc_bull_validation=None,
            btc_entry_gate=None,
            transition_diagnostic=None,
            generated_at_ms=NOW_MS,
        )

        for name in (
            "price_structure",
            "spot_demand",
            "institutional_flow",
            "leverage_quality",
        ):
            self.assertIsNone(overlay["lights"][name]["score"])
            self.assertEqual(overlay["lights"][name]["light"], "NOT_AVAILABLE")
        self.assertEqual(overlay["gate_core_veto"]["gate"]["state"], "BLOCKED")
        self.assertIsNone(overlay["formal_season"])

    def test_replay_reports_latency_and_false_positive_without_imputation(self) -> None:
        overlay = build(
            historical_replay_context={
                "historical_case_id": "HISTORICAL-CASE-001",
                "ground_truth_transition_at_ms": NOW_MS - 86_400_000,
                "ground_truth_outcome": "NO_TRANSITION",
            }
        )
        replay = overlay["historical_replay"]
        self.assertEqual(replay["objective"], "DETECTION_LATENCY_X_FALSE_POSITIVE")
        self.assertEqual(replay["detection_latency_ms"], 86_400_000)
        self.assertTrue(replay["false_positive"])

    def test_authority_and_event_coordinate_locks(self) -> None:
        overlay = build()
        authority = overlay["authority"]
        self.assertEqual(overlay["schema_version"], SCHEMA_VERSION)
        self.assertEqual(overlay["formal_season_status"], "NOT_CONFIRMED")
        self.assertIsNone(overlay["formal_season"])
        self.assertFalse(authority["score_may_determine_btc_season"])
        self.assertFalse(authority["machine_may_confirm_bull_transition"])
        self.assertFalse(authority["machine_may_output_trade_action"])
        self.assertEqual(authority["action_output"], "NONE")
        self.assertEqual(authority["external_action_authority"], "NONE")
        self.assertFalse(authority["external_action_performed"])
        coordinates = overlay["lights"]["price_structure"]["raw_metrics"][
            "event_research_coordinates"
        ]
        self.assertEqual(coordinates["attack_zone_usd"], [82000.0, 83000.0])
        self.assertEqual(coordinates["retest_defense_zone_usd"], [80000.0, 82000.0])
        self.assertFalse(coordinates["used_in_score"])
        self.assertEqual(coordinates["formal_threshold_authority"], "NONE")
        self.assertIn("CRT｜季節轉換預警", overlay["card"])
        self.assertEqual(validate_season_transition_warning_overlay(overlay), [])

        tampered = deepcopy(overlay)
        tampered["formal_season"] = "SPRING"
        errors = validate_season_transition_warning_overlay(tampered)
        self.assertIn("Formal Season must remain null", errors)
        self.assertIn("overlay hash mismatch", errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
