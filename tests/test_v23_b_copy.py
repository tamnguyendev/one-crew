"""2.3-B: a copied state root (design §7 case 15) and the honest declarations (case 14).

T10: two real controller crashes leave a reconciled attempt with an unknown result and a node held for a decision; a real Supervisor run
leaves stdout in its attempt folder. The state root is copied, the ORIGINAL folder renamed, and the copy must show the same IDs, budget,
held/unknown states, and read its process outputs from itself (M6), never from the original path.
"""
import contextlib
import io
import json
import os
import shutil
from pathlib import Path

from onecrew import artifact_provider_core
from onecrew.control_core import Control
from onecrew.ledger import Ledger, LedgerError
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.task_intake import submit
from onecrew.v2 import engine, executors, managed_executor
from tests.test_v23_b_takeover import TakeoverFixture, PIN
from tests.test_wf_engine import node


class LedgerCopyTests(TakeoverFixture):
    def supervised_stdout(self):
        task = submit(self.ledger, 'Supervisor stdout fixture', 'v23b-m6-stdout', plan_selector='plan-ns:P1', max_calls=2, max_seconds=60,
                      provider='claude', model='fixture-model')
        execution = self.control.configure(task['id'], task['revision'], {'mode': 'v23b-m6-fixture'})
        attempt = self.control.reserve(task['id'], execution['revision'], 'm6', {'unit': 'task:Z', 'stage': 'Z'})
        work = Path(self.temp.name) / 'm6-work'; work.mkdir()
        body = json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '{}'})
        Supervisor(self.control).run(attempt, [native_python(), '-c', 'import sys; print(sys.argv[1])', body], cwd=work, timeout=30, env=environment())
        return attempt['id']

    def test_t10_a_copied_state_root_keeps_ids_budget_held_and_unknown_and_never_reads_the_original_folder(self):
        self.single()
        for _ in range(2):                                                         # T2 path: crash, swept + replayed, crash again
            code, _, err = self.outcome(self.controller(mode='batch', seconds=30, crash_on_start=True))
            self.assertEqual(code, 41, err)
        self.engine.run_batch(self.ledger, 'P1', self.adapter, slots=1)              # the second interruption is held for a decision
        view = self.engine.state(self.ledger, 'P1')
        a2 = view['nodes']['C']['attempt']
        a1 = next(p['attempt'] for k, p in self.events() if k == 'node.held' and p['generation'] == 0)
        self.assertEqual(view['nodes']['C']['phase'], 'held')
        stdout_attempt = self.supervised_stdout()
        before = {'nodes': {n: {k: r.get(k) for k in ('phase', 'generation', 'attempt', 'classification')} for n, r in view['nodes'].items()},
                  'attempts': {a: {k: self.control.attempt(a)[k] for k in ('id', 'status', 'charged', 'result', 'identity', 'generation')}
                               for a in (a1, a2, stdout_attempt)},
                  'used': self.root_group()['used_calls'],
                  'state': {a: managed_executor.ManagedExecutor(self.ledger, initialize=False).state(a) for a in (a1, a2)}}
        original = Path(self.ledger.state_root)
        copy = original.with_name('state-copy')
        shutil.copytree(original, copy)
        moved = original.with_name('state-original-moved')
        os.rename(original, moved)                                                   # any read of the original path now fails
        ledger = Ledger(self.root, copy)
        control = Control(ledger)
        view2 = engine.state(ledger, 'P1')
        self.assertEqual({n: {k: r.get(k) for k in ('phase', 'generation', 'attempt', 'classification')} for n, r in view2['nodes'].items()},
                         before['nodes'])
        for attempt_id, row in before['attempts'].items():
            self.assertEqual({k: control.attempt(attempt_id)[k] for k in row}, row)
        with ledger.transaction() as conn:
            from onecrew.budget_core import group
            self.assertEqual(group(conn, self.root_view['anchor_task'])['used_calls'], before['used'])
        adapter = managed_executor.ManagedExecutor(ledger, initialize=False)
        for attempt_id in (a1, a2):
            self.assertEqual(adapter.state(attempt_id), before['state'][attempt_id])
            recovered = adapter.recover(attempt_id)
            self.assertEqual((recovered['state'], recovered.get('cleanup')), (before['state'][attempt_id]['state'], 'confirmed'))
        # M6: the process output of an attempt is read inside the state root that holds the attempt, not at the recorded absolute path
        recorded = Path(json.loads(control.attempt(stdout_attempt)['result'])['stdout'])
        self.assertTrue(recorded.is_relative_to(original) and not recorded.exists(), recorded)   # the stored path names the moved original
        worker = artifact_provider_core.ClaudeArtifact(control)
        text = worker.stdout(control.attempt(stdout_attempt))
        self.assertIn('"subtype": "success"', text)
        self.assertFalse(original.exists())
        self.assertEqual(engine.run_batch(ledger, 'P1', managed_executor.ManagedExecutor(ledger, initialize=False), slots=1)['state'], 'waiting')


class DeclarationTests(TakeoverFixture):
    def test_executor_list_shows_the_managed_and_native_declarations_and_the_hook_still_declares_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(executors.main(['list']), 0)
        listed = {d['executor']: d for d in json.loads(out.getvalue())}
        self.assertEqual(listed['claude-code-hook']['capabilities'], [])
        self.assertEqual(listed['managed-native-artifact']['capabilities'], ['isolate', 'measure', 'pause_at_safe_point', 'recover', 'start', 'stop'])
        self.assertEqual(listed['common-native-artifact']['capabilities'], ['measure', 'start'])
        self.assertIn('supervisor', listed['common-native-artifact']['process']['recover'].lower())
        self.assertIn('never', listed['common-native-artifact']['process']['recover'].lower())
        # the observation command is not widened: only the hook and the verifier can be observed from outside
        self.assertEqual(sorted(executors.REGISTRY), ['claude-code-hook', 'command-verifier'])

    def test_q6_a_windows_short_name_path_in_a_node_scope_is_refused(self):
        nodes = [node('C', write=('LONGNA~1.TXT',)), node('I', ['C'], integration=True, write=())]
        nodes[0]['read'] = ['a.txt']
        for item in nodes: item['executor'] = dict(PIN)
        with self.assertRaisesRegex(LedgerError, '8.3'):
            self.revise(nodes)
