from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from crt_radar.evidence_pack import (
    attach_premarket_market_data,
    build_evidence_pack,
)
from crt_radar.gpt_handoff import (
    build_minimized_bridge_payload,
    run_gpt_handoff_gate,
)
from crt_radar.plain_language_notice import (
    build_plain_language_notice,
)
from crt_radar.premarket_battle_map import (
    build_premarket_battle_map,
)
from crt_radar.premarket_live_market_handoff import (
    apply_live_market_handoff_to_asset_facts,
    build_premarket_live_market_handoff,
)

from test_first_evidence_slice import BASE_MS, DAY_MS, gate
from test_premarket_live_market_handoff import (
    CONTRACT,
    _observations,
    _source_gate,
)


def _private_context() -> dict:
    return {
        "state": "AVAILABLE",
        "profile": {
            "email": "NEVER_EXPORT@example.test",
            "strc": {
                "shares": 1.0,
                "distribution_rate_mode": "DYNAMIC_LOCAL_VALUE",
                "current_annual_distribution_rate": 0.12,
                "stated_amount_usd": 100.0,
                "tax_treatment": "RETURN_OF_CAPITAL",
                "withholding_rate": 0.0,
            },
            "cash_goal": {
                "six_month_target_usd": 100.0,
                "fixed_minimum_shares": 1,
            },
            "derived": {
                "six_month_cash_usd": 6.0,
                "minimum_shares_for_target": 1,
                "goal_covered_at_current_rate": False,
            },
            "capital_state": {
                "contract_version": "CRT_CAPITAL_STATE_V0.1",
                "source": "SYNTHETIC_E2E_ACCEPTANCE_FIXTURE",
                "as_of": "2026-09-06T16:00:00+08:00",
                "base_currency": "USD",
            },
            "capital_state_status": {
                "state": "AVAILABLE",
                "execution_authority": "USER_ONLY",
            },
            "holdings": [
                {
                    "asset": "MSTR",
                    "quantity": 1.0,
                    "broker_account": "NEVER_EXPORT",
                }
            ],
            "cash": {
                "available_usd": 1000.0,
                "reserved_usd": 0.0,
                "account_number": "NEVER_EXPORT",
            },
            "asset_roles": {
                "MSTR": "GROWTH_ENGINE",
                "USD": "ATTACK_CAPITAL",
                "SECRET": "NEVER_EXPORT",
            },
            "plans": [],
        },
    }


def _assumption_watch_context() -> dict:
    return {
        "state": "AVAILABLE",
        "context": {
            "schema_version": "CRT_ASSUMPTION_RESEARCH_CONTEXT_V0.1",
            "valid_until_ms": 9_999_999_999_999,
            "formal_model_modification_authority": "NONE",
            "external_action_authority": "NONE",
            "btc_q4_lower_entry_hypothesis": {
                "state": "ACTIVE_RESEARCH_HYPOTHESIS",
                "reference_target_usd": 57_000,
            },
        },
    }


def _entry_gate() -> dict:
    return {
        "state": "READY_FOR_ANALYST",
        "reason": "E2E_ACCEPTANCE_FIXTURE",
        "transition_state": "BULL_ACCEPTANCE_STRENGTHENED",
        "decision_eligibility": "PROBE_ELIGIBLE",
        "research_corridor": {
            "formal_threshold_authority": "NONE",
        },
        "mechanism_support": {
            "constructive": True,
        },
        "control_transfer_validation": {
            "control_transfer_loop_closed": True,
        },
        "quantitative": {
            "accepted_upper_by_price_closes": True,
            "accepted_lower_by_price_closes": True,
            "rejected_lower_by_price_closes": False,
            "provisional_sma200_reclaim": True,
            "closed_daily_sma200_reclaim": True,
        },
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def _wake() -> dict:
    return {
        "state": "REANALYSIS_REQUESTED",
        "reason": "E2E_ACCEPTANCE_FORCED_WAKE",
        "metric": "btc_spot_price_usd",
        "input_family": "BTC_SPOT_PRICE",
        "percent_change": 5.0,
        "wake_sources": ["E2E_ACCEPTANCE"],
        "wake_reasons": ["E2E_ACCEPTANCE_FORCED_WAKE"],
        "analyst_reanalysis_requested": True,
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def _transition_diagnostic() -> dict:
    return {
        "state": "READY_FOR_ANALYST",
        "short_squeeze": False,
        "long_fomo_rebuild": False,
        "spot_demand_absorption": True,
        "spot_demand_persistence": True,
        "leverage_quality": "CONSTRUCTIVE",
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


class SeasonThreeArmyGptE2ETests(unittest.TestCase):
    def test_current_evidence_pack_to_gpt_three_army_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            db = td_path / "obs.sqlite3"

            for day in range(31):
                build_evidence_pack(
                    gate(day),
                    observation_db=db,
                    generated_at_ms=BASE_MS + day * DAY_MS,
                )

            pack = build_evidence_pack(
                gate(31),
                observation_db=db,
                generated_at_ms=BASE_MS + 31 * DAY_MS,
                reanalysis_wake=_wake(),
                transition_diagnostic=_transition_diagnostic(),
                btc_entry_gate=_entry_gate(),
                assumption_watch_context=_assumption_watch_context(),
                private_context=_private_context(),
            )

            self.assertEqual(
                pack["schema_version"],
                "CRT_EVIDENCE_PACK_V0.2",
            )
            self.assertIn("asset_strategy_delta", pack)
            self.assertIn("btc_bull_validation", pack)
            self.assertIn("season_transition_warning_overlay", pack)
            self.assertEqual(
                pack["model_status"]["btc_season_router"]["state"],
                "CANDIDATE_BLOCKED",
            )
            self.assertIsNone(
                pack["model_status"]["btc_season_router"]["season"]
            )

            live_handoff = build_premarket_live_market_handoff(
                source_mode="MANUAL_WEB_SUPPLEMENT",
                evaluation_window={
                    "start_ms": 100,
                    "end_ms": 200,
                },
                source_gate_result=_source_gate(),
                manual_asset_observations=_observations(),
            )

            asset_facts = apply_live_market_handoff_to_asset_facts(
                {},
                live_handoff,
            )

            battle_map = build_premarket_battle_map(
                contract=CONTRACT,
                asset_facts=asset_facts,
                issuer_reflexivity={
                    "state": "VALID",
                    "event_state": (
                        "NO_NEW_MATERIAL_ISSUER_EVENT"
                    ),
                },
                as_of="2026-09-06T16:00:00+08:00",
                source_mode="MANUAL_WEB_SUPPLEMENT",
                live_market_handoff=live_handoff,
            )

            pack = attach_premarket_market_data(
                pack,
                live_market_handoff=live_handoff,
                battle_map=battle_map,
            )

            notice = build_plain_language_notice(pack)
            handoff = run_gpt_handoff_gate(
                pack,
                notice,
                ledger_path=td_path / "handoff.jsonl",
            )
            bridge = build_minimized_bridge_payload(
                pack,
                handoff,
            )

            self.assertEqual(
                handoff["state"],
                "GPT_HANDOFF_READY",
            )
            self.assertEqual(
                handoff["source_evidence_pack_hash"],
                pack["evidence_pack_hash"],
            )
            self.assertEqual(
                bridge["event"]["source_evidence_pack_hash"],
                pack["evidence_pack_hash"],
            )

            market = bridge["market_context"]
            self.assertEqual(
                market["asset_strategy_delta"],
                pack["asset_strategy_delta"],
            )
            self.assertEqual(
                market["premarket_market_data"],
                pack["premarket_market_data"],
            )
            self.assertEqual(
                market["season_transition_warning_overlay"],
                pack["season_transition_warning_overlay"],
            )

            unsafe_pack = deepcopy(pack)
            unsafe_pack["season_transition_warning_overlay"][
                "formal_season"
            ] = "SPRING"
            with self.assertRaisesRegex(
                ValueError,
                "SEASON_TRANSITION_WARNING_OVERLAY_INVALID",
            ):
                build_minimized_bridge_payload(
                    unsafe_pack,
                    handoff,
                )

            contract = bridge[
                "analysis_contract"
            ][
                "season_three_army_role_separation"
            ]

            self.assertEqual(
                contract["season"]["scope"],
                "STRATEGIC_RISK_POSTURE_ONLY",
            )
            self.assertEqual(
                contract["bull_foundation"]["scope"],
                "TRANSITION_CREDIBILITY_ONLY",
            )
            self.assertEqual(
                contract["commander"]["scope"],
                "TACTICAL_LINES_AND_CAPITAL_DEPLOYMENT",
            )
            self.assertIsNone(
                contract["season"]["formal_season"]
            )
            self.assertEqual(
                contract["season"]["output_mode"],
                (
                    "LABELED_ANALYST_HYPOTHESIS_"
                    "OR_WEATHER_ONLY"
                ),
            )
            self.assertFalse(
                contract["season"][
                    "candidate_may_promote_formal_season"
                ]
            )
            self.assertFalse(
                contract["commander"][
                    "tactical_feedback_may_modify_formal_season"
                ]
            )
            self.assertEqual(
                contract["source_evidence_pack_hash"],
                pack["evidence_pack_hash"],
            )
            self.assertEqual(
                len(
                    contract[
                        "role_separation_contract_hash"
                    ]
                ),
                64,
            )

            authority = bridge["authority"]
            self.assertEqual(
                authority["action_output"],
                "NONE",
            )
            self.assertEqual(
                authority["capital_decision_authority"],
                "USER_ONLY",
            )
            self.assertEqual(
                authority["external_action_authority"],
                "NONE",
            )
            self.assertFalse(
                authority["machine_may_execute_trade"]
            )
            self.assertEqual(
                authority["production"],
                "NOT_APPROVED",
            )

            serialized = json.dumps(
                bridge,
                ensure_ascii=False,
                sort_keys=True,
            )
            for forbidden in (
                "NEVER_EXPORT@example.test",
                "broker_account",
                "account_number",
                '"private_context"',
                '"SECRET"',
            ):
                self.assertNotIn(
                    forbidden,
                    serialized,
                )

            for row in market[
                "premarket_market_data"
            ][
                "battle_map"
            ][
                "first_screen"
            ]:
                self.assertIsNone(row["light"])
                self.assertIsNone(
                    row["entry_shares_delta"]
                )
                self.assertTrue(
                    all(
                        value is None
                        for value
                        in row["entry_condition"].values()
                    )
                )
                self.assertTrue(
                    all(
                        value is None
                        for channel
                        in row[
                            "exit_condition"
                        ].values()
                        for value
                        in channel.values()
                    )
                )
                self.assertEqual(
                    row["exit_shares_delta"],
                    {
                        "stop_loss": None,
                        "take_profit": None,
                    },
                )


if __name__ == "__main__":
    unittest.main()
