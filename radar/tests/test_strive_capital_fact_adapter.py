from __future__ import annotations

import unittest

from crt_radar.reflexivity_overlay import build_reflexivity_overlay
from crt_radar.strive_capital_fact_adapter import (
    build_strive_capital_reflexivity_input,
)


ACCEPTED = 1787788800000

# Synthetic wording shaped like the official pricing sheet, not live acceptance.
SATS_TERMS = """Strive, Inc. PRICING TERM SHEET 15.00% Series A Perpetual SATS Preferred Stock
Amount Offered 7,000,000 shares of SATS Stock. Public Offering Price $90.00 per share of SATS Stock.
Trade Date October 16, 2026. Settlement Date October 20, 2026. Stated Amount $100 per share of SATS Stock.
Ranking senior to Common Stock; junior to indebtedness. Liquidation Preference Initially, $100 per share.
Regular Dividends rate per annum equal to 15.00% on the Stated Amount.
CUSIP / ISIN Numbers for SATS Stock 862945 409 / US8629454096"""


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
    def sats(self, text=SATS_TERMS, **changes):
        args = dict(mode="SATS_TERMS", issuer_id="CIK-0001920406", document_id="synthetic-sats",
                    accepted_at_ms=1792156800000, retrieved_at_ms=1792156801000)
        args.update(changes)
        return build_strive_capital_reflexivity_input(text, **args)

    def test_sats_pricing_is_not_settlement_or_listing(self):
        result = self.sats()
        terms = fact_map(result)["SATS_OFFERING_TERMS"]["value"]
        self.assertEqual(terms["offering_stage"], "PRICED")
        self.assertEqual(terms["conditional_gross_proceeds_usd"], 630_000_000)
        self.assertEqual(terms["conditional_initial_claims_usd"], 700_000_000)
        self.assertEqual(terms["conditional_annual_dividends_usd"], 105_000_000)
        self.assertEqual(terms["cusip"], "862945409")
        self.assertIsNone(terms["settled_net_proceeds_usd"])
        self.assertIsNone(terms["actual_outstanding_shares"])
        self.assertEqual(terms["listing_qualification"], "NOT_PROVEN")
        # Even after the scheduled date the original pricing document cannot close itself.
        later = self.sats(accepted_at_ms=1793000000000, retrieved_at_ms=1793000001000)
        self.assertEqual(fact_map(later)["SATS_OFFERING_TERMS"]["value"]["offering_stage"], "PRICED")

    def test_sats_identity_and_missing_visibility_fail_closed(self):
        for args in (dict(issuer_id="CIK-0001415404"), dict(issuer_id=None), dict(accepted_at_ms=None),
                     dict(retrieved_at_ms=1)):
            self.assertEqual(self.sats(**args)["issuer_facts"]["items"], [])
        self.assertEqual(self.sats(SATS_TERMS.replace("Strive, Inc.", "EchoStar Corporation"))["issuer_facts"]["items"], [])

    def test_sats_stage_and_ambiguous_price_are_not_inferred(self):
        proposed = self.sats("Strive, Inc. Proposed Initial Public Offering of 15.00% Series A Perpetual SATS Preferred Stock")
        self.assertEqual(fact_map(proposed)["SATS_OFFERING_TERMS"]["value"]["offering_stage"], "ANNOUNCED")
        ambiguous = self.sats(SATS_TERMS + " Public Offering Price $85.00 per share of SATS Stock.")
        self.assertIsNone(fact_map(ambiguous)["SATS_OFFERING_TERMS"]["value"]["offering_price_usd"])
        closed = self.sats(SATS_TERMS + " The issuance and sale of the SATS Stock was completed on October 15, 2026.")
        self.assertEqual(fact_map(closed)["SATS_OFFERING_TERMS"]["value"]["offering_stage"], "SETTLED")
        self.assertIsNone(fact_map(closed)["SATS_OFFERING_TERMS"]["value"]["settled_net_proceeds_usd"])

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

    def test_asst_sec_comparison_table_extracts_current_values(self):
        raw = """
        <table>
          <tr>
            <th></th>
            <th>As of September 25, 2026</th>
            <th>As of October 2, 2026</th>
            <th>Change</th>
          </tr>
          <tr>
            <td>Shares of STRC held</td>
            <td>505,000</td>
            <td>505,000</td>
            <td>?</td>
          </tr>
          <tr>
            <td>Fair value of STRC Stock (in thousands)</td>
            <td>$49,763</td>
            <td>$50,202</td>
            <td>$439</td>
          </tr>
          <tr>
            <td>Bitcoin held</td>
            <td>27,462</td>
            <td>29,462</td>
            <td>2,000</td>
          </tr>
          <tr>
            <td>Assumed Fully Diluted Shares (4)</td>
            <td>100,776,795</td>
            <td>103,714,772</td>
            <td>2,937,977</td>
          </tr>
          <tr>
            <td>Shares Underlying Traditional Warrants (5)</td>
            <td>25,349,806</td>
            <td>23,249,706</td>
            <td>(2,100,100)</td>
          </tr>
        </table>

        <table>
          <tr><th>9/30/2026</th></tr>
          <tr><td>Bitcoin held</td><td>28,000</td></tr>
          <tr>
            <td>Assumed diluted shares outstanding 1</td>
            <td>100,716,638</td>
          </tr>
        </table>
        """

        result = build_strive_capital_reflexivity_input(
            raw,
            mode="ASST_CAPITAL",
            accepted_at_ms=1791201597000,
        )

        facts = fact_map(result)

        self.assertEqual(
            facts["BTC_HOLDINGS"]["value"],
            29462.0,
        )
        self.assertEqual(
            facts["DILUTED_SHARES"]["value"],
            103714772.0,
        )
        self.assertEqual(
            facts["WARRANTS_OUTSTANDING"]["value"],
            23249706.0,
        )

        # SATA aggregate liquidation preference is not the same
        # thing as the separately disclosed SATA stated amount.
        self.assertNotIn(
            "SATA_LIQUIDATION_PREFERENCE_AGGREGATE",
            facts,
        )
        self.assertIn(
            "ASST_SATA_LIQUIDATION_PREFERENCE_AGGREGATE_NOT_FOUND",
            blocker_codes(result),
        )

        sata = build_strive_capital_reflexivity_input(
            raw,
            mode="SATA_TERMS",
            accepted_at_ms=1791201597000,
        )
        sata_facts = fact_map(sata)

        self.assertEqual(
            sata_facts["STRIVE_STRC_HOLDINGS"]["value"],
            505000.0,
        )
        self.assertEqual(
            sata_facts["STRIVE_STRC_FAIR_VALUE"]["value"],
            50202000.0,
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
