from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import readonly_observation_cycle as cycle
from crt_radar.source_registry import SourceRegistry
from crt_radar.source_gate_runner import default_registry_path
from crt_radar.treasury_company_ct import (
    build_retrospective_tracker_context, build_treasury_valuation_context,
    compact_treasury_valuation_context, _digest,
)


class ReadonlyObservationCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = SourceRegistry.load(default_registry_path())
        self.url = self.registry.by_input_family("BTC_SPOT_PRICE").endpoint
        self.clock = 1_791_700_000_000

    def archive(self, fetcher):
        return cycle.PublicArchive(self.root, {}, self.registry, fetcher=fetcher, clock=lambda: self.clock)

    def response(self, raw=b'{"price":1}'):
        return dict(status_code=200, final_url=self.url, content_type="application/json",
                    body=raw, retrieved_at_ms=self.clock)

    def test_public_cache_keeps_bytes_and_original_clocks(self):
        fetch = Mock(return_value=self.response())
        a = self.archive(fetch)
        first = a.get(self.url, "BTC", self.registry.hash, refresh_ms=120_000)
        self.clock += 60_000
        restarted = cycle.PublicArchive(self.root, a.state, self.registry, fetcher=fetch, clock=lambda: self.clock)
        second = restarted.get(self.url, "BTC", self.registry.hash, refresh_ms=120_000)
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 1)
        self.assertNotEqual(second[1]["retrieved_at_ms"], self.clock)

    def test_same_content_download_preserves_first_seen(self):
        fetch = Mock(side_effect=lambda **kw: self.response())
        a = self.archive(fetch)
        first = a.get(self.url, "BTC", self.registry.hash, refresh_ms=1)
        self.clock += 10
        a.in_cycle.clear()
        second = a.get(self.url, "BTC", self.registry.hash, refresh_ms=1)
        self.assertEqual(first[1]["first_seen_at_ms"], second[1]["first_seen_at_ms"])
        self.assertEqual(second[1]["retrieved_at_ms"], first[1]["retrieved_at_ms"])
        self.assertGreater(a.requests[-1]["actual_retrieved_at_ms"], first[1]["retrieved_at_ms"])

    def test_tampered_cache_rejected_without_fetch(self):
        fetch = Mock(return_value=self.response())
        a = self.archive(fetch)
        _, artifact, _ = a.get(self.url, "BTC", self.registry.hash, refresh_ms=120_000)
        (self.root / artifact["archive_relpath"]).write_bytes(b"tampered")
        a.in_cycle.clear()
        with self.assertRaisesRegex(ValueError, "RAW_HASH"):
            a.get(self.url, "BTC", self.registry.hash, refresh_ms=120_000)
        self.assertEqual(fetch.call_count, 1)

    def test_failed_source_is_not_retried_in_cycle_or_during_backoff(self):
        fetch = Mock(side_effect=OSError("offline"))
        a = self.archive(fetch)
        for _ in range(2):
            with self.assertRaises(OSError):
                a.get(self.url, "BTC", self.registry.hash, refresh_ms=120_000)
        a.in_cycle.clear()
        with self.assertRaisesRegex(ValueError, "BACKOFF"):
            a.get(self.url, "BTC", self.registry.hash, refresh_ms=120_000)
        self.assertEqual(fetch.call_count, 1)

    def test_paid_account_and_unregistered_urls_never_reach_fetcher(self):
        fetch = Mock()
        a = self.archive(fetch)
        for url in ("https://api.openai.com/v1/responses", "https://example.org/webhook",
                    "http://127.0.0.1:7496", "https://user:secret@data-api.binance.vision/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                a.get(url, "FORBIDDEN", self.registry.hash, refresh_ms=1)
        fetch.assert_not_called()

    def test_root_overlap_fails_before_creating_files(self):
        protected = self.root / "real-runtime"
        config = dict(output_root=str(protected / "out"), protected_roots=[str(protected)])
        with self.assertRaisesRegex(ValueError, "OVERLAPS"):
            cycle.run_cycle(config)
        self.assertFalse(protected.exists())

    def test_existing_cycle_lock_prevents_all_network_calls(self):
        root = self.root / "isolated"
        root.mkdir()
        (root / ".cycle.lock").touch()
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "ALREADY_RUNNING"):
            cycle.run_cycle(dict(output_root=str(root), protected_roots=[str(self.root / "real")]), fetcher=fetch)
        fetch.assert_not_called()

    def test_tws_offline_keeps_previous_proof_and_retries_only_when_due(self):
        root = self.root
        collector = Mock(side_effect=RuntimeError("IBKR handshake timed out"))
        state = {}
        config=dict(allow_market_price_capture=True)
        first, status = cycle.collect_equities(config, root, state, self.clock, collector=collector)
        self.assertIsNone(first)
        self.assertEqual(status["state"], "TWS_OFFLINE")
        _, again = cycle.collect_equities(config, root, state, self.clock+1000, collector=collector)
        self.assertEqual(again["network_attempts"], 0)
        self.assertEqual(collector.call_count, 1)

    def test_data_conflict_is_not_claimed_to_be_offline(self):
        collector = Mock(side_effect=ValueError("conflicting daily bars"))
        _, status = cycle.collect_equities(dict(allow_market_price_capture=True), self.root, {}, self.clock, collector=collector)
        self.assertEqual(status["state"], "EQUITY_CAPTURE_BLOCKED")

    def test_default_or_false_market_capture_never_connects_to_tws(self):
        collector = Mock(side_effect=AssertionError("TWS must not be reached"))
        for config in ({}, {"allow_market_price_capture": False}):
            _, status = cycle.collect_equities(config, self.root, {}, self.clock, collector=collector)
            self.assertEqual(status["network_attempts"], 0)
        collector.assert_not_called()

    def test_failed_session_does_not_blindly_retry_after_an_hour(self):
        checked=dict(state="BLOCKED", required_session_date="2026-10-13")
        collector=Mock(side_effect=RuntimeError("handshake timed out"))
        state={}
        with patch.object(cycle, "validate_four_asset_daily_proof", return_value=checked):
            cycle.collect_equities(dict(allow_market_price_capture=True),self.root,state,self.clock,collector=collector)
            _,status=cycle.collect_equities(dict(allow_market_price_capture=True),self.root,state,self.clock+7200000,collector=collector)
        self.assertEqual(status["network_attempts"],0)
        self.assertEqual(collector.call_count,1)

    def test_explicit_market_capture_has_fixed_readonly_scope(self):
        collector = Mock(side_effect=RuntimeError("IBKR handshake timed out"))
        cycle.collect_equities(dict(allow_market_price_capture=True), self.root, {}, self.clock, collector=collector)
        collector.assert_called_once_with(host="127.0.0.1", port=7496, client_id=761,
                                         timeout_seconds=15, four_asset_prices=True)
        # This is the reused PR #143 market adapter, not the account adapter.
        source=(Path(__file__).resolve().parents[1]/"src/crt_radar/ibkr_market_health_sources.py").read_text()
        for forbidden in ("reqAccountUpdates(", "reqAccountSummary(", "reqPositions(",
                          "reqAllOpenOrders(", "placeOrder(", "cancelOrder("):
            self.assertNotIn(forbidden, source)

    def test_research_close_mark_never_becomes_a_formal_usd_price(self):
        close=1_791_600_000_000
        checked=dict(assets=dict(MSTR=dict(state="VALID", as_of_ms=close)))
        capture=Mock()
        capture.get.return_value=(json.dumps([[close-60000,"1","2","1","1.5","1",close-1]]).encode(),
            dict(sha256="a"*64,first_seen_at_ms=self.clock,retrieved_at_ms=self.clock),"application/json")
        with patch.object(cycle,"validate_four_asset_daily_proof",return_value=checked):
            mark=cycle.collect_close_mark(capture,{},self.clock)
        self.assertEqual(mark["state"], "RESEARCH_AVAILABLE")
        self.assertEqual(mark["quote_currency"], "USDT")
        self.assertEqual(mark["formal_usd_state"], "BLOCKED")
        self.assertNotIn("price_usd",mark)

    def test_missing_equity_price_does_not_erase_independent_btc_close_research(self):
        from crt_radar.mstr_asst_full_day_market_intake import _session_close_ms
        day=cycle.latest_completed_equity_session(self.clock)
        close=_session_close_ms(day,early_close_dates=frozenset(cycle._four_asset_market_calendar()['early_close_dates']))
        capture=Mock()
        capture.get.return_value=(json.dumps([[close-60000,"1","2","1","1.5","1",close-1]]).encode(),
            dict(sha256="a"*64,first_seen_at_ms=self.clock,retrieved_at_ms=self.clock),"application/json")
        mark=cycle.collect_close_mark(capture,None,self.clock)
        self.assertEqual(mark['state'],'RESEARCH_AVAILABLE')
        self.assertEqual(mark['formal_usd_state'],'BLOCKED')

    def test_new_completed_session_can_trigger_one_new_market_read(self):
        collector=Mock(side_effect=RuntimeError('handshake timed out'))
        state={}
        with patch.object(cycle,'latest_completed_equity_session',side_effect=['2026-10-13','2026-10-14']):
            cycle.collect_equities(dict(allow_market_price_capture=True),self.root,state,self.clock,collector=collector)
            cycle.collect_equities(dict(allow_market_price_capture=True),self.root,state,self.clock+86400000,collector=collector)
        self.assertEqual(collector.call_count,2)

    def test_headless_entry_finishes_without_a_console(self):
        config=self.root/'config.json';config.write_text('{}')
        result=dict(state='READ_ONLY_OBSERVATION_CYCLE_COMPLETED')
        with patch.object(cycle,'run_cycle',return_value=result),patch.object(cycle.sys,'stdout',None):
            self.assertEqual(cycle.main(['--config',str(config)]),0)

    def test_corrupt_retained_public_l4_is_recorded_without_repairing_original(self):
        path=self.root/'public-l4.json';path.write_bytes(b'{"bad":"snapshot"}')
        before=path.read_bytes()
        payload,artifact,gap=cycle.retained_liquidations(dict(liquidation_snapshot=str(path)),self.root,self.registry,self.clock)
        self.assertIsNone(payload)
        self.assertEqual(gap['input'],'liquidation_snapshot')
        self.assertEqual(path.read_bytes(),before)
        self.assertTrue(list((self.root/'artifacts').rglob('*')))

    def test_no_l4_input_does_not_touch_a_default_runtime(self):
        self.assertEqual(cycle.retained_liquidations({},self.root,self.registry,self.clock),(None,None,None))

    def test_real_pack_cycle_is_isolated_without_any_delivery_or_account_refresh(self):
        protected = self.root / "real-runtime"
        protected.mkdir()
        sentinel = protected / "pending-event.json"
        sentinel.write_bytes(b"PENDING")
        config = dict(output_root=str(self.root / "isolated"), protected_roots=[str(protected)])
        fetch = Mock(side_effect=OSError("public source unavailable"))
        collector = Mock(side_effect=RuntimeError("IBKR handshake timed out"))
        with patch.object(cycle.announcements, "_fetch_bytes", side_effect=OSError("offline")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")), \
             patch("subprocess.Popen", side_effect=AssertionError("unexpected process")):
            result = cycle.run_cycle(config, fetcher=fetch, equity_collector=collector)
        self.assertEqual(sentinel.read_bytes(), b"PENDING")
        self.assertEqual(list(protected.iterdir()), [sentinel])
        output = Path(result["cycle_path"])
        pack = cycle.read_json(output / "evidence-pack.json")
        analysis = cycle.read_json(output / "capital-analysis-input.json")
        self.assertEqual(pack["evidence_pack_hash"], _digest({k:v for k,v in pack.items() if k != "evidence_pack_hash"}))
        self.assertFalse(analysis["model_request_performed"])
        self.assertEqual(result["account_refreshes"], 0)
        self.assertIsNone(pack["formal_candidate"].get("formal_season"))
        self.assertFalse(any(p.name in {"outbox", "transport", "notifications"} for p in output.parent.parent.rglob("*")))


class RetrospectiveTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1_791_800_000_000
        dates = [(datetime(2026, 8, 1)+timedelta(days=i)).date().isoformat() for i in range(50)]
        self.history = dict(dates=dates, stock_prices=[100+i for i in range(50)],
            btc_prices=[10000]*50, btc_balance=[1000]*50,
            diluted_shares_outstanding=[200000]*50, effective_diluted_shares=[150000]*50)
        self.url = "https://data.strategytracker.com/MSTR.v20260922T100410Z.json"
        self.store()

    def store(self):
        raw=json.dumps(dict(timestamp="2026-09-22T10:03:37Z", companies=dict(MSTR=dict(historicalData=self.history,
            currencyMetadata=dict(originalCurrency="USD",targetCurrency="USD",conversionApplied=False,isGbxDisplay=False))))).encode()
        (self.root / "MSTR-tracker-raw.json").write_bytes(raw)
        (self.root / "source-manifest.json").write_text(json.dumps(dict(MSTR=dict(
            url=self.url, sha256=hashlib.sha256(raw).hexdigest(), snapshot_timestamp="2026-09-22T10:03:37Z",
            history_exclusion="No historical first-seen proof"))))
        (self.root / "valuation-inputs.json").write_text(json.dumps(dict(MSTR=dict(mnav_history=[dict(
            source_ref=self.url, retrieval_time=self.now-1000, first_seen_time=self.now-1000)]))))

    def build(self):
        return build_retrospective_tracker_context(self.root, asset_id="MSTR", as_of_ms=self.now)

    def test_two_reported_share_columns_have_separate_research_distributions(self):
        result=self.build()
        self.assertEqual(result["state"], "RESEARCH_AVAILABLE")
        self.assertEqual(result["formal_action_critical_state"], "BLOCKED")
        nominal=result["series"]["diluted_shares_outstanding"]
        effective=result["series"]["effective_diluted_shares"]
        self.assertEqual(nominal["current"]["mnav"], 200000*149/(1000*10000))
        self.assertNotEqual(nominal["current"]["mnav"], effective["current"]["mnav"])
        self.assertEqual(nominal["own_history_empirical_cdf_pct"]["value"], 100)
        self.assertAlmostEqual(nominal["five_week_mnav_change_pct"]["value"], 149/114-1)
        self.assertEqual(result["original_retrieval_time"], self.now-1000)
        self.assertEqual(result["historical_visibility"], "NOT_PROVEN_NOT_A_FORWARD_PREDICTION")

    def test_unknown_last_components_do_not_revive_previous_value(self):
        self.history["btc_balance"][-1]=None
        self.store()
        result=self.build()
        self.assertEqual(result["state"], "BLOCKED")
        self.assertTrue(all(r["current"] is None for r in result["series"].values()))

    def test_overflow_and_underflow_are_not_valid_research_ratios(self):
        self.history["stock_prices"][-1]=1e308
        self.store()
        self.assertEqual(self.build()["state"],"BLOCKED")
        self.history["stock_prices"][-1]=1e-308
        self.history["btc_prices"][-1]=1e308
        self.store()
        self.assertEqual(self.build()["state"],"BLOCKED")

    def test_hash_mismatch_blocks_only_research(self):
        (self.root / "MSTR-tracker-raw.json").write_bytes(b"tampered")
        self.assertEqual(self.build()["reason"], "TRACKER_RAW_HASH_MISMATCH")

    def test_missing_or_unequal_arrays_do_not_zero_fill(self):
        self.history["btc_prices"] = self.history["btc_prices"][:-1]
        self.store()
        self.assertEqual(self.build()["state"], "BLOCKED")

    def test_unproven_currency_is_not_labeled_usd(self):
        path=self.root/"MSTR-tracker-raw.json"
        payload=json.loads(path.read_bytes())
        payload['companies']['MSTR']['currencyMetadata']['originalCurrency']='GBP'
        raw=json.dumps(payload).encode();path.write_bytes(raw)
        manifest=json.loads((self.root/'source-manifest.json').read_bytes())
        manifest['MSTR']['sha256']=hashlib.sha256(raw).hexdigest()
        (self.root/'source-manifest.json').write_text(json.dumps(manifest))
        self.assertEqual(self.build()["reason"],"TRACKER_USD_PRICE_BASIS_UNPROVEN")

    def test_original_source_time_is_not_replaced_by_evaluation_time(self):
        original=self.build()
        later=build_retrospective_tracker_context(self.root,asset_id="MSTR",as_of_ms=self.now+86400000)
        self.assertEqual(original["original_retrieval_time"],later["original_retrieval_time"])
        self.assertEqual(original["series"],later["series"])

    def test_duplicate_or_reversed_dates_fail(self):
        for dates in (self.history["dates"][::-1], self.history["dates"][:-1]+[self.history["dates"][-2]]):
            self.history["dates"]=dates
            self.store()
            self.assertEqual(self.build()["state"], "BLOCKED")

    def test_research_reaches_existing_treasury_projection_without_formal_promotion(self):
        research=self.build()
        context=build_treasury_valuation_context(asset_id="MSTR", as_of_ms=self.now,
                                                retrospective_research=research)
        projection=compact_treasury_valuation_context(dict(asset_facts=dict(items=[dict(
            fact_type="TREASURY_VALUATION_CONTEXT", evidence=context)])))
        self.assertEqual(projection["MSTR"]["retrospective_research"], research)
        self.assertIsNone(projection["MSTR"]["diluted_mnav"])
        self.assertEqual(projection["MSTR"]["formal_action_critical_state"], "BLOCKED")

    def test_cross_asset_or_clock_rebinding_is_rejected(self):
        research=self.build()
        with self.assertRaisesRegex(ValueError, "CONTRACT_INVALID"):
            build_treasury_valuation_context(asset_id="ASST", as_of_ms=self.now, retrospective_research=research)
        with self.assertRaisesRegex(ValueError, "CONTRACT_INVALID"):
            build_treasury_valuation_context(asset_id="MSTR", as_of_ms=self.now+1, retrospective_research=research)


if __name__ == "__main__":
    unittest.main()
