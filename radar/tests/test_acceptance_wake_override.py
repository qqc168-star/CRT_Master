from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from crt_radar.daily_evidence_runner import main, run_daily_evidence
import test_daily_evidence_runner as daily_fixtures

from crt_radar.daily_evidence_runner import (
    _resolve_wake_operational_percentile,
)


class AcceptanceWakeOverrideTests(unittest.TestCase):
    def test_cli_requires_confirmation_before_running_cycle(self):
        with patch("crt_radar.daily_evidence_runner.run_daily_evidence") as runner:
            with self.assertRaisesRegex(ValueError, "requires"):
                main(["--acceptance-wake-percentile", "0.1"])
            runner.assert_not_called()

    def test_evidence_pack_override_then_normal_cycle_has_no_residue(self):
        fixture = daily_fixtures.DailyEvidenceRunnerTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory() as directory:
            args = dict(
                observation_db=Path(directory) / "observations.sqlite3",
                fetch_overrides=fixture.overrides,
                liquidation_aggregate_payload=fixture.aggregate(),
                now_ms=daily_fixtures.NOW_MS, generated_at_ms=daily_fixtures.NOW_MS,
                dvol_regime_runner=lambda **_: {
                    "recommended_wake_operational_percentile": 90.0},
            )
            acceptance = run_daily_evidence(fixture.registry,
                acceptance_wake_operational_percentile=0.1, **args)
            ordinary = run_daily_evidence(fixture.registry, **args)
        self.assertEqual(acceptance["reanalysis_wake"]["operational_percentile"], 0.1)
        metadata = acceptance["reanalysis_wake"]["acceptance_override"]
        self.assertTrue(metadata["acceptance_override_used"])
        self.assertEqual(metadata["production_wake_operational_percentile"], 90.0)
        self.assertFalse(metadata["persistent_configuration_changed"])
        self.assertEqual(ordinary["reanalysis_wake"]["operational_percentile"], 90.0)
        self.assertNotIn("acceptance_override", ordinary["reanalysis_wake"])
        for pack in (acceptance, ordinary):
            self.assertEqual(pack["formal_candidate"]["production"], "NOT_APPROVED")
            self.assertEqual(pack["authority"]["external_action_authority"], "NONE")

    def test_no_override_preserves_dvol_recommendation(self):
        effective, metadata = _resolve_wake_operational_percentile(
            {"recommended_wake_operational_percentile": 90.0},
            None,
        )
        self.assertEqual(effective, 90.0)
        self.assertIsNone(metadata)

    def test_one_shot_override_preserves_production_value_in_audit_metadata(self):
        effective, metadata = _resolve_wake_operational_percentile(
            {"recommended_wake_operational_percentile": 90.0},
            0.1,
        )
        self.assertEqual(effective, 0.1)
        assert metadata is not None
        self.assertTrue(metadata["acceptance_override_used"])
        self.assertEqual(
            metadata["scope"],
            "ONE_SHOT_TRANSPORT_ACCEPTANCE_ONLY",
        )
        self.assertEqual(
            metadata["production_wake_operational_percentile"],
            90.0,
        )
        self.assertEqual(
            metadata["acceptance_wake_operational_percentile"],
            0.1,
        )
        self.assertFalse(
            metadata["persistent_configuration_changed"]
        )
        self.assertEqual(
            metadata["formal_threshold_authority"],
            "NONE",
        )
        self.assertEqual(
            metadata["investment_threshold_authority"],
            "NONE",
        )

    def test_next_invocation_restores_production_without_mutating_recommendation(self):
        regime = {"recommended_wake_operational_percentile": 95.0}
        _resolve_wake_operational_percentile(regime, 0.1)
        self.assertEqual(_resolve_wake_operational_percentile(regime, None), (95.0, None))
        self.assertEqual(regime, {"recommended_wake_operational_percentile": 95.0})

    def test_invalid_override_fails_closed(self):
        for value in (0.0, -1.0, 100.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _resolve_wake_operational_percentile(
                        {
                            "recommended_wake_operational_percentile":
                            95.0
                        },
                        value,
                    )

    def test_invalid_dvol_recommendation_falls_back_without_override(self):
        effective, metadata = _resolve_wake_operational_percentile(
            {"recommended_wake_operational_percentile": "bad"},
            None,
        )
        self.assertEqual(effective, 95.0)
        self.assertIsNone(metadata)


if __name__ == "__main__":
    unittest.main(verbosity=2)
