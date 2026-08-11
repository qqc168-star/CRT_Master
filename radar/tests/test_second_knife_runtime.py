from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.observation_store import ObservationStore
from crt_radar.runtime_freshness import apply_runtime_checks, assess_file_freshness


NOW_MS = 1_800_000_000_000
REGISTRY_HASH = "a" * 64


def h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def valid_gate() -> dict:
    parsed = {
        "DOLLAR_STRENGTH_PROXY": {"as_of_ms": NOW_MS, "value": 120.0},
        "OPEN_INTEREST": {"as_of_ms": NOW_MS, "open_interest_contracts": 10_000.0},
        "FUNDING_RATE": {
            "as_of_ms": NOW_MS,
            "funding_rate": 0.0001,
            "mark_price": 65_000.0,
        },
        "LIQUIDATION_AGGREGATES": {
            "as_of_ms": NOW_MS,
            "coverage_ratio": 1.0,
            "windows": {
                "1h": {
                    "long_liquidation_usd": 100.0,
                    "short_liquidation_usd": 50.0,
                    "total_liquidation_usd": 150.0,
                    "event_count": 2,
                },
                "24h": {
                    "long_liquidation_usd": 1000.0,
                    "short_liquidation_usd": 500.0,
                    "total_liquidation_usd": 1500.0,
                    "event_count": 20,
                },
            },
        },
    }
    qualities = {
        "DOLLAR_STRENGTH_PROXY": ("AS-L2", "VALID_FRESH"),
        "OPEN_INTEREST": ("AS-L4", "VALID_FRESH"),
        "FUNDING_RATE": ("AS-L4", "VALID_FRESH"),
        "LIQUIDATION_AGGREGATES": ("AS-L4", "VALID_FRESH_COMPLETE_COVERAGE"),
    }
    evidence = []
    for family, (namespace, quality) in qualities.items():
        evidence.append(
            {
                "source_id": f"SRC-{family}",
                "namespace": namespace,
                "input_family": family,
                "quality_state": quality,
                "transport_status": "OK",
                "as_of_ms": NOW_MS,
                "evidence_hash": h(f"evidence:{family}"),
                "registry_hash": REGISTRY_HASH,
                "quality_error": None,
            }
        )
    return {
        "run_id": "second-knife-run",
        "idempotency_key": h("second-knife-run"),
        "as_of_ms": NOW_MS,
        "formal_state": "OBSERVATION_ONLY",
        "blocked_reasons": [],
        "source_registry_hash": REGISTRY_HASH,
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "evidence": evidence,
        "parsed": parsed,
    }


class RuntimeFreshnessTests(unittest.TestCase):
    def test_file_freshness_reports_fresh_stale_missing_and_clock_skew(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "latest.json"

            missing = assess_file_freshness(path, max_age_seconds=300, now_ms=NOW_MS)
            self.assertEqual(missing["state"], "MISSING")
            self.assertEqual(missing["blocker"], "PHONE_L4_MISSING")

            path.write_text("{}", encoding="utf-8")
            fresh_ms = NOW_MS - 60_000
            os.utime(path, ns=(fresh_ms * 1_000_000, fresh_ms * 1_000_000))
            fresh = assess_file_freshness(path, max_age_seconds=300, now_ms=NOW_MS)
            self.assertEqual(fresh["state"], "FRESH")
            self.assertIsNone(fresh["blocker"])

            stale_ms = NOW_MS - 301_000
            os.utime(path, ns=(stale_ms * 1_000_000, stale_ms * 1_000_000))
            stale = assess_file_freshness(path, max_age_seconds=300, now_ms=NOW_MS)
            self.assertEqual(stale["state"], "STALE")
            self.assertEqual(stale["blocker"], "PHONE_L4_STALE")

            future_ms = NOW_MS + 301_000
            os.utime(path, ns=(future_ms * 1_000_000, future_ms * 1_000_000))
            skew = assess_file_freshness(path, max_age_seconds=300, now_ms=NOW_MS)
            self.assertEqual(skew["state"], "CLOCK_SKEW")
            self.assertEqual(skew["blocker"], "PHONE_L4_CLOCK_SKEW")

    def test_runtime_stale_blocks_pack_but_valid_observations_still_accumulate(self):
        gate = apply_runtime_checks(
            valid_gate(),
            [
                {
                    "check_id": "PHONE_L4_FILE_FRESHNESS",
                    "state": "STALE",
                    "blocker": "PHONE_L4_STALE",
                    "authority": "TRANSPORT_ONLY",
                    "metric_authority": "NONE",
                    "external_action_authority": "NONE",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "observations.sqlite3"
            pack = build_evidence_pack(gate, observation_db=db_path, generated_at_ms=NOW_MS)
            with ObservationStore(db_path) as store:
                count = store.count()

        self.assertEqual(pack["pack_state"], "BLOCKED")
        self.assertIn("PHONE_L4_STALE", pack["data_health"]["critical_blockers"])
        self.assertEqual(pack["data_health"]["runtime_checks"][0]["state"], "STALE")
        self.assertGreater(count, 0)

    def test_fresh_runtime_check_does_not_create_blocker(self):
        gate = apply_runtime_checks(
            valid_gate(),
            [
                {
                    "check_id": "PHONE_L4_FILE_FRESHNESS",
                    "state": "FRESH",
                    "blocker": None,
                    "authority": "TRANSPORT_ONLY",
                    "metric_authority": "NONE",
                    "external_action_authority": "NONE",
                }
            ],
        )
        self.assertEqual(gate["formal_state"], "OBSERVATION_ONLY")
        self.assertEqual(gate["blocked_reasons"], [])


    def test_runtime_check_rejects_authority_escalation(self):
        base = {
            "check_id": "PHONE_L4_FILE_FRESHNESS",
            "state": "FRESH",
            "blocker": None,
            "authority": "TRANSPORT_ONLY",
            "metric_authority": "NONE",
            "external_action_authority": "NONE",
        }
        mutations = [
            ("authority", "MODEL"),
            ("metric_authority", "SCORE"),
            ("external_action_authority", "TRADE"),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                check = dict(base)
                check[field] = value
                with self.assertRaises(ValueError):
                    apply_runtime_checks(valid_gate(), [check])

    def test_fresh_transport_cannot_clear_existing_source_blocker_or_store_stale_family(self):
        source_gate = valid_gate()
        source_gate["formal_state"] = "BLOCKED"
        source_gate["blocked_reasons"] = ["LIQUIDATION_AGGREGATES_STALE"]
        for row in source_gate["evidence"]:
            if row["input_family"] == "LIQUIDATION_AGGREGATES":
                row["quality_state"] = "STALE"
                row["quality_error"] = "StaleData: source exceeds freshness policy"

        checked = apply_runtime_checks(
            source_gate,
            [
                {
                    "check_id": "PHONE_L4_FILE_FRESHNESS",
                    "state": "FRESH",
                    "blocker": None,
                    "authority": "TRANSPORT_ONLY",
                    "metric_authority": "NONE",
                    "external_action_authority": "NONE",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "observations.sqlite3"
            pack = build_evidence_pack(checked, observation_db=db_path, generated_at_ms=NOW_MS)
            with ObservationStore(db_path) as store:
                liq_rows = store.series("LIQUIDATION_AGGREGATES", "liquidation_1h_total_usd")
                other_count = store.count()

        self.assertEqual(pack["pack_state"], "BLOCKED")
        self.assertIn("LIQUIDATION_AGGREGATES_STALE", pack["data_health"]["critical_blockers"])
        self.assertEqual(liq_rows, [])
        self.assertGreater(other_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
