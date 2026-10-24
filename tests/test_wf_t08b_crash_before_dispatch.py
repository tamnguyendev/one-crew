"""T08b crash point (a) with a REAL process death (W37b, R08): the controller dies after the `prepared` intent and before the `dispatching`
intent; after restart X runs exactly once ([E1]), the marker file has one line, no candidate is replayed from nothing, and the charge is one.

The crash is a child Python process that opens the fixture ledger, reserves the attempt, and whose worker factory calls `os._exit` while the
native executor prepares (before any dispatch intent or launch). The parent then starts the same attempt with the normal fixture worker.
(b)/(c) with real processes live in tests/test_wf_managed_executor (interrupted process, settled-before-checkpoint rebuild).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from onecrew.ledger import content_hash
from onecrew.v2 import managed_executor
import tests.test_wf_managed_executor as me

CHILD = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + '/tests')
from onecrew.ledger import Ledger
from onecrew.control_core import Control, migrate
from onecrew.task_intake import submit
from onecrew.v2 import managed_executor, internal_plan
project, state = sys.argv[2], sys.argv[3]
ledger = Ledger(project, state)
def dying_factory(control, provider):
    class Dying:
        def capability(self): return {'provider': provider, 'mode': 'fixture'}
        def run(self, *a): raise AssertionError('must not launch')
        def result(self, attempt): raise AssertionError('no result')
    os._exit(3)                                           # the controller dies while preparing: after `prepared`, before `dispatching`
adapter = managed_executor.ManagedExecutor(ledger, worker_factory=dying_factory)
task = submit(ledger, 'Local managed intent fixture', 'crash-a', plan_selector='plan-ns:P1', max_calls=2, max_seconds=30, provider='codex', model='fixture-model')
execution = adapter.control.configure(task['id'], task['revision'], {'mode': 'managed-local-fixture'})
attempt = adapter.control.reserve(task['id'], execution['revision'], 'crash-a', {'unit': 'task:C', 'stage': 'C'})
item = internal_plan.current(ledger, 'P1')['definition']['nodes'][0]; item['input_artifacts'] = {}
print(json.dumps({'task': task['id'], 'attempt': attempt['id']}), flush=True)
adapter.start(ledger, adapter.control, task, item, attempt)
'''


class CrashBeforeDispatchTests(me.ManagedFixture):          # the fixture class carries no tests of its own
    def test_e1_a_real_crash_after_prepared_before_dispatching_runs_x_exactly_once_after_restart(self):
        repo = str(Path(__file__).resolve().parents[1])
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}
        child = subprocess.run([sys.executable, '-X', 'utf8', '-c', CHILD, repo, str(self.root), str(self.ledger.state_root)],
                               capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
        self.assertEqual(child.returncode, 3, child.stderr[-800:])                           # the process really died
        ids = json.loads(child.stdout.strip().splitlines()[-1])
        history = self.adapter._history(ids['attempt'])
        self.assertEqual([p['phase'] for p in history], ['prepared'])                          # intent on record, no dispatch intent
        self.assertEqual(self.adapter.control.attempt(ids['attempt'])['status'], 'reserved')
        self.assertFalse(self.marker.exists())                                                 # X never ran
        task = self.ledger.task(ids['task'], full=True)
        item = self.ip.current(self.ledger, 'P1')['definition']['nodes'][0]; item['input_artifacts'] = {}
        attempt = self.adapter.control.attempt(ids['attempt'])
        candidate = self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)     # restart
        self.assertTrue(candidate['artifact'])
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])       # [E1] X ran exactly once
        self.assertEqual(self.launches, [ids['attempt']])
        phases = [p['phase'] for p in self.adapter._history(ids['attempt'])]
        self.assertEqual(phases.count('prepared'), 1); self.assertIn('dispatching', phases); self.assertIn('candidate', phases)
        charged = self.adapter.control.status(ids['task'])['used_calls']
        replay = self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)          # a second restart replays the saved candidate
        self.assertEqual(replay, candidate); self.assertEqual(self.launches, [ids['attempt']])
        self.assertEqual(self.adapter.control.status(ids['task'])['used_calls'], charged)
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
