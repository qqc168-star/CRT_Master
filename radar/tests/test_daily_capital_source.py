"""One synthetic account capture feeds the existing daily capital contracts."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from crt_radar import capital_decision_closure as c
from crt_radar.broker_capital_observation import MAX_AGE_MS, adapt_capital_intent, seal_broker_observation
from crt_radar.daily_evidence_runner import build_daily_capital_source, main, run_daily_evidence
from crt_radar.gpt_notification_boundary import present_from_transport
from crt_radar.gpt_transport_worker import deliver_event
from crt_radar.gpt_handoff import run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice
from tests import test_daily_evidence_runner as fixture
from tests.test_broker_capital_observation import synthetic_intent, synthetic_observation
from tests.test_capital_decision_closure import item, provider_response, recommendation, source_fixture


NOW = fixture.NOW_MS
MAIN = "4bee34d0d674da785516809cb103ccef9645eee7"


class DailyCapitalSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.market = fixture.DailyEvidenceRunnerTests()
        self.market.setUp()
        self.broker = synthetic_observation(NOW, funds={"cash_usd": 1000, "available_funds_usd": 800,
                                                       "settled_cash_usd": 900})
        self.intent = synthetic_intent(NOW)
        facts = source_fixture(at=NOW)
        self.inputs = {key: deepcopy(facts[key]) for key in
                       ("user_intent", "qualification", "instruments", "fees", "task", "evidence_validity")}
        self.inputs["user_intent"]["confirmed_at_ms"] = self.intent["confirmed_at_ms"]
        self.inputs["user_intent"]["reserved_usd"] = self.intent["reserved_usd"]
        self.inputs["qualification"]["observation_hash"] = self.broker["observation_hash"]

    def prepare(self):
        self.pack = run_daily_evidence(self.market.registry, observation_db=self.root / "observations.sqlite",
            fetch_overrides=self.market.overrides, liquidation_aggregate_payload=self.market.aggregate(),
            now_ms=NOW, generated_at_ms=NOW, broker_capital_observation=self.broker,
            dvol_regime_runner=lambda **_: {"state": "EXPANSION_ACTIVATED", "current_dvol": 50,
                "dvol_30d_low": 40, "rebound_from_30d_low_pct": 25, "level_percentile_1y": 80,
                "baseline_count": 30, "action_output": "NONE", "external_action_authority": "NONE",
                "external_action_performed": False},
            user_capital_intent=self.intent, full_decision_intent=self.inputs.get("user_intent"))
        self.handoff = run_gpt_handoff_gate(self.pack, build_plain_language_notice(self.pack),
            ledger_path=self.root / "handoff.jsonl", bridge_outbox_dir=self.root / "outbox", full_decision=True)
        self.payload = json.loads((self.root / "outbox" / f'{self.handoff["event_id"]}.json').read_text(encoding="utf-8"))

    def bind(self):
        return build_daily_capital_source(self.pack, self.payload, broker_observation=self.broker,
            handoff=self.handoff,
            user_capital_intent=self.intent, decision_inputs=self.inputs, source_main_sha=MAIN, at_ms=NOW)

    def test_one_capture_hash_and_validity_are_bound_without_clock_refresh(self):
        self.prepare()
        result = self.bind()
        self.assertEqual(result["state"], "SOURCE_BOUND", result)
        source = result["source"]
        self.assertEqual(source["broker_observation"], self.broker)
        self.assertEqual(source["user_intent"], self.inputs["user_intent"])
        self.assertEqual(result["binding"]["broker_observation_hash"], self.broker["observation_hash"])
        self.assertEqual(result["binding"]["evidence_pack_hash"], self.pack["evidence_pack_hash"])
        self.assertEqual(result["binding"]["bridge_payload_hash"], self.payload["bridge_payload_hash"])
        self.assertEqual(result["binding"]["valid_until_ms"], NOW + 240_000)
        self.assertEqual(result["claim_states"]["spending_cap"]["amount_usd"], "800.00")

    def test_legacy_intent_never_invents_no_leverage_or_full_approval(self):
        self.inputs.pop("user_intent")
        self.prepare()
        result = self.bind()
        self.assertEqual(result["state"], "SOURCE_BOUND", result)
        self.assertIsNone(result["source"]["user_intent"])
        self.assertEqual(result["claim_states"]["spending_cap"]["state"], "BLOCKED")
        self.assertIsNone(result["claim_states"]["spending_cap"]["amount_usd"])
        self.assertEqual(adapt_capital_intent(self.intent)["full_decision_intent"], None)

    def test_mixed_format_adapts_only_explicit_fields(self):
        combined = {**self.intent, **self.inputs["user_intent"]}
        adapted = adapt_capital_intent(combined)
        self.assertEqual(adapted["full_decision_intent"], self.inputs["user_intent"])
        self.assertEqual(adapted["reconciliation_intent"]["plan_policy"], "CANCEL_ALL_NO_REPLACEMENT")
        partial = deepcopy(combined)
        partial.pop("no_leverage")
        self.assertIsNone(adapt_capital_intent(partial)["full_decision_intent"])

    def test_intent_confirmation_or_reserve_mismatch_is_not_bound(self):
        self.prepare()
        for key, value in (("confirmed_at_ms", NOW), ("reserved_usd", 1)):
            with self.subTest(key=key):
                previous = self.inputs["user_intent"][key]
                self.inputs["user_intent"][key] = value
                result = self.bind()
                self.assertEqual(result["state"], "BLOCKED")
                self.assertIsNone(result["source"])
                self.assertIn("CAPITAL_INTENT_IDENTITY_MISMATCH", result["blockers"])
                self.inputs["user_intent"][key] = previous

    def test_observation_reconciliation_evidence_and_bridge_mismatch_rejected(self):
        self.prepare()
        original = deepcopy(self.broker)
        self.broker["funds"]["cash_usd"] = 2000
        self.broker = seal_broker_observation(self.broker)
        self.assertIn("DAILY_RECONCILIATION_IDENTITY_MISMATCH", self.bind()["blockers"])
        self.broker = original
        self.inputs["qualification"]["observation_hash"] = "a" * 64
        self.assertIn("QUALIFICATION_SNAPSHOT_MISMATCH", self.bind()["blockers"])
        self.inputs["qualification"]["observation_hash"] = self.broker["observation_hash"]
        self.payload["event"]["source_evidence_pack_hash"] = "a" * 64
        self.assertIn("DAILY_BRIDGE_EVIDENCE_MISMATCH", self.bind()["blockers"])

    def test_capital_bridge_tampering_and_unverified_pack_are_rejected(self):
        self.prepare()
        original = deepcopy(self.payload)
        self.payload["capital_state"]["cash"]["available_usd"] = 9999
        self.assertIn("DAILY_BRIDGE_CAPITAL_MISMATCH", self.bind()["blockers"])
        self.payload = original
        self.pack["generated_at_ms"] -= 1
        self.assertIn("DAILY_SOURCE_CLOCK_MISMATCH", self.bind()["blockers"])
        self.pack["generated_at_ms"] = NOW
        self.pack["evidence_pack_hash"] = "a" * 64
        self.assertIn("DAILY_EVIDENCE_HASH_INVALID", self.bind()["blockers"])

    def test_rehashed_market_context_cannot_borrow_the_original_pack_hash(self):
        self.prepare()
        self.payload["market_context"]["generated_at_ms"] -= 1
        self.payload["bridge_payload_hash"] = c.digest({k: v for k, v in self.payload.items() if k != "bridge_payload_hash"})
        self.assertIn("DAILY_BRIDGE_PROJECTION_MISMATCH", self.bind()["blockers"])

    def test_missing_qualification_fees_and_instruments_never_create_current_funds(self):
        self.inputs.pop("qualification")
        self.inputs.pop("fees")
        self.inputs.pop("instruments")
        self.prepare()
        result = self.bind()
        self.assertEqual(result["state"], "SOURCE_BOUND", result)
        self.assertIsNone(result["source"]["qualification"])
        self.assertEqual(result["source"]["fees"], [])
        self.assertEqual(result["source"]["instruments"], [])
        self.assertEqual(result["claim_states"]["spending_cap"]["state"], "BLOCKED")
        self.assertIsNone(result["claim_states"]["spending_cap"]["amount_usd"])

    def test_partial_broker_blocks_funds_but_retains_independent_hold(self):
        self.broker["scope"]["funds_complete"] = False
        self.broker = seal_broker_observation(self.broker)
        self.inputs["qualification"]["observation_hash"] = self.broker["observation_hash"]
        self.inputs["task"]["scopes"][0]["exposure"] = "EXISTING"
        self.prepare()
        result = self.bind()
        self.assertEqual(result["claim_states"]["spending_cap"]["state"], "BLOCKED")
        hold = c.validate_recommendation(recommendation(item("HOLD")), result["source"], at_ms=NOW)
        self.assertEqual(hold["items"][0]["validation_state"], "VALIDATED")

    def test_stale_and_missing_broker_are_not_promoted_to_cash(self):
        for broker in (None, synthetic_observation(NOW - MAX_AGE_MS - 1)):
            with self.subTest(missing=broker is None):
                self.broker = broker
                self.inputs.pop("qualification", None)
                self.prepare()
                result = self.bind()
                self.assertEqual(result["state"], "SOURCE_BOUND", result)
                self.assertEqual(result["claim_states"]["spending_cap"]["state"], "BLOCKED")
                self.assertIsNone(result["claim_states"]["spending_cap"]["amount_usd"])
                self.temp.cleanup()
                self.temp = tempfile.TemporaryDirectory()
                self.addCleanup(self.temp.cleanup)
                self.root = Path(self.temp.name)

    def test_evidence_clock_cannot_be_relabelled_or_expired(self):
        self.prepare()
        self.inputs["evidence_validity"]["as_of_ms"] = NOW - 1
        self.assertIn("EVIDENCE_CLOCK_RELABEL_FORBIDDEN", self.bind()["blockers"])
        self.inputs["evidence_validity"]["as_of_ms"] = NOW
        self.inputs["evidence_validity"]["valid_until_ms"] = NOW
        self.assertEqual(self.bind()["state"], "BLOCKED")

    def test_absent_task_is_explicitly_blocked_without_invented_scope(self):
        self.prepare()
        self.inputs.pop("task")
        result = self.bind()
        self.assertIsNone(result["source"])
        self.assertIn("FULL_DECISION_TASK_AND_VALIDITY_REQUIRED", result["blockers"])

    def test_cli_one_capture_to_mock_receipt_notification_replay_and_clock_only_refresh(self):
        private = self.root / "private"
        private.mkdir()
        intent_path = private / "capital-intent.json"
        inputs_path = private / "capital-decision-inputs.json"
        source_output = private / "capital-decision-source.json"
        evidence = self.root / "evidence.json"
        outbox = self.root / "outbox"
        intent_path.write_text(json.dumps(self.intent), encoding="utf-8")
        inputs_path.write_text(json.dumps(self.inputs), encoding="utf-8")
        # This unrelated retained snapshot must not participate in a live capture.
        (private / "broker-capital-observation.json").write_text(
            json.dumps(synthetic_observation(NOW - 20_000)), encoding="utf-8")
        args = ["--registry", str(fixture.REGISTRY_PATH), "--observation-db", str(self.root / "cli.sqlite"),
            "--output", str(evidence), "--private-profile", str(private / "missing-profile.json"),
            "--observe-broker-capital", "--user-capital-intent", str(intent_path),
            "--capital-decision-inputs", str(inputs_path), "--capital-source-output", str(source_output),
            "--source-main-sha", MAIN, "--handoff-output", str(self.root / "handoff.json"),
            "--handoff-ledger", str(self.root / "cli-handoff.jsonl"), "--bridge-outbox-dir", str(outbox)]
        clock = [NOW]
        def offline_daily(registry, **kwargs):
            kwargs.update(fetch_overrides=self.market.overrides, liquidation_aggregate_payload=self.market.aggregate(),
                now_ms=clock[0], generated_at_ms=clock[0], dvol_regime_runner=None,
                transition_diagnostic_runner=None, btc_entry_gate_runner=None)
            return run_daily_evidence(registry, **kwargs)
        capture = Mock(return_value=self.broker)
        with patch("crt_radar.broker_capital_observation.capture_ibkr_capital", capture), \
             patch("crt_radar.daily_evidence_runner.run_daily_evidence", side_effect=offline_daily), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
            capture.assert_called_once_with()
            bound = json.loads(source_output.read_text(encoding="utf-8"))
            self.assertEqual(bound["state"], "SOURCE_BOUND", bound)
            source_path = Path(bound["source_path"])
            original_source = source_path.read_bytes()
            source = json.loads(original_source)
            pack = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(source["broker_observation"], pack["private_context"]["profile"]["capital_reconciliation"]["broker_observed"])
            self.assertEqual(source["broker_observation"], self.broker)
            rec = recommendation(item("WAIT", wait_kind="EVIDENCE_BLOCKED", blockers=["等待正式估值補證據"]))
            transport = Mock(return_value=provider_response(rec))
            event_path = outbox / f'{bound["event_id"]}.json'
            delivered = deliver_event(event_path, self.root / "transport", transport=transport,
                notification_state_dir=self.root / "notifications", now_ms=NOW,
                capital_source=source, current_main_sha=MAIN)
            self.assertEqual(delivered["state"], "DELIVERED", delivered)
            presenter = Mock(return_value=1)
            notice_path = next((self.root / "notifications").glob("*.json"))
            self.assertEqual(present_from_transport(notice_path, self.root / "transport",
                presenter=presenter, now_ms=NOW, current_capital_source=source,
                current_capital_state=pack)["state"], "DELIVERED")
            replay = deliver_event(event_path, self.root / "transport", transport=transport,
                notification_state_dir=self.root / "notifications", now_ms=NOW + 1,
                capital_source=source, current_main_sha=MAIN)
            self.assertEqual(replay["state"], "ALREADY_DELIVERED", replay)
            self.assertEqual(present_from_transport(notice_path, self.root / "transport",
                presenter=presenter, now_ms=NOW + 1, current_capital_source=source,
                current_capital_state=pack)["state"], "ALREADY_DELIVERED")
            transport.assert_called_once()
            presenter.assert_called_once()
            clock[0] += 1
            refreshed = deepcopy(self.broker)
            refreshed["observed_at_ms"] += 1
            refreshed["started_at_ms"] += 1
            capture.return_value = seal_broker_observation(refreshed)
            self.assertEqual(main(args), 0)
            self.assertEqual(capture.call_count, 2)
            self.assertEqual(len(list(outbox.glob("*.json"))), 1)
            self.assertEqual(source_path.read_bytes(), original_source)
            latest = json.loads(source_output.read_text(encoding="utf-8"))
            self.assertIsNone(latest["source"])
            self.assertIn("NO_NEW_FULL_DECISION_EVENT_SOURCE_NOT_REBOUND", latest["blockers"])


if __name__ == "__main__":
    unittest.main()
