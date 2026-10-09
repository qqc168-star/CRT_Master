"""Two-layer input/decision replay proves bindings, never simulated model intelligence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from crt_radar import capital_decision_closure as c
from crt_radar.gpt_bridge_outbox import enqueue_bridge_payload
from crt_radar.gpt_notification_boundary import present_from_transport
from crt_radar.gpt_transport_worker import deliver_event
from scripts import run_controlled_capital_acceptance as controlled
from tests.test_capital_decision_closure import (current_capital_pack, full_provider_response,
    item, match_scopes, provider_response, recommendation)

NOW = 1791499626351
MAIN = 'e1129f5d6d341a2669e19ef0ea9d937d25f8e68f'
BTC_PRICE = '/market_context/btc_bull_validation/price_usd'


class TwoLayerReasoningReplayTests(unittest.TestCase):
    def setUp(self):
        self.case = controlled.synthetic_case(at_ms=NOW, source_main_sha=MAIN)
        self.payload = deepcopy(self.case['payload'])
        self.payload['event']['event_id'] = c.digest({'fixture': 'two-layer-offline'})
        market = self.payload['market_context']
        market['btc_bull_validation'].update(asset='BTC', state='AVAILABLE', as_of_ms=NOW,
            price_usd=100000, research_candidate='SYNTHETIC_BULLISH_HYPOTHESIS_NOT_FORMAL_SEASON')
        market['changes']['synthetic_issuer_counterevidence'] = {
            'asset': 'MSTR', 'as_of_ms': NOW, 'quality_state': 'VALID_FRESH',
            'per_share_btc_direction': 'DILUTING', 'limitation': 'SYNTHETIC_TEST_ONLY'}
        self.payload['bridge_payload_hash'] = c.digest({k: v for k, v in self.payload.items() if k != 'bridge_payload_hash'})
        self.source = deepcopy(self.case['source'])
        self.source['bridge_payload_hash'] = self.payload['bridge_payload_hash']
        self.rec = recommendation(*[item('WAIT', asset=asset, scope=asset+'-addition',
            wait_kind='EVIDENCE_BLOCKED', blockers=['缺正式估值或收益／費用／回程風險證據，不能量化加碼'],
            reason='第一層 BTC：合成上行假說與美元100000參照僅供情境，正式季節未知；'
                   '第二層 '+asset+'：不能由BTC假說推出買進，保留個別資格缺口。',
            contradictions=['BTC上行假說與MSTR每股BTC稀釋風險並存，不構成一致買進依據'],
            applicability='只適用此合成快照；上行與下行確認、時間尺度尚缺合法來源',
            invalidation='有效證據過期或個股風險資料變動，原情境失效',
            next_trigger='正式估值或收益與輪動費用來源補齊，再檢查當次資本資格')
            for asset in ('MSTR', 'ASST', 'STRC', 'SATA')])
        match_scopes(self.source, self.rec)
        self.envelope = c.build_envelope(self.payload, self.source, at_ms=NOW, full_decision=True)
        self.projection = json.loads(self.envelope['request_body']['input'])
        self.catalog = c.semantic_evidence_catalog(self.projection)

    def response(self, rec=None):
        response = full_provider_response(rec or self.rec, self.envelope)
        decoded = json.loads(response['output'][0]['content'][0]['text'])
        paths = [BTC_PRICE, '/market_context/changes/synthetic_issuer_counterevidence/per_share_btc_direction']
        for row in decoded['items']:
            row['reasoning_support']['claim_bindings'] = [
                {'source_path': path, **{key: self.catalog[path][key]
                    for key in ('subject_asset', 'metric_basis', 'value_json')}} for path in paths]
        return provider_response(decoded)

    def test_existing_projection_carries_upper_and_lower_inputs_without_promotion(self):
        self.assertEqual(self.projection['market_context'], self.payload['market_context'])
        self.assertEqual(set(self.projection['market_context']['layers']), {'L1','L2','L3','L4','L5','L6'})
        self.assertIsNone(self.projection['market_context']['model_status']['btc_season_router']['season'])
        self.assertEqual(self.projection['posture']['formal_season'], 'NOT_DETERMINED')
        self.assertEqual(self.catalog[BTC_PRICE]['subject_asset'], 'BTC')
        self.assertEqual(self.catalog[BTC_PRICE]['source_time_ms'], NOW)
        self.assertIn('DILUTING', json.dumps(self.catalog))
        self.assertEqual({s['asset'] for s in self.projection['task']['scopes']}, {'MSTR','ASST','STRC','SATA'})

    def test_instruction_version_and_output_schema_preserve_old_request_replay(self):
        self.assertEqual(self.envelope['two_layer_analysis_contract'], c.TWO_LAYER_ANALYSIS_CONTRACT_VERSION)
        old = c._build_envelope(self.payload, self.source, at_ms=NOW, full_decision=True, legacy_two_layer=True)
        original = deepcopy(old)
        self.assertEqual(c.validate_envelope(old), original)
        self.assertEqual(old['request_body']['text'], self.envelope['request_body']['text'])
        self.assertNotIn('two_layer_analysis_contract', old)
        self.assertNotEqual(old['request_hash'], self.envelope['request_hash'])
        self.assertNotIn('Two-layer analysis', old['request_body']['instructions'])
        for marker in ('L0 is observational only', 'conditional bullish and bearish BTC paths',
                       'EACH requested security decision scope', 'No source or rail means',
                       'Do not add output fields', 'upper/lower-layer conflicts'):
            self.assertIn(marker, self.envelope['request_body']['instructions'])
        for defect in ('remove', 'wrong'):
            changed = deepcopy(self.envelope)
            if defect == 'remove':
                changed.pop('two_layer_analysis_contract')
            else:
                changed['two_layer_analysis_contract'] = 'UNKNOWN'
            changed['request_hash'] = c.digest({k: v for k, v in changed.items() if k != 'request_hash'})
            with self.assertRaisesRegex(ValueError, 'CAPITAL_ENVELOPE_MISMATCH'):
                c.validate_envelope(changed)

    def test_four_asset_nontrade_replay_preserves_conflicts_and_unproven_reasoning(self):
        response = self.response()
        original = deepcopy(response)
        validated = c.assess_response(response, self.envelope, at_ms=NOW)
        self.assertEqual(response, original)
        self.assertEqual(len(validated['items']), 4)
        self.assertTrue(all(i['validation_state'] == 'VALIDATED_NON_TRADING_WAIT' for i in validated['items']))
        text = c.render(validated)
        for phrase in ('第一層 BTC', '第二層', '稀釋風險', '上行與下行確認', '不得交易', 'NOT_YET_PROVEN'):
            self.assertIn(phrase, text)
        self.assertEqual(validated['reasoning_review']['free_prose_reasoning'], 'NOT_YET_PROVEN')
        self.assertEqual(validated['governance'], c.LOCKS)

    def test_missing_scope_btc_security_and_new_output_fields_are_rejected(self):
        for defect in ('missing_scope', 'BTC', 'new_field'):
            rec = deepcopy(self.rec)
            if defect == 'missing_scope':
                rec['items'].pop()
            elif defect == 'BTC':
                rec['items'][0]['asset'] = 'BTC'
            else:
                rec['items'][0]['btc_strategy'] = 'NOT_AN_APPROVED_FIELD'
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                c.assess_response(self.response(rec), self.envelope, at_ms=NOW)

    def test_missing_price_cannot_be_bound_or_invented_in_typed_evidence(self):
        payload = deepcopy(self.payload)
        del payload['market_context']['btc_bull_validation']['price_usd']
        payload['bridge_payload_hash'] = c.digest({k: v for k, v in payload.items() if k != 'bridge_payload_hash'})
        source = deepcopy(self.source)
        source['bridge_payload_hash'] = payload['bridge_payload_hash']
        envelope = c.build_envelope(payload, source, at_ms=NOW, full_decision=True)
        with self.assertRaisesRegex(ValueError, 'RESPONSE_ENUM_MISMATCH'):
            c.assess_response(self.response(), envelope, at_ms=NOW)
        response = self.response()
        decoded = json.loads(response['output'][0]['content'][0]['text'])
        decoded['items'][0]['reasoning_support']['claim_bindings'][0]['value_json'] = '999999'
        with self.assertRaisesRegex(ValueError, 'CLAIM_VALUE_MISMATCH'):
            c.assess_response(provider_response(decoded), self.envelope, at_ms=NOW)

    def test_research_candidate_cannot_be_bound_as_a_formal_season(self):
        response = self.response()
        decoded = json.loads(response['output'][0]['content'][0]['text'])
        path = '/posture/formal_season'
        self.assertNotIn(path, self.catalog)
        self.assertEqual(self.projection['posture']['formal_season'], 'NOT_DETERMINED')
        decoded['items'][0]['supporting_evidence'].append('posture')
        decoded['items'][0]['reasoning_support']['claim_bindings'] = [{
            'source_path': path, 'subject_asset': 'BTC',
            'metric_basis': 'POSTURE_RESEARCH', 'value_json': '"SPRING"'}]
        with self.assertRaisesRegex(ValueError, 'RESPONSE_ENUM_MISMATCH'):
            c.assess_response(provider_response(decoded), self.envelope, at_ms=NOW)
        self.assertIsNone(self.projection['market_context']['model_status']['btc_season_router']['season'])

    def test_valid_format_cannot_certify_a_false_consistent_prose_conclusion(self):
        response = self.response()
        decoded = json.loads(response['output'][0]['content'][0]['text'])
        decoded['items'][0]['reason'] = 'BTC看漲所以MSTR一定安全；這是刻意錯誤的離線反例。'
        decoded['items'][0]['contradictions'] = []
        validated = c.assess_response(provider_response(decoded), self.envelope, at_ms=NOW)
        # This deliberately exposes the existing assurance boundary. The facts
        # bind, but no semantic PASS may be inferred from these valid JSON fields.
        self.assertEqual(validated['reasoning_review']['free_prose_reasoning'], 'NOT_YET_PROVEN')
        self.assertTrue(all(row['investment_reasoning'] == 'NOT_YET_PROVEN'
                            for row in validated['reasoning_review']['items']))
        self.assertFalse(any(row['validated_legs'] for row in validated['items']))
        self.assertIn('投資因果推理仍為 NOT_YET_PROVEN', c.render(validated))

    def test_expired_and_cross_event_source_cannot_qualify(self):
        with self.assertRaises(ValueError):
            c.assess_response(self.response(), self.envelope, at_ms=NOW + 400000)
        mismatched = deepcopy(self.source)
        mismatched['bridge_payload_hash'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'BRIDGE_LINEAGE_MISMATCH'):
            c.build_envelope(self.payload, mismatched, at_ms=NOW, full_decision=True)
        mismatched = deepcopy(self.source)
        mismatched['evidence_lineage'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'EVIDENCE_LINEAGE_MISMATCH'):
            c.build_envelope(self.payload, mismatched, at_ms=NOW, full_decision=True)

    def test_mock_two_layer_receipt_notification_and_replay_are_offline_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_bridge_payload(root / 'outbox', self.payload)
            provider = Mock(return_value=self.response())
            event_path = root / 'outbox' / (self.payload['event']['event_id']+'.json')
            result = deliver_event(event_path, root / 'transport', capital_source=self.source,
                current_main_sha=MAIN, now_ms=NOW, transport=provider, notification_state_dir=root / 'notices')
            self.assertEqual(result['state'], 'DELIVERED', result)
            notice = next((root / 'notices').glob('*.json'))
            presenter = Mock(return_value=1)
            for state in ('DELIVERED','ALREADY_DELIVERED'):
                self.assertEqual(present_from_transport(notice, root / 'transport', presenter,
                    now_ms=NOW, current_capital_source=self.source,
                    current_capital_state=current_capital_pack(self.source, at=NOW))['state'], state)
            self.assertEqual(deliver_event(event_path, root / 'transport', capital_source=self.source,
                current_main_sha=MAIN, now_ms=NOW, transport=provider)['state'], 'ALREADY_DELIVERED')
            provider.assert_called_once()
            presenter.assert_called_once()
            self.assertEqual(self.envelope['delivery_mode'], 'OFFLINE_ONLY')
            self.assertEqual(self.envelope['measurement']['model_comprehension'], 'NOT_YET_PROVEN')

if __name__ == '__main__':
    unittest.main()
