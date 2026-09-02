from __future__ import annotations

import unittest
from datetime import date, timedelta

from crt_radar.ibkr_market_health_sources import (
    IbkrMarketHealthSourceError,
    normalize_ibkr_daily_capture,
)


def capture() -> dict:
    current = date(2026, 7, 27)
    sessions = []
    while len(sessions) < 22:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return {
        asset: [
            {
                "date": session.strftime("%Y%m%d"),
                "open": 100 + index,
                "high": 102 + index,
                "low": 99 + index,
                "close": 101 + index,
                "volume": 1000 + index,
            }
            for index, session in enumerate(sessions)
        ]
        for asset in ("MSTR", "ASST")
    }


class IbkrMarketHealthSourcesTests(unittest.TestCase):

    def test_normalizes_daily_history(self):
        result = normalize_ibkr_daily_capture(capture())
        self.assertEqual(result["MSTR"][0]["session_date"], "2026-07-27")
        self.assertEqual(result["ASST"][-1]["source_state"], "IBKR_HISTORICAL_TRADES_RTH")

    def test_requires_both_assets(self):
        raw = capture()
        del raw["ASST"]
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "exactly"):
            normalize_ibkr_daily_capture(raw)

    def test_requires_rvol_history(self):
        raw = capture()
        raw["MSTR"] = raw["MSTR"][:21]
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "at least 22"):
            normalize_ibkr_daily_capture(raw)

    def test_rejects_bad_bar_geometry(self):
        raw = capture()
        raw["MSTR"][0]["close"] = 500
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "geometry"):
            normalize_ibkr_daily_capture(raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
