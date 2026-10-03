from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from crt_radar.change_engine import compute_changes
from crt_radar.observation_store import (
    Observation,
    ObservationRevisionConflict,
    ObservationStore,
    extract_observations,
)
from crt_radar.source_gate_runner import (
    FetchResult,
    _evidence_envelope,
    parse_fred_latest,
)
from crt_radar.source_registry import SourceRegistry


ROOT = Path(__file__).resolve().parents[1]
BASE_MS = 2_000_000_000_000
DAY_MS = 86_400_000
FAMILY = "DOLLAR_STRENGTH_PROXY"
METRIC = "broad_usd_proxy"
SOURCE_ID = "CRT-CONN-FX-FRED-BROAD-USD-PROXY-001"
OI_SOURCE_ID = "CRT-CONN-BTC-DERIV-BINANCE-OI-001"


def _row(token: str, **changes) -> Observation:
    observation = Observation(
        layer_id="AS-L2",
        input_family=FAMILY,
        metric=METRIC,
        as_of_ms=BASE_MS,
        value_num=120.5,
        source_id=SOURCE_ID,
        quality_state="VALID_FRESH",
        evidence_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        registry_hash="1" * 64,
        recorded_run_id=f"run-{token}",
        recorded_at_ms=BASE_MS + 100,
    )
    return replace(observation, **changes)


def _oi_row(token: str, **changes) -> Observation:
    return _row(
        token,
        layer_id="AS-L4",
        input_family="OPEN_INTEREST",
        metric="open_interest_contracts",
        source_id=OI_SOURCE_ID,
        **changes,
    )


class ObservationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = ObservationStore(Path(self.temp_dir.name) / "observations.sqlite3")
        self.addCleanup(self.store.close)

    def _project(
        self,
        *,
        store=None,
        visible_at_ms=BASE_MS + 10_000,
        allowed_source_ids=(SOURCE_ID,),
        before_as_of_ms=None,
    ):
        return (store or self.store).scoring_series(
            FAMILY,
            METRIC,
            visible_at_ms=visible_at_ms,
            expected_layer_id="AS-L2",
            allowed_source_ids=allowed_source_ids,
            before_as_of_ms=before_as_of_ms,
        )

    def _project_oi(self, *, visible_at_ms, before_as_of_ms=None):
        return self.store.scoring_series(
            "OPEN_INTEREST",
            "open_interest_contracts",
            visible_at_ms=visible_at_ms,
            expected_layer_id="AS-L4",
            allowed_source_ids=(OI_SOURCE_ID,),
            before_as_of_ms=before_as_of_ms,
        )

    def test_actual_transport_envelopes_retain_audit_rows_but_one_scoring_fact(self):
        registry = SourceRegistry.load(ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json")
        spec = registry.by_input_family(FAMILY)
        payload = "DATE,DTWEXBGS\n2026-07-31,120.50\n"
        parsed = parse_fred_latest(payload)
        captured = []
        envelopes = []
        for index, (attempts, elapsed_ms) in enumerate(((1, 10.0), (3, 500.0))):
            envelope = _evidence_envelope(
                spec,
                FetchResult(
                    spec.source_id,
                    "OK",
                    payload=payload,
                    attempts=attempts,
                    elapsed_ms=elapsed_ms,
                ),
                registry_hash=registry.hash,
                parsed=parsed,
                quality_state="VALID_FRESH",
            )
            envelopes.append(envelope)
            captured.extend(
                extract_observations(
                    {
                        "run_id": f"transport-{index}",
                        "source_registry_hash": registry.hash,
                        "evidence": [envelope],
                        "parsed": {FAMILY: parsed},
                    },
                    recorded_at_ms=BASE_MS + 100 + index * 100,
                )
            )

        self.assertEqual(envelopes[0]["payload_hash"], envelopes[1]["payload_hash"])
        self.assertNotEqual(envelopes[0]["evidence_hash"], envelopes[1]["evidence_hash"])
        self.assertEqual(self.store.record(captured), 2)
        raw_before = self.store.series(FAMILY, METRIC)
        self.assertEqual(self._project(), [captured[0]])
        self.assertEqual(self.store.series(FAMILY, METRIC), raw_before)
        self.assertEqual(self.store.count(), 2)
        self.assertEqual(self.store.record(captured), 0)

    def test_existing_duplicate_rows_project_without_a_schema_or_data_migration(self):
        first = _row("legacy-first")
        repeat = _row(
            "legacy-repeat",
            recorded_at_ms=BASE_MS + 200,
            registry_hash="2" * 64,
            recorded_run_id="different-capture-run",
            quality_state="VALID_FRESH_COMPLETE_COVERAGE",
        )
        self.store.record([repeat, first])
        with ObservationStore(self.store.path) as reopened:
            raw_before = reopened.series(FAMILY, METRIC)
            schema_before = reopened.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'observations'"
            ).fetchone()[0]

            self.assertEqual(self._project(store=reopened), [first])
            self.assertEqual(reopened.series(FAMILY, METRIC), raw_before)
            self.assertEqual(reopened.count(), 2)
            self.assertEqual(
                reopened.conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'observations'"
                ).fetchone()[0],
                schema_before,
            )

    def test_equal_value_same_capture_time_is_one_general_fact(self):
        first = _row("equal-tie-a")
        repeat = _row("equal-tie-b")
        self.store.record([first, repeat])
        projected = self._project()
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0].value_num, first.value_num)
        self.assertEqual(projected[0].recorded_at_ms, first.recorded_at_ms)
        self.assertEqual(self.store.count(), 2)

    def test_future_repeat_does_not_change_past_view_or_first_capture(self):
        first = _row("repeat-first")
        self.store.record([first])
        before = self._project(visible_at_ms=BASE_MS + 150)
        future_repeat = _row("repeat-future", recorded_at_ms=BASE_MS + 200)
        self.store.record([future_repeat])

        self.assertEqual(self._project(visible_at_ms=BASE_MS + 150), before)
        self.assertEqual(self._project(visible_at_ms=BASE_MS + 250), [first])
        self.assertEqual(self.store.count(), 2)

    def test_future_conflict_is_invisible_until_its_recording_time(self):
        first = _row("conflict-first")
        self.store.record([first])
        before = self._project(visible_at_ms=BASE_MS + 150)
        future_conflict = _row(
            "conflict-future",
            value_num=121.0,
            recorded_at_ms=BASE_MS + 200,
        )
        self.store.record([future_conflict])

        self.assertEqual(self._project(visible_at_ms=BASE_MS + 150), before)
        with self.assertRaisesRegex(
            ObservationRevisionConflict, "OBSERVATION_REVISION_CONFLICT_BLOCKED"
        ):
            self._project(visible_at_ms=BASE_MS + 200)
        self.assertEqual(self.store.series(FAMILY, METRIC), [first, future_conflict])
        self.assertEqual(self.store.count(), 2)

    def test_delayed_first_capture_is_not_visible_at_the_observation_clock(self):
        delayed = _row("delayed", recorded_at_ms=BASE_MS + DAY_MS)
        self.store.record([delayed])
        self.assertEqual(self._project(visible_at_ms=BASE_MS), [])
        self.assertEqual(self._project(visible_at_ms=BASE_MS + DAY_MS), [delayed])

    def test_equal_values_at_different_observation_periods_remain_distinct(self):
        first = _row("period-first")
        second = _row(
            "period-second",
            as_of_ms=BASE_MS + DAY_MS,
            recorded_at_ms=BASE_MS + DAY_MS + 100,
        )
        self.store.record([second, first])
        self.assertEqual(
            self._project(visible_at_ms=BASE_MS + 2 * DAY_MS), [first, second]
        )
        self.assertEqual(self.store.count(), 2)

    def test_later_changed_value_is_blocked_without_generic_latest_wins(self):
        first = _row("visible-first")
        changed = _row(
            "visible-change",
            value_num=120.50000000000001,
            recorded_at_ms=BASE_MS + 200,
        )
        self.store.record([changed, first])
        raw_before = self.store.series(FAMILY, METRIC)
        with self.assertRaisesRegex(
            ObservationRevisionConflict, "OBSERVATION_REVISION_CONFLICT_BLOCKED"
        ):
            self._project()
        self.assertEqual(self.store.series(FAMILY, METRIC), raw_before)
        self.assertEqual(self.store.count(), 2)

    def test_invalid_provenance_is_never_hidden_by_an_equal_value_capture(self):
        cases = (
            {"source_id": "UNAPPROVED-SOURCE"},
            {"layer_id": "AS-L5"},
            {"quality_state": "STALE"},
        )
        for case_index, changes in enumerate(cases):
            for invalid_first in (False, True):
                with self.subTest(changes=changes, invalid_first=invalid_first):
                    path = Path(self.temp_dir.name) / f"provenance-{case_index}-{invalid_first}.sqlite3"
                    with ObservationStore(path) as store:
                        valid = _row(
                            "valid",
                            recorded_at_ms=BASE_MS + (200 if invalid_first else 100),
                        )
                        invalid = _row(
                            "invalid",
                            recorded_at_ms=BASE_MS + (100 if invalid_first else 200),
                            **changes,
                        )
                        store.record([valid, invalid])
                        with self.assertRaisesRegex(
                            ObservationRevisionConflict,
                            "HISTORY_PROVENANCE_NOT_APPROVED_BLOCKED",
                        ):
                            self._project(store=store)
                        self.assertEqual(store.count(), 2)

    def test_future_invalid_provenance_cannot_poison_past_replay(self):
        first = _row("provenance-first")
        self.store.record([first])
        before = self._project(visible_at_ms=BASE_MS + 150)
        self.store.record(
            [
                _row(
                    "future-invalid",
                    source_id="UNAPPROVED-SOURCE",
                    quality_state="STALE",
                    recorded_at_ms=BASE_MS + 200,
                )
            ]
        )
        self.assertEqual(self._project(visible_at_ms=BASE_MS + 150), before)
        with self.assertRaisesRegex(
            ObservationRevisionConflict, "HISTORY_PROVENANCE_NOT_APPROVED_BLOCKED"
        ):
            self._project(visible_at_ms=BASE_MS + 200)

    def test_two_allowed_sources_at_one_period_are_not_merged_or_selected(self):
        for index, second_value in enumerate((120.5, 121.0)):
            with self.subTest(second_value=second_value):
                with ObservationStore(Path(self.temp_dir.name) / f"sources-{index}.sqlite3") as store:
                    store.record(
                        [
                            _row("source-first"),
                            _row(
                                "source-second",
                                source_id="SECOND-ALLOWED-SOURCE",
                                value_num=second_value,
                                recorded_at_ms=BASE_MS + 200,
                            ),
                        ]
                    )
                    with self.assertRaisesRegex(
                        ObservationRevisionConflict, "SOURCE_IDENTITY_MISMATCH_BLOCKED"
                    ):
                        self._project(
                            store=store,
                            allowed_source_ids=(SOURCE_ID, "SECOND-ALLOWED-SOURCE"),
                        )
                    self.assertEqual(store.count(), 2)

    def test_invalid_visible_clocks_and_nonfinite_values_fail_closed(self):
        cases = (
            ({"as_of_ms": 0}, "REVISION_CLOCK_INVALID_BLOCKED"),
            ({"as_of_ms": -1}, "REVISION_CLOCK_INVALID_BLOCKED"),
            ({"recorded_at_ms": 0}, "REVISION_CLOCK_INVALID_BLOCKED"),
            ({"recorded_at_ms": BASE_MS - 1}, "REVISION_CLOCK_INVALID_BLOCKED"),
            ({"value_num": float("inf")}, "OBSERVATION_VALUE_INVALID_BLOCKED"),
            ({"value_num": float("-inf")}, "OBSERVATION_VALUE_INVALID_BLOCKED"),
        )
        for index, (changes, blocked_state) in enumerate(cases):
            with self.subTest(changes=changes):
                with ObservationStore(Path(self.temp_dir.name) / f"invalid-{index}.sqlite3") as store:
                    store.record([_row("invalid-row", **changes)])
                    with self.assertRaisesRegex(ObservationRevisionConflict, blocked_state):
                        self._project(store=store)
                    self.assertEqual(store.count(), 1)

    def test_optional_cutoff_includes_only_strictly_prior_general_periods(self):
        prior = _row("cutoff-prior")
        boundary = _row(
            "cutoff-boundary",
            as_of_ms=BASE_MS + DAY_MS,
            recorded_at_ms=BASE_MS + DAY_MS + 100,
        )
        boundary_conflict = replace(
            boundary,
            value_num=130.0,
            evidence_hash=hashlib.sha256(b"cutoff-conflict").hexdigest(),
            recorded_at_ms=BASE_MS + DAY_MS + 200,
        )
        self.store.record([prior, boundary, boundary_conflict])
        self.assertEqual(
            self._project(
                visible_at_ms=BASE_MS + 2 * DAY_MS,
                before_as_of_ms=boundary.as_of_ms,
            ),
            [prior],
        )
        with self.assertRaisesRegex(
            ObservationRevisionConflict, "OBSERVATION_REVISION_CONFLICT_BLOCKED"
        ):
            self._project(visible_at_ms=BASE_MS + 2 * DAY_MS)
        self.assertEqual(self.store.count(), 3)

    def _change_fixture(self):
        history = [
            _row(
                f"baseline-{index}",
                as_of_ms=BASE_MS + index * DAY_MS,
                recorded_at_ms=BASE_MS + index * DAY_MS + 100,
                value_num=100.0 + index,
            )
            for index in range(10)
        ]
        current = _row(
            "baseline-current",
            as_of_ms=BASE_MS + 10 * DAY_MS,
            recorded_at_ms=BASE_MS + 10 * DAY_MS + 500,
            value_num=115.0,
        )
        self.store.record([*history, current])
        return history, current

    def test_transport_repeats_do_not_inflate_change_baselines(self):
        history, current = self._change_fixture()
        before = compute_changes(self.store, [current])
        repeats = [
            replace(
                row,
                evidence_hash=hashlib.sha256(f"repeat-{index}".encode()).hexdigest(),
                registry_hash="2" * 64,
                recorded_run_id=f"repeat-{index}",
                recorded_at_ms=current.recorded_at_ms - 1,
            )
            for index, row in enumerate(history)
        ]
        self.store.record(repeats)

        self.assertGreater(before[METRIC]["horizons"]["1d"]["baseline_count"], 0)
        self.assertEqual(compute_changes(self.store, [current]), before)
        self.assertEqual(self.store.count(), 21)

    def test_later_records_do_not_change_past_change_engine_results(self):
        history, current = self._change_fixture()
        before = compute_changes(self.store, [current])
        future_repeat = replace(
            history[0],
            evidence_hash=hashlib.sha256(b"change-future-repeat").hexdigest(),
            recorded_run_id="change-future-repeat",
            recorded_at_ms=current.recorded_at_ms + 1,
        )
        future_conflict = replace(
            history[-1],
            value_num=500.0,
            evidence_hash=hashlib.sha256(b"change-future-conflict").hexdigest(),
            recorded_run_id="change-future-conflict",
            recorded_at_ms=current.recorded_at_ms + 1,
        )
        future_period = _row(
            "change-future-period",
            as_of_ms=current.as_of_ms + DAY_MS,
            recorded_at_ms=current.as_of_ms + DAY_MS + 100,
            value_num=600.0,
        )
        self.store.record([future_repeat, future_conflict, future_period])

        self.assertEqual(compute_changes(self.store, [current]), before)
        self.assertEqual(self.store.count(), 14)

    def test_visible_conflict_blocks_change_engine_horizons_without_change_values(self):
        history, current = self._change_fixture()
        before = compute_changes(self.store, [current])
        self.assertEqual(before[METRIC]["horizons"]["1d"]["history_state"], "AVAILABLE")
        conflicting = replace(
            history[-1],
            value_num=500.0,
            evidence_hash=hashlib.sha256(b"change-visible-conflict").hexdigest(),
            recorded_run_id="change-visible-conflict",
            recorded_at_ms=current.recorded_at_ms - 1,
        )
        self.store.record([conflicting])

        result = compute_changes(self.store, [current])
        for horizon in result[METRIC]["horizons"].values():
            self.assertEqual(
                horizon["history_state"], "OBSERVATION_REVISION_CONFLICT_BLOCKED"
            )
            self.assertIn("OBSERVATION_REVISION_CONFLICT_BLOCKED", horizon["blocked_reason"])
            self.assertNotIn("previous_value", horizon)
            self.assertNotIn("absolute_change", horizon)
            self.assertNotIn("magnitude_percentile", horizon)
        self.assertEqual(self.store.count(), 12)

    def test_oi_equal_value_same_release_tie_retains_existing_blocker(self):
        first = _oi_row("oi-equal-a")
        repeat = _oi_row("oi-equal-b")
        self.store.record([first, repeat])
        with self.assertRaisesRegex(
            ObservationRevisionConflict, "AMBIGUOUS_REVISION_BLOCKED"
        ):
            self._project_oi(visible_at_ms=BASE_MS + 100)
        self.assertEqual(self.store.series(first.input_family, first.metric), [first, repeat])
        self.assertEqual(self.store.count(), 2)

    def test_oi_legal_and_future_revisions_keep_existing_selection(self):
        first = _oi_row("oi-base", value_num=100.0)
        revision = _oi_row(
            "oi-revision", value_num=120.0, recorded_at_ms=BASE_MS + 200
        )
        self.store.record([first])
        before = self._project_oi(visible_at_ms=BASE_MS + 150)
        self.store.record([revision])

        self.assertEqual(self._project_oi(visible_at_ms=BASE_MS + 150), before)
        self.assertEqual(before, [first])
        self.assertEqual(
            self._project_oi(visible_at_ms=BASE_MS + 250), [revision]
        )
        self.assertEqual(
            self._project_oi(visible_at_ms=BASE_MS + 250),
            self.store.point_in_time_series(
                first.input_family, first.metric, visible_at_ms=BASE_MS + 250
            ),
        )
        self.assertEqual(self.store.count(), 2)

    def test_oi_prior_cutoff_does_not_bypass_existing_revision_checks(self):
        prior = _oi_row("oi-cutoff-prior")
        boundary = _oi_row(
            "oi-cutoff-boundary",
            as_of_ms=BASE_MS + DAY_MS,
            recorded_at_ms=BASE_MS + DAY_MS + 100,
        )
        self.store.record([prior, boundary])
        self.assertEqual(
            self._project_oi(
                visible_at_ms=BASE_MS + 2 * DAY_MS,
                before_as_of_ms=boundary.as_of_ms,
            ),
            [prior],
        )
        tied = replace(
            boundary,
            evidence_hash=hashlib.sha256(b"oi-cutoff-tie").hexdigest(),
            recorded_run_id="oi-cutoff-tie",
        )
        self.store.record([tied])
        with self.assertRaisesRegex(
            ObservationRevisionConflict, "AMBIGUOUS_REVISION_BLOCKED"
        ):
            self._project_oi(
                visible_at_ms=BASE_MS + 2 * DAY_MS,
                before_as_of_ms=boundary.as_of_ms,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
