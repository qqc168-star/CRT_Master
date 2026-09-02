from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from crt_radar.mstr_asst_full_day_market_intake import (
    build_mstr_asst_full_day_market_intake,
)


NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def sessions(count: int = 22) -> list[str]:
    current = date(2026, 7, 27)
    result: list[str] = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def close_ms(session_date: str, hour: int = 16) -> int:
    value = datetime.combine(
        date.fromisoformat(session_date),
        time(hour, 0),
        tzinfo=NY,
    )
    return int(value.astimezone(UTC).timestamp() * 1000)


def bars(asset: str, count: int = 22) -> list[dict]:
    offset = 0.0 if asset == "MSTR" else 50.0
    return [
        {
            "session_date": session_date,
            "open": 100.0 + offset + index,
            "high": 102.0 + offset + index,
            "low": 99.0 + offset + index,
            "close": 101.0 + offset + index,
            "volume": 1_000.0 + index * 10,
            "source_state": "REALTIME",
        }
        for index, session_date in enumerate(sessions(count))
    ]


def btc_marks(count: int = 22) -> list[dict]:
    return [
        {
            "observed_at_ms": close_ms(session_date),
            "price_usd": 70_000.0 + index * 100,
            "source_state": "VALID_FRESH",
        }
        for index, session_date in enumerate(sessions(count))
    ]


def build(**overrides):
    payload = {
        "equity_bars": {"MSTR": bars("MSTR"), "ASST": bars("ASST")},
        "btc_close_marks": btc_marks(),
        "generated_at_ms": close_ms(sessions()[-1]) + 1,
    }
    payload.update(overrides)
    return build_mstr_asst_full_day_market_intake(**payload)


class FullDayMarketIntakeTests(unittest.TestCase):

    def test_excludes_unfinished_daily_bar(self):
        equity = {"MSTR": bars("MSTR"), "ASST": bars("ASST")}
        future = "2026-09-01"
        for asset in equity:
            equity[asset].append(
                {
                    "session_date": future,
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 1,
                }
            )
        result = build(
            equity_bars=equity,
            generated_at_ms=close_ms(future) - 1,
        )
        self.assertEqual(result["assets"]["MSTR"]["excluded_incomplete_sessions"], 1)
        self.assertNotEqual(
            result["assets"]["MSTR"]["latest_complete_session"]["session_date"],
            future,
        )

    def test_early_close_is_complete_after_official_close(self):
        early = "2026-11-27"
        equity = {"MSTR": bars("MSTR"), "ASST": bars("ASST")}
        for asset in equity:
            equity[asset].append(
                {
                    "session_date": early,
                    "open": 100,
                    "high": 102,
                    "low": 99,
                    "close": 101,
                    "volume": 1500,
                }
            )
        marks = btc_marks() + [
            {"observed_at_ms": close_ms(early, 13), "price_usd": 75_000}
        ]
        result = build(
            equity_bars=equity,
            btc_close_marks=marks,
            generated_at_ms=close_ms(early, 13) + 1,
        )
        self.assertEqual(
            result["assets"]["MSTR"]["latest_complete_session"]["session_close_ms"],
            close_ms(early, 13),
        )

    def test_relative_btc_uses_exact_equity_close_clock(self):
        result = build()
        relative = result["assets"]["MSTR"]["relative_btc"]
        self.assertEqual(relative["state"], "VALID")
        self.assertTrue(relative["same_window"])
        self.assertTrue(relative["same_time_basis"])

    def test_missing_btc_mark_blocks_only_relative_claim(self):
        marks = btc_marks()
        marks.pop()
        result = build(btc_close_marks=marks)
        asset = result["assets"]["MSTR"]
        self.assertEqual(asset["state"], "VALID")
        self.assertEqual(asset["relative_btc"]["state"], "BLOCKED")

    def test_computes_latest_and_previous_rvol20(self):
        result = build()["assets"]["MSTR"]
        self.assertIsNotNone(result["rvol20"])
        self.assertIsNotNone(result["previous_rvol20"])
        self.assertGreater(result["rvol20"], 1.0)

    def test_computes_one_and_five_session_returns(self):
        result = build()["assets"]["MSTR"]
        self.assertIsNotNone(result["return_1d_pct"])
        self.assertIsNotNone(result["return_5d_pct"])
        self.assertIsNotNone(result["relative_btc"]["btc_excess_return_5d_pct"])

    def test_rejects_unapproved_asset_scope(self):
        with self.assertRaises(ValueError):
            build_mstr_asst_full_day_market_intake(
                equity_bars={"MSTR": bars("MSTR"), "TSLA": bars("ASST")},
                btc_close_marks=btc_marks(),
                generated_at_ms=close_ms(sessions()[-1]) + 1,
            )

    def test_preserves_no_external_action_authority(self):
        result = build()
        self.assertEqual(result["action_output"], "NONE")
        self.assertEqual(result["external_action_authority"], "NONE")
        self.assertFalse(result["external_action_performed"])
        self.assertEqual(len(result["snapshot_hash"]), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
