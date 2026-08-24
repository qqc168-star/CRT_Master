from __future__ import annotations

import ast
import hashlib
import inspect
import json
import unittest

import crt_radar.openai_responses_adapter_contract as adapter_module
from crt_radar.gpt_handoff import REANALYSIS_SEQUENCE
from crt_radar.openai_responses_adapter_contract import (
    API_KEY_ENV_VAR,
    AUTO_RETRY,
    MAX_ATTEMPTS,
    MAX_INPUT_UTF8_BYTES,
    MAX_OUTPUT_TOKENS,
    RESPONSES_PATH,
    SMOKE_GUARDRAILS_VERSION,
    SMOKE_MODEL,
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
        "model": SMOKE_MODEL,
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
        env = build_request_envelope(payload(), model=SMOKE_MODEL)
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
        self.assertEqual(
            env["smoke_guardrails"],
            {
                "version": SMOKE_GUARDRAILS_VERSION,
                "mode": "ONE_SHOT",
                "model": SMOKE_MODEL,
                "max_input_utf8_bytes": MAX_INPUT_UTF8_BYTES,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
                "max_attempts": MAX_ATTEMPTS,
                "auto_retry": AUTO_RETRY,
            },
        )

    def test_request_reuses_reanalysis_sequence(self) -> None:
        env = build_request_envelope(payload(), model=SMOKE_MODEL)
        instructions = env["request_body"]["instructions"]
        for item in REANALYSIS_SEQUENCE:
            self.assertIn(item, instructions)

    def test_invalid_bridge_payload_is_rejected(self) -> None:
        bad = payload()
        bad["privacy"]["transport_selected"] = True
        with self.assertRaises(ValueError):
            build_request_envelope(bad, model=SMOKE_MODEL)

    def test_smoke_model_is_exactly_pinned(self) -> None:
        with self.assertRaises(ValueError):
            build_request_envelope(payload(), model="gpt-5.6-sol")

    def test_tampered_envelope_is_rejected(self) -> None:
        env = build_request_envelope(payload(), model=SMOKE_MODEL)
        env["request_body"]["store"] = True
        with self.assertRaises(ValueError):
            validate_request_envelope(env)

    def test_tools_are_rejected_even_if_hash_resealed(self) -> None:
        env = build_request_envelope(payload(), model=SMOKE_MODEL)
        env["request_body"]["tools"] = []
        unhashed = dict(env)
        unhashed.pop("request_hash", None)
        env["request_hash"] = _hash(unhashed)
        with self.assertRaises(ValueError):
            validate_request_envelope(env)

    def test_resealed_model_and_output_ceiling_drift_are_rejected(self) -> None:
        for field, value in (
            ("model", "gpt-5.6-sol"),
            ("max_output_tokens", MAX_OUTPUT_TOKENS + 1),
        ):
            with self.subTest(field=field):
                env = build_request_envelope(payload(), model=SMOKE_MODEL)
                env["request_body"][field] = value
                unhashed = dict(env)
                unhashed.pop("request_hash", None)
                env["request_hash"] = _hash(unhashed)
                with self.assertRaises(ValueError):
                    validate_request_envelope(env)

    def test_oversized_input_is_rejected_before_envelope_creation(self) -> None:
        bad = payload()
        bad["analysis"]["marker"] = "x" * MAX_INPUT_UTF8_BYTES
        bad.pop("bridge_payload_hash")
        bad["bridge_payload_hash"] = _hash(bad)
        with self.assertRaises(ValueError):
            build_request_envelope(bad, model=SMOKE_MODEL)

    def test_input_ceiling_counts_utf8_bytes_not_characters(self) -> None:
        bad = payload()
        bad["analysis"]["marker"] = "界" * (MAX_INPUT_UTF8_BYTES // 2)
        bad.pop("bridge_payload_hash")
        bad["bridge_payload_hash"] = _hash(bad)
        with self.assertRaises(ValueError):
            build_request_envelope(bad, model=SMOKE_MODEL)

    def test_one_shot_policy_never_classifies_retryable(self) -> None:
        self.assertEqual(
            classify_http_result(429, attempt_count=1),
            "TERMINAL",
        )
        self.assertEqual(
            classify_http_result(500, attempt_count=1),
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
        with self.assertRaises(ValueError):
            classify_http_result(429, attempt_count=2)

    def test_adapter_has_no_network_or_secret_read_import_surface(self) -> None:
        tree = ast.parse(inspect.getsource(adapter_module))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue(
            imports.isdisjoint(
                {"os", "openai", "httpx", "requests", "socket", "urllib"}
            )
        )

    def test_completed_response_builds_receipt(self) -> None:
        env = build_request_envelope(payload(), model=SMOKE_MODEL)
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

    def test_response_model_mismatch_cannot_form_receipt(self) -> None:
        env = build_request_envelope(payload(), model=SMOKE_MODEL)
        bad = response()
        bad["model"] = "gpt-5.6-sol"
        with self.assertRaises(ValueError):
            build_delivery_receipt(
                bad,
                event_id=env["event_id"],
                bridge_payload_hash=env["bridge_payload_hash"],
                request_hash=env["request_hash"],
            )

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
