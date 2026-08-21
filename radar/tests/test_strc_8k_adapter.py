from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crt_radar.reflexivity_overlay import build_reflexivity_overlay
from crt_radar.strc_8k_adapter import build_strc_8k_reflexivity_input
from crt_radar.strc_strategy_review import build_strc_strategy_review, load_strc_strategy_context


ACCEPTED_MS = 1785153617000

REPURCHASE_TABLE = """
<table>
  <tr><th></th><th>During Period July 20, 2026 to July 26, 2026</th></tr>
  <tr>
    <th>Security</th>
    <th>Shares Repurchased</th>
    <th>Aggregate Purchase Price (in millions)</th>
  </tr>
  <tr><td>STRF Stock(1)</td><td>-</td><td>$</td><td>-</td></tr>
  <tr><td>STRC Stock(1)</td><td>288,930</td><td>$</td><td>25.0</td></tr>
  <tr><td>STRK Stock(1)</td><td>-</td><td>$</td><td>-</td></tr>
</table>
"""

ATM_TABLE = """
<table>
  <tr><th></th><th>During Period July 20, 2026 to July 26, 2026</th></tr>
  <tr>
    <th>Security</th>
    <th>Shares Sold</th>
    <th>Net Proceeds (in millions)</th>
  </tr>
  <tr><td>STRC Stock</td><td>9,999,999</td><td>$</td><td>999.9</td></tr>
</table>
"""


def filing_html(*, include_atm: bool = True, include_repurchase: bool = True, remaining: str = "$975.0 million") -> str:
    tables = (ATM_TABLE if include_atm else "") + (REPURCHASE_TABLE if include_repurchase else "")
    return f"""
    <html><body>
      <p>FORM 8-K</p>
      <p>Date of Report (Date of earliest event reported): July 27, 2026</p>
      <p>ATM Update</p>
      {tables}
      <p>Repurchase Program Updates</p>
      <p>
        (1) {remaining} aggregate purchase price of Strategy’s preferred stock
        remains available under the Digital Credit Securities Repurchase Program
        previously announced on June 29, 2026.
      </p>
    </body></html>
    """


def zero_filing_html() -> str:
    return """
    <html><body>
      <p>Date of Report (Date of earliest event reported): August 3, 2026</p>
      <table>
        <tr><th></th><th>During Period July 27, 2026 to August 2, 2026</th></tr>
        <tr>
          <th>Security</th>
          <th>Shares Repurchased</th>
          <th>Aggregate Purchase Price (in millions)</th>
        </tr>
        <tr><td>STRC Stock(1)</td><td>-</td><td>$</td><td>-</td></tr>
      </table>
      <p>
        (1) $975.0 million aggregate purchase price of Strategy’s preferred stock
        remains available under the Digital Credit Securities Repurchase Program.
      </p>
    </body></html>
    """


def fact_map(overlay: dict) -> dict:
    return {
        item["fact_type"]: item
        for item in overlay["asset_facts"]["items"]
        if item.get("security_id") == "SEC-STRC-PERP"
    }


def blocker_codes(overlay: dict) -> set[str]:
    return {
        item["reason_code"]
        for item in overlay["blockers"]["items"]
        if item.get("reason_code")
    }


class Strc8KAdapterTests(unittest.TestCase):
    def test_official_style_weekly_table_maps_to_issuer_facts_event_and_average_price(self):
        raw = filing_html()
        reflexivity_input = build_strc_8k_reflexivity_input(
            raw,
            document_id="SEC-0001193125-26-316917",
            accepted_at_ms=ACCEPTED_MS,
        )

        self.assertEqual(reflexivity_input["issuer_facts"]["coverage_state"], "COMPLETE")
        self.assertEqual(reflexivity_input["issuer_events"]["coverage_state"], "COMPLETE")
        self.assertEqual(reflexivity_input["market_reaction_facts"]["coverage_state"], "NOT_EVALUATED")
        self.assertTrue(reflexivity_input["adapter_diagnostics"]["strc_repurchase_row_found"])

        overlay = build_reflexivity_overlay(reflexivity_input)
        facts = fact_map(overlay)

        self.assertEqual(facts["REPURCHASED_SHARES"]["value"], 288_930.0)
        self.assertEqual(facts["REPURCHASE_CASH_CONSIDERATION"]["value"], 25_000_000.0)
        self.assertEqual(facts["REMAINING_AUTHORIZATION"]["value"], 975_000_000.0)
        self.assertAlmostEqual(facts["REPURCHASE_AVG_PRICE"]["value"], 86.5261482, places=6)
        self.assertFalse(facts["REPURCHASE_AVG_PRICE"]["causal_interpretation"])

        event = overlay["decision_relevant_events"]["items"][0]
        self.assertEqual(event["event_type"], "SECURITY_REPURCHASE")
        self.assertEqual(event["execution_window"]["precision"], "DATE_RANGE")
        self.assertEqual(event["disclosure_window"]["start_ms"], ACCEPTED_MS)
        self.assertTrue(event["active_for_calculation"])

        self.assertIn("SECTION_COVERAGE_INCOMPLETE", blocker_codes(overlay))
        self.assertEqual(overlay["asset_facts"]["section_state"], "BLOCKED")

    def test_atm_strc_row_is_not_mistaken_for_repurchase_row(self):
        reflexivity_input = build_strc_8k_reflexivity_input(
            filing_html(include_atm=True, include_repurchase=True),
            accepted_at_ms=ACCEPTED_MS,
        )
        rows = {
            item["fact_type"]: item["value"]
            for item in reflexivity_input["issuer_facts"]["items"]
        }
        self.assertEqual(rows["REPURCHASED_SHARES"], 288_930.0)
        self.assertEqual(rows["REPURCHASE_CASH_CONSIDERATION"], 25_000_000.0)

    def test_missing_acceptance_timestamp_keeps_reported_facts_but_blocks_event_math(self):
        reflexivity_input = build_strc_8k_reflexivity_input(filing_html())
        self.assertEqual(reflexivity_input["issuer_facts"]["coverage_state"], "COMPLETE")
        self.assertEqual(reflexivity_input["issuer_events"]["coverage_state"], "PARTIAL")
        self.assertEqual(reflexivity_input["issuer_events"]["items"], [])
        self.assertEqual(reflexivity_input["calculation_requests"], [])

        overlay = build_reflexivity_overlay(reflexivity_input)
        self.assertIn("DISCLOSURE_TIMESTAMP_UNKNOWN", blocker_codes(overlay))
        facts = fact_map(overlay)
        self.assertIn("REPURCHASED_SHARES", facts)
        self.assertNotIn("REPURCHASE_AVG_PRICE", facts)

    def test_explicit_dash_is_verified_reported_zero_not_missing(self):
        reflexivity_input = build_strc_8k_reflexivity_input(
            zero_filing_html(),
            accepted_at_ms=ACCEPTED_MS,
        )
        facts = {
            item["fact_type"]: item
            for item in reflexivity_input["issuer_facts"]["items"]
        }
        self.assertEqual(facts["REPURCHASED_SHARES"]["value"], 0.0)
        self.assertEqual(facts["REPURCHASED_SHARES"]["zero_state"], "VERIFIED_REPORTED_ZERO")
        self.assertEqual(facts["REPURCHASE_CASH_CONSIDERATION"]["value"], 0.0)
        self.assertEqual(
            facts["REPURCHASE_CASH_CONSIDERATION"]["zero_state"],
            "VERIFIED_REPORTED_ZERO",
        )
        self.assertEqual(reflexivity_input["calculation_requests"], [])

        overlay = build_reflexivity_overlay(reflexivity_input)
        self.assertNotIn("VERIFIED_ZERO_NOT_ESTABLISHED", blocker_codes(overlay))

    def test_missing_repurchase_table_fails_closed(self):
        reflexivity_input = build_strc_8k_reflexivity_input(
            filing_html(include_repurchase=False),
            accepted_at_ms=ACCEPTED_MS,
        )
        codes = {item["code"] for item in reflexivity_input["reflexivity_blockers"]["items"]}
        self.assertIn("STRC_REPURCHASE_ROW_NOT_FOUND", codes)
        self.assertIn("EXECUTION_WINDOW_INCOMPLETE", codes)
        self.assertEqual(reflexivity_input["issuer_facts"]["coverage_state"], "PARTIAL")

        overlay = build_reflexivity_overlay(reflexivity_input)
        self.assertIn("STRC_REPURCHASE_ROW_NOT_FOUND", blocker_codes(overlay))
        self.assertEqual(overlay["decision_relevant_events"]["items"], [])

    def test_adapter_feeds_strategy_review_as_partial_until_market_evidence_is_approved(self):
        reflexivity_input = build_strc_8k_reflexivity_input(
            filing_html(),
            accepted_at_ms=ACCEPTED_MS,
        )
        overlay = build_reflexivity_overlay(reflexivity_input)
        strategy = load_strc_strategy_context()
        self.assertEqual(strategy["state"], "AVAILABLE")

        review = build_strc_strategy_review(strategy, overlay)

        self.assertEqual(review["state"], "PARTIAL_FOR_ANALYST")
        self.assertEqual(review["issuer_evidence"]["state"], "AVAILABLE")
        self.assertEqual(review["market_handoff_evidence"]["state"], "BLOCKED")
        self.assertEqual(review["guidepost_evaluation"]["state"], "BLOCKED")
        self.assertEqual(review["action_output"], "NONE")
        self.assertEqual(review["external_action_authority"], "NONE")
        self.assertEqual(review["capital_decision_authority"], "USER_ONLY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
