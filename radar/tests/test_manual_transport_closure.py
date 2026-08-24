from __future__ import annotations

import ast
import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

import crt_radar.manual_transport_closure as manual_module
from crt_radar.gpt_transport_boundary import build_pending_state
from crt_radar.manual_transport_closure import (
    MANUAL_ADAPTER_ID,
    MAX_MANUAL_RESPONSE_UTF8_BYTES,
    build_manual_handoff,
    build_manual_receipt,
    close_manual_bundle,
    prepare_manual_bundle,
    render_manual_prompt,
    run_loopback_acceptance,
    validate_loopback_url,
    validate_loopback_receipt,
    validate_manual_handoff,
    validate_manual_receipt,
    verify_manual_bundle,
)
from crt_radar.openai_responses_adapter_contract import (
    RESPONSES_PATH,
    SMOKE_MODEL,
    build_request_envelope,
)


def _hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def payload() -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "CRT_MINIMIZED_BRIDGE_PAYLOAD_V0.1",
        "privacy_contract_version": (
            "CRT_BRIDGE_PAYLOAD_PRIVACY_CONTRACT_V0.1"
        ),
        "state": "BRIDGE_PAYLOAD_READY_LOCAL_ONLY",
        "event": {"event_id": "d" * 64},
        "analysis": {"marker": "synthetic-zero-cost"},
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


class _FakeResponse:
    def __init__(self, status: int, body: dict[str, object]) -> None:
        self.status = status
        self._raw = json.dumps(body).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        return self._raw[:size] if size >= 0 else self._raw


class ManualTransportClosureTests(unittest.TestCase):
    def test_handoff_is_minimized_manual_and_explicitly_not_live(self) -> None:
        handoff = build_manual_handoff(payload())
        self.assertEqual(handoff["state"], "MANUAL_HANDOFF_READY")
        self.assertEqual(handoff["adapter_id"], MANUAL_ADAPTER_ID)
        self.assertEqual(handoff["transfer"]["mode"], "HUMAN_COPY_PASTE")
        self.assertEqual(handoff["transfer"]["program_transport"], "NONE")
        self.assertFalse(
            handoff["limitations"]["live_openai_api_transport_verified"]
        )
        self.assertFalse(
            handoff["limitations"]["provider_model_identity_verified"]
        )
        self.assertEqual(
            handoff["authority"]["external_action_authority"],
            "NONE",
        )
        decoded = json.loads(handoff["input"])
        self.assertEqual(decoded["privacy"]["mode"], "MINIMIZED_ALLOWLIST_ONLY")

    def test_handoff_policy_drift_fails_even_when_resealed(self) -> None:
        handoff = build_manual_handoff(payload())
        handoff["limitations"]["live_openai_api_transport_verified"] = True
        handoff.pop("handoff_hash")
        handoff["handoff_hash"] = _hash(handoff)
        with self.assertRaises(ValueError):
            validate_manual_handoff(handoff)

    def test_prompt_is_deterministic_and_carries_hash(self) -> None:
        handoff = build_manual_handoff(payload())
        first = render_manual_prompt(handoff)
        second = render_manual_prompt(handoff)
        self.assertEqual(first, second)
        self.assertIn(handoff["handoff_hash"], first)
        self.assertIn("Do not perform external actions.", first)
        self.assertIn(handoff["input"], first)

    def test_manual_receipt_requires_explicit_user_attestation(self) -> None:
        handoff = build_manual_handoff(payload())
        with self.assertRaises(ValueError):
            build_manual_receipt(
                handoff,
                "Synthetic manual answer.",
                user_confirmed=False,
            )

    def test_manual_receipt_binds_response_without_claiming_api_delivery(self) -> None:
        handoff = build_manual_handoff(payload())
        receipt = build_manual_receipt(
            handoff,
            "Synthetic manual answer.",
            user_confirmed=True,
        )
        self.assertEqual(receipt["state"], "MANUAL_TRANSFER_ATTESTED")
        self.assertEqual(receipt["handoff_hash"], handoff["handoff_hash"])
        self.assertFalse(
            receipt["limitations"]["live_openai_api_transport_verified"]
        )
        self.assertFalse(
            receipt["limitations"]["existing_transport_boundary_completed"]
        )
        self.assertEqual(
            receipt["authority"]["external_action_authority"],
            "NONE",
        )

    def test_manual_receipt_tamper_is_rejected(self) -> None:
        handoff = build_manual_handoff(payload())
        receipt = build_manual_receipt(
            handoff,
            "Synthetic manual answer.",
            user_confirmed=True,
        )
        receipt["response_text"] = "Changed answer."
        with self.assertRaises(ValueError):
            validate_manual_receipt(receipt, handoff)

    def test_manual_receipt_policy_drift_fails_even_when_resealed(self) -> None:
        handoff = build_manual_handoff(payload())
        receipt = build_manual_receipt(
            handoff,
            "Synthetic manual answer.",
            user_confirmed=True,
        )
        receipt["limitations"]["unattended_delivery_verified"] = True
        receipt.pop("receipt_hash")
        receipt["receipt_hash"] = _hash(receipt)
        with self.assertRaises(ValueError):
            validate_manual_receipt(receipt, handoff)

    def test_manual_response_has_a_utf8_byte_ceiling(self) -> None:
        handoff = build_manual_handoff(payload())
        oversized = "界" * (MAX_MANUAL_RESPONSE_UTF8_BYTES // 2)
        with self.assertRaises(ValueError):
            build_manual_receipt(
                handoff,
                oversized,
                user_confirmed=True,
            )

    def test_literal_loopback_url_is_the_only_allowed_target(self) -> None:
        accepted = f"http://127.0.0.1:12345{RESPONSES_PATH}"
        self.assertEqual(validate_loopback_url(accepted), accepted)
        for rejected in (
            "https://api.openai.com/v1/responses",
            "http://localhost:12345/v1/responses",
            "http://127.0.0.2:12345/v1/responses",
            "http://127.0.0.1:12345/other",
            "http://127.0.0.1:12345/v1/responses?redirect=1",
            "http://user@127.0.0.1:12345/v1/responses",
            "http://127.0.0.1:0/v1/responses",
        ):
            with self.subTest(rejected=rejected):
                with self.assertRaises(ValueError):
                    validate_loopback_url(rejected)

    def test_external_target_is_blocked_before_opener_runs(self) -> None:
        envelope = build_request_envelope(payload(), model=SMOKE_MODEL)
        called = False

        def forbidden_opener(*args: object, **kwargs: object) -> object:
            nonlocal called
            called = True
            raise AssertionError("opener must not run")

        with self.assertRaises(ValueError):
            manual_module._post_loopback_request(
                "https://api.openai.com/v1/responses",
                envelope,
                opener=forbidden_opener,
            )
        self.assertFalse(called)

    def test_loopback_client_sends_no_credential_header(self) -> None:
        envelope = build_request_envelope(payload(), model=SMOKE_MODEL)
        captured_headers: dict[str, str] = {}

        def opener(request: object, **kwargs: object) -> _FakeResponse:
            nonlocal captured_headers
            captured_headers = {
                name.lower(): value
                for name, value in request.header_items()
            }
            return _FakeResponse(
                200,
                manual_module._synthetic_response(envelope["request_hash"]),
            )

        status, _ = manual_module._post_loopback_request(
            f"http://127.0.0.1:12345{RESPONSES_PATH}",
            envelope,
            opener=opener,
        )
        self.assertEqual(status, 200)
        self.assertNotIn("authorization", captured_headers)
        self.assertNotIn("api-key", captured_headers)
        self.assertEqual(
            captured_headers["x-crt-transport-mode"],
            "LOOPBACK_ONLY",
        )

    def test_actual_loopback_http_is_one_shot_zero_cost_and_not_live(self) -> None:
        receipt = run_loopback_acceptance(payload())
        transport = receipt["transport"]
        self.assertEqual(receipt["state"], "LOOPBACK_ACCEPTANCE_PASSED")
        self.assertEqual(transport["request_count"], 1)
        self.assertEqual(transport["attempt_count"], 1)
        self.assertTrue(transport["local_loopback_http_performed"])
        self.assertFalse(transport["external_network_performed"])
        self.assertFalse(transport["live_openai_api_request_performed"])
        self.assertFalse(transport["authorization_header_included"])
        self.assertFalse(transport["credential_header_included"])
        self.assertFalse(transport["api_key_read"])
        self.assertEqual(transport["incremental_api_cost"], "ZERO")

    def test_wrong_synthetic_response_model_cannot_form_loopback_receipt(self) -> None:
        envelope = build_request_envelope(payload(), model=SMOKE_MODEL)
        bad = manual_module._synthetic_response(envelope["request_hash"])
        bad["model"] = "gpt-5.6-sol"
        with self.assertRaises(ValueError):
            manual_module._build_loopback_receipt(
                envelope,
                status=200,
                response=bad,
                port=12345,
                audit={
                    "request_count": 1,
                    "authorization_header_included": False,
                    "credential_header_included": False,
                },
            )

    def test_loopback_policy_drift_fails_even_when_resealed(self) -> None:
        bridge_payload = payload()
        receipt = run_loopback_acceptance(bridge_payload)
        receipt["transport"]["external_network_performed"] = True
        receipt.pop("receipt_hash")
        receipt["receipt_hash"] = _hash(receipt)
        envelope = build_request_envelope(bridge_payload, model=SMOKE_MODEL)
        with self.assertRaises(ValueError):
            validate_loopback_receipt(receipt, envelope)

    def test_bundle_prepare_close_verify_and_idempotent_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "manual-bundle"
            prepared = prepare_manual_bundle(bundle, payload())
            self.assertEqual(prepared["state"], "PREPARED")
            self.assertTrue((bundle / "manual-handoff.json").is_file())
            self.assertTrue((bundle / "manual-prompt.txt").is_file())
            self.assertTrue((bundle / "loopback-receipt.json").is_file())

            response_file = root / "manual-response.txt"
            response_file.write_text(
                "Synthetic user-transferred analysis.\n",
                encoding="utf-8",
            )
            closed = close_manual_bundle(
                bundle,
                response_file,
                user_confirmed=True,
            )
            self.assertEqual(closed["state"], "MANUALLY_CLOSED")
            self.assertIsNotNone(closed["manual_receipt_hash"])
            self.assertEqual(
                close_manual_bundle(
                    bundle,
                    response_file,
                    user_confirmed=True,
                ),
                closed,
            )
            conflicting_response = root / "conflicting-response.txt"
            conflicting_response.write_text(
                "Different analysis.\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                close_manual_bundle(
                    bundle,
                    conflicting_response,
                    user_confirmed=True,
                )
            self.assertEqual(verify_manual_bundle(bundle), closed)

    def test_bundle_is_no_clobber_and_prompt_tamper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "manual-bundle"
            prepare_manual_bundle(bundle, payload())
            with self.assertRaises(FileExistsError):
                prepare_manual_bundle(bundle, payload())
            (bundle / "manual-prompt.txt").write_text(
                "tampered\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                verify_manual_bundle(bundle)

    def test_manual_closure_does_not_change_pending_transport_state(self) -> None:
        bridge_payload = payload()
        pending = build_pending_state(bridge_payload)
        handoff = build_manual_handoff(bridge_payload)
        receipt = build_manual_receipt(
            handoff,
            "Synthetic manual answer.",
            user_confirmed=True,
        )
        self.assertEqual(pending["state"], "PENDING")
        self.assertEqual(pending["attempt_count"], 0)
        self.assertNotEqual(receipt["state"], "DELIVERED")
        self.assertFalse(
            receipt["limitations"]["existing_transport_boundary_completed"]
        )

    def test_module_has_no_secret_value_read_or_external_endpoint(self) -> None:
        source = inspect.getsource(manual_module)
        tree = ast.parse(source)
        forbidden_calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Name) and function.id == "getenv":
                forbidden_calls.append(function.id)
            if isinstance(function, ast.Attribute) and function.attr in {
                "getenv",
                "environ",
            }:
                forbidden_calls.append(function.attr)
        self.assertEqual(forbidden_calls, [])
        self.assertNotIn("api.openai.com", source)


if __name__ == "__main__":
    unittest.main()
