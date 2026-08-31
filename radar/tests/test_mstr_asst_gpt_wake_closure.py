from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crt_radar.daily_evidence_runner import run_daily_evidence
from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.gpt_handoff import (
    build_minimized_bridge_payload,
    run_gpt_handoff_gate,
)
from crt_radar.mstr_asst_market_health import evaluate_mstr_asst_market_health
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.reanalysis_wake import fuse_reanalysis_wake
from tests import test_daily_evidence_runner as daily_fixture
from tests.test_gpt_handoff import bridge_pack, pack as handoff_pack
from tests.test_wake_fusion import minimal_source_gate, private_context


AUTHORITY = {
    "action_output": "NONE",
    "external_action_authority": "NONE",
    "external_action_performed": False,
}


def market_health(asset: str = "MSTR", reason: str = "FIRST_DEFENSE_BREACHED") -> dict:
    market_assets = {}
    option_assets = {}
    commander = {}
    issuer = {}
    for symbol in ("MSTR", "ASST"):
        active = symbol == asset
        close = 99.0 if active and reason == "FIRST_DEFENSE_BREACHED" else 105.0
        if active and reason == "TACTICAL_INVALIDATION_BREACHED":
            close = 89.0
        market_assets[symbol] = {
            "state": "VALID",
            "latest_complete_session": {
                "session_date": "2026-08-28",
                "close": close,
                "high": 106.0,
            },
            "previous_complete_session": {
                "session_date": "2026-08-27",
                "close": 104.0,
                "high": 105.0,
            },
            "rvol20": 0.9,
            "relative_btc": {
                "state": "VALID",
                "btc_excess_return_1d_pct": -3.0,
            },
        }
        option_assets[symbol] = {
            "aggregate_volume": {"put_call_volume_ratio": 1.1},
            "covered_open_interest": {"put_call_open_interest_ratio": 0.9},
            "top_call_oi_strikes": [],
            "top_put_oi_strikes": [],
        }
        commander[symbol] = {
            "source": "THREE_ARMY_COMMANDER",
            "approval_state": "APPROVED",
            "attack_line": 110.0,
            "first_defense": 100.0,
            "invalidation_line": 90.0,
        }
        current = 0.001
        previous = 0.001
        if active and reason == "BTC_PER_DILUTED_SHARE_DECREASED":
            current = 0.0009
        issuer[symbol] = {
            "current_btc_per_diluted_share": current,
            "previous_btc_per_diluted_share": previous,
        }

    return evaluate_mstr_asst_market_health(
        full_day_market_intake={"assets": market_assets, **AUTHORITY},
        options_daily_snapshot={"assets": option_assets, **AUTHORITY},
        commander_lines=commander,
        issuer_btc_per_diluted_share=issuer,
        generated_at_ms=1_787_950_900_001,
    )


def stable_plan() -> dict:
    return {
        "state": "STABLE",
        "reason": "ACTIVE_PLAN_CONDITIONS_SATISFIED",
        "reanalysis_required": False,
        "plans": [],
        **AUTHORITY,
    }


def active_pack(health: dict, evidence_hash: str) -> dict:
    fused = fuse_reanalysis_wake(
        None,
        plan_drift=stable_plan(),
        mstr_asst_market_health=health,
    )
    assert fused is not None
    result = bridge_pack(
        handoff_pack(
            evidence_hash=evidence_hash,
            requested=True,
            wake_sources=["MSTR_ASST_MARKET_HEALTH"],
        )
    )
    result["reanalysis_wake"] = fused
    result["mstr_asst_market_health"] = health
    result["evidence_pack_hash"] = evidence_hash
    return result


class MstrAsstGptWakeClosureTests(unittest.TestCase):

    def test_market_health_promotes_wake_with_asset_reason(self):
        result = fuse_reanalysis_wake(
            None,
            plan_drift=stable_plan(),
            mstr_asst_market_health=market_health(),
        )
        assert result is not None
        self.assertEqual(result["state"], "REANALYSIS_REQUESTED")
        self.assertEqual(result["wake_sources"], ["MSTR_ASST_MARKET_HEALTH"])
        self.assertEqual(result["wake_reasons"], ["MSTR:FIRST_DEFENSE_BREACHED"])

    def test_market_health_is_in_evidence_pack_before_hash(self):
        health = market_health()
        with tempfile.TemporaryDirectory() as td:
            result = build_evidence_pack(
                minimal_source_gate(),
                observation_db=Path(td) / "observations.sqlite3",
                generated_at_ms=1_787_950_900_001,
                private_context=private_context("NOT_YET_VALIDATED"),
                mstr_asst_market_health=health,
            )
        self.assertEqual(
            result["mstr_asst_market_health"]["market_health_hash"],
            health["market_health_hash"],
        )
        self.assertEqual(
            result["reanalysis_wake"]["wake_sources"],
            ["MSTR_ASST_MARKET_HEALTH"],
        )
        self.assertEqual(len(result["evidence_pack_hash"]), 64)

    def test_daily_runtime_entrypoint_fuses_market_health(self):
        harness = daily_fixture.DailyEvidenceRunnerTests(methodName="runTest")
        harness.setUp()
        health = market_health()
        with tempfile.TemporaryDirectory() as td:
            result = run_daily_evidence(
                harness.registry,
                observation_db=Path(td) / "observations.sqlite3",
                fetch_overrides=harness.overrides,
                liquidation_aggregate_payload=harness.aggregate(),
                now_ms=daily_fixture.NOW_MS,
                generated_at_ms=daily_fixture.NOW_MS,
                mstr_asst_market_health=health,
            )
        self.assertEqual(
            result["reanalysis_wake"]["wake_sources"],
            ["MSTR_ASST_MARKET_HEALTH"],
        )
        self.assertEqual(
            result["mstr_asst_market_health"]["market_health_hash"],
            health["market_health_hash"],
        )

    def test_notice_names_equity_event_not_btc_event(self):
        result = active_pack(market_health(), "a" * 64)
        notice = build_plain_language_notice(result)
        self.assertIn("MSTR／ASST", notice["title"])
        self.assertIn("MSTR:FIRST_DEFENSE_BREACHED", notice["what_happened"])
        self.assertNotIn("BTC 市場", notice["title"])

    def test_notice_keeps_wake_separate_from_user_notification(self):
        notice = build_plain_language_notice(active_pack(market_health(), "a" * 64))
        self.assertEqual(notice["state"], "GPT_REANALYSIS_REQUESTED")
        self.assertEqual(notice["notification_state"], "GPT_JUDGMENT_PENDING")
        self.assertFalse(notice["notification_performed"])
        self.assertEqual(notice["notification_authority"], "NONE")

    def test_handoff_requires_latest_health_and_commander_lines(self):
        with tempfile.TemporaryDirectory() as td:
            result = active_pack(market_health(), "a" * 64)
            handoff = run_gpt_handoff_gate(
                result,
                build_plain_language_notice(result),
                ledger_path=Path(td) / "handoff.jsonl",
            )
        self.assertEqual(handoff["state"], "GPT_HANDOFF_READY")
        self.assertIn("LATEST_MSTR_ASST_MARKET_HEALTH", handoff["required_inputs"])
        self.assertIn("LATEST_THREE_ARMY_COMMANDER_LINES", handoff["required_inputs"])
        self.assertIn("APPLY_THREE_ARMY_COMMANDER_DOCTRINE", handoff["required_behavior"])

    def test_minimized_bridge_carries_health_without_private_context(self):
        with tempfile.TemporaryDirectory() as td:
            result = active_pack(market_health(), "a" * 64)
            handoff = run_gpt_handoff_gate(
                result,
                build_plain_language_notice(result),
                ledger_path=Path(td) / "handoff.jsonl",
            )
            bridge = build_minimized_bridge_payload(result, handoff)
        self.assertEqual(
            bridge["market_context"]["mstr_asst_market_health"]["state"],
            "REANALYSIS_REQUESTED",
        )
        self.assertNotIn("private_context", bridge)
        self.assertFalse(bridge["privacy"]["raw_private_context_included"])
        self.assertEqual(bridge["authority"]["external_action_authority"], "NONE")

    def test_same_equity_health_state_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "handoff.jsonl"
            first_pack = active_pack(market_health(), "a" * 64)
            second_pack = active_pack(market_health(), "b" * 64)
            first = run_gpt_handoff_gate(
                first_pack,
                build_plain_language_notice(first_pack),
                ledger_path=ledger,
            )
            second = run_gpt_handoff_gate(
                second_pack,
                build_plain_language_notice(second_pack),
                ledger_path=ledger,
            )
        self.assertEqual(first["state"], "GPT_HANDOFF_READY")
        self.assertEqual(second["state"], "DUPLICATE_SKIPPED")
        self.assertEqual(first["event_id"], second["event_id"])

    def test_different_asset_health_reason_creates_new_event(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "handoff.jsonl"
            first_pack = active_pack(market_health("MSTR"), "a" * 64)
            second_pack = active_pack(market_health("ASST"), "b" * 64)
            first = run_gpt_handoff_gate(
                first_pack,
                build_plain_language_notice(first_pack),
                ledger_path=ledger,
            )
            second = run_gpt_handoff_gate(
                second_pack,
                build_plain_language_notice(second_pack),
                ledger_path=ledger,
            )
        self.assertEqual(first["state"], "GPT_HANDOFF_READY")
        self.assertEqual(second["state"], "GPT_HANDOFF_READY")
        self.assertNotEqual(first["event_id"], second["event_id"])

    def test_tampered_market_health_fails_closed(self):
        health = market_health()
        health["assets"]["MSTR"]["wake_reasons"] = []
        with self.assertRaises(ValueError):
            fuse_reanalysis_wake(
                None,
                plan_drift=stable_plan(),
                mstr_asst_market_health=health,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
