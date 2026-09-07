"""Offline durability regressions: all writes use temporary run directories."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_state


class RunDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'enza_memory').mkdir()
        self.registry = self.root / 'enza_memory/artifact_registry.json'
        self.registry.write_text(json.dumps({
            'current_mainline': {'active_run': 'RUN'},
            'runs': [{'id': 'RUN', 'path': 'enza_memory/wing_runs/RUN', 'resume_allowed': True}]}))
        self.directory = self.root / 'enza_memory/wing_runs/RUN'
        self.state = run_state.clean_run_state('RUN')

    def load(self):
        return run_state.resolve_run_state(json.loads(self.registry.read_text()), base_dir=self.root)

    def test_all_boundaries_restore_latest_state_and_bind_evidence(self):
        shot = self.root / 'evidence.png'
        shot.write_bytes(b'offline evidence fixture')
        for boundary in ('COMPLETED_WEEK', 'AUDITION_RESULT', 'SEASON_TRANSITION'):
            self.state['last_boundary'] = boundary
            self.state['season3']['audition_40k_completed'] = boundary != 'COMPLETED_WEEK'
            path = run_state.save_active_run_state(self.registry, self.state, boundary=boundary,
                                                   evidence={'result': 'verified'}, evidence_paths=(shot,))
            payload = json.loads(path.read_text())
            event = json.loads((self.directory / 'boundary_events' / (payload['event_id'] + '.json')).read_text())
            self.assertEqual(payload, event)
            self.assertEqual(payload['evidence_files'][0]['sha256'], hashlib.sha256(shot.read_bytes()).hexdigest())
            self.assertEqual(self.load(), self.state)
        run_state.persist_session_end(self.registry, reason='HANDOFF')
        self.assertEqual(self.load(), self.state)
        self.assertEqual(json.loads(path.read_text())['boundary'], 'SESSION_END')

    def test_event_then_checkpoint_then_summary(self):
        writes = []
        original = run_state._durable_json
        def write(path, payload):
            writes.append('checkpoint' if path.name == 'runtime_state.json' else 'event')
            original(path, payload)
        with patch('run_state._durable_json', side_effect=write):
            run_state.save_active_run_state(self.registry, self.state, boundary='COMPLETED_WEEK')
            writes.append('summary')
        self.assertEqual(writes, ['event', 'checkpoint', 'summary'])

    def test_failed_event_or_checkpoint_blocks_following_progress_and_resume(self):
        for fail_at in ('event', 'checkpoint'):
            with self.subTest(fail_at=fail_at):
                # independent run directory for each injected failure
                self.setUp()
                path = run_state.save_active_run_state(self.registry, self.state)
                before = path.read_bytes()
                original = run_state._durable_json
                def write(destination, payload):
                    kind = 'checkpoint' if destination.name == 'runtime_state.json' else 'event'
                    if kind == fail_at:
                        raise OSError('disk failure')
                    original(destination, payload)
                summary = []
                self.state['last_completed_week'] = {'entry_weeks_remaining': 6}
                with patch('run_state._durable_json', side_effect=write):
                    with self.assertRaises(OSError):
                        run_state.save_active_run_state(self.registry, self.state)
                        summary.append('advanced')
                self.assertEqual(summary, [])
                self.assertEqual(path.read_bytes(), before)
                with self.assertRaisesRegex(ValueError, 'PERSISTENCE_INCOMPLETE'):
                    self.load()
                with self.assertRaisesRegex(ValueError, 'PERSISTENCE_INCOMPLETE'):
                    run_state.save_active_run_state(self.registry, self.state)

    def test_fsync_failure_fails_closed(self):
        run_state.save_active_run_state(self.registry, self.state)
        with patch('run_state.os.fsync', side_effect=OSError('fsync failed')):
            with self.assertRaises(OSError):
                run_state.save_active_run_state(self.registry, self.state)
        # Even a marker-write fsync failure leaves the marker visible locally.
        with self.assertRaisesRegex(ValueError, 'PERSISTENCE_INCOMPLETE'):
            self.load()

    def test_closed_runtime_payload_cannot_authorize_resume(self):
        path = run_state.save_active_run_state(self.registry, self.state)
        payload = json.loads(path.read_text())
        payload['run_closed'] = True
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, 'NOT_RESUMABLE'):
            self.load()

    def test_manual_audition_failure_does_not_mutate_loaded_progress(self):
        import main
        config = {'run_state': self.state}
        with patch('main.setup_logging'), patch('main.load_config_with_run_state', return_value=config), \
             patch('main.read_validated_home_observation', return_value=main.HomeObservation(3, 2, 0)), \
             patch('main.save_active_run_state', side_effect=OSError('disk failure')), \
             patch('main.write_trace') as trace:
            self.assertEqual(main.mark_season3_auditions_complete(), 2)
        self.assertFalse(self.state['season3']['audition_40k_completed'])
        trace.assert_not_called()

    def test_completed_tick_flushes_before_success_and_next_tick(self):
        import main
        from types import SimpleNamespace
        from room_adapter import issue_home_provenance
        observation = main.HomeObservation(2, 4, 0, provenance=issue_home_provenance('offline'))
        result = SimpleNamespace(status='TICK_SUCCESS', room='VOCAL_ROOM', final_state='HOME',
                                 detail='offline verified', goal_context=None)
        config = {'run_state': self.state}
        with patch('main.setup_logging'), patch('main.load_config_with_run_state', return_value=config), \
             patch('main.REGISTRY_PATH', self.registry), patch('main.write_trace') as trace, \
             patch('main.execute_home_tick', return_value=result), \
             patch('main.home_tick_trace_path', return_value=self.root / 'trace.jsonl'):
            self.assertEqual(main.run_home_tick(True, observation), 0)
            restored = self.load()
            self.assertEqual(restored['last_completed_week']['entry_weeks_remaining'], 4)
            self.assertEqual(len(list((self.directory / 'boundary_events').glob('*.json'))), 2)
            self.assertEqual(trace.call_args.args[1]['status'], 'TICK_SUCCESS')
            with patch('run_state._durable_json', side_effect=OSError('disk full')):
                self.assertEqual(main.run_home_tick(True, observation), 2)
            self.assertEqual(trace.call_args.args[1]['status'], 'SAFETY_ERROR')
        with self.assertRaisesRegex(ValueError, 'PERSISTENCE_INCOMPLETE'):
            self.load()

    def test_season_exit_flushes_transition_and_handoff_before_summary(self):
        import main
        observation = main.HomeObservation(4, 8, 0)
        def summary(**kwargs):
            self.assertEqual(self.load()['home_observation']['season'], 4)
            payload = json.loads((self.directory / 'runtime_state.json').read_text())
            self.assertEqual(payload['boundary'], 'SESSION_END')
        with patch('main.setup_logging'), \
             patch('main.load_config_with_run_state', return_value={'run_state': self.state}), \
             patch('main.REGISTRY_PATH', self.registry), patch('main.write_trace'), \
             patch('main.read_validated_home_observation', return_value=observation), \
             patch('main.season_trial_summary', side_effect=summary), \
             patch('main.run_home_tick') as tick:
            self.assertEqual(main.run_season_trial(3, True, 1), 0)
        tick.assert_not_called()
