from __future__ import annotations

import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from crt_radar.ibkr_live_market_data_intake import (
    ASSET_ORDER, SOURCE_ID, IbkrIntakeConfig, IbkrIntakeError,
    _native_feed_app, build_ibkr_equity_live_snapshot,
)
from crt_radar.ibkr_commander_observation import IbkrCommanderObservationBridge
from crt_radar.ibkr_observation_journal import IbkrObservationJournal, JournaledIbkrObservationSink
from crt_radar.premarket_equity_live_snapshot import (
    equity_snapshot_to_asset_market, seal_equity_live_snapshot, validate_equity_live_snapshot,
)
from test_ibkr_live_market_data_intake import (
    _capture, _premarket_ms, _ProofSink, load_ibkr_source_registry,
    build_equity_source_binding, REGISTRY_PATH, OVERLAY_PATH,
)
from test_ibkr_commander_observation import NOW, NOW_MS, CURRENT_MAIN_SHA, verified_test_plan


def native_app(sink):
    class Wrapper:
        pass

    class Client:
        def __init__(self, wrapper):
            pass

    class Contract:
        pass

    modules = {name: ModuleType(name) for name in (
        "ibapi", "ibapi.client", "ibapi.wrapper", "ibapi.contract",
    )}
    modules["ibapi.client"].EClient = Client
    modules["ibapi.wrapper"].EWrapper = Wrapper
    modules["ibapi.contract"].Contract = Contract
    with patch.dict(sys.modules, modules):
        cls, _ = _native_feed_app(sink)
        app = cls()
    for index, asset in enumerate(ASSET_ORDER):
        app.request_map[1000 + index] = (asset, "L1")
        app.request_map[2000 + index] = (asset, "BAR_5S")
        app.marketDataType(1000 + index, 1)
    return app


def deliver_bar(app, start_ms, received_ms, *, price=100.1, volume=10, count=1, req_id=2000):
    with patch("crt_radar.ibkr_live_market_data_intake.time.time", return_value=received_ms / 1000):
        app.realtimeBar(req_id, start_ms // 1000, price, price, price, price, volume, price, count)


def deliver_rt(app, trade_ms, received_ms, *, price=100.1, size=1):
    with patch("crt_radar.ibkr_live_market_data_intake.time.time", return_value=received_ms / 1000):
        app.tickString(1000, 48, f"{price};{size};{trade_ms};1000;100;true")


class IbkrTradeClockTests(unittest.TestCase):
    def setUp(self):
        self.clock = _premarket_ms()
        self.registry = load_ibkr_source_registry(REGISTRY_PATH, OVERLAY_PATH)
        self.binding = build_equity_source_binding(self.registry, source_id=SOURCE_ID)
        self.config = IbkrIntakeConfig(duration_seconds=5)

    def snapshot(self, capture, *, retrieved=None):
        return build_ibkr_equity_live_snapshot(
            capture, source_binding=self.binding, config=self.config,
            retrieved_at_ms=self.clock + 1000 if retrieved is None else retrieved,
        )

    def test_zero_bars_keep_exact_rt_price_time_and_capture_audit(self):
        capture = _capture()
        row = capture["assets"]["STRC"]
        row["rt_volume"]["trade_at_ms"] = self.clock - 10_000
        row["bars_5s"][0].update(volume=0, count=0, close=93.9)
        row["bars_5s"][0].update(open=93.9, high=93.9, low=93.9)
        before = deepcopy(capture)
        snapshot = self.snapshot(capture)
        result = snapshot["assets"]["STRC"]
        self.assertEqual(result["premarket_price"], 94)
        self.assertEqual(result["trade_evidence"]["trade_at_ms"], self.clock - 10_000)
        self.assertEqual(result["real_time_bars_5s"]["state"], "BLOCKED")
        self.assertEqual(len(result["real_time_bars_5s"]["items"]), 1)
        self.assertEqual(capture, before)

    def test_zero_bar_only_with_bid_ask_last_quotes_is_blocked(self):
        capture = _capture()
        row = capture["assets"]["SATA"]
        row["rt_volume"] = None
        row["bars_5s"][0].update(volume=0, count=0)
        with self.assertRaisesRegex(IbkrIntakeError, "no qualified"):
            self.snapshot(capture)

    def test_positive_bar_only_keeps_interval_without_inventing_trade_time(self):
        capture = _capture()
        for row in capture["assets"].values():
            row["rt_volume"] = None
        snapshot = self.snapshot(capture)
        for row in snapshot["assets"].values():
            trade = row["trade_evidence"]
            self.assertEqual(trade["source"], "BAR_5S")
            self.assertIsNone(trade["trade_at_ms"])
            self.assertIsNone(row["l1_streaming"]["observed_trade_at_ms"])
            self.assertEqual(trade["bar_start_at_ms"], self.clock - 5000)
            self.assertEqual(trade["bar_end_at_ms"], self.clock)
            self.assertEqual(trade["received_at_ms"], self.clock + 150)
        window = {"start_ms": self.clock - 120_000, "end_ms": self.clock + 1000}
        market = equity_snapshot_to_asset_market(snapshot, source_binding=self.binding, evaluation_window=window)
        ref = market["MSTR"]["premarket_price"]["source_refs"][0]
        self.assertEqual(ref["price_time_semantics"], "TRADE_TIME_WITHIN_5S_BAR_ONLY")
        self.assertIsNone(ref["trade_at_ms"])
        self.assertEqual(market["MSTR"]["observed_at_ms"], self.clock - 5000)

    def test_invalid_volume_count_preserve_diagnostics_and_cannot_override_rt(self):
        cases = [(None, 1), (-1, 1), (float("nan"), 1), (float("inf"), 1),
                 (True, 1), (0, 1), (1, 0), (1, None), (1, -1), (1, 1.5), (1, True)]
        for volume, count in cases:
            with self.subTest(volume=volume, count=count):
                capture = _capture()
                capture["assets"]["MSTR"]["bars_5s"][0].update(volume=volume, count=count)
                result = self.snapshot(capture)["assets"]["MSTR"]
                self.assertEqual(result["premarket_price"], 125)
                self.assertEqual(result["trade_evidence"]["source"], "RT_VOLUME")
                self.assertTrue(result["trade_diagnostics"])
                capture["assets"]["MSTR"]["rt_volume"] = None
                with self.assertRaisesRegex(IbkrIntakeError, "no qualified"):
                    self.snapshot(capture)

    def test_future_incomplete_or_missing_bar_reception_is_not_evidence(self):
        cases = [{"time_s": self.clock // 1000 + 1},
                 {"received_at_ms": self.clock - 1}, {"received_at_ms": None},
                 {"received_at_ms": self.clock + 1001}]
        for changes in cases:
            with self.subTest(changes=changes):
                capture = _capture()
                capture["assets"]["MSTR"]["bars_5s"][0].update(changes)
                row = self.snapshot(capture)["assets"]["MSTR"]
                self.assertEqual(row["trade_evidence"]["source"], "RT_VOLUME")
                self.assertTrue(row["trade_diagnostics"])

    def test_invalid_rt_clocks_do_not_manufacture_last_from_quotes(self):
        cases = [{"trade_at_ms": None}, {"trade_at_ms": self.clock + 1001},
                 {"received_at_ms": None}, {"received_at_ms": self.clock - 1},
                 {"price": None}, {"size": -1}, {"single_trade": "true"}]
        for changes in cases:
            with self.subTest(changes=changes):
                capture = _capture()
                row = capture["assets"]["MSTR"]
                row["bars_5s"] = []
                row["rt_volume"].update(changes)
                with self.assertRaisesRegex(IbkrIntakeError, "no qualified"):
                    self.snapshot(capture)

    def test_fresh_zero_bars_do_not_refresh_stale_rt_trade(self):
        capture = _capture()
        row = capture["assets"]["MSTR"]
        row["rt_volume"]["trade_at_ms"] = self.clock - 121_000
        row["bars_5s"][0].update(volume=0, count=0)
        with self.assertRaisesRegex(IbkrIntakeError, "stale"):
            self.snapshot(capture)

    def test_stale_positive_bar_cannot_be_made_fresh_by_reception(self):
        capture = _capture()
        row = capture["assets"]["MSTR"]
        row["rt_volume"] = None
        row["bars_5s"][0]["time_s"] = (self.clock - 121_000) // 1000
        with self.assertRaisesRegex(IbkrIntakeError, "stale"):
            self.snapshot(capture)

    def test_older_rt_then_newer_trade_bar_selects_interval_price(self):
        capture = _capture()
        row = capture["assets"]["MSTR"]
        row["rt_volume"]["trade_at_ms"] = self.clock - 6000
        row["rt_volume"]["price"] = 124
        result = self.snapshot(capture)["assets"]["MSTR"]
        self.assertEqual(result["premarket_price"], 125)
        self.assertEqual(result["trade_evidence"]["source"], "BAR_5S")
        self.assertIsNone(result["trade_evidence"]["trade_at_ms"])

    def test_later_rt_is_selected_even_when_bar_is_received_later(self):
        capture = _capture()
        row = capture["assets"]["MSTR"]
        row["rt_volume"].update(price=124, trade_at_ms=self.clock + 100, received_at_ms=self.clock + 200)
        row["bars_5s"][0]["received_at_ms"] = self.clock + 900
        result = self.snapshot(capture)["assets"]["MSTR"]
        self.assertEqual(result["premarket_price"], 124)
        self.assertEqual(result["trade_evidence"]["trade_at_ms"], self.clock + 100)

    def test_equal_start_or_overlapping_rt_keeps_exact_clock_only_if_prices_agree(self):
        for rt_time in (self.clock - 5000, self.clock - 2000):
            with self.subTest(rt_time=rt_time):
                capture = _capture()
                capture["assets"]["MSTR"]["rt_volume"]["trade_at_ms"] = rt_time
                row = self.snapshot(capture)["assets"]["MSTR"]
                self.assertEqual(row["trade_evidence"]["trade_at_ms"], rt_time)
                capture["assets"]["MSTR"]["rt_volume"]["price"] = 124
                with self.assertRaisesRegex(IbkrIntakeError, "order unresolved"):
                    self.snapshot(capture)

    def test_asset_source_clocks_survive_evidence_projection(self):
        capture = _capture()
        capture["assets"]["STRC"]["bars_5s"][0].update(volume=0, count=0)
        capture["assets"]["STRC"]["rt_volume"]["trade_at_ms"] = self.clock - 20_000
        snapshot = self.snapshot(capture)
        market = equity_snapshot_to_asset_market(snapshot, source_binding=self.binding,
            evaluation_window={"start_ms": self.clock - 120_000, "end_ms": self.clock + 1000})
        self.assertEqual(market["STRC"]["observed_at_ms"], self.clock - 20_000)
        self.assertEqual(market["MSTR"]["observed_at_ms"], self.clock)

    def test_resealed_forged_bar_exact_clock_or_missing_ibkr_clock_is_rejected(self):
        snapshot = self.snapshot(_capture())
        for mode in ("missing", "bar_exact"):
            with self.subTest(mode=mode):
                bad = deepcopy(snapshot)
                bad.pop("snapshot_hash")
                if mode == "missing":
                    for row in bad["assets"].values():
                        row.pop("trade_evidence")
                else:
                    trade = bad["assets"]["MSTR"]["trade_evidence"]
                    trade.update(source="BAR_5S", time_semantics="TRADE_TIME_WITHIN_5S_BAR_ONLY",
                                 bar_start_at_ms=self.clock, bar_end_at_ms=self.clock + 5000)
                with self.assertRaises(ValueError):
                    validate_equity_live_snapshot(seal_equity_live_snapshot(bad), source_binding=self.binding,
                        evaluation_window={"start_ms": self.clock - 120_000, "end_ms": self.clock + 1000})

    def test_zero_and_invalid_native_bars_never_notify_but_are_audited(self):
        cases = [(0, 0), (0, 1), (1, 0), (None, 1), (-1, 1), (1, -1), (1, 1.5), (1, True)]
        for volume, count in cases:
            with self.subTest(volume=volume, count=count):
                sink = _ProofSink()
                app = native_app(sink)
                deliver_bar(app, self.clock, self.clock + 6000, volume=volume, count=count)
                self.assertEqual(sink.observations, [])
                self.assertEqual(len(app.assets["MSTR"]["bars_5s"]), 1)
                self.assertEqual(app.assets["MSTR"]["bars_5s"][0]["count"], count)

    def test_native_positive_bar_uses_close_boundary_not_receipt_or_trade_clock(self):
        sink = _ProofSink()
        app = native_app(sink)
        deliver_bar(app, self.clock, self.clock + 7000)
        self.assertEqual(sink.observations[0][:4], ("BAR_5S_CLOSE", "MSTR", 100.1, self.clock + 5000))
        self.assertNotIn("trade_at_ms", app.assets["MSTR"]["bars_5s"][0])

    def test_native_future_and_stale_bars_are_suppressed(self):
        for start_ms in (self.clock + 10_000, self.clock - 121_000):
            with self.subTest(start_ms=start_ms):
                sink = _ProofSink()
                app = native_app(sink)
                deliver_bar(app, start_ms, self.clock + 1000)
                self.assertEqual(sink.observations, [])
                self.assertTrue(app.assets["MSTR"]["trade_diagnostics"])

    def test_untimestamped_last_quote_never_notifies_commander(self):
        sink = _ProofSink()
        app = native_app(sink)
        for tick in (1, 2, 4):
            app.tickPrice(1000, tick, 100.5, None)
        self.assertEqual(sink.observations, [])
        self.assertEqual(app.assets["MSTR"]["l1"]["last"], 100.5)

    def test_rt_order_duplicates_and_conflicts_do_not_replace_true_clock(self):
        sink = _ProofSink()
        app = native_app(sink)
        deliver_rt(app, self.clock, self.clock + 1000, price=100)
        deliver_rt(app, self.clock - 1000, self.clock + 2000, price=99)
        deliver_rt(app, self.clock, self.clock + 3000, price=100)
        self.assertEqual(len(sink.observations), 1)
        self.assertEqual(sink.observations[0][3], self.clock)
        self.assertEqual(app.assets["MSTR"]["rt_volume"]["price"], 100)
        deliver_rt(app, self.clock, self.clock + 4000, price=101)
        self.assertEqual(len(sink.observations), 1)
        self.assertEqual(app.assets["MSTR"]["rt_volume_conflict_at_ms"], self.clock)
        deliver_rt(app, self.clock + 1000, self.clock + 5000, price=102)
        self.assertEqual(len(sink.observations), 2)
        self.assertIsNone(app.assets["MSTR"]["rt_volume_conflict_at_ms"])

    def test_old_bar_after_new_rt_cannot_move_commander_clock_backwards(self):
        sink = _ProofSink()
        app = native_app(sink)
        deliver_rt(app, self.clock + 6000, self.clock + 7000)
        deliver_bar(app, self.clock, self.clock + 8000)
        self.assertEqual(len(sink.observations), 1)
        deliver_bar(app, self.clock + 5000, self.clock + 11_000)
        deliver_rt(app, self.clock + 8000, self.clock + 12_000)
        self.assertEqual([row[3] for row in sink.observations], [self.clock + 6000, self.clock + 10_000])

    def test_older_bar_received_later_and_repeated_bar_do_not_duplicate_events(self):
        sink = _ProofSink()
        app = native_app(sink)
        deliver_bar(app, self.clock + 5000, self.clock + 11_000)
        deliver_bar(app, self.clock, self.clock + 12_000)
        deliver_bar(app, self.clock + 5000, self.clock + 13_000)
        self.assertEqual(len(sink.observations), 1)
        self.assertEqual(sink.observations[0][3], self.clock + 10_000)
        self.assertEqual(len(app.assets["MSTR"]["bars_5s"]), 3)

    def test_rt_zero_size_odd_lot_is_not_misclassified_as_zero_trade_bar(self):
        sink = _ProofSink()
        app = native_app(sink)
        deliver_rt(app, self.clock, self.clock + 1000, size=0)
        self.assertEqual(len(sink.observations), 1)
        self.assertEqual(sink.observations[0][3], self.clock)

    def test_invalid_and_stale_rt_ticks_are_diagnosed_without_new_events(self):
        for raw in (f"100;1;{self.clock + 2000};1000;100;true",
                    f"100;1;{self.clock - 121_000};1000;100;true",
                    f"100;1;{self.clock};1000;100;unknown", "broken"):
            with self.subTest(raw=raw):
                sink = _ProofSink()
                app = native_app(sink)
                with patch("crt_radar.ibkr_live_market_data_intake.time.time", return_value=(self.clock + 1000)/1000):
                    app.tickString(1000, 48, raw)
                self.assertEqual(sink.observations, [])
                self.assertIsNone(app.assets["MSTR"]["rt_volume"])
                self.assertTrue(app.assets["MSTR"]["trade_diagnostics"])

    def test_zero_bars_cannot_enter_journal_or_wake_verified_commander(self):
        plan = verified_test_plan()
        bridge = IbkrCommanderObservationBridge.arm(plan, current_main_sha=CURRENT_MAIN_SHA, now=NOW)
        with tempfile.TemporaryDirectory() as temp:
            with IbkrObservationJournal(Path(temp)/"journal.sqlite3", plan_sha=plan["plan_sha"], asset="MSTR") as journal:
                app = native_app(JournaledIbkrObservationSink(journal, bridge))
                deliver_rt(app, NOW_MS, NOW_MS + 1000, price=99.60)
                for index in range(6):
                    deliver_bar(app, NOW_MS + index*5000, NOW_MS + (index+1)*5000 + 1000,
                                volume=0, count=0, price=100.30)
                self.assertEqual(len(journal.records_after(0)), 1)
                self.assertEqual(bridge.bar_close_observation_count, 0)
                self.assertEqual(bridge.events, ())
                self.assertIsNone(bridge.latest_reanalysis_wake())
                self.assertEqual(len(app.assets["MSTR"]["bars_5s"]), 6)

    def test_qualified_trades_still_journal_confirm_and_wake_without_duplicates(self):
        plan = verified_test_plan()
        bridge = IbkrCommanderObservationBridge.arm(plan, current_main_sha=CURRENT_MAIN_SHA, now=NOW)
        with tempfile.TemporaryDirectory() as temp:
            with IbkrObservationJournal(Path(temp)/"journal.sqlite3", plan_sha=plan["plan_sha"], asset="MSTR") as journal:
                app = native_app(JournaledIbkrObservationSink(journal, bridge))
                for offset, price in ((0,99.60),(1000,99.85),(2000,100.02)):
                    deliver_rt(app, NOW_MS + offset, NOW_MS + offset + 100, price=price)
                for index, price in enumerate((100.03,100.04,99.99,100.05),start=1):
                    end = NOW_MS + 2000 + index*5000
                    deliver_bar(app, end - 5000, end + 1000, price=price)
                event_count = len(bridge.events)
                deliver_bar(app, end - 5000, end + 2000, price=100.05)
                self.assertEqual(len(journal.records_after(0)), 7)
                self.assertEqual(len(bridge.events), event_count)
                attack = [event["event_type"] for event in bridge.events if event["line_id"] == "test-attack"]
                self.assertIn("CROSS_RAW", attack)
                self.assertIn("ACCEPTED", attack)
                wake = bridge.latest_reanalysis_wake()
                self.assertEqual(wake["state"], "REANALYSIS_REQUESTED")
                self.assertEqual(wake["action_output"], "NONE")
                self.assertEqual(wake["external_action_authority"], "NONE")
                self.assertEqual(wake["production"], "NOT_APPROVED")
                journal.validate()


if __name__ == "__main__":
    unittest.main()
