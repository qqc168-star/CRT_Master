"""Synthetic offline cases only; live acceptance never uses these observations."""
from __future__ import annotations

import io
import json
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from crt_radar.broker_capital_observation import (
    CONNECTED_SOURCE, MAX_AGE_MS, SOCKET_SOURCE, capture_ibkr_capital,
    main as broker_main, reconcile_capital, seal_broker_observation, validate_broker_observation,
)
from crt_radar.daily_evidence_runner import run_daily_evidence
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_handoff import _bridge_capital_state, build_minimized_bridge_payload
from crt_radar.gpt_transport_worker import validate_transport_payload
from crt_radar.plan_drift import evaluate_plan_drift
from crt_radar.portfolio_allocation_context import _portfolio_state
from crt_radar.private_profile import apply_broker_capital_state, load_private_profile, validate_private_profile
from tests.test_private_profile import capital_state_payload
from tests.test_full_bridge_budget import (
    bind_pack, canonical_bytes, captured_pack, handoff_for, semantic_payload, synthetic_daily_price_source,
)
from tests import test_daily_evidence_runner as daily_fixture

NOW = 1790930000000


def synthetic_observation(at=NOW, **changes):
    capture = {
        "source": SOCKET_SOURCE, "observed_at_ms": at, "started_at_ms": at - 100,
        "automatic_local_refresh": True,
        "scope": {"account_count": 1, "same_account_verified": True, "account_ready": True,
                  "positions_complete": True, "funds_complete": True, "orders_complete": True},
        "holdings": [{"asset": "STRC", "quantity": 75, "average_cost_usd": 96.5,
                      "currency": "USD", "security_type": "STK"},
                     {"asset": "MSTR", "quantity": 12, "average_cost_usd": 130,
                      "currency": "USD", "security_type": "STK"}],
        "funds": {"cash_usd": 1000, "available_funds_usd": 800, "settled_cash_usd": None},
        "open_orders": [],
    }
    capture.update(changes)
    return seal_broker_observation(capture)


def synthetic_intent(at=NOW):
    return {"source": "USER_CONFIRMED", "confirmed_at_ms": at - 1000,
            "reserved_usd": 0, "plan_policy": "CANCEL_ALL_NO_REPLACEMENT"}


def order(**changes):
    row = {"asset": "MSTR", "side": "BUY", "currency": "USD", "order_type": "LMT",
           "quantity": 5, "filled_quantity": 2, "remaining_quantity": 3, "limit_price_usd": 100}
    row.update(changes)
    return row


def private_context():
    return {"state": "AVAILABLE", "profile": validate_private_profile(capital_state_payload())}


class BrokerCapitalTests(unittest.TestCase):
    def test_missing_settled_cash_does_not_block_analysis(self):
        result = reconcile_capital(synthetic_observation(), synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertEqual(result["analysis_cash_budget_usd"], 800)
        self.assertIn("SETTLEMENT_DEPENDENT_EXECUTION_REQUIRES_EVIDENCE", result["execution_limitations"])

    def test_margin_available_funds_cannot_exceed_cash_budget(self):
        result = reconcile_capital(synthetic_observation(funds={"cash_usd": 250, "available_funds_usd": 5000}), synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["analysis_cash_budget_usd"], 250)

    def test_missing_available_funds_never_uses_buying_power(self):
        observation = synthetic_observation(funds={"cash_usd": 1000, "buying_power": 999999})
        result = reconcile_capital(observation, synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertIsNone(result["analysis_cash_budget_usd"])

        self.assertEqual(result["position_available_quantities"]["MSTR"], 12)
        self.assertNotIn("buying_power", json.dumps(observation))

    def test_user_reserve_is_subtracted_once(self):
        intent = synthetic_intent(); intent["reserved_usd"] = 150
        result = reconcile_capital(synthetic_observation(), intent, at_ms=NOW)
        self.assertEqual(result["analysis_cash_budget_usd"], 650)

    def test_existing_portfolio_amount_never_adds_reserve_to_observed_cash(self):
        for reserve in (150, 1500):
            with self.subTest(reserve=reserve):
                intent = synthetic_intent(); intent["reserved_usd"] = reserve
                current = apply_broker_capital_state(private_context(), reconcile_capital(
                    synthetic_observation(), intent, at_ms=NOW))
                portfolio = _portfolio_state(current, {"MSTR": 150, "STRC": 100})
                self.assertEqual(portfolio["cash_usd"], 1000)
                self.assertEqual(portfolio["total_portfolio_usd"], 10_300)

    def test_budget_is_floored_to_cents_and_never_rounded_up(self):
        result = reconcile_capital(synthetic_observation(funds={"cash_usd": 1.009, "available_funds_usd": 2}), synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["analysis_cash_budget_usd"], 1.00)

    def test_negative_cash_or_excess_reserve_produces_no_deployment(self):
        for cash, reserve in ((-50, 0), (100, 500)):
            with self.subTest(cash=cash):
                intent = synthetic_intent(); intent["reserved_usd"] = reserve
                result = reconcile_capital(synthetic_observation(funds={"cash_usd": cash, "available_funds_usd": 800}), intent, at_ms=NOW)
                self.assertEqual(result["analysis_cash_budget_usd"], 0)

    def test_remaining_buy_commitment_does_not_double_subtract_available_funds(self):
        result = reconcile_capital(synthetic_observation(open_orders=[order()]), synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["open_order_cash_commitment_usd"], 300)
        self.assertEqual(result["analysis_cash_budget_usd"], 700)
        # AvailableFunds already below cash less commitments must stay unchanged.
        observation = synthetic_observation(open_orders=[order()], funds={"cash_usd": 1000, "available_funds_usd": 600})
        self.assertEqual(reconcile_capital(observation, synthetic_intent(), at_ms=NOW)["analysis_cash_budget_usd"], 600)

    def test_partial_fill_does_not_recharge_filled_shares(self):
        result = reconcile_capital(synthetic_observation(open_orders=[order(quantity=10, filled_quantity=7, remaining_quantity=3)]), synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["open_order_cash_commitment_usd"], 300)
        self.assertEqual(result["broker_observed"]["holdings"][0]["quantity"], 12)

    def test_pending_sell_does_not_add_proceeds_and_reduces_free_quantity(self):
        result = reconcile_capital(synthetic_observation(open_orders=[order(side="SELL")]), synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["analysis_cash_budget_usd"], 800)
        self.assertEqual(result["position_available_quantities"]["MSTR"], 9)

    def test_unknown_order_occupancy_is_precisely_partial(self):
        for row in (order(order_type="MKT", limit_price_usd=None), order(remaining_quantity=None), order(filled_quantity=3)):
            with self.subTest(row=row):
                result = reconcile_capital(synthetic_observation(open_orders=[row]), synthetic_intent(), at_ms=NOW)
                self.assertEqual(result["state"], "PARTIAL")
                self.assertIsNone(result["analysis_cash_budget_usd"])
                self.assertEqual(len(result["broker_observed"]["holdings"]), 2)

    def test_incomplete_orders_block_precise_budget(self):
        observation = synthetic_observation(); observation["scope"]["orders_complete"] = False
        observation = seal_broker_observation(observation)
        result = reconcile_capital(observation, synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertIsNone(result["analysis_cash_budget_usd"])
        self.assertTrue(all(value is None for value in result["position_available_quantities"].values()))

    def test_missing_reserve_confirmation_does_not_inherit_old_reserve(self):
        result = reconcile_capital(synthetic_observation(), None, at_ms=NOW)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertIsNone(result["analysis_cash_budget_usd"])
        current = apply_broker_capital_state(private_context(), result)
        self.assertIsNone(current["profile"]["cash"]["reserved_usd"])
        drift = evaluate_plan_drift(private_context=current, layers={})
        self.assertEqual(drift["reason"], "CAPITAL_INTENT_UNCONFIRMED")

    def test_intent_cannot_be_inferred_or_future_dated(self):
        for updates in ({"source": "INFERRED"}, {"confirmed_at_ms": NOW + 1}, {"reserved_usd": -1}, {"plan_policy": "INHERIT"}):
            intent = synthetic_intent(); intent.update(updates)
            self.assertIsNone(reconcile_capital(synthetic_observation(), intent, at_ms=NOW)["analysis_cash_budget_usd"])

    def test_mult_account_and_account_not_ready_are_blocked(self):
        for changes in ({"account_count": 2}, {"same_account_verified": False}, {"account_ready": False}):
            observation = synthetic_observation(); observation["scope"].update(changes)
            self.assertEqual(validate_broker_observation(seal_broker_observation(observation), at_ms=NOW)["state"], "BLOCKED")

    def test_stale_clock_future_reversed_and_span_are_qualified(self):
        stale = validate_broker_observation(synthetic_observation(NOW - MAX_AGE_MS - 1), at_ms=NOW)
        self.assertEqual(stale["state"], "STALE")
        for start, end in ((NOW, NOW + 1), (NOW, NOW - 1), (NOW - 30_001, NOW)):
            observation = synthetic_observation(started_at_ms=start, observed_at_ms=end)
            self.assertEqual(validate_broker_observation(observation, at_ms=NOW)["state"], "BLOCKED")

    def test_tampered_proof_has_no_current_budget(self):
        observation = synthetic_observation(); observation["funds"]["cash_usd"] += 1
        result = reconcile_capital(observation, synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIsNone(result["analysis_cash_budget_usd"])

    def test_unknown_source_and_nonfinite_or_unsupported_positions_are_rejected(self):
        with self.assertRaises(ValueError):
            synthetic_observation(source="CHAT_TEXT")
        for updates in ({"quantity": float("nan")}, {"currency": "EUR"}, {"asset": "INVALID/@"}):
            row = deepcopy(synthetic_observation()["holdings"][0]); row.update(updates)
            with self.assertRaises(ValueError):
                synthetic_observation(holdings=[row])

    def test_privacy_allowlist_precedes_hashing_and_ignores_unapproved_fields(self):
        observation = synthetic_observation()
        polluted = deepcopy(observation)
        polluted["account_identifier"] = "PRIVATE_SENTINEL"
        polluted["holdings"][0]["credential"] = "PRIVATE_SENTINEL"
        polluted["funds"]["BASE"] = 1000
        self.assertEqual(seal_broker_observation(polluted), observation)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(reconcile_capital(polluted, synthetic_intent(), at_ms=NOW)))

    def test_connected_proof_never_claims_local_automatic_refresh(self):
        self.assertFalse(synthetic_observation(source=CONNECTED_SOURCE, automatic_local_refresh=True)["automatic_local_refresh"])

    def test_current_quantities_sync_runtime_strc_without_mutating_history(self):
        historical = private_context(); untouched = deepcopy(historical)
        result = reconcile_capital(synthetic_observation(), synthetic_intent(), at_ms=NOW)
        current = apply_broker_capital_state(historical, result)
        self.assertEqual(historical, untouched)
        self.assertEqual(current["profile"]["strc"]["shares"], 75)
        self.assertEqual(current["profile"]["historical_capital_snapshot"]["strc_shares"], 100)
        self.assertEqual(current["profile"]["derived"]["annual_cash_usd"], 900)
        self.assertNotEqual(current["profile"]["capital_state"]["source"], "USER_CONFIRMED")
        again = apply_broker_capital_state(current, result)
        self.assertEqual(again["profile"]["historical_capital_snapshot"]["strc_shares"], 100)

    def test_existing_profile_loader_discovers_private_sidecars_without_rewriting_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); profile_path = root / "portfolio.json"
            profile_path.write_text(json.dumps(capital_state_payload()), encoding="utf-8")
            before = profile_path.read_bytes()
            (root/"broker-capital-observation.json").write_text(json.dumps(synthetic_observation()), encoding="utf-8")
            (root/"capital-intent.json").write_text(json.dumps(synthetic_intent()), encoding="utf-8")
            with patch("crt_radar.private_profile.time.time", return_value=NOW/1000):
                current = load_private_profile(profile_path)
            self.assertEqual(profile_path.read_bytes(), before)
            self.assertEqual(current["profile"]["strc"]["shares"], 75)
            self.assertEqual(current["profile"]["cash"]["reserved_usd"], 0)
            self.assertEqual(current["profile"]["capital_reconciliation"]["state"], "AVAILABLE")

    def test_existing_profile_loader_never_refreshes_expired_sidecar_clock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); profile_path = root / "portfolio.json"
            profile_path.write_text(json.dumps(capital_state_payload()), encoding="utf-8")
            stale = synthetic_observation(NOW-MAX_AGE_MS-1)
            (root/"broker-capital-observation.json").write_text(json.dumps(stale), encoding="utf-8")
            (root/"capital-intent.json").write_text(json.dumps(synthetic_intent()), encoding="utf-8")
            with patch("crt_radar.private_profile.time.time", return_value=NOW/1000):
                current = load_private_profile(profile_path)
            state = current["profile"]["capital_reconciliation"]
            self.assertEqual(state["state"], "STALE")
            self.assertEqual(state["broker_observed"]["observed_at_ms"], stale["observed_at_ms"])
            self.assertTrue(all(value is None for value in state["position_available_quantities"].values()))
            self.assertIsNone(state["analysis_cash_budget_usd"])

    def test_pack_rechecks_retained_capital_at_pack_clock_without_losing_history(self):
        case = daily_fixture.DailyEvidenceRunnerTests(); case.setUp()
        now = daily_fixture.NOW_MS
        current = apply_broker_capital_state(private_context(), reconcile_capital(
            synthetic_observation(now), synthetic_intent(now), at_ms=now))
        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(case.registry, observation_db=Path(td)/"observations.sqlite",
                fetch_overrides=case.overrides, now_ms=now+MAX_AGE_MS+1, generated_at_ms=now+MAX_AGE_MS+1,
                private_context=current)
            profile = pack["private_context"]["profile"]
            self.assertEqual(profile["capital_state_status"]["state"], "STALE")
            self.assertEqual(profile["historical_capital_snapshot"]["strc_shares"], 100)
            self.assertEqual(_bridge_capital_state(pack["private_context"], generated_at_ms=pack["generated_at_ms"])["snapshot_state"], "STALE")

    def test_closed_strc_position_syncs_zero_without_legacy_positive_requirement(self):
        observation = synthetic_observation(holdings=[])
        current = apply_broker_capital_state(private_context(), reconcile_capital(observation, synthetic_intent(), at_ms=NOW))
        self.assertEqual(current["profile"]["strc"]["shares"], 0)
        self.assertEqual(current["profile"]["derived"]["annual_cash_usd"], 0)

    def test_cash_change_and_position_change_are_used_in_next_observation(self):
        first = synthetic_observation()
        changed = deepcopy(first); changed["holdings"][0]["quantity"] = 14
        changed["funds"].update(cash_usd=400, available_funds_usd=400)
        changed = seal_broker_observation(changed)
        result = reconcile_capital(changed, synthetic_intent(), at_ms=NOW)
        self.assertEqual(result["analysis_cash_budget_usd"], 400)
        self.assertEqual(result["position_available_quantities"]["MSTR"], 14)
        self.assertNotEqual(first["observation_hash"], changed["observation_hash"])

    def test_cancelled_plans_do_not_turn_into_cash_or_keep_historical_roles(self):
        result = reconcile_capital(synthetic_observation(), synthetic_intent(), at_ms=NOW)
        current = apply_broker_capital_state(private_context(), result)
        self.assertEqual(current["profile"]["plans"], [])
        self.assertEqual(current["profile"]["cash"]["available_usd"], 1000)
        self.assertEqual(current["profile"]["asset_roles"], {})
        self.assertIn("ASSET_ROLES_NOT_RECONFIRMED", result["execution_limitations"])

    def test_capital_bridge_rechecks_hash_and_preserves_both_authorities(self):
        result = reconcile_capital(synthetic_observation(), synthetic_intent(), at_ms=NOW)
        current = apply_broker_capital_state(private_context(), result)
        bridged = _bridge_capital_state(current, generated_at_ms=NOW)
        self.assertEqual(bridged["source_attribution"]["holdings_cost_cash"], "BROKER_OBSERVED")
        self.assertEqual(bridged["source_attribution"]["reserves_roles_plans"], "USER_CONFIRMED")
        self.assertEqual(bridged["reconciliation"]["strc"]["shares"], 75)
        self.assertEqual(bridged["active_plans"], [])
        current["profile"]["capital_reconciliation"]["analysis_cash_budget_usd"] += 1
        with self.assertRaises(ValueError):
            _bridge_capital_state(current, generated_at_ms=NOW)

    def test_capital_failure_stays_claim_scoped_in_bridge(self):
        malformed = synthetic_observation(); malformed["scope"] = None
        for observation in (None, {"capture_failed": True}, malformed,
                            {"capture_failed": True, "reason": "BROKER_ACCOUNT_SCOPE_UNCONFIRMED"},
                            synthetic_observation(NOW - MAX_AGE_MS - 1)):
            result = reconcile_capital(observation, synthetic_intent(), at_ms=NOW)
            current = apply_broker_capital_state(private_context(), result)
            bridge = _bridge_capital_state(current, generated_at_ms=NOW)
            self.assertIn(bridge["snapshot_state"], {"BLOCKED", "STALE"})
            self.assertIsNone(bridge["reconciliation"]["analysis_cash_budget_usd"])
            if isinstance(observation, dict) and observation.get("reason"):
                self.assertEqual(bridge["reason"], observation["reason"])

    def test_full_bridge_with_issuer_etf_capital_and_qualified_prices_fits_existing_limit(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack(); at = pack["generated_at_ms"]
            observation = synthetic_observation(at)
            observation["holdings"].append({"asset": "ASST", "quantity": 19,
                "currency": "USD", "security_type": "STK", "average_cost_usd": 24.123456789})
            current = reconcile_capital(seal_broker_observation(observation), synthetic_intent(at), at_ms=at)
            pack["private_context"] = apply_broker_capital_state(pack["private_context"], current)
            pack["qualified_equity_daily_source"] = synthetic_daily_price_source(at)
            bind_pack(pack)
            bridge = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
            self.assertLessEqual(len(canonical_bytes(bridge)), 16_384)
            validate_transport_payload(bridge)
            self.assertEqual(semantic_payload(bridge)["capital_state"]["reconciliation"]["analysis_cash_budget_usd"], 800)
            self.assertEqual(len(semantic_payload(bridge)["capital_state"]["holdings"]), 3)
            self.assertEqual(set(semantic_payload(bridge)["market_context"]["qualified_equity_prices"]["assets"]), {"MSTR", "ASST"})
            enqueue_bridge_payload(Path(td) / "outbox", bridge)
            self.assertIn("issuer_ratio_observation", bridge)
            self.assertEqual(bridge["authority"]["external_action_authority"], "NONE")

    def test_daily_runner_evidence_pack_uses_current_projection_and_cancelled_plans(self):
        case = daily_fixture.DailyEvidenceRunnerTests(); case.setUp()
        now = daily_fixture.NOW_MS
        with tempfile.TemporaryDirectory() as td:
            pack = run_daily_evidence(case.registry, observation_db=Path(td)/"observations.sqlite",
                fetch_overrides=case.overrides, now_ms=now, generated_at_ms=now,
                private_context=private_context(), broker_capital_observation=synthetic_observation(now),
                user_capital_intent=synthetic_intent(now))
            self.assertEqual(pack["private_context"]["profile"]["strc"]["shares"], 75)
            self.assertEqual(pack["plan_drift"]["state"], "NO_ACTIVE_PLAN")
            self.assertEqual(pack["action_output"], "NONE")
            self.assertEqual(pack["authority"]["production"], "NOT_APPROVED")


class SocketCaptureTests(unittest.TestCase):
    def fake_sdk(self, *, multiple=False, conflict=False, error_calls=(),
                 ready=True, connect_timeout=False, error_stage="connect"):
        calls = []
        instances = []
        class Wrapper:
            pass
        class Client:
            def __init__(self, wrapper):
                self.wrapper = wrapper; self.connected = False
                instances.append(wrapper)
            def emit_errors(self):
                for args, kwargs in error_calls:
                    self.wrapper.error(*args, **kwargs)
            def connect(self, host, port, clientId):
                calls.append(("connect", host, port, clientId)); self.connected = True
                if connect_timeout:
                    raise TimeoutError("SYNTHETIC_CONNECTION_TIMEOUT")
                if error_stage == "connect":
                    self.emit_errors()
                if ready:
                    self.wrapper.nextValidId(1)
            def run(self):
                pass
            def reqManagedAccts(self):
                calls.append(("reqManagedAccts",)); self.wrapper.managedAccounts("scope-one,scope-two" if multiple else "scope-one")
            def reqPositions(self):
                calls.append(("reqPositions",)); self.wrapper.position("scope-one", contract, 25, 95)
                self.wrapper.positionEnd()
            def reqAccountSummary(self, reqId, group, tags):
                calls.append(("reqAccountSummary", tags))
                for tag in ("TotalCashValue", "AvailableFunds"):
                    self.wrapper.accountSummary(reqId, "scope-one", tag, "600", "USD")
                self.wrapper.accountSummaryEnd(reqId)
            def reqAllOpenOrders(self):
                calls.append(("reqAllOpenOrders",)); self.wrapper.openOrderEnd()
            def reqAccountUpdates(self, subscribe, acct):
                calls.append(("reqAccountUpdates", subscribe))
                if subscribe:
                    self.wrapper.updateAccountValue("AccountReady", "true", "", acct)
                    self.wrapper.updateAccountValue("$LEDGER-CashBalance", "600", "BASE", acct)
                    self.wrapper.updateAccountValue("$LEDGER-CashBalance", "600", "USD", acct)
                    self.wrapper.updatePortfolio(contract, 26 if conflict else 25, 100, 2500, 95, 0, 0, acct)
                    if error_stage == "updates":
                        self.emit_errors()
                    self.wrapper.accountDownloadEnd(acct)
            def isConnected(self):
                return self.connected
            def cancelPositions(self):
                calls.append(("cancelPositions",))
            def cancelAccountSummary(self, reqId):
                calls.append(("cancelAccountSummary",))
            def disconnect(self):
                calls.append(("disconnect",)); self.connected = False
        contract = types.SimpleNamespace(conId=1, symbol="STRC", currency="USD", secType="STK")
        modules = {"ibapi": types.ModuleType("ibapi"), "ibapi.client": types.ModuleType("ibapi.client"),
                   "ibapi.wrapper": types.ModuleType("ibapi.wrapper")}
        modules["ibapi.client"].EClient = Client; modules["ibapi.wrapper"].EWrapper = Wrapper
        modules["ibapi.client"].instances = instances
        return modules, calls

    def assert_fatal_callback(self, args, kwargs=None, *, stage="connect"):
        modules, calls = self.fake_sdk(error_calls=[(args, kwargs or {})], error_stage=stage)
        output = io.StringIO()
        with patch.dict("sys.modules", modules), redirect_stdout(output), redirect_stderr(output):
            with self.assertRaisesRegex(RuntimeError, "^BROKER_CAPTURE_SOURCE_CONFLICT$") as caught:
                capture_ibkr_capital()
        self.assertEqual(calls[-1], ("disconnect",))
        self.assertNotIn("PRIVATE_SENTINEL", output.getvalue() + str(caught.exception))
        return modules["ibapi.client"].instances[0], calls

    def test_legacy_three_argument_error_preserves_502(self):
        app, _ = self.assert_fatal_callback((-1, 502, "PRIVATE_SENTINEL"))
        self.assertEqual(app.errors, [502])

    def test_legacy_four_argument_error_preserves_code_and_discards_reject_json(self):
        app, _ = self.assert_fatal_callback((-1, 502, "PRIVATE_SENTINEL", '{"account":"PRIVATE_SENTINEL"}'))
        self.assertEqual(app.errors, [502])

    def test_new_four_argument_error_uses_code_not_error_time(self):
        app, _ = self.assert_fatal_callback((-1, 2104, 502, "PRIVATE_SENTINEL"))
        self.assertEqual(app.errors, [502])

    def test_new_five_argument_error_preserves_code_and_discards_reject_json(self):
        app, _ = self.assert_fatal_callback((-1, NOW, 502, "PRIVATE_SENTINEL", '{"order":"PRIVATE_SENTINEL"}'))
        self.assertEqual(app.errors, [502])

    def test_nonfatal_codes_remain_nonfatal_for_all_callback_versions(self):
        for code in (2104, 2106, 2107, 2108, 2158, 2119, 1102):
            for args in ((-1, code, "PRIVATE_SENTINEL"),
                         (-1, code, "PRIVATE_SENTINEL", "PRIVATE_SENTINEL"),
                         (-1, 502, code, "PRIVATE_SENTINEL"),
                         (-1, NOW, code, "PRIVATE_SENTINEL", "PRIVATE_SENTINEL")):
                with self.subTest(args=args):
                    modules, calls = self.fake_sdk(error_calls=[(args, {})])
                    with patch.dict("sys.modules", modules):
                        observation = capture_ibkr_capital()
                    self.assertEqual(validate_broker_observation(observation, at_ms=observation["observed_at_ms"])["state"], "AVAILABLE")
                    self.assertEqual(modules["ibapi.client"].instances[0].errors, [])
                    self.assertNotIn("PRIVATE_SENTINEL", json.dumps(observation))
                    self.assertIn(("reqAccountUpdates", False), calls)

    def test_optional_reject_json_keyword_preserves_both_versions(self):
        for args in ((-1, 502, "PRIVATE_SENTINEL"), (-1, NOW, 502, "PRIVATE_SENTINEL")):
            with self.subTest(args=args):
                app, _ = self.assert_fatal_callback(args, {"advancedOrderRejectJson": "PRIVATE_SENTINEL"})
                self.assertEqual(app.errors, [502])

    def test_unknown_and_ambiguous_formats_block_even_nonfatal_looking_codes(self):
        malformed = [(), (-1,), (-1, 2104), (-1, 2104, 502, 2158),
                     (-1, 2104, "PRIVATE_SENTINEL", 502),
                     (-1, "2104", "PRIVATE_SENTINEL"),
                     (-1, NOW, "2104", "PRIVATE_SENTINEL"),
                     (-1, "timestamp", 2104, "PRIVATE_SENTINEL"),
                     (True, 2104, "PRIVATE_SENTINEL"), (-1, True, "PRIVATE_SENTINEL"),
                     (-1, False, 2104, "PRIVATE_SENTINEL"),
                     (-1, NOW, True, "PRIVATE_SENTINEL"),
                     (-1, 2104, None), (-1, NOW, 2104, None),
                     (-1, 2104, "PRIVATE_SENTINEL", {"account": "PRIVATE_SENTINEL"}),
                     (-1, NOW, 2104, "PRIVATE_SENTINEL", None),
                     (2 ** 31, 2104, "PRIVATE_SENTINEL"),
                     (-1, 2 ** 31, "PRIVATE_SENTINEL"), (-1, -1, "PRIVATE_SENTINEL"),
                     (-1, -1, 2104, "PRIVATE_SENTINEL"),
                     (-1, 2 ** 63, 2104, "PRIVATE_SENTINEL"),
                     (-1, NOW, 2104, "PRIVATE_SENTINEL", "", "extra")]
        for args in malformed:
            with self.subTest(args=args):
                app, _ = self.assert_fatal_callback(args)
                self.assertTrue(app.conflict)
                self.assertEqual(app.errors, [])

    def test_unknown_or_duplicate_keywords_block_without_private_diagnostics(self):
        for args, kwargs in [((-1, 2104, "PRIVATE_SENTINEL"), {"unknown": "PRIVATE_SENTINEL"}),
                             ((-1, 2104, "PRIVATE_SENTINEL"), {"advancedOrderRejectJson": None}),
                             ((-1, 2104, "PRIVATE_SENTINEL", ""), {"advancedOrderRejectJson": "PRIVATE_SENTINEL"})]:
            with self.subTest(args=args, kwargs=kwargs):
                app, _ = self.assert_fatal_callback(args, kwargs)
                self.assertTrue(app.conflict)

    def test_fatal_callback_after_subscription_still_unsubscribes_and_disconnects(self):
        app, calls = self.assert_fatal_callback((-1, 502, "PRIVATE_SENTINEL"), stage="updates")
        self.assertEqual(app.errors, [502])
        self.assertIn(("reqAccountUpdates", False), calls)
        self.assertIn(("cancelPositions",), calls)
        self.assertIn(("cancelAccountSummary",), calls)

    def test_connection_and_handshake_timeouts_do_not_write_capital_observation(self):
        for changes, exception in [({"connect_timeout": True}, TimeoutError), ({"ready": False}, RuntimeError)]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as td:
                modules, calls = self.fake_sdk(**changes)
                target = Path(td) / "observation.json"
                original_capture = capture_ibkr_capital
                with patch.dict("sys.modules", modules), patch("sys.argv", ["broker", "--output", str(target)]), \
                     patch("crt_radar.broker_capital_observation.capture_ibkr_capital", side_effect=lambda: original_capture(timeout_seconds=0.001)):
                    with self.assertRaises(exception):
                        broker_main()
                self.assertFalse(target.exists())
                self.assertEqual(calls[-1], ("disconnect",))
                self.assertEqual(validate_broker_observation(None, at_ms=NOW)["state"], "BLOCKED")

    def test_collector_explicit_tags_completed_scope_prefix_and_only_read_requests(self):
        modules, calls = self.fake_sdk()
        with patch.dict("sys.modules", modules):
            observation = capture_ibkr_capital()
        self.assertEqual(observation["funds"]["cash_usd"], 600)
        self.assertIsNone(observation["funds"]["settled_cash_usd"])
        self.assertEqual(observation["holdings"][0]["quantity"], 25)
        self.assertEqual(calls[0][1:3], ("127.0.0.1", 7496))
        self.assertGreater(calls[0][3], 0)
        self.assertIn(("reqAccountSummary", "SettledCash,TotalCashValue,AvailableFunds,AccountType"), calls)
        self.assertIn(("reqAccountUpdates", False), calls)
        self.assertNotIn("scope-one", json.dumps(observation))
        self.assertNotIn("placeOrder", str(calls))

    def test_collector_refuses_multiple_accounts_and_inconsistent_partial_snapshot(self):
        for changes in ({"multiple": True}, {"conflict": True}):
            modules, calls = self.fake_sdk(**changes)
            with patch.dict("sys.modules", modules), self.assertRaises(RuntimeError):
                capture_ibkr_capital()
            self.assertEqual(calls[-1], ("disconnect",))


if __name__ == "__main__":
    unittest.main()
