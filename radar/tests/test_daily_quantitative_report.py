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


def metric(report, name, asset_id="ASST"):
    return next(r for r in report["rows"] if r["metric"]==name and r.get("asset_id") in (None,asset_id))


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
        # Exact 13/4/1-week references, never calendar-month or nearest dates.
        at=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
        history=[]; assets=[]
        for dt,value in (("2026-07-24",.777),("2026-09-25",1.286),("2026-10-16",1.018),("2026-10-23",1.2)):
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
        self.assertEqual(metric(r,"historical mNAV month")["value"],1.286)
        self.assertEqual(metric(r,"historical mNAV week")["value"],1.018)
        for name,day in (("quarter","2026-07-24"),("month","2026-09-25"),("week","2026-10-16")):
            for prefix in ("BTC/share ","historical mNAV "):
                row=metric(r,prefix+name+(" growth" if prefix.startswith("BTC") else ""))
                self.assertEqual(row["inputs"]["reference_date"],day)
        self.assertAlmostEqual(metric(r,"BTC/share week growth")["value"],(1.3/1.2-1)*100)
        text=render_markdown(r)
        self.assertIn("| historical mNAV quarter | 0.777 |  |",text)
        self.assertNotIn("0.777X",text)
        self.assertEqual(metric(r,"usable_liquidity_usd")["value"],None)

    def coverage_fixture(self):
        p=pack();ref=source()
        p["layers"]={"L6":{"metrics":{"btc_spot_price_usd":dict(value=80000,
            source_id=ref["source_id"],evidence_hash=ref["evidence_hash"],as_of_ms=ref["observed_at_ms"],quality_state="VALID")}}}
        def reported(fields,claim="REPORTED_CAPITAL_STRUCTURE_SNAPSHOT",**extra):
            return {**metadata("ASST",NOW,claim=claim,reported_fields=fields,raw_sha256="b"*64,**extra),
                "source_ref":"synthetic:"+next(iter(fields))}
        records=[reported(dict(btc_holdings=43000,diluted_shares=100000000),share_basis="same-basis"),
            reported(dict(cash_and_cash_equivalents_usd=504400000,usd_reserve_usd=900000000)),
            reported(dict(strc_fair_value_usd=50177000)),
            reported(dict(initial_preferred_claims_usd=2103017600),claim="REPORTED_INITIAL_PREFERRED_CLAIMS",
                initial_preferred_claims_scope="COMPLETE_INITIAL_PREFERENCE")]
        p["asset_facts"]["items"].append(dict(fact_type="ISSUER_CT_SOURCE_BINDING",issuer_id="CIK-0001920406",
            evidence={"observations":records}))
        seal(p)
        ctx=dict(evidence_pack_hash=p["evidence_pack_hash"],sources=[ref],
            btc_price_scenarios=[{"price_usd":60000,"assumption_ref":"synthetic:explicit"}])
        return p,ctx,records

    def test_asset_coverage_includes_cash_strc_initial_claims_and_never_adds_reserve(self):
        p,ctx,records=self.coverage_fixture()
        r=build_report(p,context=ctx,generated_at_ms=NOW)
        row=metric(r,"research asset coverage / initial preferred claims")
        self.assertAlmostEqual(row["value"],1.89945,places=5)
        self.assertAlmostEqual(row["value"],(43000*80000+504400000+50177000)/2103017600)
        self.assertNotAlmostEqual(row["value"],43000*80000/2103017600)
        self.assertEqual(row["qualification"],"RESEARCH_ONLY")
        self.assertEqual(row["inputs"]["reserve_added_usd"],0)
        self.assertEqual(len(row["inputs"]["component_evidence"]),5)
        for refs in row["inputs"]["component_evidence"].values():
            self.assertTrue(refs)
            self.assertTrue(refs[0]["source_ref"])
        self.assertAlmostEqual(metric(r,"BTC pressure comparison")["value"][0]["coverage"],
            (43000*60000+504400000+50177000)/2103017600)
        self.assertEqual(r["action_output"],"NONE")

    def test_coverage_missing_or_invalid_component_never_falls_back_to_btc_only(self):
        for index,change in ((1,"missing"),(2,"missing"),(3,"missing"),
                (1,"future"),(2,"wrong_date"),(3,"dynamic"),(2,"unverified"),(0,"hash_missing")):
            with self.subTest(index=index,change=change):
                p,ctx,records=self.coverage_fixture()
                row=records[index]
                if change=="missing": row["reported_fields"].clear()
                elif change=="future": row["retrieval_time"]=NOW+1
                elif change=="wrong_date": row["effective_time"]-=DAY_MS
                elif change=="dynamic": row["initial_preferred_claims_scope"]="DYNAMIC_ACTUAL_CLAIMS"
                elif change=="unverified": row["verification_state"]="BLOCKED"
                else: row.pop("raw_sha256")
                seal(p);ctx["evidence_pack_hash"]=p["evidence_pack_hash"]
                r=build_report(p,context=ctx,generated_at_ms=NOW)
                result=metric(r,"research asset coverage / initial preferred claims")
                self.assertIsNone(result["value"])
                self.assertEqual(result["qualification"],"BLOCKED")
                self.assertIsNone(metric(r,"BTC pressure comparison")["value"])
                self.assertEqual(metric(r,"btc_spot_price_usd")["value"],80000)

    def test_old_calendar_months_cannot_fill_missing_13_or_4_week_windows(self):
        at=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
        history=[];assets=[]
        for dt,value in (("2026-07-23",9),("2026-09-23",8),("2026-10-16",1.018),("2026-10-23",1.2)):
            t=int(datetime.fromisoformat(dt).replace(tzinfo=timezone.utc).timestamp()*1000)
            history.append(observation("ASST",at=t,value=value))
            assets.append(metadata("ASST",t,btc_holdings=100,diluted_shares=100,basis_ref="same-basis"))
        with tempfile.TemporaryDirectory() as d:
            p=build_evidence_pack(gate(0),observation_db=Path(d)/"o.db",generated_at_ms=at,
                treasury_valuation_inputs={"ASST":dict(mnav_history=history,asset_history=assets)})
        from crt_radar.treasury_company_ct import add_treasury_company_ct
        data=ct_kwargs();data.update(issuer_id="CIK-0001920406",as_of_ms=at,asset_history=assets)
        add_treasury_company_ct(p,data);seal(p)
        r=build_report(p,generated_at_ms=at)
        for name in ("quarter","month"):
            self.assertIsNone(metric(r,"historical mNAV "+name)["value"])
            self.assertIsNone(metric(r,"BTC/share "+name+" growth")["value"])
        self.assertEqual(metric(r,"historical mNAV week")["value"],1.018)
        self.assertEqual(metric(r,"BTC/share week growth")["value"],0)

    def test_weekly_values_prior_and_difference_share_completed_archive_and_stale_state(self):
        at=int(datetime(2026,10,26,12,tzinfo=timezone.utc).timestamp()*1000)
        latest=datetime(2026,10,25,23,59,59,tzinfo=timezone.utc)
        closes=[100+i+(-3 if i%3==0 else 2) for i in range(202)]
        bars=[dict(week_closed_at=(latest-timedelta(weeks=201-i)).isoformat(),
            available_at=(latest-timedelta(weeks=201-i)+timedelta(seconds=1)).isoformat(),
            is_complete=True,close=c) for i,c in enumerate(closes)]
        bars.append(dict(week_closed_at=(latest+timedelta(weeks=1)).isoformat(),
            available_at=(latest+timedelta(weeks=1,seconds=1)).isoformat(),is_complete=False,close=999999))
        raw=json.dumps(bars);ref=source(at,observed_at_ms=at-1000,evidence_hash=hashlib.sha256(raw.encode()).hexdigest())
        def rsi(values):
            gains=[max(b-a,0) for a,b in zip(values,values[1:])]
            losses=[max(a-b,0) for a,b in zip(values,values[1:])]
            g,l=sum(gains[:14])/14,sum(losses[:14])/14
            for x,y in zip(gains[14:],losses[14:]): g,l=(13*g+x)/14,(13*l+y)/14
            return 100-100/(1+g/l)
        for cutoff in (at,at+10*DAY_MS):
            p=pack(cutoff)
            r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],weekly_archive={"raw_json":raw,"source":ref}),generated_at_ms=cutoff)
            for name,n in (("50WMA",50),("200WMA",200),("RSI(14)",None)):
                expected=sum(closes[-n:])/n if n else rsi(closes)
                previous=sum(closes[-n-1:-1])/n if n else rsi(closes[:-1])
                self.assertAlmostEqual(metric(r,name)["value"],expected)
                self.assertAlmostEqual(metric(r,name+" previous completed week")["value"],previous)
                self.assertAlmostEqual(metric(r,name+" weekly difference")["value"],expected-previous)
                for label in (name,name+" previous completed week",name+" weekly difference"):
                    self.assertEqual(metric(r,label)["qualification"],"STALE" if cutoff!=at else "RESEARCH_ONLY")
                if n: self.assertAlmostEqual(metric(r,f"weekly close / {n}WMA deviation")["value"],(closes[-1]/expected-1)*100)
        # Missing history blocks only the unavailable previous 200-week value;
        # it cannot be guessed from the latest average or incomplete next bar.
        raw=json.dumps(bars[2:]);ref["evidence_hash"]=hashlib.sha256(raw.encode()).hexdigest()
        p=pack(at)
        r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],weekly_archive={"raw_json":raw,"source":ref}),generated_at_ms=at)
        self.assertIsNotNone(metric(r,"200WMA")["value"])
        self.assertIsNone(metric(r,"200WMA previous completed week")["value"])
        self.assertIsNone(metric(r,"200WMA weekly difference")["value"])
        raw=json.dumps(bars[:100]+bars[101:]);ref["evidence_hash"]=hashlib.sha256(raw.encode()).hexdigest()
        r=build_report(p,context=dict(evidence_pack_hash=p["evidence_pack_hash"],weekly_archive={"raw_json":raw,"source":ref}),generated_at_ms=at)
        self.assertEqual(metric(r,"weekly archive")["reason"],"COMPLETED_WEEKLY_ARCHIVE_GAP")

    def test_investor_main_report_order_before_audit_never_invents_ns_judgment(self):
        p,ctx,_=self.coverage_fixture()
        r=build_report(p,context=ctx,generated_at_ms=NOW)
        text=render_markdown(r)
        titles=("## 1. BTC 市場總覽","## 2. 1～3 週戰術","## 3. 鏈上、RSI", "## 4. ETF 5／20／60",
            "## 5. 槓桿、Funding","## 6. 雙公司六維","## 7. N.S. 市場與公司聯合裁決",
            "## 8. PRE／POST 驗證","## 詳細量化證據稽核附表")
        positions=[text.index(t) for t in titles]
        self.assertEqual(positions,sorted(positions))
        main,audit=text.split("## 詳細量化證據稽核附表")
        self.assertIn("聯合裁決：NOT_RUN",main)
        self.assertIn("1.899",main)
        self.assertIn("| 區塊 | 指標 | 數值 |",audit)
        self.assertEqual(len([line for line in audit.splitlines() if line.startswith("| ")])-1,len(r["rows"]))

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
            shown=render_markdown(r)
            for line in pre["content"]["original_text"].splitlines():
                self.assertIn(line,shown)
            self.assertIn(pre["content"]["invalidation_line"],shown)
            self.assertIn(pre["content"]["main_scenario"],shown)
            self.assertIn("price_anchor",shown)
            self.assertIn("PENDING",shown)
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


class DualCompanyReportTests(unittest.TestCase):
    def fixture(self):
        from test_company_health import scenario
        from test_treasury_company_ct import T2
        from crt_radar.treasury_company_ct import add_treasury_company_ct
        p=pack(T2)
        for strive in (False,True): add_treasury_company_ct(p,scenario(strive))
        return seal(p),T2

    def test_both_companies_reuse_six_dimensions_and_keep_eight_sections(self):
        from crt_radar.portfolio_allocation_context import build_common_equity_health
        p,at=self.fixture();before=deepcopy(p)
        r=build_report(p,generated_at_ms=at)
        self.assertEqual(r,build_report(p,generated_at_ms=at))
        self.assertEqual(before,p)
        engine=build_common_equity_health(p)
        for asset in ("MSTR","ASST"):
            self.assertEqual(r["companies"][asset]["health"]["company_health"],
                engine["assets"][asset]["company_health"])
            self.assertEqual(len([x for x in r["rows"] if x["section"]==asset+" 六維"]),6)
            row=metric(r,"per_share_asset_engine",asset)
            self.assertTrue(row["evidence"])
            self.assertIn("comparison_windows",row["inputs"])
            self.assertEqual(row["inputs"]["analyst_counterevidence"],"NOT_RUN")
        text=render_markdown(r)
        self.assertEqual(len([s for s in text.splitlines() if s.startswith("## ") and s[3:4].isdigit()]),8)
        self.assertIn("Strategy（MSTR）",text);self.assertIn("Strive（ASST）",text)
        self.assertIn("Strive ⑤",text)
        self.assertEqual(len([x for x in r["rows"] if x["metric"]=="company health contradictions"]),2)
        self.assertEqual(r["action_output"],"NONE")
        self.assertEqual(r["production"],"NOT_APPROVED")

    def test_cross_company_fact_and_nested_issuer_contamination_cannot_transfer(self):
        p,at=self.fixture()
        clean=build_report(p,generated_at_ms=at)
        for direction in (("MSTR","ASST"),("ASST","MSTR")):
            target,foreign=direction
            for nested in (False,True):
                bad=deepcopy(p)
                from crt_radar.treasury_company_ct import ISSUERS
                f=next(f for f in bad["asset_facts"]["items"] if f.get("ct_section")=="per_share_asset_engine"
                    and f["issuer_id"]==ISSUERS[target])
                if nested: f["evidence"]["current"]["issuer_id"]=ISSUERS[foreign]
                else: f["asset_id"]=foreign
                r=build_report(seal(bad),generated_at_ms=at)
                self.assertEqual(r["companies"][target]["health"]["company_health"]["dimensions"]["per_share_asset_engine"]["direction"],"BLOCKED")
                self.assertEqual(r["companies"][foreign],clean["companies"][foreign])
                self.assertTrue(r["excluded_company_evidence"])

    def test_one_stale_or_future_company_preserves_other_and_its_own_independent_facts(self):
        p,at=self.fixture();good=build_report(p,generated_at_ms=at)
        from crt_radar.treasury_company_ct import ISSUERS
        for changes in ({"quality_state":"STALE"},{"disclosure_time":at+1},
                {"valid_until_ms":at-1}):
            q=deepcopy(p)
            f=next(f for f in q["asset_facts"]["items"] if f.get("ct_section")=="per_share_asset_engine"
                and f["issuer_id"]==ISSUERS["MSTR"])
            f["evidence"]["current"].update(changes)
            r=build_report(seal(q),generated_at_ms=at)
            self.assertEqual(r["companies"]["ASST"],good["companies"]["ASST"])
            self.assertEqual(metric(r,"per_share_asset_engine","MSTR")["qualification"],"BLOCKED")
            self.assertIsNotNone(metric(r,"ATM / other financing","MSTR")["value"])

    def test_reported_only_adso_and_newer_unqualified_snapshot_do_not_refresh_old_health(self):
        from crt_radar.treasury_company_ct import ISSUERS
        p,at=self.fixture()
        issuer=ISSUERS["MSTR"]
        f=next(f for f in p["asset_facts"]["items"] if f.get("ct_section")=="per_share_asset_engine"
            and f["issuer_id"]==issuer)
        current=f["evidence"]["current"]
        current.pop("effective_time")
        current["reported_date"]="2026-10-11"
        r=build_report(seal(p),generated_at_ms=at)
        self.assertEqual(metric(r,"per_share_asset_engine","MSTR")["qualification"],"BLOCKED")
        p,at=self.fixture()
        from test_treasury_valuation_context import metadata
        newer=metadata("ASST",at+1,claim="REPORTED_CAPITAL_STRUCTURE_SNAPSHOT",
            reported_fields={"btc_holdings":1000,"diluted_shares":1000},share_basis="UNRESOLVED")
        p["generated_at_ms"]=at+2
        p["asset_facts"]["items"].append(dict(fact_type="ISSUER_CT_SOURCE_BINDING",issuer_id=ISSUERS["ASST"],
            evidence={"observations":[newer]}))
        r=build_report(seal(p),generated_at_ms=at+2)
        c=r["companies"]["ASST"]
        self.assertEqual(c["current_health_state"],"BLOCKED")
        self.assertEqual(c["current_comparison_effective_time"],at)
        self.assertEqual(c["latest_reported_effective_time"],at+1)
        self.assertEqual(metric(r,"per_share_asset_engine")["qualification"],"RESEARCH_ONLY")

    def test_each_company_mnav_separates_trial_history_and_original_dilution_scope(self):
        from crt_radar.treasury_company_ct import ISSUERS
        at=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
        histories={}
        for asset in ISSUERS:
            histories[asset]=dict(mnav_history=[observation(asset,at=at-days*DAY_MS,value=v)
                for days,v in ((91,.777),(28,1.286),(7,1.018),(0,1.5))])
            for row in histories[asset]["mnav_history"]:
                for field in ("equity_price_usd","btc_price_usd"):
                    row["input_evidence"][field]["valid_until_ms"]=at+DAY_MS
        with tempfile.TemporaryDirectory() as d:
            p=build_evidence_pack(gate(0),observation_db=Path(d)/"o.db",generated_at_ms=at,
                treasury_valuation_inputs=histories)
        trials={a:deepcopy(histories[a]["mnav_history"][-1]["input_evidence"]) for a in ISSUERS}
        ctx=dict(evidence_pack_hash=p["evidence_pack_hash"],mnav_trials={a:dict(input_evidence=t,
            share_basis_ref="same-basis",evidence_alignment_state="VALIDATED") for a,t in trials.items()})
        r=build_report(p,context=ctx,generated_at_ms=at)
        for asset in ISSUERS:
            row=metric(r,"current diluted mNAV",asset)
            self.assertEqual(row["value"],1.5);self.assertEqual(row["qualification"],"QUALIFIED")
            self.assertEqual(len(row["evidence"]),4)
            self.assertIn("SYNTHETIC_FULLY_DILUTED",row["evidence"][0]["dilution_scope"])
            self.assertEqual(metric(r,"historical mNAV month",asset)["value"],1.286)
        # Even a self-consistent existing context and calculator receipt cannot
        # promote a company-tagged price from the other issuer at this boundary.
        for field in ("equity_price_usd","btc_price_usd"):
            bad=deepcopy(p);bad_ctx=deepcopy(ctx)
            fact=next(f for f in bad["asset_facts"]["items"] if f.get("fact_type")=="TREASURY_VALUATION_CONTEXT"
                and f.get("asset_id")=="MSTR")
            val=fact["evidence"]
            for record in (val["current_observation"],val["mnav_observations"][-1]):
                record["input_evidence"][field]["issuer_id"]=ISSUERS["ASST"]
            val.pop("context_hash");val["context_hash"]=content_hash(val)
            seal(bad);bad_ctx["evidence_pack_hash"]=bad["evidence_pack_hash"]
            bad_ctx["mnav_trials"]["MSTR"]["input_evidence"][field]["issuer_id"]=ISSUERS["ASST"]
            projected=build_report(bad,context=bad_ctx,generated_at_ms=at)
            self.assertEqual(metric(projected,"current diluted mNAV","MSTR")["qualification"],"BLOCKED")
            self.assertIsNone(metric(projected,"current diluted mNAV","MSTR")["value"])
            self.assertEqual(metric(projected,"current diluted mNAV","ASST")["value"],1.5)
        ctx["mnav_trials"]["MSTR"]["input_evidence"]["diluted_shares"].pop("effective_time")
        r=build_report(p,context=ctx,generated_at_ms=at)
        self.assertIsNone(metric(r,"current diluted mNAV","MSTR")["value"])
        self.assertEqual(metric(r,"current diluted mNAV","ASST")["value"],1.5)
        wrong=deepcopy(ctx)
        wrong["mnav_trials"]["ASST"]["input_evidence"]["diluted_shares"]["issuer_id"]=ISSUERS["MSTR"]
        self.assertIsNone(metric(build_report(p,context=wrong,generated_at_ms=at),"current diluted mNAV")["value"])

    def test_reserve_and_incomplete_claims_not_reconstructed_for_strategy(self):
        from test_treasury_company_ct import kwargs,burden,T2
        from crt_radar.treasury_company_ct import add_treasury_company_ct
        for separate in (True,False):
            data=kwargs();cash=burden();cash.pop("preferred_liquidation_claims_usd")
            cash.update(usd_reserve_usd=50,usd_cash_usable_for_carry=True,cash_usability_basis_ref="carry",
                reserve_usable_for_carry=True,reserve_separate_from_cash=separate)
            data["burden_current"]=cash
            p=pack(T2);add_treasury_company_ct(p,data)
            r=build_report(seal(p),generated_at_ms=T2)
            self.assertIsNone(metric(r,"preferred_liquidation_claims_usd","MSTR")["value"])
            self.assertEqual(metric(r,"usd_cash_usd","MSTR")["value"],100)
            self.assertEqual(metric(r,"usd_reserve_usd","MSTR")["value"],50)
            available=metric(r,"usable_liquidity_usd","MSTR")["value"]
            self.assertTrue(available is None or available <= (150 if separate else 100))
            self.assertFalse(any(x["asset_id"]=="MSTR" and "initial preferred" in x["metric"] for x in r["rows"]))

    def test_period_strategy_facts_survive_without_becoming_executed_conversion(self):
        from crt_radar.treasury_company_ct import ISSUERS
        p,at=self.fixture()
        period=dict(issuer_id=ISSUERS["MSTR"],source_ref="synthetic:reported-period",raw_sha256="d"*64,
            claim="PERIOD_CAPITAL_FLOW",disclosure_time=at,first_seen_time=at,retrieval_time=at,
            evidence_qualification="VERIFIED_REPORTED_PERIOD_FACT",execution_time=None,
            ct_binding_state="BLOCKED",active_for_calculation=False,amount_usd=192400000,
            shares_repurchased=1932145,destination="STRC_REPURCHASE",source="FUNDING_SOURCE_UNRESOLVED")
        p["asset_facts"]["items"].append(dict(fact_type="ISSUER_CT_SOURCE_BINDING",issuer_id=ISSUERS["MSTR"],
            evidence={"observations":[period,dict(claim="DATED_ADSO_RESEARCH_OBSERVATION",qualification="RESEARCH_ONLY",
                current=dict(as_of_date="2026-10-11",btc_holdings=848250,diluted_shares=451797000),
                public_availability_state="UNPROVEN")]}))
        r=build_report(seal(p),generated_at_ms=at)
        row=metric(r,"source-bound reported fact","MSTR")
        self.assertEqual(row["value"],period)
        self.assertEqual(row["qualification"],"RESEARCH_ONLY")
        self.assertIsNone(row["value"]["execution_time"])
        self.assertEqual(row["value"]["source"],"FUNDING_SOURCE_UNRESOLVED")
        dated=metric(r,"dated ADSO research (not CT)","MSTR")
        self.assertEqual(dated["qualification"],"BLOCKED")
        self.assertEqual(dated["value"]["current"]["btc_holdings"],848250)
        period["disclosure_time"]=at+1
        r=build_report(seal(p),generated_at_ms=at)
        self.assertEqual(metric(r,"source-bound reported fact","MSTR")["qualification"],"BLOCKED")

    def test_both_historical_mnav_windows_refuse_nearest_dates_and_scope_changes(self):
        from crt_radar.treasury_company_ct import ISSUERS
        at=NOW
        for asset in ISSUERS:
            with self.subTest(asset=asset):
                history=[observation(asset,at=at-d*DAY_MS,value=v,basis=basis) for d,v,basis in (
                    (90,.7,"same-basis"),(28,1.2,"different-basis"),(7,1.018,"same-basis"),(0,1.5,"same-basis"))]
                with tempfile.TemporaryDirectory() as d:
                    p=build_evidence_pack(gate(0),observation_db=Path(d)/"o.db",generated_at_ms=at,
                        treasury_valuation_inputs={asset:dict(mnav_history=history)})
                r=build_report(p,generated_at_ms=at)
                self.assertIsNone(metric(r,"historical mNAV quarter",asset)["value"])
                self.assertIsNone(metric(r,"historical mNAV month",asset)["value"])
                self.assertEqual(metric(r,"historical mNAV week",asset)["value"],1.018)

    def test_pre_and_post_pack_mismatch_rejected_without_writing_forecast(self):
        import test_btc_tactical_forecast as tactical
        f=tactical.TacticalForecastTests();f.setUp()
        try:
            pre=freeze_pre(f.store,{**f.pre,"evidence_pack_hash":"b"*64},now_ms=f.now)
            original=deepcopy(pre)
            with self.assertRaisesRegex(ValueError,"FORECAST_PACK_MISMATCH"):
                build_report(pack(f.now),forecast=pre,generated_at_ms=f.now)
            post_data=f.post(pre);post_data["evidence_pack_hash"]="c"*64
            post=freeze_post(f.store,post_data,now_ms=post_data["generated_at_ms"])
            with self.assertRaisesRegex(ValueError,"FORECAST_PACK_MISMATCH"):
                build_report(pack(post_data["market_cutoff_ms"]),forecast=post,original_pre=pre,
                    generated_at_ms=post_data["generated_at_ms"])
            self.assertEqual(pre,original)
        finally: f.tearDown()


if __name__=="__main__": unittest.main()
