from __future__ import annotations

import unittest

from crt_radar.issuer_fact_history import (
    recent_numeric_changes,
    select_fact_history,
)


def _ref(hash_value: str):
    return [{
        "source_id": "SRC",
        "source_as_of_ms": 1,
        "evidence_hash": hash_value,
    }]


def _fact(fid, value, ts, hash_value):
    return {
        "asset_fact_id": fid,
        "issuer_id": "ISSUER",
        "security_id": "SECURITY",
        "fact_type": "BTC_HOLDINGS",
        "value": value,
        "unit": "BTC",
        "effective_at_ms": ts,
        "source_refs": _ref(hash_value),
        "quality_state": "VALID_REPORTED",
    }


def _overlay(items, coverage="COMPLETE"):
    return {
        "asset_facts": {
            "section_state": (
                "READY"
                if coverage == "COMPLETE"
                else "PARTIAL"
            ),
            "coverage_state": coverage,
            "items": items,
        }
    }


class IssuerFactHistoryTests(unittest.TestCase):
    def test_three_changes_require_four_snapshots(self):
        items = [
            _fact("f1", 100, 1, "h1"),
            _fact("f2", 110, 2, "h2"),
            _fact("f3", 125, 3, "h3"),
            _fact("f4", 140, 4, "h4"),
        ]

        history = select_fact_history(
            _overlay(items),
            fact_type="BTC_HOLDINGS",
            issuer_id="ISSUER",
            security_id="SECURITY",
        )

        result = recent_numeric_changes(
            history,
            changes=3,
        )

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertEqual(
            [item["delta"] for item in result["value"]],
            [10.0, 15.0, 15.0],
        )

    def test_only_two_changes_is_partial(self):
        items = [
            _fact("f1", 100, 1, "h1"),
            _fact("f2", 110, 2, "h2"),
            _fact("f3", 125, 3, "h3"),
        ]

        result = recent_numeric_changes(
            select_fact_history(
                _overlay(items),
                fact_type="BTC_HOLDINGS",
                issuer_id="ISSUER",
                security_id="SECURITY",
            ),
            changes=3,
        )

        self.assertEqual(result["state"], "PARTIAL")
        self.assertEqual(len(result["value"]), 2)

    def test_conflicting_same_timestamp_fails_closed(self):
        items = [
            _fact("f1", 100, 1, "h1"),
            _fact("f2", 101, 1, "h2"),
        ]

        history = select_fact_history(
            _overlay(items),
            fact_type="BTC_HOLDINGS",
            issuer_id="ISSUER",
            security_id="SECURITY",
        )

        self.assertEqual(history["state"], "BLOCKED")
        self.assertEqual(
            history["reason"],
            "CONFLICTING_FACTS_AT_SAME_EFFECTIVE_TIME",
        )

    def test_incomplete_coverage_remains_partial(self):
        history = select_fact_history(
            _overlay(
                [_fact("f1", 100, 1, "h1")],
                coverage="PARTIAL",
            ),
            fact_type="BTC_HOLDINGS",
            issuer_id="ISSUER",
            security_id="SECURITY",
        )

        self.assertEqual(history["state"], "PARTIAL")


if __name__ == "__main__":
    unittest.main(verbosity=2)