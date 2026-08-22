from __future__ import annotations

import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from crt_radar.change_engine import compute_changes
from crt_radar.observation_store import (
    Observation,
    ObservationRevisionConflict,
    ObservationStore,
)
from crt_radar import oi_revision_policy


DAY_MS = 86_400_000
BASE_MS = 2_000_000_000_000


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _observation(
    *,
    as_of_ms: int,
    value: float,
    recorded_at_ms: int,
    token: str,
    input_family: str = "OPEN_INTEREST",
    metric: str = "open_interest_contracts",
    source_id: str = "CRT-CONN-BTC-DERIV-BINANCE-OI-001",
    layer_id: str = "AS-L4",
) -> Observation:
    return Observation(
        layer_id=layer_id,
        input_family=input_family,
        metric=metric,
        as_of_ms=as_of_ms,
        value_num=value,
        source_id=source_id,
        quality_state="VALID_FRESH",
        evidence_hash=_sha256(token),
        registry_hash="1" * 64,
        recorded_run_id=f"run-{token}",
        recorded_at_ms=recorded_at_ms,
    )


class L4OiPointInTimeRevisionPolicyTests(unittest.TestCase):
    def test_policy_hash_scope_registry_and_authority_validate(self):
        policy = oi_revision_policy.load_policy()
        self.assertEqual(oi_revision_policy.validate_policy(policy), [])
        self.assertEqual(
            oi_revision_policy.canonical_hash(policy),
            oi_revision_policy.EXPECTED_POLICY_CANONICAL_SHA256,
        )
        self.assertEqual(policy["authority"]["exact_policy_hash"], "NOT_YET_APPROVED")
        self.assertEqual(policy["authority"]["runtime_binding"], "NOT_APPROVED")
        self.assertEqual(policy["authority"]["production"], "NOT_APPROVED")
        self.assertEqual(policy["authority"]["external_action_authority"], "NONE")
        self.assertIsNone(policy["integration_boundary"]["season_output"])

    def test_policy_drift_and_authority_escalation_are_rejected(self):
        policy = deepcopy(oi_revision_policy.load_policy())
        policy["point_in_time_contract"]["selection_rule"] = "last database row wins"
        policy["authority"]["runtime_binding"] = "APPROVED"
        policy["integration_boundary"]["may_determine_btc_season"] = True
        errors = oi_revision_policy.validate_policy(policy)
        self.assertIn("policy canonical hash drift", errors)
        self.assertIn("point-in-time revision contract changed", errors)
        self.assertIn("policy authority boundary changed", errors)
        self.assertIn("integration boundary changed", errors)

    def test_raw_revisions_are_preserved_and_future_revision_is_invisible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with ObservationStore(Path(temp_dir) / "observations.sqlite3") as store:
                base = _observation(
                    as_of_ms=BASE_MS,
                    value=100.0,
                    recorded_at_ms=BASE_MS + 100,
                    token="base",
                )
                revision = _observation(
                    as_of_ms=BASE_MS,
                    value=120.0,
                    recorded_at_ms=BASE_MS + 200,
                    token="revision",
                )
                self.assertEqual(store.record([base, revision]), 2)
                self.assertEqual(store.count(), 2)
                self.assertEqual(len(store.series(base.input_family, base.metric)), 2)

                before = store.point_in_time_series(
                    base.input_family,
                    base.metric,
                    visible_at_ms=BASE_MS + 150,
                )
                after = store.point_in_time_series(
                    base.input_family,
                    base.metric,
                    visible_at_ms=BASE_MS + 250,
                )

        self.assertEqual([(row.as_of_ms, row.value_num) for row in before], [(BASE_MS, 100.0)])
        self.assertEqual([(row.as_of_ms, row.value_num) for row in after], [(BASE_MS, 120.0)])

    def test_scoped_latest_lookup_requires_an_explicit_visibility_clock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with ObservationStore(Path(temp_dir) / "observations.sqlite3") as store:
                row = _observation(
                    as_of_ms=BASE_MS,
                    value=100.0,
                    recorded_at_ms=BASE_MS + 100,
                    token="visibility",
                )
                store.record([row])
                with self.assertRaisesRegex(
                    oi_revision_policy.OiRevisionPolicyError,
                    "L4_OI_POINT_IN_TIME_VISIBILITY_REQUIRED",
                ):
                    store.latest_at_or_before(
                        row.input_family,
                        row.metric,
                        BASE_MS,
                        max_gap_ms=1,
                    )

    def test_same_release_tie_fails_closed_without_hash_tiebreak(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with ObservationStore(Path(temp_dir) / "observations.sqlite3") as store:
                store.record(
                    [
                        _observation(
                            as_of_ms=BASE_MS,
                            value=100.0,
                            recorded_at_ms=BASE_MS + 100,
                            token="tie-a",
                        ),
                        _observation(
                            as_of_ms=BASE_MS,
                            value=101.0,
                            recorded_at_ms=BASE_MS + 100,
                            token="tie-b",
                        ),
                    ]
                )
                with self.assertRaisesRegex(
                    ObservationRevisionConflict,
                    "AMBIGUOUS_REVISION_BLOCKED",
                ):
                    store.point_in_time_series(
                        "OPEN_INTEREST",
                        "open_interest_contracts",
                        visible_at_ms=BASE_MS + 100,
                    )

    def test_source_substitution_and_backdating_fail_closed(self):
        cases = (
            {
                "token": "wrong-source",
                "source_id": "INVENTED-SOURCE",
                "recorded_at_ms": BASE_MS + 100,
                "error": "SOURCE_IDENTITY_MISMATCH_BLOCKED",
            },
            {
                "token": "backdated",
                "source_id": "CRT-CONN-BTC-DERIV-BINANCE-OI-001",
                "recorded_at_ms": BASE_MS - 1,
                "error": "REVISION_CLOCK_INVALID_BLOCKED",
            },
        )
        for case in cases:
            with self.subTest(error=case["error"]), tempfile.TemporaryDirectory() as temp_dir:
                with ObservationStore(Path(temp_dir) / "observations.sqlite3") as store:
                    store.record(
                        [
                            _observation(
                                as_of_ms=BASE_MS,
                                value=100.0,
                                recorded_at_ms=case["recorded_at_ms"],
                                token=case["token"],
                                source_id=case["source_id"],
                            )
                        ]
                    )
                    with self.assertRaisesRegex(ObservationRevisionConflict, case["error"]):
                        store.point_in_time_series(
                            "OPEN_INTEREST",
                            "open_interest_contracts",
                            visible_at_ms=BASE_MS + 200,
                        )

    def test_change_engine_uses_only_the_revision_visible_at_evaluation(self):
        history_as_of = BASE_MS + DAY_MS
        current_as_of = history_as_of + DAY_MS
        current_recorded_at = current_as_of + 100
        with tempfile.TemporaryDirectory() as temp_dir:
            with ObservationStore(Path(temp_dir) / "observations.sqlite3") as store:
                base = _observation(
                    as_of_ms=history_as_of,
                    value=100.0,
                    recorded_at_ms=history_as_of + 100,
                    token="change-base",
                )
                future_revision = _observation(
                    as_of_ms=history_as_of,
                    value=150.0,
                    recorded_at_ms=current_recorded_at + 1,
                    token="change-future",
                )
                current = _observation(
                    as_of_ms=current_as_of,
                    value=110.0,
                    recorded_at_ms=current_recorded_at,
                    token="change-current",
                )
                store.record([base, future_revision, current])
                result = compute_changes(store, [current])

        one_day = result["open_interest_contracts"]["horizons"]["1d"]
        self.assertEqual(one_day["history_state"], "AVAILABLE")
        self.assertEqual(one_day["previous_value"], 100.0)
        self.assertEqual(one_day["absolute_change"], 10.0)

    def test_change_engine_discloses_ambiguity_and_emits_no_change(self):
        history_as_of = BASE_MS + DAY_MS
        current_as_of = history_as_of + DAY_MS
        with tempfile.TemporaryDirectory() as temp_dir:
            with ObservationStore(Path(temp_dir) / "observations.sqlite3") as store:
                tied_recorded_at = history_as_of + 100
                current = _observation(
                    as_of_ms=current_as_of,
                    value=110.0,
                    recorded_at_ms=current_as_of + 100,
                    token="blocked-current",
                )
                store.record(
                    [
                        _observation(
                            as_of_ms=history_as_of,
                            value=100.0,
                            recorded_at_ms=tied_recorded_at,
                            token="blocked-a",
                        ),
                        _observation(
                            as_of_ms=history_as_of,
                            value=101.0,
                            recorded_at_ms=tied_recorded_at,
                            token="blocked-b",
                        ),
                        current,
                    ]
                )
                result = compute_changes(store, [current])

        horizons = result["open_interest_contracts"]["horizons"]
        self.assertTrue(
            all(row["history_state"] == "AMBIGUOUS_REVISION_BLOCKED" for row in horizons.values())
        )
        self.assertTrue(all("previous_value" not in row for row in horizons.values()))

    def test_runtime_policy_hash_drift_blocks_instead_of_falling_back(self):
        changed_policy = deepcopy(oi_revision_policy.load_policy())
        changed_policy["status"] = "APPROVED_BY_TAMPERING"
        current = _observation(
            as_of_ms=BASE_MS,
            value=110.0,
            recorded_at_ms=BASE_MS + 100,
            token="policy-drift-current",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with ObservationStore(Path(temp_dir) / "observations.sqlite3") as store:
                store.record([current])
                with patch.object(
                    oi_revision_policy,
                    "load_policy",
                    return_value=changed_policy,
                ):
                    result = compute_changes(store, [current])

        horizons = result["open_interest_contracts"]["horizons"]
        self.assertTrue(
            all(row["history_state"] == "REVISION_POLICY_INVALID_BLOCKED" for row in horizons.values())
        )
        self.assertTrue(
            all("policy canonical hash drift" in row["blocked_reason"] for row in horizons.values())
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
