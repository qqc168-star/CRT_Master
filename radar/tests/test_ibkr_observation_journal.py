from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase, main

from crt_radar.ibkr_live_market_data_intake import ASSET_ORDER
from crt_radar.ibkr_observation_journal import (
    ZERO_HASH,
    IbkrObservationJournal,
    JournaledIbkrObservationSink,
    replay_observations,
)


PLAN_SHA = "a" * 64
NOW_MS = 1_788_048_000_000
LIVE_TYPES = {asset: 1 for asset in ASSET_ORDER}


class RecordingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.observations: list[tuple] = []

    def on_ibkr_last(
        self,
        asset,
        price,
        observed_at_ms,
        *,
        market_data_types=None,
    ) -> None:
        if self.fail:
            raise RuntimeError("injected downstream failure")
        self.observations.append(
            ("LAST", asset, price, observed_at_ms, market_data_types)
        )

    def on_ibkr_5s_close(
        self,
        asset,
        close,
        observed_at_ms,
        *,
        market_data_types=None,
    ) -> None:
        if self.fail:
            raise RuntimeError("injected downstream failure")
        self.observations.append(
            ("BAR_5S_CLOSE", asset, close, observed_at_ms, market_data_types)
        )


class IbkrObservationJournalTests(TestCase):
    def test_append_is_hash_chained_and_round_trips_live_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "observations.sqlite3"
            with IbkrObservationJournal(
                path,
                plan_sha=PLAN_SHA,
                asset="MSTR",
            ) as journal:
                first = journal.append(
                    asset="MSTR",
                    channel="LAST",
                    price=100.01,
                    observed_at_ms=NOW_MS,
                    market_data_types=LIVE_TYPES,
                )
                second = journal.append(
                    asset="MSTR",
                    channel="BAR_5S_CLOSE",
                    price=100.02,
                    observed_at_ms=NOW_MS + 5_000,
                    market_data_types=LIVE_TYPES,
                )
                records = journal.records_after(0)
                head = journal.head()

        self.assertEqual(first["previous_hash"], ZERO_HASH)
        self.assertEqual(second["previous_hash"], first["record_hash"])
        self.assertEqual(head, (2, second["record_hash"]))
        self.assertEqual(records[1]["market_data_types"], LIVE_TYPES)
        self.assertEqual(records[1]["action_output"], "NONE")
        self.assertEqual(records[1]["machine_execution"], "FORBIDDEN")

    def test_non_live_proof_is_blocked_without_append(self) -> None:
        delayed = dict(LIVE_TYPES)
        delayed["STRC"] = 2
        with tempfile.TemporaryDirectory() as temp_dir:
            with IbkrObservationJournal(
                Path(temp_dir) / "observations.sqlite3",
                plan_sha=PLAN_SHA,
                asset="MSTR",
            ) as journal:
                with self.assertRaisesRegex(ValueError, "not fully live"):
                    journal.append(
                        asset="MSTR",
                        channel="LAST",
                        price=100.0,
                        observed_at_ms=NOW_MS,
                        market_data_types=delayed,
                    )
                self.assertEqual(journal.head(), (0, ZERO_HASH))

    def test_record_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "observations.sqlite3"
            with IbkrObservationJournal(
                path,
                plan_sha=PLAN_SHA,
                asset="MSTR",
            ) as journal:
                journal.append(
                    asset="MSTR",
                    channel="LAST",
                    price=100.0,
                    observed_at_ms=NOW_MS,
                    market_data_types=LIVE_TYPES,
                )
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "UPDATE observations SET price = 999.0 WHERE sequence = 1"
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "record hash mismatch"):
                IbkrObservationJournal(
                    path,
                    plan_sha=PLAN_SHA,
                    asset="MSTR",
                )

    def test_journal_is_bound_to_exact_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "observations.sqlite3"
            with IbkrObservationJournal(
                path,
                plan_sha=PLAN_SHA,
                asset="MSTR",
            ):
                pass
            with self.assertRaisesRegex(ValueError, "metadata mismatch"):
                IbkrObservationJournal(
                    path,
                    plan_sha="b" * 64,
                    asset="MSTR",
                )

    def test_committed_observation_replays_after_downstream_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "observations.sqlite3"
            with IbkrObservationJournal(
                path,
                plan_sha=PLAN_SHA,
                asset="MSTR",
            ) as journal:
                sink = JournaledIbkrObservationSink(
                    journal,
                    RecordingSink(fail=True),
                )
                with self.assertRaisesRegex(RuntimeError, "downstream failure"):
                    sink.on_ibkr_last(
                        "MSTR",
                        100.01,
                        NOW_MS,
                        market_data_types=LIVE_TYPES,
                    )
                self.assertEqual(journal.head()[0], 1)
                recovered = RecordingSink()
                replayed = replay_observations(
                    journal,
                    recovered,
                    after_sequence=0,
                )

        self.assertEqual(replayed, 1)
        self.assertEqual(recovered.observations[0][0:4], ("LAST", "MSTR", 100.01, NOW_MS))


if __name__ == "__main__":
    main(verbosity=2)
