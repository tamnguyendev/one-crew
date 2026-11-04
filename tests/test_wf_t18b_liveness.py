"""T18b [E9], [E13] (W51): liveness of a RUNNING command is observed while it runs, through the shared progress tracker, with no model call
and no operator input; silence is not "no progress".

Fixture of tests/test_wf_managed_executor (real local process under the Supervisor). With `control.liveness_every` short, a 1.2 s
operation yields several `executor.observed` progress records of kind `command` for the attempt, elapsed increasing, cap bound to the
node; the checkpoint never says blocked while the command runs within its cap, even though the fixture command prints nothing (E9).
A liveness hook that raises never stops the supervised command.
"""
from unittest.mock import patch

from onecrew.v2 import progress_track
import tests.test_wf_managed_executor as me


class LivenessTests(me.ManagedFixture):
    def fresh_reserved(self, key):
        import copy
        from onecrew.task_intake import submit
        task = submit(self.ledger, 'Local managed intent fixture', key, plan_selector='plan-ns:P1', max_calls=2,
                      max_seconds=30, provider='codex', model='fixture-model')
        execution = self.adapter.control.configure(task['id'], task['revision'], {'mode': 'managed-local-fixture'})
        attempt = self.adapter.control.reserve(task['id'], execution['revision'], key, {'unit': 'task:C', 'stage': 'C'})
        item = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'][0]); item['input_artifacts'] = {}
        return task, item, attempt

    def observations(self, attempt):
        return [p for k, p in self.events() if k == 'executor.observed' and p.get('what') == 'progress' and p.get('attempt') == attempt
                and p['observation'].get('kind') == 'command']

    def test_e9_e13_a_running_command_is_observed_alive_through_the_shared_tracker_and_silence_is_not_blocked(self):
        self.delay = 1.2
        self.adapter.control.liveness_every = 0.2
        task, item, attempt = self.fresh_reserved('liveness')
        with patch.object(progress_track, 'observe', wraps=progress_track.observe) as shared:
            candidate = self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertTrue(candidate['artifact'])
        rows = self.observations(attempt['id'])
        self.assertGreaterEqual(len(rows), 2, rows)                                                  # observed WHILE running
        elapsed = [r['observation']['elapsed_seconds'] for r in rows]
        self.assertEqual(elapsed, sorted(elapsed)); self.assertLess(elapsed[-1], 1.2 + 1.0)
        self.assertTrue(all(r['time_source'] == 'executor_clock' and r['command_cap_seconds'] == item['execution_cap_seconds'] for r in rows))
        self.assertTrue(all(r['checkpoint']['status'] != 'blocked' for r in rows))                 # [E9] silence is not "no progress"
        self.assertGreaterEqual(shared.call_count, len(rows))                                       # [E13] the shared function, not a copy
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])

    def test_a_failing_hook_never_stops_the_command(self):
        self.delay = 0.5
        self.adapter.control.liveness_every = 0.1
        task, item, attempt = self.fresh_reserved('hook-fails')
        real = progress_track.observe
        def flaky(ledger, selector, node, executor, attempt_id, key, observation, **kw):
            if key.startswith('liveness-'): raise RuntimeError('tracker down')                 # only the in-flight observation fails
            return real(ledger, selector, node, executor, attempt_id, key, observation, **kw)
        with patch.object(progress_track, 'observe', side_effect=flaky):
            candidate = self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertTrue(candidate['artifact'])
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        self.assertEqual(self.observations(attempt['id']), [])
