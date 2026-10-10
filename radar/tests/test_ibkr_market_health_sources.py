from __future__ import annotations

import unittest
from datetime import date, timedelta
from threading import Event, Lock
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from crt_radar.ibkr_market_health_sources import (
    ASSETS,
    FOUR_ASSETS,
    FOUR_DAILY_SCHEMA,
    FOUR_DAILY_SOURCE_ID,
    PRICE_BASIS,
    IbkrMarketHealthSourceError,
    _four_asset_market_calendar,
    _native_history_app,
    build_four_asset_daily_proof,
    collect_ibkr_equity_daily_proof,
    main,
    normalize_ibkr_daily_capture,
)
from crt_radar.mstr_asst_market_health_runtime import AUTHORITY, canonical_hash


MODULE = "crt_radar.ibkr_market_health_sources"
CAPTURE_MS = 1_800_000_000_000


def capture() -> dict:
    current = date(2026, 7, 27)
    sessions = []
    while len(sessions) < 22:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return {
        asset: [
            {
                "date": session.strftime("%Y%m%d"),
                "open": 100 + index,
                "high": 102 + index,
                "low": 99 + index,
                "close": 101 + index,
                "volume": 1000 + index,
            }
            for index, session in enumerate(sessions)
        ]
        for asset in ("MSTR", "ASST")
    }


class IbkrMarketHealthSourcesTests(unittest.TestCase):

    def test_normalizes_daily_history(self):
        result = normalize_ibkr_daily_capture(capture())
        self.assertEqual(result["MSTR"][0]["session_date"], "2026-07-27")
        self.assertEqual(result["ASST"][-1]["source_state"], "IBKR_HISTORICAL_TRADES_RTH")

    def test_requires_both_assets(self):
        raw = capture()
        del raw["ASST"]
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "exactly"):
            normalize_ibkr_daily_capture(raw)

    def test_requires_rvol_history(self):
        raw = capture()
        raw["MSTR"] = raw["MSTR"][:21]
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "at least 22"):
            normalize_ibkr_daily_capture(raw)

    def test_rejects_bad_bar_geometry(self):
        raw = capture()
        raw["MSTR"][0]["close"] = 500
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "geometry"):
            normalize_ibkr_daily_capture(raw)

    def test_explicit_scope_can_normalize_one_short_asset(self):
        rows = capture()["MSTR"][:1]
        result = normalize_ibkr_daily_capture(
            {"STRC": rows}, assets=("STRC",), minimum_bars=1,
        )
        self.assertEqual(set(result), {"STRC"})
        self.assertEqual(len(result["STRC"]), 1)
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "exactly"):
            normalize_ibkr_daily_capture({"STRC": rows})

    def test_rejects_nonfinite_bars_without_widening_legacy_scope(self):
        for field, value in (("open", float("inf")), ("close", float("nan")),
                             ("volume", float("inf")), ("volume", float("nan"))):
            with self.subTest(field=field, value=value):
                raw = capture()
                raw["MSTR"][0][field] = value
                with self.assertRaises(IbkrMarketHealthSourceError):
                    normalize_ibkr_daily_capture(raw)

    def test_empty_bar_date_has_controlled_error(self):
        raw = capture()
        raw["MSTR"][0]["date"] = " "
        with self.assertRaisesRegex(IbkrMarketHealthSourceError, "invalid IBKR"):
            normalize_ibkr_daily_capture(raw)


def fake_history_adapter(*, outcomes=None, ready=True, global_failure=False):
    """An in-memory SDK substitute; every connection method remains local."""
    outcomes = outcomes or {}
    instances = []

    def adapter(*, assets=ASSETS):
        class FakeApp:
            def __init__(self):
                self.ready = Event()
                self.done = {1000 + i: Event() for i in range(len(assets))}
                self.rows = {asset: [] for asset in assets}
                self.failures = []
                self.lock = Lock()
                self.requests = []
                self.disconnected = False
                instances.append(self)

            def connect(self, host, port, client_id):
                self.connection = (host, port, client_id)
                if ready:
                    self.ready.set()
                if global_failure:
                    self.failures.append({"req_id": -1, "code": 1100,
                                          "message": "global failure"})

            def run(self):
                return None

            def reqHistoricalData(self, *args):  # noqa: N802
                self.requests.append(args)
                request_id, contract = args[:2]
                outcome = outcomes.get(contract.symbol, "bars")
                if outcome == "raise":
                    raise RuntimeError("synthetic request failure")
                if outcome == "timeout":
                    return
                if outcome == "error":
                    self.failures.append({"req_id": request_id, "code": 200,
                                          "message": "synthetic asset failure"})
                elif outcome != "missing":
                    self.rows[contract.symbol] = capture()["MSTR"]
                self.done[request_id].set()

            def disconnect(self):
                self.disconnected = True

        return FakeApp, SimpleNamespace

    return adapter, instances


class FourAssetDailyProofTests(unittest.TestCase):

    def build(self, **overrides):
        payload = {
            "capture": {asset: capture()["MSTR"][:2] for asset in FOUR_ASSETS},
            "observed_at_ms": CAPTURE_MS + 1000,
            "request_started_at_ms": CAPTURE_MS,
        }
        payload.update(overrides)
        return build_four_asset_daily_proof(**payload)

    def collect(self, *, outcomes=None, four=True, ready=True, global_failure=False):
        adapter, instances = fake_history_adapter(
            outcomes=outcomes, ready=ready, global_failure=global_failure,
        )
        with patch(f"{MODULE}._native_history_app", side_effect=adapter), \
                patch(f"{MODULE}.time.time", return_value=CAPTURE_MS / 1000):
            proof = collect_ibkr_equity_daily_proof(
                four_asset_prices=four, timeout_seconds=0.001,
                observed_at_ms=CAPTURE_MS + 1000,
            )
        return proof, instances[0]

    def test_proof_binds_scope_basis_calendar_raw_bars_and_clocks(self):
        proof = self.build()
        self.assertEqual(proof["schema_version"], FOUR_DAILY_SCHEMA)
        self.assertEqual(proof["source_id"], FOUR_DAILY_SOURCE_ID)
        self.assertEqual(proof["timezone"], "America/New_York")
        self.assertEqual(proof["request_started_at_ms"], CAPTURE_MS)
        self.assertEqual(proof["request_contract"]["assets"], list(FOUR_ASSETS))
        self.assertEqual(proof["request_contract"]["price_adjustment_basis"], PRICE_BASIS)
        self.assertFalse(proof["request_contract"]["keep_up_to_date"])
        calendar = _four_asset_market_calendar()
        self.assertEqual(proof["calendar_id"], calendar["calendar_id"])
        self.assertEqual(proof["calendar_hash"], canonical_hash(calendar))
        expected = proof.pop("proof_hash")
        self.assertEqual(expected, canonical_hash(proof))
        for asset in FOUR_ASSETS:
            row = proof["assets"][asset]
            self.assertEqual(row["symbol"], asset)
            self.assertEqual(row["currency"], "USD")
            self.assertEqual(row["raw_data_hash"], canonical_hash(row["bars"]))
        for key, expected in AUTHORITY.items():
            self.assertEqual(proof[key], expected)

    def test_proof_retains_missing_asset_and_error_without_mutating_capture(self):
        rows = capture()["MSTR"][:1]
        raw = {"MSTR": rows}
        proof = self.build(capture=raw, failures=[{"req_id": 1003, "code": 200}])
        rows[0]["close"] = 1
        self.assertNotEqual(proof["assets"]["MSTR"]["bars"][0]["close"], 1)
        self.assertEqual(proof["assets"]["STRC"]["bars"], [])
        self.assertEqual(proof["assets"]["SATA"]["failure_codes"], [200])
        self.assertNotIn("state", proof)

    def test_invalid_capture_clock_or_global_failure_cannot_be_sealed(self):
        for changes in ({"request_started_at_ms": CAPTURE_MS + 2000},
                        {"observed_at_ms": True},
                        {"failures": [{"req_id": -1, "code": 1100}]},
                        {"capture": {"TSLA": []}}):
            with self.subTest(changes=changes):
                with self.assertRaises(IbkrMarketHealthSourceError):
                    self.build(**changes)

    def test_explicit_collector_requests_four_rth_daily_trade_snapshots(self):
        proof, app = self.collect()
        self.assertEqual(len(app.requests), 4)
        self.assertEqual([args[1].symbol for args in app.requests], list(FOUR_ASSETS))
        for args in app.requests:
            contract = args[1]
            self.assertEqual((contract.secType, contract.exchange, contract.currency),
                             ("STK", "SMART", "USD"))
            self.assertEqual(args[2:], ("", "2 M", "1 day", "TRADES", 1, 1, False, []))
        self.assertTrue(app.disconnected)
        self.assertEqual(proof["request_started_at_ms"], CAPTURE_MS)
        self.assertEqual(proof["observed_at_ms"], CAPTURE_MS)

    def test_failed_missing_and_timed_out_assets_preserve_other_completed_bars(self):
        for failure in ("error", "missing", "timeout", "raise"):
            with self.subTest(failure=failure):
                proof, app = self.collect(outcomes={"MSTR": failure})
                self.assertEqual(proof["assets"]["MSTR"]["bars"], [])
                expected = [] if failure == "missing" else [200 if failure == "error" else -1]
                self.assertEqual(proof["assets"]["MSTR"]["failure_codes"], expected)
                for asset in FOUR_ASSETS[1:]:
                    self.assertEqual(len(proof["assets"][asset]["bars"]), 22)
                    self.assertEqual(proof["assets"][asset]["failure_codes"], [])
                self.assertTrue(app.disconnected)

    def test_global_and_handshake_failures_remain_closed(self):
        for config in ({"global_failure": True}, {"ready": False}):
            with self.subTest(config=config):
                with self.assertRaises(IbkrMarketHealthSourceError):
                    self.collect(**config)

    def test_legacy_collector_keeps_two_asset_source_and_error_behavior(self):
        proof, app = self.collect(four=False)
        self.assertEqual(len(app.requests), 2)
        self.assertEqual(proof["source_id"], "CRT-CONN-MSTR-ASST-IBKR-EQUITY-DAILY-001")
        self.assertEqual(set(proof["data"]), set(ASSETS))
        self.assertEqual(proof["request_contract"]["assets"], list(ASSETS))
        self.assertNotIn("proof_hash", proof)
        with self.assertRaises(IbkrMarketHealthSourceError):
            self.collect(four=False, outcomes={"ASST": "error"})

    def test_cli_rejects_four_asset_options_combination_before_collection(self):
        for argv in (["collector", "--four-asset-prices", "--options-output", "options.json"],
                     ["collector", "--four-asset-prices", "--equity-output", "daily.json",
                      "--options-output", "options.json"]):
            with self.subTest(argv=argv), patch("sys.argv", argv), \
                    patch(f"{MODULE}.collect_ibkr_equity_daily_proof") as collector:
                with self.assertRaisesRegex(IbkrMarketHealthSourceError, "cannot use"):
                    main()
                collector.assert_not_called()

    def test_cli_explicit_mode_is_forwarded_without_changing_default(self):
        for extra, expected_mode in (([], False), (["--four-asset-prices"], True)):
            argv = ["collector", "--equity-output", "daily.json", *extra]
            with self.subTest(extra=extra), patch("sys.argv", argv), \
                    patch(f"{MODULE}.collect_ibkr_equity_daily_proof", return_value={}) as collector, \
                    patch(f"{MODULE}.write_json_atomic") as writer:
                self.assertEqual(main(), 0)
                self.assertEqual(collector.call_args.kwargs["four_asset_prices"], expected_mode)
                writer.assert_called_once()


class NativeHistoryCallbackTests(unittest.TestCase):

    def app(self, *, assets=FOUR_ASSETS):
        class Wrapper:
            pass

        class Client:
            def __init__(self, wrapper):
                self.wrapper = wrapper

        modules = {name: ModuleType(name) for name in
                   ("ibapi", "ibapi.client", "ibapi.wrapper", "ibapi.contract")}
        modules["ibapi.client"].EClient = Client
        modules["ibapi.wrapper"].EWrapper = Wrapper
        modules["ibapi.contract"].Contract = SimpleNamespace
        with patch.dict("sys.modules", modules):
            app_class, _ = _native_history_app(assets=assets)
            return app_class()

    def test_native_adapter_maps_only_the_requested_assets(self):
        for assets in (ASSETS, FOUR_ASSETS):
            with self.subTest(assets=assets):
                app = self.app(assets=assets)
                self.assertEqual(tuple(app.rows), assets)
                self.assertEqual(tuple(app.request_asset.values()), assets)
                self.assertEqual(len(app.done), len(assets))

    def test_legacy_and_timestamped_error_signatures_keep_fatal_asset_code(self):
        for args in ((200, "fatal"), (200, "fatal", "advanced"),
                     (CAPTURE_MS, 200, "fatal"),
                     (CAPTURE_MS, 200, "fatal", "advanced")):
            with self.subTest(args=args):
                app = self.app()
                app.error(1002, *args)
                self.assertEqual(app.failures[0]["code"], 200)
                self.assertTrue(app.done[1002].is_set())
                self.assertFalse(app.done[1000].is_set())
                app.historicalData(1000, SimpleNamespace(**capture()["MSTR"][0]))
                app.historicalDataEnd(1000, "", "")
                proof = build_four_asset_daily_proof(
                    app.rows, observed_at_ms=CAPTURE_MS,
                    request_started_at_ms=CAPTURE_MS, failures=app.failures,
                )
                self.assertEqual(proof["assets"]["STRC"]["failure_codes"], [200])
                self.assertEqual(len(proof["assets"]["MSTR"]["bars"]), 1)
                self.assertNotIn("fatal", str(proof))

    def test_informational_errors_never_end_an_asset_request(self):
        for args in ((2104, "farm ready"), (CAPTURE_MS, 2104, "farm ready"),
                     (CAPTURE_MS, 2104, "farm ready", "advanced")):
            with self.subTest(args=args):
                app = self.app()
                app.error(1000, *args)
                self.assertEqual(app.failures, [])
                self.assertFalse(app.done[1000].is_set())

    def test_malformed_error_is_retained_as_failure_without_an_informational_guess(self):
        for args in ((), (2104,), (CAPTURE_MS, 2104, 17), (True, "bad code")):
            with self.subTest(args=args):
                app = self.app()
                app.error(1003, *args)
                self.assertEqual(app.failures[0]["code"], -1)
                self.assertTrue(app.done[1003].is_set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
