"""Deterministic offline fixtures only; never used as live source proof."""
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from crt_radar import btc_etf_intake as intake
from crt_radar.evidence_pack import build_evidence_pack, _sha256
from crt_radar.gpt_handoff import build_minimized_bridge_payload, run_gpt_handoff_gate
from crt_radar.plain_language_notice import build_plain_language_notice
from test_first_evidence_slice import gate
from test_gpt_handoff import bridge_pack, pack as wake_pack

NOW = int(datetime(2026, 9, 30, 12, tzinfo=timezone.utc).timestamp()*1000)
TICKERS = ['IBIT', 'FBTC', 'BITB', 'ARKB', 'BTCO', 'EZBC', 'BRRR', 'HODL', 'BTCW', 'GBTC', 'BTC', 'MSBT']


def fixture():
    days = []
    for n in range(30):
        day = date(2026, 8, 31)+timedelta(days=n)
        if day.weekday() >= 5 or day == date(2026, 9, 7):
            continue
        values = dict.fromkeys(TICKERS, 0.0)
        values.update(IBIT=100.0, BITB=-20.0)
        days.append(dict(date=day.isoformat(), perEtfUsd=values, netFlowUsd=80.0))
    return dict(units='USD', license=intake.LICENSE, sources='offline test',
                attribution='offline test', updatedThrough='2026-09-29', days=days)


def envelope(data=None):
    raw = json.dumps(fixture() if data is None else data)
    return dict(source_id=intake.SOURCE, source_url=intake.URL, retrieved_at_ms=NOW,
                evidence_hash=hashlib.sha256(raw.encode()).hexdigest(), raw_json=raw)


class BtcEtfIntakeTests(unittest.TestCase):
    def normalize(self, data=None):
        return intake.normalize(envelope(data), as_of_ms=NOW)

    def test_calendar_sums_and_reported_zero_breadth(self):
        r = self.normalize()
        self.assertEqual([r['horizons'][h]['value'] for h in ('1D', '7D', '30D')], [80, 400, 1680])
        self.assertEqual([len(r['horizons'][h]['session_dates']) for h in ('1D', '7D', '30D')], [1, 5, 21])
        self.assertEqual(r['breadth']['positive_fund_count'], 1)
        self.assertEqual(r['breadth']['negative_fund_count'], 1)
        self.assertEqual(r['breadth']['reported_zero_fund_count'], 10)
        self.assertEqual(r['balance']['coverage_state'], 'BLOCKED')

    def test_null_is_not_zero_and_missing_fund_scope_is_constant(self):
        d = fixture(); d['days'][-2]['perEtfUsd']['IBIT'] = None
        r = self.normalize(d)
        self.assertEqual(r['horizons']['1D']['value'], 80)
        self.assertEqual(r['horizons']['7D']['value'], -100)
        self.assertEqual(r['horizons']['7D']['coverage_state'], 'PARTIAL')
        self.assertNotIn('IBIT', r['horizons']['7D']['scope_ids'])
        d['days'][-1]['perEtfUsd']['MSBT'] = None
        r = self.normalize(d)
        self.assertEqual(r['breadth']['reported_zero_fund_count'], 9)
        self.assertEqual(r['breadth']['coverage_state'], 'PARTIAL')

    def test_missing_session_blocks_only_affected_horizon(self):
        d = fixture(); del d['days'][0]
        r = self.normalize(d)
        self.assertEqual(r['horizons']['7D']['coverage_state'], 'COMPLETE')
        self.assertIsNone(r['horizons']['30D']['value'])
        self.assertEqual(r['horizons']['30D']['coverage_state'], 'BLOCKED')

    def test_missing_map_blocks_without_using_aggregate(self):
        d = fixture(); d['days'][-1]['perEtfUsd'] = None
        r = self.normalize(d)
        self.assertIsNone(r['horizons']['1D']['value'])
        self.assertIsNone(r['breadth']['positive_fund_count'])

    def test_hash_future_retrieval_and_source_identity_rejected(self):
        for key, value in [('evidence_hash', 'bad'), ('retrieved_at_ms', NOW+1), ('source_id', 'OTHER')]:
            e = envelope(); e[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                intake.normalize(e, as_of_ms=NOW)

    def test_units_license_duplicate_nonfinite_and_schema_rejected(self):
        variants = []
        for key, value in [('units', 'USD millions'), ('license', 'unknown')]:
            d = fixture(); d[key] = value; variants.append(d)
        d = fixture(); d['days'].append(d['days'][-1]); variants.append(d)
        d = fixture(); d['days'][-1]['perEtfUsd']['IBIT'] = float('nan'); variants.append(d)
        variants.extend([[], dict(fixture(), days=[7])])
        for d in variants:
            with self.subTest(data=str(d)[:45]), self.assertRaises(ValueError):
                self.normalize(d)

    def test_stale_not_carried_forward_and_future_session_rejected(self):
        r = intake.normalize(envelope(), as_of_ms=NOW+86400000)
        self.assertIsNone(r['horizons']['1D']['value'])
        self.assertEqual(r['horizons']['1D']['reason'], 'STALE_SOURCE')
        d = fixture(); d['days'][-1]['date'] = d['updatedThrough'] = '2026-09-30'
        with self.assertRaises(ValueError): self.normalize(d)

    def test_active_unknown_fund_rejected_but_old_provider_history_not_our_universe(self):
        d = fixture(); d['days'][-1]['perEtfUsd']['OTHER'] = 10
        with self.assertRaisesRegex(ValueError, 'UNIVERSE_CONFLICT'): self.normalize(d)
        d = fixture(); d['days'].insert(0, dict(date='2024-01-11', perEtfUsd={'DEFI': 10}))
        self.assertEqual(len(self.normalize(d)['horizons']['30D']['scope_ids']), 12)

    def test_effective_membership_does_not_expand_past_basket(self):
        real = intake._contract
        def contract(name):
            result = real(name)
            if 'PUBLIC_SOURCE_AUTHORITY' in name:
                result = deepcopy(result)
                next(p for p in result['decisions']['US_SPOT_BTC_ETP_POINT_IN_TIME']['universe']['members'] if p['ticker'] == 'MSBT')['membership_effective_from'] = '2026-09-29'
            return result
        with patch.object(intake, '_contract', side_effect=contract): r = self.normalize()
        self.assertEqual(len(r['horizons']['1D']['scope_ids']), 12)
        self.assertNotIn('MSBT', r['horizons']['7D']['scope_ids'])

    def test_pack_wiring_hash_formal_firewall_and_claim_scoped_balance(self):
        with tempfile.TemporaryDirectory() as td:
            kwargs = dict(observation_db=Path(td)/'test.db', generated_at_ms=NOW)
            before = build_evidence_pack(gate(0), **kwargs)
            after = build_evidence_pack(gate(0), btc_etf_archive=envelope(), **kwargs)
        for field in ('layers', 'formal_candidate', 'model_status', 'authority', 'pack_state'):
            self.assertEqual(before[field], after[field])
        self.assertEqual(len([f for f in after['asset_facts']['items'] if f.get('source_id') == intake.SOURCE]), 2)
        b = [b for b in after['blockers']['items'] if b.get('source_id') == intake.SOURCE]
        self.assertEqual([x['affected_ids'] for x in b], [[intake.BALANCE]])
        supplied = after.pop('evidence_pack_hash')
        self.assertEqual(supplied, _sha256(after))

    def test_bad_archive_becomes_metric_blockers_not_pipeline_exception(self):
        p = {'generated_at_ms': NOW, 'asset_facts': {'items': []}, 'blockers': {'items': []}}
        intake.add_to_pack(p, {'raw_json': 'bad'})
        self.assertFalse(p['asset_facts']['items'])
        self.assertEqual(len(p['blockers']['items']), 3)

    def test_downstream_preserves_facts_balance_warning_and_payload_limit(self):
        p = bridge_pack(wake_pack(evidence_hash='a'*64, requested=True))
        p.update(generated_at_ms=NOW, asset_facts={'items': []}, blockers={'items': []})
        intake.add_to_pack(p, envelope())
        with tempfile.TemporaryDirectory() as td:
            handoff = run_gpt_handoff_gate(p, build_plain_language_notice(p), ledger_path=Path(td)/'ledger.jsonl')
            bridge = build_minimized_bridge_payload(p, handoff)
        etf = bridge['market_context']['btc_etf_evidence']
        self.assertEqual(etf[intake.FLOW]['30D'][0], 1680)
        self.assertEqual(etf[intake.BREADTH][0], 1)
        self.assertTrue(etf[intake.BALANCE].startswith('BLOCKED:'))
        self.assertIn('research only', etf['semantics'])
        self.assertIn('not historical publication proof', etf['semantics'])
        self.assertLess(len(json.dumps(bridge, ensure_ascii=False, separators=(',', ':')).encode()), 16384)


if __name__ == '__main__':
    unittest.main()
