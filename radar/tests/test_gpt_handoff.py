from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crt_radar.gpt_handoff import (
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


if __name__ == "__main__":
    unittest.main()
