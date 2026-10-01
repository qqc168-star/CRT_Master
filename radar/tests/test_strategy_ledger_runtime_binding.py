"""Deterministic fixtures only; these tests never claim live source evidence."""
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.gpt_handoff import build_minimized_bridge_payload, run_gpt_handoff_gate
from crt_radar.issuer_ratio_market_health_source import (
    build_ledger_ratio_data, build_live_issuer_ratio_proof,
    parse_strategy_ledger,
)
from crt_radar.mstr_asst_market_health import issuer_ratio_observation, validate_mstr_asst_market_health
from crt_radar.mstr_asst_market_health_runtime import (
    build_market_health_runtime_outputs, canonical_hash, seal_runtime_source,
)
from crt_radar.plain_language_notice import build_plain_language_notice
from tests.test_mstr_asst_market_health_runtime import runtime_bundle
from tests.test_mstr_asst_gpt_wake_closure import active_pack
from tests.test_wake_fusion import minimal_source_gate, private_context


NOW = 1_790_846_077_298
URL = "https://www.strategy.com/ledger"
HEADER = "<tr><th>Count</th><th>Reported</th><th>BTC Acq</th><th>BTC</th><th>ADSO ('000)</th></tr>"


def ledger_html(extra: str = "") -> bytes:
    # Deliberately unordered, with unrelated acquisition amounts and a totals row.
    return ("<table>" + HEADER
            + "<tr><td></td><td></td><td>999</td><td>999999</td><td>1</td></tr>"
            + "<tr><td>119</td><td>9/14/2026</td><td>1</td><td>845050</td><td>449000</td></tr>"
            + "<tr><td>121</td><td>9/28/2026</td><td>1665</td><td>847,666</td><td>451,577</td></tr>"
            + "<tr><td>120</td><td>9/21/2026</td><td>950</td><td>846,000</td><td>450,108</td></tr>"
            + "<tr><td>1</td><td>8/10/2020</td><td>1</td><td>21454</td><td>-</td></tr>"
            + extra + "</table>").encode()


def ledger_pair() -> dict:
    return build_ledger_ratio_data(parse_strategy_ledger(
        ledger_html(), source_url=URL, retrieved_at_ms=NOW,
    ))


def ledger_runtime_bundle() -> dict:
    bundle = runtime_bundle()
    bundle["generated_at_ms"] = NOW + 1
    data = deepcopy(bundle["source_proofs"]["issuer_btc_per_diluted_share"]["data"])
    data["MSTR"] = ledger_pair()
    bundle["source_proofs"]["issuer_btc_per_diluted_share"] = seal_runtime_source(
        source_key="issuer_btc_per_diluted_share", data=data, observed_at_ms=NOW,
    )
    return bundle


class StrategyLedgerRuntimeBindingTests(unittest.TestCase):
    def test_same_row_units_adjacent_dates_and_reported_clocks(self):
        pair = ledger_pair()
        self.assertEqual(pair["previous_reported_date"], "2026-09-21")
        self.assertEqual(pair["current_reported_date"], "2026-09-28")
        self.assertEqual(pair["current_diluted_shares"], 451577000)
        self.assertEqual(pair["previous_btc_holdings"], 846000)
        change = (pair["current_btc_per_diluted_share"] / pair["previous_btc_per_diluted_share"] - 1) * 100
        self.assertAlmostEqual(change, -0.12901833051349731)
        self.assertFalse(any("effective_at" in key for key in pair))

    def test_ambiguous_header_and_changed_units_fail_closed(self):
        for raw in (ledger_html() * 2, ledger_html().replace(b"ADSO ('000)", b"ADSO")):
            with self.subTest(raw=raw[:40]), self.assertRaisesRegex(ValueError, "unambiguous"):
                parse_strategy_ledger(raw, source_url=URL, retrieved_at_ms=NOW)

    def test_conflicting_date_and_future_row_fail_closed(self):
        for extra in (
            "<tr><td>120</td><td>9/21/2026</td><td>1</td><td>1</td><td>1</td></tr>",
            "<tr><td>122</td><td>10/5/2026</td><td>1</td><td>1</td><td>1</td></tr>",
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                parse_strategy_ledger(ledger_html(extra), source_url=URL, retrieved_at_ms=NOW)

    def test_invalid_pairs_and_insufficient_history_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            parse_strategy_ledger(ledger_html().replace(b"451,577", b"0"), source_url=URL, retrieved_at_ms=NOW)
        with self.assertRaises(ValueError):
            build_ledger_ratio_data([])

    def test_clock_fabrication_and_mixed_rows_rejected_by_consumer(self):
        changes = (
            {"current_effective_at_ms": NOW},
            {"time_semantic": "EFFECTIVE_TIME"},
            {"current_retrieved_at_ms": NOW + 10},
            {"current_reported_at_ms": NOW},
            {"current_diluted_shares": 450108000},
            {"ct_binding_state": "CT_BOUND"},
            {"current_evidence_hash": "missing"},
        )
        for change in changes:
            pair = ledger_pair()
            pair.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                issuer_ratio_observation("MSTR", pair, generated_at_ms=NOW)

    def test_runtime_wake_keeps_reported_claim_and_no_actions(self):
        bundle = ledger_runtime_bundle()
        previous_asst = deepcopy(bundle["source_proofs"]["issuer_btc_per_diluted_share"]["data"]["ASST"])
        health = build_market_health_runtime_outputs(bundle)["market_health"]
        self.assertIn("MSTR:BTC_PER_DILUTED_SHARE_DECREASED", health["wake_reasons"])
        observation = health["assets"]["MSTR"]["issuer_btc_per_diluted_share"]
        self.assertEqual(observation["direction_claim"], "ADJACENT_REPORTED_BTC_PER_ADSO_DECREASED")
        self.assertEqual(observation["ct_blocker"], "ADSO_EFFECTIVE_TIME_UNRESOLVED")
        self.assertEqual(observation["machine_execution"], "FORBIDDEN")
        self.assertEqual(health["action_output"], "NONE")
        self.assertEqual(health["external_action_authority"], "NONE")
        self.assertEqual(health["notification_authority"], "GPT_JUDGMENT_REQUIRED")
        self.assertEqual(health["assets"]["ASST"]["issuer_btc_per_diluted_share"]["current"], previous_asst["current_btc_per_diluted_share"])
        self.assertFalse(health["assets"]["ASST"]["reanalysis_required"])

    def test_missing_commander_still_blocks_full_runtime(self):
        bundle = ledger_runtime_bundle()
        del bundle["source_proofs"]["commander_lines"]
        with self.assertRaisesRegex(ValueError, "exactly the five"):
            build_market_health_runtime_outputs(bundle)

    def test_resealed_health_cannot_upgrade_ledger_clocks_or_claim(self):
        for field, value in (("ct_binding_state", "CT_BOUND"), ("direction_claim", "COMPANY_HEALTH_DETERIORATING"),
                             ("semantic_authority", "UNVERIFIED"), ("current", 1.0)):
            health = build_market_health_runtime_outputs(ledger_runtime_bundle())["market_health"]
            health["assets"]["MSTR"]["issuer_btc_per_diluted_share"][field] = value
            health.pop("market_health_hash")
            health["market_health_hash"] = canonical_hash(health)
            with self.assertRaises(ValueError):
                validate_mstr_asst_market_health(health)

    def test_reported_pair_cannot_downgrade_to_unlabelled_legacy_input(self):
        pair = ledger_pair()
        del pair["source_role"]
        del pair["time_semantic"]
        with self.assertRaisesRegex(ValueError, "contract mismatch"):
            issuer_ratio_observation("MSTR", pair, generated_at_ms=NOW)

    def test_evidence_pack_and_gpt_bridge_preserve_semantic_warnings(self):
        health = build_market_health_runtime_outputs(ledger_runtime_bundle())["market_health"]
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(
                minimal_source_gate(), observation_db=Path(td) / "observations.sqlite3",
                generated_at_ms=NOW + 1, private_context=private_context("NOT_YET_VALIDATED"),
                mstr_asst_market_health=health,
            )
            self.assertIn("MSTR:BTC_PER_DILUTED_SHARE_DECREASED", pack["reanalysis_wake"]["wake_reasons"])
            self.assertEqual(pack["mstr_asst_market_health"], health)
            bridge_pack = active_pack(health, pack["evidence_pack_hash"])
            handoff = run_gpt_handoff_gate(
                bridge_pack, build_plain_language_notice(bridge_pack), ledger_path=Path(td) / "handoff.jsonl",
            )
            bridge = build_minimized_bridge_payload(bridge_pack, handoff)
        observation = bridge["market_context"]["mstr_asst_market_health"]["assets"]["MSTR"]["issuer_btc_per_diluted_share"]
        self.assertEqual(observation, health["assets"]["MSTR"]["issuer_btc_per_diluted_share"])
        self.assertEqual(observation["time_semantic"], "REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME")
        self.assertLess(len(json.dumps(bridge, ensure_ascii=False, separators=(",", ":")).encode()), 16384)

    def test_live_builder_preserves_asst_sec_and_explicit_mstr_sec_audit_path(self):
        history = [{"effective_at_ms": index, "btc_holdings": 20 + index,
                    "diluted_shares": 100, "btc_per_diluted_share": (20 + index) / 100,
                    "source_url": "SEC-TEST", "evidence_hash": "a" * 64} for index in (1, 2)]
        with patch("crt_radar.issuer_ratio_market_health_source.collect_states", return_value=history) as sec, \
                patch("crt_radar.issuer_ratio_market_health_source.collect_ledger_states", return_value=parse_strategy_ledger(ledger_html(), source_url=URL, retrieved_at_ms=NOW)) as ledger, \
                patch("crt_radar.issuer_ratio_market_health_source.time.time", return_value=(NOW + 1) / 1000):
            proof = build_live_issuer_ratio_proof(user_agent="TEST-ONLY")
            self.assertEqual(sec.call_args.args, ("ASST",))
            self.assertEqual(proof["data"]["ASST"]["current_effective_at_ms"], 2)
            self.assertEqual(proof["data"]["MSTR"]["current_reported_date"], "2026-09-28")
            sec.reset_mock()
            ledger.reset_mock()
            audit = build_live_issuer_ratio_proof(user_agent="TEST-ONLY", mstr_source="SEC")
            ledger.assert_not_called()
            self.assertEqual([call.args[0] for call in sec.call_args_list], ["MSTR", "ASST"])
            self.assertEqual(audit["data"]["MSTR"]["current_effective_at_ms"], 2)


if __name__ == "__main__":
    unittest.main()
