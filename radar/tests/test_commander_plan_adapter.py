from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from unittest import TestCase, main, mock

from crt_radar.commander_plan_adapter import (
    CommanderPlanAdapter,
    CommanderPlanBlocked,
    TEST_ONLY,
    seal_commander_plan,
)


CURRENT_MAIN_SHA = "4fe185887044abf1f378354414cbe417fa7247cb"
NOW = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)


def iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def valid_test_plan() -> dict:
    return seal_commander_plan(
        {
            "plan_id": "CRT-GATE6C2-TEST-MSTR-001",
            "plan_version": "0.1-test",
            "plan_mode": "OBSERVATION_ONLY",
            "generated_at": iso_z(NOW - timedelta(minutes=5)),
            "valid_until": iso_z(NOW + timedelta(hours=1)),
            "asset": "MSTR",
            "source_main_sha": CURRENT_MAIN_SHA,
            "price_classification": TEST_ONLY,
            "lines": [
                {
                    "line_id": "test-attack",
                    "line_type": "ATTACK",
                    "price": 100.0,
                    "direction": "UP",
                    "price_classification": TEST_ONLY,
                },
                {
                    "line_id": "test-first-defense",
                    "line_type": "FIRST_DEFENSE",
                    "price": 99.0,
                    "direction": "DOWN",
                    "price_classification": TEST_ONLY,
                },
                {
                    "line_id": "test-invalidation",
                    "line_type": "INVALIDATION",
                    "price": 98.0,
                    "direction": "DOWN",
                    "price_classification": TEST_ONLY,
                },
                {
                    "line_id": "test-harvest",
                    "line_type": "HARVEST",
                    "price": 105.0,
                    "direction": "UP",
                    "price_classification": TEST_ONLY,
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


class CommanderPlanAdapterTests(TestCase):
    def arm(
        self,
        plan: dict | None = None,
        *,
        gate6a_state: object | None = None,
    ) -> CommanderPlanAdapter:
        return CommanderPlanAdapter.arm_offline(
            plan if plan is not None else valid_test_plan(),
            current_main_sha=CURRENT_MAIN_SHA,
            now=NOW,
            gate6a_state=gate6a_state,
        )

    def feed_last(self, adapter: CommanderPlanAdapter, price: float, seconds: int) -> None:
        adapter.on_test_last(
            price,
            NOW + timedelta(seconds=seconds),
            price_classification=TEST_ONLY,
        )

    def feed_close(self, adapter: CommanderPlanAdapter, price: float, seconds: int) -> None:
        adapter.on_test_5s_close(
            price,
            NOW + timedelta(seconds=seconds),
            price_classification=TEST_ONLY,
        )

    def test_verified_plan_arms_exactly_its_four_lines(self) -> None:
        adapter = self.arm()
        self.assertEqual(adapter.armed_line_count, 4)
        self.assertEqual(
            adapter.armed_line_ids,
            (
                "test-attack",
                "test-first-defense",
                "test-invalidation",
                "test-harvest",
            ),
        )
        self.assertEqual(adapter.events, ())

    def test_existing_gate6a_state_continues_acceptance_after_restart(self) -> None:
        first = self.arm()
        self.feed_last(first, 99.60, 0)
        self.feed_last(first, 99.85, 1)
        self.feed_last(first, 100.01, 2)
        self.feed_close(first, 100.02, 7)
        self.feed_close(first, 100.03, 12)

        restored = self.arm(gate6a_state=first.gate6a_state())
        self.assertEqual(restored.events, ())
        self.feed_close(restored, 100.04, 17)
        self.feed_close(restored, 99.99, 22)

        attack_events = [
            event for event in restored.events if event["line_id"] == "test-attack"
        ]
        self.assertEqual(
            [event["event_type"] for event in attack_events],
            ["ACCEPTED"],
        )

    def test_gate6a_state_tamper_fails_closed(self) -> None:
        adapter = self.arm()
        self.feed_last(adapter, 99.85, 0)
        self.feed_last(adapter, 100.01, 1)
        checkpoint = adapter.gate6a_state()
        checkpoint["lines"]["test-attack"]["state"] = "FAR"

        with self.assertRaisesRegex(ValueError, "transition flags mismatch"):
            self.arm(gate6a_state=checkpoint)

    def test_existing_gate6a_sequence_preserves_plan_identity_and_governance(self) -> None:
        adapter = self.arm()
        self.feed_last(adapter, 99.60, 0)
        self.feed_last(adapter, 99.85, 1)
        self.feed_last(adapter, 100.02, 2)
        for index, close in enumerate((100.03, 100.04, 99.99, 100.05), start=1):
            self.feed_close(adapter, close, 2 + index * 5)
        self.feed_last(adapter, 100.30, 30)
        self.feed_last(adapter, 100.10, 31)

        attack_events = [
            event for event in adapter.events if event["line_id"] == "test-attack"
        ]
        self.assertEqual(
            [event["event_type"] for event in attack_events],
            ["APPROACH", "CROSS_RAW", "ACCEPTED", "RETEST"],
        )
        required = {
            "plan_id",
            "plan_sha",
            "asset",
            "line_id",
            "line_type",
            "level_price",
            "observed_price",
            "event_type",
            "timestamp",
            "action_output",
            "machine_execution",
            "capital_decision_authority",
        }
        for event in attack_events:
            self.assertTrue(required.issubset(event))
            self.assertEqual(event["plan_id"], "CRT-GATE6C2-TEST-MSTR-001")
            self.assertEqual(event["asset"], "MSTR")
            self.assertEqual(event["line_type"], "ATTACK")
            self.assertEqual(event["level_price"], 100.0)
            self.assertEqual(event["price_classification"], TEST_ONLY)
            self.assertEqual(event["level_price_classification"], TEST_ONLY)
            self.assertEqual(event["observed_price_classification"], TEST_ONLY)
            self.assertEqual(event["engineering_parameters"], TEST_ONLY)
            self.assertIs(event["price_reaching_is_not_action_trigger"], True)
            self.assertEqual(event["action_output"], "NONE")
            self.assertEqual(event["machine_execution"], "FORBIDDEN")
            self.assertEqual(event["external_action_authority"], "NONE")
            self.assertEqual(event["capital_decision_authority"], "USER_ONLY")
            self.assertEqual(event["production"], "NOT_APPROVED")

    def test_rejected_cycle_rearms_and_unresolved_cross_does_not_repeat(self) -> None:
        adapter = self.arm()
        self.feed_last(adapter, 99.60, 0)
        self.feed_last(adapter, 99.85, 1)
        self.feed_last(adapter, 100.01, 2)
        self.feed_last(adapter, 99.99, 3)
        self.feed_last(adapter, 100.02, 4)

        attack_events = [
            event for event in adapter.events if event["line_id"] == "test-attack"
        ]
        self.assertEqual(
            sum(event["event_type"] == "CROSS_RAW" for event in attack_events), 1
        )

        for index, close in enumerate((100.01, 99.98, 99.97, 99.96), start=1):
            self.feed_close(adapter, close, 4 + index * 5)
        self.feed_last(adapter, 99.70, 30)

        attack_events = [
            event for event in adapter.events if event["line_id"] == "test-attack"
        ]
        self.assertEqual(
            [event["event_type"] for event in attack_events],
            ["APPROACH", "CROSS_RAW", "REJECTED", "REARMED"],
        )

    def test_invalid_plans_fail_before_any_line_is_armed(self) -> None:
        cases: list[tuple[str, dict, str]] = []

        tampered = valid_test_plan()
        tampered["lines"][0]["price"] = 999.0
        cases.append(("tampered", tampered, "PLAN_SHA_MISMATCH"))

        expired = valid_test_plan()
        expired["valid_until"] = iso_z(NOW)
        cases.append(("expired", seal_commander_plan(expired), "PLAN_EXPIRED"))

        wrong_main = valid_test_plan()
        wrong_main["source_main_sha"] = "0" * 40
        cases.append(
            ("wrong_main", seal_commander_plan(wrong_main), "SOURCE_MAIN_SHA_MISMATCH")
        )

        bad_governance = valid_test_plan()
        bad_governance["governance"]["machine_execution"] = "ALLOWED"
        cases.append(
            (
                "governance",
                seal_commander_plan(bad_governance),
                "GOVERNANCE_LOCK_FAIL:machine_execution",
            )
        )

        illegal_line = valid_test_plan()
        illegal_line["lines"][0]["line_type"] = "BUY_NOW"
        cases.append(
            ("illegal_line", seal_commander_plan(illegal_line), "ILLEGAL_LINE_TYPE:BUY_NOW")
        )

        nonpositive_price = valid_test_plan()
        nonpositive_price["lines"][0]["price"] = 0
        cases.append(
            (
                "nonpositive_price",
                seal_commander_plan(nonpositive_price),
                "INVALID_PRICE:test-attack",
            )
        )

        missing_field = valid_test_plan()
        missing_field.pop("valid_until")
        cases.append(
            (
                "missing_field",
                missing_field,
                "MISSING_TOP_FIELDS:valid_until",
            )
        )

        extra_governance = valid_test_plan()
        extra_governance["governance"]["machine_may_execute_trade"] = True
        cases.append(
            (
                "extra_governance",
                seal_commander_plan(extra_governance),
                "GOVERNANCE_UNKNOWN_FIELDS:machine_may_execute_trade",
            )
        )

        for name, plan, expected_blocker in cases:
            with self.subTest(name=name):
                with mock.patch(
                    "crt_radar.commander_plan_adapter.LevelEventEngine"
                ) as engine:
                    with self.assertRaises(CommanderPlanBlocked) as raised:
                        self.arm(plan)
                    self.assertIn(expected_blocker, raised.exception.blockers)
                    engine.assert_not_called()

    def test_offline_adapter_rejects_unclassified_or_non_test_prices(self) -> None:
        adapter = self.arm()
        for classification in ("IBKR_LIVE", "", None):
            with self.subTest(classification=classification):
                with self.assertRaisesRegex(
                    ValueError, "GATE_6C2_OFFLINE_REQUIRES_TEST_ONLY"
                ):
                    adapter.on_test_last(
                        100.0,
                        NOW,
                        price_classification=classification,
                    )
        self.assertEqual(adapter.events, ())

    def test_offline_adapter_rejects_plan_prices_not_explicitly_test_only(self) -> None:
        plan = valid_test_plan()
        plan.pop("price_classification")
        plan["lines"][0].pop("price_classification")
        plan = seal_commander_plan(plan)
        with mock.patch("crt_radar.commander_plan_adapter.LevelEventEngine") as engine:
            with self.assertRaises(CommanderPlanBlocked) as raised:
                self.arm(plan)
            self.assertEqual(
                raised.exception.blockers,
                (
                    "OFFLINE_PLAN_NOT_TEST_ONLY",
                    "OFFLINE_LINE_NOT_TEST_ONLY:test-attack",
                ),
            )
            engine.assert_not_called()

    def test_current_main_is_checked_at_arm_time(self) -> None:
        with self.assertRaises(CommanderPlanBlocked) as raised:
            CommanderPlanAdapter.arm_offline(
                valid_test_plan(),
                current_main_sha="f" * 40,
                now=NOW,
            )
        self.assertIn("SOURCE_MAIN_SHA_MISMATCH", raised.exception.blockers)

    def test_constructor_cannot_bypass_plan_verification(self) -> None:
        plan = valid_test_plan()
        plan["governance"]["action_output"] = "ORDER"
        plan = seal_commander_plan(plan)
        with mock.patch("crt_radar.commander_plan_adapter.LevelEventEngine") as engine:
            with self.assertRaises(CommanderPlanBlocked) as raised:
                CommanderPlanAdapter(
                    plan,
                    current_main_sha=CURRENT_MAIN_SHA,
                    now=NOW,
                )
            self.assertIn(
                "GOVERNANCE_LOCK_FAIL:action_output", raised.exception.blockers
            )
            engine.assert_not_called()


if __name__ == "__main__":
    main(verbosity=2)
