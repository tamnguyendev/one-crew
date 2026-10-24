"""T30 [E6] (W37b): the two wrong wirings the integration checks must catch — a recovery path that skips reconcile, and a status that
says "running in the background" without reading the host.

(1) The controller really dies (os._exit) right after the `dispatching` intent of a managed attempt. The real `ManagedExecutor.recover`
reconciles the orphaned Supervisor job and settles the attempt (tests.test_wf_managed_executor). A mutant recover that only reads state
and never calls `Supervisor.reconcile` leaves the attempt un-settled for the whole deadline: the integration check (settled, unknown,
nothing replayed) goes red, so a recovery that forgets reconcile cannot pass it. (2) A mutant `host_status_core.status` that reports
alive/served without reading `roots.json`/`lease.json` contradicts the on-disk evidence (no host home at all) and the E2/E4 check
(`not alive`, `not served`, no automatic restart) goes red.
"""
import copy
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import host_status_core
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.task_intake import submit
from onecrew.v2 import managed_executor
import tests.test_wf_managed_executor as me

DRIVER = r'''
import json, os, sys
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.v2.managed_executor import ManagedExecutor
ledger=Ledger(Path(sys.argv[1]),Path(sys.argv[2]))
marker=Path(sys.argv[6])
def factory(control,provider):
    class Worker:
        def capability(self): return {'provider':provider,'mode':'local-crash-fixture'}
        def run(self,attempt,prompt,schema,profile):
            directory=ledger.state_root/'worker-io'/attempt['id']; directory.mkdir(parents=True)
            script=r'import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_text("operation completed\n")'
            return Supervisor(control).run(attempt,[native_python(),'-c',script,str(marker)],cwd=directory,timeout=3,env=environment())
        def result(self,attempt):
            return {'summary':'fixture','files':[{'path':'a.txt','content':'candidate\n'}],'backlog':[]},[]
    return Worker()
adapter=ManagedExecutor(ledger,worker_factory=factory)
original=adapter.control.launched
def crash(*args,**kwargs):
    original(*args,**kwargs)
    os._exit(41)
adapter.control.launched=crash
task=ledger.task(sys.argv[3])
attempt=adapter.control.attempt(sys.argv[4])
adapter.start(ledger,adapter.control,task,json.loads(sys.argv[5]),attempt)
'''


class RecoveryCounterexampleTests(me.ManagedFixture):              # the fixture class carries no tests of its own
    def fresh_reserved(self, key):                                    # as tests.test_wf_managed_executor.ManagedExecutorTests.fresh_reserved
        task = submit(self.ledger, 'Local managed intent fixture', key, plan_selector='plan-ns:P1', max_calls=2,
                      max_seconds=30, provider='codex', model='fixture-model')
        execution = self.adapter.control.configure(task['id'], task['revision'], {'mode': 'managed-local-fixture'})
        attempt = self.adapter.control.reserve(task['id'], execution['revision'], key, {'unit': 'task:C', 'stage': 'C'})
        item = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'][0]); item['input_artifacts'] = {}
        return task, item, attempt

    def crash_after_dispatch(self):
        task, item, attempt = self.fresh_reserved('controller-crash-no-reconcile')
        done = subprocess.run([native_python(), '-c', DRIVER, str(self.root), str(self.ledger.state_root), task['id'], attempt['id'],
                               json.dumps(item), str(self.marker)], cwd=Path(__file__).resolve().parents[1],
                              capture_output=True, timeout=8, env=environment(), creationflags=0x08000000 if os.name == 'nt' else 0)
        self.assertEqual(done.returncode, 41, done.stderr.decode())
        return task, item, attempt

    def test_e6_a_recovery_that_skips_reconcile_never_settles_the_crashed_attempt(self):
        task, item, attempt = self.crash_after_dispatch()

        def no_reconcile(self_, attempt_id):                          # mutant: reads state, never reconciles the orphaned job
            self_._ack_pause(attempt_id)
            return self_.state(attempt_id)

        reconciles = []
        real = Supervisor.reconcile
        with patch.object(managed_executor.ManagedExecutor, 'recover', no_reconcile), \
             patch.object(Supervisor, 'reconcile', lambda self_, *a, **k: (reconciles.append(a), real(self_, *a, **k))[1]):
            deadline = time.monotonic() + 1.5
            while self.adapter.control.attempt(attempt['id'])['status'] != 'settled' and time.monotonic() < deadline:
                time.sleep(.05); self.adapter.recover(attempt['id'])
            status = self.adapter.control.attempt(attempt['id'])['status']
        self.assertEqual(reconciles, [], 'the mutant never reconciled')
        self.assertNotEqual(status, 'settled', 'the integration check (settled after recover) is red for the mutant')   # [E6] caught
        # the real path, afterwards, settles the same attempt by reconciling first and replays nothing
        deadline = time.monotonic() + 3
        recovered = self.adapter.recover(attempt['id'])
        while self.adapter.control.attempt(attempt['id'])['status'] != 'settled' and time.monotonic() < deadline:
            time.sleep(.03); recovered = self.adapter.recover(attempt['id'])
        self.assertEqual(self.adapter.control.attempt(attempt['id'])['status'], 'settled')
        self.assertEqual(recovered['state'], 'unknown'); self.assertIsNone(recovered['candidate'])
        history = [p['phase'] for p in self.adapter._history(attempt['id'])]
        self.assertIn('reconciled', history)
        self.assertLess(history.index('dispatching'), history.index('reconciled'))                      # reconcile comes before anything else
        with self.assertRaises(me.LedgerError):
            self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)                   # nothing is replayed
        self.assertEqual(self.adapter.control.status(task['id'])['used_calls'], 1)


class HostStatusCounterexampleTests(unittest.TestCase):
    def test_e6_a_status_that_claims_background_running_without_reading_the_host_is_caught(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / 'not-created'
            real = host_status_core.status(Path(temp) / 'state', base)
            self.assertFalse(real['alive']); self.assertFalse(real['served']); self.assertFalse(real['automatic_restart_after_reboot'])
            reads = []
            with patch.object(host_status_core, '_read', lambda path, default: (reads.append(path), default)[1]), \
                 patch.object(host_status_core, 'lease', lambda base_: {'pid': 1, 'heartbeat': 'now'}), \
                 patch.object(host_status_core, 'served', lambda *a, **k: True):                       # mutant: claims a live host from nothing
                mutant = host_status_core.status(Path(temp) / 'state', base)
            self.assertTrue(mutant['alive'] and mutant['served'])
            self.assertFalse(base.exists())                                                              # no host evidence exists at all
            self.assertNotEqual((mutant['alive'], mutant['served']), (real['alive'], real['served']), 'the E2/E4 check is red for the mutant')
            self.assertFalse(mutant['automatic_restart_after_reboot'])                                   # even the mutant cannot promise a reboot restart
            self.assertIn('reboot', mutant['text'])
