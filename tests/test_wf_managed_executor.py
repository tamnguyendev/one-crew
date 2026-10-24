"""Actual bounded local processes prove managed controls; no provider calls."""
import copy
import contextlib
import io
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError, content_hash
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.task_intake import submit
from onecrew.v2 import executors, managed_executor, plan as plans
from onecrew.v2.cli import main
from tests.test_wf_engine import EngineFixture, node


class ManagedFixture(EngineFixture):
    def setUp(self):
        super().setUp()
        previous = os.environ.get('ONECREW_HOST_HOME')
        os.environ['ONECREW_HOST_HOME'] = str(Path(self.temp.name) / 'host-home')
        self.addCleanup(lambda: os.environ.__setitem__('ONECREW_HOST_HOME', previous) if previous is not None else os.environ.pop('ONECREW_HOST_HOME', None))
        self.marker = Path(self.temp.name) / 'operations.txt'
        self.started = Path(self.temp.name) / 'operation-started'
        self.delay = 0.35
        self.launches = []
        self.adapter = managed_executor.ManagedExecutor(self.ledger, worker_factory=self.factory)
        first = node('C'); first['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
        integration = node('I', ['C'], integration=True, write=())
        integration['executor'] = copy.deepcopy(first['executor'])
        self.revise([first, integration])

    def factory(self, control, provider):
        case = self
        class LocalArtifactWorker:
            def capability(self):
                return {'provider': provider, 'mode': 'local-test-artifact-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.launches.append(attempt['id'])
                directory = case.ledger.state_root / 'worker-io' / attempt['id']
                directory.mkdir(parents=True)
                script = ('import pathlib,sys,time\n'
                    'pathlib.Path(sys.argv[1]).write_text("started")\n'
                    'time.sleep(float(sys.argv[3]))\n'
                    'with pathlib.Path(sys.argv[2]).open("a") as out: out.write("operation completed\\n")\n'
                    'pathlib.Path("answer.json").write_text(sys.argv[4])\n')
                value = {'summary': 'Local fixture candidate', 'files': [{'path': 'a.txt', 'content': 'isolated candidate\n'}], 'backlog': []}
                return Supervisor(control).run(attempt, [native_python(), '-c', script, str(case.started), str(case.marker), str(case.delay), json.dumps(value)],
                    cwd=directory, timeout=min(5, profile['step_seconds']), env=environment())
            def result(self, attempt):
                directory = case.ledger.state_root / 'worker-io' / attempt['id']
                return json.loads((directory / 'answer.json').read_text()), []
        return LocalArtifactWorker()

    def run_in_background(self):
        result = {}
        def run():
            try: result['value'] = self.engine.step(self.ledger, 'P1', self.adapter)
            except BaseException as error: result['error'] = error
        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(lambda: thread.join(8))
        until = time.monotonic() + 5
        while not self.started.exists() and time.monotonic() < until:
            time.sleep(.01)
        self.assertTrue(self.started.exists(), result)
        with self.ledger.transaction() as conn:
            attempt = conn.execute("SELECT id FROM attempts WHERE status='running' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        return thread, result, attempt


class ManagedExecutorTests(ManagedFixture):
    def test_pause_is_requested_during_operation_then_acknowledged_at_real_safe_point(self):
        self.delay = .6
        thread, result, attempt = self.run_in_background()
        requested = executors.Dispatcher().send(self.adapter, 'pause_at_safe_point', attempt, 'Hold only this branch')
        self.assertEqual(requested['state'], 'pause_requested'); self.assertFalse(requested['safe_point_acknowledged'])
        self.assertFalse(self.marker.exists(), 'the current operation is still in flight')
        thread.join(6); self.assertFalse(thread.is_alive()); self.assertNotIn('error', result)
        paused = self.adapter.state(attempt)
        self.assertEqual(paused['state'], 'paused'); self.assertTrue(paused['tree_stopped'])
        self.assertEqual(paused['text'], 'đã dừng tại điểm an toàn')
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')
        self.assertEqual(self.store.context(paused['candidate']['artifact'])['a.txt'], 'isolated candidate\n')
        self.assertGreater(self.adapter.measure(attempt)['seconds'], 0)
        self.assertEqual(self.adapter.measure(attempt)['calls'], 'not_measured')
        before = self.adapter.control.status(self.adapter.control.attempt(attempt)['task_id'])
        recovered = self.adapter.recover(attempt)
        self.assertEqual(recovered['candidate'], paused['candidate']); self.assertEqual(self.launches, [attempt])
        after = self.adapter.control.status(self.adapter.control.attempt(attempt)['task_id'])
        self.assertEqual(after['used_calls'], before['used_calls']); self.assertEqual(after['budget'], before['budget'])
        self.assertFalse(recovered['automatic_restart'])
        self.assertFalse(recovered['host']['registered'])
        from onecrew import host
        from onecrew.process_core import identity
        import datetime as dt
        home = Path(os.environ['ONECREW_HOST_HOME']); home.mkdir()
        host.register(self.ledger.state_root, home)
        host._write(home / 'lease.json', {'identity': identity(os.getpid()), 'heartbeat': dt.datetime.now(dt.timezone.utc).isoformat(),
                                        'roots_seen': {str(self.ledger.state_root.resolve()): {}}})
        observed = self.adapter.state(attempt)
        self.assertTrue(observed['host']['registered']); self.assertTrue(observed['host']['served'])
        self.assertFalse(observed['automatic_restart']); self.assertIn('reboot', observed['restart_reason'])
        isolated = executors.Dispatcher().send(self.adapter, 'isolate', attempt)
        self.assertEqual(isolated['write_scope'], ['a.txt']); self.assertFalse(isolated['network_isolation'])
        self.assertFalse(isolated['read_isolation'])
        before_events = self.ledger.events(self.adapter.control.attempt(attempt)['task_id'])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'executor', 'state', attempt])
        self.assertEqual(code, 0, out.getvalue()); self.assertEqual(json.loads(out.getvalue())['state'], 'paused')
        self.assertEqual(self.ledger.events(self.adapter.control.attempt(attempt)['task_id']), before_events)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'executor', 'recover', attempt])
        self.assertEqual(code, 0, out.getvalue()); self.assertEqual(json.loads(out.getvalue())['candidate'], paused['candidate'])
        self.assertEqual(self.launches, [attempt])

    def test_stop_waits_for_supervisor_tree_death_and_never_calls_it_a_safe_pause(self):
        self.delay = 3
        thread, result, attempt = self.run_in_background()
        request = executors.Dispatcher().send(self.adapter, 'stop', attempt, 'Stop bounded test process')
        self.assertIn(request['state'], ('stop_requested', 'stopped'))
        thread.join(6); self.assertFalse(thread.is_alive())
        stopped = self.adapter.state(attempt)
        self.assertEqual(stopped['state'], 'stopped'); self.assertTrue(stopped['tree_stopped'])
        self.assertFalse(stopped['safe_point_acknowledged']); self.assertIsNone(stopped['candidate'])
        self.assertFalse(self.marker.exists(), 'emergency stop is not claimed as completed operation')
        self.assertEqual(len(self.launches), 1)
        self.adapter.recover(attempt)
        self.assertEqual(len(self.launches), 1)

    def fresh_reserved(self, key):
        task = submit(self.ledger, 'Local managed intent fixture', key, plan_selector='plan-ns:P1', max_calls=2,
                      max_seconds=30, provider='codex', model='fixture-model')
        execution = self.adapter.control.configure(task['id'], task['revision'], {'mode': 'managed-local-fixture'})
        attempt = self.adapter.control.reserve(task['id'], execution['revision'], key, {'unit': 'task:C', 'stage': 'C'})
        item = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'][0]); item['input_artifacts'] = {}
        return task, item, attempt

    def test_crash_before_dispatch_is_once_and_saved_candidate_replays_without_process_or_charge(self):
        task, item, attempt = self.fresh_reserved('before-dispatch')
        original = self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        charged = self.adapter.control.status(task['id'])['used_calls']
        replay = self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertEqual(replay, original); self.assertEqual(self.launches, [attempt['id']])
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        self.assertEqual(self.adapter.control.status(task['id'])['used_calls'], charged)
        settled = self.adapter.control.attempt(attempt['id'])
        receipt = json.loads(settled['result'])
        self.adapter.control.finish(attempt['id'], settled['generation'], receipt)
        self.assertEqual(self.adapter.control.status(task['id'])['used_calls'], charged)
        with self.assertRaisesRegex(LedgerError, 'generation'):
            self.adapter.control.finish(attempt['id'], settled['generation'] + 1, receipt)
        changed = copy.deepcopy(item); changed['input'].append('different inputs')
        with self.assertRaises(LedgerError): self.adapter.start(self.ledger, self.adapter.control, task, changed, attempt)

    def test_unknown_launch_or_missing_candidate_is_reconciled_and_never_blindly_replayed(self):
        task, item, attempt = self.fresh_reserved('ambiguous-launch')
        self.adapter._write(attempt['id'], 'prepared', task_revision=task['revision'], node=item['id'], node_sha=content_hash(item),
                            read=item['read'], write=item['write'], inputs_sha='unknown')
        unknown = self.adapter.recover(attempt['id'])
        self.assertEqual(unknown['state'], 'unknown')
        self.assertEqual(self.adapter.control.attempt(attempt['id'])['status'], 'unknown')
        self.assertEqual(managed_executor.unresolved(self.ledger, 'P1')[0]['attempt'], attempt['id'])
        with self.assertRaises(LedgerError): self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertEqual(self.launches, [])
        self.assertFalse(self.marker.exists())
        with self.assertRaises(LedgerError):
            self.adapter.control.reserve(task['id'], self.adapter.control.status(task['id'])['revision'], 'blind-retry', {'unit': 'task:C'})

    def test_completed_process_before_candidate_checkpoint_is_unknown_and_not_repeated(self):
        task, item, attempt = self.fresh_reserved('process-finished-no-candidate')
        self.adapter._write(attempt['id'], 'prepared', task_revision=task['revision'], node=item['id'], node_sha=content_hash(item),
                            read=item['read'], write=item['write'], inputs_sha=content_hash({}))
        # Fault injection at (c): the process and its Supervisor receipt exist,
        # but the controller lost the result before its candidate checkpoint.
        candidate = self.adapter.native.start(self.ledger, self.adapter.control, task, item, attempt)
        self.store.read_blob(candidate['receipt'])
        before = self.adapter.control.attempt(attempt['id'])
        recovered = self.adapter.recover(attempt['id'])
        self.assertEqual(recovered['state'], 'unknown'); self.assertIsNone(recovered['candidate'])
        with self.assertRaises(LedgerError): self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertEqual(self.launches, [attempt['id']]); self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        self.assertEqual(self.adapter.control.attempt(attempt['id'])['result'], before['result'])

    def test_crash_after_settled_process_before_candidate_checkpoint_rebuilds_from_durable_evidence_without_relaunch(self):
        # Fault injection at (c) with the launch intent on record: the controller dies right before the candidate checkpoint.
        task, item, attempt = self.fresh_reserved('settled-before-checkpoint')
        real_write = self.adapter._write
        def crash_at_checkpoint(attempt_id, phase, **facts):
            if phase == 'candidate': raise RuntimeError('controller died before the candidate checkpoint')
            return real_write(attempt_id, phase, **facts)
        with patch.object(self.adapter, '_write', side_effect=crash_at_checkpoint):
            with self.assertRaises(RuntimeError):
                self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertEqual(self.launches, [attempt['id']]); self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        phases = [p['phase'] for p in self.adapter._history(attempt['id'])]
        self.assertEqual(phases, ['prepared', 'dispatching'])
        charged = self.adapter.control.status(task['id'])['used_calls']
        recovered = self.adapter.recover(attempt['id'])
        self.assertEqual(recovered['state'], 'completed', recovered); self.assertEqual(recovered.get('rebuilt_from'), 'settled-process')
        candidate = recovered['candidate']; self.assertIsNotNone(candidate)
        self.assertEqual(self.store.context(candidate['artifact'])['a.txt'], 'isolated candidate\n')
        receipt = json.loads(self.store.read_blob(candidate['receipt']))
        self.assertEqual((receipt['kind'], receipt['attempt'], receipt['rebuilt_from']), ('native-node-receipt', attempt['id'], 'settled-process'))
        self.assertEqual(self.launches, [attempt['id']], 'no second launch'); self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        self.assertEqual(self.adapter.control.status(task['id'])['used_calls'], charged, 'no second charge')
        self.assertEqual(managed_executor.unresolved(self.ledger, 'P1'), [])
        # the saved rebuilt candidate now replays through start() like any saved candidate: still no process
        self.assertEqual(self.adapter.start(self.ledger, self.adapter.control, task, item, attempt), candidate)
        self.assertEqual(self.launches, [attempt['id']])

    def test_settled_process_failure_is_a_known_failed_result_not_unknown(self):
        task, item, attempt = self.fresh_reserved('process-fails')
        self.delay = 'not-a-number'                     # the fixture operation raises before completing: exit code 1, no candidate
        with self.assertRaisesRegex(LedgerError, 'successful, settled Supervisor'):
            self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertFalse(self.marker.exists())
        recovered = self.adapter.recover(attempt['id'])
        self.assertEqual(recovered['state'], 'failed', recovered); self.assertIsNone(recovered['candidate'])
        self.assertIn('known result', recovered['text'])
        self.assertEqual(self.launches, [attempt['id']])
        with self.assertRaises(LedgerError): self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertEqual(self.launches, [attempt['id']], 'a known failure is never replayed blindly')

    def test_hook_executor_never_receives_managed_pause_or_isolate(self):
        dispatcher = executors.Dispatcher()
        for command in ('pause_at_safe_point', 'stop', 'isolate', 'recover'):
            with self.assertRaises(executors.CapabilityMissing): dispatcher.send(executors.HookAdapter(), command, 'unknown-attempt')
        self.assertEqual(dispatcher.sent, [])

    def crash_controller(self, phase):
        task, item, attempt = self.fresh_reserved('controller-crash-' + phase)
        driver = r'''
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
if sys.argv[7]=='after-dispatch':
    original=adapter.control.launched
    def crash(*args,**kwargs):
        original(*args,**kwargs)
        os._exit(41)
    adapter.control.launched=crash
else:
    original=adapter.control.finish
    def crash(*args,**kwargs):
        if args[2].get('exit_code')==0: os._exit(42)
        return original(*args,**kwargs)
    adapter.control.finish=crash
task=ledger.task(sys.argv[3])
attempt=adapter.control.attempt(sys.argv[4])
adapter.start(ledger,adapter.control,task,json.loads(sys.argv[5]),attempt)
'''
        done = subprocess.run([native_python(), '-c', driver, str(self.root), str(self.ledger.state_root), task['id'], attempt['id'],
                               json.dumps(item), str(self.marker), phase], cwd=Path(__file__).resolve().parents[1],
                              capture_output=True, timeout=8, env=environment(), creationflags=0x08000000 if os.name == 'nt' else 0)
        self.assertEqual(done.returncode, 41 if phase == 'after-dispatch' else 42, done.stderr.decode())
        deadline = time.monotonic() + 3
        recovered = self.adapter.recover(attempt['id'])
        while self.adapter.control.attempt(attempt['id'])['status'] != 'settled' and time.monotonic() < deadline:
            time.sleep(.03); recovered = self.adapter.recover(attempt['id'])
        self.assertEqual(self.adapter.control.attempt(attempt['id'])['status'], 'settled')
        self.assertEqual(recovered['state'], 'unknown'); self.assertIsNone(recovered['candidate'])
        before = self.marker.read_bytes() if self.marker.exists() else None
        saved = self.adapter.control.attempt(attempt['id'])['result']
        with self.assertRaises(LedgerError): self.adapter.start(self.ledger, self.adapter.control, task, item, attempt)
        self.assertEqual(self.marker.read_bytes() if self.marker.exists() else None, before)
        self.assertEqual(self.adapter.control.attempt(attempt['id'])['result'], saved)
        self.assertEqual(self.adapter.control.status(task['id'])['used_calls'], 1)
        return before

    def test_actual_controller_death_after_dispatch_reconciles_before_any_retry(self):
        self.assertIsNone(self.crash_controller('after-dispatch'))

    def test_actual_controller_death_after_effect_before_receipt_keeps_marker_once(self):
        self.assertEqual(self.crash_controller('after-effect').decode().splitlines(), ['operation completed'])
