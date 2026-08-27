from __future__ import annotations

import unittest

from crt_radar.premarket_equity_live_snapshot import (
    build_equity_source_binding,
    equity_snapshot_to_asset_market,
    seal_equity_live_snapshot,
    validate_equity_live_snapshot,
)
from crt_radar.source_registry import SourceSpec


def _spec(
    *,
    authentication: str = "LOCAL_READ_ONLY",
) -> SourceSpec:
    raw = {
        "source_id": "CRT-CONN-EQUITY-PREMARKET-SYNTH-001",
        "namespace": "AS-L6",
        "input_family": "EQUITY_PREMARKET_SNAPSHOT",
        "role": "Synthetic equity snapshot mechanics fixture",
        "provider": "Synthetic Provider",
        "transport": "LOCAL_VERIFIED_JSON_SNAPSHOT",
        "endpoint": "runtime/equity/premarket/latest.json",
        "parser_id": "CRT_EQUITY_PREMARKET_SNAPSHOT_V1",
        "criticality": "NONCRITICAL_DISCLOSE_MISSING",
        "max_age_seconds": 120,
        "authentication": authentication,
        "implementation_state": "LIVE_READ_ONLY_COLLECTOR",
        "provider_binding_state": "BOUND",
        "provider_contract_id": "SYNTH-EQUITY-CONTRACT-V1",
        "documentation": "https://example.test/equity-docs",
    }

    return SourceSpec(
        source_id=raw["source_id"],
        namespace=raw["namespace"],
        input_family=raw["input_family"],
        role=raw["role"],
        provider=raw["provider"],
        transport=raw["transport"],
        endpoint=raw["endpoint"],
        parser_id=raw["parser_id"],
        criticality=raw["criticality"],
        max_age_seconds=raw["max_age_seconds"],
        raw=raw,
    )


def _binding():
    return build_equity_source_binding(
        _spec(),
        source_registry_hash="1" * 64,
    )


def _payload():
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

    return {
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


class PremarketEquityLiveSnapshotTests(
    unittest.TestCase
):
    def test_valid_hash_bound_snapshot_builds_asset_market(self):
        snapshot = seal_equity_live_snapshot(
            _payload()
        )

        locked = validate_equity_live_snapshot(
            snapshot,
            source_binding=_binding(),
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
        )

        market = equity_snapshot_to_asset_market(
            locked,
            source_binding=_binding(),
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
        )

        self.assertEqual(
            market["MSTR"]["premarket_price"]["value"],
            125.0,
        )

        self.assertEqual(
            market["MSTR"]["premarket_price"][
                "source_refs"
            ][0]["source_type"],
            "MACHINE_VERIFIED_EQUITY_SNAPSHOT",
        )

    def test_snapshot_hash_tamper_is_rejected(self):
        snapshot = seal_equity_live_snapshot(
            _payload()
        )

        snapshot["assets"]["MSTR"][
            "premarket_price"
        ] = 999.0

        with self.assertRaises(ValueError):
            validate_equity_live_snapshot(
                snapshot,
                source_binding=_binding(),
                evaluation_window={
                    "start_ms": 100,
                    "end_ms": 200,
                },
            )

    def test_missing_required_asset_is_rejected(self):
        payload = _payload()
        payload["assets"].pop("SATA")

        snapshot = seal_equity_live_snapshot(
            payload
        )

        with self.assertRaises(ValueError):
            validate_equity_live_snapshot(
                snapshot,
                source_binding=_binding(),
                evaluation_window={
                    "start_ms": 100,
                    "end_ms": 200,
                },
            )

    def test_outside_window_snapshot_is_rejected(self):
        snapshot = seal_equity_live_snapshot(
            _payload()
        )

        with self.assertRaises(ValueError):
            validate_equity_live_snapshot(
                snapshot,
                source_binding=_binding(),
                evaluation_window={
                    "start_ms": 170,
                    "end_ms": 200,
                },
            )

    def test_unapproved_authentication_is_rejected(self):
        with self.assertRaises(ValueError):
            build_equity_source_binding(
                _spec(
                    authentication="API_KEY"
                ),
                source_registry_hash="1" * 64,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
