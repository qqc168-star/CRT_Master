"""Real SEC bytes replay. Local discovery baseline is simulated, never live state."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

from crt_radar.issuer_announcement_runner import parse_sec_submissions, load_registry, run_issuer_announcement_cycle, _normalized_official_facts, compact_issuer_announcement_wake
from crt_radar.issuer_disclosure_tables import dated_table_facts
from crt_radar.evidence_pack import build_evidence_pack
from crt_radar.gpt_handoff import run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures' / 'issuer_disclosures_20261005'
REGISTRY = load_registry(ROOT / 'CONFIG' / 'ISSUER_ANNOUNCEMENT_REGISTRY_V1.json')
SELECTED = {name:json.loads((FIXTURES/(name+'-selected.json')).read_text(encoding='utf-8')) for name in ('strategy','strive')}
EVENTS = [event for issuer,name in zip(REGISTRY['issuers'], ('strategy','strive'))
          for event in parse_sec_submissions(issuer,SELECTED[name],material_forms=REGISTRY['material_forms'],material_keywords=REGISTRY['material_title_keywords'])]
PROVENANCE = json.loads((FIXTURES / 'provenance.json').read_text(encoding='utf-8'))
NOW = max(int(datetime.fromisoformat(r['capture_file_written_at_utc']).timestamp() * 1000) for r in PROVENANCE) + 1000


def replay(root):
    registry = load_registry(ROOT / 'CONFIG' / 'ISSUER_ANNOUNCEMENT_REGISTRY_V1.json')
    discover = False
    def fetch(url, **kwargs):
        for issuer in registry['issuers']:
            if url == issuer['sec_submissions_url']:
                name = 'strategy' if issuer['issuer_id']=='STRATEGY_INC' else 'strive'
                payload = json.loads(json.dumps(SELECTED[name]))
                if not discover:
                    payload['filings']['recent'] = {k:[] for k in payload['filings']['recent']}
                return json.dumps(payload).encode(), 'application/json', url
            if url in {issuer.get('press_archive_url'),issuer.get('press_feed_url')}:
                return (b'{"GetPressReleaseListResult":[]}', 'application/json', url) if issuer['issuer_id']=='STRIVE_INC' else (b'<html></html>', 'text/html', url)
        for event in EVENTS:
            if url == event['source_url']:
                name = 'strategy' if event['issuer_id']=='STRATEGY_INC' else 'strive'
                return (FIXTURES/(name+'.html')).read_bytes(), 'text/html', url
        raise AssertionError('Unretained network request: '+url)
    opts = dict(state_path=root/'isolated_state.json', ledger_path=root/'events.jsonl', fetcher=fetch)
    baseline = run_issuer_announcement_cycle(registry, now_ms=NOW-1, **opts)
    assert baseline['state']=='NO_WAKE'
    discover = True
    wake = run_issuer_announcement_cycle(registry, now_ms=NOW, **opts)
    # No synthetic prices are introduced. Other market layers are explicitly absent.
    gate = {'run_id':'ISOLATED_REAL_ISSUER_REPLAY',
            'source_registry_hash':hashlib.sha256((ROOT/'CONFIG'/'SOURCE_REGISTRY_V1.2.json').read_bytes()).hexdigest(),
            'parsed':{}, 'evidence':[], 'blocked_reasons':[],
            'action_output':'NONE','external_action_authority':'NONE','external_action_performed':False}
    evidence = build_evidence_pack(gate, observation_db=root/'observations.sqlite3',
                                  generated_at_ms=NOW, issuer_announcement_wake=wake,
                                  reanalysis_wake={"state":"NO_WAKE", "reason":"BTC_SPOT_OBSERVATION_UNAVAILABLE",
                                      "analyst_reanalysis_requested":False, "action_output":"NONE",
                                      "external_action_authority":"NONE", "external_action_performed":False})
    notice = build_plain_language_notice(evidence)
    handoff = run_gpt_handoff_gate(evidence, notice, ledger_path=root/'handoff.jsonl')
    duplicate = run_issuer_announcement_cycle(registry, now_ms=NOW+1, **opts)
    for name, value in [('issuer',wake),('evidence',evidence),('notice',notice),('handoff',handoff),('duplicate',duplicate)]:
        (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    return wake,evidence,handoff,duplicate


class RealIssuerDisclosureTests(unittest.TestCase):
    def test_retained_official_bytes_match_provenance(self):
        for row in PROVENANCE:
            raw=(FIXTURES/(row['name']+'.html')).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])
            self.assertEqual(len(raw),row['bytes'])

    def test_strategy_required_facts_and_missing_diluted_shares(self):
        event=next(e for e in EVENTS if e['issuer_id']=='STRATEGY_INC')
        facts=_normalized_official_facts(event,(FIXTURES/'strategy.html').read_bytes(),observed_at_ms=NOW)
        values={f['fact_type']:f for f in facts}
        self.assertEqual(values['BTC_HOLDINGS']['value'],848000)
        self.assertEqual(values['ATM_SHARES_ISSUED']['value'],92894)
        self.assertNotIn('DILUTED_SHARES',values)
        self.assertEqual(values['BTC_HOLDINGS']['reported_context']['reported_as_of_date'],'2026-10-04')
        self.assertEqual(values['ATM_SHARES_ISSUED']['reported_context']['time_semantics'],'PERIOD_AGGREGATE_NOT_SINGLE_EXECUTION')

    def test_strive_required_facts_scopes_and_no_liquidation_inference(self):
        event=next(e for e in EVENTS if e['issuer_id']=='STRIVE_INC')
        facts=_normalized_official_facts(event,(FIXTURES/'strive.html').read_bytes(),observed_at_ms=NOW)
        values={f['fact_type']:f for f in facts}
        for key,value in {'BTC_HOLDINGS':29462,'DILUTED_SHARES':103714772,'WARRANTS_OUTSTANDING':23249706,
                          'STRIVE_STRC_HOLDINGS':505000,'STRIVE_STRC_FAIR_VALUE':50202000}.items():
            self.assertEqual(values[key]['value'],value)
            self.assertEqual(values[key]['reported_context']['reported_as_of_date'],'2026-10-02')
        self.assertEqual(values['DILUTED_SHARES']['reported_context']['share_basis'],'AFDS_EXCLUDES_TRADITIONAL_WARRANTS')
        self.assertFalse(any('LIQUIDATION' in k for k in values))

    def test_real_events_reach_evidence_wake_and_handoff_without_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            wake,evidence,handoff,duplicate=replay(Path(tmp))
        self.assertEqual(wake['new_event_count'],2)
        self.assertEqual(evidence['reanalysis_wake']['state'],'REANALYSIS_REQUESTED')
        self.assertIn('ISSUER_ANNOUNCEMENT',evidence['reanalysis_wake']['wake_sources'])
        self.assertEqual(handoff['state'],'GPT_HANDOFF_READY')
        self.assertIs(handoff['transport_performed'],False)
        self.assertEqual(duplicate['new_event_count'],0)
        compact=compact_issuer_announcement_wake(wake,generated_at_ms=NOW)
        expected={(f['fact_type'],f['value']) for e in wake['new_events'] for f in e['normalized_facts']}
        actual={(f['fact_type'],f['value']) for e in compact['new_events'] for f in e['normalized_facts']}
        self.assertEqual(expected,actual)
        self.assertTrue(all(f['reported_context'] for e in compact['new_events'] for f in e['normalized_facts']))
        self.assertEqual(handoff['source_evidence_pack_hash'], evidence['evidence_pack_hash'])
        self.assertIn('LATEST_ISSUER_ANNOUNCEMENT',handoff['required_inputs'])

    def test_comparison_uses_date_not_column_order(self):
        raw=(FIXTURES/'strive.html').read_text(encoding='utf-8')
        raw=raw.replace('September 25, 2026','January 1, 2027')
        rows=dated_table_facts(raw,'STRIVE')
        self.assertEqual(rows['BTC_HOLDINGS']['value'],27462)
        blocked=dated_table_facts(raw,'STRIVE',disclosed_at_ms=1791201597000)
        self.assertIsNone(blocked['BTC_HOLDINGS']['value'])
        raw=raw.replace('As of October 2, 2026','Unknown date').replace('As of January 1, 2027','Unknown date')
        self.assertIsNone(dated_table_facts(raw,'STRIVE')['BTC_HOLDINGS']['value'])

    def test_conflict_missing_and_undated_tables_do_not_fallback(self):
        raw=(FIXTURES/'strategy.html').read_text(encoding='utf-8')
        extra='<table><tr><td>As of October 4, 2026</td></tr><tr><td>Aggregate BTC Holdings</td></tr><tr><td>849000</td></tr></table>'
        rows=dated_table_facts(raw+extra,'STRATEGY')
        self.assertIsNone(rows['BTC_HOLDINGS']['value'])
        self.assertEqual(rows['ATM_SHARES_ISSUED']['value'],92894)
        rows=dated_table_facts(raw.replace('848,000','N/A'),'STRATEGY')
        self.assertIsNone(rows['BTC_HOLDINGS']['value'])
        rows=dated_table_facts(raw.replace('As of October 4, 2026','Unknown date'),'STRATEGY')
        self.assertIsNone(rows['BTC_HOLDINGS']['value'])

    def test_missing_comparison_fact_does_not_promote_balance_sheet_footnote(self):
        event=next(e for e in EVENTS if e['issuer_id']=='STRIVE_INC')
        raw=(FIXTURES/'strive.html').read_text(encoding='utf-8')
        raw=raw.replace('Assumed Fully Diluted Shares','Unavailable comparison label')
        facts=_normalized_official_facts(event,raw.encode('utf-8'),observed_at_ms=NOW)
        values={f['fact_type']:f['value'] for f in facts}
        self.assertNotIn('DILUTED_SHARES',values)
        self.assertEqual(values['BTC_HOLDINGS'],29462)

    def test_ambiguous_value_columns_periods_and_security_identity_block(self):
        ambiguous = '<table><tr><th>As of October 4, 2026</th></tr><tr><td>Aggregate BTC Holdings</td><td>100</td><td>200</td></tr></table>'
        self.assertIsNone(dated_table_facts(ambiguous,'STRATEGY')['BTC_HOLDINGS']['value'])
        raw=(FIXTURES/'strategy.html').read_text(encoding='utf-8')
        for changed in (raw.replace('During Period October 1, 2026 to October 4, 2026',
                                     'During Period October 1, 2026 to October 3, 2026'),
                        raw.replace('Security</', 'Unknown column</')):
            self.assertIsNone(dated_table_facts(changed,'STRATEGY')['ATM_SHARES_ISSUED']['value'])

    def test_cp950_cli_exit_zero_and_utf8_artifact_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            payload={'decision_excerpt':'Official disclosure \u2610 \u2014 \u4e2d\u6587','transport_performed':False}
            source=root/'input.json';source.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            target=root/'artifact.json'
            script="""import json,sys
from unittest.mock import patch
from pathlib import Path
from crt_radar import issuer_announcement_runner as r
payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
with patch.object(r,'run_issuer_announcement_cycle',return_value=payload):
    raise SystemExit(r.main(['--state',sys.argv[2]+'.state','--ledger',sys.argv[2]+'.ledger','--output',sys.argv[2]]))
"""
            env=dict(os.environ,PYTHONIOENCODING='cp950:strict',PYTHONPATH=str(ROOT/'src'))
            result=subprocess.run([sys.executable,'-c',script,str(source),str(target)],env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode('ascii',errors='replace'))
            self.assertEqual(json.loads(result.stdout.decode('cp950')),payload)
            self.assertEqual(json.loads(target.read_text(encoding='utf-8')),payload)
            self.assertIn('\u2610'.encode(),target.read_bytes())
