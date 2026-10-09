"""Event-bound daily notification sources, synthetic capital and mocked providers."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from crt_radar import gpt_notification_boundary as boundary
from crt_radar.gpt_transport_worker import deliver_event
from crt_radar.broker_capital_observation import seal_broker_observation
from tests import test_daily_capital_source as daily
from tests import test_gpt_transport_worker as smoke
from tests.test_capital_decision_closure import current_capital_pack, full_provider_response, item, recommendation

class EventCapitalSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = self.root / 'private' / 'sources'
        self.sources.mkdir(parents=True)
        self.transport = self.root / 'transport'
        self.notices = self.root / 'notices'
        self.presenter = Mock(return_value=1)
        self.case, self.source, self.source_path = self.event()
        self.pack = self.case.pack

    def event(self, reserve=None):
        case = daily.DailyCapitalSourceTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        if reserve is not None:
            case.intent['reserved_usd'] = reserve
            case.inputs['user_intent']['reserved_usd'] = reserve
        case.prepare()
        bound = case.bind()
        self.assertEqual(bound['state'], 'SOURCE_BOUND', bound)
        source = bound['source']
        path = self.sources / f'{case.handoff["event_id"]}.json'
        path.write_text(json.dumps(source), encoding='utf-8')
        rec = recommendation(item('WAIT', wait_kind='EVIDENCE_BLOCKED', blockers=['等待正式估值補證據']))
        provider = Mock(side_effect=lambda request: full_provider_response(rec, request))
        result = deliver_event(case.root / 'outbox' / f'{case.handoff["event_id"]}.json', self.transport,
            transport=provider, notification_state_dir=self.notices, now_ms=daily.NOW,
            capital_source=source, current_main_sha=daily.MAIN)
        self.assertEqual(result['state'], 'DELIVERED', result)
        provider.assert_called_once()
        return case, source, path

    def sweep(self, pack=None, at=None, **kwargs):
        with patch.object(boundary.time, 'time', return_value=(daily.NOW if at is None else at) / 1000):
            return boundary.deliver_pending(self.transport, self.notices, self.presenter,
                capital_source_dir=self.sources, current_capital_state=self.pack if pack is None else pack, **kwargs)

    def test_correct_source_restart_replay_and_no_new_event_preserve_sources(self):
        original = {p.name: p.read_bytes() for p in self.sources.iterdir()}
        self.assertEqual(self.sweep()['presentation_count'], 1)
        self.assertEqual(self.sweep()['presentation_count'], 0)
        self.presenter.assert_called_once()
        self.assertEqual({p.name: p.read_bytes() for p in self.sources.iterdir()}, original)

    def test_two_events_cannot_borrow_sources(self):
        case, source, path = self.event(reserve=123)
        self.assertNotEqual(path, self.source_path)
        self.source_path.write_text(json.dumps(source), encoding='utf-8')
        path.write_text(json.dumps(self.source), encoding='utf-8')
        self.assertEqual(self.sweep(pack=case.pack)['presentation_count'], 0)
        self.presenter.assert_not_called()

    def test_missing_corrupt_nonobject_tampered_sources(self):
        for index, mode in enumerate(('missing', 'corrupt', 'nonobject', 'tampered')):
            with self.subTest(mode=mode):
                case, source, path = self.event(reserve=124 + index)
                if mode == 'missing':
                    path.unlink()
                elif mode == 'corrupt':
                    path.write_text('{broken', encoding='utf-8')
                elif mode == 'nonobject':
                    path.write_text('[]', encoding='utf-8')
                else:
                    source['source_main_sha'] = '0' * 40
                    path.write_text(json.dumps(source), encoding='utf-8')
                self.assertEqual(self.sweep(pack=case.pack)['presentation_count'], 0)
        self.presenter.assert_not_called()

    def test_expired_and_restored_advice_does_not_revive(self):
        self.assertEqual(self.sweep(at=daily.NOW + 400_000)['presentation_count'], 0)
        self.assertEqual(self.sweep()['presentation_count'], 0)
        self.presenter.assert_not_called()

    def test_changed_capital_and_recovery_does_not_revive(self):
        facts = deepcopy(self.source)
        facts['user_intent']['reserved_usd'] += 1
        changed = current_capital_pack(facts, at=daily.NOW + 1)
        self.assertEqual(self.sweep(pack=changed, at=daily.NOW + 1)['presentation_count'], 0)
        self.assertEqual(self.sweep()['presentation_count'], 0)
        self.presenter.assert_not_called()

    def test_partial_capital_then_recovery_does_not_revive(self):
        facts = deepcopy(self.source)
        facts['broker_observation']['scope']['funds_complete'] = False
        facts['broker_observation'] = seal_broker_observation(facts['broker_observation'])
        partial = current_capital_pack(facts, at=daily.NOW + 1)
        self.assertEqual(self.sweep(pack=partial, at=daily.NOW + 1)['presentation_count'], 0)
        self.assertEqual(self.sweep()['presentation_count'], 0)
        self.presenter.assert_not_called()

    def test_source_restoration_does_not_revive(self):
        original = self.source_path.read_bytes()
        self.source_path.unlink()
        self.assertEqual(self.sweep()['presentation_count'], 0)
        self.source_path.write_bytes(original)
        self.assertEqual(self.sweep()['presentation_count'], 0)
        self.presenter.assert_not_called()

    def test_bad_event_does_not_block_smoke_or_valid_capital(self):
        case = smoke.WorkerTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.assertEqual(deliver_event(case.path, self.transport, transport=case.transport,
            notification_state_dir=self.notices)['state'], 'DELIVERED')
        (self.notices / '000-corrupt.json').write_text('{bad', encoding='utf-8')
        result = self.sweep()
        self.assertEqual(result['presentation_count'], 2)
        self.assertIn('NOTIFICATION_VALIDATION_FAILED', [r['state'] for r in result['results']])
        self.assertEqual(self.sweep()['presentation_count'], 0)
        self.assertEqual(self.presenter.call_count, 2)

    def test_directory_never_falls_back_to_single_or_latest_wrapper(self):
        self.source_path.unlink()
        (self.sources.parent / 'capital-decision-source.json').write_text(json.dumps({'source': self.source}), encoding='utf-8')
        self.assertEqual(self.sweep(current_capital_source=self.source)['presentation_count'], 0)
        self.presenter.assert_not_called()

    def test_cli_directory_and_legacy_single_source(self):
        pack_path = self.root / 'pack.json'
        pack_path.write_text(json.dumps(self.pack), encoding='utf-8')
        args = ['deliver-pending', '--transport-state-dir', str(self.transport),
                '--notification-state-dir', str(self.notices), '--capital-state', str(pack_path)]
        with patch.object(boundary, 'windows_popup_presenter', self.presenter), \
             patch.object(boundary.time, 'time', return_value=daily.NOW / 1000), redirect_stdout(io.StringIO()):
            self.assertEqual(boundary.main(args + ['--capital-source-dir', str(self.sources)]), 0)
            self.assertEqual(boundary.main(args + ['--capital-source', str(self.source_path)]), 0)
        self.presenter.assert_called_once()

if __name__ == '__main__':
    unittest.main()
