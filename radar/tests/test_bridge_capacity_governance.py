from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import crt_radar.gpt_handoff as gh
from crt_radar.gpt_transport_worker import validate_transport_payload
from crt_radar.openai_responses_adapter_contract import (
    MAX_INPUT_UTF8_BYTES, SMOKE_MODEL, build_request_envelope,
)
from test_bridge_source_refs import make
from test_full_bridge_budget import (
    captured_pack, bind_pack, handoff_for,
)

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "CRT_BRIDGE_CAPACITY_AND_DEDUP_DOCTRINE_V0.1.md"

def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

def full_wire():
    pack = captured_pack()
    original = make()["market_context"]["premarket_market_data"]
    pack["premarket_market_data"] = deepcopy(original)
    bind_pack(pack)
    with tempfile.TemporaryDirectory() as td:
        h = handoff_for(pack, Path(td))
        # Test-only capacity oracle; no production changes.
        with patch.object(gh, "BRIDGE_CEILING_BYTES", 10**9):
            wire = gh.build_minimized_bridge_payload(pack, h)
    return pack, wire

class BridgeCapacityGovernanceTests(unittest.TestCase):
    def test_dedup_identity_and_roundtrip(self):
        original = make()
        compact = deepcopy(original)
        gh._compact_premarket_refs(compact)
        self.assertLess(len(encoded(compact)), len(encoded(original)))
        handoff = compact["market_context"][
            "premarket_market_data"]["live_market_handoff"]
        self.assertEqual(
            sum(
                "bridge_source_families"
                in x.get("available_source_families", {})
                for x in handoff["analysis_inputs"].values()
            ), 5
        )
        gh._restore_premarket_refs(compact)
        compact["market_context"].pop("premarket_ref_encoding", None)
        self.assertEqual(encoded(compact), encoded(original))

    def test_actual_wire_has_no_large_exact_duplicate(self):
        pack, wire = full_wire()
        self.assertEqual(
            gh.expand_bridge_field_names(wire)["market_context"][
                "premarket_market_data"
            ],
            pack["premarket_market_data"],
        )
        groups = defaultdict(int)
        def visit(v):
            if not isinstance(v, (dict, list)):
                return
            material = encoded(v)
            if len(material) >= 256:
                groups[hashlib.sha256(material).hexdigest()] += 1
            if isinstance(v, dict):
                for child in v.values():
                    visit(child)
            else:
                for child in v:
                    visit(child)
        visit(wire)
        self.assertFalse([v for v in groups.values() if v > 1])

    def test_smoke_cap_remains_and_rejects_full_example(self):
        self.assertEqual(gh.BRIDGE_CEILING_BYTES, 16 * 1024)
        self.assertEqual(MAX_INPUT_UTF8_BYTES, 16 * 1024)
        pack, wire = full_wire()
        self.assertEqual(
            wire["event"]["source_evidence_pack_hash"],
            pack["evidence_pack_hash"],
        )
        self.assertGreater(len(encoded(wire)), 16 * 1024)
        # Structural/privacy validation is NOT request acceptance.
        validate_transport_payload(wire)
        with self.assertRaisesRegex(ValueError, "byte ceiling"):
            build_request_envelope(wire, model=SMOKE_MODEL)

    def test_contract_is_boot_discoverable(self):
        doctrine = DOC.read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(DOC.name, readme)
        for text in (
            "Horizontal copying", "Vertical nesting",
            "Source fanout", "Budget inversion",
            "16,384 UTF-8 bytes",
            "receiver comprehension",
            "NOT_YET_PROVEN",
            "Production NOT_APPROVED",
            "External Action Authority",
        ):
            self.assertIn(text, doctrine)
