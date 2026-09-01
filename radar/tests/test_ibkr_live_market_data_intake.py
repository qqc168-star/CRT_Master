from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from crt_radar.ibkr_live_market_data_intake import (
    ALLOWED_IBKR_REQUEST_METHODS,
    ASSET_ORDER,
    SOURCE_ID,
    IbkrIntakeConfig,
    IbkrIntakeError,
    build_ibkr_source_registry,
    build_ibkr_crt_outputs,
    build_ibkr_equity_live_snapshot,
    collect_ibkr_live_snapshot,
    inspect_ibkr_environment,
    load_ibkr_source_registry,
    _native_feed_app,
)
from crt_radar.premarket_equity_live_snapshot import build_equity_source_binding
from crt_radar.source_registry import SourceRegistry, canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "CONFIG" / "SOURCE_REGISTRY_V1.2.json"
CONTRACT_PATH = ROOT / "CONFIG" / "PREMARKET_BATTLE_MAP_CONTRACT_V0.1.json"
OVERLAY_PATH = ROOT / "CONFIG" / "IBKR_EQUITY_SOURCE_V0.1.json"


def _premarket_ms() -> int:
    return int(
        datetime(
            2026,
            8,
            28,
            8,
            15,
            tzinfo=ZoneInfo("America/New_York"),
        ).timestamp()
        * 1000
    )


def _capture(*, market_data_type: int = 1, trade_at_ms: int | None = None) -> dict:
    observed = _premarket_ms() if trade_at_ms is None else trade_at_ms
    assets = {}
    prices = {
        "MSTR": 125.0,
        "ASST": 21.5,
        "STRC": 94.0,
        "SATA": 84.0,
    }
    for asset, price in prices.items():
        assets[asset] = {
            "market_data_type": market_data_type,
            "l1": {
                "bid": price - 0.05,
                "ask": price + 0.05,
                "last": price,
                "close": price - 1.0,
                "volume": 10000.0,
            },
            "rt_volume": {
                "price": price,
                "size": 10.0,
                "trade_at_ms": observed,
                "total_volume": 10000.0,
                "vwap": price - 0.1,
                "single_trade": True,
                "received_at_ms": observed + 100,
            },
            "bars_5s": [
                {
                    "time_s": observed // 1000,
                    "open": price - 0.1,
                    "high": price + 0.1,
                    "low": price - 0.2,
                    "close": price,
                    "volume": 200.0,
                    "wap": price - 0.02,
                    "count": 4,
                    "received_at_ms": observed + 150,
                }
            ],
            "last_received_at_ms": observed + 150,
        }
    return {"captured_at_ms": observed + 500, "assets": assets}


class _FakeFeed:
    def __init__(self, capture: dict) -> None:
        self.capture = capture
        self.config = None

    def collect(self, config: IbkrIntakeConfig) -> dict:
        self.config = config
        return deepcopy(self.capture)


class _ProofSink:
    def __init__(self) -> None:
        self.observations = []

    def on_ibkr_last(
        self,
        asset,
        price,
        observed_at_ms,
        *,
        market_data_types=None,
    ) -> None:
        self.observations.append(
            ("LAST", asset, price, observed_at_ms, market_data_types)
        )

    def on_ibkr_5s_close(
        self,
        asset,
        close,
        observed_at_ms,
        *,
        market_data_types=None,
    ) -> None:
        self.observations.append(
            ("BAR_5S_CLOSE", asset, close, observed_at_ms, market_data_types)
        )


def _minimal_evidence_pack() -> dict:
    pack = {
        "schema_version": "CRT_EVIDENCE_PACK_V0.2",
        "action_output": "NONE",
        "authority": {
            "production": "NOT_APPROVED",
            "external_action_authority": "NONE",
            "external_action_performed": False,
            "analyst_judgment_required": True,
            "capital_decision_authority": "USER_ONLY",
        },
        "asset_facts": {
            "section_state": "READY",
            "coverage_state": "COMPLETE",
            "items": [],
            "empty_reason": "VERIFIED_NO_MATCH",
        },
        "decision_relevant_events": {
            "section_state": "READY",
            "coverage_state": "COMPLETE",
            "items": [],
            "empty_reason": "VERIFIED_NO_MATCH",
        },
        "blockers": {
            "section_state": "READY",
            "coverage_state": "COMPLETE",
            "items": [],
            "empty_reason": "VERIFIED_NO_MATCH",
        },
    }
    pack["evidence_pack_hash"] = hashlib.sha256(canonical_json_bytes(pack)).hexdigest()
    return pack


class IbkrLiveMarketDataIntakeTests(unittest.TestCase):
    def test_observation_sink_waits_for_four_asset_live_type_proof(self) -> None:
        sink = _ProofSink()
        MarketDataApp, _ = _native_feed_app(sink)
        app = MarketDataApp()
        for index, asset in enumerate(ASSET_ORDER):
            app.request_map[1000 + index] = (asset, "L1")

        app.tickPrice(1000, 4, 125.0, None)
        self.assertEqual(sink.observations, [])

        for index, _asset in enumerate(ASSET_ORDER):
            app.marketDataType(1000 + index, 1)
        app.tickPrice(1000, 4, 125.1, None)

        self.assertEqual(len(sink.observations), 1)
        self.assertEqual(sink.observations[0][0:3], ("LAST", "MSTR", 125.1))
        self.assertEqual(
            sink.observations[0][4],
            {asset: 1 for asset in ASSET_ORDER},
        )

    def setUp(self) -> None:
        self.registry = load_ibkr_source_registry(REGISTRY_PATH, OVERLAY_PATH)
        self.binding = build_equity_source_binding(self.registry, source_id=SOURCE_ID)
        self.config = IbkrIntakeConfig(duration_seconds=5.0)
        self.retrieved_at_ms = _premarket_ms() + 1000

    def test_current_registry_binds_ibkr_read_only_source(self):
        base = SourceRegistry.load(REGISTRY_PATH)
        with self.assertRaises(ValueError):
            base.get(SOURCE_ID)
        source = self.registry.get(SOURCE_ID)
        self.assertEqual(source.input_family, "EQUITY_PREMARKET_SNAPSHOT")
        self.assertEqual(source.raw["order_api_surface"], "ABSENT")
        self.assertEqual(source.raw["external_action_authority"], "NONE")
        self.assertEqual(source.raw["capital_decision_authority"], "USER_ONLY")
        self.assertFalse(source.raw["market_data_contract"]["regulatory_snapshot"])
        self.assertEqual(
            self.registry.payload["base_source_registry_hash"],
            base.hash,
        )

    def test_overlay_cannot_add_an_order_surface(self):
        base = SourceRegistry.load(REGISTRY_PATH)
        overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
        overlay["source"]["order_api_surface"] = "PRESENT"
        with self.assertRaises(ValueError):
            build_ibkr_source_registry(base, overlay)

    def test_preflight_reports_local_runtime_blockers(self):
        result = inspect_ibkr_environment(
            module_available=lambda name: name == "ibapi",
            port_probe=lambda host, port: host == "127.0.0.1" and port == 7497,
        )
        self.assertEqual(result["state"], "READY_FOR_OPERATOR_CONFIRMATION")
        self.assertEqual(result["listening_ports"], [7497])
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertEqual(result["capital_decision_authority"], "USER_ONLY")
        self.assertEqual(set(result["allowed_api_request_methods"]), ALLOWED_IBKR_REQUEST_METHODS)

    def test_capture_builds_hash_bound_l1_and_five_second_bar_snapshot(self):
        snapshot = build_ibkr_equity_live_snapshot(
            _capture(),
            source_binding=self.binding,
            config=self.config,
            retrieved_at_ms=self.retrieved_at_ms,
        )
        self.assertEqual(snapshot["assets"]["MSTR"]["premarket_price"], 125.0)
        self.assertEqual(
            snapshot["assets"]["MSTR"]["real_time_bars_5s"]["bar_size_seconds"],
            5,
        )
        self.assertFalse(snapshot["request_contract"]["l1"]["snapshot"])
        self.assertFalse(snapshot["request_contract"]["l1"]["regulatory_snapshot"])
        self.assertEqual(snapshot["external_action_authority"], "NONE")
        self.assertEqual(snapshot["capital_decision_authority"], "USER_ONLY")

    def test_fake_feed_runs_full_snapshot_validation(self):
        feed = _FakeFeed(_capture())
        snapshot = collect_ibkr_live_snapshot(
            self.registry,
            config=self.config,
            feed=feed,
            retrieved_at_ms=self.retrieved_at_ms,
        )
        self.assertEqual(snapshot["provider"], "Interactive Brokers TWS API")
        self.assertEqual(feed.config, self.config)

    def test_delayed_or_frozen_market_data_fails_closed(self):
        for data_type in (2, 3, 4):
            with self.subTest(data_type=data_type), self.assertRaises(IbkrIntakeError):
                build_ibkr_equity_live_snapshot(
                    _capture(market_data_type=data_type),
                    source_binding=self.binding,
                    config=self.config,
                    retrieved_at_ms=self.retrieved_at_ms,
                )

    def test_regular_hours_trade_is_not_relabelled_premarket(self):
        regular_hours = int(
            datetime(
                2026,
                8,
                28,
                10,
                15,
                tzinfo=ZoneInfo("America/New_York"),
            ).timestamp()
            * 1000
        )
        with self.assertRaises(IbkrIntakeError):
            build_ibkr_equity_live_snapshot(
                _capture(trade_at_ms=regular_hours),
                source_binding=self.binding,
                config=self.config,
                retrieved_at_ms=regular_hours + 1000,
            )

    def test_snapshot_flows_to_handoff_battle_map_and_evidence_pack(self):
        snapshot = collect_ibkr_live_snapshot(
            self.registry,
            config=self.config,
            feed=_FakeFeed(_capture()),
            retrieved_at_ms=self.retrieved_at_ms,
        )
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        outputs = build_ibkr_crt_outputs(
            snapshot,
            registry=self.registry,
            battle_map_contract=contract,
            evidence_pack=_minimal_evidence_pack(),
            as_of="2026-08-28T20:15:01+08:00",
        )
        self.assertEqual(
            outputs["live_market_handoff"]["asset_market"]["MSTR"]["premarket_price"]["value"],
            125.0,
        )
        self.assertEqual(outputs["battle_map"]["first_screen"][0]["premarket_price"], 125.0)
        attached = outputs["evidence_pack"]["premarket_market_data"]
        self.assertEqual(attached["external_action_authority"], "NONE")
        self.assertEqual(attached["capital_decision_authority"], "USER_ONLY")
        for row in attached["battle_map"]["first_screen"]:
            self.assertIsNone(row["light"])
            self.assertIsNone(row["entry_shares_delta"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
