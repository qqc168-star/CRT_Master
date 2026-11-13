"""Real SEC archives for replay; modified raw vectors are explicitly synthetic."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.issuer_ratio_market_health_source import build_archived_issuer_ct_inputs
from crt_radar.observation_store import ObservationStore
from crt_radar.gpt_handoff import build_minimized_bridge_payload, _bridge_market_context, run_gpt_handoff_gate, expand_bridge_field_names
from crt_radar.plain_language_notice import build_plain_language_notice
from test_first_evidence_slice import gate

FIXTURES=Path(__file__).parent/'fixtures'


def archive(root, version='20261109', mstr=True):
    sec=root/'sec-disclosures';sec.mkdir(parents=True)
    manifest=[]
    original=FIXTURES/'issuer_disclosures_20261005'
    sources=[]
    if mstr:
        prov=json.loads((original/'provenance.json').read_text())[0]
        selected=json.loads((original/'strategy-selected.json').read_text())['filings']['recent']
        item=dict(asset='MSTR',accession=selected['accessionNumber'][0],primary=selected['primaryDocument'][0],
            accepted=selected['acceptanceDateTime'][0],source_url=prov['url'],raw_sha256=prov['sha256'],
            retrieved_at_ms=int(datetime.fromisoformat(prov['capture_file_written_at_utc']).timestamp()*1000))
        sources.append((original/'strategy.html',item))
    if version=='20261005':
        prov=json.loads((original/'provenance.json').read_text())[1]
        selected=json.loads((original/'strive-selected.json').read_text())['filings']['recent']
        item=dict(asset='ASST',accession=selected['accessionNumber'][0],primary=selected['primaryDocument'][0],
            accepted=selected['acceptanceDateTime'][0],source_url=prov['url'],raw_sha256=prov['sha256'],
            retrieved_at_ms=int(datetime.fromisoformat(prov['capture_file_written_at_utc']).timestamp()*1000))
    else:
        original=FIXTURES/('issuer_disclosures_'+version)
        item=json.loads((original/'provenance.json').read_text())
        if (original/'strive-submissions.json').exists():
            shutil.copyfile(original/'strive-submissions.json',sec/'ASST-submissions.json')
    sources.append((original/'strive.html',item))
    for path,item in sources:
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['raw_sha256']
        shutil.copyfile(path,sec/f"{item['asset']}-{item['accession']}.html")
        manifest.append(item)
    (sec/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return root


def status(pack,asset='ASST'):
    return next(r['evidence'] for r in pack['asset_facts']['items']
        if r.get('fact_type')=='ISSUER_SOURCE_FRESHNESS' and r['asset_id']==asset)


class IssuerSourceFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'observations.sqlite3'
        self.new=archive(self.root/'new')
        self.old=archive(self.root/'old','20261026')
        self.early=archive(self.root/'early','20261005')
        manifest=json.loads((self.new/'sec-disclosures/manifest.json').read_text())
        self.now=max(max(r['retrieved_at_ms'],r.get('issuer_index_retrieved_at_ms',0)) for r in manifest)+1000

    def build(self,archive_path=None,**kwargs):
        return build_evidence_pack(gate(0),observation_db=self.db,generated_at_ms=self.now,
            issuer_ct_archive=archive_path,**kwargs)

    def test_real_november_snapshot_has_independent_dated_watermarks_not_fake_formal_scope(self):
        p=self.build(self.new);s=status(p)
        with ObservationStore(self.db) as store:
            state=store.latest_research_event('issuer_source_versions:CIK-0001920406')
        fields=state['fields']
        self.assertEqual(fields['btc_holdings']['value'],43153)
        self.assertEqual(fields['usd_cash_usd']['value'],487600000)
        self.assertEqual(fields['diluted_shares']['value'],130044690)
        self.assertEqual(fields['btc_holdings']['accession'],'0001628280-26-071888')
        self.assertEqual(datetime.fromtimestamp(fields['btc_holdings']['effective_time']/1000,timezone.utc).date().isoformat(),'2026-11-06')
        self.assertEqual(status(p,'MSTR')['state'],'SOURCE_BOUND')
        # New reported AFDS is preserved, but main's dilution/valuation gate is
        # not relaxed by the source-version guard.
        self.assertEqual(p['common_equity_health']['assets']['ASST']['company_health']['dimensions']['per_share_asset_engine']['direction'],'BLOCKED')

    def test_three_runs_keep_watermarks_without_reusing_absent_financial_values(self):
        first=self.build(self.new)
        self.now+=86400000;second=self.build()
        self.assertEqual(status(second)['state'],'NOT_RUN')
        self.assertFalse(any(r.get('fact_type')=='TREASURY_COMPANY_CT' for r in second['asset_facts']['items']))
        self.now+=86400000;third=self.build(self.old)
        self.assertEqual(status(first)['watermarks'],status(third)['watermarks'])
        self.assertEqual(status(third)['blocked_fields']['btc_holdings'],'ISSUER_SOURCE_REGRESSION_BLOCKED')
        self.assertEqual(status(third)['blocked_fields']['usd_cash_usd'],'ISSUER_SOURCE_REGRESSION_BLOCKED')
        asst=third['common_equity_health']['assets']['ASST']
        self.assertIsNone(asst['btc_per_diluted_share'])
        self.assertEqual(third['layers'],first['layers'])

    def test_metadata_flags_cannot_seed_versions_or_override_an_authentic_version(self):
        raw=build_archived_issuer_ct_inputs(self.old,as_of_ms=self.now)
        for r in raw['ASST']['asset_history']:
            r.update(verification_state='VALIDATED',correction_verified=True,correction_document='official-amendment.htm')
        p=self.build(treasury_company_ct_inputs=raw)
        self.assertIn('ISSUER_SOURCE_NOT_ARCHIVE_VERIFIED',status(p)['blocked_fields'].values())
        with ObservationStore(self.db) as store:
            self.assertIsNone(store.latest_research_event('issuer_source_versions:CIK-0001920406'))
        self.build(self.new)
        p=self.build(treasury_company_ct_inputs=raw)
        self.assertEqual(status(p)['watermarks']['btc_holdings']['accession'],'0001628280-26-071888')
        self.assertIsNone(p['common_equity_health']['assets']['ASST']['btc_per_diluted_share'])

    def test_source_url_raw_hash_and_submission_index_tampering_cannot_seed(self):
        manifest_path=self.new/'sec-disclosures/manifest.json'
        original=json.loads(manifest_path.read_text())
        for change in ({'source_url':'https://www.sec.gov/Archives/edgar/data/1050446/fake.htm'},
                {'raw_sha256':'a'*64},{'issuer_index_raw_sha256':'a'*64}):
            rows=deepcopy(original);rows[-1].update(change);manifest_path.write_text(json.dumps(rows))
            p=self.build(self.new)
            self.assertEqual(status(p,'MSTR')['state'],'SOURCE_BOUND')
            self.assertNotIn('btc_holdings',status(p)['watermarks'])
        manifest_path.write_text(json.dumps(original))

    def test_same_date_conflict_and_self_asserted_correction_do_not_replace_prior(self):
        self.build(self.new)
        # Synthetic altered original bytes test the conflict gate; never claimed
        # to be a real SEC correction or used for the real market acceptance.
        manifest_path=self.new/'sec-disclosures/manifest.json'
        rows=json.loads(manifest_path.read_text());item=rows[-1]
        raw_path=self.new/'sec-disclosures'/f"ASST-{item['accession']}.html"
        raw=raw_path.read_bytes();changed=raw.replace(b'43,153',b'43,999')
        self.assertNotEqual(raw,changed)
        raw_path.write_bytes(changed);item.update(raw_sha256=hashlib.sha256(changed).hexdigest(),correction_verified=True)
        manifest_path.write_text(json.dumps(rows))
        p=self.build(self.new)
        self.assertEqual(status(p)['blocked_fields']['btc_holdings'],'ISSUER_SAME_DATE_CONFLICT_CORRECTION_UNPROVEN')
        self.assertEqual(status(p)['watermarks']['usd_cash_usd']['effective_time'],status(p)['watermarks']['btc_holdings']['effective_time'])
        with ObservationStore(self.db) as store:
            self.assertEqual(store.latest_research_event('issuer_source_versions:CIK-0001920406')['fields']['btc_holdings']['value'],43153)

    def test_real_october_sources_health_pack_bridge_preserve_full_failure_context(self):
        early=self.build(self.early)
        self.assertEqual(status(early)['state'],'SOURCE_BOUND')
        self.assertIsNotNone(early['common_equity_health']['assets']['ASST']['btc_per_diluted_share'])
        self.build(self.new)
        old=self.build(self.old,treasury_valuation_inputs={'ASST':{'mnav_history':[]}})
        market=_bridge_market_context(old)
        self.assertEqual(market['company_source_freshness']['ASST']['state'],'BLOCKED')
        self.assertTrue(any(r.get('reason')=='ISSUER_SOURCE_REGRESSION_BLOCKED' for r in old['blockers']['items']))
        # Market/wake envelope is synthetic; SEC originals above are real.
        # Only the local gate/projection runs, never a provider or outbox worker.
        old['reanalysis_wake']=dict(state='REANALYSIS_REQUESTED',reason='SYNTHETIC_OFFLINE_SOURCE_AUDIT',
            wake_sources=['BTC_INTRADAY'],percent_change=7)
        from test_gpt_handoff import bridge_pack,pack as synthetic_pack
        old['private_context']=bridge_pack(synthetic_pack(evidence_hash='synthetic',requested=True))['private_context']
        old.pop('evidence_pack_hash');old['evidence_pack_hash']=hashlib.sha256(json.dumps(old,
            ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        handoff=run_gpt_handoff_gate(old,build_plain_language_notice(old),ledger_path=self.root/'handoff.jsonl')
        payload=build_minimized_bridge_payload(old,handoff)
        encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()
        self.assertGreater(len(encoded),16384)  # Full evidence, not the former 16 KiB cap.
        self.assertIn(b'ISSUER_SOURCE_REGRESSION_BLOCKED',encoded)
        expanded=expand_bridge_field_names(payload)
        self.assertEqual(expanded['market_context']['company_source_freshness'],market['company_source_freshness'])
        self.assertEqual(expanded['market_context']['common_equity_health'],market['common_equity_health'])
        self.assertFalse(payload['authority']['machine_may_execute_trade'])

    def test_supplied_mnav_scope_and_older_values_cannot_override_current_versions(self):
        from test_treasury_valuation_context import observation
        self.build(self.new)
        row=observation('ASST',at=self.now)
        p=self.build(self.old,treasury_valuation_inputs={'ASST':dict(mnav_history=[row])})
        from crt_radar.treasury_company_ct import compact_treasury_valuation_context
        self.assertEqual(compact_treasury_valuation_context(p)['ASST']['formal_action_critical_state'],'BLOCKED')
        self.assertIsNone(p['common_equity_health']['assets']['ASST']['btc_per_diluted_share'])

    def test_field_dates_remain_independent_and_new_current_source_does_not_relabel_old_ct(self):
        self.build(self.early)
        p=self.build(self.new)
        with ObservationStore(self.db) as store:
            mstr=store.latest_research_event('issuer_source_versions:CIK-0001050446')['fields']
            asst=store.latest_research_event('issuer_source_versions:CIK-0001920406')['fields']
        self.assertNotEqual(mstr['usd_cash_usd']['effective_time'],asst['usd_cash_usd']['effective_time'])
        self.assertGreater(asst['usd_cash_usd']['effective_time'],int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000))
        self.assertIsNone(p['common_equity_health']['assets']['ASST']['btc_per_diluted_share'])

    def test_replay_dedup_and_missing_input_do_not_erase_history(self):
        self.build(self.new)
        with ObservationStore(self.db) as store:
            before=store.conn.execute("SELECT count(*) FROM btc_research_events WHERE kind LIKE 'issuer_source_versions:%'").fetchone()[0]
        self.build(self.new);self.build()
        with ObservationStore(self.db) as store:
            after=store.conn.execute("SELECT count(*) FROM btc_research_events WHERE kind LIKE 'issuer_source_versions:%'").fetchone()[0]
        self.assertEqual(before,after)

    def test_public_boundary_rejects_self_labels_without_even_an_official_url(self):
        from test_treasury_company_ct import kwargs
        raw=kwargs()
        def rewrite(value):
            if isinstance(value,dict):
                if 'source_ref' in value:value['source_ref']='unproven-caller-note'
                for child in value.values():rewrite(child)
            elif isinstance(value,list):
                for child in value:rewrite(child)
        rewrite(raw)
        p=self.build(treasury_company_ct_inputs={'MSTR':raw},issuer_source_verification_required=True)
        self.assertEqual(status(p,'MSTR')['blocked_fields']['btc_holdings'],'ISSUER_SOURCE_NOT_ARCHIVE_VERIFIED')
        self.assertIsNone(p['common_equity_health']['assets']['MSTR']['btc_per_diluted_share'])
        with ObservationStore(self.db) as store:
            self.assertIsNone(store.latest_research_event('issuer_source_versions:CIK-0001050446'))

    def test_malformed_archive_blocks_company_claims_but_preserves_market_observations(self):
        good=self.build(self.new)
        (self.new/'sec-disclosures/manifest.json').write_text('[null]')
        bad=self.build(self.new)
        self.assertEqual(status(bad)['state'],'BLOCKED')
        self.assertEqual(status(good)['watermarks'],status(bad)['watermarks'])
        self.assertEqual(good['layers'],bad['layers'])


if __name__=='__main__':unittest.main()
