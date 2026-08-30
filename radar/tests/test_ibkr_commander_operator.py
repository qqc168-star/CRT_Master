from __future__ import annotations

import copy
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase, main, mock

from crt_radar.commander_plan_adapter import (
    CommanderPlanBlocked,
    SIMULATION_ONLY,
    seal_commander_plan,
    validate_commander_plan,
)
from crt_radar.ibkr_commander_operator import (
    build_simulation_plan_from_capture,
    run_gate6c3_operator,
)
from crt_radar.ibkr_live_market_data_intake import ASSET_ORDER, IbkrIntakeConfig
from crt_radar.run_ledger import RunLedger


CURRENT_MAIN_SHA = "4fe185887044abf1f378354414cbe417fa7247cb"
NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def simulation_plan() -> dict:
    return seal_commander_plan(
        {
            "plan_id": "CRT-GATE6C3-OPERATOR-SIM-MSTR-001",
            "plan_version": "0.1-simulation",
            "plan_mode": "OBSERVATION_ONLY",
            "generated_at": iso_z(NOW - timedelta(minutes=5)),
            "valid_until": iso_z(NOW + timedelta(hours=1)),
            "asset": "MSTR",
            "source_main_sha": CURRENT_MAIN_SHA,
            "price_classification": SIMULATION_ONLY,
            "lines": [
                {
                    "line_id": "sim-attack",
                    "line_type": "ATTACK",
                    "price": 100.0,
                    "direction": "UP",
                    "price_classification": SIMULATION_ONLY,
                },
                {
                    "line_id": "sim-first-defense",
                    "line_type": "FIRST_DEFENSE",
                    "price": 99.0,
                    "direction": "DOWN",
                    "price_classification": SIMULATION_ONLY,
                },
                {
                    "line_id": "sim-invalidation",
                    "line_type": "INVALIDATION",
                    "price": 98.0,
                    "direction": "DOWN",
                    "price_classification": SIMULATION_ONLY,
                },
                {
                    "line_id": "sim-harvest",
                    "line_type": "HARVEST",
                    "price": 105.0,
                    "direction": "UP",
                    "price_classification": SIMULATION_ONLY,
                },
            ],
            "governance": {
                "action_output": "NONE",
                "machine_execution": "FORBIDDEN",
                "external_action_authority": "NONE",
                "capital_decision_authority": "USER_ONLY",
            },
        }
    )


def live_capture() -> dict:
    return {
        "captured_at_ms": NOW_MS,
        "assets": {
            asset: {
                "market_data_type": 1,
                "l1": {},
                "bars_5s": [],
            }
            for asset in ASSET_ORDER
        },
    }


class FeedFactory:
    def __init__(self, capture: dict, callbacks: list[tuple]) -> None:
        self.capture = capture
        self.callbacks = callbacks
        self.call_count = 0

    def __call__(self, sink):
        parent = self

        class Feed:
            def collect(self, config):
                config.validate()
                parent.call_count += 1
                for callback in parent.callbacks:
                    if callback[0] == "LAST":
                        sink.on_ibkr_last(callback[1], callback[2], callback[3])
                    else:
                        sink.on_ibkr_5s_close(
                            callback[1], callback[2], callback[3]
                        )
                return copy.deepcopy(parent.capture)

        return Feed()


class Gate6C3OperatorTests(TestCase):
    def run_operator(
        self,
        temp_dir: str,
        *,
        factory: FeedFactory,
        plan: dict | None = None,
        current_main_sha: str = CURRENT_MAIN_SHA,
    ) -> dict:
        return run_gate6c3_operator(
            plan if plan is not None else simulation_plan(),
            current_main_sha=current_main_sha,
            config=IbkrIntakeConfig(duration_seconds=5.0),
            ledger_path=Path(temp_dir) / "handoff.jsonl",
            dedupe_state_path=Path(temp_dir) / "dedupe.json",
            report_path=Path(temp_dir) / "report.json",
            now=NOW,
            feed_factory=factory,
        )

    def test_closed_market_is_waiting_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_operator(
                temp_dir,
                factory=FeedFactory(live_capture(), []),
            )
            written = json.loads(
                (Path(temp_dir) / "report.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["state"], "WAITING_FOR_MARKET_ACTIVITY")
        self.assertEqual(written, result)
        self.assertEqual(result["handoffs"], [])
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["machine_execution"], "FORBIDDEN")
        self.assertEqual(
            result["current_main_verification"],
            "CALLER_SUPPLIED_READ_ONLY_PRECHECK_REQUIRED",
        )
        self.assertIs(result["plan_source_main_match"], True)

    def test_live_capture_builds_sealed_non_test_simulation_plan(self) -> None:
        capture = live_capture()
        capture["assets"]["MSTR"]["l1"]["last"] = 137.54
        plan = build_simulation_plan_from_capture(
            capture,
            asset="MSTR",
            current_main_sha=CURRENT_MAIN_SHA,
            valid_for_minutes=60,
        )
        valid, blockers = validate_commander_plan(
            plan,
            current_main_sha=CURRENT_MAIN_SHA,
            now=NOW,
        )

        self.assertTrue(valid, blockers)
        self.assertEqual(plan["price_classification"], SIMULATION_ONLY)
        self.assertNotEqual(plan["price_classification"], "TEST_ONLY")
        self.assertEqual(
            [line["price"] for line in plan["lines"]],
            [137.61, 136.85, 134.79, 140.29],
        )
        self.assertEqual(
            plan["simulation_basis"]["commander_judgment"],
            "SIMULATED_NOT_FORMAL",
        )

    def test_simulation_plan_requires_live_last(self) -> None:
        with self.assertRaisesRegex(ValueError, "LAST unavailable"):
            build_simulation_plan_from_capture(
                live_capture(),
                asset="MSTR",
                current_main_sha=CURRENT_MAIN_SHA,
            )

    def test_explicit_closed_market_close_builds_waiting_only_plan(self) -> None:
        capture = live_capture()
        capture["assets"]["MSTR"]["l1"]["close"] = 137.399994
        plan = build_simulation_plan_from_capture(
            capture,
            asset="MSTR",
            current_main_sha=CURRENT_MAIN_SHA,
            allow_closed_market_close=True,
        )

        self.assertEqual(
            plan["simulation_basis"]["source"],
            "IBKR_L1_CLOSE_CLOSED_MARKET",
        )
        self.assertEqual(plan["price_classification"], SIMULATION_ONLY)
        self.assertEqual(
            [line["price"] for line in plan["lines"]],
            [137.47, 136.71, 134.65, 140.15],
        )

    def test_close_fallback_is_forbidden_when_5s_activity_exists(self) -> None:
        capture = live_capture()
        capture["assets"]["MSTR"]["l1"]["close"] = 137.399994
        capture["assets"]["MSTR"]["bars_5s"].append({"close": 137.4})
        with self.assertRaisesRegex(ValueError, "fallback forbidden"):
            build_simulation_plan_from_capture(
                capture,
                asset="MSTR",
                current_main_sha=CURRENT_MAIN_SHA,
                allow_closed_market_close=True,
            )

    def test_5s_activity_without_line_event_is_monitoring(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_operator(
                temp_dir,
                factory=FeedFactory(
                    live_capture(),
                    [("BAR", "MSTR", 110.0, NOW_MS)],
                ),
            )

        self.assertEqual(result["state"], "MONITORING_NO_EVENT")
        self.assertEqual(result["gate_summary"]["bar_close_observation_count"], 1)
        self.assertEqual(result["raw_events"], [])

    def test_new_event_reaches_existing_handoff_and_is_persisted(self) -> None:
        capture = live_capture()
        capture["assets"]["MSTR"]["l1"]["last"] = 99.85
        factory = FeedFactory(
            capture,
            [("LAST", "MSTR", 99.85, NOW_MS)],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_operator(temp_dir, factory=factory)
            ledger = RunLedger(Path(temp_dir) / "handoff.jsonl")
            validation = ledger.validate()
            ledger_record_count = len(ledger.records())

        self.assertEqual(result["state"], "OBSERVATION_EVENTS_HANDOFF_READY")
        self.assertEqual(len(result["new_events"]), 1)
        self.assertEqual(result["new_events"][0]["event_type"], "APPROACH")
        self.assertEqual(
            result["new_events"][0]["price_classification"],
            "SEALED_SIMULATION_X_IBKR_LIVE",
        )
        self.assertEqual(result["handoffs"][0]["handoff"]["state"], "GPT_HANDOFF_READY")
        self.assertTrue(validation.valid)
        self.assertEqual(ledger_record_count, 1)

    def test_exact_restart_event_is_deduplicated_without_second_handoff(self) -> None:
        capture = live_capture()
        capture["assets"]["MSTR"]["l1"]["last"] = 99.85
        callbacks = [("LAST", "MSTR", 99.85, NOW_MS)]
        with tempfile.TemporaryDirectory() as temp_dir:
            first = self.run_operator(
                temp_dir,
                factory=FeedFactory(capture, callbacks),
            )
            second = self.run_operator(
                temp_dir,
                factory=FeedFactory(capture, callbacks),
            )
            ledger = RunLedger(Path(temp_dir) / "handoff.jsonl")
            ledger_record_count = len(ledger.records())

        self.assertEqual(first["state"], "OBSERVATION_EVENTS_HANDOFF_READY")
        self.assertEqual(second["state"], "DUPLICATE_EVENTS_SKIPPED")
        self.assertEqual(second["new_events"], [])
        self.assertEqual(len(second["duplicate_events"]), 1)
        self.assertEqual(second["handoffs"], [])
        self.assertEqual(ledger_record_count, 1)
        self.assertEqual(second["restart_continuity"], "EVENT_DEDUPE_ONLY")

    def test_invalid_plan_blocks_before_feed_connects(self) -> None:
        expired = simulation_plan()
        expired["valid_until"] = iso_z(NOW)
        expired = seal_commander_plan(expired)
        factory = FeedFactory(live_capture(), [])
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(CommanderPlanBlocked) as raised:
                self.run_operator(temp_dir, factory=factory, plan=expired)

        self.assertIn("PLAN_EXPIRED", raised.exception.blockers)
        self.assertEqual(factory.call_count, 0)

    def test_non_live_market_data_fails_closed_without_handoff(self) -> None:
        capture = live_capture()
        capture["assets"]["STRC"]["market_data_type"] = 2
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "handoff.jsonl"
            with self.assertRaisesRegex(ValueError, "not live:STRC"):
                self.run_operator(
                    temp_dir,
                    factory=FeedFactory(capture, []),
                )
            self.assertFalse(ledger_path.exists())

    def test_current_main_mismatch_blocks_before_feed_connects(self) -> None:
        factory = FeedFactory(live_capture(), [])
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(CommanderPlanBlocked) as raised:
                self.run_operator(
                    temp_dir,
                    factory=factory,
                    current_main_sha="f" * 40,
                )

        self.assertIn("SOURCE_MAIN_SHA_MISMATCH", raised.exception.blockers)
        self.assertEqual(factory.call_count, 0)

    def test_governance_mismatch_blocks_before_feed_connects(self) -> None:
        invalid = simulation_plan()
        invalid["governance"]["machine_execution"] = "ALLOWED"
        invalid = seal_commander_plan(invalid)
        factory = FeedFactory(live_capture(), [])
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(CommanderPlanBlocked) as raised:
                self.run_operator(
                    temp_dir,
                    factory=factory,
                    plan=invalid,
                )

        self.assertIn(
            "GOVERNANCE_LOCK_FAIL:machine_execution",
            raised.exception.blockers,
        )
        self.assertEqual(factory.call_count, 0)

    def test_tampered_dedupe_state_fails_closed(self) -> None:
        capture = live_capture()
        callbacks = [("LAST", "MSTR", 99.85, NOW_MS)]
        with tempfile.TemporaryDirectory() as temp_dir:
            self.run_operator(
                temp_dir,
                factory=FeedFactory(capture, callbacks),
            )
            state_path = Path(temp_dir) / "dedupe.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["lines"]["MSTR:sim-attack"]["event_type"] = "TAMPERED"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "state hash mismatch"):
                self.run_operator(
                    temp_dir,
                    factory=FeedFactory(capture, callbacks),
                )

    def test_handoff_failure_does_not_commit_dedupe_state(self) -> None:
        capture = live_capture()
        callbacks = [("LAST", "MSTR", 99.85, NOW_MS)]
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "dedupe.json"
            with mock.patch(
                "crt_radar.ibkr_commander_operator.run_gpt_handoff_gate",
                side_effect=RuntimeError("injected handoff failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected handoff failure"):
                    self.run_operator(
                        temp_dir,
                        factory=FeedFactory(capture, callbacks),
                    )
            self.assertFalse(state_path.exists())

            recovered = self.run_operator(
                temp_dir,
                factory=FeedFactory(capture, callbacks),
            )

        self.assertEqual(
            recovered["state"],
            "OBSERVATION_EVENTS_HANDOFF_READY",
        )

    def test_each_successful_handoff_commits_its_own_dedupe_checkpoint(self) -> None:
        capture = live_capture()
        callbacks = [
            ("LAST", "MSTR", 99.85, NOW_MS),
            ("LAST", "MSTR", 100.02, NOW_MS + 1_000),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch(
                "crt_radar.ibkr_commander_operator._handoff_for_event",
                side_effect=[{"state": "FIRST_HANDOFF_OK"}, RuntimeError("second failed")],
            ):
                with self.assertRaisesRegex(RuntimeError, "second failed"):
                    self.run_operator(
                        temp_dir,
                        factory=FeedFactory(capture, callbacks),
                    )

            recovered = self.run_operator(
                temp_dir,
                factory=FeedFactory(capture, callbacks),
            )

        self.assertEqual(len(recovered["duplicate_events"]), 1)
        self.assertEqual(
            recovered["duplicate_events"][0]["event_type"],
            "APPROACH",
        )
        self.assertEqual(len(recovered["new_events"]), 1)
        self.assertEqual(recovered["new_events"][0]["event_type"], "CROSS_RAW")


if __name__ == "__main__":
    main(verbosity=2)
