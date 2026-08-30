from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
from unittest import TestCase, main

from crt_radar.commander_plan_adapter import (
    CommanderPlanAdapter,
    CommanderPlanBlocked,
    IBKR_LIVE,
    SIMULATION_ONLY,
    TEST_ONLY,
    seal_commander_plan,
)
from crt_radar.ibkr_commander_observation import IbkrCommanderObservationBridge
from crt_radar.ibkr_live_market_data_intake import (
    NativeIbkrFeed,
    _observation_channel_for_tick_type,
)
from crt_radar.gpt_handoff import run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.reanalysis_wake import fuse_reanalysis_wake


CURRENT_MAIN_SHA = "4fe185887044abf1f378354414cbe417fa7247cb"
NOW = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def verified_test_plan() -> dict:
    return seal_commander_plan(
        {
            "plan_id": "CRT-GATE6C3-TEST-MSTR-001",
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


class IbkrCommanderObservationTests(TestCase):
    def arm(self, plan: dict | None = None) -> IbkrCommanderObservationBridge:
        return IbkrCommanderObservationBridge.arm(
            plan if plan is not None else verified_test_plan(),
            current_main_sha=CURRENT_MAIN_SHA,
            now=NOW,
        )

    def test_verified_plan_receives_ibkr_last_and_5s_close_events(self) -> None:
        bridge = self.arm()
        bridge.on_ibkr_last("ASST", 20.0, NOW_MS)
        bridge.on_ibkr_last("MSTR", 99.60, NOW_MS)
        bridge.on_ibkr_last("MSTR", 99.85, NOW_MS + 1_000)
        bridge.on_ibkr_last("MSTR", 100.02, NOW_MS + 2_000)
        for index, close in enumerate((100.03, 100.04, 99.99, 100.05), start=1):
            bridge.on_ibkr_5s_close(
                "MSTR",
                close,
                NOW_MS + 2_000 + index * 5_000,
            )
        bridge.on_ibkr_last("MSTR", 100.30, NOW_MS + 30_000)
        bridge.on_ibkr_last("MSTR", 100.10, NOW_MS + 31_000)

        attack_events = [
            event for event in bridge.events if event["line_id"] == "test-attack"
        ]
        self.assertEqual(
            [event["event_type"] for event in attack_events],
            ["APPROACH", "CROSS_RAW", "ACCEPTED", "RETEST"],
        )
        for event in attack_events:
            self.assertEqual(event["plan_id"], "CRT-GATE6C3-TEST-MSTR-001")
            self.assertEqual(event["asset"], "MSTR")
            self.assertEqual(event["price_classification"], TEST_ONLY)
            self.assertEqual(event["level_price_classification"], TEST_ONLY)
            self.assertEqual(event["observed_price_classification"], IBKR_LIVE)
            self.assertIn(
                event["observation_channel"], {"IBKR_LAST", "IBKR_5S_CLOSE"}
            )
            self.assertEqual(event["event_purpose"], "WAKE_GPT_REANALYSIS_ONLY")
            self.assertIs(event["price_reaching_is_not_action_trigger"], True)
            self.assertEqual(event["action_output"], "NONE")
            self.assertEqual(event["machine_execution"], "FORBIDDEN")
            self.assertEqual(event["external_action_authority"], "NONE")
            self.assertEqual(event["capital_decision_authority"], "USER_ONLY")

        summary = bridge.gate_summary()
        self.assertEqual(summary["state"], "ARMED_OBSERVATION_ONLY")
        self.assertEqual(summary["last_observation_count"], 5)
        self.assertEqual(summary["bar_close_observation_count"], 4)
        self.assertEqual(summary["ignored_asset_observation_count"], 1)
        self.assertEqual(summary["observation_event_count"], len(bridge.events))
        self.assertIs(summary["reanalysis_wake_ready"], True)
        self.assertEqual(summary["event_purpose"], "WAKE_GPT_REANALYSIS_ONLY")
        self.assertEqual(summary["action_output"], "NONE")
        self.assertEqual(summary["machine_execution"], "FORBIDDEN")

        wake = bridge.latest_reanalysis_wake()
        self.assertIsNotNone(wake)
        assert wake is not None
        self.assertEqual(wake["state"], "REANALYSIS_REQUESTED")
        self.assertEqual(wake["input_family"], "COMMANDER_PLAN_OBSERVATION")
        self.assertEqual(wake["wake_sources"], ["COMMANDER_PLAN_OBSERVATION"])
        self.assertEqual(len(wake["commander_event_id"]), 64)
        self.assertTrue(wake["reason"].endswith(wake["commander_event_id"]))
        self.assertEqual(wake["action_output"], "NONE")
        self.assertEqual(wake["machine_execution"], "FORBIDDEN")

        fused = fuse_reanalysis_wake(
            wake,
            plan_drift={
                "state": "STABLE",
                "reason": "ACTIVE_PLAN_CONDITIONS_SATISFIED",
                "reanalysis_required": False,
                "action_output": "NONE",
                "external_action_authority": "NONE",
                "external_action_performed": False,
            },
        )
        self.assertIsNotNone(fused)
        assert fused is not None
        self.assertEqual(fused["wake_sources"], ["COMMANDER_PLAN_OBSERVATION"])
        self.assertTrue(fused["analyst_reanalysis_requested"])

    def test_bid_and_ask_tick_types_never_route_to_the_observation_engine(self) -> None:
        self.assertIsNone(_observation_channel_for_tick_type(1))
        self.assertIsNone(_observation_channel_for_tick_type(2))
        self.assertEqual(_observation_channel_for_tick_type(4), "LAST")

    def test_invalid_plan_blocks_before_live_bridge_arms(self) -> None:
        expired = verified_test_plan()
        expired["valid_until"] = iso_z(NOW)
        expired = seal_commander_plan(expired)
        with self.assertRaises(CommanderPlanBlocked) as raised:
            self.arm(expired)
        self.assertIn("PLAN_EXPIRED", raised.exception.blockers)

    def test_zero_events_produce_no_wake(self) -> None:
        bridge = self.arm()
        self.assertEqual(bridge.events, ())
        self.assertIsNone(bridge.latest_reanalysis_wake())
        self.assertIs(bridge.gate_summary()["reanalysis_wake_ready"], False)

    def test_sealed_simulation_remains_distinct_from_test_and_formal_plan(self) -> None:
        plan = verified_test_plan()
        plan["plan_id"] = "CRT-GATE6C3-SIM-MSTR-001"
        plan["plan_version"] = "0.1-simulation"
        plan["price_classification"] = SIMULATION_ONLY
        for line in plan["lines"]:
            line["price_classification"] = SIMULATION_ONLY
        plan = seal_commander_plan(plan)

        bridge = self.arm(plan)
        bridge.on_ibkr_last("MSTR", 99.85, NOW_MS)

        self.assertEqual(len(bridge.events), 1)
        event = bridge.events[0]
        self.assertEqual(event["event_type"], "APPROACH")
        self.assertEqual(event["level_price_classification"], SIMULATION_ONLY)
        self.assertEqual(
            event["price_classification"],
            "SEALED_SIMULATION_X_IBKR_LIVE",
        )
        self.assertNotEqual(event["price_classification"], TEST_ONLY)
        self.assertNotEqual(
            event["price_classification"],
            "VERIFIED_PLAN_X_IBKR_LIVE",
        )

        wake = bridge.latest_reanalysis_wake()
        self.assertIsNotNone(wake)
        assert wake is not None
        plan_drift = {
            "state": "STABLE",
            "reason": "SIMULATION_ONLY",
            "reanalysis_required": False,
            "plans": [],
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
        fused = fuse_reanalysis_wake(wake, plan_drift=plan_drift)
        assert fused is not None
        notice = build_plain_language_notice(
            {
                "evidence_pack_hash": "b" * 64,
                "authority": {
                    "action_output": "NONE",
                    "external_action_authority": "NONE",
                    "external_action_performed": False,
                },
                "reanalysis_wake": fused,
                "plan_drift": plan_drift,
                "data_health": {"critical_blockers": []},
            }
        )
        self.assertIn("sealed simulated Commander Plan", notice["why_it_matters"])
        self.assertIn(
            "sealed simulated Commander Plan",
            notice["instruction_for_gpt"],
        )
        self.assertNotIn("verified Commander Plan", notice["instruction_for_gpt"])

    def test_commander_event_uses_existing_gpt_reanalysis_handoff(self) -> None:
        bridge = self.arm()
        bridge.on_ibkr_last("MSTR", 99.85, NOW_MS)
        bridge.on_ibkr_last("MSTR", 100.02, NOW_MS + 1_000)

        wake = bridge.latest_reanalysis_wake()
        self.assertIsNotNone(wake)
        assert wake is not None
        plan_drift = {
            "state": "STABLE",
            "reason": "ACTIVE_PLAN_CONDITIONS_SATISFIED",
            "reanalysis_required": False,
            "plans": [],
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
        fused = fuse_reanalysis_wake(wake, plan_drift=plan_drift)
        self.assertIsNotNone(fused)
        assert fused is not None
        pack = {
            "evidence_pack_hash": "a" * 64,
            "authority": {
                "action_output": "NONE",
                "external_action_authority": "NONE",
                "external_action_performed": False,
            },
            "reanalysis_wake": fused,
            "plan_drift": plan_drift,
            "data_health": {"critical_blockers": []},
        }

        notice = build_plain_language_notice(pack)
        self.assertEqual(notice["state"], "GPT_REANALYSIS_REQUESTED")
        self.assertIn("Commander", notice["title"])
        self.assertIn("MSTR ATTACK", notice["what_happened"])
        self.assertIn("CROSS_RAW", notice["what_happened"])
        self.assertIn("not an action trigger", notice["what_happened"])
        self.assertEqual(notice["action_output"], "NONE")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_gpt_handoff_gate(
                pack,
                notice,
                ledger_path=Path(temp_dir) / "gpt_handoff.jsonl",
            )

        self.assertEqual(result["state"], "GPT_HANDOFF_READY")
        self.assertEqual(
            result["wake"]["wake_sources"],
            ["COMMANDER_PLAN_OBSERVATION"],
        )
        self.assertIn("ADVISE_USER_ONLY", result["required_behavior"])
        self.assertIn("NO_EXTERNAL_ACTION", result["required_behavior"])
        self.assertEqual(result["action_output"], "NONE")

    def test_bridge_rejects_offline_adapter_mode(self) -> None:
        adapter = CommanderPlanAdapter.arm_offline(
            verified_test_plan(),
            current_main_sha=CURRENT_MAIN_SHA,
            now=NOW,
        )
        with self.assertRaisesRegex(ValueError, "IBKR_LIVE adapter"):
            IbkrCommanderObservationBridge(adapter)

    def test_native_feed_accepts_only_an_observation_sink_reference(self) -> None:
        bridge = self.arm()
        feed = NativeIbkrFeed(observation_sink=bridge)
        self.assertIs(feed.observation_sink, bridge)


if __name__ == "__main__":
    main(verbosity=2)
