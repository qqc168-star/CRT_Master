"""Synthetic vectors only; real archive acceptance is performed separately."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crt_radar.daily_quantitative_report import build_report, build_report_from_store, render_markdown, _reference_date
from crt_radar.btc_tactical_forecast import content_hash, freeze_pre, freeze_post, PRE
from crt_radar.evidence_pack import build_evidence_pack
from crt_radar import btc_etf_intake as etf
from test_first_evidence_slice import gate
from test_treasury_valuation_context import metadata, observation, NOW, DAY_MS
from test_treasury_company_ct import kwargs as ct_kwargs
from test_btc_etf_intake import TICKERS, envelope


def seal(p):
    p.pop("evidence_pack_hash",None)
    p["evidence_pack_hash"]=content_hash(p)
    return p


def pack(now=NOW):
    with tempfile.TemporaryDirectory() as d:
        return build_evidence_pack(gate(0),observation_db=Path(d)/"pack.db",generated_at_ms=now)


def source(at=NOW, **changes):
    row=dict(source_id="TEST_SOURCE",source_ref="synthetic:only", validation_ref="synthetic:validated",
        evidence_hash="a"*64, observed_at_ms=at-4,available_at_ms=at-3,
        retrieved_at_ms=at-2,validated_at_ms=at-1,quality_state="RESEARCH_ONLY",valid_until_ms=at+DAY_MS,currency="USD")
    row.update(changes)
    return row


def metric(report, name):
    return next(r for r in report["rows"] if r["metric"]==name)


class DailyQuantitativeReportTests(unittest.TestCase):
    def test_existing_fred_levels_are_sealed_facts_without_dxy_or_nominal_10y_substitution(self):
        from crt_radar.source_registry import SourceRegistry
        from crt_radar.source_gate_runner import parse_macro_context, parse_rates_context, default_registry_path
        from layer_fixtures import supplemental_overrides
        registry=SourceRegistry.load(default_registry_path())
        overrides=supplemental_overrides(registry,NOW)
        g=gate(0);refs=[]
        for family,parser in (("MACRO_CONTEXT",parse_macro_context),("RATES_CONTEXT",parse_rates_context)):
            spec=registry.by_input_family(family)
            parsed=parser(overrides[spec.source_id].payload)
            g["parsed"][family]=parsed
            g["evidence"].append(dict(input_family=family,source_id=spec.source_id,namespace=spec.namespace,
                quality_state="VALID_FRESH",evidence_hash="c"*64,registry_hash=g["source_registry_hash"],as_of_ms=parsed["as_of_ms"]))
            for field in (("effective_fed_funds_rate_pct","effective_fed_funds_change_bp") if family=="MACRO_CONTEXT"
                    else ("broad_usd_index","real_10y_yield_pct","nominal_2y_yield_pct")):
                observed=parsed["fed_funds_observed_at_ms"] if family=="MACRO_CONTEXT" else parsed["level_observed_at_ms"][field]
                if not any(r["source_id"]==spec.source_id and r["observed_at_ms"]==observed for r in refs):
                    refs.append(source(NOW,source_id=spec.source_id,source_ref="synthetic:"+family+str(observed),
                        observed_at_ms=observed,available_at_ms=NOW-3,retrieved_at_ms=NOW-2,
                        validated_at_ms=NOW-1,evidence_hash="c"*64))
        with tempfile.TemporaryDirectory() as d:
            p=build_evidence_pack(g,observation_db=Path(d)/"macro.db",generated_at_ms=NOW)
        facts=[r for r in p["asset_facts"]["items"] if r.get("fact_type")=="MACRO_REPORTED_LEVEL"]
        self.assertEqual(len(facts),5)
        self.assertTrue(all(r["formal_model_input"] is False for r in facts))
        r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],sources=refs),generated_at_ms=NOW)
        self.assertEqual(metric(r,"effective_fed_funds_rate_pct")["value"],4.5)
        self.assertEqual(metric(r,"effective_fed_funds_change_bp")["value"],0)
        self.assertAlmostEqual(metric(r,"nominal_2y_yield_pct")["value"],3.52)
        self.assertIsNone(metric(r,"DXY")["value"])
        self.assertIsNone(metric(r,"10Y nominal yield")["value"])

    def test_existing_reserve_nonoverlap_gate_not_replaced_by_report_arithmetic(self):
        from test_treasury_company_ct import burden,T2
        from crt_radar.treasury_company_ct import add_treasury_company_ct
        for separate in (False,True):
            data=ct_kwargs()
            cash=burden()
            cash.update(usd_reserve_usd=50,usd_cash_usable_for_carry=True,cash_usability_basis_ref="synthetic-carry",
                reserve_usable_for_carry=True,reserve_separate_from_cash=separate)
            data.update(issuer_id="CIK-0001920406",burden_current=cash)
            data["burden_current"]["issuer_id"]="CIK-0001920406"
            p=pack(T2);add_treasury_company_ct(p,data);seal(p)
            r=build_report(p,generated_at_ms=T2)
            value=metric(r,"usable_liquidity_usd")["value"]
            if separate: self.assertEqual(value,150)
            else: self.assertTrue(value is None or value<=100)
            self.assertEqual(metric(r,"BTC pressure comparison")["qualification"],"NOT_RUN")

    def test_repeatable_read_only_pack_and_values_with_full_provenance(self):
        p=pack()
        ref=source()
        p["layers"]={"L6":{"metrics":{"btc_spot_price_usd":dict(value=80000,
            source_id=ref["source_id"],evidence_hash=ref["evidence_hash"],as_of_ms=ref["observed_at_ms"],quality_state="VALID")}}}
        seal(p); original=deepcopy(p)
        ctx=dict(evidence_pack_hash=p["evidence_pack_hash"], sources=[ref])
        r=build_report(p,context=ctx,generated_at_ms=NOW)
        self.assertEqual(r,build_report(p,context=ctx,generated_at_ms=NOW))
        self.assertEqual(p,original)
        self.assertEqual(metric(r,"btc_spot_price_usd")["value"],80000)
        self.assertEqual(metric(r,"btc_spot_price_usd")["evidence"][0]["available_at_ms"],ref["available_at_ms"])
        self.assertEqual(metric(r,"SOPR")["qualification"],"BLOCKED")
        self.assertEqual(r["action_output"],"NONE")
        self.assertEqual(r["formal_season"],None)
        self.assertEqual(r["cloud_shared_access"],"BLOCKED")
        self.assertEqual(r["cloud_two_task_read_write"],"NOT_RUN")

    def test_stale_price_unknown_source_and_wrong_clocks_cannot_promote(self):
        p=pack(); ref=source()
        p["layers"]={"L6":{"metrics":{"btc_spot_price_usd":dict(value=80000,
            source_id=ref["source_id"],evidence_hash=ref["evidence_hash"],as_of_ms=ref["observed_at_ms"],quality_state="VALID")}}}
        seal(p)
        for change in ({"valid_until_ms":NOW},{"quality_state":"STALE"},{"evidence_hash":"b"*64}):
            with self.subTest(change=change):
                ctx=dict(evidence_pack_hash=p["evidence_pack_hash"],sources=[{**ref,**change}])
                r=build_report(p,context=ctx,generated_at_ms=NOW)
                self.assertIsNone(metric(r,"btc_spot_price_usd")["value"])
        with self.assertRaisesRegex(ValueError,"CLOCK_ORDER"):
            build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],sources=[{**ref,"available_at_ms":NOW-1}]),generated_at_ms=NOW)
        with self.assertRaisesRegex(ValueError,"PACK_MISMATCH"):
            build_report(p,context={"evidence_pack_hash":"b"*64},generated_at_ms=NOW)
        p["layers"]["L6"]["metrics"]["btc_spot_price_usd"]["value"]=1
        with self.assertRaisesRegex(ValueError,"HASH_INVALID"): build_report(p,generated_at_ms=NOW)

    def test_weekly_completed_acquisition_set_does_not_expand_on_replay(self):
        at=int(datetime(2026,10,26,12,tzinfo=timezone.utc).timestamp()*1000)
        latest=datetime(2026,10,25,23,59,59,tzinfo=timezone.utc)
        bars=[dict(week_closed_at=(latest-timedelta(weeks=200-i)).isoformat(),
            available_at=(latest-timedelta(weeks=200-i)+timedelta(seconds=1)).isoformat(),
            is_complete=True,close=100+i) for i in range(201)]
        bars.append(dict(week_closed_at=(latest+timedelta(weeks=1)).isoformat(),
            available_at=(latest+timedelta(weeks=1,seconds=1)).isoformat(),is_complete=False,close=99999))
        raw=json.dumps(bars)
        ref=source(at,observed_at_ms=at-1000,evidence_hash=hashlib.sha256(raw.encode()).hexdigest())
        for cutoff in (at,at+10*DAY_MS):
            p=pack(cutoff)
            r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],weekly_archive={"raw_json":raw,"source":ref}),generated_at_ms=cutoff)
            self.assertEqual(metric(r,"weekly close")["value"],300)
            self.assertEqual(metric(r,"50WMA")["value"],275.5)
            self.assertEqual(metric(r,"200WMA")["value"],200.5)
            self.assertEqual(metric(r,"RSI(14)")["value"],100)
        self.assertEqual(metric(r,"50WMA")["qualification"],"STALE")
        bars[-1]["is_complete"]=True
        raw=json.dumps(bars); ref["evidence_hash"]=hashlib.sha256(raw.encode()).hexdigest()
        r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],weekly_archive={"raw_json":raw,"source":ref}),generated_at_ms=cutoff)
        self.assertIn("COMPLETION_NOT_VISIBLE",metric(r,"weekly archive")["reason"])

    def test_formal_mnav_substitution_and_research_trial_never_grant_buy(self):
        p=pack()
        row=observation("ASST",value=1.5)
        for k in ("equity_price_usd","btc_price_usd"):
            row["input_evidence"][k]["valid_until_ms"]=NOW+1
        trial=dict(input_evidence=row["input_evidence"],share_basis_ref=row["share_basis_ref"],evidence_alignment_state="VALIDATED")
        ctx=dict(evidence_pack_hash=p["evidence_pack_hash"],mnav_trial=trial)
        unbound=build_report(p,context=ctx,generated_at_ms=NOW)
        self.assertEqual(metric(unbound,"current diluted mNAV")["qualification"],"RESEARCH_ONLY")
        from crt_radar.treasury_company_ct import add_treasury_valuation_context
        add_treasury_valuation_context(p,{"ASST":{"mnav_history":[row]}})
        seal(p);ctx["evidence_pack_hash"]=p["evidence_pack_hash"]
        r=build_report(p,context=ctx,generated_at_ms=NOW)
        m=metric(r,"current diluted mNAV")
        self.assertEqual(m["value"],1.5)
        self.assertEqual(m["qualification"],"QUALIFIED")
        self.assertIn("(10 * 15.0) / (1 * 100)",m["inputs"]["substitution"])
        self.assertFalse(m["inputs"]["buy_eligible"])
        for change in ({"asset_id":"MSTR"},{"currency":"USDT"},{"quality_state":"BLOCKED"}):
            bad=deepcopy(ctx)
            bad["mnav_trial"]["input_evidence"]["btc_price_usd"].update(change)
            bad_report=build_report(p,context=bad,generated_at_ms=NOW)
            self.assertIsNone(metric(bad_report,"current diluted mNAV")["value"])
            self.assertEqual(metric(bad_report,"current diluted mNAV")["qualification"],"BLOCKED")
        no_hash=deepcopy(ctx)
        no_hash["mnav_trial"]["input_evidence"]["btc_price_usd"].pop("raw_sha256")
        self.assertIsNone(metric(build_report(p,context=no_hash,generated_at_ms=NOW),"current diluted mNAV")["value"])
        trial["input_evidence"]["diluted_shares"]["effective_time"]-=DAY_MS
        r=build_report(p,context=ctx,generated_at_ms=NOW)
        self.assertEqual(metric(r,"current diluted mNAV")["value"],1.5)
        self.assertEqual(metric(r,"current diluted mNAV")["qualification"],"RESEARCH_ONLY")
        trial["input_evidence"]["btc_price_usd"]["valid_until_ms"]=NOW
        r=build_report(p,context=ctx,generated_at_ms=NOW)
        self.assertEqual(metric(r,"current diluted mNAV")["qualification"],"STALE")

    def test_existing_ct_and_historical_numbers_keep_scope_and_decimal_format(self):
        # Exact calendar references, not guessed nearest dates or annualized returns.
        at=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
        history=[]; assets=[]
        for dt,value in (("2026-07-23",.777),("2026-09-23",1.286),("2026-10-16",1.018),("2026-10-23",1.2)):
            t=int(datetime.fromisoformat(dt).replace(tzinfo=timezone.utc).timestamp()*1000)
            history.append(observation("ASST",at=t,value=value))
            assets.append(metadata("ASST",t,btc_holdings=100+len(assets)*10,diluted_shares=100,basis_ref="same-basis"))
        with tempfile.TemporaryDirectory() as d:
            p=build_evidence_pack(gate(0),observation_db=Path(d)/"o.db",generated_at_ms=at,
                treasury_valuation_inputs={"ASST":dict(mnav_history=history,asset_history=assets)})
        # Use the existing normalized per-share organ, with the same evidence.
        from crt_radar.treasury_company_ct import build_treasury_company_ct, add_treasury_company_ct
        data=ct_kwargs(); data.update(issuer_id="CIK-0001920406",as_of_ms=at,asset_history=assets)
        add_treasury_company_ct(p,data);seal(p)
        r=build_report(p,generated_at_ms=at)
        self.assertEqual(metric(r,"historical mNAV quarter")["value"],.777)
        self.assertAlmostEqual(metric(r,"BTC/share week growth")["value"],(1.3/1.2-1)*100)
        text=render_markdown(r)
        self.assertIn("| historical mNAV quarter | 0.777 |  |",text)
        self.assertNotIn("0.777X",text)
        self.assertEqual(metric(r,"usable_liquidity_usd")["value"],None)

    def test_pre_post_projection_does_not_modify_original_or_expire_early(self):
        from test_btc_tactical_forecast import TacticalForecastTests
        fixture=TacticalForecastTests();fixture.setUp()
        try:
            pre=freeze_pre(fixture.store,fixture.pre,now_ms=fixture.now)
            p=pack(fixture.now)
            first=build_report(p,forecast=pre,generated_at_ms=fixture.now)
            self.assertEqual(first["forecast"]["record"],pre)
            before=fixture.store.conn.total_changes
            readback=build_report_from_store(p,fixture.store,pre_id=pre["content"]["id"],
                pre_hash=pre["content_hash"],generated_at_ms=fixture.now)
            self.assertEqual(readback["forecast_access"],"OBSERVATION_STORE_READBACK")
            self.assertEqual(fixture.store.conn.total_changes,before)
            post_data=fixture.post(pre)
            post=freeze_post(fixture.store,post_data,now_ms=post_data["generated_at_ms"])
            p=pack(post_data["market_cutoff_ms"])
            original=deepcopy(pre)
            r=build_report(p,forecast=post,original_pre=pre,generated_at_ms=post_data["generated_at_ms"])
            self.assertEqual(r["forecast"]["record"]["content"]["reviews"][0]["result"],"PENDING")
            self.assertEqual(pre,original)
            with self.assertRaises((ValueError,KeyError,TypeError)):
                build_report(p,forecast=post,original_pre=None,generated_at_ms=post_data["generated_at_ms"])
            changed=deepcopy(pre);changed["content"]["main_scenario"]="changed"
            with self.assertRaisesRegex(ValueError,"FORECAST_INVALID"):
                build_report(pack(fixture.now),forecast=changed,generated_at_ms=fixture.now)
        finally: fixture.tearDown()

    def test_cli_only_creates_explicit_new_report_without_network_or_database_access(self):
        import runpy,sys
        with tempfile.TemporaryDirectory() as d:
            original=Path(d)/"pack.json";original.write_text(json.dumps(pack()),encoding="utf-8")
            before=original.read_bytes();out=Path(d)/"report.json"
            args=["daily_quantitative_report","--evidence-pack",str(original),"--output",str(out),"--generated-at-ms",str(NOW)]
            with patch.object(sys,"argv",args),patch("urllib.request.urlopen",side_effect=AssertionError("NO_NETWORK")),patch("sqlite3.connect",side_effect=AssertionError("NO_DATABASE_WRITE")):
                from crt_radar.daily_quantitative_report import main
                main()
                with self.assertRaisesRegex(ValueError,"OUTPUT_EXISTS"):
                    main()
            self.assertEqual(original.read_bytes(),before)
            self.assertEqual({p.name for p in Path(d).iterdir()},{"pack.json","report.json","report.md"})


class EtfTradingSessionReportTests(unittest.TestCase):
    def fixture(self):
        data=dict(units="USD",license=etf.LICENSE,sources="synthetic",attribution="synthetic",
            updatedThrough="2026-10-27",days=[])
        closed=set(etf._contract("CRT_ETP_PROSPECTIVE_CAPTURE_CONTRACT_V0.1.json")["market_calendar"]["full_close_dates"])
        day=date(2026,3,1)
        while day<=date(2026,10,27):
            if day.weekday()<5 and day.isoformat() not in closed:
                data["days"].append(dict(date=day.isoformat(),perEtfUsd={t:float(len(data["days"])+1) for t in TICKERS}))
            day+=timedelta(days=1)
        at=int(datetime(2026,10,28,12,tzinfo=timezone.utc).timestamp()*1000)
        env=envelope(data);env["retrieved_at_ms"]=at
        return data,env,at

    def test_completed_5_20_60_sessions_previous_comparison_and_fund_details(self):
        data,env,at=self.fixture()
        r=etf.trading_session_windows(env,as_of_ms=at)
        for n in (5,20,60):
            w=r["windows"][str(n)]
            self.assertEqual(len(w["current_session_dates"]),n)
            self.assertEqual(len(w["previous_session_dates"]),n)
            self.assertFalse(set(w["current_session_dates"])&set(w["previous_session_dates"]))
            self.assertEqual(w["value"],sum(v["current_usd"] for v in w["by_fund"].values()))
            self.assertAlmostEqual(w["change_usd"],w["value"]-w["previous_value"])
        self.assertFalse(r["formal_model_input"])
        self.assertEqual(r["fund_daily"],data["days"])

    def test_unpublished_fund_is_not_zero_or_different_scope_in_previous_window(self):
        data,env,at=self.fixture()
        data["days"][-3]["perEtfUsd"]["IBIT"]=None
        env=envelope(data);env["retrieved_at_ms"]=at
        r=etf.trading_session_windows(env,as_of_ms=at)
        w=r["windows"]["5"]
        self.assertNotIn("IBIT",w["scope_ids"])
        self.assertNotIn("IBIT",w["by_fund"])
        self.assertEqual(w["coverage_state"],"PARTIAL")
        self.assertIsNone(r["fund_daily"][-3]["perEtfUsd"]["IBIT"])
        r=etf.trading_session_windows(env,as_of_ms=at+DAY_MS)
        self.assertIsNone(r["windows"]["5"]["value"])

    def test_etf_archive_must_be_bound_to_same_pack(self):
        data,env,at=self.fixture()
        p=pack(at)
        r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],btc_etf_archive=env),generated_at_ms=at)
        self.assertEqual(metric(r,"ETF 5/20/60 sessions")["reason"],"ETF_ARCHIVE_NOT_BOUND_TO_PACK")
        etf.add_to_pack({"generated_at_ms":at,"asset_facts":{"items":[]},"blockers":{"items":[]}},env)
        p["asset_facts"]["items"]=[{"source_id":etf.SOURCE,"evidence_hash":env["evidence_hash"]}];seal(p)
        r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],btc_etf_archive=env),generated_at_ms=at)
        self.assertIsNotNone(metric(r,"ETF 5 completed sessions")["value"])
        self.assertIn("IBIT:",render_markdown(r))


if __name__=="__main__": unittest.main()
