from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar import capital_decision_closure as capital
from crt_radar.daily_evidence_runner import run_daily_evidence
from crt_radar.gpt_handoff import (
    build_full_decision_bridge_payload,
    build_minimized_bridge_payload,
    expand_bridge_field_names,
    run_gpt_handoff_gate,
)
from crt_radar.ibkr_market_health_sources import (
    FOUR_ASSETS,
    build_four_asset_daily_proof,
    validate_four_asset_daily_proof,
)
from crt_radar.premarket_live_market_handoff import build_premarket_live_market_handoff
from crt_radar.plain_language_notice import build_plain_language_notice
from tests.test_capital_decision_closure import NOW, source_fixture
from tests import test_daily_evidence_runner as daily_fixture
from tests.test_full_bridge_budget import bind_pack, captured_pack, handoff_for, synthetic_daily_price_source

NOW_MS = daily_fixture.NOW_MS


def daily_proof(*, at_ms=NOW, session_date="20260930", missing=()):
    """Disposable vendor-shaped capture, never a live market retrieval."""
    prices = {"MSTR": 153.09, "ASST": 29.41, "STRC": 99.5, "SATA": 98.75}
    capture = {asset: [{"date": session_date, "open": price, "high": price + 1,
                       "low": price - 1, "close": price, "volume": 100}]
               for asset, price in prices.items() if asset not in missing}
    return build_four_asset_daily_proof(
        capture, observed_at_ms=at_ms, request_started_at_ms=at_ms - 1000)


def full_handoff_for(pack, root):
    return run_gpt_handoff_gate(
        pack, build_plain_language_notice(pack), ledger_path=root / "handoff.jsonl",
        full_decision=True)


class FourAssetDailyIntegrationTests(unittest.TestCase):
    def bridge_pack(self, proof):
        pack = captured_pack()
        pack["qualified_equity_daily_source"] = deepcopy(proof)
        pack["qualified_equity_prices"] = validate_four_asset_daily_proof(
            proof, at_ms=pack["generated_at_ms"])
        bind_pack(pack)
        return pack

    def test_daily_runner_seals_original_proof_and_independent_prices(self):
        fixture = daily_fixture.DailyEvidenceRunnerTests()
        fixture.setUp()
        proof = daily_proof(at_ms=NOW_MS, session_date="20260731", missing=("SATA",))
        original = deepcopy(proof)
        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(
                fixture.registry, observation_db=Path(td) / "observations.sqlite3",
                fetch_overrides=fixture.overrides,
                liquidation_aggregate_payload=fixture.aggregate(),
                now_ms=NOW_MS, generated_at_ms=NOW_MS,
                qualified_equity_daily_source=proof)
        self.assertEqual(proof, original)
        self.assertEqual(pack["qualified_equity_daily_source"], original)
        snapshot = pack["qualified_equity_prices"]
        self.assertEqual(set(snapshot["assets"]), set(FOUR_ASSETS))
        for asset in ("MSTR", "ASST", "STRC"):
            self.assertEqual(snapshot["assets"][asset]["state"], "VALID")
        self.assertEqual(snapshot["assets"]["SATA"]["state"], "BLOCKED")
        self.assertEqual(pack["evidence_pack_hash"], capital.digest(
            {key: value for key, value in pack.items() if key != "evidence_pack_hash"}))
        for asset, row in snapshot["assets"].items():
            self.assertEqual(pack["asset_strategy_delta"]["assets"][asset]["price_evidence"], row)
        self.assertEqual(pack["asset_strategy_delta"]["income_engine"]["assets"]["SATA"]["holding_state"], "BLOCKED")
        self.assertIsNone(pack["analyst_output"]["season"])
        self.assertEqual(pack["action_output"], "NONE")

    def test_four_prices_survive_existing_full_capital_projection(self):
        pack = self.bridge_pack(daily_proof())
        original = deepcopy(pack)
        with tempfile.TemporaryDirectory() as td:
            payload = build_full_decision_bridge_payload(pack, full_handoff_for(pack, Path(td)))
        source = source_fixture(payload)
        envelope = capital.build_envelope(payload, source, at_ms=NOW, full_decision=True)
        capital.validate_envelope(envelope)
        projection = json.loads(envelope["request_body"]["input"])
        self.assertEqual(projection["market_context"], payload["market_context"])
        expanded = expand_bridge_field_names(payload)
        self.assertEqual(expanded["market_context"]["qualified_equity_prices"], pack["qualified_equity_prices"])
        self.assertEqual(set(expanded["market_context"]["qualified_equity_prices"]["assets"]), set(FOUR_ASSETS))
        self.assertEqual(projection["evidence_lineage"], pack["evidence_pack_hash"])
        self.assertNotIn("qualified_equity_daily_source", expanded["market_context"])
        catalog = capital.semantic_evidence_catalog(projection)
        for asset in FOUR_ASSETS:
            fact = catalog[f"/market_context/qualified_equity_prices/assets/{asset}/price_usd"]
            self.assertEqual(fact["subject_asset"], asset)
            self.assertEqual(fact["metric_basis"], "COMPLETED_RTH_CLOSE")
            self.assertEqual(fact["qualification_state"], "VALID")
            self.assertEqual(fact["source_time_ms"], pack["qualified_equity_prices"]["assets"][asset]["as_of_ms"])
        self.assertIn("last completed regular-session daily closes", envelope["request_body"]["instructions"])
        self.assertIn("not premarket, live or executable quotes", envelope["request_body"]["instructions"])
        self.assertIn("formal mNAV eligibility", envelope["request_body"]["instructions"])
        self.assertEqual(pack, original)

    def test_invalid_new_proof_blocks_prices_without_losing_other_evidence(self):
        fixture = daily_fixture.DailyEvidenceRunnerTests()
        fixture.setUp()
        proof = daily_proof(at_ms=NOW_MS, session_date="20260731")
        proof["proof_hash"] = "0" * 64
        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(
                fixture.registry, observation_db=Path(td) / "observations.sqlite3",
                fetch_overrides=fixture.overrides,
                liquidation_aggregate_payload=fixture.aggregate(),
                now_ms=NOW_MS, generated_at_ms=NOW_MS,
                qualified_equity_daily_source=proof)
        self.assertEqual(pack["qualified_equity_prices"]["state"], "BLOCKED")
        self.assertTrue(all(row["state"] == "BLOCKED"
                            for row in pack["qualified_equity_prices"]["assets"].values()))
        self.assertIn("L2", pack["layers"])
        self.assertIn("L4", pack["layers"])
        self.assertEqual(pack["qualified_equity_daily_source"], proof)

    def test_bridge_rejects_unsealed_clock_change_and_resealed_snapshot_substitution(self):
        for mode in ("clock", "snapshot"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                pack = self.bridge_pack(daily_proof())
                handoff = handoff_for(pack, Path(td))
                if mode == "clock":
                    pack["qualified_equity_daily_source"]["observed_at_ms"] -= 1
                    expected = "Evidence Pack hash mismatch"
                else:
                    pack["qualified_equity_prices"]["assets"]["STRC"]["price_usd"] += 1
                    bind_pack(pack)
                    handoff = handoff_for(pack, Path(td) / "replacement")
                    expected = "do not match retained source"
                with self.assertRaisesRegex(ValueError, expected):
                    build_minimized_bridge_payload(pack, handoff)

    def test_partial_daily_prices_do_not_unlock_premarket_or_health(self):
        pack = self.bridge_pack(daily_proof(missing=("SATA",)))
        handoff = build_premarket_live_market_handoff(
            source_mode="MACHINE_VERIFIED_ONLY",
            evaluation_window={"start_ms": NOW - 1000, "end_ms": NOW})
        pack["mstr_asst_market_health"] = {"state": "BLOCKED", "reason": "COMMANDER_PROOF_MISSING"}
        pack["premarket_market_data"] = {"state": "BLOCKED", "reason": "PREMARKET_PRICE_UNQUALIFIED",
                                        "battle_map": {"first_screen": []}}
        bind_pack(pack)
        with tempfile.TemporaryDirectory() as td:
            payload = build_full_decision_bridge_payload(pack, full_handoff_for(pack, Path(td)))
        market = expand_bridge_field_names(payload)["market_context"]
        self.assertEqual(market["qualified_equity_prices"]["assets"]["STRC"]["state"], "VALID")
        self.assertEqual(market["qualified_equity_prices"]["assets"]["SATA"]["state"], "BLOCKED")
        self.assertEqual(market["mstr_asst_market_health"], pack["mstr_asst_market_health"])
        self.assertEqual(market["premarket_market_data"], pack["premarket_market_data"])
        for row in handoff["asset_market"].values():
            self.assertEqual(row["premarket_price"]["state"], "BLOCKED")
            self.assertEqual(row["previous_close"]["state"], "BLOCKED")

    def test_legacy_daily_proof_preserves_two_asset_bridge(self):
        pack = captured_pack()
        pack["qualified_equity_daily_source"] = synthetic_daily_price_source(pack["generated_at_ms"])
        bind_pack(pack)
        with tempfile.TemporaryDirectory() as td:
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
        prices = expand_bridge_field_names(payload)["market_context"]["qualified_equity_prices"]
        self.assertEqual(set(prices["assets"]), {"MSTR", "ASST"})
        self.assertEqual(prices["scope"], "LAST_COMPLETED_RTH_CLOSE_NOT_LIVE_QUOTE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
