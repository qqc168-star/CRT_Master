from __future__ import annotations

from copy import deepcopy
from typing import Any

from .premarket_live_market_handoff import (
    validate_premarket_live_market_handoff,
)

CONTRACT_VERSION = "CRT_PREMARKET_BATTLE_MAP_CONTRACT_V0.1"
ASSET_ORDER = ["MSTR", "ASST", "STRC", "SATA"]
FIRST_SCREEN_FIELDS = [
    "light",
    "asset",
    "premarket_price",
    "diluted_mnav",
    "entry_condition",
    "entry_shares_delta",
    "exit_condition",
    "exit_shares_delta",
]
ANALYSIS_SECTION_IDS = [
    "ISSUER_REFLEXIVITY",
    "PRICE_STRUCTURE",
    "VOLUME_QUALITY",
    "SPOT_VS_DERIVATIVES",
    "BULL_BEAR_FORCE_DISTRIBUTION",
    "BTC_MACRO_TRANSMISSION",
    "CAPITAL_CONVEXITY",
    "ACTION_MAP",
]
ANALYST_FIELDS = {
    "light",
    "entry_condition",
    "entry_shares_delta",
    "exit_condition",
    "exit_shares_delta",
}


def validate_premarket_battle_map_contract(
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("battle map contract must be an object")
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("battle map contract version mismatch")
    if contract.get("asset_order") != ASSET_ORDER:
        raise ValueError("battle map asset order mismatch")

    field_rows = contract.get("first_screen_fields")
    if not isinstance(field_rows, list):
        raise ValueError("first_screen_fields must be a list")
    fields = [row.get("field") for row in field_rows if isinstance(row, dict)]
    if fields != FIRST_SCREEN_FIELDS:
        raise ValueError("battle map first-screen field order mismatch")

    sections = contract.get("analysis_sections")
    if not isinstance(sections, list):
        raise ValueError("analysis_sections must be a list")
    section_ids = [row.get("id") for row in sections if isinstance(row, dict)]
    section_indexes = [row.get("index") for row in sections if isinstance(row, dict)]
    if section_ids != ANALYSIS_SECTION_IDS or section_indexes != list(range(1, 9)):
        raise ValueError("battle map analysis section order mismatch")
    if not all(
        isinstance(row, dict) and row.get("required") is True for row in sections
    ):
        raise ValueError("all battle map analysis sections must remain required")

    required_facts = contract.get("required_facts")
    if not isinstance(required_facts, dict):
        raise ValueError("required_facts must be an object")
    if list(required_facts) != ASSET_ORDER:
        raise ValueError("required_facts asset order mismatch")
    for asset in ASSET_ORDER:
        facts = required_facts.get(asset)
        if not isinstance(facts, list) or not facts:
            raise ValueError(f"required facts missing for {asset}")

    issuer_policy = contract.get("issuer_reflexivity_policy")
    if not isinstance(issuer_policy, dict):
        raise ValueError("issuer reflexivity policy missing")
    if issuer_policy.get("must_be_first") is not True:
        raise ValueError("issuer reflexivity must remain first")
    if issuer_policy.get("section_must_never_disappear") is not True:
        raise ValueError("issuer reflexivity section must never disappear")

    action_policy = contract.get(
        "action_surface_policy"
    )

    if not isinstance(action_policy, dict):
        raise ValueError(
            "battle map action surface policy missing"
        )

    expected_action_policy = {
        "owner": "GPT",
        "purpose": (
            "CONDITIONAL_CAPITAL_EXPOSURE_DECISION_SURFACE"
        ),
        "entry_condition": {
            "asset_price_clause_required": True,
            "btc_price_clause_required": True,
            "confirmation_clause_supported": True,
        },
        "entry_shares_delta": {
            "sign": "NONNEGATIVE",
            "zero_allowed": True,
        },
        "exit_condition": {
            "required_channels": [
                "STOP_LOSS",
                "TAKE_PROFIT",
            ],
            "asset_price_clause_required": True,
            "btc_price_clause_required": True,
            "confirmation_clause_supported": True,
        },
        "exit_shares_delta": {
            "stop_loss": {
                "sign": "NONPOSITIVE",
                "zero_allowed": True,
            },
            "take_profit": {
                "sign": "NONPOSITIVE",
                "zero_allowed": True,
            },
            "independent_by_channel": True,
        },
        "price_reaching_is_not_action_trigger": True,
        "condition_requires_context": True,
        "machine_execution": "FORBIDDEN",
        "external_action_authority": "NONE",
        "capital_decision_authority": "USER_ONLY",
    }

    if action_policy != expected_action_policy:
        raise ValueError(
            "battle map action surface policy mismatch"
        )

    mnav_policy = contract.get("mnav_policy")
    if not isinstance(mnav_policy, dict):
        raise ValueError("mNAV policy missing")
    if (
        mnav_policy.get("semantic_lock")
        != "DO_NOT_REDEFINE_EXISTING_CRT_MNAV_SEMANTICS"
    ):
        raise ValueError("mNAV semantic lock mismatch")
    if mnav_policy.get("nav_composition_owner") != "UPSTREAM_FORMAL_SEMANTICS":
        raise ValueError("mNAV composition ownership mismatch")

    governance = contract.get("governance")
    if not isinstance(governance, dict):
        raise ValueError("battle map governance missing")
    expected = {
        "production": "NOT_APPROVED",
        "external_action_authority": "NONE",
        "action_output": "NONE",
        "capital_decision_authority": "USER_ONLY",
        "machine_may_execute_trade": False,
        "formal_weights_unchanged": True,
        "traffic_light_thresholds_unchanged": True,
        "mnav_semantics_unchanged": True,
    }
    for key, value in expected.items():
        if governance.get(key) != value:
            raise ValueError(f"battle map governance mismatch: {key}")
    return deepcopy(contract)


def _claim_state(value: Any) -> str:
    if value is None:
        return "MISSING"
    if isinstance(value, dict):
        state = value.get("state")
        if state in {"BLOCKED", "PARTIAL"}:
            return state
    return "AVAILABLE"


def _display_value(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("state") in {"BLOCKED", "PARTIAL"}:
            return None
        if "value" in value:
            return value.get("value")
        if "mnav" in value:
            return value.get("mnav")
    return value


def _asset_readiness(
    asset: str,
    facts: dict[str, Any],
    required_fields: list[str],
) -> dict[str, Any]:
    status = []
    missing = []
    partial = []
    blocked = []
    for field in required_fields:
        state = _claim_state(facts.get(field))
        status.append({"field": field, "state": state})
        if state == "MISSING":
            missing.append(field)
        elif state == "PARTIAL":
            partial.append(field)
        elif state == "BLOCKED":
            blocked.append(field)

    if blocked:
        overall = "BLOCKED"
    elif missing or partial:
        overall = "PARTIAL"
    else:
        overall = "AVAILABLE"
    return {
        "asset": asset,
        "state": overall,
        "facts": status,
        "missing_fields": missing,
        "partial_fields": partial,
        "blocked_fields": blocked,
    }


def build_premarket_battle_map(
    *,
    contract: dict[str, Any],
    asset_facts: dict[str, Any] | None,
    issuer_reflexivity: dict[str, Any] | None,
    as_of: str | None,
    source_mode: str,
    live_market_handoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    locked = validate_premarket_battle_map_contract(contract)
    modes = locked.get("source_modes", {})
    if source_mode not in modes:
        raise ValueError("unsupported battle map source mode")

    live_market = None

    if live_market_handoff is not None:
        live_market = (
            validate_premarket_live_market_handoff(
                live_market_handoff
            )
        )

        if live_market["source_mode"] != source_mode:
            raise ValueError(
                "battle map / live market source mode mismatch"
            )

    supplied_assets = asset_facts if isinstance(asset_facts, dict) else {}
    required_facts = locked["required_facts"]

    first_screen = []
    readiness = {}
    missing_evidence = []

    for asset in ASSET_ORDER:
        facts = supplied_assets.get(asset)
        facts = facts if isinstance(facts, dict) else {}
        asset_ready = _asset_readiness(asset, facts, required_facts[asset])
        readiness[asset] = asset_ready

        for field in asset_ready["missing_fields"]:
            missing_evidence.append(
                {"asset": asset, "field": field, "state": "MISSING"}
            )
        for field in asset_ready["partial_fields"]:
            missing_evidence.append(
                {"asset": asset, "field": field, "state": "PARTIAL"}
            )
        for field in asset_ready["blocked_fields"]:
            missing_evidence.append(
                {"asset": asset, "field": field, "state": "BLOCKED"}
            )

        diluted_mnav = None
        if asset in {"MSTR", "ASST"}:
            diluted_mnav = _display_value(facts.get("diluted_mnav"))

        first_screen.append(
            {
                "light": None,
                "asset": asset,
                "premarket_price": _display_value(
                    facts.get("premarket_price")
                ),
                "diluted_mnav": diluted_mnav,
                "entry_condition": {
                    "asset_price_clause": None,
                    "btc_price_clause": None,
                    "confirmation_clause": None,
                },
                "entry_shares_delta": None,
                "exit_condition": {
                    "stop_loss": {
                        "asset_price_clause": None,
                        "btc_price_clause": None,
                        "confirmation_clause": None,
                    },
                    "take_profit": {
                        "asset_price_clause": None,
                        "btc_price_clause": None,
                        "confirmation_clause": None,
                    },
                },
                "exit_shares_delta": {
                    "stop_loss": None,
                    "take_profit": None,
                },
            }
        )

    issuer_evidence = (
        deepcopy(issuer_reflexivity)
        if isinstance(issuer_reflexivity, dict)
        else {
            "state": "BLOCKED",
            "event_state": None,
            "reason": "ISSUER_REFLEXIVITY_EVIDENCE_MISSING",
        }
    )

    sections = []
    for index, section_id in enumerate(ANALYSIS_SECTION_IDS, start=1):
        if section_id == "ISSUER_REFLEXIVITY":
            section = {
                "index": index,
                "id": section_id,
                "state": (
                    "READY_FOR_ANALYST"
                    if issuer_evidence.get("state") != "BLOCKED"
                    else "BLOCKED"
                ),
                "machine_evidence": issuer_evidence,
                "analyst_judgment": None,
            }
        else:
            machine_evidence = None
            section_state = "REQUIRED_FOR_ANALYST"

            if live_market is not None:
                candidate = (
                    live_market
                    .get("analysis_inputs", {})
                    .get(section_id)
                )

                if isinstance(candidate, dict):
                    machine_evidence = deepcopy(
                        candidate
                    )

                    section_state = (
                        "BLOCKED"
                        if candidate.get("state")
                        == "BLOCKED"
                        else "READY_FOR_ANALYST"
                    )

            section = {
                "index": index,
                "id": section_id,
                "state": section_state,
                "machine_evidence": machine_evidence,
                "analyst_judgment": None,
            }
        sections.append(section)

    if any(item["state"] == "BLOCKED" for item in readiness.values()):
        overall_state = "PARTIAL"
    elif missing_evidence:
        overall_state = "PARTIAL"
    else:
        overall_state = "READY_FOR_ANALYST"

    return {
        "contract_version": CONTRACT_VERSION,
        "state": overall_state,
        "as_of": as_of,
        "source_mode": source_mode,
        "first_screen": first_screen,
        "asset_fact_readiness": readiness,
        "missing_evidence": missing_evidence,
        "analysis_sections": sections,
        "live_market_handoff": (
            deepcopy(live_market)
            if live_market is not None
            else None
        ),
        "analyst_owned_fields": sorted(ANALYST_FIELDS),
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "machine_may_execute_trade": False,
        "capital_decision_authority": "USER_ONLY",
        "analyst_judgment_required": True,
    }