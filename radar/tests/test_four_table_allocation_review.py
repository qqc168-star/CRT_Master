from copy import deepcopy
import json
from pathlib import Path
import re
import unittest

from crt_radar.capital_posture_context import build_capital_posture_context, render_allocation_review_table
from crt_radar.gold_research_context import _hash
from test_capital_posture_context import fixture, observation, NOW, DAY
from test_capital_decision_closure import source_fixture, recommendation, item, leg, match_scopes, provider_response, full_provider_response
from crt_radar import capital_decision_closure as capital
from scripts.run_controlled_capital_acceptance import synthetic_case


def table_fixture():
    data, pack, _ = fixture(step=1)
    allocation = pack['portfolio_allocation_context']
    allocation['suggested_mstr_pct'], allocation['suggested_asst_pct'] = 65, 35
    pack['common_equity_health']['assets']['MSTR']['health_direction'] = 'STABLE'
    pack['common_equity_health']['assets']['ASST']['health_direction'] = 'STABLE'
    # Synthetic Q4 facts only; an income total or side-job flag never supplies a split.
    income = {'schema_version':'CRT_DUAL_FIXED_INCOME_V0.1','as_of_ms':NOW,
        'assets':{asset:{'holding_state':'AVAILABLE','current_terms':{'state':'AVAILABLE'}} for asset in ('STRC','SATA')}}
    income['summary_hash']=_hash(income)

    case = {
        'state': 'RESEARCH_EVIDENCED', 'as_of_ms': NOW,
        'income_summary_hash': income['summary_hash'],
        'recommended_strc_sata_pct': [40,60],
        'asset_evidence_refs': {asset: f'income_engine.assets.{asset}.current_terms'
                                for asset in ('STRC','SATA')},
        'economic_reasons': {
            'income_tradeoff':'合成收益比較；非真實投資研究',
            'issuer_risk':'合成發行人風險比較；待 Q5 檢驗',
            'capital_preservation':'合成資本保全檢查；非已證實回程',
            'round_trip_friction':'合成雙向摩擦比較；非即時價差',
            'cash_alternative':'合成現金替代方案比較',
            'allocation_reason':'合成研究分配理由；不形成交易權限',
            'invalidation':'來源、現金、發行人或回程條件失效時重審',
        },
    }
    pack['asset_strategy_delta'] = {'state': 'RESEARCH_ONLY', 'income_engine':income,
                                    'strc_sata_allocation_case':case}
    pack['private_context'] = {'profile': {'capital_reconciliation': {
        'broker_observed': source_fixture(at=NOW)['broker_observation']}}}
    pack['evidence_pack_hash'] = _hash({k:v for k,v in pack.items() if k != 'evidence_pack_hash'})
    data['current_rail']['parent_evidence_pack_hash'] = pack['evidence_pack_hash']
    data['allocation_review'] = observation('ALLOCATION_REVIEW', reviewed_by='ANALYST',
        parent_evidence_pack_hash=pack['evidence_pack_hash'], allocation_source_hash=_hash(allocation),

        q4_source_hash=_hash(pack['asset_strategy_delta']), strc_sata_within_fixed_pct=[40,60],
        q4_allocation_case_hash=_hash(case),
        allocation_adjustment_scopes={'MSTR':'MSTR-rebalance'})
    return data, pack, None


def rows(context):
    return {r['asset']:r for r in context['allocation_review_table']['rows']}


def display_envelope(context, rec, *, wrong_event=False, wrong_capital=False):
    # A new synthetic event at its native clock, never a relabeled real archive.
    payload=synthetic_case(at_ms=NOW,source_main_sha='a'*40)['payload']
    payload['event']['source_evidence_pack_hash']=context['parent_evidence_pack_hash'] if not wrong_event else 'a'*64
    payload['bridge_payload_hash']=capital.digest({k:v for k,v in payload.items() if k!='bridge_payload_hash'})
    source=source_fixture(payload,at=NOW+1 if wrong_capital else NOW)
    source['evidence_validity']['as_of_ms']=NOW
    match_scopes(source,rec)
    return capital.build_envelope(payload,source,at_ms=NOW+1 if wrong_capital else NOW,full_decision=True)


class FourTableAllocationTests(unittest.TestCase):
    def test_two_65_35_scopes_and_total_portfolio_sum(self):
        out = build_capital_posture_context(*table_fixture())
        table = out['allocation_review_table']
        r = rows(out)
        self.assertAlmostEqual(table['target_total_pct'],100)
        self.assertAlmostEqual(r['MSTR']['target_pct'],.92*35*.65)
        self.assertAlmostEqual(r['ASST']['target_pct'],.92*35*.35)
        self.assertAlmostEqual(r['STRC']['target_pct'],.92*65*.40)
        self.assertAlmostEqual(r['SATA']['target_pct'],.92*65*.60)
        self.assertAlmostEqual(sum(x['current_pct'] for x in r.values()),100)
        for row in r.values():
            self.assertAlmostEqual(row['delta_pct'],row['target_pct']-row['current_pct'])
            self.assertAlmostEqual(row['delta_usd'],row['target_usd']-row['current_usd'])
            self.assertIsNone(row['qualified_share_counts'])
        self.assertEqual(out['current_rail_step']['step'],1)
        self.assertEqual(out['eligible_next_posture']['state'],'NOT_EVALUATED')

    def test_unreasoned_strc_sata_ratio_is_not_displayed_as_qualified(self):
        data, pack, gold = table_fixture()
        case = pack['asset_strategy_delta']['strc_sata_allocation_case']
        case['economic_reasons']['capital_preservation'] = ''
        # Recompute all source hashes, so the economic requirement, not a stale hash,
        # is the precise reason for blocking the split.
        data['allocation_review']['q4_allocation_case_hash'] = _hash(case)
        data['allocation_review']['q4_source_hash'] = _hash(pack['asset_strategy_delta'])
        pack['evidence_pack_hash'] = _hash({k:v for k,v in pack.items() if k!='evidence_pack_hash'})
        for k in ('current_rail','allocation_review'):
            data[k]['parent_evidence_pack_hash'] = pack['evidence_pack_hash']
        out = rows(build_capital_posture_context(data, pack, gold))
        self.assertIsNone(out['STRC']['target_pct'])
        self.assertIsNone(out['SATA']['target_pct'])
        self.assertIsNotNone(out['MSTR']['target_pct'])

    def test_duplicate_lots_are_aggregated_and_balance_to_total(self):
        from crt_radar.portfolio_allocation_context import _portfolio_state
        profile = {'state':'AVAILABLE','profile': {
            'capital_state_status':{'state':'AVAILABLE'},
            'holdings':[{'asset':'MSTR','quantity':2},{'asset':'MSTR','quantity':3},
                        {'asset':'STRC','quantity':1}],
            'cash':{'available_usd':100,'reserved_usd':0}}}
        state = _portfolio_state(profile,{'MSTR':10,'STRC':100})
        self.assertEqual(state['state'],'AVAILABLE')
        self.assertAlmostEqual(state['values_usd']['MSTR'],50)
        self.assertAlmostEqual(state['total_portfolio_usd'],250)
        self.assertAlmostEqual(sum(state['values_usd'].values())+state['cash_usd'],250)

    def test_q4_ratio_must_come_from_matching_economic_case_not_free_text(self):
        args = table_fixture()
        args[0]['allocation_review']['strc_sata_within_fixed_pct']=[90,10]
        result=rows(build_capital_posture_context(*args))
        self.assertIsNone(result['STRC']['target_pct'])
        self.assertIsNone(result['SATA']['target_pct'])

    def test_review_never_mutates_pack_or_advances_rail(self):
        args = table_fixture()
        before = deepcopy(args)
        a = build_capital_posture_context(*args)
        self.assertEqual(a,build_capital_posture_context(*args))
        self.assertEqual(args,before)
        self.assertEqual(a['final_eligibility'],'NOT_DETERMINED')
        self.assertEqual(a['machine_execution'],'FORBIDDEN')

    def test_missing_q4_split_does_not_pad_income_or_erase_growth(self):
        args = table_fixture()
        del args[0]['allocation_review']['strc_sata_within_fixed_pct']
        out = build_capital_posture_context(*args)
        r = rows(out)
        self.assertIsNotNone(r['MSTR']['target_pct'])
        self.assertIsNone(r['STRC']['target_pct'])
        self.assertIsNone(r['SATA']['target_pct'])
        self.assertIsNone(out['allocation_review_table']['target_total_pct'])

    def test_bad_q3_health_blocks_only_affected_precise_target(self):
        data, pack, gold = table_fixture()
        pack['common_equity_health']['assets']['ASST']['health_direction']='BLOCKED'
        pack['evidence_pack_hash']=_hash({k:v for k,v in pack.items() if k!='evidence_pack_hash'})
        for k in ('current_rail','allocation_review'):
            data[k]['parent_evidence_pack_hash']=pack['evidence_pack_hash']
        r=rows(build_capital_posture_context(data,pack,gold))
        self.assertIsNone(r['ASST']['target_pct'])
        self.assertIsNotNone(r['MSTR']['target_pct'])
        self.assertIsNotNone(r['SATA']['target_pct'])
        self.assertIsNotNone(r['ASST']['current_pct'])

    def test_missing_sata_terms_does_not_erase_strc_or_fabricate_split(self):
        data,pack,gold=table_fixture()
        income=pack['asset_strategy_delta']['income_engine']
        income['assets']['SATA']['current_terms']={'state':'BLOCKED'}
        income['summary_hash']=_hash({k:v for k,v in income.items() if k!='summary_hash'})
        pack['asset_strategy_delta']['strc_sata_allocation_case']['income_summary_hash']=income['summary_hash']
        data['allocation_review']['q4_allocation_case_hash']=_hash(pack['asset_strategy_delta']['strc_sata_allocation_case'])
        pack['evidence_pack_hash']=_hash({k:v for k,v in pack.items() if k!='evidence_pack_hash'})
        for k in ('current_rail','allocation_review'):data[k]['parent_evidence_pack_hash']=pack['evidence_pack_hash']
        data['allocation_review']['q4_source_hash']=_hash(pack['asset_strategy_delta'])
        r=rows(build_capital_posture_context(data,pack,gold))
        self.assertIsNone(r['SATA']['target_pct'])
        self.assertIsNotNone(r['STRC']['target_pct'])
        self.assertIsNotNone(r['MSTR']['target_pct'])

    def test_stale_cross_cycle_and_cross_event_review_fail_closed(self):
        for key,value in [('valid_until_ms',NOW-1),('cycle_id','other-cycle'),
                          ('parent_evidence_pack_hash','a'*64),('allocation_source_hash','a'*64),
                          ('reviewed_by','UNATTRIBUTED')]:
            with self.subTest(key=key):
                args=table_fixture();args[0]['allocation_review'][key]=value
                r=rows(build_capital_posture_context(*args))
                self.assertTrue(all(x['target_pct'] is None for x in r.values()))

    def test_missing_user_rail_does_not_use_season_anchor(self):
        args=table_fixture();args[0]['current_rail']['recorded_by']='ANALYST'
        r=rows(build_capital_posture_context(*args))
        self.assertTrue(all(x['target_pct'] is None for x in r.values()))

    def test_unknown_denominator_keeps_values_without_renormalization(self):
        data,pack,gold=table_fixture()
        pack['portfolio_allocation_context']['current_allocation']['state']='BLOCKED'
        pack['evidence_pack_hash']=_hash({k:v for k,v in pack.items() if k!='evidence_pack_hash'})
        for k in ('current_rail','allocation_review'):data[k]['parent_evidence_pack_hash']=pack['evidence_pack_hash']
        data['allocation_review']['allocation_source_hash']=_hash(pack['portfolio_allocation_context'])
        r=rows(build_capital_posture_context(data,pack,gold))
        self.assertIsNotNone(r['MSTR']['current_usd'])
        self.assertTrue(all(x['current_pct'] is None and x['delta_usd'] is None for x in r.values()))

    def test_expired_render_cannot_present_current_precise_target(self):
        out=build_capital_posture_context(*table_fixture())
        text=render_allocation_review_table(out,at_ms=NOW+DAY)
        self.assertIn('ALLOCATION_REVIEW_EXPIRED_OR_UNBOUNDED',text)
        self.assertNotIn('20.93',text)

    def test_valid_sale_leg_needs_same_rebalance_scope_and_direction(self):
        data,pack,gold=table_fixture()
        allocation=pack['portfolio_allocation_context']
        allocation['suggested_mstr_pct'],allocation['suggested_asst_pct']=10,90
        data['allocation_review']['allocation_source_hash']=_hash(allocation)
        pack['evidence_pack_hash']=_hash({k:v for k,v in pack.items() if k!='evidence_pack_hash'})
        for k in ('current_rail','allocation_review'):
            data[k]['parent_evidence_pack_hash']=pack['evidence_pack_hash']
        out=build_capital_posture_context(data,pack,gold)
        self.assertLess(rows(out)['MSTR']['delta_usd'],0)
        rec=recommendation(item('SELL',scope='MSTR-rebalance',legs=[leg('SELL',quantity=3)]))
        envelope=display_envelope(out,rec)
        good=render_allocation_review_table(out,at_ms=NOW,envelope=envelope,
                    response=full_provider_response(rec,envelope))
        self.assertIn('SELL 3',good)
        # Different purpose/scope must not be imported into rebalance quantities.
        other=recommendation(item('SELL',scope='MSTR-unrelated',legs=[leg('SELL',quantity=3)]))
        other_env=display_envelope(out,other)
        bad=render_allocation_review_table(out,at_ms=NOW,envelope=other_env,
                    response=full_provider_response(other,other_env))
        self.assertNotIn('SELL 3',bad)

    def test_display_uses_final_validator_not_target_divided_by_close(self):
        out=build_capital_posture_context(*table_fixture())
        rec=recommendation(item('SELL',legs=[leg('SELL',quantity=3)]))
        envelope=display_envelope(out,rec)
        text=render_allocation_review_table(out,at_ms=NOW,envelope=envelope,response=full_provider_response(rec,envelope))
        self.assertNotIn('SELL 3',text)  # Rejected: current MSTR delta is BUY, not SELL.
        bad=deepcopy(rec);bad['items'][0]['legs'][0]['quantity']=9999
        with self.assertRaisesRegex(ValueError,'POSITION_REUSE_OR_EXCESS'):
            render_allocation_review_table(out,at_ms=NOW,envelope=envelope,response=full_provider_response(bad,envelope))

    def test_buy_missing_formal_valuation_cannot_gain_qualified_share_display(self):
        out=build_capital_posture_context(*table_fixture())
        rec=recommendation(item('BUY'))
        envelope=display_envelope(out,rec)
        # A saved legacy contract still has the independent formal-buy receipt gate.
        envelope=capital._build_envelope(envelope['capital_bridge_payload'],envelope['capital_source'],
            at_ms=NOW,full_decision=True,legacy_semantics=True)
        with self.assertRaisesRegex(ValueError,'VALUATION_EVIDENCE_UNQUALIFIED'):
            render_allocation_review_table(out,at_ms=NOW,envelope=envelope,response=provider_response(rec))

    def test_render_rejects_foreign_event_and_tampered_context(self):
        out=build_capital_posture_context(*table_fixture())
        rec=recommendation(item('SELL',legs=[leg('SELL',quantity=3)]))
        with self.assertRaisesRegex(ValueError,'LINEAGE_MISMATCH'):
            render_allocation_review_table(out,at_ms=NOW,envelope=display_envelope(out,rec,wrong_event=True),response=provider_response(rec))
        with self.assertRaisesRegex(ValueError,'CAPITAL_OBSERVATION_MISMATCH'):
            render_allocation_review_table(out,at_ms=NOW,envelope=display_envelope(out,rec,wrong_capital=True),response=provider_response(rec))
        out['allocation_review_table']['rows'][0]['target_pct']=100
        with self.assertRaisesRegex(ValueError,'HASH_INVALID'):
            render_allocation_review_table(out,at_ms=NOW)

    def test_no_q4_auto_role_or_new_trade_from_income_coverage(self):
        args=table_fixture();args[0]['allocation_review'].pop('strc_sata_within_fixed_pct')
        q4=args[1]['asset_strategy_delta']
        q4.update(income_goal={'state':'ESTIMATE','gap_usd':0},side_job={'state':'EXECUTE'})
        args[1]['evidence_pack_hash']=_hash({k:v for k,v in args[1].items() if k!='evidence_pack_hash'})
        for key in ('current_rail','allocation_review'):args[0][key]['parent_evidence_pack_hash']=args[1]['evidence_pack_hash']
        args[0]['allocation_review']['q4_source_hash']=_hash(q4)
        r=rows(build_capital_posture_context(*args))
        self.assertIsNone(r['STRC']['target_pct'])
        self.assertIsNone(r['SATA']['qualified_share_counts'])


class FourTableHistoricalReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[2]
        cls.archive=json.loads((Path(__file__).parent/'fixtures/four_table_historical_replay_20261010.json').read_text(encoding='utf-8'))
        cls.doctrine=(cls.root/'CRT_GPT_ANALYSIS_DOCTRINE_V0.1.md').read_text(encoding='utf-8')

    def test_real_radar_keeps_blocked_formal_season_and_valid_independent_fact(self):
        radar=self.archive['radar']
        self.assertEqual(radar['pack_state'],'BLOCKED')
        self.assertIsNone(radar['formal_season'])
        self.assertEqual(radar['btc_spot']['value'],82822.01)
        self.assertEqual(radar['btc_spot']['quality_state'],'VALID_FRESH')
        self.assertEqual(radar['weights'],dict(zip(('L1','L2','L3','L4','L5','L6'),(20,20,17,25,13,5))))
        self.assertIn('spot_btc_etp_flow_20d_pct_aum',radar['missing_etp_metric'])
        self.assertGreater(radar['credit_counterevidence']['value'],0)
        # A valid historical price is neither formal seasonal approval nor an order.
        self.assertEqual(self.archive['capital_state'],'NOT_PROVIDED_IN_RADAR_ATTACHMENT')

    def test_seven_original_sources_are_traceable_not_ex_ante_model_validation(self):
        research=self.archive['research']
        self.assertEqual(len(research),7)
        self.assertEqual(len({r['original_docx_sha256'] for r in research}),7)
        for row in research:
            self.assertRegex(row['original_docx_sha256'],r'^[0-9a-f]{64}$')
            self.assertFalse(row['point_in_time_eligible'])
            self.assertIsNone(row['first_seen_at_ms'])
        self.assertEqual(self.archive['replay_kind'],'RETROSPECTIVE_ARCHIVE_COMPARISON_ONLY')
        self.assertEqual(self.archive['model_comprehension'],'NOT_YET_PROVEN')

    def test_incomplete_real_export_cannot_be_resealed_as_qualified_capital(self):
        radar=deepcopy(self.archive['radar'])
        radar['evidence_pack_hash']=radar.pop('claimed_evidence_pack_hash')
        with self.assertRaisesRegex(ValueError,'PARENT_EVIDENCE_PACK_HASH_INVALID'):
            build_capital_posture_context({'as_of_ms':radar['generated_at_ms'],'cycle_id':'historical'},radar)
        self.assertIn('FULL_PACK_HASH_NOT_VERIFIED',self.archive['radar_artifact_status'])

    def test_original_price_time_and_invalidation_are_not_rewritten_as_crt_rules(self):
        sources={r['source_id']:r for r in self.archive['research']}
        jason=sources['JASON_JUDGEMENT']
        self.assertIn([87400],jason['original_price_coordinates_usd'])
        self.assertIn('不要求收盤',jason['original_confirmation'])
        self.assertIn('另要求',jason['crt_countercondition'])
        self.assertIn('週線',sources['BEN_LINE']['original_time_conditions'][0])
        self.assertIn('日線',sources['JASON_NOW']['original_invalidation'])
        self.assertIn('黑天鵝',sources['AMAO_PULLBACK']['original_invalidation'])
        for row in sources.values():
            self.assertTrue(row['original_price_coordinates_usd'])
            self.assertTrue(row['original_time_conditions'])
            self.assertIsNone(row['publication_at_ms'])
            if row['original_invalidation_status']=='NOT_STATED_AS_EXPLICIT_RULE':
                self.assertIsNone(row['original_invalidation'])
                self.assertTrue(row['crt_countercondition'])

    def test_six_example_rows_sum_to_100_without_becoming_approved_targets(self):
        section=self.doctrine.split('### 11.2 A～F',1)[1].split('### 11.3',1)[0]
        examples=re.findall(r'\| ([A-F]) \| [^\n]+ \| ([0-9／]+) \|',section)
        self.assertEqual(len(examples),6)
        for _,numbers in examples:self.assertEqual(sum(map(int,numbers.split('／'))),100)
        self.assertIn('不是現行目標',section)
        self.assertIn('35% 示範現金不能覆寫',section)


if __name__=='__main__':
    unittest.main()
