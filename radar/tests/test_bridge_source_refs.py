
import unittest
from copy import deepcopy

from crt_radar.gpt_handoff import (
    _compact_premarket_refs,
    _restore_premarket_refs,
)
from test_premarket_live_market_handoff import (
    CONTRACT, _source_gate, _observations,
)
from crt_radar.premarket_live_market_handoff import (
    build_premarket_live_market_handoff,
    apply_live_market_handoff_to_asset_facts,
)
from crt_radar.premarket_battle_map import build_premarket_battle_map
from crt_radar.evidence_pack import _premarket_market_data_surface

def make():
    h = build_premarket_live_market_handoff(
        source_mode="MANUAL_WEB_SUPPLEMENT",
        evaluation_window={"start_ms":100,"end_ms":200},
        source_gate_result=_source_gate(),
        manual_asset_observations=_observations(),
    )
    b = build_premarket_battle_map(
        contract=CONTRACT,
        asset_facts=apply_live_market_handoff_to_asset_facts({},h),
        issuer_reflexivity={
            "state":"VALID",
            "event_state":"NO_NEW_MATERIAL_ISSUER_EVENT",
        },
        as_of="2026-09-06T16:00:00+08:00",
        source_mode="MANUAL_WEB_SUPPLEMENT",
        live_market_handoff=h,
    )
    return {"market_context":{"premarket_market_data":
        _premarket_market_data_surface(
            live_market_handoff=h,battle_map=b
        )
    }}

def restore(x):
    _restore_premarket_refs(x)
    x["market_context"].pop("premarket_ref_encoding",None)

class BridgeSourceRefsTests(unittest.TestCase):
    def test_exact_roundtrip(self):
        x=make()
        before=deepcopy(x)
        _compact_premarket_refs(x)
        h=x["market_context"]["premarket_market_data"][
            "live_market_handoff"]
        self.assertTrue(any(
            "bridge_source_families"
            in r["available_source_families"]
            for r in h["analysis_inputs"].values()
        ))
        restore(x)
        self.assertEqual(x,before)

    def test_conflicting_value_not_merged(self):
        x=make()
        row=x["market_context"]["premarket_market_data"][
            "live_market_handoff"]["analysis_inputs"][
            "PRICE_STRUCTURE"]["available_source_families"]
        row["BTC_SPOT_PRICE"]["spot_price_usd"]=123456
        before=deepcopy(x)
        _compact_premarket_refs(x)
        self.assertNotIn("bridge_source_families",
            x["market_context"]["premarket_market_data"][
            "live_market_handoff"]["analysis_inputs"][
            "PRICE_STRUCTURE"]["available_source_families"])
        restore(x)
        self.assertEqual(x,before)

    def test_broken_reference_rejected(self):
        x=make()
        _compact_premarket_refs(x)
        row=x["market_context"]["premarket_market_data"][
            "live_market_handoff"]["analysis_inputs"][
            "PRICE_STRUCTURE"]
        row["available_source_families"]={
            "bridge_source_families":["NO_SOURCE"]
        }
        with self.assertRaises(ValueError):
            _restore_premarket_refs(x)

    def test_input_unchanged(self):
        x=make()
        original=deepcopy(x)
        y=deepcopy(x)
        _compact_premarket_refs(y)
        self.assertEqual(x,original)
