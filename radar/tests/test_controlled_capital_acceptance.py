"""Controlled synthetic model preparation: every test stays offline."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from crt_radar import capital_decision_closure as capital
from crt_radar import gpt_transport_worker as worker
from crt_radar.gpt_handoff import expand_bridge_field_names
from scripts import run_controlled_capital_acceptance as controlled

MAIN = "4bee34d0d674da785516809cb103ccef9645eee7"
NOW = 1790930000000


class ControlledAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        no_http = patch.object(worker.urlrequest, "build_opener",
            side_effect=AssertionError("No external network requests in acceptance tests"))
        self.http_opener = no_http.start()
        self.addCleanup(no_http.stop)
        with patch.object(worker, "_post_response", side_effect=AssertionError("No external model requests")):
            self.preflight = controlled.preflight(self.root, source_main_sha=MAIN, at_ms=NOW)
        self.case = controlled._read_json(self.root / "synthetic-case.json")

    def approval(self):
        at = int(time.time() * 1000)
        return {"contract_version": controlled.APPROVAL_VERSION, "source": "USER_EXPLICIT_APPROVAL",
            "approved": True, "model": controlled.SMOKE_MODEL, "case_hash": self.case["case_hash"],
            "request_hash": self.case["envelope"]["request_hash"], "max_calls": 1,
            "max_cost_usd": "0.05", "approved_at_ms": at - 1000, "expires_at_ms": at + 60_000}

    def test_default_preflight_is_no_network_full_synthetic_contract(self):
        result = self.preflight
        self.assertFalse(result["network_performed"])
        self.assertFalse(result["daily_auto_send_enabled"])
        self.assertEqual(result["model_tokens"], "NOT_MEASURED")
        self.assertEqual(self.case["envelope"]["contract_version"], capital.FULL_REQUEST_VERSION)
        self.assertEqual(self.case["envelope"]["delivery_mode"], "OFFLINE_ONLY")
        self.assertEqual(controlled.validate_case(self.case), self.case)
        expanded = expand_bridge_field_names(self.case["payload"])
        self.assertEqual(set(expanded["market_context"]["layers"]), {f"L{i}" for i in range(1, 7)})
        valuations = expanded["market_context"]["treasury_valuation_context"]
        self.assertTrue(all(row["formal_action_critical_state"] == "BLOCKED" for row in valuations.values()))
        body = json.loads(self.case["envelope"]["request_body"]["input"])
        self.assertEqual(body["capital"]["funds"]["cash_usd"], 1000)
        self.assertNotIn("account_number", json.dumps(self.case))
        self.assertNotIn("never-export@example.com", json.dumps(self.case))

    def test_offline_full_delivery_notification_replay_and_dedupe(self):
        with patch.object(worker, "_post_response", side_effect=AssertionError("No external model requests")):
            first = controlled.execute(self.root, mode="OFFLINE_SIMULATION")
            replay = controlled.execute(self.root, mode="OFFLINE_SIMULATION")
        self.assertEqual(first["delivery"]["state"], "DELIVERED")
        self.assertEqual(first["notification_results"][0]["state"], "DELIVERED")
        self.assertIn("不得交易", first["presented_text"][0])
        self.assertEqual(replay["delivery"]["state"], "ALREADY_DELIVERED")
        self.assertEqual(replay["presented_text"], [])
        self.assertEqual(first["real_model_acceptance"], "NOT_MEASURED")
        self.assertEqual(first["model_cost"], "NOT_MEASURED")

    def test_convincing_provider_id_and_usage_in_mock_never_mark_real(self):
        response = controlled.simulated_response(self.case)
        response.update(id="resp_convincing_real_looking", usage={"input_tokens": 99, "output_tokens": 88})
        with patch.object(worker, "_post_response", side_effect=AssertionError("No external model requests")):
            result = controlled.execute(self.root, mode="OFFLINE_SIMULATION", offline_response=response)
        self.assertEqual(result["delivery"]["state"], "DELIVERED")
        self.assertEqual(result["mode"], "OFFLINE_SIMULATION")
        self.assertEqual(result["model_tokens"], "NOT_MEASURED")
        self.assertEqual(result["real_model_acceptance"], "NOT_MEASURED")

    def test_approval_missing_or_scope_modified_never_calls_sender(self):
        approval = self.approval()
        cases = [None, {**approval, "approved": False}, {**approval, "max_calls": 2},
            {**approval, "model": "unapproved-model"}, {**approval, "request_hash": "a" * 64},
            {**approval, "case_hash": "b" * 64}, {**approval, "expires_at_ms": 1},
            {**approval, "max_cost_usd": "0.000001"}]
        with patch.object(worker, "_post_response") as sender:
            for candidate in cases:
                with self.subTest(candidate=candidate), self.assertRaises((ValueError, TypeError)):
                    controlled.execute(self.root, mode="CONTROLLED_REAL_REQUEST", approval=candidate)
            sender.assert_not_called()
        self.http_opener.assert_not_called()

    def test_live_entry_rejects_any_injected_mock_response(self):
        with patch.object(worker, "_post_response") as sender:
            with self.assertRaisesRegex(ValueError, "Mock response"):
                controlled.execute(self.root, mode="CONTROLLED_REAL_REQUEST", approval=self.approval(),
                    offline_response=controlled.simulated_response(self.case))
            sender.assert_not_called()

    def test_sender_mock_cannot_supply_live_provenance_or_usage(self):
        response = controlled.simulated_response(self.case)
        response["usage"] = {"input_tokens": 500, "output_tokens": 100}
        approval = self.approval()
        with patch.dict(os.environ, {controlled.API_KEY_ENV_VAR: "offline-test-placeholder"}), \
                patch.object(worker, "_post_response", return_value=response) as sender:
            result = controlled.execute(self.root, mode="CONTROLLED_REAL_REQUEST", approval=approval)
            replay = controlled.execute(self.root, mode="CONTROLLED_REAL_REQUEST", approval=approval)
            self.assertEqual(sender.call_count, 1)
        self.assertEqual(result["delivery"]["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(replay["delivery"]["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(result["real_model_acceptance"], "NOT_MEASURED")
        self.assertEqual(result["model_tokens"], "NOT_MEASURED")
        self.assertFalse((self.root / "CONTROLLED_REAL_REQUEST" / "controlled-http-result.json").exists())

    def test_missing_credential_does_not_consume_approved_call(self):
        with patch.dict(os.environ, {controlled.API_KEY_ENV_VAR: ""}), patch.object(worker, "_post_response") as sender:
            with self.assertRaisesRegex(ValueError, "no controlled call attempted"):
                controlled.execute(self.root, mode="CONTROLLED_REAL_REQUEST", approval=self.approval())
            sender.assert_not_called()
        self.assertFalse((self.root / "CONTROLLED_REAL_REQUEST").exists())

    def test_tampered_synthetic_package_fails_even_with_resealed_hashes(self):
        mutated = deepcopy(self.case)
        mutated["source"]["broker_observation"]["holdings"][0]["quantity"] = 9999
        mutated["case_hash"] = capital.digest({key: value for key, value in mutated.items() if key != "case_hash"})
        with self.assertRaisesRegex(ValueError, "exact generated synthetic fixture"):
            controlled.validate_case(mutated)

    def test_normal_daily_capital_sender_remains_offline_only(self):
        with patch.object(worker, "_post_response") as sender:
            with self.assertRaisesRegex(ValueError, "OFFLINE_ONLY"):
                worker.send_response(self.case["envelope"])
            sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
