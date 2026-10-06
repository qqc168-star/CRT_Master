"""Offline protocol fixtures, never live evidence."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from crt_radar.commander_plan_adapter import CommanderPlanBlocked, validate_commander_plan, seal_commander_plan
from crt_radar.gpt_commander_plan_closure import (build_commander_source_bundle,
    commander_judgment_response_format, parse_commander_judgment_response, JUDGMENT_FIELDS, LINE_FIELDS)
from crt_radar.gpt_transport_worker import deliver_event
from crt_radar.gpt_transport_boundary import _read_json
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_handoff import build_minimized_bridge_payload, run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice
from crt_radar.openai_responses_adapter_contract import build_request_envelope, validate_request_envelope, SMOKE_MODEL, _hash
from test_gpt_commander_plan_closure import source_inputs, judgment_for, MAIN, NOW, seal_field
from test_gpt_handoff import bridge_pack, pack


def provider(judgment):
    return {"id": "resp_synthetic", "model": SMOKE_MODEL, "status": "completed",
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps(judgment)}]}]}


class Fixture:
    def setUp(self):
        self.bundle = build_commander_source_bundle(**source_inputs())
        self.judgment = judgment_for(self.bundle)
        self.context = {key: self.judgment[key] for key in
                        ("source_main_sha", "source_bundle_hash", "asset", "posture_candidate")}

    def parse(self, response, **kwargs):
        return parse_commander_judgment_response(response, source_bundle=self.bundle,
            current_main_sha=kwargs.get("main", MAIN), asset=kwargs.get("asset", "MSTR"),
            now=kwargs.get("now", NOW))


class StructuredJudgmentTests(Fixture, unittest.TestCase):
    def test_valid_response_reaches_existing_validator_without_inference(self):
        raw = provider(self.judgment); before = deepcopy(raw)
        judgment, candidate = self.parse(raw)
        self.assertEqual(raw, before)
        self.assertEqual(judgment, self.judgment)
        self.assertEqual(candidate["lines"], self.judgment["lines"])
        self.assertNotIn("plan_sha", candidate)
        self.assertEqual(validate_commander_plan(seal_commander_plan(candidate),
            current_main_sha=MAIN, now=NOW), (True, []))

    def test_missing_extra_fields_at_all_levels_block(self):
        for scope in ("top", "line", "governance"):
            base = deepcopy(self.judgment)
            row = base if scope == "top" else base["lines"][0] if scope == "line" else base["governance"]
            for key in list(row) + ["unexpected"]:
                bad = deepcopy(base)
                target = bad if scope == "top" else bad["lines"][0] if scope == "line" else bad["governance"]
                if key == "unexpected": target[key] = "extra"
                else: del target[key]
                with self.subTest(scope=scope, key=key), self.assertRaises(CommanderPlanBlocked):
                    self.parse(provider(bad))

    def test_malformed_duplicate_and_nonfinite_json_block(self):
        for text in ("not JSON", "```json {} ```", "{}{}", "[]", "null",
                     '{"asset":"MSTR","asset":"ASST"}', '{"price":NaN}'):
            raw = provider(self.judgment); raw["output"][0]["content"][0]["text"] = text
            with self.subTest(text=text), self.assertRaises(CommanderPlanBlocked): self.parse(raw)

    def test_hash_main_asset_posture_and_authority_mismatch_block(self):
        for field, value in (("source_bundle_hash", "a" * 64), ("source_main_sha", "b" * 40),
                             ("asset", "ASST"), ("posture_candidate", "UNRESTRICTED")):
            bad = deepcopy(self.judgment); bad[field] = value
            with self.subTest(field=field), self.assertRaises(CommanderPlanBlocked): self.parse(provider(bad))
        for field in self.judgment["governance"]:
            bad = deepcopy(self.judgment); bad["governance"][field] = "APPROVED"
            with self.subTest(field=field), self.assertRaises(CommanderPlanBlocked): self.parse(provider(bad))
        with self.assertRaises(CommanderPlanBlocked): self.parse(provider(self.judgment), main="c" * 40)

    def test_invalid_lines_prices_directions_and_context_block(self):
        for key, value in (("price", 0), ("price", -1), ("price", True), ("price", "125"),
                           ("price", 1e309), ("direction", "SIDEWAYS"), ("rationale", ""),
                           ("confirmation_condition", "UNKNOWN"), ("line_type", "BUY")):
            bad = deepcopy(self.judgment); bad["lines"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(CommanderPlanBlocked): self.parse(provider(bad))
        bad = deepcopy(self.judgment); bad["lines"][1] = deepcopy(bad["lines"][0])
        with self.assertRaises(CommanderPlanBlocked): self.parse(provider(bad))

    def test_refusal_incomplete_empty_and_multiple_messages_block(self):
        original = provider(self.judgment)
        cases = [{**original, "status": "incomplete"}, {**original, "error": {"code": "failure"}},
                 {**original, "incomplete_details": {"reason": "max_output_tokens"}},
                 {**original, "output": []}, {**original, "output": original["output"] * 2}]
        for content in ([{"type": "refusal", "refusal": "No"}],
                        original["output"][0]["content"] + [{"type": "refusal", "refusal": "No"}], []):
            bad = deepcopy(original); bad["output"][0]["content"] = content; cases.append(bad)
        for field, value in (("status", "in_progress"), ("role", "user")):
            bad = deepcopy(original); bad["output"][0][field] = value; cases.append(bad)
        for bad in cases:
            with self.subTest(raw=bad), self.assertRaises(CommanderPlanBlocked): self.parse(bad)

    def test_expired_future_and_stale_source_block(self):
        for field, value in (("generated_at", (NOW + timedelta(seconds=1)).isoformat()),
                             ("valid_until", NOW.isoformat())):
            bad = deepcopy(self.judgment); bad[field] = value
            with self.assertRaises(CommanderPlanBlocked): self.parse(provider(bad))
        with self.assertRaises(CommanderPlanBlocked): self.parse(provider(self.judgment), now=NOW + timedelta(days=1))

    def test_schema_projects_existing_fields_and_locks(self):
        fmt = commander_judgment_response_format(self.context); self.assertTrue(fmt["strict"])
        schema = fmt["schema"]
        self.assertEqual(set(schema["properties"]), JUDGMENT_FIELDS)
        self.assertEqual(set(schema["properties"]["lines"]["items"]["properties"]), LINE_FIELDS)
        def visit(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertFalse(value["additionalProperties"])
                    self.assertEqual(set(value["required"]), set(value["properties"]))
                for item in value.values(): visit(item)
            elif isinstance(value, list):
                for item in value: visit(item)
        visit(schema)


class StructuredWorkerTests(Fixture, unittest.TestCase):
    # Isolate worker protocol from large Bridge projection. Source/Commander
    # validators are real; this projection stub does not prove live acceptance.
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        evidence = bridge_pack(pack(evidence_hash="a" * 64, requested=True))
        handoff = run_gpt_handoff_gate(evidence, build_plain_language_notice(evidence),
                                      ledger_path=self.root / "handoff.jsonl")
        self.payload = build_minimized_bridge_payload(evidence, handoff)
        enqueue_bridge_payload(self.root / "outbox", self.payload)
        self.event = self.payload["event"]["event_id"]
        self.path = self.root / "outbox" / (self.event + ".json")
        self.states = self.root / "states"
        self.send = Mock(return_value=provider(self.judgment))

    def deliver(self, **kwargs):
        with patch("crt_radar.gpt_transport_worker.build_minimized_bridge_payload", return_value=self.payload):
            return deliver_event(self.path, self.states, transport=self.send,
                source_bundle=self.bundle, current_main_sha=kwargs.get("main", MAIN),
                asset=kwargs.get("asset", "MSTR"), now_ms=int(NOW.timestamp() * 1000))

    def test_worker_validates_persists_candidate_and_deduplicates(self):
        self.assertEqual(self.deliver()["state"], "DELIVERED")
        saved = _read_json(self.states / "responses" / (self.event + ".json"))
        self.assertEqual(saved["response"], self.send.return_value)
        validated = _read_json(self.states / "judgments" / (self.event + ".json"))
        self.assertEqual(validated["judgment"], self.judgment)
        self.assertNotIn("plan_sha", validated["candidate"])
        self.assertEqual(self.deliver()["state"], "ALREADY_DELIVERED"); self.send.assert_called_once()
        body = self.send.call_args.args[0]["request_body"]
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertLessEqual(len(body["input"].encode()), 16384)
        self.assertEqual(body["model"], SMOKE_MODEL); self.assertEqual(body["max_output_tokens"], 1800)

    def test_invalid_response_is_retained_no_candidate_no_resend(self):
        self.send.return_value["output"][0]["content"] = [{"type": "refusal", "refusal": "No"}]
        self.assertEqual(self.deliver()["state"], "RECONCILIATION_REQUIRED")
        saved = _read_json(self.states / "responses" / (self.event + ".json"))
        self.assertEqual(saved["response"], self.send.return_value)
        self.assertFalse((self.states / "judgments").exists())
        self.assertEqual(self.deliver()["state"], "RECONCILIATION_REQUIRED"); self.send.assert_called_once()

    def test_wrong_main_blocks_before_transport(self):
        with self.assertRaises(ValueError): self.deliver(main="b" * 40)
        self.send.assert_not_called(); self.assertFalse(self.states.exists())

    def test_worker_checks_exact_projected_bridge_before_transport(self):
        with patch("crt_radar.gpt_transport_worker.build_minimized_bridge_payload", return_value={}):
            with self.assertRaisesRegex(ValueError, "exact minimized bridge"):
                deliver_event(self.path, self.states, transport=self.send, source_bundle=self.bundle,
                    current_main_sha=MAIN, asset="MSTR", now_ms=int(NOW.timestamp() * 1000))
        self.send.assert_not_called()

    def test_native_schema_tampering_and_context_overflow_block(self):
        env = build_request_envelope(self.payload, model=SMOKE_MODEL, judgment_context=self.context)
        bad = deepcopy(env); bad["request_body"]["text"]["format"]["strict"] = False
        bad.pop("request_hash"); bad["request_hash"] = _hash(bad)
        with self.assertRaises(ValueError): validate_request_envelope(bad)
        big = deepcopy(self.payload); big["market_context"]["test_padding"] = "x" * 16384
        big.pop("bridge_payload_hash"); big["bridge_payload_hash"] = _hash(big)
        with self.assertRaises(ValueError): build_request_envelope(big, model=SMOKE_MODEL, judgment_context=self.context)

    def test_original_full_source_projection_stays_fail_closed_over_budget(self):
        inputs = source_inputs(); evidence = inputs["evidence_pack"]
        evidence["private_context"] = bridge_pack(evidence)["private_context"]
        evidence["private_context"]["profile"]["capital_state"]["as_of"] = NOW.isoformat()
        seal_field(evidence, "evidence_pack_hash")
        inputs["handoff"] = run_gpt_handoff_gate(evidence, build_plain_language_notice(evidence),
                                                ledger_path=self.root / "full.jsonl")
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            build_minimized_bridge_payload(evidence, inputs["handoff"])
