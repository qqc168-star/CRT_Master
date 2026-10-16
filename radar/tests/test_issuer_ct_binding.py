"""Synthetic archive tests, not live issuer evidence."""
from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from crt_radar.issuer_ratio_market_health_source import build_archived_issuer_ct_inputs, _document_url, ASSETS
from crt_radar.treasury_company_ct import build_treasury_company_ct
from crt_radar.daily_evidence_runner import run_daily_evidence
from crt_radar.gpt_handoff import _bridge_market_context
from test_first_evidence_slice import gate

NOW = 1790940900702
ASST = """0001920406 TEST ONLY
As of September 18, 2026 As of September 25, 2026
Cash and cash equivalents (in thousands) $ 200,000 $ 210,000
Bitcoin held 1,000 1,100 Assumed Fully Diluted Shares (4) 10,000 10,500
Assumed Fully Diluted Shares Outstanding represents Effective Common Shares Outstanding
plus shares underlying all potentially dilutive securities, including options and unvested RSUs.
Shares underlying Traditional Warrants are excluded from this figure. (5)
During the period from September 21, 2026 through September 25, 2026, Strive purchased 100 bitcoin
"""
MSTR = """0001050446 TEST ONLY USD Reserve is intended to support the payment of dividends and interest on its outstanding indebtedness. As of September 27, 2026, the balances of the USD Reserve and USD Cash were $1.00 billion and $0.20 billion, respectively.
During Period September 21, 2026 to September 27, 2026
$10.0 million in net proceeds from MSTR Stock sales were used to fund bitcoin purchases and $5.0 million in net proceeds from MSTR Stock sales were used to fund repurchases of STRC Stock
used $2.0 million of USD Cash to fund repurchases of STRC Stock
"""

# Synthetic period with the real disclosure's column shapes; not live acceptance.
MSTR_PERIOD = """0001050446 TEST ONLY
During Period September 21, 2026 to September 27, 2026
$21.0 million in bitcoin purchases were made using net proceeds from MSTR Stock sales
and $0.5 million in bitcoin purchases were made using USD Cash.
Strategy used $0.5 million of USD Cash to fund bitcoin purchases.
Net proceeds are presented net of sales commission.
Aggregate and average purchase prices are inclusive of fees and expenses.
<table><tr><td>During Period September 21, 2026 to September 27, 2026</td></tr>
<tr><td>Security Shares Sold Net Proceeds (in millions)</td></tr>
<tr><td>MSTR Stock</td><td>125,183</td><td>$ -</td><td>$ 21.0 (3)</td><td>$ 18,807.6</td></tr></table>
<table><tr><td>During Period September 21, 2026 to September 27, 2026</td></tr>
<tr><td>BTC Purchased Aggregate BTC Holdings</td></tr>
<tr><td>250</td><td>$ 21.5</td><td>$ 86,194</td><td>848,250</td><td>$ 64.00</td><td>$ 75,444</td></tr></table>
<table><tr><td>During Period September 21, 2026 to September 27, 2026</td></tr>
<tr><td>Security Shares Repurchased Aggregate Purchase Price (in millions)</td></tr>
<tr><td>STRC Stock (1)</td><td>1,932,145</td><td>$ 192.4</td></tr></table>
USD Reserve is intended to support the payment of dividends and interest on its outstanding indebtedness.
As of September 27, 2026, the balances of the USD Reserve and USD Cash were $4.88 billion and $640.5 million, respectively.
"""

class IssuerCtBindingTests(unittest.TestCase):
    def test_independent_btc_funding_uses_survive_missing_strc_or_cash_snapshot(self):
        self.items = []
        self.add('MSTR', '0001050446 TEST ONLY During Period September 21, 2026 to September 27, 2026 '
            '$21.0 million in net proceeds from MSTR Stock sales were used to fund bitcoin purchases. '
            'Strategy used $0.5 million of USD Cash to fund bitcoin purchases.', 30)
        rows = self.periods(self.inputs()['MSTR'])
        self.assertEqual({(r['source'], r['destination'], r['amount_usd']) for r in rows},
            {('MSTR_COMMON_ISSUANCE', 'BTC_PURCHASE', 21e6), ('USD_CASH', 'BTC_PURCHASE', .5e6)})
        self.assertTrue(all(r['execution_time'] is None for r in rows))

    def test_period_tables_keep_issuance_purchase_and_repurchase_without_inferred_claims(self):
        self.items = []
        item = self.add('MSTR', MSTR_PERIOD, 31)
        data = self.inputs()['MSTR']
        rows = {r['observation_id'].split(':')[-1]: r for r in self.periods(data)}
        self.assertEqual(len(rows), 5)  # Repeated cash wording is one source fact.
        self.assertEqual(rows['common-issuance']['new_common_shares_sold'], 125183)
        self.assertEqual(rows['common-issuance']['amount_usd'], 21e6)
        self.assertEqual(rows['btc-purchase-total']['btc_change'], 250)
        self.assertEqual(rows['btc-purchase-total']['amount_usd'], 21.5e6)
        self.assertEqual(rows['btc-purchase-total']['reported_average_price_usd'], 86194)
        self.assertIsNone(rows['btc-purchase'].get('btc_change'))
        repurchase = rows['strc-repurchase-total']
        self.assertEqual((repurchase['shares_repurchased'], repurchase['amount_usd']), (1932145, 192.4e6))
        self.assertEqual(repurchase['source'], 'FUNDING_SOURCE_UNRESOLVED')
        self.assertTrue(all(r.get('senior_claim_change_usd') is None and r.get('annual_carry_change_usd') is None for r in rows.values()))
        self.assertTrue(all(r.get('effective_time') is None and r['execution_time'] is None for r in rows.values()))
        self.assertTrue(all(r['raw_sha256'] == item['raw_sha256'] for r in rows.values()))
        self.assertEqual(data['funding_instruments'][0]['observed_funding_use_usd'], 21e6)
        self.assertEqual(rows['btc-purchase-total']['aggregation_role'], 'OVERLAPPING_TOTAL_NOT_ADDITIVE')

    def add_period_exhibit(self):
        parent = self.add('MSTR', '0001050446 TEST ONLY <a href="mstr-ex99_1.htm">Exhibit 99.1</a>', 32)
        raw = MSTR_PERIOD.replace('0001050446 TEST ONLY', 'TEST ONLY').encode()
        child = dict(parent, primary='mstr-ex99_1.htm', raw_sha256=hashlib.sha256(raw).hexdigest(),
            source_url=_document_url(ASSETS['MSTR']['cik'], parent['accession'], 'mstr-ex99_1.htm'),
            parent_document={k:parent[k] for k in ('primary','raw_sha256','retrieved_at_ms')})
        (self.root/'sec-disclosures'/f"MSTR-{child['accession']}-{child['primary']}.html").write_bytes(raw)
        self.items.append(child)
        return parent, child

    def test_linked_sec_exhibit_retains_own_hash_and_actual_local_visibility(self):
        self.items = []
        parent, child = self.add_period_exhibit()
        child['retrieved_at_ms'] = NOW
        data = self.inputs()['MSTR']
        rows = self.periods(data)
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row['raw_sha256'], child['raw_sha256'])
            self.assertEqual(row['source_ref'], child['source_url']+'#sha256='+child['raw_sha256'])
            self.assertEqual(row['source_evidence']['parent_document']['raw_sha256'], parent['raw_sha256'])
            self.assertEqual(row['first_seen_time'], NOW)
            self.assertEqual(row['retrieval_time'], NOW)
            self.assertNotIn('effective_time', row)
        self.assertEqual(self.periods(self.inputs(NOW-1)['MSTR']), [])

    def test_exhibit_needs_valid_parent_hash_link_cik_and_clock(self):
        for mode in ('hash', 'link', 'cik', 'future', 'accepted'):
            with self.subTest(mode=mode):
                self.items = []
                parent, child = self.add_period_exhibit()
                parent_path = self.root/'sec-disclosures'/f"MSTR-{parent['accession']}.html"
                if mode == 'hash':
                    child['parent_document']['raw_sha256'] = '0'*64
                elif mode in ('link','cik'):
                    raw = parent_path.read_bytes().replace(b'mstr-ex99_1.htm', b'unlinked.htm') if mode == 'link' else parent_path.read_bytes().replace(b'0001050446', b'0001920406')
                    parent_path.write_bytes(raw)
                    parent['raw_sha256'] = child['parent_document']['raw_sha256'] = hashlib.sha256(raw).hexdigest()
                elif mode == 'future':
                    parent['retrieved_at_ms'] = child['parent_document']['retrieved_at_ms'] = NOW+1
                else:
                    child['accepted'] = '2026-09-28T11:59:00Z'
                self.assertEqual(self.periods(self.inputs()['MSTR']), [])

    def test_missing_or_ambiguous_table_does_not_erase_independent_funding_fact(self):
        self.items = []
        table = '<table><tr><td>During Period Shares Repurchased Aggregate Purchase Price (in millions)</td></tr><tr><td>STRC Stock (1) 2 $ 3.0</td></tr></table>'
        self.add('MSTR', MSTR_PERIOD+table, 33)
        data = self.inputs()['MSTR']
        rows = self.periods(data)
        self.assertTrue(any(r['observation_id'].endswith(':btc-purchase') for r in rows))
        self.assertFalse(any(r['observation_id'].endswith(':strc-repurchase-total') for r in rows))
        self.assertIn('ISSUER_PERIOD_TABLE_AMBIGUOUS', str(data['source_binding']['blockers']))

    def test_period_source_facts_reach_pack_but_not_executed_health_routes(self):
        self.items = []
        self.add('MSTR', MSTR_PERIOD, 34)
        with patch('crt_radar.daily_evidence_runner.run_source_gate', return_value=gate(0)):
            pack = run_daily_evidence(None, observation_db=self.root/'period.sqlite3',
                issuer_ct_archive=self.root, now_ms=NOW, generated_at_ms=NOW)
        fact = next(f for f in pack['asset_facts']['items'] if f.get('fact_type') == 'ISSUER_CT_SOURCE_BINDING'
                    and f.get('issuer_id') == 'CIK-0001050446')
        self.assertEqual(len(self.periods({'source_binding':fact['evidence']})), 5)
        health = _bridge_market_context(pack)['common_equity_health']['assets']['MSTR']
        self.assertEqual(health['health_direction'], 'BLOCKED')
        self.assertIsNone(health['net_residual_value_per_diluted_share'])
        self.assertEqual(health['company_health']['capital_engine']['current_route_count'], 0)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'sec-disclosures').mkdir()
        self.items = []
        self.add('ASST', ASST, 1)
        self.add('MSTR', MSTR, 2)

    def add(self, asset, text, number):
        accession = f'0001234567-26-{number:06d}'
        primary = asset.lower() + '.htm'
        raw = ('<html><body>' + text + '</body></html>').encode()
        item = dict(asset=asset, accession=accession, primary=primary,
            source_url=_document_url(ASSETS[asset]['cik'], accession, primary),
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            accepted='2026-09-28T12:00:00Z', retrieved_at_ms=NOW - 1000)
        (self.root / 'sec-disclosures' / f'{asset}-{accession}.html').write_bytes(raw)
        self.items.append(item)
        self.save()
        return item

    def save(self):
        (self.root / 'sec-disclosures' / 'manifest.json').write_text(json.dumps(self.items))

    def inputs(self, now=NOW):
        self.save()
        return build_archived_issuer_ct_inputs(self.root, as_of_ms=now)

    def ct(self, asset='ASST', now=NOW):
        return build_treasury_company_ct(**self.inputs(now)[asset])

    def test_same_filing_afds_ratio_reaches_organ(self):
        a = self.ct()['organs']['per_share_asset_engine']
        self.assertAlmostEqual(a['btc_per_diluted_share_change_pct'], (1100 / 10500) / .1 - 1)
        self.assertEqual(a['direction'], 'IMPROVING')
        self.assertIn('EXCLUDES_TRADITIONAL_WARRANTS', a['current']['basis_ref'])

    def test_date_precision_and_four_clocks_retained(self):
        r = self.ct()['organs']['per_share_asset_engine']['current']
        self.assertEqual(r['source_evidence']['effective_precision'], 'DATE')
        self.assertEqual(r['source_evidence']['effective_date'], '2026-09-25')
        self.assertLess(r['effective_time'], r['disclosure_time'])
        self.assertLess(r['disclosure_time'], r['first_seen_time'])
        self.assertEqual(r['first_seen_time'], r['retrieval_time'])

    def test_later_acquisition_cannot_enter_earlier_replay(self):
        ct = self.ct(now=NOW - 1001)
        self.assertEqual(ct['organs']['per_share_asset_engine']['state'], 'BLOCKED')
        self.assertIn('NOT_LOCALLY_VISIBLE_AT_REPLAY', str(ct['blockers']))

    def test_future_disclosure_is_rejected(self):
        self.items[0]['accepted'] = '2027-01-01T00:00:00Z'
        self.assertIn('SOURCE_CLOCK_INVALID', str(self.ct()['blockers']))

    def test_missing_acceptance_is_not_inferred(self):
        self.items[0]['accepted'] = ''
        self.assertEqual(self.ct()['organs']['per_share_asset_engine']['state'], 'BLOCKED')

    def test_missing_retrieval_is_not_inferred(self):
        self.items[0].pop('retrieved_at_ms')
        self.assertIn('SOURCE_CLOCK_INVALID', str(self.ct()['blockers']))

    def test_hash_mismatch_blocks_only_affected_source(self):
        self.items[0]['raw_sha256'] = '0' * 64
        data = self.inputs()
        self.assertEqual(build_treasury_company_ct(**data['ASST'])['organs']['per_share_asset_engine']['state'], 'BLOCKED')
        self.assertEqual(len(self.periods(data['MSTR'])), 3)

    def test_cross_company_url_cannot_supply_facts(self):
        self.items[0]['source_url'] = self.items[1]['source_url']
        self.assertIn('SEC_ISSUER_SOURCE_MISMATCH', str(self.ct()['blockers']))

    def test_document_cik_is_required(self):
        self.items = []
        self.add('ASST', ASST.replace('0001920406', '0001050446'), 3)
        self.assertIn('SEC_DOCUMENT_CIK_MISMATCH', str(self.ct()['blockers']))

    def test_afds_basis_missing_does_not_erase_other_issuer(self):
        self.items = []
        self.add('ASST', ASST.replace('Traditional Warrants are excluded', 'Scope unspecified'), 4)
        self.assertIn('AFDS_BASIS_UNVERIFIED', str(self.ct()['blockers']))

    def test_conflicting_same_date_is_not_latest_wins(self):
        self.add('ASST', ASST.replace('1,000 1,100', '1,000 1,200'), 5)
        ct = self.ct()
        self.assertEqual(ct['organs']['per_share_asset_engine']['state'], 'BLOCKED')
        self.assertIn('CONFLICTING_FACTS_AT_SAME_EFFECTIVE_TIME', str(ct['blockers']))

    def test_same_values_keep_explicit_same_document_pair(self):
        self.add('ASST', ASST, 6)
        a = self.ct()['organs']['per_share_asset_engine']
        self.assertEqual(len(a['observations']), 2)
        self.assertEqual(a['previous']['source_ref'], a['current']['source_ref'])

    def test_mstr_adso_effective_clock_not_invented(self):
        ct = self.ct('MSTR')
        self.assertEqual(ct['organs']['per_share_asset_engine']['state'], 'BLOCKED')
        self.assertIn('ADSO_EFFECTIVE_TIME_UNRESOLVED', str(ct['blockers']))
        self.assertEqual(ct['organs']['capital_conversion']['state'], 'BLOCKED')

    def test_no_missing_burden_components_filled_with_zero(self):
        r = self.ct()['organs']['capital_burden_resilience']['current']
        self.assertEqual(r['usd_cash_usd'], 210000000)
        for key in ('debt_principal_usd', 'preferred_liquidation_claims_usd', 'annual_carry_usd', 'senior_claims_usd'):
            self.assertIsNone(r[key])

    def test_reserve_not_double_counted(self):
        r = self.ct('MSTR')['organs']['capital_burden_resilience']['current']
        self.assertEqual(r['usable_liquidity_usd'], 1200000000)
        self.assertIsNone(r['cash_usability_basis_ref'])
        self.assertIsNone(r['carry_coverage_years'])

    def test_funding_use_is_not_usable_capacity(self):
        r = self.ct('MSTR')['organs']['funding_engine']['instruments'][0]
        self.assertEqual(r['observed_funding_use_usd'], 15000000)
        self.assertIsNone(r['usable_capacity_usd'])
        self.assertIsNone(r['annual_cost_rate_pct'])

    def test_capital_routes_do_not_invent_consequences(self):
        events = self.periods(self.inputs()['MSTR'])
        self.assertEqual(len(events), 3)
        self.assertEqual(sum(e['amount_usd'] for e in events), 17000000)
        self.assertTrue(all(e.get('senior_claim_change_usd') is None for e in events))
        self.assertTrue(all(e.get('annual_carry_change_usd') is None for e in events))
        self.assertEqual(sum(e.get('liquidity_change_usd') or 0 for e in events), -2000000)

    def test_purchase_does_not_attribute_share_change_or_rounded_cost(self):
        e = self.periods(self.inputs()['ASST'])[0]
        self.assertEqual(e['btc_change'], 100)
        self.assertIsNone(e['amount_usd'])
        self.assertIsNone(e.get('diluted_share_change'))
        self.assertEqual(e['source'], 'FUNDING_SOURCE_UNRESOLVED')

    def test_future_sata_rate_not_backfilled_as_september_carry(self):
        self.add('ASST', "0001920406 TEST ONLY rate per annum on the Company’s SATA Stock at 13.00%, effective for periods commencing on or after October 1, 2026", 7)
        ct = self.ct()
        self.assertIn('FORWARD_SENSITIVITY_NOT_HISTORICAL_CARRY', str(ct['source_binding']))
        self.assertIsNone(ct['organs']['capital_burden_resilience']['current']['annual_preferred_distributions_usd'])

    def test_management_action_has_no_quality_score(self):
        ct = self.ct('MSTR')
        self.assertEqual(len(ct['organs']['management_evidence']['events']), 0)
        self.assertEqual(ct['action_output'], 'NONE')
        self.assertEqual(ct['external_action_authority'], 'NONE')
        self.assertNotIn('score', ct['organs']['management_evidence'])

    def test_daily_pack_health_and_existing_gpt_projection(self):
        self.save()
        with patch('crt_radar.daily_evidence_runner.run_source_gate', return_value=gate(0)):
            pack = run_daily_evidence(None, observation_db=self.root / 'test.sqlite3',
                issuer_ct_archive=self.root, now_ms=NOW, generated_at_ms=NOW)
        health = pack['common_equity_health']['assets']['ASST']
        self.assertGreater(health['btc_per_diluted_share_change_pct'], 0)
        self.assertTrue(any(f['fact_type'] == 'TREASURY_COMPANY_CT' for f in pack['asset_facts']['items']))
        self.assertFalse(any(e.get('ct_section') in ('capital_conversion', 'management_evidence') for e in pack['decision_relevant_events']['items']))
        self.assertTrue(any(f['fact_type'] == 'ISSUER_CT_SOURCE_BINDING' for f in pack['asset_facts']['items']))
        projected = _bridge_market_context(pack)
        self.assertEqual(projected['common_equity_health']['assets']['ASST']['btc_per_diluted_share_change_pct'], health['btc_per_diluted_share_change_pct'])
        dim = health['company_health']['dimensions']['per_share_asset_engine']
        self.assertEqual(dim['claims']['btc_per_diluted_share']['direction'], 'IMPROVING')
        self.assertEqual(pack['common_equity_health']['action_output'], 'NONE')
        self.assertIsNone(health['net_residual_value_per_diluted_share'])

    def test_ambiguous_two_input_lanes_rejected(self):
        with self.assertRaises(ValueError):
            run_daily_evidence(None, observation_db=self.root/'unused', issuer_ct_archive=self.root,
                treasury_company_ct_inputs={}, generated_at_ms=NOW)

    def test_archive_unchanged(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        self.inputs()
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_ct_projection_does_not_use_future_retrieval(self):
        from crt_radar.portfolio_allocation_context import build_common_equity_health
        from crt_radar.treasury_company_ct import add_treasury_company_ct
        pack = {"generated_at_ms": NOW, **{k: {"items": [], "section_state": "PARTIAL"} for k in ("asset_facts", "decision_relevant_events", "blockers")}}
        inputs = self.inputs()['ASST']
        for r in inputs['asset_history']:
            r['retrieval_time'] = NOW + 1
        add_treasury_company_ct(pack, inputs)
        h = build_common_equity_health(pack)['assets']['ASST']
        self.assertIsNone(h['btc_per_diluted_share'])
        self.assertIsNone(h['btc_per_diluted_share_change_pct'])

    def test_conflicting_valuation_and_ct_claim_is_blocked(self):
        from crt_radar.portfolio_allocation_context import build_common_equity_health
        from crt_radar.treasury_company_ct import add_treasury_company_ct
        pack = {"generated_at_ms": NOW, **{k: {"items": [], "section_state": "PARTIAL"} for k in ("asset_facts", "decision_relevant_events", "blockers")}}
        add_treasury_company_ct(pack, self.inputs()['ASST'])
        pack['asset_facts']['items'].append(dict(fact_type='TREASURY_VALUATION_CONTEXT', asset_id='ASST', evidence={'current_btc_per_diluted_share': 99}))
        h = build_common_equity_health(pack)['assets']['ASST']
        self.assertIsNone(h['btc_per_diluted_share'])
        self.assertIn('CT_VALUATION_BTC_SHARE_CONFLICT', h['blockers'])

    def test_disclosed_nominal_remainder_is_not_usable(self):
        from test_treasury_company_ct import funding, kwargs
        d = kwargs()
        r = funding()
        r.pop('program_capacity_usd')
        r.pop('cumulative_program_usage_usd')
        r.pop('usable_capacity_usd')
        r['reported_remaining_nominal_capacity_usd'] = 800
        d['funding_instruments'] = [r]
        x = build_treasury_company_ct(**d)['organs']['funding_engine']['instruments'][0]
        self.assertEqual(x['remaining_nominal_capacity_usd'], 800)
        self.assertIsNone(x['usable_capacity_usd'])

    def test_missing_mnav_does_not_erase_qualified_ct_asset(self):
        ct = self.ct()
        self.assertEqual(ct['price_financing_state']['state'], 'BLOCKED')
        self.assertGreater(ct['organs']['per_share_asset_engine']['btc_per_diluted_share_change_pct'], 0)

    def test_zero_denominator_is_scoped_not_global_failure(self):
        self.items = []
        self.add('ASST', ASST.replace('10,000 10,500', '10,000 0'), 9)
        self.assertIn('SEC_ASSET_SCHEMA_INVALID', str(self.ct()['blockers']))

    def test_reserve_usability_requires_explicit_source_statement(self):
        self.items = []
        self.add('MSTR', MSTR.replace('intended to support the payment of dividends and interest on its outstanding indebtedness', 'use unspecified'), 10)
        ct = self.ct('MSTR')
        self.assertEqual(ct['organs']['capital_burden_resilience']['current']['usable_liquidity_usd'], 200000000)
        self.assertIn('RESERVE_USABILITY_OR_NONOVERLAP_UNVERIFIED', str(ct['blockers']))

    @staticmethod
    def periods(data):
        return [o for o in data['source_binding']['observations'] if o.get('claim') == 'PERIOD_CAPITAL_FLOW']

    def test_asst_cross_document_cash_conflict_different_basis(self):
        # Reproduces the reviewed failure: same date/scope, different document
        # hashes (and therefore different basis_ref), conflicting cash values.
        later = self.add('ASST', ASST.replace('$ 210,000', '$ 211,000'), 11)
        later['accepted'] = '2026-09-29T12:00:00Z'
        d = self.inputs()['ASST']
        self.assertIsNone(d['burden_current']['usd_cash_usd'])
        conflict = d['source_binding']['cash_conflicts'][0]
        self.assertEqual({o['value'] for o in conflict['observations']}, {210000000, 211000000})
        self.assertEqual(len({o['basis_ref'] for o in conflict['observations']}), 2)
        self.assertGreater(build_treasury_company_ct(**d)['organs']['per_share_asset_engine']['btc_per_diluted_share_change_pct'], 0)

    def test_mstr_cross_document_cash_conflict(self):
        self.add('MSTR', MSTR.replace('$0.20 billion', '$0.21 billion'), 12)
        d = self.inputs()['MSTR']
        self.assertIsNone(d['burden_current']['usd_cash_usd'])
        self.assertEqual(d['burden_current']['usd_reserve_usd'], 1e9)
        self.assertIn('CONFLICTING_CASH_AT_SAME_EFFECTIVE_TIME', str(d['source_binding']['blockers']))

    def test_cash_conflict_blocks_downstream_liquidity_only(self):
        self.add('ASST', ASST.replace('$ 210,000', '$ 211,000'), 13)
        with patch('crt_radar.daily_evidence_runner.run_source_gate', return_value=gate(0)):
            pack = run_daily_evidence(None, observation_db=self.root/'conflict.sqlite3',
                issuer_ct_archive=self.root, now_ms=NOW, generated_at_ms=NOW)
        health = _bridge_market_context(pack)['common_equity_health']['assets']['ASST']
        self.assertIsNone(health['liquidity_change_usd'])
        self.assertGreater(health['btc_per_diluted_share_change_pct'], 0)

    def test_economic_scope_not_document_basis_controls_cash_conflict(self):
        from copy import deepcopy
        from crt_radar.issuer_ratio_market_health_source import _reconcile_archived_cash
        row = self.inputs()['ASST']['burden_current']
        for field, replacement in [('definition', 'RESTRICTED_CASH'), ('accounting_scope', 'SUBSIDIARY_ONLY'), ('currency', 'EUR')]:
            with self.subTest(field=field):
                other = deepcopy(row)
                other['usd_cash_usd'] += 1
                other['source_evidence']['cash_claim_scopes']['usd_cash_usd'][field] = replacement
                _, conflicts = _reconcile_archived_cash([row, other])
                self.assertEqual(conflicts, [])
        other = deepcopy(row)
        other['basis_ref'] = 'ANOTHER_DOCUMENT'
        _, conflicts = _reconcile_archived_cash([row, other])
        self.assertEqual(conflicts, [])
        other['usd_cash_usd'] += 1
        _, conflicts = _reconcile_archived_cash([row, other])
        self.assertEqual(len(conflicts), 1)

    def test_asst_prior_date_conflict_cannot_hide_behind_latest_pair(self):
        self.add('ASST', ASST.replace('$ 200,000', '$ 201,000'), 14)
        d = self.inputs()['ASST']
        self.assertIsNone(d['burden_previous']['usd_cash_usd'])
        self.assertEqual(d['burden_current']['usd_cash_usd'], 210000000)

    def test_period_end_is_never_action_effective_time(self):
        inputs = self.inputs()
        for asset, end in [('MSTR', '2026-09-27'), ('ASST', '2026-09-25')]:
            ct = build_treasury_company_ct(**inputs[asset])
            self.assertEqual(ct['organs']['capital_conversion']['events'], [])
            self.assertEqual(ct['organs']['management_evidence']['events'], [])
            for row in self.periods(inputs[asset]):
                self.assertEqual(row['period_start_date'], '2026-09-21')
                self.assertEqual(row['period_end_date'], end)
                self.assertNotIn('effective_time', row)
                self.assertIsNone(row['execution_time'])
                self.assertFalse(row['active_for_calculation'])

    def test_missing_period_keeps_amount_without_inventing_endpoint(self):
        self.items = []
        self.add('MSTR', MSTR.replace('During Period September 21, 2026 to September 27, 2026', ''), 15)
        rows = self.periods(self.inputs()['MSTR'])
        self.assertEqual(sum(r['amount_usd'] for r in rows), 17000000)
        self.assertTrue(all('period_end_date' not in r and r['period_candidates'] == [] for r in rows))
        self.assertEqual(self.ct('MSTR')['organs']['capital_conversion']['events'], [])

    def test_asst_stock_and_future_dividend_are_not_funding_proceeds(self):
        self.add('ASST', '0001920406 rate per annum on the Company’s SATA Stock at 13.00%, effective for periods commencing on or after October 1, 2026', 16)
        d = self.inputs()['ASST']
        self.assertEqual(d['funding_instruments'], [])
        self.assertEqual(build_treasury_company_ct(**d)['organs']['funding_engine']['state'], 'BLOCKED')

    def test_reserve_conflict_preserves_cash_but_blocks_liquidity_total(self):
        self.add('MSTR', MSTR.replace('$1.00 billion', '$1.01 billion'), 17)
        ct = self.ct('MSTR')
        row = ct['organs']['capital_burden_resilience']['current']
        self.assertEqual(row['usd_cash_usd'], 200000000)
        self.assertIsNone(row['usd_reserve_usd'])
        self.assertIsNone(row['usable_liquidity_usd'])
        self.assertIn('CASH_COMPONENT_CONFLICT', str(ct['blockers']))

    def test_unknown_funding_period_cannot_take_cash_snapshot_date(self):
        self.items = []
        self.add('MSTR', MSTR.replace('During Period September 21, 2026 to September 27, 2026', ''), 18)
        ct = self.ct('MSTR')
        self.assertIsNone(ct['organs']['funding_engine']['instruments'][0]['observed_funding_use_usd'])
        self.assertIn('FUNDING_USE_PERIOD_UNRESOLVED', str(ct['blockers']))

    def test_optional_provenance_does_not_break_existing_burden_input(self):
        from test_treasury_company_ct import kwargs
        data = kwargs()
        data['burden_current']['source_evidence'] = None
        self.assertIsNotNone(build_treasury_company_ct(**data)['organs']['capital_burden_resilience']['current'])
