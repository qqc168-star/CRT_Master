from __future__ import annotations

import hashlib
import json
import unittest

from crt_radar.gpt_handoff import REANALYSIS_SEQUENCE
from crt_radar.openai_responses_adapter_contract import (
    API_KEY_ENV_VAR,
    RESPONSES_PATH,
    build_delivery_receipt,
    build_request_envelope,
    classify_http_result,
    validate_request_envelope,
)


def _hash(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def payload() -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "CRT_MINIMIZED_BRIDGE_PAYLOAD_V0.1",
        "privacy_contract_version": "CRT_BRIDGE_PAYLOAD_PRIVACY_CONTRACT_V0.1",
        "state": "BRIDGE_PAYLOAD_READY_LOCAL_ONLY",
        "event": {"event_id": "a" * 64},
        "analysis": {"marker": "synthetic"},
        "authority": {
            "production": "NOT_APPROVED",
            "trading_authority": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "transport_authority": "NONE",
            "transport_performed": False,
            "action_output": "NONE",
        },
        "privacy": {
            "mode": "MINIMIZED_ALLOWLIST_ONLY",
            "raw_private_context_included": False,
            "full_private_profile_included": False,
            "filesystem_paths_included": False,
            "broker_or_account_identifiers_included": False,
            "credentials_or_secrets_included": False,
            "transport_selected": False,
        },
    }
    result["bridge_payload_hash"] = _hash(result)
    return result


def response() -> dict[str, object]:
    return {
        "id": "resp_test_1",
        "status": "completed",
        "model": "gpt-test",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Synthetic CRT analysis."}
                ],
            }
        ],
    }


class OpenAIResponsesAdapterContractTests(unittest.TestCase):
    def test_request_is_offline_store_false_and_tool_free(self) -> None:
        env = build_request_envelope(payload(), model="gpt-test")
        self.assertEqual(env["transport"]["path"], RESPONSES_PATH)
        self.assertEqual(env["transport"]["auth_env_var"], API_KEY_ENV_VAR)
        self.assertFalse(env["transport"]["secret_value_included"])
        self.assertFalse(env["request_body"]["store"])
        self.assertFalse(env["request_body"]["background"])
        self.assertNotIn("tools", env["request_body"])
        self.assertFalse(env["tools_allowed"])
        self.assertFalse(env["network_performed"])
        self.assertEqual(env["production"], "NOT_APPROVED")
        self.assertEqual(env["external_action_authority"], "NONE")

    def test_request_reuses_reanalysis_sequence(self) -> None:
        env = build_request_envelope(payload(), model="gpt-test")
        instructions = env["request_body"]["instructions"]
        for item in REANALYSIS_SEQUENCE:
            self.assertIn(item, instructions)

    def test_invalid_bridge_payload_is_rejected(self) -> None:
        bad = payload()
        bad["privacy"]["transport_selected"] = True
        with self.assertRaises(ValueError):
            build_request_envelope(bad, model="gpt-test")

    def test_tampered_envelope_is_rejected(self) -> None:
        env = build_request_envelope(payload(), model="gpt-test")
        env["request_body"]["store"] = True
        with self.assertRaises(ValueError):
            validate_request_envelope(env)

    def test_tools_are_rejected_even_if_hash_resealed(self) -> None:
        env = build_request_envelope(payload(), model="gpt-test")
        env["request_body"]["tools"] = []
        unhashed = dict(env)
        unhashed.pop("request_hash", None)
        env["request_hash"] = _hash(unhashed)
        with self.assertRaises(ValueError):
            validate_request_envelope(env)

    def test_retry_policy(self) -> None:
        self.assertEqual(
            classify_http_result(429, attempt_count=1),
            "RETRYABLE",
        )
        self.assertEqual(
            classify_http_result(429, attempt_count=3),
            "TERMINAL",
        )
        self.assertEqual(
            classify_http_result(400, attempt_count=1),
            "TERMINAL",
        )
        self.assertEqual(
            classify_http_result(200, attempt_count=1),
            "SUCCESS",
        )

    def test_completed_response_builds_receipt(self) -> None:
        env = build_request_envelope(payload(), model="gpt-test")
        receipt = build_delivery_receipt(
            response(),
            event_id=env["event_id"],
            bridge_payload_hash=env["bridge_payload_hash"],
            request_hash=env["request_hash"],
        )
        self.assertEqual(
            receipt["state"],
            "RESPONSES_DELIVERY_RECEIPT_READY",
        )
        self.assertEqual(receipt["response_id"], "resp_test_1")
        self.assertEqual(receipt["output_text"], "Synthetic CRT analysis.")
        self.assertEqual(receipt["production"], "NOT_APPROVED")
        self.assertEqual(receipt["external_action_authority"], "NONE")

    def test_incomplete_response_cannot_form_receipt(self) -> None:
        bad = response()
        bad["status"] = "in_progress"
        with self.assertRaises(ValueError):
            build_delivery_receipt(
                bad,
                event_id="a" * 64,
                bridge_payload_hash="b" * 64,
                request_hash="c" * 64,
            )


if __name__ == "__main__":
    unittest.main()
