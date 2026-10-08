"""Terminal US securities recommendation validation; no strategy or execution.

Local source seals detect mutation, not authenticity. Source qualification is an
explicit, attributed input; a caller cannot turn an analysis budget into cash.
Missing qualification blocks only dependent claims. Commander is not imported.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import hashlib
import json
import re

from .broker_capital_observation import validate_broker_observation, MAX_AGE_MS

VERSION = "CRT_CAPITAL_RECOMMENDATION_V0.1"
REQUEST_VERSION = "CRT_CAPITAL_RECOMMENDATION_REQUEST_V0.1"
FULL_REQUEST_VERSION = "CRT_CAPITAL_FULL_DECISION_OFFLINE_V0.1"
LOCKS = {"production": "NOT_APPROVED", "external_action_authority": "NONE",
         "capital_decision_authority": "USER_ONLY", "machine_execution": "FORBIDDEN"}
ACTIONS = ("BUY", "SELL", "HOLD", "WAIT", "ROTATE")
WAIT_KINDS = ("ACTIVE_WAIT", "CONDITION_NOT_MET", "EVIDENCE_BLOCKED")
SOURCE_FIELDS = {"source_main_sha", "bridge_payload_hash", "evidence_lineage",
                 "broker_observation", "user_intent", "qualification", "instruments",
                 "fees", "posture", "task", "governance", "evidence_validity"}
SENSITIVE = re.compile(r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|file://|/(?:Users|home|tmp|var)/|"
                       r"\bsk-[A-Za-z0-9_-]{12,}|\bBearer\s+\S+|"
                       r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|"
                       r"\b(?:bc1|0x)[A-Za-z0-9]{20,}|\b[UDF]\d{6,}\b)", re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def number(value, *, positive=False):
    require(type(value) in (int, float, str), "NUMBER_REQUIRED")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("NUMBER_REQUIRED") from exc
    require(result.is_finite() and (result > 0 if positive else result >= 0), "INVALID_NUMBER")
    return result


def fields(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected), "FIELD_SET_MISMATCH")


def text(value):
    require(isinstance(value, str) and bool(value.strip()) and not SENSITIVE.search(value),
            "PUBLIC_TEXT_REQUIRED")
    return value


def fresh(row, at_ms):
    require(isinstance(row, dict) and type(row.get("as_of_ms")) is int
            and type(row.get("valid_until_ms")) is int
            and 0 < row["as_of_ms"] <= at_ms < row["valid_until_ms"], "SOURCE_STALE_OR_MISSING")
    text(row.get("source_ref"))


def _canonical_source(source):
    result = deepcopy(source)
    # Asset/order permutations are semantic no-ops. Preserve duplicate orders.
    for key in ("instruments", "fees"):
        result[key] = sorted(result[key], key=digest)
    result["task"]["scopes"] = sorted(result["task"]["scopes"], key=lambda r: r["decision_scope"])
    broker = result.get("broker_observation")
    if isinstance(broker, dict):
        for key in ("holdings", "open_orders"):
            broker[key] = sorted(broker.get(key, []), key=digest)
    return result


def source_hash(source):
    return digest(_canonical_source(source))


def build_source(*, payload, source_main_sha, broker_observation, user_intent,
                 qualification, instruments, fees, task, evidence_validity,
                 posture_context=None, at_ms):
    """Bind existing local inputs, projecting only approved posture fields.

    Qualification/fees are attributed source facts, never generated defaults.
    In their absence exact dependent claims remain BLOCKED. Original local
    posture stays LOCAL_ONLY; its full object is not attached to an envelope.
    """
    posture = None
    if posture_context is not None:
        p = posture_context
        require(p.get("schema_version") == "CRT_CAPITAL_POSTURE_CONTEXT_V0.1"
                and p.get("storage") == "LOCAL_ONLY"
                and p.get("parent_evidence_pack_hash") == payload["event"]["source_evidence_pack_hash"]
                and p.get("context_hash") == digest({k: v for k, v in p.items() if k != "context_hash"}),
                "LOCAL_POSTURE_LINEAGE_INVALID")
        for key, value in LOCKS.items():
            require(p.get(key) == value, "LOCAL_POSTURE_AUTHORITY_INVALID")
        rail = p.get("current_strategic_capital_posture", {})
        provenance = rail.get("provenance", {})
        require(type(provenance.get("valid_until_ms")) is int, "POSTURE_VALIDITY_REQUIRED")
        from .portfolio_allocation_context import compact_portfolio_allocation_context_for_bridge
        original_health = p.get("supporting_evidence", {}).get("company_health", {})
        health = compact_portfolio_allocation_context_for_bridge({"common_equity_health": original_health})["common_equity_health"]
        # The older bridge summary limits missing-claim examples. This contract
        # retains all of them; no counterevidence is removed to meet capacity.
        for asset, row in health.get("assets", {}).items():
            original = original_health.get("assets", {}).get(asset, {}).get("company_health", {})
            for dimension, detail in row.get("company_health", {}).get("dimensions", {}).items():
                detail["missing_evidence"] = deepcopy(original["dimensions"][dimension]["missing_evidence"])
        from .gpt_handoff import expand_bridge_field_names
        bridge_health = expand_bridge_field_names(payload)["market_context"].get("common_equity_health")
        compact_health = compact_portfolio_allocation_context_for_bridge({"common_equity_health": original_health})["common_equity_health"]
        if bridge_health == compact_health:
            extra_missing = {}
            for asset, row in health.get("assets", {}).items():
                for dimension, detail in row.get("company_health", {}).get("dimensions", {}).items():
                    existing = bridge_health["assets"][asset]["company_health"]["dimensions"][dimension]["missing_evidence"]
                    if detail["missing_evidence"] != existing:
                        extra_missing.setdefault(asset, {})[dimension] = detail["missing_evidence"]
            health = {"same_as": "market_context.common_equity_health", "full_missing_evidence": extra_missing}
        research = p["research_posture_candidate"]
        research_projection = {k: deepcopy(research.get(k)) for k in (
            "state", "reason", "research_state", "eligibility_level", "posture_candidate",
            "final_eligibility", "plan_invalidation", "required_downstream_gates")}
        contradictions = []
        for row in p["contradictions"]:
            if row.get("reason") == "HEALTH_REQUIRES_ANALYST":
                require(row.get("source") == original_health.get("assets", {}).get(row.get("asset")), "HEALTH_LINEAGE_MISMATCH")
                contradictions.append({"asset": row["asset"], "reason": row["reason"], "source": "posture.health"})
            else:
                contradictions.append(deepcopy(row))
        posture = {"source_ref": "capital_posture_context", "as_of_ms": p["as_of_ms"],
            "valid_until_ms": provenance["valid_until_ms"], "context_hash": p["context_hash"],
            "formal_season": "SEE_EXISTING_MARKET_CONTEXT_NO_REINTERPRETATION",
            "research_state": json.dumps(research_projection, ensure_ascii=False, sort_keys=True),
            "rail": json.dumps(p["current_rail_step"], ensure_ascii=False, sort_keys=True),
            "contradictions": [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in contradictions],
            "blockers": list(p["blockers"]), "health": health}
    result = {"source_main_sha": source_main_sha, "bridge_payload_hash": payload["bridge_payload_hash"],
        "evidence_lineage": payload["event"]["source_evidence_pack_hash"], "evidence_validity": deepcopy(evidence_validity),
        "broker_observation": deepcopy(broker_observation), "user_intent": deepcopy(user_intent),
        "qualification": deepcopy(qualification), "instruments": deepcopy(instruments), "fees": deepcopy(fees),
        "posture": posture, "task": deepcopy(task), "governance": dict(LOCKS)}
    build_projection(payload, result, at_ms=at_ms)
    return _canonical_source(result)


def validate_source(source, *, at_ms):
    fields(source, SOURCE_FIELDS)
    require(source["governance"] == LOCKS, "FORMAL_LOCK_CHANGED")
    require(re.fullmatch(r"[0-9a-f]{40}", source["source_main_sha"]) is not None, "SOURCE_MAIN_REQUIRED")
    for key in ("bridge_payload_hash", "evidence_lineage"):
        require(re.fullmatch(r"[0-9a-f]{64}", source[key]) is not None, "LINEAGE_REQUIRED")
    fields(source["evidence_validity"], {"source_ref", "as_of_ms", "valid_until_ms"})
    task = source["task"]
    fields(task, {"task_id", "replaces", "scopes", "as_of_ms", "valid_until_ms", "source_ref"})
    fresh(task, at_ms)
    text(task["task_id"])
    require(task["replaces"] is None or isinstance(task["replaces"], str), "REPLACEMENT_INVALID")
    require(isinstance(task["scopes"], list) and bool(task["scopes"]), "SCOPES_REQUIRED")
    scopes = set()
    for row in task["scopes"]:
        fields(row, {"decision_scope", "asset", "exposure"})
        text(row["decision_scope"])
        require(row["decision_scope"] not in scopes, "DUPLICATE_SCOPE")
        scopes.add(row["decision_scope"])
        require(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", row["asset"]) is not None, "ASSET_REQUIRED")
        require(row["exposure"] in ("EXISTING", "PROPOSED_CHANGE"), "EXPOSURE_SCOPE_REQUIRED")
    require(isinstance(source["instruments"], list) and isinstance(source["fees"], list), "FACT_LIST_REQUIRED")
    intent = source["user_intent"]
    if intent is not None:
        fields(intent, {"version", "source", "confirmed_at_ms", "reserved_usd", "no_leverage"})
    broker = source["broker_observation"]
    if broker is not None:
        fields(broker, {"schema_version", "source", "observed_at_ms", "started_at_ms",
            "automatic_local_refresh", "scope", "holdings", "funds", "open_orders",
            "action_output", "external_action_authority", "external_action_performed", "observation_hash"})
        for row in broker["holdings"]:
            fields(row, {"asset", "quantity", "currency", "security_type", "average_cost_usd"})
        for row in broker["open_orders"]:
            fields(row, {"asset", "side", "currency", "order_type", "quantity", "filled_quantity",
                         "remaining_quantity", "limit_price_usd"})
    if source["qualification"] is not None:
        fields(source["qualification"], {"source_ref", "as_of_ms", "valid_until_ms", "observation_hash",
            "cash_semantics", "available_funds_orders", "restricted_cash_usd",
            "position_restrictions", "open_buy_fee_upper_bound_usd"})
    _privacy(source)
    return _canonical_source(source)


def _qualified(source, at_ms):
    q = source.get("qualification")
    fields(q, {"source_ref", "as_of_ms", "valid_until_ms", "observation_hash",
               "cash_semantics", "available_funds_orders", "restricted_cash_usd",
               "position_restrictions", "open_buy_fee_upper_bound_usd"})
    fresh(q, at_ms)
    require(q["observation_hash"] == source["broker_observation"]["observation_hash"], "QUALIFICATION_SNAPSHOT_MISMATCH")
    require(q["cash_semantics"] == "USD_SECURITIES_SETTLED_NONBORROWED_GROSS_OF_OPEN_ORDERS",
            "CASH_SEMANTICS_UNPROVEN")
    require(q["available_funds_orders"] in ("INCLUDED", "EXCLUDED"), "AVAILABLE_FUNDS_SEMANTICS_UNPROVEN")
    return q


def normalize_spending_cap(source, *, at_ms):
    """Do not change analysis_cash_budget_usd. No proceeds or leverage inputs.

    Cash and settled cash are qualified gross amounts. Occupancy is removed once
    from that cash branch. AvailableFunds has its own explicit occupancy basis;
    it is a ceiling, never additional cash. Reserve is removed after the minimum.
    """
    try:
        checked = validate_broker_observation(source["broker_observation"], at_ms=at_ms)
        require(checked["state"] == "AVAILABLE", checked["reason"])
        broker = checked["observation"]
        q = _qualified(source, at_ms)
        intent = source["user_intent"]
        fields(intent, {"version", "source", "confirmed_at_ms", "reserved_usd", "no_leverage"})
        require(intent["source"] == "USER_CONFIRMED" and intent["no_leverage"] is True
                and type(intent["confirmed_at_ms"]) is int
                and 0 < intent["confirmed_at_ms"] <= at_ms, "USER_INTENT_UNCONFIRMED")
        text(intent["version"])
        cash = number(broker["funds"]["cash_usd"])
        settled = number(broker["funds"]["settled_cash_usd"])
        available = number(broker["funds"]["available_funds_usd"])
        commitment = Decimal(0)
        for order in broker["open_orders"]:
            remaining = _remaining(order)
            if order["side"] == "BUY" and remaining:
                require(order["order_type"] == "LMT", "OPEN_ORDER_PRICE_BOUND_UNKNOWN")
                commitment += remaining * number(order["limit_price_usd"], positive=True)
        fees = number(q["open_buy_fee_upper_bound_usd"]) if commitment else Decimal(0)
        occupancy = commitment + fees
        free_cash = min(cash, settled) - occupancy - number(q["restricted_cash_usd"])
        if q["available_funds_orders"] == "EXCLUDED":
            available -= occupancy
        cap = max(Decimal(0), min(free_cash, available) - number(intent["reserved_usd"]))
        return {"state": "AVAILABLE", "amount_usd": str(cap.quantize(Decimal(".01"), rounding=ROUND_FLOOR)),
                "open_order_cash_commitment_usd": str(commitment), "reason": "QUALIFIED_CASH_INTERSECTION"}
    except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
        return {"state": "BLOCKED", "amount_usd": None,
                "open_order_cash_commitment_usd": None, "reason": str(exc)}


def _remaining(order):
    total, filled, remaining = [number(order.get(k)) for k in ("quantity", "filled_quantity", "remaining_quantity")]
    require(abs(total - filled - remaining) <= Decimal(".00000001"), "OPEN_ORDER_ALIGNMENT_UNKNOWN")
    return remaining


def position_available(source, asset, *, at_ms, selling=False):
    checked = validate_broker_observation(source["broker_observation"], at_ms=at_ms)
    require(checked["state"] in ("AVAILABLE", "PARTIAL"), checked["reason"])
    broker = checked["observation"]
    require(broker["scope"]["positions_complete"] is True, "HOLDINGS_INCOMPLETE")
    quantity = sum((number(r["quantity"]) for r in broker["holdings"] if r["asset"] == asset), Decimal(0))
    if selling:
        require(broker["scope"]["orders_complete"] is True, "ORDERS_INCOMPLETE")
        # Position restrictions are independent from cash/fees qualification.
        q = source.get("qualification")
        fresh(q, at_ms)
        require(q.get("observation_hash") == broker["observation_hash"], "QUALIFICATION_SNAPSHOT_MISMATCH")
        restrictions = q.get("position_restrictions")
        require(isinstance(restrictions, dict) and asset in restrictions, "POSITION_RESTRICTIONS_UNKNOWN")
        quantity -= number(restrictions[asset])
        quantity -= sum((_remaining(r) for r in broker["open_orders"]
                         if r["asset"] == asset and r["side"] == "SELL"), Decimal(0))
    require(quantity >= 0, "POSITION_OVERCOMMITTED")
    return quantity


def build_projection(payload, source, *, at_ms):
    """Allowlisted capital fields plus existing minimized market evidence.

    No private profile or LOCAL_ONLY capital_posture_context object is exported.
    The posture argument is a small attributed projection, not that context.
    """
    from .gpt_transport_worker import validate_transport_payload
    validate_transport_payload(payload)
    source = validate_source(source, at_ms=at_ms)
    require(source["bridge_payload_hash"] == payload["bridge_payload_hash"], "BRIDGE_LINEAGE_MISMATCH")
    require(source["evidence_lineage"] == payload["event"]["source_evidence_pack_hash"], "EVIDENCE_LINEAGE_MISMATCH")
    from .gpt_handoff import expand_bridge_field_names
    expanded = expand_bridge_field_names(payload)
    require(source["evidence_validity"]["as_of_ms"] == expanded["market_context"].get("generated_at_ms"),
            "EVIDENCE_CLOCK_RELABEL_FORBIDDEN")
    broker = validate_broker_observation(source["broker_observation"], at_ms=at_ms).get("observation")
    # Preserve unavailable as null, never convert it to an empty account.
    capital = None if broker is None else {
        "source": broker["source"], "observed_at_ms": broker["observed_at_ms"],
        "scope": broker["scope"], "funds": broker["funds"],
        "holdings": [{k: r[k] for k in ("asset", "quantity", "currency", "security_type")}
                     for r in broker["holdings"]], "open_orders": broker["open_orders"]}
    posture = source["posture"]
    if posture is not None:
        expected = {"source_ref", "as_of_ms", "valid_until_ms", "context_hash",
                    "formal_season", "research_state", "rail", "contradictions", "blockers"}
        fields(posture, expected | ({"health"} if "health" in posture else set()))
        fresh(posture, at_ms)
        require(re.fullmatch(r"[0-9a-f]{64}", posture["context_hash"]) is not None, "POSTURE_HASH_REQUIRED")
        for key in ("formal_season", "research_state", "rail"):
            text(posture[key])
        for key in ("contradictions", "blockers"):
            require(isinstance(posture[key], list), "POSTURE_LIST_REQUIRED")
            for value in posture[key]:
                text(value)
    instruments = []
    for r in source["instruments"]:
        fields(r, {"asset", "asset_class", "currency", "quantity_step", "source_ref", "as_of_ms", "valid_until_ms"})
        instruments.append(deepcopy(r))
    fees = []
    for r in source["fees"]:
        fields(r, {"asset", "side", "quantity_max", "upper_bound_usd", "source_ref", "as_of_ms", "valid_until_ms"})
        fees.append(deepcopy(r))
    result = {"contract_version": REQUEST_VERSION, "source_hash": source_hash(source),
        "source_main_sha": source["source_main_sha"], "evidence_lineage": source["evidence_lineage"],
        "evidence_validity": deepcopy(source["evidence_validity"]),
        "capital_pool": "POOL_1", "currency": "USD", "capital": capital,
        "user_intent": deepcopy(source["user_intent"]), "spending_cap": normalize_spending_cap(source, at_ms=at_ms),
        "instruments": instruments, "fees": fees, "posture": deepcopy(posture),
        "task": deepcopy(source["task"]), "market_context": deepcopy(payload["market_context"]),
        "event": deepcopy(payload["event"]), "authority": deepcopy(payload["authority"]),
        "issuer_ratio_observation": deepcopy(payload.get("issuer_ratio_observation")), "governance": dict(LOCKS)}
    _privacy(result)
    return result


def _privacy(value):
    if isinstance(value, dict):
        for key, child in value.items():
            require(not re.search(r"credential|password|private_key|wallet|account_number|order_id|contact|local_path", key, re.I),
                    "PRIVATE_FIELD_FORBIDDEN")
            _privacy(child)
    elif isinstance(value, list):
        for child in value:
            _privacy(child)
    elif isinstance(value, str):
        require(not SENSITIVE.search(value), "PRIVATE_TEXT_FORBIDDEN")


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def response_format():
    string = {"type": "string"}
    strings = {"type": "array", "items": string}
    nullable_number = {"type": ["number", "null"]}
    leg = _object({"leg_id": string, "asset": string, "action": {"type": "string", "enum": ["BUY", "SELL"]},
        "quantity": nullable_number, "price_condition": string,
        "order_type": {"type": "string", "enum": ["LIMIT", "MARKET"]},
        "limit_price_usd": nullable_number, "dependent_legs": strings})
    item = _object({"decision_scope": string, "asset": string,
        "action": {"type": "string", "enum": list(ACTIONS)}, "reason": string,
        "supporting_evidence": strings, "contradictions": strings, "applicability": string,
        "invalidation": string, "next_trigger": string, "blockers": strings,
        "wait_kind": {"type": ["string", "null"], "enum": [None, *WAIT_KINDS]},
        "legs": {"type": "array", "items": leg}})
    return {"type": "json_schema", "name": "crt_capital_recommendation_v01", "strict": True,
        "schema": _object({"contract_version": {"type": "string", "enum": [VERSION]},
            "task_id": string, "items": {"type": "array", "items": item}})}


INSTRUCTIONS = (
    "Return one complete portfolio capital recommendation JSON for every requested decision_scope. "
    "You own causal judgment, opposing evidence, opportunity cost versus cash and other assets, "
    "portfolio interaction and decision asymmetry. Select BUY/SELL/HOLD/WAIT/ROTATE yourself. "
    "No rule maps Season, Health, allocation gap or HARVEST to a trade. "
    "HOLD requires existing holdings; WAIT concerns a proposed change and has ACTIVE_WAIT, "
    "CONDITION_NOT_MET or EVIDENCE_BLOCKED wait_kind. Other actions use null wait_kind. "
    "Different scopes may HOLD existing exposure and WAIT an addition. "
    "BUY/SELL use one leg; ROTATE uses one SELL and one BUY of distinct assets, with the BUY "
    "dependent_legs containing the sell leg_id. Unfilled sale proceeds are not current cash. "
    "Legs alone specify quantities and price conditions. Missing precise quantity is null; "
    "do not guess fees, price bounds or sizing. No zero-fill, no invented slippage. "
    "LIMIT requires a positive limit_price_usd; MARKET uses null. Limits do not guarantee fills. "
    "Use supporting_evidence references bridge or posture, and supplied source_ref values. "
    "Every item needs specific reason, contradictions (empty only if none found), applicability, "
    "invalidation, next_trigger and blockers. Address existing orders; HOLD does not freeze exposure. "
    "Keep explanations concise in Traditional Chinese. No prose outside JSON. "
    "Decision support only: Production NOT_APPROVED, external authority NONE, user capital "
    "authority USER_ONLY, machine execution FORBIDDEN. Synthetic fixtures are never live advice."
)


def _check_shape(value, schema):
    types = schema.get("type")
    types = types if isinstance(types, list) else [types]
    actual = ("null" if value is None else "boolean" if isinstance(value, bool) else
              "object" if isinstance(value, dict) else "array" if isinstance(value, list) else
              "number" if type(value) in (int, float) else "string" if isinstance(value, str) else "invalid")
    require(actual in types, "RESPONSE_TYPE_MISMATCH")
    if "enum" in schema:
        require(value in schema["enum"], "RESPONSE_ENUM_MISMATCH")
    if actual == "object":
        fields(value, schema["properties"])
        for k, v in value.items():
            _check_shape(v, schema["properties"][k])
    elif actual == "array":
        for v in value:
            _check_shape(v, schema["items"])
    elif actual == "string":
        text(value)


def _instrument(source, asset, at_ms):
    rows = [r for r in source["instruments"] if r["asset"] == asset]
    require(len(rows) == 1, "INSTRUMENT_UNCONFIRMED")
    row = rows[0]
    fresh(row, at_ms)
    require(row["asset_class"] == "US_SECURITY" and row["currency"] == "USD", "ASSET_OUTSIDE_US_SECURITIES_SCOPE")
    return number(row["quantity_step"], positive=True)


def _fee(source, leg, at_ms):
    rows = [r for r in source["fees"] if r["asset"] == leg["asset"] and r["side"] == leg["action"]]
    require(len(rows) == 1, "FEE_UPPER_BOUND_UNKNOWN")
    row = rows[0]
    fresh(row, at_ms)
    require(number(leg["quantity"], positive=True) <= number(row["quantity_max"], positive=True), "FEE_BOUND_QUANTITY_EXCEEDED")
    return number(row["upper_bound_usd"])


def validate_recommendation(recommendation, source, *, at_ms):
    """Return validated claims with original intent; never silently alter action/size.

    Schema, contradictions and overcommitment reject the portfolio. Missing
    evidence yields explicit claim blockers while independent claims survive.
    """
    source = validate_source(source, at_ms=at_ms)
    _check_shape(recommendation, response_format()["schema"])
    require(recommendation["task_id"] == source["task"]["task_id"], "TASK_LINEAGE_MISMATCH")
    scopes = {r["decision_scope"]: r for r in source["task"]["scopes"]}
    items = recommendation["items"]
    require(len(items) == len(scopes) and {i["decision_scope"] for i in items} == set(scopes), "COMPLETE_UNIQUE_SCOPES_REQUIRED")
    cap = normalize_spending_cap(source, at_ms=at_ms)
    used_cash, used_positions, ids = Decimal(0), {}, set()
    known_refs = {"bridge", "posture"} | {r["source_ref"] for r in source["fees"] + source["instruments"]}
    validated = []
    for item in sorted(items, key=lambda i: i["decision_scope"]):
        scope, action = scopes[item["decision_scope"]], item["action"]
        require(item["asset"] == scope["asset"], "SCOPE_ASSET_MISMATCH")
        require(item["supporting_evidence"] and set(item["supporting_evidence"]) <= known_refs, "EVIDENCE_REFERENCE_UNKNOWN")
        require(set(item["supporting_evidence"]) & {"bridge", "posture"}, "INVESTMENT_EVIDENCE_REQUIRED")
        require("posture" not in item["supporting_evidence"] or source["posture"] is not None, "POSTURE_EVIDENCE_MISSING")
        blockers, legs = list(item["blockers"]), item["legs"]
        try:
            _instrument(source, item["asset"], at_ms)
        except ValueError as exc:
            if str(exc) == "ASSET_OUTSIDE_US_SECURITIES_SCOPE":
                raise
            blockers.append("judgment:" + str(exc))
        for ref in item["supporting_evidence"]:
            rows = ([source["evidence_validity"]] if ref == "bridge" else
                    [source["posture"]] if ref == "posture" else
                    [r for r in source["instruments"] + source["fees"] if r["source_ref"] == ref])
            try:
                for row in rows:
                    fresh(row, at_ms)
            except ValueError as exc:
                blockers.append("judgment:" + str(exc))
        out = deepcopy(item)
        out["blockers"] = blockers
        out["validated_legs"] = []
        if action == "HOLD":
            require(scope["exposure"] == "EXISTING" and not legs and item["wait_kind"] is None, "HOLD_SCOPE_INVALID")
            require(position_available(source, item["asset"], at_ms=at_ms) > 0, "HOLD_REQUIRES_CONFIRMED_POSITION")
        elif action == "WAIT":
            require(scope["exposure"] == "PROPOSED_CHANGE" and not legs and item["wait_kind"] in WAIT_KINDS, "WAIT_SCOPE_INVALID")
            require(item["wait_kind"] != "EVIDENCE_BLOCKED" or bool(blockers), "WAIT_BLOCKERS_REQUIRED")
            require(item["wait_kind"] == "EVIDENCE_BLOCKED" or not blockers, "ACTIVE_WAIT_HAS_EVIDENCE_BLOCKERS")
        else:
            require(item["wait_kind"] is None, "TRADE_WAIT_KIND_INVALID")
            if action == "ROTATE":
                require(len(legs) == 2 and {l["action"] for l in legs} == {"BUY", "SELL"}, "ROTATION_LEGS_REQUIRED")
                sell = next(l for l in legs if l["action"] == "SELL")
                buy = next(l for l in legs if l["action"] == "BUY")
                require(sell["asset"] == item["asset"] and buy["asset"] != sell["asset"]
                        and not sell["dependent_legs"] and buy["dependent_legs"] == [sell["leg_id"]], "ROTATION_DEPENDENCY_INVALID")
            else:
                require(len(legs) == 1 and legs[0]["action"] == action and legs[0]["asset"] == item["asset"]
                        and not legs[0]["dependent_legs"], "SINGLE_TRADE_LEG_INVALID")
        for leg in sorted(legs, key=lambda l: l["leg_id"]):
            require(leg["leg_id"] not in ids, "DUPLICATE_LEG")
            ids.add(leg["leg_id"])
            claims = []
            quantity = None
            effect = {"spend_upper_bound_usd": None, "proceeds_lower_bound_usd": None,
                      "exact_net_proceeds_usd": None, "current_capital_credit_usd": "0"}
            try:
                step = _instrument(source, leg["asset"], at_ms)
                quantity = number(leg["quantity"], positive=True)
                require(quantity % step == 0, "QUANTITY_STEP_MISMATCH_REJUDGMENT_REQUIRED")
            except (ValueError, KeyError, TypeError) as exc:
                if str(exc) == "QUANTITY_STEP_MISMATCH_REJUDGMENT_REQUIRED":
                    raise
                claims.append("quantity:" + str(exc))
            if leg["order_type"] == "LIMIT":
                require(leg["limit_price_usd"] is not None, "LIMIT_PRICE_REQUIRED")
                price = number(leg["limit_price_usd"], positive=True)
            else:
                require(leg["limit_price_usd"] is None, "MARKET_PRICE_IS_NOT_A_BOUND")
                price = None
            fee = None
            try:
                fee = _fee(source, leg, at_ms)
            except (ValueError, KeyError, TypeError) as exc:
                claims.append(("quantity:" if leg["action"] == "BUY" else "net_proceeds:") + str(exc))
            if leg["action"] == "BUY":
                if price is None:
                    claims.append("quantity:PRICE_UPPER_BOUND_UNKNOWN")
                if quantity is not None and price is not None and fee is not None:
                    effect["spend_upper_bound_usd"] = str(quantity * price + fee)
                if not leg["dependent_legs"]:
                    if cap["state"] != "AVAILABLE":
                        claims.append("quantity:" + cap["reason"])
                    elif not claims and not blockers:
                        used_cash += number(effect["spend_upper_bound_usd"])
                status = "DEPENDENT_CONDITIONAL" if leg["dependent_legs"] else "VALIDATED"
            else:
                try:
                    available = position_available(source, leg["asset"], at_ms=at_ms, selling=True)
                    if quantity is not None:
                        used_positions[leg["asset"]] = used_positions.get(leg["asset"], Decimal(0)) + quantity
                        require(used_positions[leg["asset"]] <= available, "POSITION_REUSE_OR_EXCESS_REJUDGMENT_REQUIRED")
                except (ValueError, KeyError, TypeError) as exc:
                    if str(exc) == "POSITION_REUSE_OR_EXCESS_REJUDGMENT_REQUIRED":
                        raise
                    claims.append("quantity:" + str(exc))
                if quantity is not None and price is not None and fee is not None:
                    effect["proceeds_lower_bound_usd"] = str(quantity * price - fee)
                status = "VALIDATED"
            if any(c.startswith("quantity:") for c in claims) or blockers:
                status = "BLOCKED"
            out["validated_legs"].append({**deepcopy(leg), "claim_blockers": claims,
                "validation_state": status, "capital_effect": effect,
                "funding_source": "SALE_LEG_AFTER_FILL_SETTLEMENT_AND_REVALIDATION" if leg["dependent_legs"] else
                                  "POOL_1" if leg["action"] == "BUY" else "CONFIRMED_HOLDING"})
        out["open_order_handling"] = _order_disclosure(source, item["asset"], at_ms)
        out["validation_state"] = "BLOCKED" if blockers or any(l["validation_state"] == "BLOCKED" for l in out["validated_legs"]) else "VALIDATED"
        # Declared missing investment evidence can justify waiting, never a trade.
        # Added source/instrument validation failures still block the conclusion.
        if (action == "WAIT" and item["wait_kind"] == "EVIDENCE_BLOCKED"
                and blockers == item["blockers"]):
            out["validation_state"] = "VALIDATED_NON_TRADING_WAIT"
        validated.append(out)
    if cap["state"] == "AVAILABLE":
        require(used_cash <= number(cap["amount_usd"]), "SHARED_BUDGET_EXCEEDED_REJUDGMENT_REQUIRED")
    result = {"contract_version": VERSION, "recommendation": deepcopy(recommendation),
        "source_hash": source_hash(source), "evidence_lineage": source["evidence_lineage"],
        "capital_snapshot_hash": digest(source["broker_observation"]),
        "open_order_snapshot_hash": digest((source["broker_observation"] or {}).get("open_orders")),
        "user_intent_version": (source["user_intent"] or {}).get("version"),
        "evaluated_at_ms": at_ms, "valid_until_ms": source["task"]["valid_until_ms"],
        "task_id": source["task"]["task_id"], "replaces": source["task"]["replaces"],
        "spending_cap": cap, "current_spend_upper_bound_usd": str(used_cash),
        "items": validated, "governance": dict(LOCKS)}
    broker = source.get("broker_observation")
    if isinstance(broker, dict):
        result["valid_until_ms"] = min(result["valid_until_ms"], broker["observed_at_ms"] + MAX_AGE_MS)
    result["validation_hash"] = digest(result)
    return result


def _order_disclosure(source, asset, at_ms):
    checked = validate_broker_observation(source["broker_observation"], at_ms=at_ms)
    broker = checked.get("observation")
    if broker is None or broker["scope"]["orders_complete"] is not True or checked["state"] == "STALE":
        return {"state": "UNKNOWN", "orders": None, "exposure_may_change": None}
    orders = [deepcopy(r) for r in broker["open_orders"] if r["asset"] == asset]
    return {"state": "CONFIRMED_SNAPSHOT", "orders": orders, "exposure_may_change": bool(orders),
            "cancellation_request_releases_occupancy": False}


def assert_current(validated, source, *, at_ms):
    require(digest({k: v for k, v in validated.items() if k != "validation_hash"}) == validated.get("validation_hash"), "VALIDATION_MUTATED")
    require(validated["evaluated_at_ms"] <= at_ms < validated["valid_until_ms"], "RECOMMENDATION_EXPIRED")
    require(validated["source_hash"] == source_hash(source), "RECOMMENDATION_SUPERSEDED")
    # Recheck every claim at current time, rather than reuse a hash as freshness.
    rebuilt = validate_recommendation(validated["recommendation"], source, at_ms=at_ms)
    require(rebuilt["items"] == validated["items"] and rebuilt["spending_cap"] == validated["spending_cap"], "ACTION_CRITICAL_FACT_EXPIRED")


def render(validated):
    """Pure rendering. Caller must assert_current immediately before presentation."""
    require(digest({k: v for k, v in validated.items() if k != "validation_hash"}) == validated.get("validation_hash"), "VALIDATION_MUTATED")
    labels = {"BUY": "買進", "SELL": "賣出", "HOLD": "續抱", "WAIT": "等待", "ROTATE": "輪動"}
    lines = ["美股範圍投資組合資本建議；決策由使用者作成，禁止機器交易。",
             "有效期限（毫秒時間戳）: " + str(validated["valid_until_ms"])]
    immediate = [l for i in validated["items"] for l in i["validated_legs"] if l["validation_state"] == "VALIDATED"]
    if not immediate:
        lines.append("NO-TRADE（本次無已驗證立即交易腿；既有委託仍可能改變曝險）")
    for item in validated["items"]:
        lines.append(f"{item['decision_scope']} | {item['asset']} | {item['action']}（{labels[item['action']]}） | {item['validation_state']}（驗證狀態）")
        if item["validation_state"] == "VALIDATED_NON_TRADING_WAIT":
            lines.append("此決策範圍不得交易；等待補證據後重新驗證。")
        for key, label in (("reason", "理由"), ("supporting_evidence", "支持證據"), ("contradictions", "反證"),
                           ("applicability", "適用條件"), ("invalidation", "失效條件"), ("next_trigger", "下次重判觸發"),
                           ("wait_kind", "等待類型"), ("blockers", "阻塞"), ("open_order_handling", "既有委託與曝險")):
            lines.append(label + ": " + json.dumps(item[key], ensure_ascii=False, sort_keys=True))
        for leg in item["validated_legs"]:
            lines.append("交易腿（價格／數量／資本效果／資金來源／相依／主張阻塞）: " + json.dumps(leg, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def build_envelope(payload, source, *, at_ms, full_decision=False):
    from .openai_responses_adapter_contract import (SMOKE_MODEL, MAX_INPUT_UTF8_BYTES,
        MAX_OUTPUT_TOKENS, API_KEY_ENV_VAR, RESPONSES_PATH)
    projection = build_projection(payload, source, at_ms=at_ms)
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if not full_decision:
        require(len(serialized.encode("utf-8")) <= MAX_INPUT_UTF8_BYTES, "CAPITAL_INPUT_CAPACITY_EXCEEDED")
    result = {"contract_version": FULL_REQUEST_VERSION if full_decision else REQUEST_VERSION, "event_id": payload["event"]["event_id"],
        "bridge_payload_hash": payload["bridge_payload_hash"], "capital_bridge_payload": deepcopy(payload),
        "capital_source": _canonical_source(source), "request_at_ms": at_ms,
        "transport": {"method": "POST", "path": RESPONSES_PATH, "auth_env_var": API_KEY_ENV_VAR, "secret_value_included": False},
        "request_body": {"model": SMOKE_MODEL, "instructions": INSTRUCTIONS, "input": serialized,
            "store": False, "background": False, "max_output_tokens": MAX_OUTPUT_TOKENS,
            "text": {"format": response_format()}},
        "tools_allowed": False, "network_performed": False,
        "production": "NOT_APPROVED", "external_action_authority": "NONE", "action_output": "NONE"}
    if full_decision:
        result["delivery_mode"] = "OFFLINE_ONLY"
        result["measurement"] = {
            "projection_utf8_bytes": len(serialized.encode("utf-8")),
            "request_body_utf8_bytes": len(json.dumps(result["request_body"], ensure_ascii=False).encode("utf-8")),
            "formal_input_capacity": "NOT_APPROVED",
            "model_tokens": "NOT_MEASURED", "model_cost": "NOT_MEASURED",
            "model_comprehension": "NOT_YET_PROVEN"}
    result["request_hash"] = digest(result)
    return result


def validate_envelope(envelope):
    expected = build_envelope(envelope["capital_bridge_payload"], envelope["capital_source"], at_ms=envelope["request_at_ms"],
                              full_decision=envelope.get("contract_version") == FULL_REQUEST_VERSION)
    require(envelope == expected, "CAPITAL_ENVELOPE_MISMATCH")
    return envelope


def validated_receipt(response, envelope, *, at_ms):
    from .openai_responses_adapter_contract import build_delivery_receipt
    validate_envelope(envelope)
    receipt = build_delivery_receipt(response, event_id=envelope["event_id"],
        bridge_payload_hash=envelope["bridge_payload_hash"], request_hash=envelope["request_hash"])
    require(not response.get("incomplete_details") and not response.get("error"), "INCOMPLETE_RECOMMENDATION")
    messages = [r for r in response.get("output", []) if r.get("type") == "message"]
    require(len(messages) == 1 and messages[0].get("status", "completed") == "completed", "ONE_COMPLETE_MESSAGE_REQUIRED")
    parts = messages[0].get("content", [])
    require(len(parts) == 1 and parts[0].get("type") == "output_text", "REFUSAL_OR_EXTRA_OUTPUT")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, "DUPLICATE_JSON_KEY")
            obj[key] = value
        return obj
    recommendation = json.loads(receipt["output_text"], object_pairs_hook=unique,
                                parse_constant=lambda _: require(False, "NONFINITE_JSON"))
    validation = validate_recommendation(recommendation, envelope["capital_source"], at_ms=at_ms)
    # Qualification belongs to the affected asset, not the model's choice of
    # reference label. Execution facts cannot bypass an investment evidence gate.
    from .gpt_handoff import expand_bridge_field_names
    expanded = expand_bridge_field_names(envelope["capital_bridge_payload"])
    valuations = expanded["market_context"].get("treasury_valuation_context", {})
    if not isinstance(valuations, dict):
        valuations = {}
    if "assets" in valuations:
        common = valuations.get("common", {})
        rows = valuations["assets"]
        valuations = {asset: {**(common if isinstance(common, dict) else {}), **row}
                      if isinstance(row, dict) else None
                      for asset, row in (rows.items() if isinstance(rows, dict) else [])}
    for item in recommendation.get("items", []):
        if item.get("action") in {"BUY", "ROTATE"}:
            buy_assets = {leg["asset"] for leg in item["legs"] if leg["action"] == "BUY"}
            for asset in buy_assets & {"MSTR", "ASST"}:
                valuation = valuations.get(asset)
                require(isinstance(valuation, dict) and valuation.get("formal_action_critical_state") == "AVAILABLE",
                        "VALUATION_EVIDENCE_UNQUALIFIED:" + asset)
    require(all(item["validation_state"] in {"VALIDATED", "VALIDATED_NON_TRADING_WAIT"}
                for item in validation["items"]),
            "CAPITAL_RECOMMENDATION_NOT_VALIDATED")
    receipt["capital_validation"] = validation
    receipt["output_text"] = render(validation)
    receipt.pop("receipt_hash")
    receipt["receipt_hash"] = digest(receipt)
    return receipt
