from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crt_radar.issuer_ratio_market_health_source import (
    _strategy_state,
    _strive_states,
    build_ratio_data,
    build_archived_issuer_ct_inputs,
    _document_url,
    ASSETS,
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


class ArchivedCapitalFactsTests(unittest.TestCase):
    """Synthetic dated tables exercise normalization, not real issuer proof."""

    NOW = 1791877000000
    ASST = """0001920406 TEST ONLY
    <table><tr><td></td><td>As of September 25, 2026</td><td>As of October 2, 2026</td><td>Change</td></tr>
    <tr><td>Bitcoin held</td><td>27,462</td><td>29,462</td><td>2,000</td></tr>
    <tr><td>Cash and cash equivalents (in thousands)</td><td>$ 248,800</td><td>$ 284,700</td><td>$ 35,900</td></tr>
    <tr><td>Class A common stock</td><td>88,453,685</td><td>91,708,804</td><td>3,255,119</td></tr>
    <tr><td>Class B common stock</td><td>9,198,036</td><td>9,230,182</td><td>32,146</td></tr>
    <tr><td>Effective Common Shares Outstanding (2)</td><td>97,651,721</td><td>100,938,986</td><td>3,287,265</td></tr>
    <tr><td>Assumed Fully Diluted Shares (4)</td><td>100,776,795</td><td>103,714,772</td><td>2,937,977</td></tr>
    <tr><td>Shares Underlying Traditional Warrants (5)</td><td>25,349,806</td><td>23,249,706</td><td>(2,100,100)</td></tr>
    <tr><td>Fair value of STRC Stock (in thousands)</td><td>$49,763</td><td>$50,202</td><td>$439</td></tr>
    <tr><td>Shares of STRC held</td><td>505,000</td><td>505,000</td><td>0</td></tr>
    <tr><td>SATA Stock</td><td>12,193,180</td><td>13,498,082</td><td>1,304,902</td></tr>
    <tr><td colspan="4">(1) Includes shares outstanding and shares sold through 4:00pm EST,
    which will be issued on the following business day. Assumed Fully Diluted Shares Outstanding represents Effective Common Shares Outstanding
    plus shares underlying all potentially dilutive securities, including options and unvested RSUs.
    Shares underlying Traditional Warrants are excluded from this figure. (5)</td></tr></table>
    As of September 30, 2026, the Company had 88,814,706 shares of Class A common stock,
    9,198,036 shares of Class B common stock, and 12,940,621 shares of SATA Stock outstanding.
    <table><tr><td></td><td>9/30/2026</td></tr><tr><td>Balance Sheet</td><td></td></tr>
    <tr><td>Bitcoin held</td><td>28,000</td></tr>
    <tr><td>Cash and cash equivalents (in thousands)</td><td>$284,722</td></tr>
    <tr><td>Fair value of bitcoin held (in thousands)</td><td>$2,340,192</td></tr>
    <tr><td>Fair value of STRC Stock (in thousands)</td><td>$50,172</td></tr>
    <tr><td>Total treasury value (in thousands)</td><td>$2,675,086</td></tr>
    <tr><td>Debt principal balance (in thousands)</td><td>$—</td></tr>
    <tr><td>SATA stated amount (in thousands)</td><td>$1,294,062</td></tr>
    <tr><td>Total Debt and Preferred (in thousands)</td><td>$1,294,062</td></tr>
    <tr><td>Annualized interest obligation (in thousands)</td><td>$168,228</td></tr>
    <tr><td>Assumed diluted shares outstanding 1</td><td>100,716,638</td></tr></table>
    This preliminary unaudited information has not been reviewed or audited and is subject to change.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "sec-disclosures").mkdir()
        self.manifest = []

    def add(self, asset, text, number=1):
        accession = f"0001234567-26-{number:06d}"
        raw = ("<html><body>" + text + "</body></html>").encode("utf-8")
        item = dict(asset=asset, accession=accession, primary=asset.lower() + ".htm",
            raw_sha256=hashlib.sha256(raw).hexdigest(), accepted="2026-10-05T15:59:57Z",
            retrieved_at_ms=self.NOW - 1000,
            source_url=_document_url(ASSETS[asset]["cik"], accession, asset.lower() + ".htm"))
        (self.root / "sec-disclosures" / f"{asset}-{accession}.html").write_bytes(raw)
        self.manifest.append(item)
        return item

    def inputs(self, now=None):
        (self.root / "sec-disclosures" / "manifest.json").write_text(json.dumps(self.manifest))
        return build_archived_issuer_ct_inputs(self.root, as_of_ms=now or self.NOW)

    def snapshots(self, data):
        return {r["reported_date"]: r for r in data["ASST"]["source_binding"]["observations"]
                if r.get("claim") == "REPORTED_CAPITAL_STRUCTURE_SNAPSHOT"}

    def test_mstr_cash_and_reserve_scale_independently(self):
        self.add("MSTR", "0001050446 As of October 4, 2026, the balances of the USD Reserve and USD Cash were $4.88 billion and $833.4 million, respectively.")
        row = self.inputs()["MSTR"]["burden_current"]
        self.assertEqual(row["usd_reserve_usd"], 4880000000)
        self.assertEqual(row["usd_cash_usd"], 833400000)
        self.assertEqual(row["source_evidence"]["effective_date"], "2026-10-04")
        self.assertNotIn("cash_unrestricted", row)

    def test_mstr_reverse_mixed_units_and_unknown_units(self):
        item = self.add("MSTR", "0001050446 As of October 4, 2026, the balances of the USD Reserve and USD Cash were $833.4 million and $4.88 billion, respectively.")
        self.assertEqual(self.inputs()["MSTR"]["burden_current"]["usd_reserve_usd"], 833400000)
        self.manifest.clear()
        self.add("MSTR", "0001050446 As of October 4, 2026, the balances of the USD Reserve and USD Cash were $4.88 credits and $833.4 million, respectively.", 2)
        self.assertNotIn("burden_current", self.inputs()["MSTR"])

    def test_asst_dated_facts_do_not_merge_three_snapshots(self):
        self.add("ASST", self.ASST)
        data = self.inputs()
        s = self.snapshots(data)
        self.assertEqual(set(s), {"2026-09-25", "2026-09-30", "2026-10-02"})
        self.assertEqual(s["2026-10-02"]["reported_fields"]["basic_shares"], 100938986)
        self.assertEqual(s["2026-10-02"]["share_settlement_scope"], "INCLUDES_SOLD_NOT_YET_ISSUED_SHARES")
        self.assertIn("4:00pm EST", s["2026-10-02"]["share_settlement_source_note"])
        self.assertEqual(s["2026-09-30"]["share_settlement_scope"], "ISSUER_REPORTED_OUTSTANDING_ON_SNAPSHOT_DATE")
        self.assertEqual(s["2026-10-02"]["reported_fields"]["traditional_warrant_shares"], 23249706)
        self.assertEqual(s["2026-10-02"]["reported_fields"]["strc_fair_value_usd"], 50202000)
        self.assertEqual(s["2026-09-30"]["reported_fields"]["basic_shares"], 98012742)
        self.assertEqual(s["2026-09-30"]["reported_fields"]["diluted_shares"], 100716638)
        self.assertNotIn("traditional_warrant_shares", s["2026-09-30"]["reported_fields"])
        self.assertEqual([r["btc_holdings"] for r in data["ASST"]["asset_history"]], [27462, 29462])

    def test_preferred_stated_and_aggregate_carry_remain_partial(self):
        self.add("ASST", self.ASST)
        data = self.inputs()
        row = self.snapshots(data)["2026-09-30"]
        self.assertEqual(row["reported_fields"]["preferred_stated_amount_usd"], 1294062000)
        self.assertEqual(row["reported_fields"]["reported_annual_payment_obligation_usd"], 168228000)
        self.assertEqual(row["reported_fields"]["debt_principal_usd"], 0)
        for key in ("preferred_liquidation_claims_usd", "other_senior_claims_usd", "tax_liabilities_usd", "cash_unrestricted", "warrant_exercise_proceeds_usd"):
            self.assertIsNone(row[key])
        self.assertTrue(row["preliminary_unaudited"])
        self.assertFalse(row["active_for_calculation"])
        self.assertNotIn("annual_carry_usd", data["ASST"]["burden_current"])
        self.assertNotIn("annual_interest_usd", row["reported_fields"])

    def test_unreconciled_debt_dash_is_not_zero(self):
        self.add("ASST", self.ASST.replace("<td>Total Debt and Preferred (in thousands)</td><td>$1,294,062", "<td>Total Debt and Preferred (in thousands)</td><td>$1,394,062"))
        self.assertIsNone(self.snapshots(self.inputs())["2026-09-30"]["reported_fields"]["debt_principal_usd"])

    def test_partial_facts_keep_four_clocks_hash_and_share_scope(self):
        item = self.add("ASST", self.ASST)
        row = self.snapshots(self.inputs())["2026-10-02"]
        self.assertEqual(row["source_evidence"]["raw_sha256"], item["raw_sha256"])
        self.assertLess(row["effective_time"], row["disclosure_time"])
        self.assertLess(row["disclosure_time"], row["first_seen_time"])
        self.assertEqual(row["first_seen_time"], row["retrieval_time"])
        self.assertEqual(row["share_basis"], "AFDS_EXCLUDES_TRADITIONAL_WARRANTS")

    def test_tampered_raw_and_unavailable_local_time_supply_no_facts(self):
        item = self.add("ASST", self.ASST)
        self.assertEqual(self.snapshots(self.inputs(self.NOW - 1001)), {})
        item["raw_sha256"] = "0" * 64
        self.assertEqual(self.snapshots(self.inputs()), {})

    def test_future_snapshot_and_missing_common_do_not_borrow_other_date(self):
        self.add("ASST", self.ASST.replace("9/30/2026", "10/30/2026"))
        self.assertNotIn("2026-10-30", self.snapshots(self.inputs()))
        self.manifest.clear()
        self.add("ASST", self.ASST.replace("the Company had 88,814,706", "the Company had an unknown number of"), 2)
        self.assertNotIn("basic_shares", self.snapshots(self.inputs())["2026-09-30"]["reported_fields"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
