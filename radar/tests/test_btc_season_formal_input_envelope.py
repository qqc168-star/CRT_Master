from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


RADAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR_ROOT / "src"))

from crt_radar import btc_season_formal_input_envelope as formal_input


NOW_MS = 1_787_342_400_000


class BtcSeasonFormalInputEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = formal_input.load_contract()

    def _row(self, family_id: str, **changes):
        row = {
            "family_id": family_id,
            "binding_status": "UNBOUND_BLOCKED",
            "source_id": None,
            "source_registry_hash": formal_input.EXPECTED_REGISTRY_CANONICAL_SHA256,
            "observed_at_ms": NOW_MS - 60_000,
            "available_at_ms": NOW_MS - 30_000,
            "window_start_ms": NOW_MS - 86_400_000,
            "window_end_ms": NOW_MS - 60_000,
            "quality_state": "Q2",
            "freshness_state": "FRESH",
            "crossed_material_event_ids": [],
        }
        row.update(changes)
        return row

    def _envelope(self):
        return {
            "schema_version": "CRT_BTC_SEASON_FORMAL_INPUT_ENVELOPE_V0.1",
            "envelope_id": "sample-envelope",
            "as_of_ms": NOW_MS,
            "decision_event_id": "decision-event-1",
            "source_registry_id": "CRT-RADAR-SOURCE-REGISTRY-V1.4-WIP",
            "source_registry_hash": formal_input.EXPECTED_REGISTRY_CANONICAL_SHA256,
            "inputs": [self._row(x) for x in sorted(formal_input.EXPECTED_FAMILY_IDS)],
        }

    def _evaluate(self, envelope, contract=None, **kwargs):
        return formal_input.evaluate_envelope(
            envelope,
            contract,
            now_ms=NOW_MS,
            **kwargs,
        )

    def test_candidate_contract_and_pinned_authorities_validate(self):
        self.assertEqual(formal_input.validate_contract(self.contract), [])
        self.assertEqual(
            formal_input.canonical_hash(self.contract),
            formal_input.EXPECTED_CONTRACT_CANONICAL_SHA256,
        )
        self.assertEqual(
            {row["family_id"] for row in self.contract["required_family_bindings"]},
            formal_input.EXPECTED_FAMILY_IDS,
        )
        self.assertTrue(
            all(
                row["binding_status"] == "UNBOUND_BLOCKED"
                for row in self.contract["required_family_bindings"]
            )
        )

    def test_complete_shape_remains_unbound_and_cannot_emit_season(self):
        report = self._evaluate(self._envelope())
        self.assertEqual(report["state"], "UNBOUND_BLOCKED")
        self.assertEqual(report["contract_errors"], [])
        self.assertEqual(report["required_family_count"], 12)
        self.assertEqual(report["formally_bound_family_count"], 0)
        self.assertEqual(len(report["unbound_family_ids"]), 12)
        self.assertFalse(report["closes_unmapped_requirement"])
        self.assertFalse(report["runtime_binding_ready"])
        self.assertFalse(report["machine_may_determine_btc_season"])
        self.assertIsNone(report["season"])
        self.assertEqual(report["action_output"], "NONE")
        self.assertEqual(report["external_action_authority"], "NONE")

    def test_missing_family_and_fields_fail_closed(self):
        envelope = self._envelope()
        removed = envelope["inputs"].pop()
        del envelope["decision_event_id"]
        report = self._evaluate(envelope)
        self.assertIn("REQUIRED_FIELD_MISSING:decision_event_id", report["blocked_reasons"])
        self.assertIn(
            f"REQUIRED_FIELD_MISSING:FAMILY:{removed['family_id']}",
            report["blocked_reasons"],
        )
        self.assertIn(
            f"REQUIRED_FAMILY_UNBOUND:{removed['family_id']}",
            report["blocked_reasons"],
        )

    def test_stale_low_quality_and_registry_mismatch_fail_closed(self):
        envelope = self._envelope()
        row = envelope["inputs"][0]
        family_id = row["family_id"]
        row["freshness_state"] = "STALE"
        row["quality_state"] = "Q0"
        row["source_registry_hash"] = "0" * 64
        report = self._evaluate(envelope)
        self.assertIn(
            f"STALE_OR_UNKNOWN_FRESHNESS_BLOCK:{family_id}",
            report["blocked_reasons"],
        )
        self.assertIn(f"QUALITY_Q0_BLOCK:{family_id}", report["blocked_reasons"])
        self.assertIn(
            f"REQUIRED_GATE_QUALITY_Q1_OR_Q0_BLOCK:{family_id}",
            report["blocked_reasons"],
        )
        self.assertIn(
            f"SOURCE_REGISTRY_HASH_MISMATCH:{family_id}",
            report["blocked_reasons"],
        )

    def test_clock_order_future_and_window_fail_closed(self):
        envelope = self._envelope()
        first, second, third = envelope["inputs"][:3]
        first["observed_at_ms"] = NOW_MS - 10_000
        first["available_at_ms"] = NOW_MS - 20_000
        second["available_at_ms"] = NOW_MS + 1
        third["window_start_ms"] = NOW_MS
        third["window_end_ms"] = NOW_MS - 1
        report = self._evaluate(envelope)
        self.assertIn(
            f"OBSERVED_AFTER_AVAILABLE_BLOCK:{first['family_id']}",
            report["blocked_reasons"],
        )
        self.assertIn(
            f"AVAILABLE_AFTER_ENVELOPE_AS_OF_BLOCK:{second['family_id']}",
            report["blocked_reasons"],
        )
        self.assertIn(
            f"INVALID_OR_FUTURE_WINDOW_BLOCK:{third['family_id']}",
            report["blocked_reasons"],
        )

    def test_material_event_crossing_never_silently_aligns(self):
        envelope = self._envelope()
        row = envelope["inputs"][0]
        row["crossed_material_event_ids"] = ["FOMC-2026-08"]
        report = self._evaluate(envelope)
        self.assertIn(
            f"MATERIAL_EVENT_CLOCK_MISALIGNMENT_BLOCK:{row['family_id']}",
            report["blocked_reasons"],
        )

    def test_claimed_binding_requires_a_pinned_registry_source(self):
        envelope = self._envelope()
        row = envelope["inputs"][0]
        row["binding_status"] = "FORMALLY_BOUND"
        row["source_id"] = "INVENTED-SEASON-SOURCE"
        report = self._evaluate(envelope)
        self.assertIn(
            f"SOURCE_NOT_IN_PINNED_REGISTRY:{row['family_id']}",
            report["blocked_reasons"],
        )
        self.assertIn(
            f"REQUIRED_FAMILY_UNBOUND:{row['family_id']}",
            report["blocked_reasons"],
        )

    def test_envelope_identity_registry_id_and_future_as_of_fail_closed(self):
        envelope = self._envelope()
        envelope["schema_version"] = "invented"
        envelope["source_registry_id"] = "invented"
        envelope["decision_event_id"] = ""
        envelope["as_of_ms"] = NOW_MS + 301_000
        report = self._evaluate(envelope)
        self.assertIn("REQUIRED_FIELD_MISSING:schema_version", report["blocked_reasons"])
        self.assertIn("REQUIRED_FIELD_MISSING:decision_event_id", report["blocked_reasons"])
        self.assertIn(
            "SOURCE_REGISTRY_HASH_MISMATCH:REGISTRY_ID",
            report["blocked_reasons"],
        )
        self.assertIn("FUTURE_CLOCK_BLOCK:ENVELOPE", report["blocked_reasons"])

    def test_authority_runtime_or_research_escalation_invalidates_contract(self):
        changed = deepcopy(self.contract)
        changed["authority"]["runtime_binding"] = "APPROVED"
        changed["runtime_boundary"]["may_determine_btc_season"] = True
        changed["candidate_effect"]["closes_unmapped_requirement"] = True
        changed["research_firewall"]["research_may_supply_formal_binding"] = True
        errors = formal_input.validate_contract(changed)
        self.assertIn("formal input envelope authority boundary changed", errors)
        self.assertIn("formal input envelope runtime boundary changed", errors)
        self.assertIn("candidate may not close the unmapped requirement", errors)
        self.assertIn("research firewall changed", errors)

    def test_registry_byte_tampering_invalidates_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for relative in (
                "CONFIG/SOURCE_REGISTRY_V1.2.json",
                "CONFIG/BTC_SEASON_SEMANTIC_MAPPING_CANDIDATE_V0.1.1.json",
                "CONFIG/BTC_SEASON_SEMANTIC_MAPPING_HASH_APPROVAL_SEAL_V0.1.json",
            ):
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(RADAR_ROOT / relative, target)
            registry_path = temp_root / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["version"] = "tampered"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            errors = formal_input.validate_contract(
                self.contract,
                radar_root=temp_root,
            )
        self.assertIn("pinned engineering registry canonical hash changed", errors)
        self.assertIn("pinned engineering registry file hash changed", errors)

    def test_current_runtime_does_not_import_candidate(self):
        importing_files = []
        for path in sorted((RADAR_ROOT / "src" / "crt_radar").glob("*.py")):
            if path.name == "btc_season_formal_input_envelope.py":
                continue
            if "btc_season_formal_input_envelope" in path.read_text(encoding="utf-8"):
                importing_files.append(path.name)
        self.assertEqual(importing_files, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
