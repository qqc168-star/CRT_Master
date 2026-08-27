from __future__ import annotations

import unittest

from crt_radar.reflexivity_overlay import build_reflexivity_overlay
from crt_radar.strive_capital_fact_adapter import (
    build_strive_capital_reflexivity_input,
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


class StriveCapitalFactAdapterTests(unittest.TestCase):
    def test_asst_complete_capital_document(self):
        raw = """
        Strive holds 21,356 bitcoins.
        Fully diluted shares outstanding: 15,000,000.
        SATA aggregate liquidation preference is $350 million.
        Warrants outstanding to purchase 2,500,000 shares.
        Under its at-the-market program Strive sold
        1,000,000 shares.
        """

        result = build_strive_capital_reflexivity_input(
            raw,
            mode="ASST_CAPITAL",
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
            21356.0,
        )
        self.assertEqual(
            facts["DILUTED_SHARES"]["value"],
            15000000.0,
        )
        self.assertEqual(
            facts["SATA_LIQUIDATION_PREFERENCE_AGGREGATE"]["value"],
            350000000.0,
        )
        self.assertEqual(
            facts["WARRANTS_OUTSTANDING"]["value"],
            2500000.0,
        )

    def test_strive_facts_normalize_but_overlay_remains_fail_closed(self):
        raw = """
        Strive holds 21,356 bitcoins.
        Fully diluted shares outstanding: 15,000,000.
        SATA aggregate liquidation preference is $350 million.
        Warrants outstanding to purchase 2,500,000 shares.
        """

        adapter = build_strive_capital_reflexivity_input(
            raw,
            mode="ASST_CAPITAL",
            accepted_at_ms=ACCEPTED,
        )

        overlay = build_reflexivity_overlay(adapter)

        fact_types = {
            row["fact_type"]
            for row in overlay["asset_facts"]["items"]
        }

        self.assertIn("BTC_HOLDINGS", fact_types)
        self.assertIn(
            "SATA_LIQUIDATION_PREFERENCE_AGGREGATE",
            fact_types,
        )

        # Facts survive normalization, while incomplete event/market
        # evidence correctly keeps the complete overlay fail-closed.
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

    def test_asst_missing_sata_liquidation_preference_is_partial(self):
        raw = """
        Strive holds 21,356 bitcoins.
        Fully diluted shares outstanding: 15,000,000.
        Warrants outstanding to purchase 2,500,000 shares.
        """

        result = build_strive_capital_reflexivity_input(
            raw,
            mode="ASST_CAPITAL",
            accepted_at_ms=ACCEPTED,
        )

        self.assertEqual(
            result["issuer_facts"]["coverage_state"],
            "PARTIAL",
        )
        self.assertIn(
            "ASST_SATA_LIQUIDATION_PREFERENCE_AGGREGATE_NOT_FOUND",
            blocker_codes(result),
        )

    def test_asst_missing_timestamp_emits_no_facts(self):
        result = build_strive_capital_reflexivity_input(
            """
            Strive holds 21,356 bitcoins.
            Fully diluted shares outstanding: 15,000,000.
            SATA aggregate liquidation preference is $350 million.
            Warrants outstanding to purchase 2,500,000 shares.
            """,
            mode="ASST_CAPITAL",
        )

        self.assertEqual(
            result["issuer_facts"]["items"],
            [],
        )
        self.assertIn(
            "DISCLOSURE_TIMESTAMP_UNKNOWN",
            blocker_codes(result),
        )

    def test_sata_terms_complete(self):
        raw = """
        Strive holds 1,250,000 shares of STRC.
        The fair value of our STRC holdings was $112.5 million.
        SATA annualized distribution rate is 13.0%.
        SATA stated amount is $100 per share.
        SATA liquidation preference is $100 per share.
        """

        result = build_strive_capital_reflexivity_input(
            raw,
            mode="SATA_TERMS",
            accepted_at_ms=ACCEPTED,
        )

        self.assertEqual(
            result["issuer_facts"]["coverage_state"],
            "COMPLETE",
        )

        facts = fact_map(result)

        self.assertEqual(
            facts["STRIVE_STRC_HOLDINGS"]["value"],
            1250000.0,
        )
        self.assertEqual(
            facts["STRIVE_STRC_FAIR_VALUE"]["value"],
            112500000.0,
        )
        self.assertEqual(
            facts["DISTRIBUTION_RATE"]["value"],
            13.0,
        )
        self.assertEqual(
            facts["STATED_AMOUNT"]["value"],
            100.0,
        )
        self.assertEqual(
            facts["LIQUIDATION_PREFERENCE"]["value"],
            100.0,
        )

    def test_sata_missing_fair_value_fails_closed(self):
        raw = """
        Strive holds 1,250,000 shares of STRC.
        SATA annualized distribution rate is 13.0%.
        SATA stated amount is $100 per share.
        SATA liquidation preference is $100 per share.
        """

        result = build_strive_capital_reflexivity_input(
            raw,
            mode="SATA_TERMS",
            accepted_at_ms=ACCEPTED,
        )

        self.assertIn(
            "STRIVE_STRC_FAIR_VALUE_NOT_FOUND",
            blocker_codes(result),
        )
        self.assertEqual(
            result["issuer_facts"]["coverage_state"],
            "PARTIAL",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
