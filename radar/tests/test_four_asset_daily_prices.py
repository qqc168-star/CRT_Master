"""Synthetic vendor-shaped closes; no TWS connection or real price claim."""
from copy import deepcopy
from datetime import datetime
import unittest
from unittest.mock import patch

from crt_radar.ibkr_market_health_sources import (
    FOUR_ASSETS, PRICE_BASIS, build_four_asset_daily_proof,
    validate_four_asset_daily_proof,
)
from crt_radar.mstr_asst_market_health_runtime import canonical_hash


def stamp(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def proof(day="2026-10-09", at=None, cutoff=None):
    at = stamp("2026-10-10T14:00:00Z") if at is None else at
    capture = {a: [{"date": day.replace("-", ""), "open": 100 + i,
                    "high": 103 + i, "low": 99 + i, "close": 101 + i,
                    "volume": 1000}] for i, a in enumerate(FOUR_ASSETS)}
    return build_four_asset_daily_proof(capture, observed_at_ms=at,
                                      request_started_at_ms=at if cutoff is None else cutoff)


def reseal(value):
    value["proof_hash"] = canonical_hash({k: v for k, v in value.items() if k != "proof_hash"})
    return value


class FourAssetDailyPricesTests(unittest.TestCase):
    def test_four_independent_completed_closes_with_provenance_and_immutable_source(self):
        source = proof()
        before = deepcopy(source)
        result = validate_four_asset_daily_proof(source, at_ms=source["observed_at_ms"])
        self.assertEqual(result["state"], "VALID")
        self.assertEqual(source, before)
        self.assertEqual(result["scope"], "LAST_COMPLETED_RTH_CLOSE_NOT_LIVE_QUOTE")
        for i, asset in enumerate(FOUR_ASSETS):
            row = result["assets"][asset]
            self.assertEqual((row["state"], row["currency"], row["price_usd"]), ("VALID", "USD", 101 + i))
            self.assertEqual(row["as_of_ms"], stamp("2026-10-09T20:00:00Z"))
            self.assertEqual(row["price_type"], "RTH_SESSION_CLOSE")
            self.assertEqual(row["price_adjustment_basis"], PRICE_BASIS)
            self.assertEqual(row["raw_data_hash"], source["assets"][asset]["raw_data_hash"])
            self.assertEqual(row["source_ref"]["evidence_hash"], source["proof_hash"])
            self.assertEqual(row["calendar_id"], source["calendar_id"])

    def test_missing_single_asset_does_not_erase_other_prices(self):
        source = proof()
        del source["assets"]["SATA"]
        result = validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])
        self.assertEqual(result["state"], "PARTIAL")
        self.assertEqual(result["assets"]["SATA"]["price_usd"], None)
        self.assertTrue(all(result["assets"][a]["state"] == "VALID" for a in FOUR_ASSETS[:-1]))

    def test_unknown_symbol_currency_or_failed_request_block_only_affected_asset(self):
        for key, value in (("symbol", "STRC"), ("currency", "EUR"), ("failure_codes", [502])):
            with self.subTest(key=key):
                source = proof()
                source["assets"]["SATA"][key] = value
                result = validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])
                self.assertEqual(result["assets"]["SATA"]["state"], "BLOCKED")
                self.assertEqual(result["assets"]["STRC"]["state"], "VALID")

    def test_weekend_and_market_holiday_keep_real_previous_close_clock(self):
        for day, now in (("2026-10-09", "2026-10-11T21:00:00Z"),
                         ("2026-11-25", "2026-11-26T21:00:00Z"),
                         ("2026-07-02", "2026-07-03T21:00:00Z")):
            with self.subTest(now=now):
                at = stamp(now)
                result = validate_four_asset_daily_proof(proof(day, at), at_ms=at)
                self.assertEqual(result["state"], "VALID")
                self.assertEqual(result["assets"]["STRC"]["session_date"], day)
                self.assertLess(result["assets"]["STRC"]["as_of_ms"], at)

    def test_premarket_and_intraday_do_not_promote_partial_daily_bar(self):
        for time in ("2026-10-09T12:00:00Z", "2026-10-09T19:59:59Z"):
            with self.subTest(time=time):
                at = stamp(time)
                source = proof("2026-10-08", at)
                for row in source["assets"].values():
                    row["bars"].append({**row["bars"][0], "date": "20261009", "close": 102})
                    row["raw_data_hash"] = canonical_hash(row["bars"])
                result = validate_four_asset_daily_proof(reseal(source), at_ms=at)
                self.assertEqual(result["state"], "VALID")
                self.assertEqual(result["assets"]["MSTR"]["session_date"], "2026-10-08")

    def test_replay_cannot_complete_bar_requested_before_close(self):
        cutoff = stamp("2026-10-09T19:59:59Z")
        after = stamp("2026-10-09T20:00:01Z")
        source = proof("2026-10-09", after, cutoff)
        result = validate_four_asset_daily_proof(source, at_ms=after)
        self.assertTrue(all(row["price_usd"] is None for row in result["assets"].values()))
        source = proof("2026-10-08", cutoff)
        result = validate_four_asset_daily_proof(source, at_ms=after)
        self.assertTrue(all(row["state"] == "STALE" for row in result["assets"].values()))

    def test_early_close_and_daylight_saving_use_existing_calendar(self):
        for day, at, close in (("2026-11-27", "2026-11-27T18:00:00Z", "2026-11-27T18:00:00Z"),
                               ("2026-11-02", "2026-11-02T21:01:00Z", "2026-11-02T21:00:00Z")):
            with self.subTest(day=day):
                result = validate_four_asset_daily_proof(proof(day, stamp(at)), at_ms=stamp(at))
                self.assertEqual(result["state"], "VALID")
                self.assertEqual(result["assets"]["SATA"]["as_of_ms"], stamp(close))

    def test_weekend_holiday_future_and_intraday_labels_are_invalid(self):
        for day in ("20261010", "20260703", "20261012", "20261009 15:59:00"):
            with self.subTest(day=day):
                source = proof()
                row = source["assets"]["SATA"]
                row["bars"][0]["date"] = day
                row["raw_data_hash"] = canonical_hash(row["bars"])
                result = validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])
                self.assertEqual(result["assets"]["SATA"]["state"], "BLOCKED")
                self.assertEqual(result["assets"]["MSTR"]["state"], "VALID")

    def test_fresh_retrieval_of_old_close_is_stale(self):
        source = proof("2026-10-08")
        result = validate_four_asset_daily_proof(source, at_ms=source["observed_at_ms"])
        self.assertEqual(result["assets"]["STRC"]["state"], "STALE")
        self.assertIsNone(result["assets"]["STRC"]["price_usd"])

    def test_bad_prices_geometry_duplicates_or_volume_do_not_poison_other_assets(self):
        for key, value in (("close", 0), ("close", float("nan")), ("close", float("inf")),
                           ("close", 999), ("low", True), ("volume", -1)):
            with self.subTest(key=key, value=value):
                source = proof()
                row = source["assets"]["SATA"]
                row["bars"][0][key] = value
                row["raw_data_hash"] = canonical_hash(row["bars"])
                result = validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])
                self.assertEqual(result["assets"]["SATA"]["state"], "BLOCKED")
                self.assertEqual(result["assets"]["STRC"]["state"], "VALID")
        source = proof()
        row = source["assets"]["SATA"]
        row["bars"].append(deepcopy(row["bars"][0]))
        row["raw_data_hash"] = canonical_hash(row["bars"])
        self.assertEqual(validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])["assets"]["SATA"]["state"], "BLOCKED")

    def test_unknown_adjustment_wrong_source_or_changed_calendar_are_blocked(self):
        for field, value in (("source_id", "UNBOUND_PROVIDER"), ("calendar_hash", "0" * 64),
                             ("timezone", "UTC")):
            source = proof()
            source[field] = value
            self.assertEqual(validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])["state"], "BLOCKED")
        for field, value in (("price_adjustment_basis", "UNKNOWN"), ("use_rth", False),
                             ("bar_size", "1 min"), ("what_to_show", "ADJUSTED_LAST"),
                             ("keep_up_to_date", True)):
            with self.subTest(field=field):
                source = proof()
                source["request_contract"][field] = value
                self.assertEqual(validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])["state"], "BLOCKED")

    def test_clock_raw_hash_and_envelope_mutations_are_rejected(self):
        for field in ("observed_at_ms", "request_started_at_ms"):
            source = proof()
            source[field] += 1
            self.assertEqual(validate_four_asset_daily_proof(source, at_ms=source["observed_at_ms"])["state"], "BLOCKED")
        source = proof()
        source["assets"]["SATA"]["bars"][0]["close"] += 1
        result = validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])
        self.assertEqual(result["assets"]["SATA"]["reason"], "ASSET_RAW_HASH_MISMATCH")
        self.assertEqual(result["assets"]["MSTR"]["state"], "VALID")

    def test_unknown_clock_calendar_and_authority_fail_closed_without_external_call(self):
        with patch("crt_radar.ibkr_market_health_sources._native_history_app", side_effect=AssertionError("NO_TWS")):
            for at in (True, 0, stamp("2026-10-09T14:00:00Z"), stamp("2029-01-02T22:00:00Z")):
                self.assertEqual(validate_four_asset_daily_proof(proof(), at_ms=at)["state"], "BLOCKED")
            source = proof()
            source["external_action_authority"] = "TRADE"
            self.assertEqual(validate_four_asset_daily_proof(reseal(source), at_ms=source["observed_at_ms"])["state"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
