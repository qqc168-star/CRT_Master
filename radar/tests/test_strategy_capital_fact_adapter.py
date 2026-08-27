from __future__ import annotations

import unittest

from crt_radar.reflexivity_overlay import build_reflexivity_overlay
from crt_radar.strategy_capital_fact_adapter import (
    build_strategy_capital_reflexivity_input,
)


ACCEPTED = 1787788800000


def fact_map(result):
    return {
        row["fact_type"]: row
        for row in result["issuer_facts"]["items"]
    }


def blocker_codes(result):
    return {
        row["code"]
        for row in result["reflexivity_blockers"]["items"]
    }


class StrategyCapitalFactAdapterTests(unittest.TestCase):
    def test_mstr_complete_capital_document(self):
        raw = """
        <p>As of August 26, 2026, Strategy holds
        700,000 bitcoins.</p>
        <p>Fully diluted shares outstanding: 400,000,000.</p>
        <p>Under its at-the-market program Strategy sold
        5,000,000 shares of Class A common stock.</p>
        """

        result = build_strategy_capital_reflexivity_input(
            raw,
            mode="MSTR_CAPITAL",
            accepted_at_ms=ACCEPTED,
            require_atm=True,
        )

        self.assertEqual(
            result["issuer_facts"]["coverage_state"],
            "COMPLETE",
        )

        facts = fact_map(result)

        self.assertEqual(
            facts["BTC_HOLDINGS"]["value"],
            700000.0,
        )
        self.assertEqual(
            facts["DILUTED_SHARES"]["value"],
            400000000.0,
        )
        self.assertEqual(
            facts["ATM_SHARES_ISSUED"]["value"],
            5000000.0,
        )

    def test_mstr_facts_normalize_but_overlay_remains_fail_closed(self):
        raw = """
        As of August 26, 2026, Strategy holds 700,000 bitcoins.
        Fully diluted shares outstanding: 400,000,000.
        """

        adapter = build_strategy_capital_reflexivity_input(
            raw,
            mode="MSTR_CAPITAL",
            accepted_at_ms=ACCEPTED,
        )

        overlay = build_reflexivity_overlay(adapter)

        fact_types = {
            row["fact_type"]
            for row in overlay["asset_facts"]["items"]
        }

        self.assertIn("BTC_HOLDINGS", fact_types)
        self.assertIn("DILUTED_SHARES", fact_types)

        # Capital-fact completion does not pretend issuer-event or
        # market-reaction coverage is complete.
        self.assertEqual(
            overlay["asset_facts"]["section_state"],
            "BLOCKED",
        )
        self.assertEqual(adapter["action_output"], "NONE")
        self.assertEqual(
            adapter["external_action_authority"],
            "NONE",
        )

        self.assertEqual(
            overlay["blockers"]["section_state"],
            "BLOCKED",
        )

        blocker_codes = {
            row["reason_code"]
            for row in overlay["blockers"]["items"]
        }
        self.assertIn(
            "SECTION_COVERAGE_INCOMPLETE",
            blocker_codes,
        )

    def test_mstr_missing_diluted_shares_fails_closed(self):
        result = build_strategy_capital_reflexivity_input(
            "Strategy holds 700,000 bitcoins.",
            mode="MSTR_CAPITAL",
            accepted_at_ms=ACCEPTED,
        )

        self.assertEqual(
            result["issuer_facts"]["coverage_state"],
            "PARTIAL",
        )
        self.assertIn(
            "MSTR_DILUTED_SHARES_NOT_FOUND",
            blocker_codes(result),
        )

    def test_mstr_missing_disclosure_timestamp_emits_no_facts(self):
        result = build_strategy_capital_reflexivity_input(
            """
            Strategy holds 700,000 bitcoins.
            Fully diluted shares outstanding: 400,000,000.
            """,
            mode="MSTR_CAPITAL",
        )

        self.assertEqual(
            result["issuer_facts"]["items"],
            [],
        )
        self.assertIn(
            "DISCLOSURE_TIMESTAMP_UNKNOWN",
            blocker_codes(result),
        )

    def test_strc_dividend_terms_complete(self):
        raw = """
        STRC annualized dividend rate is 11.5%.
        The ex-dividend date is September 14, 2026.
        The record date is September 15, 2026.
        The payment date is October 1, 2026.
        """

        result = build_strategy_capital_reflexivity_input(
            raw,
            mode="STRC_DIVIDEND",
            accepted_at_ms=ACCEPTED,
        )

        self.assertEqual(
            result["issuer_facts"]["coverage_state"],
            "COMPLETE",
        )

        facts = fact_map(result)

        self.assertEqual(
            facts["DISTRIBUTION_RATE"]["value"],
            11.5,
        )
        self.assertIn("EX_DIVIDEND_DATE", facts)
        self.assertIn("RECORD_DATE", facts)
        self.assertIn("PAYMENT_DATE", facts)

    def test_strc_ex_dividend_date_is_never_inferred(self):
        raw = """
        STRC annualized dividend rate is 11.5%.
        The record date is September 15, 2026.
        The payment date is October 1, 2026.
        """

        result = build_strategy_capital_reflexivity_input(
            raw,
            mode="STRC_DIVIDEND",
            accepted_at_ms=ACCEPTED,
        )

        facts = fact_map(result)

        self.assertNotIn("EX_DIVIDEND_DATE", facts)
        self.assertIn(
            "STRC_EX_DIVIDEND_DATE_NOT_FOUND",
            blocker_codes(result),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
