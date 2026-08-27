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

    def test_complete_empty_without_verified_reason_fails_closed(self):
        overlay = _overlay([])
        del overlay["decision_relevant_events"]["empty_reason"]

        result = build_premarket_evidence_binding(
            reflexivity_overlay=overlay,
            evaluation_window={"start_ms": 100, "end_ms": 200},
        )

        self.assertEqual(result["issuer_reflexivity"]["state"], "BLOCKED")
        self.assertEqual(
            result["issuer_reflexivity"]["reason"],
            "ISSUER_EVENT_EMPTY_STATE_UNVERIFIED",
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

    def test_canonical_mstr_fact_wiring_is_default(self):
        items = [
            _fact(
                "mstr-btc",
                "CIK-0001050446",
                "MSTR",
                "BTC_HOLDINGS",
                700000,
                100,
                "same",
            ),
            _fact(
                "mstr-shares",
                "CIK-0001050446",
                "MSTR",
                "DILUTED_SHARES",
                400000000,
                100,
                "same",
            ),
            _fact(
                "mstr-atm",
                "CIK-0001050446",
                "MSTR",
                "ATM_SHARES_ISSUED",
                1000000,
                100,
                "same",
            ),
        ]

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(items),
            evaluation_window={
                "start_ms": 1,
                "end_ms": 2,
            },
            mnav_results={
                "MSTR": {
                    "state": "AVAILABLE",
                    "mnav": 0.80,
                }
            },
        )

        mstr = result["asset_facts"]["MSTR"]

        self.assertEqual(
            mstr["btc_holdings_current"]["value"],
            700000,
        )
        self.assertEqual(
            mstr["diluted_shares"]["value"],
            400000000,
        )
        self.assertEqual(
            mstr["atm_issuance"]["value"],
            1000000,
        )
        self.assertAlmostEqual(
            mstr["btc_per_diluted_share"]["value"],
            0.00175,
        )
        self.assertEqual(
            mstr["diluted_mnav"]["mnav"],
            0.80,
        )

    def test_canonical_asst_and_sata_fact_wiring_is_default(self):
        items = [
            _fact(
                "asst-btc",
                "CIK-0001920406",
                "ASST",
                "BTC_HOLDINGS",
                21356,
                100,
                "asst",
            ),
            _fact(
                "asst-shares",
                "CIK-0001920406",
                "ASST",
                "DILUTED_SHARES",
                15000000,
                100,
                "asst",
            ),
            _fact(
                "asst-sata-pref",
                "CIK-0001920406",
                "ASST",
                "SATA_LIQUIDATION_PREFERENCE_AGGREGATE",
                350000000,
                100,
                "asst",
            ),
            _fact(
                "asst-warrants",
                "CIK-0001920406",
                "ASST",
                "WARRANTS_OUTSTANDING",
                2500000,
                100,
                "asst",
            ),
            _fact(
                "sata-strc-1",
                "CIK-0001920406",
                "SATA",
                "STRIVE_STRC_HOLDINGS",
                100000,
                100,
                "sata1",
            ),
            _fact(
                "sata-strc-2",
                "CIK-0001920406",
                "SATA",
                "STRIVE_STRC_HOLDINGS",
                120000,
                200,
                "sata2",
            ),
            _fact(
                "sata-fair",
                "CIK-0001920406",
                "SATA",
                "STRIVE_STRC_FAIR_VALUE",
                12000000,
                200,
                "sata2",
            ),
            _fact(
                "sata-rate",
                "CIK-0001920406",
                "SATA",
                "DISTRIBUTION_RATE",
                13.0,
                200,
                "sata2",
            ),
            _fact(
                "sata-stated",
                "CIK-0001920406",
                "SATA",
                "STATED_AMOUNT",
                100.0,
                200,
                "sata2",
            ),
            _fact(
                "sata-liquidation",
                "CIK-0001920406",
                "SATA",
                "LIQUIDATION_PREFERENCE",
                100.0,
                200,
                "sata2",
            ),
        ]

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(items),
            evaluation_window={
                "start_ms": 1,
                "end_ms": 300,
            },
        )

        asst = result["asset_facts"]["ASST"]
        sata = result["asset_facts"]["SATA"]

        self.assertEqual(
            asst["sata_burden"]["state"],
            "PARTIAL",
        )
        self.assertEqual(
            asst["sata_burden"]["reason"],
            "SATA_BURDEN_COMPONENT_ONLY",
        )
        self.assertEqual(
            asst["sata_burden"]["value"],
            350000000,
        )
        self.assertEqual(
            asst["sata_burden"]["component_fact_type"],
            "SATA_LIQUIDATION_PREFERENCE_AGGREGATE",
        )
        self.assertEqual(
            asst["warrants"]["value"],
            2500000,
        )

        # Do not mislabel ATM issuance as total dilution.
        self.assertEqual(
            asst["dilution"]["state"],
            "BLOCKED",
        )

        # Live market / derivative evidence remains out of scope.
        self.assertEqual(
            asst["short_interest"]["state"],
            "BLOCKED",
        )
        self.assertEqual(
            asst["gamma"]["state"],
            "BLOCKED",
        )

        self.assertEqual(
            sata["strive_strc_holdings_current"]["value"],
            120000,
        )
        self.assertEqual(
            sata["strive_strc_holdings_previous"]["value"],
            100000,
        )
        self.assertEqual(
            sata["strive_strc_holdings_delta"]["value"],
            20000,
        )
        self.assertEqual(
            sata["strive_strc_fair_value"]["value"],
            12000000,
        )
        self.assertEqual(
            sata["distribution_rate"]["value"],
            13.0,
        )
        self.assertEqual(
            sata["stated_amount"]["value"],
            100.0,
        )
        self.assertEqual(
            sata["liquidation_preference"]["value"],
            100.0,
        )

    def test_strc_dividend_terms_bind_from_strategy_facts(self):
        day = 86_400_000

        items = [
            _fact(
                "strc-ex",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "EX_DIVIDEND_DATE",
                3 * day,
                100,
                "strc",
            ),
            _fact(
                "strc-record",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "RECORD_DATE",
                4 * day,
                100,
                "strc",
            ),
            _fact(
                "strc-payment",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "PAYMENT_DATE",
                5 * day,
                100,
                "strc",
            ),
            _fact(
                "strc-rate",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "DISTRIBUTION_RATE",
                12.0,
                100,
                "strc",
            ),
        ]

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(items),
            evaluation_window={
                "start_ms": 2 * day,
                "end_ms": 2 * day,
            },
        )

        strc = result["asset_facts"]["STRC"]

        self.assertEqual(
            strc["next_ex_dividend_date"]["state"],
            "AVAILABLE",
        )
        self.assertEqual(
            strc["next_ex_dividend_date"]["value"],
            3 * day,
        )
        self.assertEqual(
            strc["record_date"]["value"],
            4 * day,
        )
        self.assertEqual(
            strc["payment_date"]["value"],
            5 * day,
        )
        self.assertEqual(
            strc["distribution_rate"]["value"],
            12.0,
        )

    def test_stale_strc_ex_dividend_date_never_claims_next(self):
        day = 86_400_000

        items = [
            _fact(
                "strc-ex-old",
                "CIK-0001050446",
                "SEC-STRC-PERP",
                "EX_DIVIDEND_DATE",
                1 * day,
                100,
                "strc-old",
            ),
        ]

        result = build_premarket_evidence_binding(
            reflexivity_overlay=_overlay(items),
            evaluation_window={
                "start_ms": 2 * day,
                "end_ms": 2 * day,
            },
        )

        next_date = result["asset_facts"]["STRC"][
            "next_ex_dividend_date"
        ]

        self.assertEqual(
            next_date["state"],
            "BLOCKED",
        )
        self.assertEqual(
            next_date["reason"],
            "LATEST_REPORTED_EX_DIVIDEND_DATE_NOT_FUTURE",
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