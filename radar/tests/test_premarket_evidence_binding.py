from __future__ import annotations

import unittest

from crt_radar.premarket_evidence_binding import (
    build_premarket_evidence_binding,
)


def _ref(hash_value: str):
    return [{
        "source_id": "SRC",
        "source_as_of_ms": 1,
        "evidence_hash": hash_value,
    }]


def _fact(
    fid,
    issuer,
    security,
    fact_type,
    value,
    ts,
    hash_value,
):
    return {
        "asset_fact_id": fid,
        "issuer_id": issuer,
        "security_id": security,
        "fact_type": fact_type,
        "value": value,
        "unit": "X",
        "effective_at_ms": ts,
        "source_refs": _ref(hash_value),
        "quality_state": "VALID_REPORTED",
    }


def _overlay(
    items,
    *,
    event_coverage="COMPLETE",
    events=None,
):
    event_section = {
        "section_state": (
            "READY"
            if event_coverage == "COMPLETE"
            else "PARTIAL"
        ),
        "coverage_state": event_coverage,
        "items": list(events or []),
    }

    if event_coverage == "COMPLETE" and not event_section["items"]:
        event_section["empty_reason"] = "VERIFIED_NO_MATCH"

    return {
        "asset_facts": {
            "section_state": "READY",
            "coverage_state": "COMPLETE",
            "items": items,
        },
        "decision_relevant_events": event_section,
    }


def _repurchase_event(index, *, disclosure_ms=None):
    disclosure = index if disclosure_ms is None else disclosure_ms
    return {
        "event_id": f"event-{index}",
        "issuer_id": "CIK-0001050446",
        "security_id": "SEC-STRC-PERP",
        "event_type": "SECURITY_REPURCHASE",
        "execution_window": {
            "kind": "EXECUTION",
            "start_ms": index * 100,
            "end_ms": index * 100 + 99,
            "precision": "DATE_RANGE",
        },
        "disclosure_window": {
            "kind": "DISCLOSURE",
            "start_ms": disclosure,
            "end_ms": disclosure,
            "precision": "SECOND",
        },
        "reported_values": [
            {
                "fact_id": f"shares-{index}",
                "value": 100 * index,
                "unit": "SHARES",
            },
            {
                "fact_id": f"cash-{index}",
                "value": 1000 * index,
                "unit": "USD",
            },
        ],
        "active_for_calculation": True,
    }


class PremarketEvidenceBindingTests(unittest.TestCase):
    def test_growth_asset_recent_three_and_per_share(self):
        items = []

        for ts, btc, shares, hash_value in (
            (1, 100, 10, "h1"),
            (2, 110, 10, "h2"),
            (3, 120, 12, "h3"),
            (4, 132, 12, "h4"),
        ):
            items.extend([
                _fact(
                    f"btc-{ts}",
                    "ISSUER",
                    "SECURITY",
                    "BTC",
                    btc,
                    ts,
                    hash_value,
                ),
                _fact(
                    f"shares-{ts}",
                    "ISSUER",
                    "SECURITY",
                    "SHARES",
                    shares,
                    ts,
                    hash_value,
                ),
            ])

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(items),
            growth_specs={
                "MSTR": {
                    "issuer_id": "ISSUER",
                    "security_id": "SECURITY",
                    "btc_holdings_fact_type": "BTC",
                    "diluted_shares_fact_type": "SHARES",
                }
            },
            mnav_results={
                "MSTR": {
                    "state": "AVAILABLE",
                    "mnav": 0.8,
                }
            },
        )

        mstr = result["asset_facts"]["MSTR"]

        self.assertEqual(
            mstr["btc_holdings_last_3"]["state"],
            "AVAILABLE",
        )
        self.assertEqual(
            mstr["btc_per_diluted_share"]["state"],
            "AVAILABLE",
        )
        self.assertAlmostEqual(
            mstr["btc_per_diluted_share"]["value"],
            11.0,
        )
        self.assertEqual(
            mstr["diluted_mnav"]["mnav"],
            0.8,
        )

    def test_per_share_source_mismatch_blocks(self):
        items = [
            _fact(
                "btc",
                "ISSUER",
                "SECURITY",
                "BTC",
                100,
                1,
                "h1",
            ),
            _fact(
                "shares",
                "ISSUER",
                "SECURITY",
                "SHARES",
                10,
                1,
                "h2",
            ),
        ]

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(items),
            growth_specs={
                "MSTR": {
                    "issuer_id": "ISSUER",
                    "security_id": "SECURITY",
                    "btc_holdings_fact_type": "BTC",
                    "diluted_shares_fact_type": "SHARES",
                }
            },
        )

        self.assertEqual(
            result["asset_facts"]["MSTR"][
                "btc_per_diluted_share"
            ]["state"],
            "BLOCKED",
        )

    def test_strc_five_rounds_are_preserved(self):
        items = []

        for index in range(1, 6):
            hash_value = f"h{index}"

            items.extend([
                _fact(
                    f"shares-{index}",
                    "CIK-0001050446",
                    "SEC-STRC-PERP",
                    "REPURCHASED_SHARES",
                    100 * index,
                    index,
                    hash_value,
                ),
                _fact(
                    f"cash-{index}",
                    "CIK-0001050446",
                    "SEC-STRC-PERP",
                    "REPURCHASE_CASH_CONSIDERATION",
                    1000 * index,
                    index,
                    hash_value,
                ),
            ])

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(
                items,
                events=[
                    _repurchase_event(index)
                    for index in range(1, 6)
                ],
            ),
            evaluation_window={"start_ms": 1, "end_ms": 10},
        )

        strc = result["asset_facts"]["STRC"]

        self.assertEqual(
            strc["repurchase_rounds"]["state"],
            "AVAILABLE",
        )
        self.assertEqual(
            len(strc["repurchase_rounds"]["value"]),
            5,
        )
        self.assertEqual(
            strc["latest_round"]["value"]["round_id"],
            5,
        )
        self.assertEqual(
            strc["cumulative_repurchase"]["value"]["shares"],
            1500.0,
        )

    def test_zero_share_round_never_divides_by_zero(self):
        items = []

        for index in range(1, 6):
            hash_value = f"h{index}"
            shares = 0 if index == 5 else 100
            cash = 0 if index == 5 else 1000

            items.extend([
                _fact(
                    f"shares-{index}",
                    "CIK-0001050446",
                    "SEC-STRC-PERP",
                    "REPURCHASED_SHARES",
                    shares,
                    index,
                    hash_value,
                ),
                _fact(
                    f"cash-{index}",
                    "CIK-0001050446",
                    "SEC-STRC-PERP",
                    "REPURCHASE_CASH_CONSIDERATION",
                    cash,
                    index,
                    hash_value,
                ),
            ])

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(
                items,
                events=[
                    _repurchase_event(index)
                    for index in range(1, 6)
                ],
            ),
            evaluation_window={"start_ms": 1, "end_ms": 10},
        )

        self.assertIsNone(
            result["asset_facts"]["STRC"][
                "latest_round"
            ]["value"]["avg_price"]
        )

    def test_incomplete_event_coverage_never_claims_no_event(self):
        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(
                [],
                event_coverage="PARTIAL",
            ),
            evaluation_window={"start_ms": 100, "end_ms": 200},
        )

        self.assertNotEqual(
            result["issuer_reflexivity"].get("event_state"),
            "NO_NEW_MATERIAL_ISSUER_EVENT",
        )
        self.assertEqual(
            result["issuer_reflexivity"]["state"],
            "PARTIAL",
        )

    def test_missing_evaluation_window_fails_closed(self):
        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay([]),
        )

        self.assertEqual(
            result["issuer_reflexivity"]["state"],
            "BLOCKED",
        )
        self.assertEqual(
            result["issuer_reflexivity"]["reason"],
            "ISSUER_EVENT_EVALUATION_WINDOW_REQUIRED",
        )

    def test_historical_event_outside_window_is_not_new_event(self):
        historical = _repurchase_event(
            1,
            disclosure_ms=50,
        )

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(
                [],
                events=[historical],
            ),
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
        )

        self.assertEqual(
            result["issuer_reflexivity"]["state"],
            "VALID",
        )
        self.assertEqual(
            result["issuer_reflexivity"]["event_state"],
            "NO_NEW_MATERIAL_ISSUER_EVENT",
        )

    def test_event_inside_window_is_material(self):
        current = _repurchase_event(
            1,
            disclosure_ms=150,
        )

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(
                [],
                events=[current],
            ),
            evaluation_window={
                "start_ms": 100,
                "end_ms": 200,
            },
        )

        self.assertEqual(
            result["issuer_reflexivity"]["event_state"],
            "MATERIAL_ISSUER_EVENT_PRESENT",
        )

    def test_strc_round_preserves_execution_window(self):
        items = [
            _fact(
                "shares-1",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "REPURCHASED_SHARES",
                100,
                1,
                "h1",
            ),
            _fact(
                "cash-1",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "REPURCHASE_CASH_CONSIDERATION",
                1000,
                1,
                "h1",
            ),
        ]

        event = _repurchase_event(1)

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(
                items,
                events=[event],
            ),
            evaluation_window={
                "start_ms": 1,
                "end_ms": 10,
            },
        )

        round_one = result["asset_facts"]["STRC"][
            "repurchase_rounds"
        ]["value"][0]

        self.assertEqual(
            round_one["execution_start_ms"],
            100,
        )
        self.assertEqual(
            round_one["execution_end_ms"],
            199,
        )

    def test_unmatched_strc_fact_is_not_silently_accepted(self):
        items = [
            _fact(
                "shares-1",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "REPURCHASED_SHARES",
                100,
                1,
                "h1",
            ),
            _fact(
                "cash-1",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "REPURCHASE_CASH_CONSIDERATION",
                1000,
                1,
                "h1",
            ),
        ]

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(items),
            evaluation_window={
                "start_ms": 1,
                "end_ms": 10,
            },
        )

        self.assertEqual(
            result["asset_facts"]["STRC"][
                "repurchase_rounds"
            ]["state"],
            "BLOCKED",
        )

    def test_governance_remains_read_only(self):
        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay([]),
        )

        self.assertEqual(
            result["action_output"],
            "NONE",
        )
        self.assertEqual(
            result["external_action_authority"],
            "NONE",
        )
        self.assertFalse(
            result["machine_may_execute_trade"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)