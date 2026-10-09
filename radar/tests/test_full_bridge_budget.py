"""Offline captured public context with synthetic capital; never live evidence."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_transport_worker import validate_transport_payload
from crt_radar.gpt_handoff import (
    _compact_field_names, _compact_tranche_fields, _inherit_equal_authority,
    build_minimized_bridge_payload,
    build_full_decision_bridge_payload,
    expand_bridge_field_names, run_gpt_handoff_gate,
)
from crt_radar.mstr_asst_market_health import compact_issuer_ratio_observation
from crt_radar.mstr_asst_market_health_runtime import seal_runtime_source
from crt_radar.openai_responses_adapter_contract import build_request_envelope, SMOKE_MODEL
from crt_radar.plain_language_notice import build_plain_language_notice
from tests.test_gpt_handoff import bridge_pack, pack as handoff_pack
from tests.test_mstr_asst_gpt_wake_closure import market_health


FIXTURE = Path(__file__).parent / "fixtures" / "full_bridge_budget_market.json"
STALE_FIELDS = ["holdings.quantity", "cash.available_usd", "cash.reserved_usd",
                "active_plans", "tranche_budgets", "asset_roles"]
AUDIT_METRICS = {
    "core_inflation_acceleration", "real_policy_rate", "unemployment_deterioration",
    "market_cap_usd", "mvrv", "nupl", "realized_cap_30d_log_change", "realized_cap_usd",
    "close_minus_sma200_over_atr20", "return_20d_over_atr_vol", "sma50_minus_sma200_over_atr20",
    "mark_price", "open_interest_contracts",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def reverse_dict_order(value: object) -> object:
    if isinstance(value, dict):
        return {key: reverse_dict_order(child)
                for key, child in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reverse_dict_order(child) for child in value]
    return value


def captured_pack() -> dict:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = deepcopy(captured.get("public_projection", captured))
    synthetic = bridge_pack(handoff_pack(evidence_hash="a" * 64, requested=True))
    result["private_context"] = synthetic["private_context"]
    result["plan_drift"] = synthetic["plan_drift"]
    profile = result["private_context"]["profile"]
    for section in (profile, profile["capital_state"], profile["capital_state_status"]):
        section["snapshot_state"] = "STALE"
        section["STALE_CAPITAL_FIELDS"] = list(STALE_FIELDS)
    profile["holdings"][0]["cost_basis_usd"] = 1234.5
    # Bind this offline replay, including synthetic capital, independently of the
    # retained capture hash. Never claim synthetic capital is live evidence.
    material = {key: value for key, value in result.items() if key != "evidence_pack_hash"}
    result["evidence_pack_hash"] = hashlib.sha256(canonical_bytes(material)).hexdigest()
    return result


def handoff_for(pack: dict, root: Path) -> dict:
    result = run_gpt_handoff_gate(pack, build_plain_language_notice(pack),
                                 ledger_path=root / "handoff.jsonl")
    if result["state"] != "GPT_HANDOFF_READY":
        raise AssertionError(result["state"])
    return result


def synthetic_daily_price_source(generated: int) -> dict:
    """Offline test source only; never evidence of an actual market retrieval."""
    bars = {asset: [{"session_date": day, "open": close, "high": close + 1,
                    "low": close - 1, "close": close, "volume": 100.0,
                    "source_state": "IBKR_HISTORICAL_TRADES_RTH"}
                   for day in ("2026-09-29", "2026-09-30", "2026-10-02")]
            for asset, close in (("MSTR", 153.09), ("ASST", 29.41))}
    return seal_runtime_source(source_key="equity_daily", data=bars,
                               observed_at_ms=generated - 1)


def bind_pack(pack: dict) -> None:
    pack["evidence_pack_hash"] = hashlib.sha256(canonical_bytes(
        {key: value for key, value in pack.items() if key != "evidence_pack_hash"})).hexdigest()


def metric_facts(market: dict, layer: str, metric: str) -> dict:
    row = market["layers"][layer]["metrics"][metric]
    if isinstance(row, dict):
        return row
    as_of, quality = market["metric_metadata"][row[1]]
    return {"value": row[0], "as_of_ms": as_of, "quality_state": quality}


def semantic_payload(payload: dict) -> dict:
    """Expand declared keys/tranches and ONLY explicitly indexed lock fields."""
    result = expand_bridge_field_names(payload)
    market = result.get("market_context", {})
    columns = market.get("authority_field_values", [])

    def inherit(value):
        if isinstance(value, dict):
            for index in value.pop("authority_fields", []):
                key, literal = columns[index]
                if key in value and value[key] != literal:
                    raise AssertionError("Conflicting literal authority field")
                value[key] = deepcopy(literal)
            for child in list(value.values()):
                inherit(child)
        elif isinstance(value, list):
            for child in value:
                inherit(child)

    inherit(market)
    return result


class FullBridgeBudgetTests(unittest.TestCase):
    def test_full_issuer_bridge_passes_worker_with_legacy_payload_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack = captured_pack()
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, root))
            self.assertEqual(validate_transport_payload(payload),
                             (payload["event"]["event_id"], payload["bridge_payload_hash"]))
            legacy = deepcopy(payload)
            legacy.pop("issuer_ratio_observation")
            legacy.pop("bridge_payload_hash")
            legacy["bridge_payload_hash"] = hashlib.sha256(canonical_bytes(legacy)).hexdigest()
            validate_transport_payload(legacy)

    def test_worker_rejects_unknown_root_fields_and_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
            for change in ("extra", "missing"):
                candidate = deepcopy(payload)
                if change == "extra":
                    candidate["uncontracted_section"] = {"value": 1}
                else:
                    candidate.pop("capital_state")
                candidate.pop("bridge_payload_hash")
                candidate["bridge_payload_hash"] = hashlib.sha256(canonical_bytes(candidate)).hexdigest()
                with self.assertRaisesRegex(ValueError, "field set"):
                    validate_transport_payload(candidate)

    def test_worker_checks_encoded_names_and_raw_descriptor_text(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
            candidate = deepcopy(payload)
            codec = candidate["market_context"]["key_encoding"]
            first_token = codec[0][0]
            codec[1] = "broker_account|" + codec[1].split("|", 1)[1]
            candidate["market_context"][first_token] = "NEVER_EXPORT"
            candidate.pop("bridge_payload_hash")
            candidate["bridge_payload_hash"] = hashlib.sha256(canonical_bytes(candidate)).hexdigest()
            with self.assertRaises(ValueError):
                validate_transport_payload(candidate)
            candidate = deepcopy(payload)
            candidate["market_context"]["key_encoding"][2] = "private@example.test"
            candidate.pop("bridge_payload_hash")
            candidate["bridge_payload_hash"] = hashlib.sha256(canonical_bytes(candidate)).hexdigest()
            with self.assertRaisesRegex(ValueError, "Forbidden transport text"):
                validate_transport_payload(candidate)

    def test_qualified_prices_coexist_with_full_issuer_capital_etf_and_blocked_health(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            source = synthetic_daily_price_source(pack["generated_at_ms"])
            pack["qualified_equity_daily_source"] = source
            # Explicit blocked contexts remain blocked; price evidence is independent.
            pack["mstr_asst_market_health"] = {"state": "BLOCKED", "reason": "COMMANDER_PROOF_MISSING"}
            pack["premarket_market_data"] = {"state": "BLOCKED", "reason": "PREMARKET_PRICE_UNQUALIFIED",
                                            "battle_map": {"first_screen": []}}
            bind_pack(pack)
            original = deepcopy(pack)
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
            expanded = semantic_payload(payload)
            prices = expanded["market_context"]["qualified_equity_prices"]
            self.assertEqual(prices["source_hash"], source["data_hash"])
            self.assertEqual(prices["source_id"], source["source_id"])
            self.assertEqual(prices["observed_at_ms"], source["observed_at_ms"])
            self.assertEqual(prices["scope"], "LAST_COMPLETED_RTH_CLOSE_NOT_LIVE_QUOTE")
            for asset, value in (("MSTR", 153.09), ("ASST", 29.41)):
                row = prices["assets"][asset]
                self.assertEqual(row, {"state": "VALID", "price_usd": value,
                    "as_of_ms": 1790798400000, "session_date": "2026-09-30",
                    "session_state": "COMPLETE", "source_state": "IBKR_HISTORICAL_TRADES_RTH"})
            for section in ("mstr_asst_market_health", "premarket_market_data"):
                self.assertEqual(expanded["market_context"][section], pack[section])
            self.assertIn("btc_etf_evidence", expanded["market_context"])
            self.assertEqual(expanded["capital_state"]["snapshot_state"], "STALE")
            self.assertEqual(expanded["issuer_ratio_observation"], compact_issuer_ratio_observation(
                pack["issuer_ratio_observation"], generated_at_ms=pack["generated_at_ms"]))
            self.assertLess(len(canonical_bytes(payload)), 16384)
            validate_transport_payload(payload)
            self.assertEqual(build_request_envelope(payload, model=SMOKE_MODEL)["request_body"]["input"],
                             canonical_bytes(payload).decode("utf-8"))
            self.assertEqual(enqueue_bridge_payload(Path(td) / "outbox", payload)["state"], "OUTBOX_ENQUEUED")
            self.assertEqual(payload, build_minimized_bridge_payload(reverse_dict_order(pack),
                                                                    reverse_dict_order(handoff_for(pack, Path(td) / "second"))))
            self.assertEqual(pack, original)

    def test_price_proof_rejects_wrong_source_hash_clock_quality_and_non_rth(self):
        for mode in ("source", "hash", "future", "clock", "quality", "non_rth", "invalid_price"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                pack = captured_pack()
                source = synthetic_daily_price_source(pack["generated_at_ms"])
                if mode == "source": source["source_id"] = "UNAPPROVED_SOURCE"
                elif mode == "hash": source["data_hash"] = "0" * 64
                elif mode == "future": source["observed_at_ms"] = pack["generated_at_ms"] + 1
                elif mode == "clock": source["observed_at_ms"] = True
                elif mode == "quality": source["validation_state"] = "BLOCKED"
                else:
                    row = source["data"]["MSTR"][1]
                    if mode == "non_rth": row["source_state"] = "UNQUALIFIED_L1_QUOTE"
                    else: row["close"] = 0.0
                    source["data_hash"] = hashlib.sha256(canonical_bytes(source["data"])).hexdigest()
                pack["qualified_equity_daily_source"] = source
                bind_pack(pack)
                with self.assertRaises(ValueError):
                    build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))

    def test_price_with_no_completed_session_stays_blocked_without_imputed_price(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            source = synthetic_daily_price_source(pack["generated_at_ms"])
            for asset in source["data"]:
                source["data"][asset] = source["data"][asset][-1:]
            source["data_hash"] = hashlib.sha256(canonical_bytes(source["data"])).hexdigest()
            pack["qualified_equity_daily_source"] = source
            bind_pack(pack)
            payload = semantic_payload(build_minimized_bridge_payload(pack, handoff_for(pack, Path(td))))
            prices = payload["market_context"]["qualified_equity_prices"]
            self.assertEqual(prices["state"], "BLOCKED")
            for row in prices["assets"].values():
                self.assertEqual(row, {"state": "BLOCKED", "reason": "NO_COMPLETE_EQUITY_SESSION"})

    def test_later_replay_cannot_promote_a_source_incomplete_session(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            source = synthetic_daily_price_source(pack["generated_at_ms"])
            pack["qualified_equity_daily_source"] = source
            pack["generated_at_ms"] += 7 * 86400000
            bind_pack(pack)
            payload = semantic_payload(build_minimized_bridge_payload(pack, handoff_for(pack, Path(td))))
            for row in payload["market_context"]["qualified_equity_prices"]["assets"].values():
                self.assertEqual(row["session_date"], "2026-09-30")

    def test_realistic_full_context_reaches_validated_outbox_with_headroom(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack = captured_pack()
            handoff = handoff_for(pack, root)
            payload = build_minimized_bridge_payload(pack, handoff)
            self.assertEqual(payload["state"], "BRIDGE_PAYLOAD_READY_LOCAL_ONLY")
            self.assertLessEqual(len(canonical_bytes(payload)), 15 * 1024)
            self.assertEqual(payload["event"]["source_evidence_pack_hash"], pack["evidence_pack_hash"])
            result = enqueue_bridge_payload(root / "outbox", payload)
            self.assertEqual(result["state"], "OUTBOX_ENQUEUED")
            self.assertEqual(result["bridge_payload_hash"], payload["bridge_payload_hash"])
            stored = json.loads((root / "outbox" / (result["event_id"] + ".json")).read_text())
            self.assertEqual(stored, payload)
            self.assertEqual(enqueue_bridge_payload(root / "outbox", payload)["state"], "DUPLICATE_SKIPPED")

    def test_issuer_pairs_and_unresolved_clock_locks_stay_literal(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
            payload = semantic_payload(payload)
            expected = compact_issuer_ratio_observation(
                pack["issuer_ratio_observation"], generated_at_ms=pack["generated_at_ms"])
            self.assertEqual(payload["issuer_ratio_observation"], expected)
            mstr = payload["issuer_ratio_observation"]["observations"]["MSTR"]
            self.assertEqual(mstr["time_semantic"], "REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME")
            self.assertEqual(mstr["ct_binding_state"], "NOT_CT_BOUND")
            self.assertEqual(mstr["ct_blocker"], "ADSO_EFFECTIVE_TIME_UNRESOLVED")
            self.assertEqual(mstr["wake_authority"], "OBSERVATION_ONLY")
            self.assertEqual(mstr["machine_execution"], "FORBIDDEN")
            self.assertNotIn("current_effective_at_ms", mstr)
            asst = payload["issuer_ratio_observation"]["observations"]["ASST"]
            for key in ("previous_effective_at_ms", "current_effective_at_ms"):
                self.assertEqual(asst[key], pack["issuer_ratio_observation"]["observations"]["ASST"][key])

    def test_synthetic_capital_cash_budget_roles_stale_and_cost_basis_survive(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            profile = pack["private_context"]["profile"]
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
            payload = semantic_payload(payload)
            capital = payload["capital_state"]
            self.assertEqual(capital["snapshot_state"], "STALE")
            self.assertEqual(capital["STALE_CAPITAL_FIELDS"], STALE_FIELDS)
            self.assertEqual(capital["capital_state"]["as_of"], profile["capital_state"]["as_of"])
            self.assertEqual(capital["holdings"], [
                {"asset": "STRC", "quantity": 80.0, "cost_basis_usd": 1234.5},
                {"asset": "MSTR", "quantity": 5.0}])
            self.assertEqual(capital["cash"], {"available_usd": 4500.0, "reserved_usd": 180.0})
            self.assertEqual(capital["asset_roles"], {
                "STRC": "INCOME_CORE", "MSTR": "BTC_PROXY", "USD": "ATTACK_CAPITAL"})
            self.assertEqual(capital["execution_authority"], "USER_ONLY")
            plans = capital["active_plans"]
            self.assertEqual([(plan["plan_id"], plan["asset"], plan["side"], plan["status"])
                              for plan in plans], [("ATTACK_CAPITAL_WAIT", "USD", "WAIT", "ACTIVE")])
            self.assertEqual([(tranche["tranche_id"], tranche["budget_usd"], tranche["status"])
                              for tranche in plans[0]["tranches"]],
                             [("T1", 1500.0, "PENDING"), ("T2", 1500.0, "PENDING"), ("T3", 1500.0, "PENDING")])

    def test_market_health_states_blockers_dvol_etf_and_formal_locks_stay_literal(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            pack["layers"]["L1"]["status"] = "PARTIAL"
            pack["distillation"]["divergences"] = [{"state": "PARTIAL", "reason": "CONTRADICTORY_FLOW_HORIZONS"}]
            pack["distillation"]["formal_extremes"] = [{"state": "BLOCKED", "reason": "NOT_FORMALLY_QUALIFIED"}]
            payload = build_minimized_bridge_payload(pack, handoff_for(pack, Path(td)))
            payload = semantic_payload(payload)
            market = payload["market_context"]
            self.assertEqual(market["generated_at_ms"], pack["generated_at_ms"])
            self.assertEqual(market["pack_state"], pack["pack_state"])
            self.assertEqual(market["data_health"]["critical_blockers"], pack["data_health"]["critical_blockers"])
            self.assertEqual(market["data_health"]["source_gate_state"], pack["data_health"]["source_gate_state"])
            self.assertEqual(market["data_health"]["unusable_or_missing_evidence"], [
                {"input_family": row.get("input_family"), "quality_state": row.get("quality_state")}
                for row in pack["data_health"]["unusable_or_missing_evidence"]])
            self.assertEqual(market["layers"]["L1"]["status"], "PARTIAL")
            self.assertEqual(market["distillation"]["divergences"], pack["distillation"]["divergences"])
            self.assertEqual(market["distillation"]["formal_extremes"], pack["distillation"]["formal_extremes"])
            for layer, row in pack["layers"].items():
                for name, metric in row.get("metrics", {}).items():
                    eligible = (name in AUDIT_METRICS
                                and name != pack["reanalysis_wake"].get("metric")
                                and metric.get("quality_state") == "VALID_FRESH"
                                and metric.get("value") is not None)
                    if eligible:
                        self.assertNotIn(name, market["layers"][layer]["metrics"])
                        continue
                    actual = metric_facts(market, layer, name)
                    for key in ("value", "as_of_ms", "quality_state"):
                        if key in metric:
                            self.assertEqual(actual[key], metric[key], (layer, name, key))
                if "missing_required_metrics" in row:
                    self.assertEqual(market["layers"][layer]["missing_required_metrics"], row["missing_required_metrics"])
            self.assertEqual(market["btc_entry_gate"]["state"], pack["btc_entry_gate"]["state"])
            self.assertEqual(market["btc_entry_gate"]["reason"], pack["btc_entry_gate"]["reason"])
            bull = market["btc_bull_validation"]
            for key in ("state", "reason", "blocked_checks", "pending_checks", "mixed_checks", "adverse_checks", "supportive_checks"):
                if key in pack["btc_bull_validation"]:
                    self.assertEqual(bull[key], pack["btc_bull_validation"][key])
            actual_checks = {row["check_id"]: row for row in bull["checks"]}
            for check in pack["btc_bull_validation"]["checks"]:
                if check["status"] == "BLOCKED":
                    reason = (bull["blocked_check_reason"] if "blocked_check_reason" in bull
                              else bull["blocked_check_reasons"][check["check_id"]])
                    self.assertEqual(reason, check["reason"])
                    self.assertIn(check["check_id"], bull["blocked_checks"])
                    continue
                if check["status"] == "PENDING":
                    self.assertIn(check["check_id"], bull["pending_checks"])
                    continue
                actual = actual_checks[check["check_id"]]
                self.assertEqual(actual["status"], check["status"])
                self.assertEqual(actual["reason"], check["reason"])
                if check["status"] in {"ADVERSE", "MIXED"}:
                    expected_value = deepcopy(check["value"])
                    if isinstance(expected_value, dict):
                        # Descriptions and constant baseline labels are audit
                        # detail; observed volume/proxy values remain literal.
                        expected_value.pop("baseline_meaning", None)
                        expected_value.pop("natural_research_baselines", None)
                    self.assertEqual(actual["value"], expected_value)
            dvol = market["dvol_regime_watch"]
            for key in ("state", "reason", "current_dvol", "as_of_ms", "direction", "level_percentile_1y",
                        "change_1d_pct", "change_7d_pct", "rebound_from_30d_low_pct"):
                self.assertEqual(dvol[key], pack["dvol_regime_watch"][key])
            self.assertIn("btc_etf_evidence", market)
            serialized = canonical_bytes(payload).decode("utf-8")
            self.assertIn("RELIABLE_FREE_BTC_BALANCE_HISTORY_UNAVAILABLE", serialized)
            for key in ("btc_season_router", "locked_formal_scoring", "six_layer_evidence"):
                expected = pack["model_status"][key]
                actual = market["model_status"][key]
                for field in ("state", "reason", "season", "candidate_weather_bucket", "formal_model",
                              "layer_weights_percent", "light_thresholds", "blocked_reasons"):
                    if field in expected:
                        self.assertEqual(actual[field], expected[field], (key, field))
            for fact in pack["asset_facts"]["items"]:
                if fact["fact_type"] == "TREASURY_VALUATION_CONTEXT":
                    self.assertIn(fact["evidence"]["context_hash"], serialized)
                    self.assertIn('"formal_action_critical_state":"BLOCKED"', serialized)
                    for blocker in fact["evidence"]["blockers"]:
                        self.assertIn(blocker["code"], serialized)

    def test_authority_privacy_and_required_analyst_behavior_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            handoff = handoff_for(pack, Path(td))
            payload = build_minimized_bridge_payload(pack, handoff)
            self.assertEqual(payload["authority"], {
                "production": "NOT_APPROVED", "trading_authority": "NONE",
                "capital_decision_authority": "USER_ONLY", "machine_may_execute_trade": False,
                "external_action_authority": "NONE", "external_action_performed": False,
                "transport_authority": "NONE", "transport_performed": False, "action_output": "NONE"})
            self.assertEqual(payload["privacy"], {
                "mode": "MINIMIZED_ALLOWLIST_ONLY", "user_authorization_scope": "ANALYSIS_AND_NOTIFICATION_ONLY",
                "raw_private_context_included": False, "full_private_profile_included": False,
                "filesystem_paths_included": False, "broker_or_account_identifiers_included": False,
                "credentials_or_secrets_included": False, "transport_selected": False})
            contract = semantic_payload(payload)["analysis_contract"]
            for bridge_key, handoff_key in (("instruction_for_gpt", "instruction_for_gpt"),
                                            ("reanalysis_semantics", "reanalysis_semantics"),
                                            ("source_required_inputs", "required_inputs"),
                                            ("required_behavior", "required_behavior")):
                self.assertEqual(contract[bridge_key], handoff[handoff_key])
            serialized = canonical_bytes(semantic_payload(payload)).decode("utf-8")
            for forbidden in ("never-export@example.com", "NEVER_EXPORT", "broker_account", "account_number",
                              '"private_context":', '"private_note":', "C:\\\\Users\\\\private"):
                self.assertNotIn(forbidden, serialized)

    def test_payload_and_hash_ignore_dictionary_insertion_order(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            handoff = handoff_for(pack, Path(td))
            untouched = deepcopy(pack)
            first = build_minimized_bridge_payload(pack, handoff)
            second = build_minimized_bridge_payload(pack, handoff)
            reversed_payload = build_minimized_bridge_payload(reverse_dict_order(pack), reverse_dict_order(handoff))
            self.assertEqual(pack, untouched)
            self.assertEqual(first, second)
            self.assertEqual(first, reversed_payload)
            self.assertEqual(canonical_bytes(first), canonical_bytes(reversed_payload))
            digest_material = {key: value for key, value in first.items() if key != "bridge_payload_hash"}
            self.assertEqual(first["bridge_payload_hash"], hashlib.sha256(canonical_bytes(digest_material)).hexdigest())

    def test_oversized_supporting_history_is_deterministic_and_explicitly_bound(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            pack["changes"] = {"btc_spot_price_usd": {
                "current_value": 83928.01, "as_of_ms": pack["generated_at_ms"],
                "history": [{"at": index, "value": index / 3.0} for index in range(3000)],
                "baseline": [index / 7.0 for index in range(3000)],
                "rankings": [{"rank": index, "support": "AUDIT_ONLY"} for index in range(3000)]}}
            handoff = handoff_for(pack, Path(td))
            payload = build_minimized_bridge_payload(pack, handoff)
            reordered = build_minimized_bridge_payload(reverse_dict_order(pack), reverse_dict_order(handoff))
            self.assertEqual(payload, reordered)
            self.assertLessEqual(len(canonical_bytes(payload)), 15 * 1024)
            self.assertEqual(payload["event"]["source_evidence_pack_hash"], pack["evidence_pack_hash"])
            serialized = canonical_bytes(payload).decode("utf-8")
            self.assertIn("OMITTED_FROM_BRIDGE_NOT_ABSENT_FROM_EVIDENCE", serialized)
            expanded = semantic_payload(payload)
            self.assertIn("source_market_context_hash", expanded["market_context"]["minimization"])
            self.assertEqual(expanded["issuer_ratio_observation"], compact_issuer_ratio_observation(
                pack["issuer_ratio_observation"], generated_at_ms=pack["generated_at_ms"]))

    def test_qualified_market_and_premarket_sections_preserved_when_supplied(self):
        with tempfile.TemporaryDirectory() as td:
            pack = bridge_pack(handoff_pack(evidence_hash="b" * 64, requested=True))
            pack["mstr_asst_market_health"] = market_health()
            synthetic = bridge_pack(handoff_pack(evidence_hash="b" * 64, requested=True))
            pack["premarket_market_data"] = synthetic["premarket_market_data"]
            payload = semantic_payload(build_minimized_bridge_payload(pack, handoff_for(pack, Path(td))))
            for key in ("mstr_asst_market_health", "premarket_market_data"):
                self.assertEqual(payload["market_context"][key], pack[key])

    def test_additive_full_qualified_context_fails_closed_if_critical_facts_exceed_capacity(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            pack["mstr_asst_market_health"] = market_health()
            synthetic = bridge_pack(handoff_pack(evidence_hash="b" * 64, requested=True))
            pack["premarket_market_data"] = synthetic["premarket_market_data"]
            handoff = handoff_for(pack, Path(td))
            original = deepcopy(pack)
            full_handoff = run_gpt_handoff_gate(pack, build_plain_language_notice(pack),
                ledger_path=Path(td) / "handoff.jsonl", full_decision=True)
            inspected = build_full_decision_bridge_payload(pack, full_handoff)
            self.assertGreaterEqual(len(canonical_bytes(inspected)), 16 * 1024)
            validate_transport_payload(inspected)
            self.assertEqual(semantic_payload(inspected)["analysis_contract"]["delivery_scope"],
                             "FULL_DECISION_OFFLINE")
            full_market = semantic_payload(inspected)["market_context"]
            self.assertEqual(full_market["changes"], pack["changes"])
            self.assertEqual(full_market["mstr_asst_market_health"], pack["mstr_asst_market_health"])
            for layer, context in pack["layers"].items():
                for name, row in context["metrics"].items():
                    self.assertEqual(full_market["layers"][layer]["metrics"][name]["value"], row["value"])
            with self.assertRaisesRegex(ValueError, "byte ceiling"):
                build_request_envelope(inspected, model=SMOKE_MODEL)
            with self.assertRaisesRegex(ValueError, "16 KiB"):
                build_minimized_bridge_payload(pack, handoff)
            self.assertEqual(pack, original)

    def test_stale_partial_blocked_null_and_trigger_scoring_rows_cannot_be_omitted(self):
        for quality, value, trigger in (
            ("STALE", 1.25, False), ("PARTIAL", 1.25, False),
            ("BLOCKED", 1.25, False), ("VALID_FRESH", None, False),
            ("VALID_FRESH", 1.25, True),
        ):
            with self.subTest(quality=quality, value=value, trigger=trigger), tempfile.TemporaryDirectory() as td:
                pack = captured_pack()
                name = "core_inflation_acceleration"
                pack["layers"]["L1"]["metrics"][name] = {
                    "value": value, "as_of_ms": pack["generated_at_ms"], "quality_state": quality}
                if trigger:
                    pack["reanalysis_wake"]["metric"] = name
                payload = semantic_payload(build_minimized_bridge_payload(pack, handoff_for(pack, Path(td))))
                self.assertEqual(metric_facts(payload["market_context"], "L1", name),
                                 pack["layers"]["L1"]["metrics"][name])

    def test_unknown_fresh_metric_stays_literal(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            row = {"value": 1.25, "as_of_ms": pack["generated_at_ms"], "quality_state": "VALID_FRESH"}
            pack["layers"]["L1"]["metrics"]["unknown_current_metric"] = row
            payload = semantic_payload(build_minimized_bridge_payload(pack, handoff_for(pack, Path(td))))
            self.assertEqual(metric_facts(payload["market_context"], "L1", "unknown_current_metric"), row)

    def test_key_glossary_roundtrip_preserves_values_and_existing_token_like_keys(self):
        fields = {
            "current_reported_observation_value": "REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME",
            "previous_reported_observation_value": "ADSO_EFFECTIVE_TIME_UNRESOLVED",
            "current_reported_observation_state": "BLOCKED",
            "previous_reported_observation_state": "PARTIAL",
            "existing@0_key": "STALE", "punctuation!key": 123.456789012345,
        }
        payload = {"market_context": {"rows": [deepcopy(fields) for _ in range(30)]},
                   "authority": {"production": "NOT_APPROVED"}, "privacy": {"mode": "MINIMIZED_ALLOWLIST_ONLY"}}
        original = deepcopy(payload)
        _compact_field_names(payload)
        self.assertIn("key_encoding", payload["market_context"])
        self.assertLess(len(canonical_bytes(payload)), len(canonical_bytes(original)))
        self.assertEqual(expand_bridge_field_names(payload), original)
        self.assertEqual(payload["authority"], original["authority"])
        self.assertEqual(payload["privacy"], original["privacy"])
        reordered = reverse_dict_order(original)
        _compact_field_names(reordered)
        self.assertEqual(reordered, payload)
        for text in ("REPORTED_OBSERVATION_NOT_EFFECTIVE_TIME", "ADSO_EFFECTIVE_TIME_UNRESOLVED",
                     "BLOCKED", "PARTIAL", "STALE"):
            self.assertIn(text, canonical_bytes(payload).decode("utf-8"))

    def test_key_glossary_delimiter_collision_disables_encoding_without_loss(self):
        payload = {"market_context": {"legal|source_field": "BLOCKED",
                                     "rows": [{"current_observation_state": "STALE"} for _ in range(30)]}}
        original = deepcopy(payload)
        _compact_field_names(payload)
        self.assertEqual(payload, original)
        self.assertNotIn("key_encoding", payload["market_context"])

    def test_key_glossary_expansion_collision_fails_closed(self):
        payload = {"market_context": {"key_encoding": ["$", "current_value", "test glossary"],
                                      "current_value": 1, "$": 2}}
        original = deepcopy(payload)
        with self.assertRaisesRegex(ValueError, "collision"):
            expand_bridge_field_names(payload)
        self.assertEqual(payload, original)

    def test_authority_inheritance_restores_only_original_subset(self):
        top = {"production": "NOT_APPROVED", "action_output": "NONE",
               "capital_decision_authority": "USER_ONLY", "machine_may_execute_trade": False,
               "external_action_authority": "NONE", "external_action_performed": False}
        subset = {"action_output": "NONE", "external_action_authority": "NONE",
                  "external_action_performed": False}
        payload = {"authority": top, "market_context": {"child": deepcopy(subset)}}
        original = deepcopy(payload)
        _inherit_equal_authority(payload["market_context"], top)
        self.assertLess(len(canonical_bytes(payload)), len(canonical_bytes(original)))
        expanded = expand_bridge_field_names(payload)
        self.assertEqual(expanded, original)
        self.assertEqual(set(expanded["market_context"]["child"]), set(subset))

    def test_authority_inheritance_never_coalesces_boolean_false_with_numeric_zero(self):
        top = {"action_output": "NONE", "external_action_authority": "NONE",
               "external_action_performed": False, "machine_may_execute_trade": False}
        source = {"action_output": "NONE", "external_action_authority": "NONE",
                  "external_action_performed": 0, "machine_may_execute_trade": 0}
        payload = {"authority": top, "market_context": {"child": deepcopy(source)}}
        original = deepcopy(payload)
        _inherit_equal_authority(payload["market_context"], top)
        expanded = expand_bridge_field_names(payload)
        self.assertEqual(canonical_bytes(expanded), canonical_bytes(original))
        self.assertIs(type(expanded["market_context"]["child"]["external_action_performed"]), int)

    def test_tranche_inheritance_preserves_distinct_integer_and_float_literals(self):
        condition = {"field": "mstr_asst_relative_value_validation_status",
                     "operator": "EQ", "value": "NOT_YET_VALIDATED"}
        payload = {"capital_state": {"active_plans": [{"plan_id": "SYNTHETIC_WAIT", "tranches": [
            {"tranche_id": "T1", "budget_usd": 1500, "status": "PENDING", "validity_conditions": [condition]},
            {"tranche_id": "T2", "budget_usd": 1500.0, "status": "PENDING", "validity_conditions": [condition]},
            {"tranche_id": "T3", "budget_usd": 1500, "status": "PENDING", "validity_conditions": [condition]},
        ]}]}}
        original = deepcopy(payload)
        _compact_tranche_fields(payload)
        expanded = expand_bridge_field_names(payload)
        self.assertEqual(canonical_bytes(expanded), canonical_bytes(original))
        rows = expanded["capital_state"]["active_plans"][0]["tranches"]
        self.assertEqual([type(row["budget_usd"]) for row in rows], [int, float, int])

    def test_oversized_decision_critical_blockers_fail_closed_without_treasury(self):
        with tempfile.TemporaryDirectory() as td:
            pack = captured_pack()
            pack["asset_facts"]["items"] = [fact for fact in pack["asset_facts"]["items"]
                                              if fact["fact_type"] != "TREASURY_VALUATION_CONTEXT"]
            pack["data_health"]["critical_blockers"] = ["UNRESOLVED_CRITICAL_EVIDENCE_" + "X" * (17 * 1024)]
            handoff = handoff_for(pack, Path(td))
            original = deepcopy(pack)
            with self.assertRaisesRegex(ValueError, "16 KiB|16 KiB ceiling|16384|size limit|ceiling"):
                build_minimized_bridge_payload(pack, handoff)
            self.assertEqual(pack, original)


if __name__ == "__main__":
    unittest.main()
