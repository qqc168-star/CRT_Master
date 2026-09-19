from copy import deepcopy
import json
import unittest

from crt_radar.diluted_equity_mnav import build_diluted_equity_mnav
from crt_radar.issuer_fact_history import select_fact_history
from crt_radar.premarket_evidence_binding import build_premarket_evidence_binding
from crt_radar.ibkr_live_market_data_intake import (
    build_ibkr_crt_outputs, build_ibkr_equity_live_snapshot,
    load_ibkr_source_registry, SOURCE_ID, IbkrIntakeConfig,
)
from crt_radar.premarket_equity_live_snapshot import build_equity_source_binding
from test_ibkr_live_market_data_intake import (
    _capture, _premarket_ms, REGISTRY_PATH, OVERLAY_PATH, CONTRACT_PATH,
)
from test_premarket_evidence_binding import _fact, _overlay


def envelope(asset="MSTR"):
    return {
        **build_diluted_equity_mnav(
            asset_id=asset, diluted_equity_market_cap_usd=800,
            asset_nav_usd=1000, semantic_ref="FORMAL_CRT",
            evidence_alignment_state="VALIDATED",
        ),
        "provenance": {"source_refs": [{"evidence_hash": "a" * 64}]},
        "as_of": "2026-08-28T12:15:00Z",
    }


class AssetFactClosureTests(unittest.TestCase):
    def test_formal_envelope_preserved_and_detached(self):
        original = envelope()
        result = build_premarket_evidence_binding(
            reflexivity_overlay=None, mnav_results={"MSTR": original},
        )["asset_facts"]["MSTR"]["diluted_mnav"]
        self.assertEqual(result, original)
        result["provenance"].clear()
        self.assertTrue(original["provenance"])

    def test_malformed_formal_envelopes_fail_closed(self):
        for key, bad in [("asset_id", "ASST"), ("schema_version", "unknown"),
                         ("semantic_ref", ""), ("evidence_alignment_state", "UNKNOWN"),
                         ("mnav", float("nan")), ("mnav", -1), ("mnav", True),
                         ("action_output", "BUY"), ("external_action_performed", True)]:
            with self.subTest(key=key, bad=bad):
                value = {**envelope(), key: bad}
                result = build_premarket_evidence_binding(
                    reflexivity_overlay=None, mnav_results={"MSTR": value},
                )["asset_facts"]["MSTR"]["diluted_mnav"]
                self.assertEqual(result["state"], "BLOCKED")
                self.assertIsNone(result["mnav"])

    def test_blocked_mnav_keeps_diagnostics_without_numeric_display(self):
        value = {**envelope(), "state": "BLOCKED", "reason": "SOURCE_STALE"}
        result = build_premarket_evidence_binding(
            reflexivity_overlay=None, mnav_results={"MSTR": value},
        )["asset_facts"]["MSTR"]["diluted_mnav"]
        self.assertEqual(result["provenance"], value["provenance"])
        self.assertEqual(result["reason"], "SOURCE_STALE")
        self.assertIsNone(result["mnav"])

    def test_claim_scoping_retains_valid_fact_and_global_blockers(self):
        item = _fact("btc", "issuer", "security", "BTC", 100, 1, "hash")
        base = _overlay([item])
        base["asset_facts"]["section_state"] = "BLOCKED"
        for scope, affected, expected in [
            ("CALCULATION", ["unrelated-calc"], "AVAILABLE"),
            ("FACT", ["other-fact"], "AVAILABLE"),
            ("FACT", ["btc"], "BLOCKED"),
            ("FACT", ["issuer"], "BLOCKED"),
            ("FACT", ["issuer_facts"], "BLOCKED"),
            ("OVERLAY", ["other"], "BLOCKED"),
            ("SOURCE_GATE", ["other"], "BLOCKED"),
            ("FACT", [], "BLOCKED"),
        ]:
            with self.subTest(scope=scope, affected=affected):
                base["blockers"] = {"items": [{"scope": scope, "affected_ids": affected}]}
                result = select_fact_history(base, fact_type="BTC", issuer_id="issuer", security_id="security")
                self.assertEqual(result["state"], expected)

    def test_ibkr_to_battle_map_core_ready_supporting_blocked(self):
        registry = load_ibkr_source_registry(REGISTRY_PATH, OVERLAY_PATH)
        snapshot = build_ibkr_equity_live_snapshot(
            _capture(), source_binding=build_equity_source_binding(registry, source_id=SOURCE_ID),
            retrieved_at_ms=_premarket_ms() + 1000, config=IbkrIntakeConfig(),
        )
        items = []
        for asset, issuer in [("MSTR", "CIK-0001050446"), ("ASST", "CIK-0001920406")]:
            items.extend([
                _fact(asset + "btc", issuer, asset, "BTC_HOLDINGS", 100, 1, "hash"),
                _fact(asset + "shares", issuer, asset, "DILUTED_SHARES", 10, 1, "hash"),
            ])
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        kwargs = dict(registry=registry, battle_map_contract=contract,
                      evidence_pack={**_overlay(items), "action_output": "NONE",
                                     "authority": {"external_action_authority": "NONE",
                                                   "external_action_performed": False}},
                      mnav_results={a: envelope(a) for a in ("MSTR", "ASST")})
        battle = build_ibkr_crt_outputs(snapshot, **kwargs)["battle_map"]
        for asset in ("MSTR", "ASST"):
            self.assertEqual(battle["asset_fact_readiness"][asset]["state"], "AVAILABLE")
            self.assertEqual(battle["supporting_fact_readiness"][asset]["state"], "BLOCKED")
            self.assertEqual(battle["asset_facts"][asset]["diluted_mnav"], envelope(asset))
        for field in contract["required_facts"]["MSTR"]:
            from crt_radar.premarket_battle_map import build_premarket_battle_map
            facts = deepcopy(battle["asset_facts"])
            facts["MSTR"][field] = {"state": "BLOCKED"}
            result = build_premarket_battle_map(contract=contract, asset_facts=facts,
                issuer_reflexivity=None, as_of=None, source_mode="MACHINE_VERIFIED_ONLY")
            self.assertEqual(result["asset_fact_readiness"]["MSTR"]["state"], "BLOCKED")
