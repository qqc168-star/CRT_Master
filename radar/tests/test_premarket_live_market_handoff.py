from __future__ import annotations

import json
import unittest
from pathlib import Path

from crt_radar.premarket_battle_map import (
    build_premarket_battle_map,
)
from crt_radar.premarket_equity_live_snapshot import (
    seal_equity_live_snapshot,
)
from crt_radar.premarket_live_market_handoff import (
    apply_live_market_handoff_to_asset_facts,
    build_premarket_live_market_handoff,
    validate_premarket_live_market_handoff,
)
from crt_radar.source_registry import SourceRegistry


ROOT = Path(__file__).resolve().parents[1]

CONTRACT = json.loads(
    (
        ROOT
        / "CONFIG"
        / "PREMARKET_BATTLE_MAP_CONTRACT_V0.1.json"
    ).read_text(encoding="utf-8")
)


def _source_gate():
    parsed = {
        "BTC_SPOT_PRICE": {
            "as_of_ms": 150,
            "spot_price_usd": 80000.0,
        },
        "PRICE_STRUCTURE_CONTEXT": {
            "as_of_ms": 150,
            "quote_volume_rvol20": 1.2,
            "taker_buy_quote_share_1d": 0.54,
        },
        "OPEN_INTEREST": {
            "as_of_ms": 150,
            "open_interest_contracts": 1000.0,
        },
        "OPEN_INTEREST_NOTIONAL": {
            "as_of_ms": 150,
            "open_interest_notional_usd": 1000000.0,
        },
        "FUNDING_RATE": {
            "as_of_ms": 150,
            "funding_rate": 0.0001,
        },
        "LIQUIDATION_AGGREGATES": {
            "as_of_ms": 150,
            "windows": {
                "24h": {
                    "total_liquidation_usd": 100.0,
                }
            },
        },
        "DOLLAR_STRENGTH_PROXY": {
            "as_of_ms": 150,
            "value": 120.0,
        },
        "RATES_CONTEXT": {
            "as_of_ms": 150,
            "real_10y_yield_20d_change_bp": 5.0,
        },
        "CREDIT_LIQUIDITY_CONTEXT": {
            "as_of_ms": 150,
            "stablecoin_supply_30d_log_change": 2.0,
            "spot_btc_etp_flow_state": (
                "COLLECTING_OFFICIAL_ISSUER_HISTORY"
            ),
        },
    }

    return {
        "formal_state": "OBSERVATION_ONLY",
        "blocked_reasons": [],
        "source_registry_hash": "registry-hash",
        "parsed": parsed,
        "evidence": [],
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def _observations(observed_at_ms=150):
    prices = {
        "MSTR": 125.0,
        "ASST": 21.5,
        "STRC": 94.0,
        "SATA": 84.0,
    }

    result = {}

    for asset, price in prices.items():
        result[asset] = {
            "session": "PREMARKET",
            "observed_at_ms": observed_at_ms,
            "premarket_price": price,
            "previous_close": price - 1.0,
            "premarket_high": price + 1.0,
            "premarket_low": price - 1.0,
            "premarket_volume": 10000,
            "source_ref": {
                "source_id": f"PUBLIC-{asset}",
                "source_type": "PUBLIC_MARKET_SUPPLEMENT",
                "retrieved_at_ms": observed_at_ms,
            },
        }

    return result


def _machine_equity_registry():
    raw = {
        "source_id": "CRT-CONN-EQUITY-PREMARKET-SYNTH-001",
        "namespace": "AS-L6",
        "input_family": "EQUITY_PREMARKET_SNAPSHOT",
        "role": "Synthetic machine equity fixture",
        "provider": "Synthetic Provider",
        "transport": "LOCAL_VERIFIED_JSON_SNAPSHOT",
        "endpoint": "runtime/equity/premarket/latest.json",
        "parser_id": "CRT_EQUITY_PREMARKET_SNAPSHOT_V1",
        "criticality": "NONCRITICAL_DISCLOSE_MISSING",
        "max_age_seconds": 120,
        "authentication": "LOCAL_READ_ONLY",
        "implementation_state": "LIVE_READ_ONLY_COLLECTOR",
        "provider_binding_state": "BOUND",
        "provider_contract_id": "SYNTH-EQUITY-CONTRACT-V1",
        "documentation": "https://example.test/equity-docs",
    }

    payload = json.loads(
        (
            ROOT
            / "CONFIG"
            / "SOURCE_REGISTRY_V1.2.json"
        ).read_text(encoding="utf-8")
    )

    payload["sources"].append(raw)

    return SourceRegistry(payload)


def _machine_equity_snapshot():
    prices = {
        "MSTR": 125.0,
        "ASST": 21.5,
        "STRC": 94.0,
        "SATA": 84.0,
    }

    assets = {}

    for asset, price in prices.items():
        assets[asset] = {
            "symbol": asset,
            "premarket_price": price,
            "previous_close": price - 1.0,
            "premarket_high": price + 1.0,
            "premarket_low": price - 1.0,
            "premarket_volume": 10000,
        }

    return seal_equity_live_snapshot(
        {
            "schema_version": (
                "CRT_PREMARKET_EQUITY_LIVE_SNAPSHOT_V0.1"
            ),
            "source_id": (
                "CRT-CONN-EQUITY-PREMARKET-SYNTH-001"
            ),
            "provider": "Synthetic Provider",
            "provider_contract_id": (
                "SYNTH-EQUITY-CONTRACT-V1"
            ),
            "session": "PREMARKET",
            "observed_at_ms": 150,
            "retrieved_at_ms": 160,
            "first_seen_at_ms": 160,
            "request_identity_hash": "a" * 64,
            "raw_response_hash": "b" * 64,
            "assets": assets,
            "action_output": "NONE",
            "external_action_authority": "NONE",
            "external_action_performed": False,
        }
    )


class PremarketLiveMarketHandoffTests(
    unittest.TestCase
):
    def test_manual_quotes_fuse_into_asset_facts(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MANUAL_WEB_SUPPLEMENT",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
            manual_asset_observations=_observations(),
        )

        fused = apply_live_market_handoff_to_asset_facts(
            {},
            handoff,
        )

        self.assertEqual(
            fused["MSTR"]["premarket_price"]["value"],
            125.0,
        )
        self.assertEqual(
            fused["ASST"]["premarket_price"]["value"],
            21.5,
        )
        self.assertEqual(
            handoff["action_output"],
            "NONE",
        )
        self.assertEqual(
            handoff["capital_decision_authority"],
            "USER_ONLY",
        )

    def test_manual_supplement_never_replaces_existing_available_price(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MANUAL_WEB_SUPPLEMENT",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
            manual_asset_observations=_observations(),
        )

        existing = {
            "MSTR": {
                "premarket_price": {
                    "state": "AVAILABLE",
                    "value": 999.0,
                    "unit": "USD",
                    "source_refs": [
                        {
                            "source_id": "UPSTREAM-VERIFIED",
                        }
                    ],
                }
            }
        }

        fused = apply_live_market_handoff_to_asset_facts(
            existing,
            handoff,
        )

        self.assertEqual(
            fused["MSTR"]["premarket_price"]["value"],
            999.0,
        )
        self.assertEqual(
            fused["MSTR"]["premarket_price"][
                "source_refs"
            ][0]["source_id"],
            "UPSTREAM-VERIFIED",
        )

    def test_bound_machine_snapshot_unlocks_equity_prices(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MACHINE_VERIFIED_ONLY",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
            machine_equity_snapshot=(
                _machine_equity_snapshot()
            ),
            machine_equity_source_registry=(
                _machine_equity_registry()
            ),
            machine_equity_source_id=(
                "CRT-CONN-EQUITY-PREMARKET-SYNTH-001"
            ),
        )

        self.assertEqual(
            handoff["asset_market"]["MSTR"][
                "premarket_price"
            ]["value"],
            125.0,
        )

        self.assertEqual(
            handoff["asset_market"]["ASST"][
                "premarket_price"
            ]["value"],
            21.5,
        )

        self.assertEqual(
            handoff["state"],
            "READY_FOR_ANALYST",
        )

        self.assertEqual(
            handoff["machine_equity_source_binding"][
                "binding_state"
            ],
            "BOUND",
        )

        self.assertEqual(
            handoff["action_output"],
            "NONE",
        )

    def test_current_registry_cannot_unlock_unregistered_equity_source(self):
        current_registry = SourceRegistry.load(
            ROOT
            / "CONFIG"
            / "SOURCE_REGISTRY_V1.2.json"
        )

        with self.assertRaises(ValueError):
            build_premarket_live_market_handoff(
                source_mode="MACHINE_VERIFIED_ONLY",
                evaluation_window={
                    "start_ms": 100,
                    "end_ms": 200,
                },
                source_gate_result=_source_gate(),
                machine_equity_snapshot=(
                    _machine_equity_snapshot()
                ),
                machine_equity_source_registry=(
                    current_registry
                ),
                machine_equity_source_id=(
                    "CRT-CONN-EQUITY-PREMARKET-SYNTH-001"
                ),
            )

    def test_machine_snapshot_without_bound_source_is_rejected(self):
        with self.assertRaises(ValueError):
            build_premarket_live_market_handoff(
                source_mode="MACHINE_VERIFIED_ONLY",
                evaluation_window={
                    "start_ms": 100,
                    "end_ms": 200,
                },
                source_gate_result=_source_gate(),
                machine_equity_snapshot=(
                    _machine_equity_snapshot()
                ),
            )

    def test_machine_mode_rejects_injected_available_equity_price(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MACHINE_VERIFIED_ONLY",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
        )

        handoff["asset_market"]["MSTR"][
            "premarket_price"
        ] = {
            "state": "AVAILABLE",
            "value": 125.0,
            "unit": "USD",
        }

        with self.assertRaises(ValueError):
            validate_premarket_live_market_handoff(
                handoff
            )

    def test_injected_machine_judgment_is_rejected(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MANUAL_WEB_SUPPLEMENT",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
            manual_asset_observations=_observations(),
        )

        handoff["analysis_inputs"][
            "SPOT_VS_DERIVATIVES"
        ]["machine_judgment"] = "BUY"

        with self.assertRaises(ValueError):
            validate_premarket_live_market_handoff(
                handoff
            )

    def test_outside_window_quote_fails_closed(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MANUAL_WEB_SUPPLEMENT",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
            manual_asset_observations=_observations(
                observed_at_ms=99
            ),
        )

        self.assertEqual(
            handoff["asset_market"]["MSTR"][
                "premarket_price"
            ]["state"],
            "BLOCKED",
        )
        self.assertEqual(
            handoff["asset_market"]["MSTR"][
                "premarket_price"
            ]["reason"],
            "MARKET_OBSERVATION_OUTSIDE_EVALUATION_WINDOW",
        )

    def test_machine_mode_rejects_manual_equity_data(self):
        with self.assertRaises(ValueError):
            build_premarket_live_market_handoff(
                source_mode="MACHINE_VERIFIED_ONLY",
                evaluation_window={
                    "start_ms": 100,
                    "end_ms": 200,
                },
                source_gate_result=_source_gate(),
                manual_asset_observations=_observations(),
            )

    def test_source_gate_authority_violation_is_rejected(self):
        source_gate = _source_gate()
        source_gate["external_action_authority"] = (
            "TRADE"
        )

        with self.assertRaises(ValueError):
            build_premarket_live_market_handoff(
                source_mode="MANUAL_WEB_SUPPLEMENT",
                evaluation_window={
                    "start_ms": 100,
                    "end_ms": 200,
                },
                source_gate_result=source_gate,
                manual_asset_observations=_observations(),
            )

    def test_existing_btc_macro_and_derivatives_are_routed(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MANUAL_WEB_SUPPLEMENT",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
            manual_asset_observations=_observations(),
        )

        derivatives = handoff["analysis_inputs"][
            "SPOT_VS_DERIVATIVES"
        ]

        self.assertEqual(
            derivatives["state"],
            "AVAILABLE",
        )
        self.assertIn(
            "FUNDING_RATE",
            derivatives["available_source_families"],
        )
        self.assertIn(
            "LIQUIDATION_AGGREGATES",
            derivatives["available_source_families"],
        )

        bull_bear = handoff["analysis_inputs"][
            "BULL_BEAR_FORCE_DISTRIBUTION"
        ]

        self.assertEqual(
            bull_bear["state"],
            "PARTIAL",
        )
        self.assertIn(
            "EQUITY_OPTIONS_SHORT_GAMMA_NOT_BOUND",
            bull_bear["missing_inputs"],
        )

    def test_battle_map_receives_live_evidence_without_judgment(self):
        handoff = build_premarket_live_market_handoff(
            source_mode="MANUAL_WEB_SUPPLEMENT",
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
            source_gate_result=_source_gate(),
            manual_asset_observations=_observations(),
        )

        facts = apply_live_market_handoff_to_asset_facts(
            {},
            handoff,
        )

        battle_map = build_premarket_battle_map(
            contract=CONTRACT,
            asset_facts=facts,
            issuer_reflexivity={
                "state": "VALID",
                "event_state": (
                    "NO_NEW_MATERIAL_ISSUER_EVENT"
                ),
            },
            as_of="2026-08-27T20:30:00+08:00",
            source_mode="MANUAL_WEB_SUPPLEMENT",
            live_market_handoff=handoff,
        )

        self.assertEqual(
            battle_map["first_screen"][0][
                "premarket_price"
            ],
            125.0,
        )

        sections = {
            row["id"]: row
            for row in battle_map["analysis_sections"]
        }

        self.assertEqual(
            sections["SPOT_VS_DERIVATIVES"]["state"],
            "READY_FOR_ANALYST",
        )

        self.assertIsNotNone(
            sections["SPOT_VS_DERIVATIVES"][
                "machine_evidence"
            ]
        )

        for row in battle_map["first_screen"]:
            self.assertIsNone(row["light"])

            self.assertEqual(
                row["entry_condition"],
                {
                    "asset_price_clause": None,
                    "btc_price_clause": None,
                    "confirmation_clause": None,
                },
            )

            self.assertIsNone(
                row["entry_shares_delta"]
            )

            self.assertEqual(
                row["exit_condition"],
                {
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
            )

            self.assertIsNone(
                row["exit_shares_delta"]
            )

        self.assertEqual(
            battle_map["action_output"],
            "NONE",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
