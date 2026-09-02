from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from crt_radar.mstr_asst_market_health_runtime import (
    AUTHORITY,
    SCHEMA_VERSION,
    build_market_health_runtime_outputs,
    build_runtime_input_from_source_proofs,
    seal_runtime_source,
    write_market_health_runtime_outputs,
)


NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def session_dates(count: int = 22) -> list[str]:
    current = date(2026, 7, 27)
    result: list[str] = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def close_ms(session_date: str) -> int:
    value = datetime.combine(
        date.fromisoformat(session_date),
        time(16, 0),
        tzinfo=NY,
    )
    return int(value.astimezone(UTC).timestamp() * 1000)


def equity_data() -> dict:
    result = {}
    for asset, offset in (("MSTR", 0.0), ("ASST", -90.0)):
        result[asset] = [
            {
                "session_date": session_date,
                "open": 100.0 + offset + index,
                "high": 102.0 + offset + index,
                "low": 99.0 + offset + index,
                "close": 101.0 + offset + index,
                "volume": 1000.0 + index * 10,
                "source_state": "VALID",
            }
            for index, session_date in enumerate(session_dates())
        ]
    return result


def option_asset(asset: str) -> dict:
    strike = 125.0 if asset == "MSTR" else 35.0
    return {
        "session_date": session_dates()[-1],
        "aggregate_volume": {
            "call_volume": 100,
            "put_volume": 60,
            "source_state": "VALID_LIMITED",
            "observed_at_ms": close_ms(session_dates()[-1]),
        },
        "contracts": [
            {
                "expiry": "2026-09-18",
                "strike": strike,
                "right": "CALL",
                "volume": 40,
                "open_interest": 500,
                "implied_volatility": 0.7,
                "volume_state": "VALID",
                "open_interest_state": "VALID",
                "implied_volatility_state": "VALID",
                "observed_at_ms": close_ms(session_dates()[-1]),
                "oi_effective_at": session_dates()[-1],
            },
            {
                "expiry": "2026-09-18",
                "strike": strike - 5,
                "right": "PUT",
                "volume": 20,
                "open_interest": 300,
                "implied_volatility": 0.8,
                "volume_state": "VALID",
                "open_interest_state": "VALID",
                "implied_volatility_state": "VALID",
                "observed_at_ms": close_ms(session_dates()[-1]),
                "oi_effective_at": session_dates()[-1],
            },
        ],
        "coverage": {
            "state": "LIMITED",
            "expiry_count": 1,
            "strike_min": strike - 5,
            "strike_max": strike,
        },
    }


def runtime_bundle() -> dict:
    generated_at_ms = close_ms(session_dates()[-1]) + 1
    data = {
        "equity_daily": equity_data(),
        "btc_exact_close": [
            {
                "observed_at_ms": close_ms(session_date),
                "price_usd": 70_000 + index * 100,
                "source_state": "VALID",
            }
            for index, session_date in enumerate(session_dates())
        ],
        "options_daily": {
            "MSTR": option_asset("MSTR"),
            "ASST": option_asset("ASST"),
        },
        "issuer_btc_per_diluted_share": {
            "MSTR": {
                "current_btc_per_diluted_share": 0.0018,
                "previous_btc_per_diluted_share": 0.0018,
            },
            "ASST": {
                "current_btc_per_diluted_share": 0.00024,
                "previous_btc_per_diluted_share": 0.00023,
            },
        },
        "commander_lines": {
            "MSTR": {
                "source": "THREE_ARMY_COMMANDER",
                "approval_state": "APPROVED",
                "attack_line": 130,
                "first_defense": 110,
                "invalidation_line": 100,
            },
            "ASST": {
                "source": "THREE_ARMY_COMMANDER",
                "approval_state": "APPROVED",
                "attack_line": 40,
                "first_defense": 20,
                "invalidation_line": 10,
            },
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": generated_at_ms,
        "source_proofs": {
            key: seal_runtime_source(
                source_key=key,
                data=value,
                observed_at_ms=generated_at_ms,
            )
            for key, value in data.items()
        },
        **AUTHORITY,
    }


class MarketHealthRuntimeTests(unittest.TestCase):

    def test_builds_runtime_input_from_five_proofs(self):
        original = runtime_bundle()
        rebuilt = build_runtime_input_from_source_proofs(
            original["source_proofs"],
            generated_at_ms=original["generated_at_ms"],
        )
        self.assertEqual(rebuilt["schema_version"], SCHEMA_VERSION)
        self.assertEqual(set(rebuilt["source_proofs"]), set(original["source_proofs"]))

    def test_builds_all_validated_outputs(self):
        outputs = build_market_health_runtime_outputs(runtime_bundle())
        self.assertEqual(outputs["full_day_market_intake"]["state"], "VALID")
        self.assertEqual(outputs["options_daily_snapshot"]["state"], "VALID")
        self.assertIn(outputs["market_health"]["state"], {"NO_WAKE", "REANALYSIS_REQUESTED"})
        self.assertEqual(outputs["manifest"]["external_action_authority"], "NONE")
        self.assertEqual(len(outputs["manifest"]["manifest_hash"]), 64)

    def test_missing_source_fails_closed(self):
        bundle = runtime_bundle()
        del bundle["source_proofs"]["btc_exact_close"]
        with self.assertRaisesRegex(ValueError, "exactly the five"):
            build_market_health_runtime_outputs(bundle)

    def test_tampered_source_hash_fails_closed(self):
        bundle = runtime_bundle()
        bundle["source_proofs"]["equity_daily"]["data"]["MSTR"][0]["close"] = 1
        with self.assertRaisesRegex(ValueError, "data_hash mismatch"):
            build_market_health_runtime_outputs(bundle)

    def test_authority_escalation_fails_closed(self):
        bundle = runtime_bundle()
        bundle["source_proofs"]["options_daily"]["external_action_authority"] = "TRADE"
        with self.assertRaisesRegex(ValueError, "must remain 'NONE'"):
            build_market_health_runtime_outputs(bundle)

    def test_unapproved_commander_lines_fail_closed(self):
        bundle = runtime_bundle()
        proof = bundle["source_proofs"]["commander_lines"]
        proof["data"]["MSTR"]["approval_state"] = "SIMULATION_ONLY"
        proof["data_hash"] = seal_runtime_source(
            source_key="commander_lines",
            data=proof["data"],
            observed_at_ms=bundle["generated_at_ms"],
        )["data_hash"]
        with self.assertRaisesRegex(ValueError, "must be APPROVED"):
            build_market_health_runtime_outputs(bundle)

    def test_invalid_build_writes_no_artifacts(self):
        bundle = runtime_bundle()
        bundle["source_proofs"]["issuer_btc_per_diluted_share"]["validation_state"] = "BLOCKED"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "must be VALID"):
                outputs = build_market_health_runtime_outputs(bundle)
                write_market_health_runtime_outputs(
                    outputs,
                    full_day_output=root / "full-day.json",
                    options_output=root / "options.json",
                    market_health_output=root / "latest.json",
                    manifest_output=root / "manifest.json",
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_writes_parseable_artifacts_with_atomic_writer(self):
        outputs = build_market_health_runtime_outputs(runtime_bundle())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                root / "full-day.json",
                root / "options.json",
                root / "latest.json",
                root / "manifest.json",
            ]
            write_market_health_runtime_outputs(
                outputs,
                full_day_output=paths[0],
                options_output=paths[1],
                market_health_output=paths[2],
                manifest_output=paths[3],
            )
            self.assertTrue(all(path.exists() for path in paths))
            self.assertEqual(json.loads(paths[2].read_text())["external_action_authority"], "NONE")
            self.assertEqual(list(root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
