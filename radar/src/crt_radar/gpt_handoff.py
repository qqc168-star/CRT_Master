from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .gpt_bridge_outbox import enqueue_bridge_payload
from .run_ledger import GENESIS_HASH, RunLedger
from .treasury_company_ct import compact_treasury_valuation_context
from .portfolio_allocation_context import (
    compact_portfolio_allocation_context_for_bridge,
)
from .season_transition_warning_overlay import (
    assert_season_transition_warning_overlay,
)


SCHEMA_VERSION = "CRT_GPT_HANDOFF_V0.1"
HANDOFF_RECORD_TYPE = "GPT_HANDOFF"
RESET_RECORD_TYPE = "GPT_HANDOFF_RESET"

REANALYSIS_SEMANTICS_SCHEMA_VERSION = (
    "CRT_GPT_REANALYSIS_SEMANTICS_V0.1"
)

REANALYSIS_SEQUENCE = (
    "CATALYST",
    "AMPLIFIER",
    "PERSISTENCE",
    "ACCEPTANCE",
    "CONTRADICTIONS",
    "MISSING_EVIDENCE",
)

CAUSAL_GUARDRAILS = (
    "TEMPORAL_ORDER_IS_NOT_CAUSATION",
    "TRANSIENT_PRICE_CROSSING_IS_NOT_ACCEPTANCE_OR_REAL_DEMAND",
    "CONTRADICTORY_EVIDENCE_MUST_BE_SURFACED",
    "MISSING_EVIDENCE_MUST_NOT_BE_IMPUTED_OR_GUESSED",
)

EVIDENCE_RULES = (
    "SEPARATE_OBSERVATION_FROM_INFERENCE",
    "STATE_UNRESOLVED_CAUSALITY_EXPLICITLY",
    "USE_LATEST_REQUIRED_INPUTS",
)

GOVERNANCE_GUARDRAILS = (
    "RESEARCH_OVERLAY_CANNOT_PROMOTE_FORMAL_SEASON",
    "NO_AUTOMATIC_BUY_SELL",
    "NO_EXTERNAL_ACTION",
)

BRIDGE_PAYLOAD_SCHEMA_VERSION = (
    "CRT_MINIMIZED_BRIDGE_PAYLOAD_V0.1"
)

BRIDGE_PRIVACY_CONTRACT_VERSION = (
    "CRT_BRIDGE_PAYLOAD_PRIVACY_CONTRACT_V0.1"
)

SEASON_THREE_ARMY_ANALYSIS_CONTRACT_SCHEMA_VERSION = (
    "CRT_SEASON_THREE_ARMY_GPT_BRIDGE_V0.1"
)

SEASON_THREE_ARMY_ROLE_CONTRACT = {
    "season_scope": "STRATEGIC_RISK_POSTURE_ONLY",
    "bull_foundation_scope": "TRANSITION_CREDIBILITY_ONLY",
    "commander_map_scope": "TACTICAL_LINES_AND_CAPITAL_DEPLOYMENT",
    "candidate_may_promote_formal_season": False,
    "tactical_feedback_may_modify_formal_season": False,
    "formal_season_blocked_output_mode": (
        "LABELED_ANALYST_HYPOTHESIS_OR_WEATHER_ONLY"
    ),
}

TACTICAL_FORMAL_SEASON_OVERRIDE_KEYS = {
    "formal_season",
    "formal_season_authority",
    "season_transition_authority",
}

BRIDGE_FORBIDDEN_EXACT_KEYS = {
    "private_context",
    "profile",
    "path",
    "email",
    "phone",
    "address",
    "account_number",
    "broker_account",
    "brokerage_account",
    "api_key",
    "access_token",
    "password",
    "secret",
    "credential",
    "credentials",
}

BRIDGE_OPTIONAL_MARKET_SECTIONS = (
    "dvol_regime_watch",
    "transition_diagnostic",
    "btc_entry_gate",
    "btc_bull_validation",
    "season_transition_warning_overlay",
    "mstr_asst_market_health",
    "asset_strategy_delta",
    "premarket_market_data",
)


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _authority() -> dict[str, Any]:
    return {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "transport_authority": "NONE",
        "transport_performed": False,
    }


def _reanalysis_semantics() -> dict[str, Any]:
    return {
        "schema_version": (
            REANALYSIS_SEMANTICS_SCHEMA_VERSION
        ),
        "scope": "POST_WAKE_ANALYSIS_ONLY",
        "analysis_sequence": list(
            REANALYSIS_SEQUENCE
        ),
        "causal_guardrails": list(
            CAUSAL_GUARDRAILS
        ),
        "evidence_rules": list(
            EVIDENCE_RULES
        ),
        "governance_guardrails": list(
            GOVERNANCE_GUARDRAILS
        ),
        "wake_authority": "NONE",
        "formal_season_authority": "NONE",
        "trading_authority": "NONE",
        "external_action_authority": "NONE",
    }


def _assert_bridge_privacy(
    value: Any,
    *,
    location: str = "$",
) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.strip().lower()

            if normalized in BRIDGE_FORBIDDEN_EXACT_KEYS:
                raise ValueError(
                    "Bridge payload contains forbidden key "
                    f"{location}.{key}"
                )

            _assert_bridge_privacy(
                child,
                location=f"{location}.{key}",
            )

    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_bridge_privacy(
                child,
                location=f"{location}[{index}]",
            )


def _bridge_data_health(
    pack: dict[str, Any],
) -> dict[str, Any]:
    raw = pack.get("data_health")

    if not isinstance(raw, dict):
        return {
            "source_gate_state": None,
            "critical_blockers": [],
            "unusable_or_missing_evidence": [],
        }

    unusable = []

    for row in raw.get(
        "unusable_or_missing_evidence",
        [],
    ):
        if not isinstance(row, dict):
            continue

        unusable.append(
            {
                "input_family": row.get(
                    "input_family"
                ),
                "quality_state": row.get(
                    "quality_state"
                ),
            }
        )

    return {
        "source_gate_state": raw.get(
            "source_gate_state"
        ),
        "critical_blockers": deepcopy(
            raw.get(
                "critical_blockers",
                [],
            )
        ),
        "unusable_or_missing_evidence": (
            unusable
        ),
    }



def _assert_no_tactical_formal_season_override(
    value: Any,
    *,
    location: str,
) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.strip().lower()

            if normalized in TACTICAL_FORMAL_SEASON_OVERRIDE_KEYS:
                raise ValueError(
                    "Tactical bridge section may not override Formal Season "
                    f"{location}.{key}"
                )

            _assert_no_tactical_formal_season_override(
                child,
                location=f"{location}.{key}",
            )

    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_tactical_formal_season_override(
                child,
                location=f"{location}[{index}]",
            )


def _assert_bridge_analyst_owned_fields_unfilled(
    payload: Any,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(
            "premarket_market_data must be an object"
        )

    battle_map = payload.get("battle_map")
    if not isinstance(battle_map, dict):
        raise ValueError(
            "premarket battle map must be an object"
        )

    rows = battle_map.get("first_screen")
    if not isinstance(rows, list):
        raise ValueError(
            "premarket battle map first screen missing"
        )

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(
                "premarket battle map first-screen row invalid"
            )

        if row.get("light") is not None:
            raise ValueError(
                "premarket battle map machine-filled analyst light"
            )

        if row.get("entry_shares_delta") is not None:
            raise ValueError(
                "premarket battle map machine-filled entry shares"
            )

        entry = row.get("entry_condition")
        if (
            not isinstance(entry, dict)
            or any(value is not None for value in entry.values())
        ):
            raise ValueError(
                "premarket battle map machine-filled entry condition"
            )

        exits = row.get("exit_condition")
        if not isinstance(exits, dict):
            raise ValueError(
                "premarket battle map exit condition invalid"
            )

        for channel in ("stop_loss", "take_profit"):
            condition = exits.get(channel)
            if (
                not isinstance(condition, dict)
                or any(
                    value is not None
                    for value in condition.values()
                )
            ):
                raise ValueError(
                    "premarket battle map machine-filled exit condition"
                )

        if row.get("exit_shares_delta") != {
            "stop_loss": None,
            "take_profit": None,
        }:
            raise ValueError(
                "premarket battle map machine-filled exit shares"
            )


def _season_three_army_analysis_contract(
    pack: dict[str, Any],
    *,
    pack_hash: str,
) -> dict[str, Any]:
    model_status = pack.get("model_status")
    if not isinstance(model_status, dict):
        model_status = {}

    router = model_status.get("btc_season_router")
    if not isinstance(router, dict):
        router = {}

    bull_foundation = pack.get("btc_bull_validation")
    if not isinstance(bull_foundation, dict):
        bull_foundation = {}

    router_state = router.get("state")
    formal_model = router.get("formal_model")
    raw_season = router.get("season")

    formal_season = None
    if (
        formal_model == "APPROVED"
        and router_state not in {
            "BLOCKED",
            "CANDIDATE_BLOCKED",
        }
    ):
        formal_season = raw_season

    contract = {
        "schema_version": (
            SEASON_THREE_ARMY_ANALYSIS_CONTRACT_SCHEMA_VERSION
        ),
        "doctrine_artifact": (
            "CRT_SEASON_THREE_ARMY_COMMANDER_DEPLOYMENT_DOCTRINE_V0.1.md"
        ),
        "season": {
            "scope": SEASON_THREE_ARMY_ROLE_CONTRACT[
                "season_scope"
            ],
            "source_state": router_state,
            "formal_model": formal_model,
            "formal_season": formal_season,
            "candidate_weather_bucket": router.get(
                "candidate_weather_bucket"
            ),
            "output_mode": (
                "FORMAL_SEASON"
                if formal_season is not None
                else SEASON_THREE_ARMY_ROLE_CONTRACT[
                    "formal_season_blocked_output_mode"
                ]
            ),
            "allowed_non_formal_outputs": [
                "LABELED_ANALYST_HYPOTHESIS",
                "WEATHER",
            ],
            "candidate_may_promote_formal_season": False,
        },
        "bull_foundation": {
            "scope": SEASON_THREE_ARMY_ROLE_CONTRACT[
                "bull_foundation_scope"
            ],
            "source_section": "btc_bull_validation",
            "state": bull_foundation.get("state"),
            "may_modify_formal_season": False,
        },
        "capital_state": {
            "source_section": "capital_state",
            "capital_decision_authority": "USER_ONLY",
            "required_for_tactical_deployment": True,
        },
        "commander": {
            "scope": SEASON_THREE_ARMY_ROLE_CONTRACT[
                "commander_map_scope"
            ],
            "source_sections": [
                "asset_strategy_delta",
                "premarket_market_data",
            ],
            "asset_strategy_delta_available": isinstance(
                pack.get("asset_strategy_delta"),
                dict,
            ),
            "premarket_market_data_available": isinstance(
                pack.get("premarket_market_data"),
                dict,
            ),
            "tactical_feedback_may_modify_formal_season": False,
        },
        "authority": {
            "action_output": "NONE",
            "capital_decision_authority": "USER_ONLY",
            "external_action_authority": "NONE",
            "machine_may_execute_trade": False,
        },
    }

    binding_material = {
        "source_evidence_pack_hash": pack_hash,
        "contract": contract,
    }

    return {
        **contract,
        "source_evidence_pack_hash": pack_hash,
        "role_separation_contract_hash": _canonical_hash(
            binding_material
        ),
    }


def _bridge_market_context(
    pack: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "generated_at_ms": pack.get(
            "generated_at_ms"
        ),
        "pack_state": pack.get(
            "pack_state"
        ),
        "data_health": _bridge_data_health(
            pack
        ),
        "layers": deepcopy(
            pack.get(
                "layers",
                {},
            )
        ),
        "changes": deepcopy(
            pack.get(
                "changes",
                {},
            )
        ),
        "distillation": deepcopy(
            pack.get(
                "distillation",
                {},
            )
        ),
        "model_status": deepcopy(
            pack.get(
                "model_status",
                {},
            )
        ),
    }

    for key in BRIDGE_OPTIONAL_MARKET_SECTIONS:
        if key in pack:
            if key == "season_transition_warning_overlay":
                assert_season_transition_warning_overlay(pack[key])

            if key in {
                "asset_strategy_delta",
                "premarket_market_data",
            }:
                _assert_no_tactical_formal_season_override(
                    pack[key],
                    location=f"$.{key}",
                )

            if key == "premarket_market_data":
                _assert_bridge_analyst_owned_fields_unfilled(
                    pack[key]
                )

            result[key] = deepcopy(
                pack[key]
            )

    treasury = compact_treasury_valuation_context(pack)
    if treasury:
        result["treasury_valuation_context"] = treasury
    portfolio = compact_portfolio_allocation_context_for_bridge(pack)
    if portfolio:
        result.update(portfolio)
    return result


def _bridge_capital_condition(
    payload: Any,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(
            "capital-state validity condition "
            "must be an object"
        )

    result: dict[str, Any] = {}

    for key in (
        "field",
        "operator",
        "value",
    ):
        if key in payload:
            result[key] = deepcopy(
                payload[key]
            )

    return result


def _bridge_capital_state(
    private_context: Any,
) -> dict[str, Any]:
    if not isinstance(
        private_context,
        dict,
    ):
        raise ValueError(
            "current private context unavailable"
        )

    if (
        private_context.get("state")
        != "AVAILABLE"
    ):
        raise ValueError(
            "current private context must be AVAILABLE"
        )

    profile = private_context.get(
        "profile"
    )

    if not isinstance(profile, dict):
        raise ValueError(
            "current private profile unavailable"
        )

    status = profile.get(
        "capital_state_status"
    )

    if (
        not isinstance(status, dict)
        or status.get("state")
        != "AVAILABLE"
    ):
        raise ValueError(
            "current Capital State must be AVAILABLE"
        )

    if (
        status.get("execution_authority")
        != "USER_ONLY"
    ):
        raise ValueError(
            "Capital State execution authority "
            "must remain USER_ONLY"
        )

    meta = profile.get("capital_state")

    if not isinstance(meta, dict):
        raise ValueError(
            "capital_state unavailable"
        )

    capital_state = {
        key: deepcopy(meta.get(key))
        for key in (
            "contract_version",
            "source",
            "as_of",
            "base_currency",
        )
    }

    holdings_raw = profile.get(
        "holdings"
    )

    if not isinstance(
        holdings_raw,
        list,
    ):
        raise ValueError(
            "holdings unavailable"
        )

    holdings = []

    for row in holdings_raw:
        if not isinstance(row, dict):
            raise ValueError(
                "holding must be an object"
            )

        holdings.append(
            {
                "asset": row.get("asset"),
                "quantity": row.get(
                    "quantity"
                ),
            }
        )

    cash_raw = profile.get("cash")

    if not isinstance(cash_raw, dict):
        raise ValueError(
            "cash unavailable"
        )

    cash = {
        "available_usd": cash_raw.get(
            "available_usd"
        ),
        "reserved_usd": cash_raw.get(
            "reserved_usd"
        ),
    }

    roles_raw = profile.get(
        "asset_roles"
    )

    if not isinstance(roles_raw, dict):
        raise ValueError(
            "asset_roles unavailable"
        )

    plans_raw = profile.get("plans")

    if not isinstance(plans_raw, list):
        raise ValueError(
            "plans unavailable"
        )

    plans = []

    for plan_raw in plans_raw:
        if not isinstance(plan_raw, dict):
            raise ValueError(
                "plan must be an object"
            )

        if (
            str(
                plan_raw.get("status")
            ).upper()
            != "ACTIVE"
        ):
            continue

        tranches_raw = plan_raw.get(
            "tranches",
            [],
        )

        if not isinstance(
            tranches_raw,
            list,
        ):
            raise ValueError(
                "plan tranches unavailable"
            )

        tranches = []

        for tranche_raw in tranches_raw:
            if not isinstance(
                tranche_raw,
                dict,
            ):
                raise ValueError(
                    "tranche must be an object"
                )

            conditions_raw = (
                tranche_raw.get(
                    "validity_conditions",
                    [],
                )
            )

            if not isinstance(
                conditions_raw,
                list,
            ):
                raise ValueError(
                    "validity_conditions "
                    "must be a list"
                )

            tranches.append(
                {
                    "tranche_id": (
                        tranche_raw.get(
                            "tranche_id"
                        )
                    ),
                    "budget_usd": (
                        tranche_raw.get(
                            "budget_usd"
                        )
                    ),
                    "status": (
                        tranche_raw.get(
                            "status"
                        )
                    ),
                    "validity_conditions": [
                        _bridge_capital_condition(
                            condition
                        )
                        for condition
                        in conditions_raw
                    ],
                }
            )

        plans.append(
            {
                "plan_id": plan_raw.get(
                    "plan_id"
                ),
                "asset": plan_raw.get(
                    "asset"
                ),
                "side": plan_raw.get(
                    "side"
                ),
                "status": plan_raw.get(
                    "status"
                ),
                "tranches": tranches,
            }
        )

    referenced_assets = {
        str(row.get("asset"))
        for row in holdings
        if row.get("asset") is not None
    }

    referenced_assets.update(
        str(row.get("asset"))
        for row in plans
        if row.get("asset") is not None
    )

    asset_roles = {
        str(asset): deepcopy(role)
        for asset, role in roles_raw.items()
        if str(asset) in referenced_assets
    }

    return {
        "capital_state": capital_state,
        "holdings": holdings,
        "cash": cash,
        "asset_roles": asset_roles,
        "active_plans": plans,
        "execution_authority": "USER_ONLY",
    }


def _bridge_plan_drift(
    handoff: dict[str, Any],
) -> dict[str, Any]:
    raw = handoff.get(
        "plan_drift"
    )

    if not isinstance(raw, dict):
        raise ValueError(
            "handoff plan_drift unavailable"
        )

    conditions = []

    for row in raw.get(
        "violated_conditions",
        [],
    ):
        if not isinstance(row, dict):
            continue

        conditions.append(
            {
                key: deepcopy(
                    row.get(key)
                )
                for key in (
                    "plan_id",
                    "tranche_id",
                    "field",
                    "operator",
                    "target_value",
                    "source_kind",
                )
            }
        )

    return {
        "state": raw.get("state"),
        "reason": raw.get("reason"),
        "reanalysis_required": raw.get(
            "reanalysis_required"
        ),
        "violated_conditions": conditions,
    }


def build_minimized_bridge_payload(
    pack: dict[str, Any],
    handoff: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(pack, dict):
        raise ValueError(
            "Evidence Pack must be an object"
        )

    if not isinstance(handoff, dict):
        raise ValueError(
            "GPT handoff must be an object"
        )

    if (
        handoff.get("state")
        != "GPT_HANDOFF_READY"
    ):
        raise ValueError(
            "Bridge payload requires "
            "GPT_HANDOFF_READY"
        )

    pack_hash = pack.get(
        "evidence_pack_hash"
    )

    if (
        not isinstance(pack_hash, str)
        or not pack_hash
    ):
        raise ValueError(
            "Evidence Pack hash unavailable"
        )

    if (
        handoff.get(
            "source_evidence_pack_hash"
        )
        != pack_hash
    ):
        raise ValueError(
            "handoff is not linked to "
            "current Evidence Pack"
        )

    pack_authority = pack.get(
        "authority"
    )

    if not isinstance(
        pack_authority,
        dict,
    ):
        raise ValueError(
            "Evidence Pack authority unavailable"
        )

    if (
        pack_authority.get(
            "production"
        )
        != "NOT_APPROVED"
    ):
        raise ValueError(
            "Production approval must remain "
            "NOT_APPROVED"
        )

    if (
        pack_authority.get(
            "external_action_authority"
        )
        != "NONE"
    ):
        raise ValueError(
            "Evidence Pack EAA must remain NONE"
        )

    if (
        pack_authority.get(
            "capital_decision_authority"
        )
        not in {
            None,
            "USER_ONLY",
        }
    ):
        raise ValueError(
            "Evidence Pack capital decision authority "
            "must remain USER_ONLY"
        )

    required_handoff_authority = {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
        "transport_authority": "NONE",
        "transport_performed": False,
    }

    for key, expected in (
        required_handoff_authority.items()
    ):
        if handoff.get(key) != expected:
            raise ValueError(
                f"handoff {key} must remain "
                f"{expected!r}"
            )

    semantics = handoff.get(
        "reanalysis_semantics"
    )

    if not isinstance(
        semantics,
        dict,
    ):
        raise ValueError(
            "reanalysis semantics unavailable"
        )

    instruction = handoff.get(
        "instruction_for_gpt"
    )

    if (
        not isinstance(instruction, str)
        or not instruction.strip()
    ):
        raise ValueError(
            "instruction_for_gpt unavailable"
        )

    wake_raw = handoff.get("wake")

    if not isinstance(wake_raw, dict):
        raise ValueError(
            "handoff wake unavailable"
        )

    payload: dict[str, Any] = {
        "schema_version": (
            BRIDGE_PAYLOAD_SCHEMA_VERSION
        ),
        "privacy_contract_version": (
            BRIDGE_PRIVACY_CONTRACT_VERSION
        ),
        "state": (
            "BRIDGE_PAYLOAD_READY_LOCAL_ONLY"
        ),
        "event": {
            "event_id": handoff.get(
                "event_id"
            ),
            "semantic_wake_key": (
                handoff.get(
                    "semantic_wake_key"
                )
            ),
            "handoff_hash": handoff.get(
                "handoff_hash"
            ),
            "source_evidence_pack_hash": (
                pack_hash
            ),
            "source_notice_hash": (
                handoff.get(
                    "source_notice_hash"
                )
            ),
            "wake": {
                "state": wake_raw.get(
                    "state"
                ),
                "reason": wake_raw.get(
                    "reason"
                ),
                "wake_sources": deepcopy(
                    wake_raw.get(
                        "wake_sources",
                        [],
                    )
                ),
                "wake_reasons": deepcopy(
                    wake_raw.get(
                        "wake_reasons",
                        [],
                    )
                ),
            },
            "plan_drift": (
                _bridge_plan_drift(
                    handoff
                )
            ),
        },
        "market_context": (
            _bridge_market_context(
                pack
            )
        ),
        "capital_state": (
            _bridge_capital_state(
                pack.get(
                    "private_context"
                )
            )
        ),
        "analysis_contract": {
            "instruction_for_gpt": (
                instruction
            ),
            "reanalysis_semantics": (
                deepcopy(semantics)
            ),
            "source_required_inputs": (
                deepcopy(
                    handoff.get(
                        "required_inputs",
                        [],
                    )
                )
            ),
            "required_behavior": (
                deepcopy(
                    handoff.get(
                        "required_behavior",
                        [],
                    )
                )
            ),
            "season_three_army_role_separation": (
                _season_three_army_analysis_contract(
                    pack,
                    pack_hash=pack_hash,
                )
            ),
        },
        "privacy": {
            "mode": (
                "MINIMIZED_ALLOWLIST_ONLY"
            ),
            "user_authorization_scope": (
                "ANALYSIS_AND_NOTIFICATION_ONLY"
            ),
            "raw_private_context_included": (
                False
            ),
            "full_private_profile_included": (
                False
            ),
            "filesystem_paths_included": (
                False
            ),
            "broker_or_account_identifiers_included": (
                False
            ),
            "credentials_or_secrets_included": (
                False
            ),
            "transport_selected": False,
        },
        "authority": {
            "production": "NOT_APPROVED",
            "trading_authority": "NONE",
            "capital_decision_authority": (
                "USER_ONLY"
            ),
            "machine_may_execute_trade": False,
            "external_action_authority": (
                "NONE"
            ),
            "external_action_performed": (
                False
            ),
            "transport_authority": "NONE",
            "transport_performed": False,
            "action_output": "NONE",
        },
    }

    _assert_bridge_privacy(payload)
    _bound_bridge_detail(payload, pack)

    payload[
        "bridge_payload_hash"
    ] = _canonical_hash(payload)

    _assert_bridge_privacy(payload)

    if ("treasury_valuation_context" in payload["market_context"] and
            len(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")) >= 16 * 1024):
        raise ValueError("Treasury bridge exceeds the unchanged 16 KiB ceiling")
    return payload


def _bound_bridge_detail(payload: dict[str, Any], pack: dict[str, Any]) -> None:
    """Project oversized research detail, never mutate evidence or an outbox.

    Keep capital, analysis semantics, formal locks, current metric values/times/
    quality and every layer's missing inputs. Omitted research detail is explicitly
    distinguished from absent evidence and bound to the original market hash.
    The provider's independent 16 KiB validation remains the final fail-closed gate.
    """
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode("utf-8")
    # Reserve the final bridge_payload_hash field before computing that hash.
    if len(serialized) + 90 <= 16 * 1024:
        return
    market = payload["market_context"]
    original_hash = _canonical_hash(market)
    for layer in market.get("layers", {}).values():
        if not isinstance(layer, dict):
            raise ValueError("Bridge layer must be an object")
        layer.pop("required_metrics", None)
        for name, row in layer.get("metrics", {}).items():
            layer["metrics"][name] = {
                key: deepcopy(row[key]) for key in ("value", "quality_state", "as_of_ms")
                if key in row
            }
    market["changes"] = {}
    for key in ("top_changes", "note"):
        market.get("distillation", {}).pop(key, None)
    # Source pack + market hash bind the omitted repeated per-metric provenance.
    scoring = market.get("model_status", {}).get("locked_formal_scoring", {})
    for key in ("candidate_contract_hash", "candidate_output_hash"):
        scoring.pop(key, None)
    diagnostic = market.get("transition_diagnostic")
    if isinstance(diagnostic, dict):
        diagnostic.pop("gpt_handoff", None)
        diagnostic.pop("wake", None)
        diagnostic.pop("mechanism_findings", None)
        diagnostic.get("data_health", {}).pop("provenance", None)
        if "windows" in diagnostic:
            diagnostic["windows"] = {
                key: value for key, value in diagnostic["windows"].items()
                if key in {"impulse_window", "prior_60m", "recent_60m"}
            }
    bull = market.get("btc_bull_validation")
    if isinstance(bull, dict):
        market["btc_bull_validation"] = {
            key: value for key, value in bull.items() if key in {
                "state", "reason", "scope", "authority", "blocked_checks",
                "pending_checks", "mixed_checks", "adverse_checks", "supportive_checks",
                "machine_may_confirm_bull_transition", "control_transfer_loop_closed",
            }
        }
    # Preserve DVOL detail when it is the trigger, otherwise include its status.
    wake = pack.get("reanalysis_wake", {})
    dvol = market.get("dvol_regime_watch")
    if isinstance(dvol, dict) and "DVOL" not in str(wake.get("wake_sources", [])):
        market["dvol_regime_watch"] = {
            key: value for key, value in dvol.items() if key in {
                "state", "reason", "scope", "current_dvol", "as_of_ms", "direction",
                "formal_model_authority", "season_transition_authority",
            }
        }
    market["wake_observation"] = {
        key: deepcopy(wake[key]) for key in (
            "current_value", "previous_value", "percent_change", "historical_percentile",
            "baseline_count", "metric", "input_family",
        ) if key in wake
    }
    market["minimization"] = {
        "source_market_context_hash": original_hash,
        "omitted_detail": (
            "Omitted: metric provenance/required lists, history/rankings, scoring hashes, "
            "non-trigger DVOL detail, transition 30m/prompts/machine hypotheses, bull values. "
            "Omitted is not absent; do not infer. See source evidence."
        ),
    }
    if len(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")) + 90 >= 16 * 1024:
        _compact_supporting_context(market, payload["authority"])
    if "treasury_valuation_context" in market:
        _compact_treasury_bridge(payload)


def _compact_treasury_bridge(payload: dict[str, Any]) -> None:
    """Lossless column projection plus explicit inheritance of repeated facts."""
    market = payload["market_context"]
    treasury = market["treasury_valuation_context"]
    # A shared column definition avoids repeating long claim names per issuer.
    # Every value, status, reason and hash survives the projection unchanged.
    schemas: list[list[str]] = []
    def encode(value: Any) -> Any:
        if isinstance(value, dict):
            keys = sorted(value)
            if keys not in schemas:
                schemas.append(keys)
            return {"record": [schemas.index(keys), *[encode(value[k]) for k in keys]]}
        if isinstance(value, list):
            return [encode(v) for v in value]
        return value
    encoded = {asset: encode(row) for asset, row in treasury.items()}
    candidate = {"encoding": "record=[schema_index,values_in_column_order]; arrays otherwise literal",
                 "columns": schemas, "assets": encoded}
    values = list(treasury.values())
    common = {k: v for k, v in values[0].items()
              if all(k in row and row[k] == v for row in values[1:])}
    inherited = {
        "encoding": "Each asset inherits common, then its own fields; null claims are BLOCKED; changes are fractions; CDF is 0..100.",
        "common": common,
        "assets": {asset: {k: v for k, v in row.items() if k not in common}
                   for asset, row in treasury.items()},
    }
    shared_blockers = sorted(set.intersection(*(set(row.get("blockers", [])) for row in values)))
    if shared_blockers and "blockers" not in common:
        inherited["common"]["blockers"] = shared_blockers
        for row in inherited["assets"].values():
            row["additional_blockers"] = [b for b in row.pop("blockers", []) if b not in shared_blockers]
        inherited["encoding"] += " Append additional_blockers to common.blockers."
    if len(json.dumps(inherited)) < len(json.dumps(candidate)):
        candidate = inherited
    if len(json.dumps(candidate)) < len(json.dumps(treasury)):
        market["treasury_valuation_context"] = candidate
    # Same-as references remove only proven equal data, not supporting claims.
    delta = market.get("asset_strategy_delta", {})
    income = delta.get("income_engine")
    for row in delta.get("assets", {}).values():
        if income is not None and row.get("quantitative") == income:
            row["quantitative"] = {"same_as": "market_context.asset_strategy_delta.income_engine"}
    def inherit(value: Any) -> None:
        if isinstance(value, dict):
            for child in list(value.values()):
                inherit(child)
            shared = {k for k, v in payload["authority"].items() if k in value and value[k] == v}
            if sum(len(k) + len(json.dumps(value[k])) + 4 for k in shared) > 70:
                for k in shared:
                    del value[k]
                value["authority_same_as"] = "authority"
        elif isinstance(value, list):
            for child in value:
                inherit(child)
    for key in ("asset_strategy_delta", "model_status", "btc_bull_validation", "btc_entry_gate", "dvol_regime_watch"):
        inherit(market.get(key))
    role = payload["analysis_contract"].get("season_three_army_role_separation", {})
    # Version/hash retain the doctrine binding; its long filename and source
    # section labels duplicate the surrounding named contract/market sections.
    role.pop("doctrine_artifact", None)
    for child in role.values():
        if isinstance(child, dict):
            child.pop("source_section", None)
            child.pop("source_sections", None)
    delta.pop("schema_version", None)
    market["minimization"]["omitted_detail"] = (
        "Local hashes bind omitted provenance, histories/baselines, prior windows, supporting explanations, "
        "schema/doctrine labels and duplicate displays. Omitted is not absent."
    )
    if role.get("source_evidence_pack_hash") == payload["event"].get("source_evidence_pack_hash"):
        role["source_evidence_pack_hash"] = {"same_as": "event.source_evidence_pack_hash"}
    inherit(role)
    # Repeated plan conditions and blockers may be shared across assets/tranches.
    # Replace exact equal structures only; an explicit reference is reversible.
    seen: dict[str, str] = {}
    def share(value: Any, location: str) -> Any:
        if isinstance(value, (dict, list)):
            literal = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            previous = seen.get(literal)
            reference = {"same_as": previous}
            if previous and len(literal) > len(json.dumps(reference)):
                return reference
            seen[literal] = location
            if isinstance(value, dict):
                return {k: share(v, location + "." + k) for k, v in value.items()}
            return [share(v, location + f"[{i}]") for i, v in enumerate(value)]
        return value
    for section in ("capital_state", "market_context", "analysis_contract"):
        payload[section] = share(payload[section], section)
    # Intern repeated long literal strings, with an explicit dictionary readable
    # by GPT. Values remain exact, including blocker codes and semantic labels.
    from collections import Counter
    counts: Counter[str] = Counter()
    def count(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                count(child)
        elif isinstance(value, list):
            for child in value:
                count(child)
        elif isinstance(value, str):
            counts[value] += 1
    count(payload["market_context"])
    strings = sorted(s for s, n in counts.items() if (len(s.encode("utf-8")) - 18) * (n - 1) > 30)
    if strings:
        indexes = {s: i for i, s in enumerate(strings)}
        def intern(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: intern(v) for k, v in value.items()}
            if isinstance(value, list):
                return [intern(v) for v in value]
            if isinstance(value, str) and value in indexes:
                return {"text_ref": indexes[value]}
            return value
        payload["market_context"] = intern(payload["market_context"])
        payload["market_context"]["literal_strings"] = strings
        payload["market_context"]["literal_encoding"] = "text_ref indexes literal_strings (exact text)."
    key_counts: Counter[str] = Counter()
    def count_keys(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_counts[key] += 1
                count_keys(child)
        elif isinstance(value, list):
            for child in value:
                count_keys(child)
    count_keys(payload["market_context"])
    keys = sorted(k for k, n in key_counts.items() if (len(k) - 5) * (n - 1) > 20)
    if keys:
        aliases = {k: f"@{i}" for i, k in enumerate(keys)}
        def alias(value: Any) -> Any:
            if isinstance(value, dict):
                return {aliases.get(k, k): alias(v) for k, v in value.items()}
            if isinstance(value, list):
                return [alias(v) for v in value]
            return value
        payload["market_context"] = alias(payload["market_context"])
        payload["market_context"]["field_names"] = keys
        payload["market_context"]["field_encoding"] = "Keys @N mean field_names[N]; same_as paths use expanded keys."


def _compact_supporting_context(market: dict[str, Any], authority: dict[str, Any]) -> None:
    """Second-stage projection; current facts stay explicit, detail stays hash-bound."""
    for section in ("transition_diagnostic", "btc_entry_gate",
                    "btc_bull_validation", "dvol_regime_watch"):
        if isinstance(market.get(section), dict):
            market[section].pop("schema_version", None)
    overlay = market.get("season_transition_warning_overlay")
    if isinstance(overlay, dict):
        # The overlay repeats layer inputs, model explanations and display cards.
        # Keep formal status, blockers, veto evidence and authority locks.
        summary = {key: deepcopy(overlay[key]) for key in (
            "authority", "inherited_locks", "formal_season", "formal_season_status",
        ) if key in overlay}
        summary["source_overlay_hash"] = overlay.get("overlay_hash")
        overlay_authority = summary.get("authority", {})
        summary["authority"] = {
            "same_as": "authority",
            **{key: value for key, value in overlay_authority.items()
               if key not in authority or authority[key] != value},
        }
        summary["light_evidence_status"] = {
            name: row.get("evidence_status")
            for name, row in overlay.get("lights", {}).items()
        }
        gate = overlay.get("gate_core_veto", {})
        summary["gate_reasons"] = {
            name: row["reason"]
            for name, row in gate.items() if isinstance(row, dict)
            and "reason" in row
        }
        summary["veto"] = gate.get("veto", {})
        summary.get("inherited_locks", {}).pop("light_buckets", None)
        summary["conflict_evidence"] = overlay.get("lights", {}).get(
            "conflict_veto", {}).get("raw_metrics", {})
        market["season_transition_warning_overlay"] = summary

    # Column names explicitly define every value; no precision loss or truncation.
    # Missing fields remain distinguishable from explicit nulls by field presence.
    columns = ["value", "as_of_ms", "quality_state"]
    metadata: list[list[Any]] = []
    for layer_name in sorted(market.get("layers", {})):
        layer = market["layers"][layer_name]
        for name, row in sorted(layer.get("metrics", {}).items()):
            if set(row) == set(columns):
                pair = [row["as_of_ms"], row["quality_state"]]
                if pair not in metadata:
                    metadata.append(pair)
                layer["metrics"][name] = [row["value"], metadata.index(pair)]
    market["metric_metadata"] = metadata

    diagnostic = market.get("transition_diagnostic")
    if isinstance(diagnostic, dict):
        diagnostic.get("windows", {}).pop("prior_60m", None)
        diagnostic.get("data_health", {}).pop("limitations", None)
        diagnostic.pop("source_mode", None)
    dvol = market.get("dvol_regime_watch")
    if isinstance(dvol, dict):
        # Even when DVOL is the trigger, retain every observation, baseline,
        # timestamp, state/reason and authority. Only supporting descriptions go.
        dvol.pop("provenance", None)
        dvol.pop("research_parameters", None)
    health = market.get("data_health", {})
    distillation = market.get("distillation", {})
    if ("data_quality_conflicts" in distillation and
            distillation["data_quality_conflicts"] == health.get("critical_blockers")):
        distillation["data_quality_conflicts"] = {"same_as": "market_context.data_health.critical_blockers"}
        if (set(distillation) <= {"data_quality_conflicts", "divergences", "formal_extremes"}
                and not distillation.get("divergences") and not distillation.get("formal_extremes")):
            market.pop("distillation", None)
    six_layer = market.get("model_status", {}).get("six_layer_evidence", {})
    missing = {name: layer["missing_required_metrics"]
               for name, layer in market.get("layers", {}).items()
               if layer.get("missing_required_metrics")}
    if "missing_by_layer" in six_layer and six_layer["missing_by_layer"] == missing:
        six_layer["missing_by_layer"] = {"same_as": "layers.*.missing_required_metrics"}
    market["minimization"]["omitted_detail"] = (
        "Omitted is not absent: provenance/lists/history/hashes, non-trigger DVOL detail, "
        "diagnostic explanations/prior windows, bull values, overlay support/schema labels, "
        "DVOL research parameters, duplicate distillation."
    )
    market["metric_encoding"] = (
        "Arrays=[value,metadata_index]; metric_metadata=[as_of_ms,quality_state]; objects=literal; same_as=inherit reference then literal fields."
    )


def _assert_optional_authority(
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    expected = {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }

    for key, expected_value in expected.items():
        if (
            key in payload
            and payload.get(key) != expected_value
        ):
            raise ValueError(
                f"{label} {key} must remain {expected_value!r}"
            )


def _violated_condition_signatures(
    plan_drift: dict[str, Any],
) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []

    for plan in plan_drift.get("plans", []):
        if not isinstance(plan, dict):
            continue

        plan_id = plan.get("plan_id")

        for condition in plan.get("conditions", []):
            if not isinstance(condition, dict):
                continue

            if condition.get("evaluation") != "VIOLATED":
                continue

            signatures.append(
                {
                    "plan_id": plan_id,
                    "tranche_id": condition.get("tranche_id"),
                    "field": condition.get("field"),
                    "operator": condition.get("operator"),
                    "target_value": condition.get(
                        "target_value"
                    ),
                    "source_kind": condition.get(
                        "source_kind"
                    ),
                    "source_path": condition.get(
                        "source_path"
                    ),
                }
            )

    return sorted(
        signatures,
        key=lambda row: json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _semantic_descriptor(
    pack: dict[str, Any],
) -> dict[str, Any]:
    wake = pack.get("reanalysis_wake")
    plan_drift = pack.get("plan_drift")

    if not isinstance(wake, dict):
        raise ValueError(
            "Evidence Pack reanalysis_wake must be an object"
        )

    if not isinstance(plan_drift, dict):
        raise ValueError(
            "Evidence Pack plan_drift must be an object"
        )

    wake_sources = sorted(
        {
            str(value)
            for value in wake.get("wake_sources", [])
        }
    )

    wake_reasons = sorted(
        {
            str(value)
            for value in wake.get("wake_reasons", [])
        }
    )

    if (
        wake.get("state") == "REANALYSIS_REQUESTED"
        and not wake_reasons
    ):
        wake_reasons = [
            str(
                wake.get(
                    "reason",
                    "REANALYSIS_REQUESTED",
                )
            )
        ]

    return {
        "wake_state": wake.get("state"),
        "wake_reason": wake.get("reason"),
        "wake_sources": wake_sources,
        "wake_reasons": wake_reasons,
        "plan_drift_state": plan_drift.get("state"),
        "plan_drift_reanalysis_required": (
            plan_drift.get("reanalysis_required")
        ),
        "violated_conditions": (
            _violated_condition_signatures(
                plan_drift
            )
        ),
    }


def semantic_wake_key(
    pack: dict[str, Any],
) -> str:
    return _canonical_hash(
        _semantic_descriptor(pack)
    )


def _last_gate_record(
    ledger: RunLedger,
) -> dict[str, Any] | None:
    for row in reversed(ledger.records()):
        if row.get("record_type") in {
            HANDOFF_RECORD_TYPE,
            RESET_RECORD_TYPE,
        }:
            return row

    return None


def _base_result(
    *,
    state: str,
    append_status: str,
    event_id: str | None,
    semantic_key: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "append_status": append_status,
        "event_id": event_id,
        "semantic_wake_key": semantic_key,
        **_authority(),
    }


def run_gpt_handoff_gate(
    pack: dict[str, Any],
    notice: dict[str, Any],
    *,
    ledger_path: str | Path,
    bridge_outbox_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not isinstance(pack, dict):
        raise ValueError(
            "Evidence Pack must be an object"
        )

    if not isinstance(notice, dict):
        raise ValueError(
            "notice must be an object"
        )

    authority = pack.get("authority")

    if not isinstance(authority, dict):
        raise ValueError(
            "Evidence Pack authority must be an object"
        )

    _assert_optional_authority(
        authority,
        label="Evidence Pack authority",
    )
    _assert_optional_authority(
        notice,
        label="notice",
    )

    pack_hash = pack.get("evidence_pack_hash")
    notice_pack_hash = notice.get(
        "source_evidence_pack_hash"
    )

    if (
        not isinstance(pack_hash, str)
        or not pack_hash
    ):
        raise ValueError(
            "Evidence Pack hash is unavailable"
        )

    if notice_pack_hash != pack_hash:
        raise ValueError(
            "notice is not linked to current Evidence Pack"
        )

    wake = pack.get("reanalysis_wake")

    if not isinstance(wake, dict):
        raise ValueError(
            "Evidence Pack reanalysis_wake must be an object"
        )

    _assert_optional_authority(
        wake,
        label="reanalysis_wake",
    )

    wake_requested = (
        wake.get("state")
        == "REANALYSIS_REQUESTED"
    )

    notice_requested = (
        notice.get("state")
        == "GPT_REANALYSIS_REQUESTED"
    )

    if wake_requested != notice_requested:
        raise ValueError(
            "wake and notice reanalysis states disagree"
        )

    ledger_file = Path(ledger_path)

    if not wake_requested:
        if not ledger_file.exists():
            return _base_result(
                state="NO_HANDOFF",
                append_status="NOOP",
                event_id=None,
                semantic_key=None,
            )

        ledger = RunLedger(ledger_file)
        validation = ledger.validate()

        if not validation.valid:
            raise ValueError(
                "GPT handoff ledger is invalid: "
                + "; ".join(validation.errors)
            )

        last = _last_gate_record(ledger)

        if (
            last is None
            or last.get("record_type")
            == RESET_RECORD_TYPE
        ):
            return _base_result(
                state="NO_HANDOFF",
                append_status="NOOP",
                event_id=None,
                semantic_key=None,
            )

        payload = last.get("payload", {})

        reset = ledger.append(
            RESET_RECORD_TYPE,
            {
                "schema_version": SCHEMA_VERSION,
                "reason": "WAKE_CLEARED",
                "prior_event_id": payload.get(
                    "event_id"
                ),
                "prior_semantic_wake_key": (
                    payload.get(
                        "semantic_wake_key"
                    )
                ),
                "source_evidence_pack_hash": (
                    pack_hash
                ),
                "source_notice_hash": notice.get(
                    "notice_hash"
                ),
                **_authority(),
            },
        )

        result = _base_result(
            state="NO_HANDOFF",
            append_status="RESET_APPENDED",
            event_id=None,
            semantic_key=None,
        )
        result["reset_record_hash"] = reset[
            "record_hash"
        ]
        return result

    descriptor = _semantic_descriptor(pack)
    semantic_key = _canonical_hash(descriptor)

    ledger = RunLedger(ledger_file)
    validation = ledger.validate()

    if not validation.valid:
        raise ValueError(
            "GPT handoff ledger is invalid: "
            + "; ".join(validation.errors)
        )

    last = _last_gate_record(ledger)

    if (
        last is not None
        and last.get("record_type")
        == HANDOFF_RECORD_TYPE
    ):
        previous_payload = last.get(
            "payload",
            {},
        )

        if (
            previous_payload.get(
                "semantic_wake_key"
            )
            == semantic_key
        ):
            result = _base_result(
                state="DUPLICATE_SKIPPED",
                append_status="DUPLICATE_SKIPPED",
                event_id=previous_payload.get(
                    "event_id"
                ),
                semantic_key=semantic_key,
            )
            result[
                "existing_record_hash"
            ] = last.get("record_hash")
            result[
                "source_evidence_pack_hash"
            ] = pack_hash
            result[
                "source_notice_hash"
            ] = notice.get("notice_hash")
            return result

    episode_anchor = (
        last.get("record_hash")
        if isinstance(last, dict)
        else GENESIS_HASH
    )

    event_id = _canonical_hash(
        {
            "semantic_wake_key": semantic_key,
            "episode_anchor": episode_anchor,
        }
    )

    plan_drift = pack["plan_drift"]

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": "GPT_HANDOFF_READY",
        "event_id": event_id,
        "semantic_wake_key": semantic_key,
        "semantic_descriptor": descriptor,
        "episode_anchor": episode_anchor,
        "source_evidence_pack_hash": pack_hash,
        "source_notice_hash": notice.get(
            "notice_hash"
        ),
        "wake": {
            "state": wake.get("state"),
            "reason": wake.get("reason"),
            "wake_sources": list(
                wake.get("wake_sources", [])
            ),
            "wake_reasons": list(
                wake.get("wake_reasons", [])
            ),
        },
        "plan_drift": {
            "state": plan_drift.get("state"),
            "reason": plan_drift.get("reason"),
            "reanalysis_required": (
                plan_drift.get(
                    "reanalysis_required"
                )
            ),
            "violated_conditions": (
                descriptor[
                    "violated_conditions"
                ]
            ),
        },
        "instruction_for_gpt": notice.get(
            "instruction_for_gpt"
        ),
        "reanalysis_semantics": (
            _reanalysis_semantics()
        ),
        "required_inputs": [
            "LATEST_EVIDENCE_PACK",
            "LATEST_CAPITAL_STATE",
            "LATEST_NOTICE",
            *(
                [
                    "LATEST_MSTR_ASST_MARKET_HEALTH",
                    "LATEST_THREE_ARMY_COMMANDER_LINES",
                ]
                if "mstr_asst_market_health" in pack
                else []
            ),
        ],
        "required_behavior": [
            "READ_CURRENT_EVIDENCE",
            "REANALYZE",
            "APPLY_THREE_ARMY_COMMANDER_DOCTRINE",
            "DECIDE_USER_NOTIFICATION_AFTER_REANALYSIS",
            "ADVISE_USER_ONLY",
            "NO_EXTERNAL_ACTION",
        ],
        **_authority(),
    }

    payload["handoff_hash"] = _canonical_hash(
        payload
    )

    outbox_result = None

    if bridge_outbox_dir is not None:
        bridge_payload = build_minimized_bridge_payload(
            pack,
            payload,
        )
        outbox_result = enqueue_bridge_payload(
            bridge_outbox_dir,
            bridge_payload,
        )

    record = ledger.append(
        HANDOFF_RECORD_TYPE,
        payload,
    )

    result = dict(payload)
    result["append_status"] = "APPENDED"
    result["ledger_record_hash"] = record[
        "record_hash"
    ]

    if outbox_result is not None:
        result["bridge_outbox"] = outbox_result

    return result
