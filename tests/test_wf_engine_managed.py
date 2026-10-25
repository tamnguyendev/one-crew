"""Real Supervisor safe point is consumed by the engine without another call."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError, content_hash
from onecrew.task_intake import submit
from onecrew.v2 import executors, managed_executor
from tests.test_wf_managed_executor import ManagedFixture

# W37b/W36 crash point (d): the engine's controller dies after ManagedExecutor wrote the `candidate` checkpoint and before the engine
# published node.produced. A real process death (os._exit) in a child that runs the real engine.step with a local fixture worker; X appends
# one line to the marker file.
CRASH_D = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + '/tests')
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.v2 import engine
from onecrew.v2.managed_executor import ManagedExecutor
ledger = Ledger(Path(sys.argv[2]), Path(sys.argv[3]))
marker = Path(sys.argv[4])
def factory(control, provider):
    class Worker:
        def capability(self): return {'provider': provider, 'mode': 'local-crash-d-fixture'}
        def run(self, attempt, prompt, schema, profile):
            directory = ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
            value = {'summary': 'fixture', 'files': [{'path': 'a.txt', 'content': 'isolated candidate\n'}], 'backlog': []}
            script = ('import pathlib,sys\n'
                      'with pathlib.Path(sys.argv[1]).open("a") as out: out.write("operation completed\\n")\n'
                      'pathlib.Path("answer.json").write_text(sys.argv[2])\n')
            return Supervisor(control).run(attempt, [native_python(), '-c', script, str(marker), json.dumps(value)], cwd=directory,
                                           timeout=min(5, profile['step_seconds']), env=environment())
        def result(self, attempt):
            return json.loads((ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
    return Worker()
adapter = ManagedExecutor(ledger, worker_factory=factory)
real = adapter._write
def write(attempt_id, phase, **facts):
    out = real(attempt_id, phase, **facts)
    if phase == 'candidate': os._exit(43)                 # the controller dies right after the candidate checkpoint
    return out
adapter._write = write
engine.step(ledger, 'P1', adapter)
'''


class EngineManagedTests(ManagedFixture):
    def test_acknowledged_pause_is_held_then_same_candidate_is_released_without_another_process(self):
        self.delay=.5
        thread,result,attempt=self.run_in_background()
        executors.Dispatcher().send(self.adapter,'pause_at_safe_point',attempt,'Temporary scoped hold')
        thread.join(6);self.assertFalse(thread.is_alive());self.assertNotIn('error',result)
        self.assertEqual(result['value']['executor_state'],'paused')
        view=self.engine.state(self.ledger,'P1')
        self.assertEqual(view['nodes']['C']['phase'],'held')
        self.assertIsNone(view['nodes']['C']['artifact'])
        before=self.adapter.control.status(self.adapter.control.attempt(attempt)['task_id'])
        released=self.engine.release_paused(self.ledger,'P1','C',self.adapter)
        self.assertTrue(released['reused_safe_candidate'])
        self.assertEqual(self.launches,[attempt])
        after=self.adapter.control.status(self.adapter.control.attempt(attempt)['task_id'])
        self.assertEqual(before['used_calls'],after['used_calls']);self.assertEqual(before['budget'],after['budget'])
        self.verify('C')

    def test_settled_but_unknown_managed_result_cannot_be_replayed_by_new_internal_revision(self):
        task=submit(self.ledger,'Unknown managed result fixture','unknown-result',plan_selector='plan-ns:P1',max_calls=2,max_seconds=30,provider='codex',model='fixture-model')
        execution=self.adapter.control.configure(task['id'],task['revision'],{'mode':'managed-fixture'})
        attempt=self.adapter.control.reserve(task['id'],execution['revision'],'once',{'unit':'task:C'})
        item=copy.deepcopy(self.ip.current(self.ledger,'P1')['definition']['nodes'][0]);item['input_artifacts']={}
        self.adapter._write(attempt['id'],'prepared',task_revision=task['revision'],node='C',node_sha=content_hash(item),read=item['read'],write=item['write'],inputs_sha=content_hash({}))
        self.adapter.native.start(self.ledger,self.adapter.control,task,item,attempt)
        changed=self.ip.current(self.ledger,'P1')['definition']['nodes'];changed[0]['goal']+=' altered wording'
        with self.assertRaisesRegex(LedgerError,'unknown managed operation'):
            self.revise(changed)
        self.assertEqual(self.launches,[attempt['id']])

    def crash_d(self):
        repo = str(Path(__file__).resolve().parents[1])
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}
        child = subprocess.run([sys.executable, '-X', 'utf8', '-c', CRASH_D, repo, str(self.root), str(self.ledger.state_root), str(self.marker)],
                               capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
        self.assertEqual(child.returncode, 43, child.stderr[-1500:])                    # the controller really died at (d)
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['phase'], view['nodes']['C']['artifact']), ('running', None))
        attempt = view['nodes']['C']['attempt']
        self.assertEqual(self.adapter.control.attempt(attempt)['status'], 'settled')
        self.assertIn('candidate', [p['phase'] for p in self.adapter._history(attempt)])
        return attempt

    def payloads(self, kind):
        return [p for k, p in self.events() if k == kind]

    def charged(self, attempt):
        return self.adapter.control.status(self.adapter.control.attempt(attempt)['task_id'])['used_calls']

    def test_crash_d_candidate_saved_before_publication_is_adopted_once_on_restart(self):
        attempt = self.crash_d()
        charged = self.charged(attempt)
        changed = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes']); changed[0]['goal'] += ' (wording only)'
        with self.assertRaisesRegex(LedgerError, 'managed'):
            self.revise(changed)                                                        # the saved, unpublished candidate is unresolved
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['generation'], 0)
        result = self.engine.step(self.ledger, 'P1', self.adapter)                     # restart
        self.assertEqual(result['state'], 'produced', result)
        saved = self.adapter.state(attempt)['candidate']
        self.assertEqual((result['artifact'], result['receipt']), (saved['artifact'], saved['receipt']))
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['state'], view['nodes']['C']['attempt'], view['nodes']['C']['artifact']), ('produced', attempt, saved['artifact']))
        self.assertEqual(self.kinds().count('node.produced'), 1)
        self.assertEqual(self.launches, []); self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        self.assertEqual(self.charged(attempt), charged)
        self.assertEqual(managed_executor.unresolved(self.ledger, 'P1'), [])
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'waiting')   # nothing published or run twice
        self.assertEqual(self.kinds().count('node.produced'), 1)
        nodes = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes']); nodes[1]['goal'] += ' (wording only)'
        self.revise(nodes)                                                              # a wording-only replan of the integration node
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['state'], view['nodes']['C']['generation'], view['nodes']['C']['attempt']), ('produced', 0, attempt))
        self.assertEqual(self.launches, []); self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        self.assertEqual(self.charged(attempt), charged)
        self.verify('C')

    def test_crash_d_candidate_of_a_moved_generation_is_retained_not_published(self):
        attempt = self.crash_d()
        changed = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes']); changed[0]['goal'] += ' (wording only)'
        with patch.object(managed_executor, 'unresolved', return_value=[]):
            self.revise(changed)                                                        # a build without the check moved the generation
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['generation'], 1)
        self.engine.publish_retained(self.ledger, 'P1')
        retained = [p for p in self.payloads('node.result_retained') if p.get('attempt') == attempt]
        self.assertEqual(len(retained), 1); self.assertEqual(retained[0]['generation'], 0)
        self.assertEqual(retained[0]['candidate'], self.adapter.state(attempt)['candidate'])
        self.assertNotIn('node.produced', self.kinds())
        self.engine.publish_retained(self.ledger, 'P1')
        self.assertEqual(len([p for p in self.payloads('node.result_retained') if p.get('attempt') == attempt]), 1)   # idempotent
        self.assertEqual(managed_executor.unresolved(self.ledger, 'P1'), [])
