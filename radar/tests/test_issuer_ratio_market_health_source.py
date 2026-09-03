from __future__ import annotations

import unittest

from crt_radar.issuer_ratio_market_health_source import (
    _strategy_state,
    _strive_states,
    build_ratio_data,
)


class IssuerRatioMarketHealthSourceTests(unittest.TestCase):

    def test_strategy_real_format(self):
        raw = b"""
        BTC holdings 840,447 BTC as of Aug. 23, 2026.
        Formula uses approximately ~419.9M fully diluted shares.
        """

        row = _strategy_state(
            raw,
            accepted_at_ms=1_788_000_000_000,
            source_url="SEC-TEST",
        )

        self.assertIsNotNone(row)
        self.assertEqual(row["btc_holdings"], 840447.0)
        self.assertEqual(row["diluted_shares"], 419900000.0)

    def test_strive_real_table_format(self):
        raw = b"""
        As of August 21, 2026
        As of August 28, 2026
        Change

        Bitcoin held
        21,356
        23,156
        1,800

        Assumed Fully Diluted Shares (4)
        92,949,226
        96,523,351
        3,574,125
        """

        rows = _strive_states(
            raw,
            accepted_at_ms=1_788_000_000_000,
            source_url="SEC-TEST",
        )

        self.assertEqual(len(rows), 2)

        self.assertEqual(
            rows[0]["btc_holdings"],
            21356.0,
        )

        self.assertEqual(
            rows[1]["btc_holdings"],
            23156.0,
        )

        self.assertEqual(
            rows[1]["diluted_shares"],
            96523351.0,
        )

    def test_ratio_requires_two_states_each(self):
        sample = {
            "MSTR": [
                {
                    "effective_at_ms": 1,
                    "btc_holdings": 100.0,
                    "diluted_shares": 1000.0,
                    "btc_per_diluted_share": 0.1,
                    "source_url": "a",
                    "evidence_hash": "a",
                },
                {
                    "effective_at_ms": 2,
                    "btc_holdings": 110.0,
                    "diluted_shares": 1000.0,
                    "btc_per_diluted_share": 0.11,
                    "source_url": "b",
                    "evidence_hash": "b",
                },
            ],
            "ASST": [
                {
                    "effective_at_ms": 1,
                    "btc_holdings": 20.0,
                    "diluted_shares": 200.0,
                    "btc_per_diluted_share": 0.1,
                    "source_url": "c",
                    "evidence_hash": "c",
                },
                {
                    "effective_at_ms": 2,
                    "btc_holdings": 22.0,
                    "diluted_shares": 200.0,
                    "btc_per_diluted_share": 0.11,
                    "source_url": "d",
                    "evidence_hash": "d",
                },
            ],
        }

        result = build_ratio_data(sample)

        self.assertEqual(
            result["MSTR"][
                "current_btc_per_diluted_share"
            ],
            0.11,
        )

        self.assertEqual(
            result["ASST"][
                "previous_btc_per_diluted_share"
            ],
            0.1,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)