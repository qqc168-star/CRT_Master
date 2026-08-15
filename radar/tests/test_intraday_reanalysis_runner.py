from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.intraday_reanalysis_runner import run_intraday_reanalysis
from crt_radar.observation_store import Observation, ObservationStore


SOURCE_ID = "CRT-CONN-BTC-SPOT-BINANCE-WAKE-001"
REGISTRY_HASH = "a" * 64


def ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def observation(as_of_ms: int, value: float, index: int) -> Observation:
    return Observation(
        layer_id="AS-L3",
        input_family="BTC_SPOT_PRICE",
        metric="btc_spot_price_usd",
        as_of_ms=as_of_ms,
        value_num=value,
        source_id=SOURCE_ID,
        quality_state="VALID_FRESH",
        evidence_hash=hashlib.sha256(f"btc:{index}".encode()).hexdigest(),
        registry_hash=REGISTRY_HASH,
        recorded_run_id=f"replay-{index}",
        recorded_at_ms=as_of_ms,
    )


class IntradayReanalysisRunnerTests(unittest.TestCase):
    def test_runner_reads_history_and_stays_silent_without_a_material_move(self):
        with tempfile.TemporaryDirectory() as td:
            with ObservationStore(Path(td) / "observations.sqlite3") as store:
                base = ms("2026-08-14T09:00:00")
                history = [observation(base + index * 300_000, 100 + index * 0.2, index) for index in range(10)]
                store.record(history)
                before = store.count()

                result = run_intraday_reanalysis(
                    store,
                    observation(base + 10 * 300_000, 102.0, 10),
                )

                self.assertEqual(result["state"], "NO_WAKE")
                self.assertEqual(result["action_output"], "NONE")
                self.assertEqual(result["external_action_authority"], "NONE")
                self.assertFalse(result["external_action_performed"])
                self.assertEqual(store.count(), before)

    def test_replay_2026_08_14_drop_requests_reanalysis_only(self):
        """Replay the material intraday leg without turning it into a trade signal."""
        with tempfile.TemporaryDirectory() as td:
            with ObservationStore(Path(td) / "observations.sqlite3") as store:
                base = ms("2026-08-14T12:00:00")
                calm_prices = [
                    118.00,
                    118.12,
                    118.04,
                    118.18,
                    118.10,
                    118.22,
                    118.14,
                    118.26,
                    118.18,
                    118.30,
                ]
                store.record(
                    [
                        observation(base + index * 300_000, value, index)
                        for index, value in enumerate(calm_prices)
                    ]
                )

                result = run_intraday_reanalysis(
                    store,
                    observation(base + len(calm_prices) * 300_000, 108.0, 100),
                )

                self.assertEqual(result["state"], "REANALYSIS_REQUESTED")
                self.assertEqual(result["reason"], "MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY")
                self.assertEqual(result["action_output"], "NONE")
                self.assertEqual(result["external_action_authority"], "NONE")
                self.assertFalse(result["external_action_performed"])

    def test_runner_rejects_non_spot_or_non_as_l3_observations(self):
        with tempfile.TemporaryDirectory() as td:
            with ObservationStore(Path(td) / "observations.sqlite3") as store:
                current = observation(ms("2026-08-15T09:00:00"), 100.0, 1)
                with self.assertRaises(ValueError):
                    run_intraday_reanalysis(
                        store,
                        Observation(
                            **{
                                **current.__dict__,
                                "input_family": "OPEN_INTEREST",
                            }
                        ),
                    )
                with self.assertRaises(ValueError):
                    run_intraday_reanalysis(
                        store,
                        Observation(**{**current.__dict__, "layer_id": "AS-L4"}),
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
