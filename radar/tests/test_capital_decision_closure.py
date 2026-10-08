"""Deterministic synthetic capital fixtures; never live account facts/advice."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from crt_radar import capital_decision_closure as c
from crt_radar.broker_capital_observation import seal_broker_observation
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_handoff import build_minimized_bridge_payload
from crt_radar.gpt_transport_worker import deliver_event
from crt_radar.gpt_notification_boundary import present, present_from_transport
from crt_radar.openai_responses_adapter_contract import SMOKE_MODEL, validate_request_envelope
from tests.test_full_bridge_budget import captured_pack, handoff_for
from tests.test_broker_capital_observation import synthetic_observation, order

NOW = 1790866561134
MAIN = "5519a613be9b829eb6518942494f68f2363dee92"


def source_fixture(payload=None, at=NOW):
    broker = synthetic_observation(at, funds={"cash_usd": 1000, "available_funds_usd": 800, "settled_cash_usd": 900})
    clock = {"as_of_ms": at, "valid_until_ms": at + 240_000, "source_ref": "synthetic:qualified-account-facts"}
    return {"source_main_sha": MAIN,
        "bridge_payload_hash": payload["bridge_payload_hash"] if payload else "a" * 64,
        "evidence_lineage": payload["event"]["source_evidence_pack_hash"] if payload else "b" * 64,
        "evidence_validity": {**clock, "source_ref": "synthetic:historical-evidence-validity"},
        "broker_observation": broker,
        "user_intent": {"version": "synthetic-intent-1", "source": "USER_CONFIRMED",
            "confirmed_at_ms": at, "reserved_usd": 100, "no_leverage": True},
        "qualification": {**clock, "observation_hash": broker["observation_hash"],
            "cash_semantics": "USD_SECURITIES_SETTLED_NONBORROWED_GROSS_OF_OPEN_ORDERS",
            "available_funds_orders": "INCLUDED", "restricted_cash_usd": 0,
            "position_restrictions": {"MSTR": 0, "STRC": 0}, "open_buy_fee_upper_bound_usd": 2},
        "instruments": [{**clock, "asset": a, "asset_class": "US_SECURITY", "currency": "USD", "quantity_step": 1}
                        for a in ("MSTR", "STRC", "ASST", "SATA")],
        "fees": [{**clock, "source_ref": "synthetic:fee-bound", "asset": a, "side": side,
                  "quantity_max": 100, "upper_bound_usd": 2} for a in ("MSTR", "STRC", "ASST", "SATA") for side in ("BUY", "SELL")],
        "posture": {**clock, "context_hash": "c" * 64, "formal_season": "SPRING",
                    "research_state": "RESEARCH_ONLY", "rail": "SPRING", "contradictions": ["synthetic:valuation-risk"], "blockers": []},
        "task": {**clock, "task_id": "synthetic-us-closure", "replaces": None,
                 "scopes": [{"decision_scope": "MSTR-addition", "asset": "MSTR", "exposure": "PROPOSED_CHANGE"}]},
        "governance": dict(c.LOCKS)}


def current_capital_pack(source, *, at=NOW):
    """Sealed current synthetic observation, separate from an event source."""
    from crt_radar.broker_capital_observation import reconcile_capital
    from crt_radar.private_profile import apply_broker_capital_state
    intent = source.get("user_intent") or {}
    legacy = {"source": "USER_CONFIRMED", "confirmed_at_ms": intent.get("confirmed_at_ms", at),
              "reserved_usd": intent.get("reserved_usd", 0), "plan_policy": "CANCEL_ALL_NO_REPLACEMENT"}
    pack = {"generated_at_ms": at,
            "private_context": apply_broker_capital_state(None,
                reconcile_capital(source.get("broker_observation"), legacy, at_ms=at))}
    pack["private_context"]["profile"]["full_decision_intent"] = deepcopy(source.get("user_intent"))
    pack["evidence_pack_hash"] = c.digest(pack)
    return pack


def leg(action="BUY", asset="MSTR", quantity=3, leg_id="leg1", **changes):
    return {"leg_id": leg_id, "asset": asset, "action": action, "quantity": quantity,
        "price_condition": "僅在限價內成交，條件失效則重新判斷", "order_type": "LIMIT",
        "limit_price_usd": 100, "dependent_legs": [], **changes}


def item(action="BUY", asset="MSTR", scope="MSTR-addition", **changes):
    return {"decision_scope": scope, "asset": asset, "action": action,
        "reason": "合成情境：相較現金替代方案，有限部位提供較佳非對稱性",
        "supporting_evidence": ["bridge"], "contradictions": ["估值仍可能壓縮"],
        "applicability": "僅適用此合成資料快照與所列條件", "invalidation": "健康惡化或資本快照改變",
        "next_trigger": "下一次健康證據更新或價格條件失效時重判", "blockers": [],
        "wait_kind": "ACTIVE_WAIT" if action == "WAIT" else None,
        "legs": [leg(action, asset)] if action in ("BUY", "SELL") else [], **changes}


def recommendation(*items):
    return {"contract_version": c.VERSION, "task_id": "synthetic-us-closure", "items": list(items or (item(),))}


def match_scopes(source, rec):
    source["task"]["scopes"] = [{"decision_scope": i["decision_scope"], "asset": i["asset"],
        "exposure": "EXISTING" if i["action"] in ("HOLD", "SELL", "ROTATE") else "PROPOSED_CHANGE"} for i in rec["items"]]


def set_orders(source, orders):
    broker = deepcopy(source["broker_observation"])
    broker["open_orders"] = orders
    source["broker_observation"] = seal_broker_observation(broker)
    source["qualification"]["observation_hash"] = source["broker_observation"]["observation_hash"]


def provider_response(rec):
    return {"id": "resp_synthetic", "model": SMOKE_MODEL, "status": "completed", "output": [
        {"type": "message", "status": "completed", "content": [{"type": "output_text", "text": json.dumps(rec, ensure_ascii=False)}]}]}


def complete_capacity_diagnostic(root):
    """Observe the rejected local object without relaxing a single size check."""
    from tests.test_capital_posture_context import fixture
    from tests.test_full_bridge_budget import bind_pack
    from crt_radar.capital_posture_context import build_capital_posture_context
    from crt_radar import gpt_handoff as h
    inputs, organ_pack, _ = fixture()
    evidence = captured_pack()
    from crt_radar.portfolio_allocation_context import _valuation_evidence
    # Derive every valuation view from the exact same captured synthetic facts.
    # Their missing qualification remains BLOCKED; do not fabricate provenance.
    organ_pack["portfolio_allocation_context"]["valuation_evidence"] = _valuation_evidence(evidence)
    for key in ("common_equity_health", "portfolio_allocation_context"):
        evidence[key] = organ_pack[key]
    bind_pack(evidence)
    at = evidence["generated_at_ms"]
    inputs["as_of_ms"] = at
    inputs["research_evidence_pack_hash"] = evidence["evidence_pack_hash"]
    inputs["current_rail"]["parent_evidence_pack_hash"] = evidence["evidence_pack_hash"]
    inputs["current_rail"]["valid_until_ms"] = at + 240_000
    posture = build_capital_posture_context(inputs, evidence, None)
    seen, size = [], h._bridge_size
    def observe(value):
        if isinstance(value, dict) and "bridge_payload_hash" in value:
            seen.append(deepcopy(value))
        return size(value)
    with patch.object(h, "_bridge_size", side_effect=observe):
        try:
            h.build_minimized_bridge_payload(evidence, handoff_for(evidence, root))
        except ValueError as exc:
            if "unchanged 16 KiB ceiling" not in str(exc):
                raise
        else:
            raise AssertionError("Update capacity diagnosis: upstream now fits")
    payload = seen[-1]
    source = source_fixture(payload, at)
    source = c.build_source(payload=payload, posture_context=posture, at_ms=at,
        **{k: source[k] for k in ("source_main_sha", "broker_observation", "user_intent",
                                  "qualification", "instruments", "fees", "task", "evidence_validity")})
    projection = c.build_projection(payload, source, at_ms=at)
    return payload, source, {"bridge_bytes": size(payload), "capital_input_bytes": size(projection),
                            "ceiling_bytes": 16 * 1024}


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.source = source_fixture()

    def validate(self, rec=None):
        rec = rec or recommendation()
        match_scopes(self.source, rec)
        return c.validate_recommendation(rec, self.source, at_ms=NOW)

    def test_01_positive_buy(self):
        result = self.validate()
        trade = result["items"][0]["validated_legs"][0]
        self.assertEqual(trade["quantity"], 3)
        self.assertEqual(trade["validation_state"], "VALIDATED")
        self.assertEqual(result["current_spend_upper_bound_usd"], "302")
        self.assertEqual(result["spending_cap"]["amount_usd"], "700.00")

    def test_02_sell_full_and_partial(self):
        for qty in (3, 12):
            result = self.validate(recommendation(item("SELL", legs=[leg("SELL", quantity=qty)])))
            self.assertEqual(result["items"][0]["validated_legs"][0]["validation_state"], "VALIDATED")

    def test_03_rotation_does_not_create_current_cash(self):
        rec = recommendation(item("ROTATE", legs=[leg("SELL", quantity=10, leg_id="sale"),
            leg("BUY", asset="ASST", quantity=10, leg_id="purchase", dependent_legs=["sale"])]))
        result = self.validate(rec)
        self.assertEqual(result["current_spend_upper_bound_usd"], "0")
        buy = next(l for l in result["items"][0]["validated_legs"] if l["action"] == "BUY")
        self.assertEqual(buy["validation_state"], "DEPENDENT_CONDITIONAL")
        self.assertEqual(buy["capital_effect"]["current_capital_credit_usd"], "0")
        rec["items"][0]["legs"][1]["dependent_legs"] = []
        with self.assertRaisesRegex(ValueError, "ROTATION_DEPENDENCY"):
            self.validate(rec)

    def test_04_active_hold_and_05_active_wait(self):
        for action in ("HOLD", "WAIT"):
            result = self.validate(recommendation(item(action)))
            self.assertEqual(result["items"][0]["validation_state"], "VALIDATED")
            self.assertIn("NO-TRADE", c.render(result))

    def test_06_missing_cash_does_not_block_sell_or_hold(self):
        self.source["qualification"]["cash_semantics"] = None
        result = self.validate(recommendation(item("SELL"), item("HOLD", scope="MSTR-existing")))
        self.assertEqual(result["spending_cap"]["state"], "BLOCKED")
        self.assertTrue(all(i["validation_state"] == "VALIDATED" for i in result["items"]))

    def test_07_buy_order_hold_discloses_changing_exposure(self):
        set_orders(self.source, [order(quantity=5, filled_quantity=0, remaining_quantity=5)])
        result = self.validate(recommendation(item("HOLD")))
        self.assertTrue(result["items"][0]["open_order_handling"]["exposure_may_change"])
        self.assertIn('"remaining_quantity": 5.0', c.render(result))

    def test_08_sell_order_and_new_sell_share_position(self):
        set_orders(self.source, [order(side="SELL", quantity=10, filled_quantity=0, remaining_quantity=10)])
        with self.assertRaisesRegex(ValueError, "POSITION_REUSE_OR_EXCESS"):
            self.validate(recommendation(item("SELL")))

    def test_09_cancel_request_never_releases_cash(self):
        set_orders(self.source, [order(quantity=5, filled_quantity=0, remaining_quantity=5, cancel_requested=True)])
        cap = c.normalize_spending_cap(self.source, at_ms=NOW)
        self.assertEqual(cap["amount_usd"], "298.00")

    def test_10_hold_and_wait_distinct_scopes(self):
        result = self.validate(recommendation(item("HOLD", scope="MSTR-existing"), item("WAIT")))
        self.assertEqual(len(result["items"]), 2)

    def test_11_multi_asset_budget(self):
        rec = recommendation(item(legs=[leg(quantity=4)]), item(asset="ASST", scope="ASST-addition",
            legs=[leg(asset="ASST", quantity=4, leg_id="leg2")]))
        with self.assertRaisesRegex(ValueError, "SHARED_BUDGET"):
            self.validate(rec)

    def test_12_permutation_invariance(self):
        original = self.validate()
        self.source["instruments"].reverse()
        self.source["fees"].reverse()
        self.source["broker_observation"]["holdings"].reverse()
        self.assertEqual(original, self.validate())

    def test_13_unknown_fees_or_market_price_block_buy(self):
        self.source["fees"] = []
        result = self.validate()
        self.assertEqual(result["items"][0]["validated_legs"][0]["validation_state"], "BLOCKED")
        self.source = source_fixture()
        result = self.validate(recommendation(item(legs=[leg(order_type="MARKET", limit_price_usd=None)])))
        self.assertIn("quantity:PRICE_UPPER_BOUND_UNKNOWN", result["items"][0]["validated_legs"][0]["claim_blockers"])

    def test_14_stale_and_superseded(self):
        result = self.validate()
        with self.assertRaisesRegex(ValueError, "EXPIRED"):
            c.assert_current(result, self.source, at_ms=NOW + 240_000)
        self.source["task"]["task_id"] = "replacement"
        with self.assertRaisesRegex(ValueError, "SUPERSEDED"):
            c.assert_current(result, self.source, at_ms=NOW)

    def test_15_each_critical_mutation_invalidates_validation(self):
        for change in (lambda s: s["broker_observation"]["funds"].update(cash_usd=900),
                       lambda s: s["broker_observation"]["holdings"][0].update(quantity=1),
                       lambda s: s["broker_observation"]["open_orders"].append(order()),
                       lambda s: s.update(evidence_lineage="d" * 64),
                       lambda s: s["user_intent"].update(version="v2"),
                       lambda s: s["qualification"].update(restricted_cash_usd=100)):
            self.source = source_fixture()
            result = self.validate()
            change(self.source)
            with self.assertRaisesRegex(ValueError, "SUPERSEDED"):
                c.assert_current(result, self.source, at_ms=NOW)

    def test_no_hold_without_position(self):
        with self.assertRaisesRegex(ValueError, "HOLD_REQUIRES"):
            self.validate(recommendation(item("HOLD", asset="ASST")))

    def test_same_scope_conflict_rejected(self):
        rec = recommendation(item("HOLD"), item("SELL"))
        with self.assertRaises(ValueError):
            self.validate(rec)

    def test_missing_settled_cash_blocks_only_buy(self):
        b = deepcopy(self.source["broker_observation"])
        b["funds"]["settled_cash_usd"] = None
        self.source["broker_observation"] = seal_broker_observation(b)
        self.source["qualification"]["observation_hash"] = self.source["broker_observation"]["observation_hash"]
        self.assertEqual(self.validate()["items"][0]["validation_state"], "BLOCKED")
        self.assertEqual(self.validate(recommendation(item("SELL")))["items"][0]["validation_state"], "VALIDATED")

    def test_no_double_subtraction_from_available_funds(self):
        set_orders(self.source, [order(quantity=2, filled_quantity=0, remaining_quantity=2)])
        b = deepcopy(self.source["broker_observation"])
        b["funds"]["available_funds_usd"] = 500
        self.source["broker_observation"] = seal_broker_observation(b)
        self.source["qualification"]["observation_hash"] = self.source["broker_observation"]["observation_hash"]
        self.assertEqual(c.normalize_spending_cap(self.source, at_ms=NOW)["amount_usd"], "400.00")
        self.source["qualification"]["available_funds_orders"] = "EXCLUDED"
        self.assertEqual(c.normalize_spending_cap(self.source, at_ms=NOW)["amount_usd"], "198.00")

    def test_unknown_semantics_and_fee_reservation_are_not_zero(self):
        self.source["qualification"]["available_funds_orders"] = "UNKNOWN"
        self.assertEqual(self.validate()["spending_cap"]["state"], "BLOCKED")
        self.source = source_fixture()
        set_orders(self.source, [order()])
        self.source["qualification"]["open_buy_fee_upper_bound_usd"] = None
        self.assertEqual(self.validate()["spending_cap"]["state"], "BLOCKED")

    def test_sell_unknown_fees_only_blocks_net_proceeds(self):
        self.source["fees"] = []
        result = self.validate(recommendation(item("SELL")))
        trade = result["items"][0]["validated_legs"][0]
        self.assertEqual(trade["validation_state"], "VALIDATED")
        self.assertEqual(trade["capital_effect"]["exact_net_proceeds_usd"], None)
        self.assertIn("net_proceeds:FEE_UPPER_BOUND_UNKNOWN", trade["claim_blockers"])

    def test_duplicate_leg_and_invalid_rounding_rejected(self):
        rec = recommendation(item(), item(asset="ASST", scope="other", legs=[leg(asset="ASST")]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_LEG"):
            self.validate(rec)
        with self.assertRaisesRegex(ValueError, "QUANTITY_STEP"):
            self.validate(recommendation(item(legs=[leg(quantity=1.5)])))

    def test_formal_locks_and_action_enums(self):
        for action in ("TRIM", "REINFORCE", "HARVEST", "NO-TRADE"):
            with self.assertRaises(ValueError):
                self.validate(recommendation(item(action)))
        self.source["governance"]["production"] = "APPROVED"
        with self.assertRaisesRegex(ValueError, "FORMAL_LOCK"):
            self.validate()

    def test_source_fees_expiry_invalidates_old_validation(self):
        self.source["fees"][0]["valid_until_ms"] = NOW + 10
        result = self.validate()
        with self.assertRaisesRegex(ValueError, "ACTION_CRITICAL_FACT_EXPIRED"):
            c.assert_current(result, self.source, at_ms=NOW + 11)


class TransportClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        pack = captured_pack()
        self.payload = build_minimized_bridge_payload(pack, handoff_for(pack, self.root))
        self.source = source_fixture(self.payload)
        self.rec = recommendation(item("WAIT"))
        self.envelope = c.build_envelope(self.payload, self.source, at_ms=NOW)

    def test_representative_full_projection_capacity_and_privacy(self):
        validate_request_envelope(self.envelope)
        size = len(self.envelope["request_body"]["input"].encode())
        self.assertLessEqual(size, 16 * 1024)
        data = json.loads(self.envelope["request_body"]["input"])
        self.assertEqual(data["market_context"], self.payload["market_context"])
        self.assertEqual(data["issuer_ratio_observation"], self.payload["issuer_ratio_observation"])
        self.assertNotIn("average_cost_usd", data["capital"]["holdings"][0])
        self.assertEqual(self.envelope["request_body"]["max_output_tokens"], 1800)

    def test_complete_organs_offline_full_contract_preserves_smoke_capacity(self):
        payload, source, measurement = complete_capacity_diagnostic(self.root / "complete-capacity")
        self.assertGreater(measurement["bridge_bytes"], measurement["ceiling_bytes"])
        self.assertGreater(measurement["capital_input_bytes"], measurement["ceiling_bytes"])
        from crt_radar.gpt_handoff import expand_bridge_field_names
        expanded = expand_bridge_field_names(payload)["market_context"]
        for asset in ("MSTR", "ASST"):
            treasury = expanded["treasury_valuation_context"]
            valuation = {**treasury["common"], **treasury["assets"][asset]}
            allocation = expanded["portfolio_allocation_context"]["valuation_evidence"][asset]
            self.assertEqual(allocation["formal_action_critical_state"], valuation["formal_action_critical_state"])
            self.assertEqual(allocation["diluted_mnav"], valuation["diluted_mnav"])
            self.assertEqual(valuation["formal_action_critical_state"], "BLOCKED")
        with self.assertRaisesRegex(ValueError, "CAPACITY_EXCEEDED"):
            c.build_envelope(payload, source, at_ms=NOW)
        envelope = c.build_envelope(payload, source, at_ms=NOW, full_decision=True)
        validate_request_envelope(envelope)
        self.assertEqual(envelope["delivery_mode"], "OFFLINE_ONLY")
        self.assertEqual(envelope["measurement"]["request_body_utf8_bytes"],
                         len(json.dumps(envelope["request_body"], ensure_ascii=False).encode()))
        self.assertEqual(json.loads(envelope["request_body"]["input"])["market_context"], payload["market_context"])
        transport = Mock(return_value=provider_response(recommendation(item("WAIT"))))
        enqueue_bridge_payload(self.root / "diagnostic-outbox", payload)
        path = self.root / "diagnostic-outbox" / (payload["event"]["event_id"] + ".json")
        kw = dict(capital_source=source, current_main_sha=MAIN, now_ms=NOW, transport=transport,
                  notification_state_dir=self.root / "full-notices")
        self.assertEqual(deliver_event(path, self.root / "states", **kw)["state"], "DELIVERED")
        self.assertEqual(deliver_event(path, self.root / "states", **kw)["state"], "ALREADY_DELIVERED")
        transport.assert_called_once()
        notice = next((self.root / "full-notices").glob("*.json"))
        presenter = Mock(return_value=1)
        self.assertTrue(present_from_transport(notice, self.root / "states", presenter, now_ms=NOW,
                                              current_capital_source=source,
                                              current_capital_state=current_capital_pack(source))["presentation_performed"])
        present_from_transport(notice, self.root / "states", presenter, now_ms=NOW, current_capital_source=source,
                               current_capital_state=current_capital_pack(source))
        presenter.assert_called_once()

    def test_unqualified_valuation_cannot_support_capital_increase(self):
        with self.assertRaisesRegex(ValueError, "VALUATION_EVIDENCE_UNQUALIFIED"):
            c.validated_receipt(provider_response(recommendation()), self.envelope, at_ms=NOW)
        enqueue_bridge_payload(self.root / "valuation-outbox", self.payload)
        transport = Mock(return_value=provider_response(recommendation()))
        path = self.root / "valuation-outbox" / (self.payload["event"]["event_id"] + ".json")
        kw = dict(capital_source=self.source, current_main_sha=MAIN, now_ms=NOW, transport=transport,
                  notification_state_dir=self.root / "valuation-notices")
        self.assertEqual(deliver_event(path, self.root / "valuation-states", **kw)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(deliver_event(path, self.root / "valuation-states", **kw)["state"], "RECONCILIATION_REQUIRED")
        transport.assert_called_once()
        self.assertFalse(list((self.root / "valuation-notices").glob("*.json")))

    def test_same_event_smoke_and_capital_share_roots_without_collisions(self):
        enqueue_bridge_payload(self.root / "shared-outbox", self.payload)
        path = self.root / "shared-outbox" / (self.payload["event"]["event_id"] + ".json")
        for order in (("smoke", "capital"), ("capital", "smoke")):
            with self.subTest(order=order):
                root = self.root / order[0]
                transports = {mode: Mock(return_value=provider_response(self.rec)) for mode in order}
                for replay in (False, True):
                    for mode in order:
                        kw = dict(transport=transports[mode], now_ms=NOW,
                                  notification_state_dir=root / "notices")
                        if mode == "capital":
                            kw.update(capital_source=self.source, current_main_sha=MAIN)
                        result = deliver_event(path, root / "states", **kw)
                        self.assertEqual(result["state"], "ALREADY_DELIVERED" if replay else "DELIVERED")
                for transport in transports.values():
                    transport.assert_called_once()
                responses = list((root / "states").rglob("responses/*.json"))
                self.assertEqual(len(responses), 2)
                self.assertEqual(len({json.loads(p.read_text(encoding="utf-8"))["request"]["request_hash"] for p in responses}), 2)
                notices = list((root / "notices").glob("*.json"))
                self.assertEqual(len(notices), 2)
                presenter = Mock(return_value=1)
                for replay in (False, True):
                    for notice in notices:
                        result = present_from_transport(notice, root / "states", presenter, now_ms=NOW,
                                                        current_capital_source=self.source,
                                                        current_capital_state=current_capital_pack(self.source))
                        self.assertEqual(result["presentation_performed"], not replay)
                self.assertEqual(presenter.call_count, 2)

    def test_evidence_blocked_wait_is_presented_as_verified_non_trade(self):
        enqueue_bridge_payload(self.root / "blocked-outbox", self.payload)
        rec = recommendation(item("WAIT", wait_kind="EVIDENCE_BLOCKED", blockers=["缺少資格"] ))
        transport = Mock(return_value=provider_response(rec))
        result = deliver_event(self.root / "blocked-outbox" / (self.payload["event"]["event_id"] + ".json"),
            self.root / "blocked-states", capital_source=self.source, current_main_sha=MAIN, now_ms=NOW,
            transport=transport, notification_state_dir=self.root / "blocked-notices")
        self.assertEqual(result["state"], "DELIVERED")
        notice = next((self.root / "blocked-notices").glob("*.json"))
        stored = json.loads(notice.read_text(encoding="utf-8"))
        validated = stored["capital_validation"]["items"][0]
        self.assertEqual(validated["validation_state"], "VALIDATED_NON_TRADING_WAIT")
        self.assertEqual(validated["blockers"], ["缺少資格"])
        self.assertEqual(validated["validated_legs"], [])
        self.assertIn("不得交易", stored["output_text"])
        self.assertIn("等待補證據", stored["output_text"])
        presenter = Mock(return_value=1)
        for replay in (False, True):
            result = present_from_transport(notice, self.root / "blocked-states", presenter, now_ms=NOW,
                                            current_capital_source=self.source,
                                            current_capital_state=current_capital_pack(self.source))
            self.assertEqual(result["presentation_performed"], not replay)
        presenter.assert_called_once()
        transport.assert_called_once()

    def test_invalid_blocked_wait_never_becomes_verified_non_trade(self):
        for defect in ("missing_reason", "stale_evidence", "unknown_reference", "trade_leg", "wrong_scope", "missing_instrument"):
            with self.subTest(defect=defect):
                source = deepcopy(self.source)
                rec = recommendation(item("WAIT", wait_kind="EVIDENCE_BLOCKED", blockers=["缺少資格"]))
                if defect == "missing_reason":
                    rec["items"][0]["blockers"] = []
                elif defect == "stale_evidence":
                    source["evidence_validity"]["valid_until_ms"] = NOW
                elif defect == "unknown_reference":
                    rec["items"][0]["supporting_evidence"] = ["unknown"]
                elif defect == "trade_leg":
                    rec["items"][0]["legs"] = [leg()]
                elif defect == "wrong_scope":
                    source["task"]["scopes"][0]["exposure"] = "EXISTING"
                else:
                    source["instruments"] = []
                with self.assertRaises(ValueError):
                    envelope = c.build_envelope(self.payload, source, at_ms=NOW)
                    c.validated_receipt(provider_response(rec), envelope, at_ms=NOW)

    def test_blocked_trades_still_never_create_success_notifications(self):
        enqueue_bridge_payload(self.root / "trade-outbox", self.payload)
        for action in ("BUY", "SELL", "ROTATE"):
            with self.subTest(action=action):
                proposal = item(action, blockers=["缺少資格"])
                if action == "ROTATE":
                    proposal["legs"] = [leg("SELL", leg_id="sale"),
                        leg("BUY", asset="STRC", leg_id="purchase", dependent_legs=["sale"])]
                rec = recommendation(item("WAIT", scope="MSTR-evidence-wait",
                    wait_kind="EVIDENCE_BLOCKED", blockers=["待補估值"]), proposal)
                source = deepcopy(self.source)
                match_scopes(source, rec)
                result = deliver_event(self.root / "trade-outbox" / (self.payload["event"]["event_id"] + ".json"),
                    self.root / action / "states", capital_source=source, current_main_sha=MAIN, now_ms=NOW,
                    transport=Mock(return_value=provider_response(rec)), notification_state_dir=self.root / action / "notices")
                self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
                self.assertFalse(list((self.root / action / "notices").glob("*.json")))

    def test_execution_fact_references_cannot_replace_investment_evidence(self):
        for ref in (self.source["fees"][0]["source_ref"], self.source["instruments"][0]["source_ref"]):
            with self.subTest(ref=ref):
                rec = recommendation(item(supporting_evidence=[ref]))
                with self.assertRaisesRegex(ValueError, "INVESTMENT_EVIDENCE_REQUIRED"):
                    c.validated_receipt(provider_response(rec), self.envelope, at_ms=NOW)
                receipt = c.validated_receipt(provider_response(recommendation(
                    item("WAIT", supporting_evidence=["bridge", ref]))), self.envelope, at_ms=NOW)
                self.assertEqual(receipt["capital_validation"]["items"][0]["validation_state"], "VALIDATED")

    def test_posture_reference_does_not_bypass_blocked_asset_valuation(self):
        rec = recommendation(item(supporting_evidence=["posture"]))
        with self.assertRaisesRegex(ValueError, "VALUATION_EVIDENCE_UNQUALIFIED"):
            c.validated_receipt(provider_response(rec), self.envelope, at_ms=NOW)

    def test_legacy_capital_state_cannot_trigger_new_namespaced_send(self):
        # Reproduce the pre-fix durable send marker at the original root, both
        # before and after its response was persisted. Never resend either one.
        from crt_radar.gpt_transport_boundary import build_pending_state, _seal_state
        enqueue_bridge_payload(self.root / "legacy-outbox", self.payload)
        path = self.root / "legacy-outbox" / (self.payload["event"]["event_id"] + ".json")
        envelope = c.build_envelope(self.payload, self.source, at_ms=NOW, full_decision=True)
        for has_response in (False, True):
            with self.subTest(has_response=has_response):
                root = self.root / str(has_response)
                root.mkdir()
                state = _seal_state({**build_pending_state(self.payload), "request_hash": envelope["request_hash"]})
                (root / path.name).write_text(json.dumps(state), encoding="utf-8")
                if has_response:
                    (root / "responses").mkdir()
                    (root / "responses" / path.name).write_text(json.dumps({
                        "request": envelope, "response": provider_response(self.rec)}), encoding="utf-8")
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")}
                transport = Mock()
                result = deliver_event(path, root, capital_source=self.source, current_main_sha=MAIN,
                                       now_ms=NOW, transport=transport)
                self.assertEqual(result["state"], "RECONCILIATION_REQUIRED")
                self.assertEqual(result["reason"], "LEGACY_CAPITAL_STATE_REQUIRES_RECONCILIATION")
                transport.assert_not_called()
                self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")})

    def test_real_capital_dispatch_is_blocked_before_credentials_or_network(self):
        from crt_radar.gpt_transport_worker import send_response
        with patch("crt_radar.gpt_transport_worker.urlrequest.build_opener") as opener:
            with self.assertRaisesRegex(ValueError, "OFFLINE_ONLY"):
                send_response(c.build_envelope(self.payload, self.source, at_ms=NOW, full_decision=True))
            opener.assert_not_called()

    def test_capacity_failure_does_not_trim_counterevidence(self):
        self.source["posture"]["contradictions"].append("重要反證" * 5000)
        with self.assertRaisesRegex(ValueError, "CAPACITY"):
            c.build_envelope(self.payload, self.source, at_ms=NOW)

    def test_private_user_intent_and_local_paths_rejected(self):
        self.source["user_intent"]["name"] = "private name"
        with self.assertRaises(ValueError):
            c.build_envelope(self.payload, self.source, at_ms=NOW)
        self.source = source_fixture(self.payload)
        self.source["task"]["source_ref"] = "C:/private/account.json"
        with self.assertRaises(ValueError):
            c.build_envelope(self.payload, self.source, at_ms=NOW)

    def test_16_worker_persist_render_notification_and_dedupe(self):
        enqueue_bridge_payload(self.root / "outbox", self.payload)
        path = self.root / "outbox" / (self.payload["event"]["event_id"] + ".json")
        transport = Mock(return_value=provider_response(self.rec))
        kw = {"capital_source": self.source, "transport": transport, "now_ms": NOW,
              "current_main_sha": MAIN,
              "notification_state_dir": self.root / "notifications"}
        result = deliver_event(path, self.root / "states", **kw)
        self.assertEqual(result["state"], "DELIVERED")
        self.assertEqual(deliver_event(path, self.root / "states", **{**kw, "now_ms": NOW + 1})["state"], "ALREADY_DELIVERED")
        transport.assert_called_once()
        notice = next((self.root / "notifications").glob("*.json"))
        presenter = Mock(return_value=1)
        blocked = present(notice, presenter, now_ms=NOW)
        self.assertFalse(blocked["presentation_performed"])
        shown = present_from_transport(notice, self.root / "states", presenter, now_ms=NOW,
                                       current_capital_source=self.source, current_capital_state=current_capital_pack(self.source))
        self.assertTrue(shown["presentation_performed"])
        stored = json.loads(notice.read_text(encoding="utf-8"))
        self.assertEqual(presenter.call_args.args[0], c.render(stored["capital_validation"]))
        self.assertNotEqual(presenter.call_args.args[0], transport.return_value["output"][0]["content"][0]["text"])

    def test_stale_notification_is_not_displayed(self):
        from crt_radar.gpt_notification_boundary import ensure_pending
        receipt = c.validated_receipt(provider_response(self.rec), self.envelope, at_ms=NOW)
        ensure_pending(self.root, receipt)
        path = self.root / (next(r.name for r in self.root.glob("*.json") if r.name != "handoff.jsonl"))
        presenter = Mock(return_value=1)
        self.source["user_intent"]["version"] = "new-intent"
        result = present(path, presenter, now_ms=NOW, current_capital_source=self.source,
                         current_capital_state=current_capital_pack(self.source))
        self.assertEqual(result["state"], "CAPITAL_RECOMMENDATION_NOT_CURRENT")
        presenter.assert_not_called()

    def test_truncated_refused_and_duplicate_json_never_accepted(self):
        for response in ({**provider_response(self.rec), "status": "incomplete"},
                         {**provider_response(self.rec), "incomplete_details": {"reason": "max_output_tokens"}},
                         {**provider_response(self.rec), "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}):
            with self.assertRaises(ValueError):
                c.validated_receipt(response, self.envelope, at_ms=NOW)
        response = provider_response(self.rec)
        response["output"][0]["content"][0]["text"] = '{"task_id":"a","task_id":"b"}'
        with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON"):
            c.validated_receipt(response, self.envelope, at_ms=NOW)


if __name__ == "__main__":
    unittest.main()
