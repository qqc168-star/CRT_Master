from __future__ import annotations

import hashlib
import json
import math
import re
import string
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from .gpt_bridge_outbox import enqueue_bridge_payload
from .issuer_announcement_runner import (
    compact_issuer_announcement_wake,
    validate_issuer_announcement_wake,
)
from .mstr_asst_market_health import (
    validate_issuer_ratio_observation, compact_issuer_ratio_observation,
)
from .run_ledger import GENESIS_HASH, RunLedger
from .btc_etf_intake import compact_for_bridge as compact_btc_etf_evidence
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

BRIDGE_OPERATIONAL_BUDGET_BYTES = 15 * 1024
BRIDGE_CEILING_BYTES = 16 * 1024


BRIDGE_OPTIONAL_MARKET_SECTIONS = (
    "btc_long_horizon_context",
    "dvol_regime_watch",
    "transition_diagnostic",
    "btc_entry_gate",
    "btc_bull_validation",
    "season_transition_warning_overlay",
    "mstr_asst_market_health",
    "issuer_announcement_wake",
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

            if key == "issuer_announcement_wake":
                if pack[key].get("state") != "REANALYSIS_REQUESTED":
                    continue
                result[key] = compact_issuer_announcement_wake(
                    pack[key],
                    generated_at_ms=pack.get("generated_at_ms"),
                )
            else:
                result[key] = deepcopy(
                    pack[key]
                )
                if key == "asset_strategy_delta":
                    income = result[key].get("income_engine")
                    if isinstance(income, dict) and "legacy_strc_derived" in income:
                        # Project older immutable packs without their historical
                        # private estimates. Verify first; never repair corruption.
                        if income.get("summary_hash") != _canonical_hash({
                            k: v for k, v in income.items() if k != "summary_hash"
                        }):
                            raise ValueError("INCOME_SUMMARY_HASH_INVALID")
                        income.pop("legacy_strc_derived")
                        income["legacy_policy_state"] = "HISTORICAL_USER_PROFILE_INPUTS_EXCLUDED"
                        income["summary_hash"] = _canonical_hash({
                            k: v for k, v in income.items() if k != "summary_hash"
                        })

    btc_etf = compact_btc_etf_evidence(pack)
    if btc_etf:
        result["btc_etf_evidence"] = btc_etf
    treasury = compact_treasury_valuation_context(pack)
    if treasury:
        result["treasury_valuation_context"] = treasury
    portfolio = compact_portfolio_allocation_context_for_bridge(pack)
    if portfolio:
        result.update(portfolio)
    if "qualified_equity_daily_source" in pack:
        result["qualified_equity_prices"] = _bridge_qualified_equity_prices(pack)
    return result


def _bridge_qualified_equity_prices(pack: dict[str, Any]) -> dict[str, Any]:
    """Carry existing qualified RTH closes independently of full Market Health.

    The full source proof belongs to the sealed Evidence Pack, not transport.
    This is a completed-session price observation, never a live/premarket quote.
    """
    from .mstr_asst_market_health_runtime import _validated_source
    from .mstr_asst_full_day_market_intake import build_mstr_asst_full_day_market_intake

    proof = pack["qualified_equity_daily_source"]
    generated = pack["generated_at_ms"]
    from .ibkr_market_health_sources import FOUR_DAILY_SCHEMA, validate_four_asset_daily_proof
    if isinstance(proof, dict) and proof.get("schema_version") == FOUR_DAILY_SCHEMA:
        if pack.get("evidence_pack_hash") != _canonical_hash(
                {key: value for key, value in pack.items() if key != "evidence_pack_hash"}):
            raise ValueError("Qualified equity Evidence Pack hash mismatch")
        qualified = validate_four_asset_daily_proof(proof, at_ms=generated)
        if ("qualified_equity_prices" in pack
                and pack["qualified_equity_prices"] != qualified):
            raise ValueError("Qualified equity prices do not match retained source proof")
        return qualified
    if (type(generated) is not int or generated <= 0
            or not isinstance(proof, dict)
            or type(proof.get("observed_at_ms")) is not int
            or proof["observed_at_ms"] <= 0):
        raise ValueError("Qualified equity source requires positive integer clocks")
    bars = _validated_source("equity_daily", proof, generated_at_ms=generated)
    intake = build_mstr_asst_full_day_market_intake(
        equity_bars=bars, btc_close_marks=[], generated_at_ms=proof["observed_at_ms"])
    assets = {}
    for asset, row in sorted(intake["assets"].items()):
        if row["state"] != "VALID":
            assets[asset] = {"state": row["state"], "reason": row["reason"]}
            continue
        session = row["latest_complete_session"]
        if (session["source_state"] != "IBKR_HISTORICAL_TRADES_RTH"
                or not math.isfinite(session["close"]) or session["close"] <= 0):
            raise ValueError("Qualified equity price requires a finite positive IBKR RTH close")
        assets[asset] = {"state": row["state"], "price_usd": session["close"],
            "as_of_ms": session["session_close_ms"], "session_date": session["session_date"],
            "session_state": session["session_state"], "source_state": session["source_state"]}
    return {"state": intake["state"], "scope": "LAST_COMPLETED_RTH_CLOSE_NOT_LIVE_QUOTE",
        "source_id": proof["source_id"], "source_hash": proof["data_hash"],
        "observed_at_ms": proof["observed_at_ms"], "assets": assets}


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
    *, generated_at_ms: int | None = None,
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

    if "capital_reconciliation" in profile:
        from .broker_capital_observation import BLOCKED_BROKER_REASONS, bridge_capital_surface, reconcile_capital
        supplied = profile["capital_reconciliation"]
        if generated_at_ms is None:
            raise ValueError("current broker capital requires an evaluation clock")
        checked = reconcile_capital(supplied.get("broker_observed"), supplied.get("user_confirmed"),
                                    at_ms=generated_at_ms)
        if (supplied.get("broker_observed") is None and supplied.get("state") == "BLOCKED"
                and supplied.get("reason") in BLOCKED_BROKER_REASONS):
            checked["reason"] = supplied["reason"]
        if _canonical_hash(checked) != _canonical_hash(supplied):
            raise ValueError("current broker capital reconciliation changed")
        return bridge_capital_surface(checked, historical_snapshot=profile.get("historical_capital_snapshot", {}))

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

        holding = {"asset": row.get("asset"), "quantity": row.get("quantity")}
        for key in ("cost_basis_usd", "cost_basis", "cost_basis_per_share"):
            if key in row:
                holding[key] = deepcopy(row[key])
        holdings.append(holding)

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

    result = {
        "capital_state": capital_state,
        "holdings": holdings,
        "cash": cash,
        "asset_roles": asset_roles,
        "active_plans": plans,
        "execution_authority": "USER_ONLY",
    }
    # Carry supplied assessments, never infer freshness or refresh private capital.
    for key in ("snapshot_state", "STALE_CAPITAL_FIELDS", "stale_flags"):
        supplied = [source[key] for source in (profile, meta, status) if key in source]
        if supplied:
            if any(_canonical_hash(value) != _canonical_hash(supplied[0]) for value in supplied[1:]):
                raise ValueError(f"Conflicting Capital State {key}")
            result[key] = deepcopy(supplied[0])
    return result


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
    *,
    full_decision: bool = False,
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

    handoff_scope = handoff.get("semantic_descriptor", {}).get("delivery_scope")
    if full_decision and handoff_scope != "FULL_DECISION_OFFLINE":
        raise ValueError("Full-decision bridge requires its own current handoff; old events cannot be rebound")
    if not full_decision and handoff_scope == "FULL_DECISION_OFFLINE":
        raise ValueError("Full-decision handoff cannot be used as a Smoke bridge")

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
                ), generated_at_ms=pack.get("generated_at_ms"),
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

    if "issuer_ratio_observation" in pack:
        # Independent allowlisted section stays literal during market-detail compaction.
        payload["issuer_ratio_observation"] = compact_issuer_ratio_observation(
            pack["issuer_ratio_observation"], generated_at_ms=pack["generated_at_ms"],
        )
    if full_decision:
        payload["analysis_contract"]["delivery_scope"] = "FULL_DECISION_OFFLINE"
    _assert_bridge_privacy(payload)
    if full_decision:
        # Share literal equal observations only. Full-decision evidence never
        # inherits Smoke's capacity-triggered audit/history omissions.
        _compact_premarket_refs(payload)
    else:
        _bound_bridge_detail(payload, pack)

    payload[
        "bridge_payload_hash"
    ] = _canonical_hash(payload)

    _assert_bridge_privacy(expand_bridge_field_names(payload))

    if not full_decision and _bridge_size(payload) >= BRIDGE_CEILING_BYTES:
        raise ValueError("Decision-critical bridge exceeds the unchanged 16 KiB ceiling")
    return payload


def build_full_decision_bridge_payload(
    pack: dict[str, Any], handoff: dict[str, Any],
) -> dict[str, Any]:
    """Reuse the local bridge projection under the distinct offline contract.

    The Smoke request ceiling is not a full-decision evidence limit. This
    wrapper grants no provider delivery or production authority.
    """
    return build_minimized_bridge_payload(pack, handoff, full_decision=True)


def _bridge_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))



def _compact_premarket_refs(payload: dict[str, Any]) -> None:
    """Share exact duplicates, preserving all independent analysis."""
    market = payload.get("market_context", {})
    pre = market.get("premarket_market_data")
    if not isinstance(pre, dict):
        return

    handoff = pre.get("live_market_handoff")
    battle = pre.get("battle_map")
    if not isinstance(handoff, dict) or not isinstance(battle, dict):
        return

    assets = handoff.get("asset_market")
    inputs = handoff.get("analysis_inputs")
    sections = battle.get("analysis_sections")
    if not isinstance(assets, dict) or not isinstance(inputs, dict):
        return
    if not isinstance(sections, list):
        return

    original = deepcopy(pre)
    candidate = deepcopy(pre)
    h = candidate["live_market_handoff"]
    b = candidate["battle_map"]
    changed = False

    # Full handoff repeated inside Commander map.
    if _canonical_hash(b.get("live_market_handoff")) == _canonical_hash(h):
        b["live_market_handoff"] = {
            "bridge_same_as": "premarket.live_market_handoff"
        }
        changed = True

    # Commander sections repeat the analysis inputs.
    for row in b["analysis_sections"]:
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        if isinstance(sid, str) and sid in h["analysis_inputs"] and (
            _canonical_hash(row.get("machine_evidence")) == _canonical_hash(h["analysis_inputs"][sid])
        ):
            row["machine_evidence"] = {
                "bridge_same_as": "premarket.analysis_inputs." + sid
            }
            changed = True

    # Each analysis input repeats all four asset snapshots.
    for row in h["analysis_inputs"].values():
        if isinstance(row, dict) and (
            _canonical_hash(row.get("asset_market_observations")) == _canonical_hash(h["asset_market"])
        ):
            row["asset_market_observations"] = {
                "bridge_same_as": "premarket.asset_market"
            }
            changed = True


    # Only share whole source-family observations that match the
    # canonical parsed source, including clocks and provenance.
    gate = h.get("source_gate_context")
    parsed = gate.get("parsed") if isinstance(gate, dict) else None
    if isinstance(parsed, dict):
        for row in h["analysis_inputs"].values():
            if not isinstance(row, dict):
                continue
            families = row.get("available_source_families")
            if not isinstance(families, dict) or not families:
                continue
            if not all(
                isinstance(key, str)
                and key in parsed
                and _canonical_hash(parsed[key]) == _canonical_hash(value)
                for key, value in families.items()
            ):
                continue
            ref = {"bridge_source_families": sorted(families)}
            if _bridge_size(ref) < _bridge_size(families):
                row["available_source_families"] = ref
                changed = True

    if not changed:
        return

    probe = {
        "market_context": {
            "premarket_market_data": deepcopy(candidate)
        }
    }
    _restore_premarket_refs(probe)

    if _canonical_hash(
        probe["market_context"]["premarket_market_data"]
    ) != _canonical_hash(original):
        raise ValueError("Premarket roundtrip mismatch")

    if _bridge_size(candidate) >= _bridge_size(original):
        return

    market["premarket_market_data"] = candidate
    market["premarket_ref_encoding"] = (
        "bridge_source_families inherits named items from " "live_market_handoff.source_gate_context.parsed; " "bridge_same_as refers to fields under "
        "market_context.premarket_market_data; "
        "expand references before interpretation."
    )


def _restore_premarket_refs(payload: dict[str, Any]) -> None:
    """Expand only exact, declared reference paths."""
    pre = payload.get("market_context", {}).get(
        "premarket_market_data"
    )
    if not isinstance(pre, dict):
        return

    handoff = pre.get("live_market_handoff")
    battle = pre.get("battle_map")
    if not isinstance(handoff, dict) or not isinstance(battle, dict):
        return

    assets = handoff.get("asset_market")
    inputs = handoff.get("analysis_inputs")
    if not isinstance(assets, dict) or not isinstance(inputs, dict):
        return


    # Restore source families before restoring whole sections and
    # Commander handoff copies.
    gate = handoff.get("source_gate_context")
    parsed = gate.get("parsed") if isinstance(gate, dict) else None
    for row in inputs.values():
        if not isinstance(row, dict):
            continue
        ref = row.get("available_source_families")
        if not isinstance(ref, dict):
            continue
        if "bridge_source_families" not in ref:
            continue
        if set(ref) != {"bridge_source_families"}:
            raise ValueError("Invalid source reference")
        names = ref["bridge_source_families"]
        if (
            not isinstance(names, list)
            or not names
            or any(not isinstance(k, str) for k in names)
            or names != sorted(set(names))
            or not isinstance(parsed, dict)
            or any(k not in parsed for k in names)
        ):
            raise ValueError("Unresolvable source reference")
        row["available_source_families"] = {
            k: deepcopy(parsed[k]) for k in names
        }

    def restore(row, field, expected, source):
        if not isinstance(row, dict):
            return
        value = row.get(field)
        if not isinstance(value, dict) or "bridge_same_as" not in value:
            return
        if value != {"bridge_same_as": expected}:
            raise ValueError("Invalid premarket reference")
        row[field] = deepcopy(source)

    for row in inputs.values():
        restore(
            row, "asset_market_observations",
            "premarket.asset_market", assets
        )

    for row in battle.get("analysis_sections", []):
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        if isinstance(sid, str) and sid in inputs:
            restore(
                row, "machine_evidence",
                "premarket.analysis_inputs." + sid,
                inputs[sid]
            )

    restore(
        battle, "live_market_handoff",
        "premarket.live_market_handoff", handoff
    )


def _compact_tranche_fields(payload: dict[str, Any]) -> None:
    """Share exact-equal tranche fields; budgets/statuses stay literal in common."""
    for plan in payload.get("capital_state", {}).get("active_plans", []):
        tranches = plan.get("tranches", [])
        if len(tranches) < 2:
            continue
        common = {key: deepcopy(tranches[0][key]) for key in (
            "budget_usd", "status", "validity_conditions") if key in tranches[0]
            and all(key in row and _canonical_hash(row[key]) == _canonical_hash(tranches[0][key]) for row in tranches)}
        candidate = {**plan, "tranche_common": common,
            "tranche_encoding": "Each tranche inherits tranche_common then its literal fields.",
            "tranches": [{key: deepcopy(value) for key, value in row.items() if key not in common}
                         for row in tranches]}
        if common and _bridge_size(candidate) < _bridge_size(plan):
            if _canonical_hash(_expand_tranche_fields(deepcopy(candidate))) != _canonical_hash(plan):
                raise ValueError("Bridge tranche roundtrip mismatch")
            plan.clear()
            plan.update(candidate)


def _expand_tranche_fields(plan: dict[str, Any]) -> dict[str, Any]:
    common = plan.pop("tranche_common", None)
    if common is not None:
        plan.pop("tranche_encoding")
        plan["tranches"] = [{**deepcopy(common), **row} for row in plan["tranches"]]
    return plan


def _compact_field_names(payload: dict[str, Any]) -> None:
    """Reversible field-name glossary; every observation/lock value stays literal.

    This extends the existing bridge's field-name references. Top-level keys,
    event, authority and privacy remain directly readable by the outbox/worker.
    Choose tokens absent from ALL original keys, so expansion cannot collide.
    """
    sections = ("market_context", "analysis_contract", "capital_state", "issuer_ratio_observation")
    keys: Counter[str] = Counter()

    def count(value: Any) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                keys[name] += 1
                count(child)
        elif isinstance(value, list):
            for child in value:
                count(child)

    for section in sections:
        count(payload.get(section))
    current = keys.copy()
    keys.clear()
    count(payload)
    # A legal source key containing the delimiter stays unencoded, never lost.
    if any("|" in name for name in keys):
        return
    symbols = "".join(char for char in string.ascii_uppercase + string.digits + string.punctuation
                      if char not in '_"\\@' and all(char not in name for name in keys))
    alphabet = string.digits + string.ascii_uppercase + string.ascii_lowercase
    tokens = list(symbols)
    if all("@" not in name for name in keys):
        tokens += ["@" + char for char in alphabet]
    boundaries = re.compile("(?:@[" + alphabet + "]|[" + re.escape(symbols) + "])") if symbols else re.compile("@[0-9A-Za-z]")
    fragments: list[str] = []
    used_tokens: list[str] = []
    for token in tokens:
        candidates: Counter[str] = Counter()
        for name, frequency in current.items():
            for part in boundaries.split(name):
                unique = {part[start:stop] for start in range(len(part))
                          for stop in range(start + 3, len(part) + 1)}
                for fragment in unique:
                    candidates[fragment] += part.count(fragment) * frequency
        scored = [(frequency * (len(fragment.encode("utf-8")) - len(token))
                   - len(fragment.encode("utf-8")) - 1, fragment)
                  for fragment, frequency in candidates.items()]
        gain, fragment = max(scored, default=(0, ""))
        if gain <= 0:
            break
        fragments.append(fragment)
        used_tokens.append(token)
        rewritten: Counter[str] = Counter()
        for name, frequency in current.items():
            rewritten[name.replace(fragment, token)] += frequency
        current = rewritten
    if not fragments:
        return

    def encode(value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for name, child in sorted(value.items()):
                encoded = name
                for token, fragment in zip(used_tokens, fragments):
                    encoded = encoded.replace(fragment, token)
                if encoded in result:
                    raise ValueError("Bridge field-name collision")
                result[encoded] = encode(child)
            return result
        if isinstance(value, list):
            return [encode(child) for child in value]
        return value

    candidate = deepcopy(payload)
    for section in sections:
        if section in candidate:
            candidate[section] = encode(candidate[section])
    candidate["market_context"]["key_encoding"] = [symbols, "|".join(fragments),
        "Keys: chars index |-split fields then @0-9A-Za-z. Expand once; values literal."]
    if _canonical_hash(expand_bridge_field_names(candidate)) != _canonical_hash(expand_bridge_field_names(payload)):
        raise ValueError("Bridge field-name roundtrip mismatch")
    if _bridge_size(candidate) < _bridge_size(payload):
        payload.clear()
        payload.update(candidate)


def expand_bridge_field_names(payload: dict[str, Any]) -> dict[str, Any]:
    """Expand keys and exact tranche inheritance; literal values never change."""
    result = deepcopy(payload)
    codec = result.get("market_context", {}).pop("key_encoding", None)
    if codec is None:
        for plan in result.get("capital_state", {}).get("active_plans", []):
            _expand_tranche_fields(plan)
        _expand_authority_references(result)
        _restore_premarket_refs(result)
        return result
    symbols, glossary, _ = codec
    tokens = list(symbols) + ["@" + char for char in string.digits + string.ascii_uppercase + string.ascii_lowercase]
    mapping = dict(zip(tokens, glossary.split("|")))
    matcher = re.compile("|".join(re.escape(token) for token in sorted(mapping, key=lambda item: (-len(item), item))))

    def decode(value: Any) -> Any:
        if isinstance(value, dict):
            decoded = {}
            for name, child in value.items():
                expanded = matcher.sub(lambda match: mapping[match.group()], name)
                if expanded in decoded:
                    raise ValueError("Expanded bridge field collision")
                decoded[expanded] = decode(child)
            return decoded
        if isinstance(value, list):
            return [decode(child) for child in value]
        return value

    result = decode(result)
    for plan in result.get("capital_state", {}).get("active_plans", []):
        _expand_tranche_fields(plan)
    _expand_authority_references(result)
    _restore_premarket_refs(result)
    return result


def _expand_authority_references(payload: dict[str, Any]) -> None:
    authority = payload.get("authority", {})
    keys = sorted(authority)
    market = payload.get("market_context", {})
    pairs = market.pop("authority_field_values", [])
    market.pop("authority_field_encoding", None)

    def expand(value: Any) -> None:
        if isinstance(value, dict):
            mask = value.get("authority_same_as")
            if isinstance(mask, int) and not isinstance(mask, bool):
                if mask < 0 or mask >= 1 << len(keys):
                    raise ValueError("Invalid authority reference bits")
                value.pop("authority_same_as")
                for index, key in enumerate(keys):
                    if mask & (1 << index):
                        if key in value:
                            raise ValueError("Inherited authority field collision")
                        value[key] = deepcopy(authority[key])
            for index in (value.pop("authority_fields", []) if pairs else []):
                key, literal = pairs[index]
                if key in value:
                    raise ValueError("Shared authority field collision")
                value[key] = deepcopy(literal)
            for child in value.values():
                expand(child)
        elif isinstance(value, list):
            for child in value:
                expand(child)

    expand(payload)


def _inherit_equal_authority(value: Any, authority: dict[str, Any]) -> None:
    """Reference only exactly equal repeated fields; different locks stay literal."""
    if isinstance(value, dict):
        for key in sorted(value):
            _inherit_equal_authority(value[key], authority)
        shared = sorted(k for k in authority if k in value and _canonical_hash(value[k]) == _canonical_hash(authority[k]))
        if sum(_bridge_size({k: value[k]}) for k in shared) > 70:
            mask = sum(1 << index for index, key in enumerate(sorted(authority)) if key in shared)
            for key in shared:
                del value[key]
            value["authority_same_as"] = mask
    elif isinstance(value, list):
        for child in value:
            _inherit_equal_authority(child, authority)


def _share_authority_fields(market: dict[str, Any]) -> None:
    """Lossless exact field/value references; never inherit unspecified locks."""
    names = {"analyst_judgment_required", "formal_model", "production",
        "formal_model_authority", "formal_threshold_authority", "formal_weight_authority",
        "machine_may_confirm_bull_transition", "machine_may_output_trade_action",
        "score_may_determine_btc_season", "season_transition_authority", "formal_season_authority"}
    occurrences: dict[str, list[dict[str, Any]]] = {}
    pairs: dict[str, list[Any]] = {}
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                child = value[key]
                if key in names:
                    pair = [key, child]
                    token = json.dumps(pair, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    occurrences.setdefault(token, []).append(value)
                    pairs[token] = pair
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(market)
    columns = []
    for token in sorted(occurrences):
        rows = occurrences[token]
        key, value = pairs[token]
        if len(rows) >= 3 and (_bridge_size({key: value}) - 8) * len(rows) > _bridge_size(pairs[token]) + 40:
            index = len(columns)
            columns.append(pairs[token])
            for row in rows:
                del row[key]
                row.setdefault("authority_fields", []).append(index)
    if columns:
        market["authority_field_values"] = columns
        market["authority_field_encoding"] = "authority_fields indexes [field,literal_value]; inherit ONLY listed fields."


def _bound_bridge_detail(payload: dict[str, Any], pack: dict[str, Any]) -> None:
    """One bridge, fixed ceiling: omit audit detail, preserve decision semantics.

    15 KiB is operational headroom, not a new CRT formal lock. The final hash
    costs exactly 89 additional bytes. Critical inputs are never truncated.
    """
    source_market_hash = _canonical_hash(payload["market_context"])
    _compact_premarket_refs(payload)
    if _bridge_size(payload) + 89 <= BRIDGE_OPERATIONAL_BUDGET_BYTES:
        return
    market = payload["market_context"]
    original_hash = source_market_hash
    # These are non-trigger history/ranking displays; current layer facts and
    # the trigger's current/previous/change remain separately literal.
    changes = market.get("changes", {})
    market["changes"] = {"section_hash": _canonical_hash(changes),
        "detail": "OMITTED_FROM_BRIDGE_NOT_ABSENT_FROM_EVIDENCE"}
    for key in ("top_changes", "note"):
        market.get("distillation", {}).pop(key, None)
    scoring = market.get("model_status", {}).get("locked_formal_scoring", {})
    for key in ("candidate_contract_hash", "candidate_output_hash", "candidate_score",
                "candidate_threshold_bucket", "score"):
        scoring.pop(key, None)
    audit_metrics = {
        "core_inflation_acceleration", "real_policy_rate", "unemployment_deterioration",
        "market_cap_usd", "mvrv", "nupl", "realized_cap_30d_log_change", "realized_cap_usd",
        "close_minus_sma200_over_atr20", "return_20d_over_atr_vol", "sma50_minus_sma200_over_atr20",
        "mark_price", "open_interest_contracts",
    }
    trigger_metric = pack.get("reanalysis_wake", {}).get("metric")
    for layer in market.get("layers", {}).values():
        if not isinstance(layer, dict):
            raise ValueError("Bridge layer must be an object")
        layer.pop("required_metrics", None)
        for name, row in list(layer.get("metrics", {}).items()):
            # Only known non-trigger, fresh scoring support is audit-only.
            # Unknown/missing/stale/partial/blocked observations never disappear.
            if (name in audit_metrics and name != trigger_metric
                    and row.get("quality_state") == "VALID_FRESH" and row.get("value") is not None):
                del layer["metrics"][name]
                continue
            layer["metrics"][name] = {key: deepcopy(row[key]) for key in
                ("value", "quality_state", "as_of_ms") if key in row}
    diagnostic = market.get("transition_diagnostic")
    if isinstance(diagnostic, dict):
        for key in ("gpt_handoff", "wake", "mechanism_findings"):
            diagnostic.pop(key, None)
        diagnostic.get("data_health", {}).pop("provenance", None)
    bull = market.get("btc_bull_validation")
    if isinstance(bull, dict):
        # Category lists retain every blocked/pending check. Contradictions keep
        # their exact reason and current values; duplicate pending display goes.
        retained = {key: deepcopy(bull[key]) for key in (
            "generated_at_ms", "state", "reason", "scope", "authority", "blocked_checks",
            "pending_checks", "mixed_checks", "adverse_checks", "supportive_checks",
            "machine_may_confirm_bull_transition", "control_transfer_loop_closed") if key in bull}
        blocked = [row for row in bull.get("checks", []) if row.get("status") == "BLOCKED"]
        reasons = {row.get("reason") for row in blocked}
        if len(reasons) == 1:
            retained["blocked_check_reason"] = next(iter(reasons))
        elif reasons:
            retained["blocked_check_reasons"] = {row["check_id"]: row.get("reason") for row in blocked}
        retained["checks"] = [row for row in bull.get("checks", [])
            if row.get("status") in {"ADVERSE", "MIXED", "SUPPORTIVE"}]
        for row in retained["checks"]:
            value = row.get("value")
            if isinstance(value, dict):
                for key in ("baseline_meaning", "natural_research_baselines"):
                    value.pop(key, None)
        market["btc_bull_validation"] = retained
    dvol = market.get("dvol_regime_watch")
    if isinstance(dvol, dict):
        for key in ("provenance", "research_parameters", "schema_version",
                    "scale_normalization", "investment_threshold_authority"):
            dvol.pop(key, None)
        if "DVOL" not in str(pack.get("reanalysis_wake", {}).get("wake_sources", [])):
            for key in ("baseline_count", "dvol_30d_low", "dvol_30d_low_as_of_ms",
                        "hours_since_30d_low", "low_30d_percentile_1y",
                        "recommended_wake_operational_percentile"):
                dvol.pop(key, None)
    wake = pack.get("reanalysis_wake", {})
    market["wake_observation"] = {key: deepcopy(wake[key]) for key in (
        "current_value", "previous_value", "percent_change", "historical_percentile",
        "baseline_count", "metric", "input_family") if key in wake}
    market["minimization"] = {
        "source_market_context_hash": original_hash,
        "source_evidence_pack_hash": payload["event"]["source_evidence_pack_hash"],
        "provenance": "FULL_PROVENANCE_IN_EVIDENCE_PACK",
        "omitted_detail": "OMITTED_FROM_BRIDGE_NOT_ABSENT_FROM_EVIDENCE; Omitted is not absent.",
        "audit_only": "HISTORY_RANKINGS_NON_TRIGGER_SCORING_AND_TREASURY_BASELINE_CDF_BENCHMARK_COLUMNS",
    }
    if market["minimization"]["source_evidence_pack_hash"] == payload["event"]["source_evidence_pack_hash"]:
        market["minimization"]["source_evidence_pack_hash"] = {"same_as": "event.source_evidence_pack_hash"}
    if _bridge_size(payload) + 89 > BRIDGE_OPERATIONAL_BUDGET_BYTES:
        _compact_supporting_context(market, payload["authority"])
    role = (payload["analysis_contract"].get("season_three_army_role_separation", {})
            if "treasury_valuation_context" in market else {})
    role.pop("doctrine_artifact", None)
    for child in role.values():
        if isinstance(child, dict):
            child.pop("source_section", None)
            child.pop("source_sections", None)
    _inherit_equal_authority(role, payload["authority"])
    if role or "metric_encoding" in market:
        market["metric_encoding"] = market.get("metric_encoding", "") + " authority_same_as=bits(sorted authority keys)."
    if "treasury_valuation_context" in market:
        _compact_treasury_bridge(payload)
    if _bridge_size(payload) + 89 > BRIDGE_OPERATIONAL_BUDGET_BYTES:
        _share_authority_fields(market)
        _compact_tranche_fields(payload)
        _compact_field_names(payload)


def _compact_treasury_bridge(payload: dict[str, Any]) -> None:
    """Shared exact-equal context only; critical states/values are not interned."""
    market = payload["market_context"]
    treasury = market["treasury_valuation_context"]
    # Omit ONLY explicitly declared audit columns, bound to the original full
    # market hash. Current mNAV/BTC-share values, clocks, quality/action states,
    # context_hash and EVERY blocker remain literal. Direct helper calls without
    # this declaration are completely lossless, including historical columns.
    minimization = market.get("minimization", {})
    if (minimization.get("audit_only") == "HISTORY_RANKINGS_NON_TRIGGER_SCORING_AND_TREASURY_BASELINE_CDF_BENCHMARK_COLUMNS"
            and isinstance(minimization.get("source_market_context_hash"), str)):
        for row in treasury.values():
            for key in ("baseline_counts", "own_history_empirical_cdf_pct",
                        "regime_empirical_cdf_pct", "benchmark_empirical_cdf_pct", "benchmark_identity"):
                row.pop(key, None)
    assets = sorted(treasury)
    if not assets:
        return
    first = treasury[assets[0]]
    common = {k: deepcopy(first[k]) for k in sorted(first)
              if all(k in treasury[a] and _canonical_hash(treasury[a][k]) == _canonical_hash(first[k]) for a in assets)}
    inherited = {"encoding": "Each asset inherits common then its literal fields.",
        "common": common, "assets": {a: {k: v for k, v in sorted(treasury[a].items())
            if k not in common} for a in assets}}
    if _bridge_size(inherited) < _bridge_size(treasury):
        market["treasury_valuation_context"] = inherited


def _compact_supporting_context(market: dict[str, Any], authority: dict[str, Any]) -> None:
    """Only audited supporting displays go; states, contradictions and locks stay."""
    overlay = market.get("season_transition_warning_overlay")
    if isinstance(overlay, dict):
        summary = {key: deepcopy(overlay[key]) for key in (
            "generated_at_ms", "scope", "authority", "formal_season",
            "formal_season_status", "research_season", "transition_warning", "evidence_momentum")
            if key in overlay}
        summary["source_overlay_hash"] = overlay.get("overlay_hash")
        summary["lights"] = {name: {key: deepcopy(row[key]) for key in
            ("light", "evidence_status") if key in row}
            for name, row in sorted(overlay.get("lights", {}).items())}
        gate = overlay.get("gate_core_veto", {})
        summary["gate_core_veto"] = {name: {k: deepcopy(row[k]) for k in
            ("state", "reason") if k in row} for name, row in sorted(gate.items())
            if isinstance(row, dict)}
        summary["gate_core_veto"]["veto"] = deepcopy(gate.get("veto", {}))
        summary["conflict_evidence"] = deepcopy(overlay.get("lights", {}).get(
            "conflict_veto", {}).get("raw_metrics", {}))
        summary["inherited_locks"] = {k: deepcopy(v) for k, v in
            overlay.get("inherited_locks", {}).items() if k != "light_buckets"}
        market["season_transition_warning_overlay"] = summary
    metadata: list[list[Any]] = []
    for layer_name in sorted(market.get("layers", {})):
        layer = market["layers"][layer_name]
        for name, row in sorted(layer.get("metrics", {}).items()):
            if set(row) == {"value", "as_of_ms", "quality_state"}:
                pair = [row["as_of_ms"], row["quality_state"]]
                if pair not in metadata:
                    metadata.append(pair)
                layer["metrics"][name] = [row["value"], metadata.index(pair)]
    market["metric_metadata"] = metadata
    market["metric_encoding"] = "Arrays=[value,metadata_index]; metric_metadata=[as_of_ms,quality_state]; objects=literal."
    for key in BRIDGE_OPTIONAL_MARKET_SECTIONS:
        _inherit_equal_authority(market.get(key), authority)
    _inherit_equal_authority(market.get("model_status"), authority)
    for key in ("btc_entry_gate", "transition_diagnostic"):
        if isinstance(market.get(key), dict):
            market[key].pop("schema_version", None)
    # Literal issuer/capital/analysis/top-level authority/privacy are untouched.


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
    *, full_decision: bool = False,
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

    descriptor = {
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
    if full_decision:
        descriptor["delivery_scope"] = "FULL_DECISION_OFFLINE"
    capital_change = wake.get("capital_change")
    if isinstance(capital_change, dict) and capital_change.get("current_state_hash") is not None:
        descriptor["capital_state_hash"] = capital_change["current_state_hash"]

    if (
        "issuer_announcement_wake" in pack
        and "ISSUER_ANNOUNCEMENT" in wake_sources
    ):
        announcement = validate_issuer_announcement_wake(
            pack["issuer_announcement_wake"],
            generated_at_ms=pack.get("generated_at_ms"),
        )
        descriptor["issuer_announcement_events"] = [
            {
                key: event.get(key)
                for key in (
                    "event_id",
                    "event_hash",
                    "issuer_id",
                    "source_type",
                    "classification",
                    "form",
                    "items",
                    "filing_date",
                    "accepted_at",
                    "title",
                )
            }
            for event in announcement["new_events"]
        ]

    if "issuer_ratio_observation" in pack:
        observation = validate_issuer_ratio_observation(
            pack["issuer_ratio_observation"], generated_at_ms=pack["generated_at_ms"],
        )
        # Repeated retrievals of one reported pair do not create new episodes.
        # A new adjacent pair must not be swallowed by a prior decrease reason.
        descriptor["issuer_observation_pairs"] = {
            asset: {key: value for key, value in row.items() if key in {
                "previous_reported_date", "current_reported_date",
                "previous_effective_at_ms", "current_effective_at_ms",
                "previous_btc_holdings", "current_btc_holdings",
                "previous_diluted_shares", "current_diluted_shares",
                "time_semantic", "comparison_horizon",
            }} for asset, row in observation["observations"].items()
            if f"{asset}_ISSUER_RATIO_OBSERVATION" in wake_sources
        }
    return descriptor


def semantic_wake_key(
    pack: dict[str, Any],
    *, full_decision: bool = False,
) -> str:
    return _canonical_hash(
        _semantic_descriptor(pack, full_decision=full_decision)
    )


def _last_gate_record(
    ledger: RunLedger,
    *, full_decision: bool = False,
) -> dict[str, Any] | None:
    for row in reversed(ledger.records()):
        if row.get("record_type") in {
            HANDOFF_RECORD_TYPE,
            RESET_RECORD_TYPE,
        }:
            payload = row.get("payload", {})
            scope = payload.get("delivery_scope", payload.get("semantic_descriptor", {}).get("delivery_scope"))
            if scope == ("FULL_DECISION_OFFLINE" if full_decision else None):
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
    full_decision: bool = False,
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

        last = _last_gate_record(ledger, full_decision=full_decision)

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
                **({"delivery_scope": "FULL_DECISION_OFFLINE"} if full_decision else {}),
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

    descriptor = _semantic_descriptor(pack, full_decision=full_decision)
    semantic_key = _canonical_hash(descriptor)

    ledger = RunLedger(ledger_file)
    validation = ledger.validate()

    if not validation.valid:
        raise ValueError(
            "GPT handoff ledger is invalid: "
            + "; ".join(validation.errors)
        )

    last = _last_gate_record(ledger, full_decision=full_decision)

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
            *(["LATEST_ISSUER_RATIO_OBSERVATION"] if "issuer_ratio_observation" in pack else []),
            *(
                ["LATEST_ISSUER_ANNOUNCEMENT"]
                if "ISSUER_ANNOUNCEMENT" in descriptor["wake_sources"]
                else []
            ),
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
            *(
                ["DISTINGUISH_PROPOSED_APPROVED_EFFECTIVE_ISSUER_POLICY"]
                if "ISSUER_ANNOUNCEMENT" in descriptor["wake_sources"]
                else []
            ),
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
            full_decision=full_decision,
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
