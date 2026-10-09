"""Read-only IBKR observations; cash analysis is distinct from trade authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import threading
import time
from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "CRT_BROKER_CAPITAL_OBSERVATION_V0.1"
SOCKET_SOURCE = "IBKR_TWS_SOCKET_API"
CONNECTED_SOURCE = "IBKR_CONNECTED_ACCOUNT_INTERFACE"
MAX_AGE_MS = 300_000
MAX_SNAPSHOT_SPAN_MS = 30_000
BLOCKED_BROKER_REASONS = {
    "BROKER_OBSERVATION_MISSING", "BROKER_OBSERVATION_INVALID",
    "BROKER_PROOF_HASH_INVALID", "BROKER_AUTHORITY_INVALID",
    "BROKER_ACCOUNT_SCOPE_UNCONFIRMED", "BROKER_ACCOUNT_NOT_READY",
    "BROKER_OBSERVATION_CLOCK_INVALID", "UNRECOGNIZED_BROKER_SOURCE",
    "UNSUPPORTED_POSITION_SCOPE", "AMBIGUOUS_DUPLICATE_POSITION",
    "INVALID_CAPITAL_NUMBER", "INVALID_CAPITAL_ASSET", "IDENTIFIER_NOT_ASSET",
    "INVALID_AVERAGE_COST", "INVALID_POSITION_COST_BASIS", "UNSUPPORTED_ORDER_SCOPE",
    "BROKER_CAPTURE_INCOMPLETE", "BROKER_CAPTURE_SOURCE_CONFLICT",
    "BROKER_ACCOUNT_SNAPSHOT_UNQUALIFIED", "BROKER_POSITION_CONFLICT",
    "BROKER_CASH_SOURCE_CONFLICT", "BROKER_CONNECT_UNAVAILABLE", "BROKER_SDK_UNAVAILABLE",
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_CAPITAL_NUMBER")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("INVALID_CAPITAL_NUMBER")
    return number


def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value):
        raise ValueError("INVALID_CAPITAL_ASSET")
    if re.fullmatch(r"[A-Z]{1,2}\d{7,}", value):
        raise ValueError("IDENTIFIER_NOT_ASSET")
    return value


def seal_broker_observation(capture: dict[str, Any]) -> dict[str, Any]:
    """Allowlist before hashing/export; never retain account/order identifiers."""
    if capture.get("source") not in {SOCKET_SOURCE, CONNECTED_SOURCE}:
        raise ValueError("UNRECOGNIZED_BROKER_SOURCE")
    scope = capture.get("scope", {})
    result = {
        "schema_version": SCHEMA, "source": capture["source"],
        "observed_at_ms": int(capture["observed_at_ms"]),
        "started_at_ms": int(capture["started_at_ms"]),
        "automatic_local_refresh": capture["source"] == SOCKET_SOURCE and capture.get("automatic_local_refresh") is True,
        "scope": {key: scope.get(key) for key in (
            "account_count", "same_account_verified", "account_ready",
            "positions_complete", "funds_complete", "orders_complete")},
        "holdings": [], "funds": {}, "open_orders": [],
        "action_output": "NONE", "external_action_authority": "NONE",
        "external_action_performed": False,
    }
    for row in capture.get("holdings", []):
        holding = {"asset": _symbol(row["asset"]), "quantity": _number(row["quantity"]),
                   "currency": row.get("currency"), "security_type": row.get("security_type"),
                   "average_cost_usd": _number(row["average_cost_usd"])}
        if holding["currency"] != "USD" or holding["security_type"] != "STK":
            raise ValueError("UNSUPPORTED_POSITION_SCOPE")
        if holding["average_cost_usd"] < 0:
            raise ValueError("INVALID_AVERAGE_COST")
        if not math.isfinite(holding["quantity"] * holding["average_cost_usd"]):
            raise ValueError("INVALID_POSITION_COST_BASIS")
        result["holdings"].append(holding)
    result["holdings"].sort(key=lambda row: row["asset"])
    if len({row["asset"] for row in result["holdings"]}) != len(result["holdings"]):
        raise ValueError("AMBIGUOUS_DUPLICATE_POSITION")
    funds = capture.get("funds", {})
    for key in ("cash_usd", "available_funds_usd", "settled_cash_usd"):
        result["funds"][key] = None if funds.get(key) is None else _number(funds[key])
    for row in capture.get("open_orders", []):
        order = {"asset": _symbol(row["asset"]), "side": row.get("side"),
                 "currency": row.get("currency"), "order_type": row.get("order_type"),
                 "quantity": _number(row["quantity"]),
                 "filled_quantity": None if row.get("filled_quantity") is None else _number(row["filled_quantity"]),
                 "remaining_quantity": None if row.get("remaining_quantity") is None else _number(row["remaining_quantity"]),
                 "limit_price_usd": None if row.get("limit_price_usd") is None else _number(row["limit_price_usd"])}
        if order["side"] not in {"BUY", "SELL"} or order["currency"] != "USD":
            raise ValueError("UNSUPPORTED_ORDER_SCOPE")
        result["open_orders"].append(order)
    result["open_orders"].sort(key=lambda row: json.dumps(row, sort_keys=True))
    result["observation_hash"] = _hash(result)
    return result


def validate_broker_observation(observation: Any, *, at_ms: int) -> dict[str, Any]:
    result = {"state": "BLOCKED", "reason": "BROKER_OBSERVATION_MISSING"}
    if not isinstance(observation, dict):
        return result
    if observation.get("capture_failed") is True:
        reason = observation.get("reason")
        return {"state": "BLOCKED", "reason": reason if reason in BLOCKED_BROKER_REASONS else "BROKER_OBSERVATION_INVALID"}
    try:
        clean = seal_broker_observation(observation)
        if observation.get("schema_version") != SCHEMA or clean["observation_hash"] != observation.get("observation_hash"):
            raise ValueError("BROKER_PROOF_HASH_INVALID")
        if (observation.get("action_output") != "NONE"
                or observation.get("external_action_authority") != "NONE"
                or observation.get("external_action_performed") is not False):
            raise ValueError("BROKER_AUTHORITY_INVALID")
        scope = clean["scope"]
        if type(scope["account_count"]) is not int or scope["account_count"] != 1 or scope["same_account_verified"] is not True:
            raise ValueError("BROKER_ACCOUNT_SCOPE_UNCONFIRMED")
        if scope["account_ready"] is not True:
            raise ValueError("BROKER_ACCOUNT_NOT_READY")
        start, end = clean["started_at_ms"], clean["observed_at_ms"]
        if start <= 0 or start > end or end > at_ms or end - start > MAX_SNAPSHOT_SPAN_MS:
            raise ValueError("BROKER_OBSERVATION_CLOCK_INVALID")
        result = {"state": "AVAILABLE", "reason": "BROKER_OBSERVATION_VALID", "observation": clean}
        if at_ms - end > MAX_AGE_MS:
            result.update(state="STALE", reason="BROKER_OBSERVATION_EXPIRED")
        elif not all(scope[key] is True for key in ("positions_complete", "funds_complete", "orders_complete")):
            result.update(state="PARTIAL", reason="BROKER_SNAPSHOT_INCOMPLETE")
        elif any(clean["funds"][key] is None for key in ("cash_usd", "available_funds_usd")):
            result.update(state="PARTIAL", reason="BROKER_ANALYSIS_FUNDS_MISSING")
        # SettledCash is a settlement-specific limitation, never an analysis veto.
        return result
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
        return {"state": "BLOCKED", "reason": str(exc) if str(exc) in BLOCKED_BROKER_REASONS else "BROKER_OBSERVATION_INVALID"}


def adapt_capital_intent(intent: Any, decision_intent: Any = None) -> dict[str, Any]:
    """Separate legacy plan policy from explicit full-decision permissions.

    A legacy reserve/cancel-plan confirmation is not a no-leverage confirmation.
    Combined inputs may carry both formats, but shared facts must be identical.
    Missing full-decision facts remain unknown, never supplied as defaults.
    """
    legacy_keys = {"source", "confirmed_at_ms", "reserved_usd", "plan_policy", "asset_roles"}
    full_keys = {"version", "source", "confirmed_at_ms", "reserved_usd", "no_leverage"}
    legacy = ({key: deepcopy(intent[key]) for key in legacy_keys if key in intent}
              if isinstance(intent, dict) else None)
    supplied = decision_intent if decision_intent is not None else intent
    full = None
    blockers = []
    if isinstance(supplied, dict) and full_keys <= supplied.keys():
        full = {key: deepcopy(supplied[key]) for key in full_keys}
        if not isinstance(full["version"], str) or not full["version"].strip():
            blockers.append("FULL_DECISION_INTENT_VERSION_UNCONFIRMED")
        if full["source"] != "USER_CONFIRMED" or full["no_leverage"] is not True:
            blockers.append("FULL_DECISION_INTENT_PERMISSION_UNCONFIRMED")
        if isinstance(intent, dict):
            for key in ("source", "confirmed_at_ms", "reserved_usd"):
                if key not in intent or intent[key] != full[key]:
                    blockers.append("CAPITAL_INTENT_IDENTITY_MISMATCH")
                    full = None
                    break
    else:
        blockers.append("FULL_DECISION_INTENT_UNCONFIRMED")
    return {"reconciliation_intent": legacy, "full_decision_intent": full,
            "state": "AVAILABLE" if not blockers else "BLOCKED", "blockers": blockers}


def reconcile_capital(observation: Any, intent: Any, *, at_ms: int) -> dict[str, Any]:
    checked = validate_broker_observation(observation, at_ms=at_ms)
    clean = checked.get("observation")
    result = {"state": checked["state"], "reason": checked["reason"],
              "broker_observed": clean, "user_confirmed": None,
              "analysis_cash_budget_usd": None, "open_order_cash_commitment_usd": None,
              "execution_limitations": [], "position_available_quantities": {},
              "scope": "IBKR_SINGLE_ACCOUNT_USD_ONLY", "action_output": "NONE",
              "external_action_authority": "NONE", "external_action_performed": False}
    limitations = result["execution_limitations"]
    try:
        if not isinstance(intent, dict) or intent.get("source") != "USER_CONFIRMED":
            raise ValueError("CAPITAL_INTENT_UNCONFIRMED")
        confirmed_at = int(intent["confirmed_at_ms"])
        if confirmed_at > at_ms or confirmed_at <= 0:
            raise ValueError("CAPITAL_INTENT_CLOCK_INVALID")
        reserve = _number(intent["reserved_usd"])
        if reserve < 0 or intent.get("plan_policy") != "CANCEL_ALL_NO_REPLACEMENT":
            raise ValueError("CAPITAL_INTENT_INVALID")
        roles = intent.get("asset_roles", {})
        if not isinstance(roles, dict):
            raise ValueError("CAPITAL_INTENT_INVALID")
        safe_roles = {}
        for asset, role in roles.items():
            if not isinstance(role, str) or not re.fullmatch(r"[A-Z_]{1,64}", role):
                raise ValueError("CAPITAL_ROLE_INVALID")
            safe_roles[_symbol(asset)] = role
        result["user_confirmed"] = {"source": "USER_CONFIRMED", "confirmed_at_ms": confirmed_at,
                                    "reserved_usd": reserve, "plan_policy": "CANCEL_ALL_NO_REPLACEMENT",
                                    "asset_roles": safe_roles}
    except (ValueError, TypeError, KeyError, OverflowError):
        limitations.append("CAPITAL_INTENT_UNCONFIRMED")
        if result["state"] == "AVAILABLE":
            result.update(state="PARTIAL", reason="CAPITAL_INTENT_UNCONFIRMED")
        reserve = None
    limitations.append("NO_TRADE_OR_FINANCING_AUTHORIZATION")
    if clean is None:
        return result
    if clean["funds"]["settled_cash_usd"] is None:
        limitations.append("SETTLEMENT_DEPENDENT_EXECUTION_REQUIRES_EVIDENCE")
    roles = (result["user_confirmed"] or {}).get("asset_roles", {})
    if any(row["asset"] not in roles for row in clean["holdings"]):
        limitations.append("ASSET_ROLES_NOT_RECONFIRMED")
    commitment = Decimal("0")
    selling = {}
    for row in clean["open_orders"]:
        filled, remaining, total = row["filled_quantity"], row["remaining_quantity"], row["quantity"]
        if (filled is None or remaining is None or min(filled, remaining, total) < 0
                or not math.isclose(filled + remaining, total, rel_tol=0, abs_tol=1e-8)):
            limitations.append("OPEN_ORDER_FILL_ALIGNMENT_UNRESOLVED")
            commitment = None
            break
        if row["side"] == "BUY":
            if row["order_type"] != "LMT" or row["limit_price_usd"] is None or row["limit_price_usd"] <= 0:
                limitations.append("OPEN_ORDER_CASH_COMMITMENT_UNRESOLVED")
                commitment = None
                break
            commitment += Decimal(str(remaining)) * Decimal(str(row["limit_price_usd"]))
        else:
            selling[row["asset"]] = selling.get(row["asset"], 0.0) + remaining
    for holding in clean["holdings"]:
        result["position_available_quantities"][holding["asset"]] = (
            max(0.0, holding["quantity"] - selling.get(holding["asset"], 0.0))
            if commitment is not None and checked["state"] != "STALE"
            and clean["scope"]["positions_complete"] is True and clean["scope"]["orders_complete"] is True else None)
        if holding["quantity"] < 0 or selling.get(holding["asset"], 0.0) > max(0, holding["quantity"]):
            limitations.append("SHORT_OR_SELL_EXCESS_REQUIRES_FINANCING_RECHECK")
    if checked["state"] != "AVAILABLE":
        return result
    result["open_order_cash_commitment_usd"] = float(commitment) if commitment is not None else None
    if clean["open_orders"]:
        limitations.append("ORDER_FEES_AND_FINANCING_REQUIRE_EXECUTION_RECHECK")
    if commitment is None:
        result.update(state="PARTIAL", reason="OPEN_ORDER_OCCUPANCY_UNRESOLVED")
    elif reserve is not None:
        cash, available = clean["funds"]["cash_usd"], clean["funds"]["available_funds_usd"]
        # AvailableFunds may already reflect orders: do NOT subtract them twice.
        budget = max(Decimal("0"), min(Decimal(str(cash)) - commitment, Decimal(str(available))) - Decimal(str(reserve)))
        result["analysis_cash_budget_usd"] = float(budget.quantize(Decimal("0.01"), rounding=ROUND_FLOOR))
    return result


def capture_ibkr_capital(*, timeout_seconds: float = 25, client_id: int = 13124) -> dict[str, Any]:
    """Official SDK only; nonzero client, no binding, order write or what-if call."""
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    if client_id <= 0 or timeout_seconds <= 0:
        raise ValueError("INVALID_READ_ONLY_CAPTURE_CONFIGURATION")
    class App(EWrapper, EClient):
        def __init__(self):
            EWrapper.__init__(self); EClient.__init__(self, self)
            self.ready = threading.Event(); self.accounts_ready = threading.Event()
            self.ends = {key: threading.Event() for key in ("positions", "summary", "orders", "updates")}
            self.accounts = []; self.account = None; self.conflict = False; self.errors = []
            self.positions = {}; self.portfolio = {}; self.values = {}; self.orders = {}; self.statuses = {}
            self.account_ready = None

        def logRequest(self, fnName, fnParams):
            pass  # Account selection stays in memory, never a request log.

        def nextValidId(self, orderId):
            self.ready.set()

        def managedAccounts(self, accountsList):
            self.accounts = sorted(set(value.strip() for value in accountsList.split(",") if value.strip()))
            self.accounts_ready.set()

        def same(self, account):
            if account != self.account:
                self.conflict = True
                return False
            return True

        def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
            if errorCode not in {2104, 2106, 2107, 2108, 2158, 2119, 1102}:
                self.errors.append(int(errorCode))

        def funds(self, tag, value, currency):
            key = tag.removeprefix("$LEDGER-")
            if currency == "USD" and key in {"CashBalance", "TotalCashValue", "AvailableFunds", "SettledCash"}:
                number = _number(value)
                if key in self.values and self.values[key] != number:
                    self.conflict = True
                self.values[key] = number

        def accountSummary(self, reqId, account, tag, value, currency):
            if self.same(account):
                self.funds(tag, value, currency)

        def accountSummaryEnd(self, reqId):
            if reqId == 90104:
                self.ends["summary"].set()

        def updateAccountValue(self, key, val, currency, accountName):
            if self.same(accountName):
                if key.lower() == "accountready":
                    if self.account_ready is False or val.lower() != "true":
                        self.account_ready = False
                    else:
                        self.account_ready = True
                else:
                    self.funds(key, val, currency)

        def position(self, account, contract, position, avgCost):
            if self.same(account):
                self.positions[contract.conId] = {"asset": contract.symbol, "quantity": str(position),
                    "average_cost_usd": avgCost, "currency": contract.currency, "security_type": contract.secType}

        def positionEnd(self):
            self.ends["positions"].set()

        def updatePortfolio(self, contract, position, marketPrice, marketValue, averageCost,
                            unrealizedPNL, realizedPNL, accountName):
            if self.same(accountName):
                self.portfolio[contract.conId] = {"asset": contract.symbol, "quantity": str(position),
                    "average_cost_usd": averageCost, "currency": contract.currency, "security_type": contract.secType}

        def accountDownloadEnd(self, accountName):
            if self.same(accountName):
                self.ends["updates"].set()

        def openOrder(self, orderId, contract, order, orderState):
            if self.same(order.account):
                self.orders[orderId] = {"asset": contract.symbol, "currency": contract.currency,
                    "side": order.action, "quantity": str(order.totalQuantity), "order_type": order.orderType,
                    "limit_price_usd": order.lmtPrice if order.orderType == "LMT" else None}

        def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId,
                        parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
            self.statuses[orderId] = {"filled_quantity": str(filled), "remaining_quantity": str(remaining)}

        def openOrderEnd(self):
            self.ends["orders"].set()

    app = App(); thread = None; subscribed = False
    started = int(time.time() * 1000)
    deadline = time.monotonic() + timeout_seconds
    def wait(event):
        if not event.wait(max(0.0, deadline - time.monotonic())):
            raise RuntimeError("BROKER_CAPTURE_INCOMPLETE")
        if app.errors or app.conflict:
            raise RuntimeError("BROKER_CAPTURE_SOURCE_CONFLICT")
    try:
        app.connect("127.0.0.1", 7496, clientId=client_id)
        thread = threading.Thread(target=app.run, daemon=True); thread.start()
        wait(app.ready); app.reqManagedAccts(); wait(app.accounts_ready)
        if len(app.accounts) != 1:
            raise RuntimeError("BROKER_ACCOUNT_SCOPE_UNCONFIRMED")
        app.account = app.accounts[0]
        app.reqPositions()
        app.reqAccountSummary(90104, "All", "SettledCash,TotalCashValue,AvailableFunds,AccountType")
        app.reqAllOpenOrders()
        for key in ("positions", "summary", "orders"):
            wait(app.ends[key])
        subscribed = True; app.reqAccountUpdates(True, app.account); wait(app.ends["updates"])
        if app.account_ready is not True or set(app.positions) != set(app.portfolio):
            raise RuntimeError("BROKER_ACCOUNT_SNAPSHOT_UNQUALIFIED")
        for key, position in app.positions.items():
            portfolio = app.portfolio[key]
            if any(position[field] != portfolio[field] for field in ("asset", "currency", "security_type")):
                raise RuntimeError("BROKER_POSITION_CONFLICT")
            for field in ("quantity", "average_cost_usd"):
                if not math.isclose(_number(position[field]), _number(portfolio[field]), rel_tol=0, abs_tol=1e-6):
                    raise RuntimeError("BROKER_POSITION_CONFLICT")
        for key, row in app.orders.items():
            row.update(app.statuses.get(key, {}))
        cash = app.values.get("CashBalance", app.values.get("TotalCashValue"))
        if "CashBalance" in app.values and "TotalCashValue" in app.values and cash != app.values["TotalCashValue"]:
            raise RuntimeError("BROKER_CASH_SOURCE_CONFLICT")
        return seal_broker_observation({"source": SOCKET_SOURCE, "started_at_ms": started,
            "observed_at_ms": int(time.time() * 1000), "automatic_local_refresh": True,
            "scope": {"account_count": 1, "same_account_verified": True, "account_ready": True,
                      "positions_complete": True, "funds_complete": True, "orders_complete": True},
            "holdings": list(app.positions.values()), "open_orders": list(app.orders.values()),
            "funds": {"cash_usd": cash, "available_funds_usd": app.values.get("AvailableFunds"),
                      "settled_cash_usd": app.values.get("SettledCash")}})
    finally:
        if app.isConnected():
            if subscribed:
                app.reqAccountUpdates(False, app.account)
            app.cancelPositions(); app.cancelAccountSummary(90104); app.disconnect()
        if thread:
            thread.join(timeout=2)


def bridge_capital_surface(reconciliation: dict[str, Any], *, historical_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Small explicit source split, inside the existing capital_state payload."""
    broker = reconciliation.get("broker_observed") or {}
    intent = reconciliation.get("user_confirmed") or {}
    funds = broker.get("funds", {})
    holdings = broker.get("holdings", [])
    return {
        "capital_state": {"contract_version": "CRT_CAPITAL_STATE_V0.1",
                          "source": "BROKER_OBSERVED_WITH_USER_CONFIRMED_INTENT",
                          "as_of": datetime.fromtimestamp(broker["observed_at_ms"] / 1000, timezone.utc).isoformat()
                          if broker else None, "base_currency": "USD"},
        "snapshot_state": reconciliation["state"], "reason": reconciliation["reason"],
        "holdings": [{"asset": row["asset"], "quantity": row["quantity"],
                      "average_cost_usd": row["average_cost_usd"],
                      "cost_basis_usd": round(row["quantity"] * row["average_cost_usd"], 2)} for row in holdings],
        "cash": {"available_usd": funds.get("cash_usd"), "reserved_usd": intent.get("reserved_usd"),
                 "available_funds_usd": funds.get("available_funds_usd"),
                 "settled_cash_usd": funds.get("settled_cash_usd")},
        "asset_roles": deepcopy(intent.get("asset_roles", {})), "active_plans": [],
        "plans_state": "CANCELLED" if intent else "UNCONFIRMED",
        "source_attribution": {
            "holdings_cost_cash": "BROKER_OBSERVED", "reserves_roles_plans": "USER_CONFIRMED",
            "broker_source": broker.get("source"), "observed_at_ms": broker.get("observed_at_ms"),
            "observation_hash": broker.get("observation_hash"),
            "automatic_local_refresh": broker.get("automatic_local_refresh", False),
            "intent_confirmed_at_ms": intent.get("confirmed_at_ms"),
            "plan_policy": intent.get("plan_policy"),
            "freshness_scope": "AS_OF_EVIDENCE_PACK_CLOCK",
        },
        "reconciliation": {
            "scope": reconciliation["scope"],
            "analysis_cash_budget_usd": reconciliation["analysis_cash_budget_usd"],
            "open_order_cash_commitment_usd": reconciliation["open_order_cash_commitment_usd"],
            "open_orders": deepcopy(broker.get("open_orders", [])),
            "position_available_quantities": deepcopy(reconciliation["position_available_quantities"]),
            "execution_limitations": list(reconciliation["execution_limitations"]),
            "strc": {"shares": next((row["quantity"] for row in holdings if row["asset"] == "STRC"),
                                    0.0 if broker.get("scope", {}).get("positions_complete") is True else None),
                     "historical_shares": historical_snapshot.get("strc_shares"),
                     "historical_as_of": historical_snapshot.get("as_of"),
                     "historical_snapshot_not_current": True},
        },
        "execution_authority": "USER_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    observation = capture_ibkr_capital()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(observation, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "CAPTURED", "observation_hash": observation["observation_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
