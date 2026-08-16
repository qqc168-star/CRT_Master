from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.maturity_tracker import record_maturity_attempt
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.private_profile import PrivateProfileError, load_private_profile, validate_private_profile
from crt_radar.source_gate_runner import parse_coinmetrics_caps


def private_payload() -> dict:
    return {
        "schema_version": "CRT_PRIVATE_PORTFOLIO_V1",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "action_output": "NONE",
        "strc": {
            "shares": 100,
            "distribution_rate_mode": "DYNAMIC_LOCAL_VALUE",
            "current_annual_distribution_rate": 0.10,
            "stated_amount_usd": 100,
            "tax_treatment": "RETURN_OF_CAPITAL",
            "withholding_rate": 0,
        },
        "cash_goal": {
            "six_month_target_usd": 500,
            "fixed_minimum_shares": 100,
        },
    }


def blocked_pack(private_context: dict | None = None) -> dict:
    return {
        "evidence_pack_hash": "a" * 64,
        "pack_state": "BLOCKED",
        "authority": {
            "external_action_authority": "NONE",
            "external_action_performed": False,
        },
        "data_health": {"critical_blockers": ["LIQUIDATION_AGGREGATES_STALE"]},
        "distillation": {"top_changes": []},
        "model_status": {
            "six_layer_evidence": {
                "state": "BLOCKED",
                "blocked_reasons": ["L3_SPOT_BTC_ETP_FLOW_MISSING"],
            },
            "locked_formal_scoring": {
                "state": "BLOCKED",
                "reason": "LOCKED_FORMAL_SCORING_EXECUTABLE_UNAVAILABLE_IN_CURRENT_MAIN",
            },
            "btc_season_router": {
                "state": "BLOCKED",
                "reason": "BTC_SEASON_ROUTER_EXECUTABLE_UNAVAILABLE_IN_CURRENT_MAIN",
            },
        },
        "reanalysis_wake": {
            "state": "REANALYSIS_REQUESTED",
            "reason": "MATERIAL_CHANGE_RELATIVE_TO_INTRADAY_HISTORY",
            "percent_change": -8.5,
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        },
        "private_context": private_context,
    }


class OperationalLoopTests(unittest.TestCase):
    def test_windows_liquidation_collector_defaults_to_continuous_duty(self):
        runner = (ROOT / "scripts" / "windows" / "run_liquidation_collector_windows.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "windows" / "install_liquidation_collector_task_windows.ps1").read_text(encoding="utf-8")
        observation_runner = (ROOT / "scripts" / "windows" / "run_observation_history_windows.ps1").read_text(encoding="utf-8")
        etp_caller = (ROOT / "scripts" / "windows" / "run_etp_capture_if_due_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("[int]$MaxRuntimeSeconds = 0", runner)
        self.assertIn("[int]$MaxRuntimeSeconds = 0", installer)
        self.assertIn("-ExecutionTimeLimit ([TimeSpan]::Zero)", installer)
        self.assertIn('if ($MaxRuntimeSeconds -gt 0)', runner)
        self.assertIn("Get-CimInstance Win32_Process", observation_runner)
        self.assertIn("crt_radar.liquidation_collector", observation_runner)
        self.assertIn('Start-Process -FilePath "powershell.exe"', observation_runner)
        self.assertIn("-WindowStyle Hidden", observation_runner)
        self.assertIn("run_etp_capture_if_due_windows.ps1", observation_runner)
        self.assertIn("Eastern Standard Time", etp_caller)
        self.assertIn("ETP_CAPTURE_ALREADY_ATTEMPTED", etp_caller)
        self.assertIn('external_action_authority = "NONE"', etp_caller)
        self.assertNotIn("candidate_model", etp_caller)

    def test_private_profile_is_dynamic_local_roc_and_read_only(self):
        validated = validate_private_profile(private_payload())
        self.assertEqual(validated["derived"]["six_month_cash_usd"], 500.0)
        self.assertEqual(validated["derived"]["minimum_shares_for_target"], 100)
        self.assertTrue(validated["derived"]["goal_covered_at_current_rate"])
        self.assertEqual(validated["strc"]["tax_treatment"], "RETURN_OF_CAPITAL")
        self.assertEqual(validated["strc"]["withholding_rate"], 0)

    def test_private_profile_rejects_external_action_authority(self):
        payload = private_payload()
        payload["external_action_authority"] = "TRADE"
        with self.assertRaises(PrivateProfileError):
            validate_private_profile(payload)

    def test_private_profile_loads_from_local_file_without_code_constants(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "portfolio.json"
            path.write_text(json.dumps(private_payload()), encoding="utf-8")
            loaded = load_private_profile(path)
        self.assertEqual(loaded["state"], "AVAILABLE")
        self.assertEqual(loaded["profile"]["strc"]["distribution_rate_mode"], "DYNAMIC_LOCAL_VALUE")

    def test_plain_language_notice_requests_gpt_reanalysis_without_action(self):
        context = {"state": "AVAILABLE", "profile": validate_private_profile(private_payload())}
        notice = build_plain_language_notice(blocked_pack(context))
        self.assertEqual(notice["state"], "GPT_REANALYSIS_REQUESTED")
        self.assertIn("BTC", notice["what_happened"])
        self.assertIn("STRC", notice["position_context"])
        self.assertEqual(notice["action_output"], "NONE")
        self.assertEqual(notice["external_action_authority"], "NONE")
        self.assertFalse(notice["external_action_performed"])

    def test_maturity_attempt_remains_zero_until_formal_executables_are_verified(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "attempts.jsonl"
            status_path = Path(td) / "status.json"
            first = record_maturity_attempt(ledger, status_path, blocked_pack())
            second = record_maturity_attempt(ledger, status_path, blocked_pack())
        self.assertEqual(first["qualified_runs"], 0)
        self.assertEqual(first["attempt_count"], 1)
        self.assertEqual(second["attempt_count"], 1)
        self.assertIn(
            "LOCKED_FORMAL_SCORING_EXECUTABLE_UNAVAILABLE_IN_CURRENT_MAIN",
            second["latest_attempt"]["blocked_reasons"],
        )

    def test_coinmetrics_free_direct_mvrv_preserves_nupl_identity(self):
        result = parse_coinmetrics_caps(
            {
                "data": [
                    {
                        "asset": "btc",
                        "time": "2026-08-15T00:00:00.000000000Z",
                        "CapMVRVCur": "1.25",
                        "CapMrktCurUSD": "1250000000000",
                    }
                ]
            }
        )
        self.assertAlmostEqual(result["mvrv"], 1.25)
        self.assertAlmostEqual(result["nupl"], 0.2)
        self.assertAlmostEqual(result["realized_cap_usd"], 1_000_000_000_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
