import ast
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from crt_radar import ibkr_live_market_data_intake as intake
from crt_radar.ibkr_observation_journal import AUTHORITY
from crt_radar.local_live_runtime import Runtime, RuntimeConfig, RuntimeJournal, single_instance

CONFIG = Path(__file__).resolve().parents[1] / 'CONFIG' / 'LOCAL_LIVE_RUNTIME_V0.1.json'


class Worker:
    def __init__(self):
        self.messages = []
        self.running = True
        self.closed = False
    def poll(self):
        return self.messages.pop(0) if self.messages else None
    def alive(self):
        return self.running
    def close(self):
        self.closed = True
        self.running = False


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = RuntimeJournal(self.temp.name)
        self.addCleanup(self.journal.close)
        self.now = 0
        self.available = False
        self.workers = []
        self.probes = []
        self.config = RuntimeConfig.load(CONFIG)
        self.runtime = Runtime(self.config, self.journal, probe=self.probe,
                               factory=self.factory, clock=lambda: self.now)
        self.addCleanup(self.runtime.close)

    def probe(self, host, port):
        self.probes.append((host, port))
        return self.available

    def factory(self, config):
        worker = Worker()
        self.workers.append(worker)
        return worker

    def checkpoint(self):
        return json.loads((Path(self.temp.name) / 'checkpoint.json').read_text())

    def connect(self):
        self.available = True
        self.runtime.tick()
        worker = self.workers[-1]
        worker.messages.append(('CONNECTED', {}))
        self.runtime.tick()
        return worker

    def test_missing_tws_bounded_backoff_and_recovery(self):
        for _ in range(10):
            self.runtime.tick()
            checkpoint = self.checkpoint()
            self.assertEqual(checkpoint['state'], 'WAITING_FOR_TWS')
            self.assertLessEqual(checkpoint['retry_after_seconds'], 60)
            before = len(self.probes)
            self.runtime.tick()
            self.assertEqual(len(self.probes), before)
            self.now = self.runtime.next_attempt
        self.connect()
        self.assertEqual(self.runtime.state, 'CONNECTED')
        self.assertEqual(self.probes[-1][1], self.config.intake.port)

    def test_live_capture_disconnect_pause_resume_never_promotes_snapshot(self):
        worker = self.connect()
        capture = {'assets': {'MSTR': {'market_data_type': 1, 'last_received_at_ms': 123,
                                      'l1': {'last': 100}}}, 'captured_at_ms': 456}
        worker.messages.append(('CAPTURE', capture))
        self.runtime.tick()
        self.assertEqual(self.runtime.state, 'RECEIVING')
        checkpoint = self.checkpoint()
        self.assertEqual(checkpoint['premarket_pipeline'], 'PENDING_MARKET_WINDOW')
        self.assertFalse(checkpoint['evidence_usable'])
        for key, value in AUTHORITY.items():
            self.assertEqual(checkpoint[key], value)
        self.runtime.tick(paused=True)
        self.assertTrue(worker.closed)
        self.assertEqual(self.runtime.state, 'PAUSED')
        self.assertNotIn('live_callback_assets', self.checkpoint())
        self.runtime.tick()
        self.now = self.runtime.next_attempt
        new_worker = self.connect()
        self.assertIsNot(new_worker, worker)
        self.assertIsNone(self.runtime.capture_signature)

    def test_delayed_data_is_not_live(self):
        worker = self.connect()
        worker.messages.append(('CAPTURE', {'assets': {'MSTR': {'market_data_type': 3, 'last_received_at_ms': 1}}}))
        self.runtime.tick()
        self.assertEqual(self.runtime.state, 'CONNECTED_NO_DATA')

    def test_handshake_hang_killed_at_deadline(self):
        self.available = True
        self.runtime.tick()
        self.now = self.runtime.deadline
        self.runtime.tick()
        self.assertTrue(self.workers[0].closed)
        self.assertEqual(self.runtime.state, 'WAITING_FOR_TWS')

    def test_connection_loss_and_unexpected_worker_exit(self):
        for event in ('DISCONNECTED', 'ERROR', 'FINISHED', None):
            self.now = self.runtime.next_attempt
            worker = self.connect()
            if event:
                worker.messages.append((event, {'reason': 'failure'}))
                if event == 'DISCONNECTED':
                    worker.messages.append(('FINISHED', {}))
            else:
                worker.running = False
            self.runtime.tick()
            self.assertTrue(worker.closed)
            self.assertTrue(self.checkpoint()['fail_closed'])
            self.assertEqual(self.runtime.state, 'WAITING_FOR_TWS')

    def test_cleanup_does_not_hide_original_api_error(self):
        worker = self.connect()
        worker.messages.extend([('DISCONNECTED', {}), ('ERROR', {'reason': 'API_REJECTED'})])
        self.runtime.tick()
        self.assertEqual(self.checkpoint()['reason'], 'API_REJECTED')

    def test_stalled_connected_worker_is_terminated(self):
        worker = self.connect()
        self.now = self.runtime.deadline + 1
        self.runtime.tick()
        self.assertTrue(worker.closed)

    def test_restart_invalidates_checkpoint_and_preserves_journal(self):
        self.connect()
        before = self.journal.db.execute('SELECT count(*) FROM events').fetchone()[0]
        runtime = Runtime(self.config, self.journal)
        self.assertEqual(self.checkpoint()['state'], 'STARTING')
        self.assertGreater(self.journal.db.execute('SELECT count(*) FROM events').fetchone()[0], before)
        runtime.close()

    def test_config_rejects_remote_and_unbounded_or_fast_retry(self):
        base = json.loads(CONFIG.read_text())
        for key, value in [('host', 'example.com'), ('backoff_max_seconds', float('inf')),
                           ('backoff_initial_seconds', 0), ('duration_seconds', 5),
                           ('heartbeat_timeout_seconds', -1)]:
            changed = dict(base, **{key: value})
            path = Path(self.temp.name) / 'bad.json'
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                RuntimeConfig.load(path)

    def test_single_instance_and_crash_released_lock(self):
        with single_instance(self.temp.name):
            with self.assertRaises(OSError):
                with single_instance(self.temp.name):
                    pass
        with single_instance(self.temp.name):
            pass

    def test_task_has_logon_trigger_and_stable_no_console_launcher(self):
        script = (CONFIG.parents[1] / 'scripts/windows/install_local_live_runtime.ps1').read_text()
        for item in ('-AtLogOn', 'pythonw.exe', '-MultipleInstances IgnoreNew',
                     '-RunLevel Limited', '-ExecutionTimeLimit ([TimeSpan]::Zero)', 'deployment.json'):
            self.assertIn(item, script)

    def test_intake_has_only_existing_market_data_request_surface(self):
        tree = ast.parse(Path(intake.__file__).read_text())
        requests = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr.startswith(('req', 'cancel', 'place'))}
        self.assertEqual(requests, {'reqMarketDataType', 'reqMktData', 'reqRealTimeBars',
                                    'cancelMktData', 'cancelRealTimeBars'})

    def test_native_lifecycle_reuses_feed_and_disconnects_on_loss(self):
        for connected in (True, False):
            app = MagicMock()
            app.ready.wait.return_value = True
            app.isConnected.return_value = connected
            app.failures = []
            app.assets = {'MSTR': {'bars_5s': [{'time_s': 1}, {'time_s': 2}]}}
            app.request_map = {}
            events = []
            clock = iter(range(100))
            with patch.object(intake, '_native_feed_app', return_value=(lambda: app, SimpleNamespace)), \
                 patch.object(intake.threading, 'Thread'), \
                 patch.object(intake.threading, 'Event'), \
                 patch.object(intake.time, 'monotonic', side_effect=lambda: next(clock)):
                feed = intake.NativeIbkrFeed(lifecycle_sink=lambda event, details: events.append((event, details)))
                config = intake.IbkrIntakeConfig(duration_seconds=5)
                if connected:
                    feed.collect(config)
                    captures = [data for event, data in events if event == 'CAPTURE']
                    self.assertTrue(captures)
                    self.assertEqual(captures[0]['assets']['MSTR']['bars_5s'], [{'time_s': 2}])
                    self.assertEqual(len(app.assets['MSTR']['bars_5s']), 2)
                else:
                    with self.assertRaisesRegex(intake.IbkrIntakeError, 'connection lost'):
                        feed.collect(config)
                self.assertEqual(events[0][0], 'CONNECTED')
                self.assertEqual(events[-1][0], 'DISCONNECTED')
                app.disconnect.assert_called_once()
                self.assertEqual(app.reqMktData.call_count, len(intake.ASSET_ORDER))
                self.assertEqual(app.cancelRealTimeBars.call_count, len(intake.ASSET_ORDER))

    def test_existing_observation_sink_coexists_with_lifecycle_and_api_failure(self):
        app = MagicMock()
        app.ready.wait.return_value = True
        app.isConnected.return_value = True
        app.assets = {'MSTR': {'bars_5s': []}}
        app.failures = [{'code': 354, 'reason': 'NOT_SUBSCRIBED'}]
        app.request_map = {}
        observation_sink = object()
        events = []
        clock = iter(range(100))
        with patch.object(intake, '_native_feed_app', return_value=(lambda: app, SimpleNamespace)) as factory, \
             patch.object(intake.threading, 'Thread'), \
             patch.object(intake.threading, 'Event'), \
             patch.object(intake.time, 'monotonic', side_effect=lambda: next(clock)):
            feed = intake.NativeIbkrFeed(observation_sink, lifecycle_sink=lambda event, _: events.append(event))
            with self.assertRaisesRegex(intake.IbkrIntakeError, 'NOT_SUBSCRIBED'):
                feed.collect(intake.IbkrIntakeConfig(duration_seconds=5))
        factory.assert_called_once_with(observation_sink)
        self.assertEqual(events, ['CONNECTED', 'DISCONNECTED'])
        app.disconnect.assert_called_once()
        self.assertEqual(app.cancelMktData.call_count, len(intake.ASSET_ORDER))
        self.assertEqual(app.cancelRealTimeBars.call_count, len(intake.ASSET_ORDER))

    def test_failed_handshake_never_subscribes_or_reports_connected(self):
        app = MagicMock()
        app.ready.wait.return_value = False
        events = []
        with patch.object(intake, '_native_feed_app', return_value=(lambda: app, SimpleNamespace)), \
             patch.object(intake.threading, 'Thread'):
            feed = intake.NativeIbkrFeed(lifecycle_sink=lambda event, _: events.append(event))
            with self.assertRaisesRegex(intake.IbkrIntakeError, 'handshake timed out'):
                feed.collect(intake.IbkrIntakeConfig())
        self.assertEqual(events, ['DISCONNECTED'])
        app.reqMktData.assert_not_called()
        app.reqRealTimeBars.assert_not_called()
        app.disconnect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
