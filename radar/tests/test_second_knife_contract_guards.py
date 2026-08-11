from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.observation_store import extract_observations
from crt_radar.runtime_freshness import apply_runtime_checks


REGISTRY_PATH = ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"
REGISTRY_HASH = "a" * 64
NOW_MS = 1_800_000_000_000


def gate_with_mixed_quality() -> dict:
    return {
        "run_id": "guard-run",
        "idempotency_key": "b" * 64,
        "as_of_ms": NOW_MS,
        "formal_state": "BLOCKED",
        "blocked_reasons": ["OPEN_INTEREST_STALE"],
        "source_registry_hash": REGISTRY_HASH,
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "evidence": [
            {
                "source_id": "SRC-OI",
                "namespace": "AS-L4",
                "input_family": "OPEN_INTEREST",
                "quality_state": "STALE",
                "transport_status": "OK",
                "as_of_ms": NOW_MS,
                "evidence_hash": "c" * 64,
                "registry_hash": REGISTRY_HASH,
                "quality_error": "StaleData: source exceeds freshness policy",
            },
            {
                "source_id": "SRC-FUNDING",
                "namespace": "AS-L4",
                "input_family": "FUNDING_RATE",
                "quality_state": "VALID_FRESH",
                "transport_status": "OK",
                "as_of_ms": NOW_MS,
                "evidence_hash": "d" * 64,
                "registry_hash": REGISTRY_HASH,
                "quality_error": None,
            },
        ],
        "parsed": {
            # Deliberately leave a parsed value behind for stale OI to prove
            # Observation History is gated by evidence quality, not by parsed presence.
            "OPEN_INTEREST": {
                "as_of_ms": NOW_MS,
                "open_interest_contracts": 10000.0,
            },
            "FUNDING_RATE": {
                "as_of_ms": NOW_MS,
                "funding_rate": 0.0001,
                "mark_price": 65000.0,
            },
        },
    }


class SecondKnifeContractGuardTests(unittest.TestCase):
    def test_blocked_evidence_is_not_laundered_into_observation_history(self):
        observations = extract_observations(gate_with_mixed_quality(), recorded_at_ms=NOW_MS)
        families = {item.input_family for item in observations}
        metrics = {item.metric for item in observations}
        self.assertNotIn("OPEN_INTEREST", families)
        self.assertNotIn("open_interest_contracts", metrics)
        self.assertIn("FUNDING_RATE", families)
        self.assertIn("funding_rate", metrics)

    def test_mobile_l4_check_is_transport_only_and_cannot_change_evidence_quality(self):
        gate = gate_with_mixed_quality()
        original_evidence = gate["evidence"]
        original_parsed = gate["parsed"]
        result = apply_runtime_checks(
            gate,
            [{
                "check_id": "PHONE_L4_FILE_FRESHNESS",
                "state": "STALE",
                "blocker": "PHONE_L4_STALE",
                "authority": "TRANSPORT_ONLY",
                "metric_authority": "NONE",
                "external_action_authority": "NONE",
            }],
        )
        self.assertEqual(result["evidence"], original_evidence)
        self.assertEqual(result["parsed"], original_parsed)
        self.assertEqual(result["formal_state"], "BLOCKED")
        self.assertIn("PHONE_L4_STALE", result["blocked_reasons"])

    def test_dollar_proxy_policy_is_unchanged_and_fail_closed(self):
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        dollar = next(
            item for item in payload["sources"]
            if item["input_family"] == "DOLLAR_STRENGTH_PROXY"
        )
        self.assertEqual(dollar["source_id"], "CRT-CONN-FX-FRED-BROAD-USD-PROXY-001")
        self.assertEqual(
            dollar["endpoint"],
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS",
        )
        self.assertEqual(dollar["criticality"], "CRITICAL_FAIL_CLOSED")
        self.assertEqual(dollar["max_age_seconds"], 864000)
        self.assertEqual(payload["external_action_authority"], "NONE")

    def test_operational_defaults_do_not_mutate_registry_thresholds(self):
        runner = (ROOT / "src" / "crt_radar" / "daily_evidence_runner.py").read_text(encoding="utf-8")
        installer = (
            ROOT / "scripts" / "windows" / "install_observation_history_task_windows.ps1"
        ).read_text(encoding="utf-8")
        operations = (ROOT / "OPERATIONS.md").read_text(encoding="utf-8")

        self.assertIn('default=300', runner)
        self.assertIn('[int]$IntervalMinutes = 60', installer)
        self.assertIn('60 分鐘，只屬於 Operational Default（營運預設值）', operations)
        self.assertIn('預設 300 秒只屬於 Operational Default（營運預設值）', operations)


    def test_bootloader_persists_language_and_simple_workflow_rules(self):
        readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("User-facing Language Rule（對使用者語言規則）", readme)
        self.assertIn("新聊天室必須從 current `main`（目前主分支）恢復此規則", readme)
        self.assertIn("`Branch / Commit / PR`（分支／提交／合併請求）", readme)
        self.assertIn("`Simplicity first`（簡單優先）", readme)
        self.assertIn("`HTTP 403`（拒絕寫入）", readme)



if __name__ == "__main__":
    unittest.main(verbosity=2)
