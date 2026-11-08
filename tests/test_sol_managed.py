"""The existing single-node CLI can own real fixture processes and their evidence."""
import contextlib
import io
import json
from unittest.mock import patch

from onecrew.v2 import engine_cli, progress_track
from tests.test_wf_managed_executor import ManagedFixture


class ManagedEntryTests(ManagedFixture):
    def test_managed_cli_observes_silent_process_then_publishes_actual_candidate(self):
        self.delay = .4
        self.adapter.control.liveness_every = .05
        output = io.StringIO()
        def connected(ledger):
            self.adapter.ledger = ledger
            return self.adapter
        with patch('onecrew.v2.managed_executor.ManagedExecutor', side_effect=connected), contextlib.redirect_stdout(output):
            code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root),
                                    'engine', 'step', 'P1', '--managed'])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(result['state'], 'produced', result)
        observations = [p for k, p in self.events() if k == 'executor.observed' and p.get('what') == 'progress']
        clocks = [p for p in observations if p['time_source'] == 'executor_clock']
        self.assertTrue(clocks, observations)
        self.assertTrue(all(p['checkpoint']['status'] == 'unknown' for p in clocks))
        self.assertTrue(all(p['observation']['output_hash'] is None for p in clocks))
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(self.adapter.state(self.launches[0])['state'], 'completed')

    def test_finite_execution_window_stops_real_tree_and_repeated_step_does_not_retry(self):
        self.delay = 10
        current = self.ip.current(self.ledger, 'P1')['definition']['nodes']
        current[0]['execution_cap_seconds'] = 3
        current[0]['estimate_seconds'] = [.1, .5]
        self.revise(current)
        self.adapter.control.liveness_every = .05
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'held', result)
        held = [p for k, p in self.events() if k == 'node.held'][-1]
        self.assertEqual(held['classification'], 'executor_stopped')
        self.assertIn(held['trigger'], ('execution_cap', 'deadline'))
        self.assertEqual(held['cleanup'], 'confirmed')
        proof = json.loads(self.store.read_blob(held['process_receipt']))
        self.assertTrue(proof['tree_stopped'])
        self.assertIn(proof['reason'], ('timeout', 'deadline'))
        self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(len(self.launches), 1)
        self.assertFalse(self.marker.exists())
