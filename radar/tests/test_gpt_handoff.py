from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crt_radar.gpt_bridge_outbox import (
    enqueue_bridge_payload,
)
from crt_radar.gpt_handoff import (
    build_minimized_bridge_payload,
    run_gpt_handoff_gate,
    semantic_wake_key,
)
from crt_radar.plain_language_notice import (
    build_plain_language_notice,
)
from crt_radar.run_ledger import RunLedger


def authority() -> dict:
    return {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def pack(
    *,
    evidence_hash: str,
    requested: bool,
    wake_sources: list[str] | None = None,
    violated: bool = False,
) -> dict:
    wake_sources = (
        list(wake_sources)
        if wake_sources is not None
        else (
            ["BTC_INTRADAY"]
            if requested
            else []
        )
    )

    wake_reasons = (
        ["MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY"]
        if requested
        else []
    )

    conditions = []

    if violated:
        conditions.append(
            {
                "tranche_id": "T1",
                "field": (
                    "mstr_asst_relative_value_"
                    "validation_status"
                ),
                "operator": "EQ",
                "target_value": "NOT_YET_VALIDATED",
                "source_state": "BOUND",
                "source_kind": "CAPITAL_STATE",
                "source_path": (
                    "private_context.profile.capital_state."
                    "mstr_asst_relative_value_"
                    "validation_status"
                ),
                "current_value": "VALIDATED",
                "evaluation": "VIOLATED",
            }
        )

    return {
        "evidence_pack_hash": evidence_hash,
        "authority": {
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "action_output": "NONE",
        },
        "reanalysis_wake": {
            "state": (
                "REANALYSIS_REQUESTED"
                if requested
                else "NO_WAKE"
            ),
            "reason": (
                "MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY"
                if requested
                else "CHANGE_WITHIN_INTRADAY_HISTORY"
            ),
            "metric": "btc_spot_price_usd",
            "input_family": "BTC_SPOT_PRICE",
            "percent_change": (
                -6.0 if requested else 0.5
            ),
            "wake_sources": wake_sources,
            "wake_reasons": wake_reasons,
            "analyst_reanalysis_requested": requested,
            **authority(),
        },
        "plan_drift": {
            "state": (
                "REANALYSIS_REQUIRED"
                if violated
                else "STABLE"
            ),
            "reason": (
                "ACTIVE_PLAN_CONDITION_VIOLATED"
                if violated
                else "ACTIVE_PLAN_CONDITIONS_SATISFIED"
            ),
            "reanalysis_required": violated,
            "violated_condition_count": (
                1 if violated else 0
            ),
            "plans": [
                {
                    "plan_id": "ATTACK_CAPITAL_WAIT",
                    "conditions": conditions,
                }
            ],
            **authority(),
        },
        "data_health": {
            "critical_blockers": [],
        },
    }


def bridge_pack(
    base: dict,
) -> dict:
    result = json.loads(
        json.dumps(base)
    )

    result["authority"][
        "production"
    ] = "NOT_APPROVED"

    result.update(
        {
            "generated_at_ms": 1787496000000,
            "pack_state": "READY_FOR_ANALYST",
            "layers": {
                "L6": {
                    "status": "VALID",
                    "metrics": {
                        "btc_spot_price_usd": {
                            "value": 77000.0,
                            "source_id": "PUBLIC",
                        }
                    },
                }
            },
            "changes": {
                "btc_spot_price_usd": {
                    "horizons": {
                        "1d": {
                            "history_state": "AVAILABLE",
                            "percent_change": -2.5,
                        }
                    }
                }
            },
            "distillation": {
                "top_changes": [
                    {
                        "metric": "btc_spot_price_usd",
                        "percent_change": -2.5,
                    }
                ]
            },
            "model_status": {
                "btc_season_router": {
                    "state": "CANDIDATE_BLOCKED",
                    "season": None,
                }
            },
            "btc_bull_validation": {
                "state": "SUPPORTIVE",
            },
            "private_context": {
                "state": "AVAILABLE",
                "path": (
                    r"C:\Users\private\portfolio.json"
                ),
                "profile": {
                    "email": "never-export@example.com",
                    "capital_state": {
                        "contract_version": (
                            "CRT_CAPITAL_STATE_V0.1"
                        ),
                        "source": "USER_CONFIRMED",
                        "as_of": (
                            "2026-08-23T22:00:00+08:00"
                        ),
                        "base_currency": "USD",
                    },
                    "capital_state_status": {
                        "state": "AVAILABLE",
                        "execution_authority": (
                            "USER_ONLY"
                        ),
                    },
                    "holdings": [
                        {
                            "asset": "STRC",
                            "quantity": 80.0,
                            "broker_account": (
                                "NEVER_EXPORT"
                            ),
                        },
                        {
                            "asset": "MSTR",
                            "quantity": 5.0,
                        },
                    ],
                    "cash": {
                        "available_usd": 4500.0,
                        "reserved_usd": 180.0,
                        "account_number": (
                            "NEVER_EXPORT"
                        ),
                    },
                    "asset_roles": {
                        "STRC": "INCOME_CORE",
                        "MSTR": "BTC_PROXY",
                        "USD": "ATTACK_CAPITAL",
                        "UNUSED": "DO_NOT_EXPORT",
                    },
                    "plans": [
                        {
                            "plan_id": (
                                "ATTACK_CAPITAL_WAIT"
                            ),
                            "asset": "USD",
                            "side": "WAIT",
                            "status": "ACTIVE",
                            "private_note": (
                                "NEVER_EXPORT"
                            ),
                            "tranches": [
                                {
                                    "tranche_id": "T1",
                                    "budget_usd": 1500.0,
                                    "status": "PENDING",
                                    "validity_conditions": [
                                        {
                                            "field": (
                                                "mstr_asst_relative_value_"
                                                "validation_status"
                                            ),
                                            "operator": "EQ",
                                            "value": (
                                                "NOT_YET_VALIDATED"
                                            ),
                                            "private_note": (
                                                "NEVER_EXPORT"
                                            ),
                                        }
                                    ],
                                },
                                {
                                    "tranche_id": "T2",
                                    "budget_usd": 1500.0,
                                    "status": "PENDING",
                                    "validity_conditions": [
                                        {
                                            "field": (
                                                "mstr_asst_relative_value_"
                                                "validation_status"
                                            ),
                                            "operator": "EQ",
                                            "value": (
                                                "NOT_YET_VALIDATED"
                                            ),
                                        }
                                    ],
                                },
                                {
                                    "tranche_id": "T3",
                                    "budget_usd": 1500.0,
                                    "status": "PENDING",
                                    "validity_conditions": [
                                        {
                                            "field": (
                                                "mstr_asst_relative_value_"
                                                "validation_status"
                                            ),
                                            "operator": "EQ",
                                            "value": (
                                                "NOT_YET_VALIDATED"
                                            ),
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "plan_id": "OLD_PLAN",
                            "asset": "MSTR",
                            "side": "BUY",
                            "status": "CANCELLED",
                            "tranches": [],
                        },
                    ],

                    # Existing Notice contract dependencies.
                    "strc": {
                        "shares": 80.0,
                        "current_annual_distribution_rate": (
                            0.12
                        ),
                        "tax_treatment": (
                            "RETURN_OF_CAPITAL"
                        ),
                        "secret": "NEVER_EXPORT",
                    },
                    "cash_goal": {
                        "six_month_target_usd": 1500.0,
                    },
                    "derived": {
                        "six_month_cash_usd": 480.0,
                        "minimum_shares_for_target": 250,
                        "private_metric": 123,
                    },
                },
            },
        }
    )

    return result


class GptHandoffGateTests(unittest.TestCase):

    def test_first_wake_is_appended(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "handoff.jsonl"

            first_pack = pack(
                evidence_hash="a" * 64,
                requested=True,
            )
            notice = build_plain_language_notice(
                first_pack
            )

            result = run_gpt_handoff_gate(
                first_pack,
                notice,
                ledger_path=ledger_path,
            )

            self.assertEqual(
                result["state"],
                "GPT_HANDOFF_READY",
            )
            self.assertEqual(
                result["append_status"],
                "APPENDED",
            )
            self.assertEqual(
                result[
                    "external_action_authority"
                ],
                "NONE",
            )
            self.assertFalse(
                result["transport_performed"]
            )

            rows = RunLedger(
                ledger_path
            ).records()

            self.assertEqual(len(rows), 1)
            self.assertEqual(
                rows[0]["record_type"],
                "GPT_HANDOFF",
            )

    def test_same_semantic_event_is_deduplicated_even_if_pack_hash_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "handoff.jsonl"

            first_pack = pack(
                evidence_hash="a" * 64,
                requested=True,
            )
            second_pack = pack(
                evidence_hash="b" * 64,
                requested=True,
            )

            first = run_gpt_handoff_gate(
                first_pack,
                build_plain_language_notice(
                    first_pack
                ),
                ledger_path=ledger_path,
            )

            second = run_gpt_handoff_gate(
                second_pack,
                build_plain_language_notice(
                    second_pack
                ),
                ledger_path=ledger_path,
            )

            self.assertEqual(
                second["state"],
                "DUPLICATE_SKIPPED",
            )
            self.assertEqual(
                second["event_id"],
                first["event_id"],
            )

            self.assertEqual(
                len(
                    RunLedger(
                        ledger_path
                    ).records()
                ),
                1,
            )

    def test_no_wake_resets_episode_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "handoff.jsonl"

            active_pack = pack(
                evidence_hash="a" * 64,
                requested=True,
            )
            quiet_pack = pack(
                evidence_hash="b" * 64,
                requested=False,
            )

            run_gpt_handoff_gate(
                active_pack,
                build_plain_language_notice(
                    active_pack
                ),
                ledger_path=ledger_path,
            )

            reset = run_gpt_handoff_gate(
                quiet_pack,
                build_plain_language_notice(
                    quiet_pack
                ),
                ledger_path=ledger_path,
            )

            quiet_again = run_gpt_handoff_gate(
                quiet_pack,
                build_plain_language_notice(
                    quiet_pack
                ),
                ledger_path=ledger_path,
            )

            self.assertEqual(
                reset["append_status"],
                "RESET_APPENDED",
            )
            self.assertEqual(
                quiet_again["append_status"],
                "NOOP",
            )

            rows = RunLedger(
                ledger_path
            ).records()

            self.assertEqual(len(rows), 2)
            self.assertEqual(
                rows[-1]["record_type"],
                "GPT_HANDOFF_RESET",
            )

    def test_same_semantic_event_after_reset_is_new_episode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "handoff.jsonl"

            active_one = pack(
                evidence_hash="a" * 64,
                requested=True,
            )
            quiet = pack(
                evidence_hash="b" * 64,
                requested=False,
            )
            active_two = pack(
                evidence_hash="c" * 64,
                requested=True,
            )

            first = run_gpt_handoff_gate(
                active_one,
                build_plain_language_notice(
                    active_one
                ),
                ledger_path=ledger_path,
            )

            run_gpt_handoff_gate(
                quiet,
                build_plain_language_notice(
                    quiet
                ),
                ledger_path=ledger_path,
            )

            second = run_gpt_handoff_gate(
                active_two,
                build_plain_language_notice(
                    active_two
                ),
                ledger_path=ledger_path,
            )

            self.assertEqual(
                second["state"],
                "GPT_HANDOFF_READY",
            )
            self.assertNotEqual(
                second["event_id"],
                first["event_id"],
            )

            self.assertEqual(
                len(
                    RunLedger(
                        ledger_path
                    ).records()
                ),
                3,
            )

    def test_changed_wake_sources_create_new_event(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "handoff.jsonl"

            first_pack = pack(
                evidence_hash="a" * 64,
                requested=True,
                wake_sources=[
                    "BTC_INTRADAY",
                ],
            )

            second_pack = pack(
                evidence_hash="b" * 64,
                requested=True,
                wake_sources=[
                    "BTC_INTRADAY",
                    "PLAN_DRIFT",
                ],
                violated=True,
            )

            first = run_gpt_handoff_gate(
                first_pack,
                build_plain_language_notice(
                    first_pack
                ),
                ledger_path=ledger_path,
            )

            second = run_gpt_handoff_gate(
                second_pack,
                build_plain_language_notice(
                    second_pack
                ),
                ledger_path=ledger_path,
            )

            self.assertEqual(
                first["append_status"],
                "APPENDED",
            )
            self.assertEqual(
                second["append_status"],
                "APPENDED",
            )
            self.assertNotEqual(
                first["semantic_wake_key"],
                second["semantic_wake_key"],
            )

            self.assertEqual(
                len(
                    RunLedger(
                        ledger_path
                    ).records()
                ),
                2,
            )

    def test_handoff_carries_reanalysis_semantics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "handoff.jsonl"

            active_pack = pack(
                evidence_hash="a" * 64,
                requested=True,
            )

            result = run_gpt_handoff_gate(
                active_pack,
                build_plain_language_notice(
                    active_pack
                ),
                ledger_path=ledger_path,
            )

            semantics = result[
                "reanalysis_semantics"
            ]

            self.assertEqual(
                semantics["schema_version"],
                "CRT_GPT_REANALYSIS_SEMANTICS_V0.1",
            )

            self.assertEqual(
                semantics["scope"],
                "POST_WAKE_ANALYSIS_ONLY",
            )

            self.assertEqual(
                semantics["analysis_sequence"],
                [
                    "CATALYST",
                    "AMPLIFIER",
                    "PERSISTENCE",
                    "ACCEPTANCE",
                    "CONTRADICTIONS",
                    "MISSING_EVIDENCE",
                ],
            )

            self.assertEqual(
                semantics["causal_guardrails"],
                [
                    "TEMPORAL_ORDER_IS_NOT_CAUSATION",
                    (
                        "TRANSIENT_PRICE_CROSSING_IS_NOT_"
                        "ACCEPTANCE_OR_REAL_DEMAND"
                    ),
                    (
                        "CONTRADICTORY_EVIDENCE_MUST_BE_"
                        "SURFACED"
                    ),
                    (
                        "MISSING_EVIDENCE_MUST_NOT_BE_"
                        "IMPUTED_OR_GUESSED"
                    ),
                ],
            )

            self.assertEqual(
                semantics["evidence_rules"],
                [
                    "SEPARATE_OBSERVATION_FROM_INFERENCE",
                    (
                        "STATE_UNRESOLVED_CAUSALITY_"
                        "EXPLICITLY"
                    ),
                    "USE_LATEST_REQUIRED_INPUTS",
                ],
            )

            self.assertEqual(
                semantics["governance_guardrails"],
                [
                    (
                        "RESEARCH_OVERLAY_CANNOT_PROMOTE_"
                        "FORMAL_SEASON"
                    ),
                    "NO_AUTOMATIC_BUY_SELL",
                    "NO_EXTERNAL_ACTION",
                ],
            )

            self.assertEqual(
                semantics["wake_authority"],
                "NONE",
            )

            self.assertEqual(
                semantics[
                    "formal_season_authority"
                ],
                "NONE",
            )

            self.assertEqual(
                semantics["trading_authority"],
                "NONE",
            )

            self.assertEqual(
                semantics[
                    "external_action_authority"
                ],
                "NONE",
            )

            rows = RunLedger(
                ledger_path
            ).records()

            self.assertEqual(
                rows[0]["payload"][
                    "reanalysis_semantics"
                ],
                semantics,
            )

    def test_reanalysis_semantics_do_not_change_semantic_wake_identity(
        self,
    ) -> None:
        active_pack = pack(
            evidence_hash="a" * 64,
            requested=True,
        )

        decorated_pack = {
            **active_pack,
            "reanalysis_semantics": {
                "analysis_sequence": [
                    "SENTINEL"
                ],
            },
        }

        self.assertEqual(
            semantic_wake_key(
                active_pack
            ),
            semantic_wake_key(
                decorated_pack
            ),
        )


    def test_minimized_bridge_payload_allowlists_private_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            active_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )

            handoff = run_gpt_handoff_gate(
                active_pack,
                build_plain_language_notice(
                    active_pack
                ),
                ledger_path=(
                    Path(td)
                    / "handoff.jsonl"
                ),
            )

            bridge = build_minimized_bridge_payload(
                active_pack,
                handoff,
            )

            self.assertEqual(
                bridge["state"],
                "BRIDGE_PAYLOAD_READY_LOCAL_ONLY",
            )

            self.assertEqual(
                bridge[
                    "privacy_contract_version"
                ],
                (
                    "CRT_BRIDGE_PAYLOAD_"
                    "PRIVACY_CONTRACT_V0.1"
                ),
            )

            self.assertEqual(
                bridge["authority"][
                    "production"
                ],
                "NOT_APPROVED",
            )

            self.assertEqual(
                bridge["authority"][
                    "external_action_authority"
                ],
                "NONE",
            )

            self.assertEqual(
                bridge["authority"][
                    "transport_authority"
                ],
                "NONE",
            )

            self.assertFalse(
                bridge["authority"][
                    "transport_performed"
                ]
            )

            self.assertEqual(
                bridge["capital_state"][
                    "execution_authority"
                ],
                "USER_ONLY",
            )

            self.assertEqual(
                bridge["capital_state"][
                    "holdings"
                ],
                [
                    {
                        "asset": "STRC",
                        "quantity": 80.0,
                    },
                    {
                        "asset": "MSTR",
                        "quantity": 5.0,
                    },
                ],
            )

            self.assertEqual(
                bridge["capital_state"][
                    "cash"
                ],
                {
                    "available_usd": 4500.0,
                    "reserved_usd": 180.0,
                },
            )

            self.assertEqual(
                set(
                    bridge["capital_state"][
                        "asset_roles"
                    ]
                ),
                {
                    "STRC",
                    "MSTR",
                    "USD",
                },
            )

            self.assertEqual(
                len(
                    bridge["capital_state"][
                        "active_plans"
                    ]
                ),
                1,
            )

            serialized = json.dumps(
                bridge,
                ensure_ascii=False,
                sort_keys=True,
            )

            for forbidden in (
                '"private_context":',
                r"C:\Users\private",
                "never-export@example.com",
                "broker_account",
                "account_number",
                "NEVER_EXPORT",
                "RETURN_OF_CAPITAL",
                "cash_goal",
                '"strc"',
                "private_note",
                "OLD_PLAN",
                "UNUSED",
            ):
                self.assertNotIn(
                    forbidden,
                    serialized,
                )

            self.assertEqual(
                len(
                    bridge[
                        "bridge_payload_hash"
                    ]
                ),
                64,
            )

    def test_minimized_bridge_payload_requires_current_capital_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            active_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )

            active_pack[
                "private_context"
            ][
                "profile"
            ][
                "capital_state_status"
            ][
                "state"
            ] = "BLOCKED"

            handoff = run_gpt_handoff_gate(
                active_pack,
                build_plain_language_notice(
                    active_pack
                ),
                ledger_path=(
                    Path(td)
                    / "handoff.jsonl"
                ),
            )

            with self.assertRaises(
                ValueError
            ):
                build_minimized_bridge_payload(
                    active_pack,
                    handoff,
                )

    def test_minimized_bridge_payload_requires_ready_handoff(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            quiet_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=False,
                )
            )

            handoff = run_gpt_handoff_gate(
                quiet_pack,
                build_plain_language_notice(
                    quiet_pack
                ),
                ledger_path=(
                    Path(td)
                    / "handoff.jsonl"
                ),
            )

            with self.assertRaises(
                ValueError
            ):
                build_minimized_bridge_payload(
                    quiet_pack,
                    handoff,
                )

    def test_minimized_bridge_payload_rejects_forbidden_market_key(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            active_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )

            active_pack[
                "btc_entry_gate"
            ] = {
                "state": "AVAILABLE",
                "api_key": "NEVER_EXPORT",
            }

            handoff = run_gpt_handoff_gate(
                active_pack,
                build_plain_language_notice(
                    active_pack
                ),
                ledger_path=(
                    Path(td)
                    / "handoff.jsonl"
                ),
            )

            with self.assertRaises(
                ValueError
            ):
                build_minimized_bridge_payload(
                    active_pack,
                    handoff,
                )

    def test_invalid_authority_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad_pack = pack(
                evidence_hash="a" * 64,
                requested=True,
            )

            bad_pack[
                "reanalysis_wake"
            ][
                "external_action_authority"
            ] = "TRADE"

            notice = build_plain_language_notice(
                {
                    **bad_pack,
                    "reanalysis_wake": {
                        **bad_pack[
                            "reanalysis_wake"
                        ],
                        "external_action_authority": "NONE",
                    },
                }
            )

            with self.assertRaises(
                ValueError
            ):
                run_gpt_handoff_gate(
                    bad_pack,
                    notice,
                    ledger_path=(
                        Path(td)
                        / "handoff.jsonl"
                    ),
                )

    def test_local_bridge_outbox_is_written_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger_path = root / "handoff.jsonl"
            outbox = root / "outbox"

            active_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )
            notice = build_plain_language_notice(active_pack)

            first = run_gpt_handoff_gate(
                active_pack,
                notice,
                ledger_path=ledger_path,
                bridge_outbox_dir=outbox,
            )

            self.assertEqual(first["state"], "GPT_HANDOFF_READY")
            self.assertEqual(
                first["bridge_outbox"]["state"],
                "OUTBOX_ENQUEUED",
            )
            self.assertEqual(
                len(list(outbox.glob("*.json"))),
                1,
            )

            second = run_gpt_handoff_gate(
                active_pack,
                notice,
                ledger_path=ledger_path,
                bridge_outbox_dir=outbox,
            )

            self.assertEqual(
                second["state"],
                "DUPLICATE_SKIPPED",
            )
            self.assertEqual(
                len(list(outbox.glob("*.json"))),
                1,
            )

    def test_outbox_failure_does_not_commit_handoff(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger_path = root / "handoff.jsonl"

            active_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )
            notice = build_plain_language_notice(active_pack)

            with patch(
                "crt_radar.gpt_handoff.enqueue_bridge_payload",
                side_effect=OSError("synthetic disk failure"),
            ):
                with self.assertRaises(OSError):
                    run_gpt_handoff_gate(
                        active_pack,
                        notice,
                        ledger_path=ledger_path,
                        bridge_outbox_dir=root / "outbox",
                    )

            self.assertEqual(
                RunLedger(ledger_path).records(),
                [],
            )

    def test_orphan_outbox_recovers_if_ledger_append_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger_path = root / "handoff.jsonl"
            outbox = root / "outbox"

            active_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )
            notice = build_plain_language_notice(active_pack)

            with patch.object(
                RunLedger,
                "append",
                side_effect=OSError("synthetic ledger failure"),
            ):
                with self.assertRaises(OSError):
                    run_gpt_handoff_gate(
                        active_pack,
                        notice,
                        ledger_path=ledger_path,
                        bridge_outbox_dir=outbox,
                    )

            self.assertEqual(
                len(list(outbox.glob("*.json"))),
                1,
            )
            self.assertEqual(
                RunLedger(ledger_path).records(),
                [],
            )

            recovered = run_gpt_handoff_gate(
                active_pack,
                notice,
                ledger_path=ledger_path,
                bridge_outbox_dir=outbox,
            )

            self.assertEqual(
                recovered["state"],
                "GPT_HANDOFF_READY",
            )
            self.assertEqual(
                recovered["bridge_outbox"]["state"],
                "DUPLICATE_SKIPPED",
            )
            self.assertEqual(
                len(RunLedger(ledger_path).records()),
                1,
            )

    def test_outbox_same_event_conflict_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            first_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )
            second_pack = bridge_pack(
                pack(
                    evidence_hash="b" * 64,
                    requested=True,
                )
            )

            first_handoff = run_gpt_handoff_gate(
                first_pack,
                build_plain_language_notice(first_pack),
                ledger_path=root / "first.jsonl",
            )
            second_handoff = run_gpt_handoff_gate(
                second_pack,
                build_plain_language_notice(second_pack),
                ledger_path=root / "second.jsonl",
            )

            self.assertEqual(
                first_handoff["event_id"],
                second_handoff["event_id"],
            )

            first_bridge = build_minimized_bridge_payload(
                first_pack,
                first_handoff,
            )
            second_bridge = build_minimized_bridge_payload(
                second_pack,
                second_handoff,
            )

            outbox = root / "outbox"
            enqueue_bridge_payload(outbox, first_bridge)

            with self.assertRaises(ValueError):
                enqueue_bridge_payload(
                    outbox,
                    second_bridge,
                )

    def test_outbox_publish_race_does_not_overwrite_existing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outbox = root / "outbox"

            first_pack = bridge_pack(
                pack(
                    evidence_hash="a" * 64,
                    requested=True,
                )
            )
            second_pack = bridge_pack(
                pack(
                    evidence_hash="b" * 64,
                    requested=True,
                )
            )

            first_handoff = run_gpt_handoff_gate(
                first_pack,
                build_plain_language_notice(first_pack),
                ledger_path=root / "first.jsonl",
            )
            second_handoff = run_gpt_handoff_gate(
                second_pack,
                build_plain_language_notice(second_pack),
                ledger_path=root / "second.jsonl",
            )

            first_bridge = build_minimized_bridge_payload(
                first_pack,
                first_handoff,
            )
            second_bridge = build_minimized_bridge_payload(
                second_pack,
                second_handoff,
            )

            enqueue_bridge_payload(
                outbox,
                first_bridge,
            )

            event_id = first_bridge["event"]["event_id"]
            target = outbox / f"{event_id}.json"
            original_exists = Path.exists

            def racing_exists(path: Path) -> bool:
                if path == target:
                    return False
                return original_exists(path)

            with patch.object(
                Path,
                "exists",
                autospec=True,
                side_effect=racing_exists,
            ):
                with self.assertRaises(ValueError):
                    enqueue_bridge_payload(
                        outbox,
                        second_bridge,
                    )

            stored = json.loads(
                target.read_text(encoding="utf-8")
            )

            self.assertEqual(
                stored["bridge_payload_hash"],
                first_bridge["bridge_payload_hash"],
            )


if __name__ == "__main__":
    unittest.main()
