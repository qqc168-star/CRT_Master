from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.observation_store import ObservationStore, extract_observations


DAY_MS = 86_400_000
BASE_MS = 1_786_000_000_000
REGISTRY_HASH = "a" * 64


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def gate(day: int, *, blocked: bool = False, onchain_ok: bool = True) -> dict:
    now = BASE_MS + day * DAY_MS
    rows = []
    parsed = {}

    def add(family: str, namespace: str, quality: str, values: dict | None):
        rows.append(
            {
                "source_id": f"SRC-{family}",
                "namespace": namespace,
                "input_family": family,
                "quality_state": quality,
                "transport_status": "OK" if quality.startswith("VALID") else "ERROR",
                "as_of_ms": values.get("as_of_ms") if values else None,
                "evidence_hash": h(f"{day}:{family}:{quality}"),
                "registry_hash": REGISTRY_HASH,
                "quality_error": None if quality.startswith("VALID") else "synthetic outage",
            }
        )
        if values is not None:
            parsed[family] = values

    add("DOLLAR_STRENGTH_PROXY", "AS-L2", "VALID_FRESH", {"as_of_ms": now, "value": 100 + day * 0.2})
    add("OPEN_INTEREST", "AS-L4", "VALID_FRESH", {"as_of_ms": now, "open_interest_contracts": 10_000 + day * 50})
    add("FUNDING_RATE", "AS-L4", "VALID_FRESH", {"as_of_ms": now, "funding_rate": 0.00005 + day * 0.000001, "mark_price": 60_000 + day * 100})
    add(
        "LIQUIDATION_AGGREGATES",
        "AS-L4",
        "VALID_FRESH_COMPLETE_COVERAGE",
        {
            "as_of_ms": now,
            "coverage_ratio": 1.0,
            "windows": {
                "1h": {"long_liquidation_usd": 100 + day, "short_liquidation_usd": 50 + day, "total_liquidation_usd": 150 + day * 2, "event_count": 2 + day},
                "24h": {"long_liquidation_usd": 1000 + day * 10, "short_liquidation_usd": 500 + day * 5, "total_liquidation_usd": 1500 + day * 15, "event_count": 20 + day},
            },
        },
    )
    if onchain_ok:
        add(
            "ONCHAIN_VALUE",
            "AS-L5",
            "VALID_FRESH",
            {
                "as_of_ms": now,
                "market_cap_usd": 1_200_000_000_000 + day * 1_000_000_000,
                "realized_cap_usd": 600_000_000_000 + day * 500_000_000,
                "mvrv": 2.0 + day * 0.01,
                "nupl": 0.5 + day * 0.001,
            },
        )
    else:
        add("ONCHAIN_VALUE", "AS-L5", "TRANSPORT_ERROR", None)

    blocked_reasons = ["OPEN_INTEREST_TRANSPORT_ERROR"] if blocked else []
    formal_state = "BLOCKED" if blocked else "OBSERVATION_ONLY"
    if blocked:
        oi = next(r for r in rows if r["input_family"] == "OPEN_INTEREST")
        oi["quality_state"] = "TRANSPORT_ERROR"
        oi["transport_status"] = "ERROR"
        oi["quality_error"] = "timeout"
        parsed.pop("OPEN_INTEREST", None)

    return {
        "run_id": f"run-{day}",
        "idempotency_key": h(f"run:{day}:{blocked}:{onchain_ok}"),
        "as_of_ms": now,
        "formal_state": formal_state,
        "blocked_reasons": blocked_reasons,
        "source_registry_hash": REGISTRY_HASH,
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "evidence": rows,
        "parsed": parsed,
    }


class FirstEvidenceSliceTests(unittest.TestCase):
    def test_observation_store_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "obs.sqlite3"
            obs = extract_observations(gate(0), recorded_at_ms=BASE_MS)
            with ObservationStore(path) as store:
                first = store.record(obs)
                count1 = store.count()
                second = store.record(obs)
                count2 = store.count()
            self.assertGreater(first, 0)
            self.assertEqual(second, 0)
            self.assertEqual(count1, count2)

    def test_first_run_is_partial_without_history(self):
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(gate(0), observation_db=Path(td) / "obs.sqlite3", generated_at_ms=BASE_MS)
            self.assertEqual(pack["pack_state"], "PARTIAL_FOR_ANALYST")
            self.assertEqual(pack["changes"]["open_interest_contracts"]["horizons"]["1d"]["history_state"], "INSUFFICIENT_HISTORY")

    def test_contract_surface_is_explicitly_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(
                gate(0),
                observation_db=Path(td) / "obs.sqlite3",
                generated_at_ms=BASE_MS,
            )
        self.assertEqual(pack["schema_version"], "CRT_EVIDENCE_PACK_V0.2")
        self.assertEqual(pack["action_output"], "NONE")
        self.assertEqual(pack["asset_facts"]["section_state"], "BLOCKED")
        self.assertEqual(pack["asset_facts"]["reason_code"], "REFLEXIVITY_INPUT_MISSING")
        self.assertEqual(pack["asset_facts"]["items"], [])
        self.assertNotIn("empty_reason", pack["asset_facts"])
        self.assertEqual(pack["decision_relevant_events"]["section_state"], "BLOCKED")
        self.assertEqual(pack["decision_relevant_events"]["items"], [])
        self.assertEqual(pack["blockers"]["section_state"], "BLOCKED")
        self.assertEqual(
            {item["reason_code"] for item in pack["blockers"]["items"]},
            {"REFLEXIVITY_INPUT_MISSING"},
        )
        self.assertEqual(pack["pack_state"], "PARTIAL_FOR_ANALYST")

    def test_history_enables_1d_7d_30d_changes(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "obs.sqlite3"
            for day in range(31):
                build_evidence_pack(gate(day), observation_db=db, generated_at_ms=BASE_MS + day * DAY_MS)
            pack = build_evidence_pack(gate(31), observation_db=db, generated_at_ms=BASE_MS + 31 * DAY_MS)
            horizons = pack["changes"]["open_interest_contracts"]["horizons"]
            self.assertEqual(horizons["1d"]["history_state"], "AVAILABLE")
            self.assertEqual(horizons["7d"]["history_state"], "AVAILABLE")
            self.assertEqual(horizons["30d"]["history_state"], "AVAILABLE")
            self.assertEqual(pack["pack_state"], "READY_FOR_ANALYST")
            self.assertLessEqual(len(pack["distillation"]["top_changes"]), 8)

    def test_blocked_source_gate_propagates(self):
        source_gate = gate(0, blocked=True)
        source_gate["blocked_reasons"] = [
            "Z_SOURCE_GATE_BLOCKER",
            "OPEN_INTEREST_TRANSPORT_ERROR",
            "A_SOURCE_GATE_BLOCKER",
            "OPEN_INTEREST_TRANSPORT_ERROR",
        ]
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(
                source_gate,
                observation_db=Path(td) / "obs.sqlite3",
                generated_at_ms=BASE_MS,
            )
            self.assertEqual(pack["pack_state"], "BLOCKED")
            self.assertIn("OPEN_INTEREST_TRANSPORT_ERROR", pack["data_health"]["critical_blockers"])
            self.assertEqual(pack["blockers"]["section_state"], "BLOCKED")
            source_gate_codes = [
                item["reason_code"]
                for item in pack["blockers"]["items"]
                if item["scope"] == "SOURCE_GATE"
            ]
            self.assertEqual(
                source_gate_codes,
                [
                    "A_SOURCE_GATE_BLOCKER",
                    "OPEN_INTEREST_TRANSPORT_ERROR",
                    "Z_SOURCE_GATE_BLOCKER",
                ],
            )
            self.assertIn(
                "REFLEXIVITY_INPUT_MISSING",
                {item["reason_code"] for item in pack["blockers"]["items"]},
            )

    def test_noncritical_onchain_failure_is_partial_not_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(gate(0, onchain_ok=False), observation_db=Path(td) / "obs.sqlite3", generated_at_ms=BASE_MS)
            self.assertEqual(pack["pack_state"], "PARTIAL_FOR_ANALYST")
            self.assertNotIn("L5", pack["layers"])

    def test_automation_never_fills_analyst_judgment(self):
        with tempfile.TemporaryDirectory() as td:
            pack = build_evidence_pack(gate(0), observation_db=Path(td) / "obs.sqlite3", generated_at_ms=BASE_MS)
            self.assertEqual(pack["action_output"], "NONE")
            self.assertEqual(pack["authority"]["external_action_authority"], "NONE")
            self.assertFalse(pack["authority"]["external_action_performed"])
            self.assertTrue(pack["authority"]["analyst_judgment_required"])
            self.assertTrue(all(value is None for value in pack["analyst_output"].values()))
            self.assertEqual(pack["distillation"]["formal_extremes"], [])
            self.assertEqual(pack["distillation"]["divergences"], [])

    def test_same_evidence_and_history_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "obs.sqlite3"
            for day in range(10):
                build_evidence_pack(gate(day), observation_db=db, generated_at_ms=BASE_MS + day * DAY_MS)
            a = build_evidence_pack(gate(10), observation_db=db, generated_at_ms=BASE_MS + 10 * DAY_MS)
            b = build_evidence_pack(gate(10), observation_db=db, generated_at_ms=BASE_MS + 10 * DAY_MS)
            self.assertEqual(a["evidence_pack_hash"], b["evidence_pack_hash"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
