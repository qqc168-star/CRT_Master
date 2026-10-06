from __future__ import annotations

from copy import deepcopy
import unittest

from crt_radar.gpt_handoff import semantic_wake_key
from crt_radar.issuer_announcement_runner import (
    _canonical_hash,
    compact_issuer_announcement_wake,
    validate_issuer_announcement_wake,
)
from crt_radar.reanalysis_wake import fuse_reanalysis_wake


NOW = 1_800_000_000_000


def authority() -> dict:
    return {
        "action_output": "NONE",
        "external_action_authority": "NONE",
        "external_action_performed": False,
    }


def base_wake() -> dict:
    return {
        "state": "NO_WAKE",
        "reason": "CHANGE_WITHIN_INTRADAY_HISTORY",
        "metric": "btc_spot_price_usd",
        "input_family": "BTC_SPOT_PRICE",
        "current_value": 100.0,
        "previous_value": 100.0,
        "percent_change": 0.0,
        "historical_percentile": 50.0,
        "baseline_count": 20,
        "analyst_reanalysis_requested": False,
        **authority(),
    }


def stable_plan() -> dict:
    return {
        "state": "STABLE",
        "reason": "ACTIVE_PLAN_CONDITIONS_SATISFIED",
        "reanalysis_required": False,
        **authority(),
    }


def event(event_id: str) -> dict:
    row = {
        "event_id": event_id,
        "issuer_id": "STRATEGY_INC",
        "issuer_name": "Strategy Inc",
        "source_type": "OFFICIAL_PRESS_RELEASE",
        "source_id": "STRATEGY_OFFICIAL_PRESS_ARCHIVE",
        "source_url": "https://www.strategy.com/mstr/votes",
        "accession_number": None,
        "filing_date": "2026-10-05",
        "report_date": None,
        "accepted_at": None,
        "form": None,
        "items": "",
        "title": (
            "Strategy Proposes to Pay Daily Dividends "
            "on its U.S. Listed Preferred Securities"
        ),
        "classification": "CAPITAL_OR_TREASURY_POLICY",
        "symbols": ["MSTR", "STRC"],
        "position_relevance": [
            "STRC_ISSUER",
            "DIVIDEND_POLICY",
        ],
    }
    row["event_hash"] = _canonical_hash(row)
    return row


def announcement(event_id: str = "STRATEGY_INC:PRESS:DAILY") -> dict:
    row = {
        "schema_version": "CRT_ISSUER_ANNOUNCEMENT_WAKE_V1",
        "state": "REANALYSIS_REQUESTED",
        "reason": "NEW_OFFICIAL_ISSUER_ANNOUNCEMENT",
        "observed_at_ms": NOW,
        "baseline_established_before_poll": True,
        "coverage_state": "VALID",
        "coverage": [],
        "new_event_count": 1,
        "new_events": [event(event_id)],
        "analyst_reanalysis_requested": True,
        **authority(),
    }
    row["wake_hash"] = _canonical_hash(row)
    return row


class IssuerAnnouncementWakeClosureTests(unittest.TestCase):
    def test_verified_announcement_promotes_no_wake(self) -> None:
        fused = fuse_reanalysis_wake(
            base_wake(),
            plan_drift=stable_plan(),
            issuer_announcement_wake=announcement(),
        )
        self.assertEqual(
            fused["state"],
            "REANALYSIS_REQUESTED",
        )
        self.assertEqual(
            fused["input_family"],
            "ISSUER_ANNOUNCEMENT",
        )
        self.assertIn(
            "ISSUER_ANNOUNCEMENT",
            fused["wake_sources"],
        )
        self.assertTrue(
            fused["issuer_announcement_reanalysis_requested"]
        )
        self.assertEqual(
            fused["external_action_authority"],
            "NONE",
        )

    def test_tampered_event_fails_closed(self) -> None:
        bad = announcement()
        bad["new_events"][0]["title"] = "tampered"
        bad_material = deepcopy(bad)
        bad_material.pop("wake_hash")
        bad["wake_hash"] = _canonical_hash(bad_material)
        with self.assertRaises(ValueError):
            validate_issuer_announcement_wake(
                bad,
                generated_at_ms=NOW + 1,
            )

    def test_compact_projection_keeps_triggering_public_event(self) -> None:
        compact = compact_issuer_announcement_wake(
            announcement(),
            generated_at_ms=NOW + 1,
        )
        self.assertEqual(
            compact["new_events"][0]["issuer_id"],
            "STRATEGY_INC",
        )
        self.assertIn(
            "Proposes",
            compact["new_events"][0]["title"],
        )
        self.assertNotIn("coverage", compact)

    def test_semantic_dedupe_same_event_same_key_new_event_new_key(self) -> None:
        def pack(event_id: str) -> dict:
            ann = announcement(event_id)
            fused = fuse_reanalysis_wake(
                base_wake(),
                plan_drift=stable_plan(),
                issuer_announcement_wake=ann,
            )
            return {
                "generated_at_ms": NOW + 1,
                "reanalysis_wake": fused,
                "plan_drift": stable_plan(),
                "issuer_announcement_wake": ann,
            }

        first = semantic_wake_key(pack("EVENT-A"))
        same = semantic_wake_key(pack("EVENT-A"))
        second = semantic_wake_key(pack("EVENT-B"))

        self.assertEqual(first, same)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
