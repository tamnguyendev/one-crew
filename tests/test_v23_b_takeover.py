"""2.3-B (L1): cleanup completes BEFORE another controller takes over X; real OS processes and real Windows Job objects, no provider.

Every controller is a separate Python process (tests/v23_b_controller.py) running the real engine with the real ManagedExecutor; every
worker runs under the real Supervisor (named per-attempt Job, KILL_ON_JOB_CLOSE) and has a sleeping grandchild in the same Job. A
"hung" controller is a real controller suspended with NtSuspendProcess (never while it holds the ledger lock, except in the lock test).
The test process only ever kills processes it started itself (by handle), never by name.

Design §7 cases: 1 (T8), 2 (T3), 4 (T1, T5, Q4), 6 (T6), 7 (T1); survey T1-T3, T5, T6, T8.
"""
import ctypes
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from onecrew import process_core
from onecrew.budget_core import group
from onecrew.ledger import LedgerError
from onecrew.process_core import identity, native_python, probe
from onecrew.v2 import managed_executor
from tests import v23_b_controller as driver
from tests.test_wf_engine import node
from tests.test_wf_parallel_engine import ParallelFixture

REPO = Path(__file__).resolve().parents[1]
HELPER = Path(driver.__file__).resolve()
NO_WINDOW = 0x08000000
GRACE = 0.5                     # the escalation grace for these tests (process_core.ESCALATION_GRACE_MAX, normally 60 s)
PIN = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}


def alive(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    handle = k.OpenProcess(0x100000, False, pid)
    if not handle: return False
    try: return k.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 258
    finally: k.CloseHandle(ctypes.c_void_p(handle))


def image(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle: raise OSError('cannot open process ' + str(pid))
    try:
        size = ctypes.c_ulong(1024); buffer = ctypes.create_unicode_buffer(1024)
        if not k.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buffer, ctypes.byref(size)): raise OSError('image name unavailable')
        return buffer.value
    finally:
        k.CloseHandle(ctypes.c_void_p(handle))


def suspend(pid, resume=False):
    k = ctypes.WinDLL('kernel32', use_last_error=True); nt = ctypes.WinDLL('ntdll')
    k.OpenProcess.restype = ctypes.c_void_p
    handle = k.OpenProcess(0x0800, False, pid)
    if not handle: raise OSError('cannot open the controller to suspend/resume it')
    try:
        call = nt.NtResumeProcess if resume else nt.NtSuspendProcess
        call.argtypes = [ctypes.c_void_p]
        if call(ctypes.c_void_p(handle)) != 0: raise OSError('NtSuspend/ResumeProcess failed')
    finally:
        k.CloseHandle(ctypes.c_void_p(handle))


class TakeoverFixture(ParallelFixture):
    """Root with the parallel-engine capability (two controllers may each hold one slot); helpers for controller processes."""

    def setUp(self):
        super().setUp()
        previous = os.environ.get('ONECREW_HOST_HOME')
        os.environ['ONECREW_HOST_HOME'] = str(Path(self.temp.name) / 'host-home')
        self.addCleanup(lambda: os.environ.__setitem__('ONECREW_HOST_HOME', previous) if previous is not None else os.environ.pop('ONECREW_HOST_HOME', None))
        base = Path(self.temp.name)
        self.ops = base / 'operations.txt'
        self.started_dir = base / 'started'; self.started_dir.mkdir()
        self.cfg = {'project': str(self.root), 'state': str(self.ledger.state_root), 'plan': 'P1', 'ops': str(self.ops),
                    'started': str(self.started_dir), 'seconds': 0.2, 'timeout': 60}
        self.launches = []
        self.adapter = managed_executor.ManagedExecutor(self.ledger, worker_factory=driver.make_factory(self.ledger, self.cfg, self.launches))
        grace = patch.object(process_core, 'ESCALATION_GRACE_MAX', GRACE, create=True); grace.start(); self.addCleanup(grace.stop)

    # ---- plan -----------------------------------------------------------------------------------------------------------
    def single(self):
        nodes = [node('C'), node('I', ['C'], integration=True, write=())]
        for item in nodes: item['executor'] = dict(PIN)
        self.revise(nodes)

    def pair(self):
        nodes = [node('A'), node('B', write=('b.txt',)), node('I', ['A', 'B'], integration=True, write=())]
        for item in nodes: item['executor'] = dict(PIN)
        self.revise(nodes)

    # ---- processes ------------------------------------------------------------------------------------------------------
    def controller(self, **overrides):
        cfg = dict(self.cfg, **overrides)
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'PYTHONUTF8', 'PYTHONIOENCODING')}
        proc = subprocess.Popen([native_python(), '-X', 'utf8', str(HELPER), json.dumps(cfg)], cwd=str(REPO), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        self.addCleanup(self._kill, proc)
        return proc

    def _kill(self, proc):
        if proc.poll() is None:
            try: suspend(proc.pid, resume=True)
            except OSError: pass
            proc.kill()
        try: proc.communicate(timeout=20)
        except (subprocess.TimeoutExpired, ValueError): pass

    def outcome(self, proc, timeout=90):
        out, err = proc.communicate(timeout=timeout)
        text = out.decode('utf-8', 'replace').strip().splitlines()
        return proc.returncode, (json.loads(text[-1]) if text and text[-1].startswith('{') else None), err.decode('utf-8', 'replace')[-3000:]

    def wait_started(self, count, timeout=60, proc=None):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            rows = []
            for path in sorted(self.started_dir.glob('ATT-*.json')):
                try: rows.append((path.stem, json.loads(path.read_text())))
                except ValueError: pass
            if len(rows) >= count: return rows
            if proc is not None and proc.poll() is not None:
                self.fail('controller exited before its worker started: ' + proc.stderr.read().decode('utf-8', 'replace')[-2000:])
            time.sleep(.05)
        self.fail(f'{count} worker(s) did not start')

    def suspend_unlocked(self, pid):
        """Suspend a controller at a moment it holds no ledger lock (Q4 is tested separately)."""
        for _ in range(200):
            suspend(pid)
            try:
                conn = sqlite3.connect(str(self.ledger.path), timeout=0.2, isolation_level=None)
                try:
                    conn.execute('BEGIN EXCLUSIVE'); conn.execute('ROLLBACK')
                    return
                finally:
                    conn.close()
            except sqlite3.OperationalError:
                suspend(pid, resume=True); time.sleep(.03)
        self.fail('the controller always held the ledger lock')

    def outsider(self):
        proc = subprocess.Popen([native_python(), '-c', 'import time; time.sleep(240)'], creationflags=NO_WINDOW)
        self.addCleanup(self._kill, proc)
        return proc, identity(proc.pid)

    # ---- observations ---------------------------------------------------------------------------------------------------
    def wait_dead(self, *pids, timeout=15):
        until = time.monotonic() + timeout
        while time.monotonic() < until and any(alive(pid) for pid in pids): time.sleep(.05)
        return not any(alive(pid) for pid in pids)

    def root_group(self):
        with self.ledger.transaction() as conn:
            return group(conn, self.root_view['anchor_task'])

    def operations(self):
        return self.ops.read_text().splitlines() if self.ops.exists() else []

    def payloads(self, kind):
        return [p for k, p in self.events() if k == kind]

    def attempt(self, attempt_id):
        return self.adapter.control.attempt(attempt_id)

    def stopped_by_escalation(self, attempt_id, pids):
        """Stop a hung controller's attempt: a stop request alone never kills; recover terminates only after the grace period."""
        stop = self.adapter.stop(attempt_id, 'The controller of this operation is hung; stop it')
        self.assertEqual(stop['state'], 'stop_requested')
        early = self.adapter.recover(attempt_id)                             # the grace has not passed yet
        self.assertNotEqual(self.attempt(attempt_id)['status'], 'settled', early)
        self.assertTrue(alive(pids['worker']) and alive(pids['grandchild']), 'a stop request alone never terminates the tree')
        self.assertEqual(early['state'], 'stop_requested')
        self.assertEqual(early.get('cleanup'), 'pending', early)
        time.sleep(GRACE + .4)
        done = self.adapter.recover(attempt_id)
        self.assertEqual(done['state'], 'stopped', done)
        self.assertTrue(done['tree_stopped'])
        self.assertEqual(done.get('cleanup'), 'confirmed', done)
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild'], timeout=2), 'the whole tree is dead once recovery says so')
        return done


class HungControllerTests(TakeoverFixture):
    def test_t1_hung_controller_is_escalated_only_after_stop_and_grace_then_b_takes_over_and_late_output_is_retained(self):
        self.single()
        before = self.root_group()
        hung = self.controller(mode='step', seconds=40)
        (a1, pids), = self.wait_started(1, proc=hung)
        self.suspend_unlocked(hung.pid)
        # silence is not a reason: no stop request, no passed cap -> nothing is terminated, however long the controller is silent
        time.sleep(GRACE + .4)
        silent = self.adapter.recover(a1)
        self.assertEqual(self.attempt(a1)['status'], 'running', silent)
        self.assertTrue(alive(pids['worker']) and alive(pids['grandchild']))
        self.assertEqual(silent.get('cleanup'), 'pending', silent)
        done = self.stopped_by_escalation(a1, pids)
        settled = json.loads(self.attempt(a1)['result'])
        self.assertEqual(settled['reason'], 'stopped_by_recovery')
        self.assertTrue(settled['tree_stopped'])
        self.assertEqual(settled['job']['active_after'], 0)                   # Q7: the Job's own count is the proof
        self.assertTrue({pids['worker'], pids['grandchild']} <= set(settled['job']['members_before']), settled['job'])
        self.assertEqual(done['cleanup'], 'confirmed')
        # B takes over X only now: a new controller (this process) holds the node with cleanup confirmed and replays it once
        taken = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(taken['state'], 'produced', taken)
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['generation'], view['nodes']['C']['state']), (1, 'produced'))
        a2 = view['nodes']['C']['attempt']
        self.assertNotEqual(a2, a1); self.assertEqual(self.launches, [a2])
        held = [p for p in self.payloads('node.held') if p['node'] == 'C' and p['generation'] == 0]
        self.assertEqual(len(held), 1, held)
        self.assertEqual((held[0]['classification'], held[0]['attempt'], held[0]['cleanup']), ('executor_interrupted', a1, 'confirmed'))
        resumed = [p for p in self.payloads('node.resumed') if p['node'] == 'C']
        self.assertEqual(len(resumed), 1, resumed)
        self.assertEqual((resumed[0]['generation'], resumed[0]['continues_attempt'], resumed[0]['budget_reset']), (0, a1, False))
        # the hung controller wakes up: its late outcome is retained under its original generation, never published
        suspend(hung.pid, resume=True)
        code, late, err = self.outcome(hung)
        self.assertEqual(code, 0, err)
        self.assertNotEqual(late.get('state'), 'produced', late)
        retained = [p for p in self.payloads('node.result_retained') if p.get('attempt') == a1]
        self.assertEqual(len(retained), 1, self.payloads('node.result_retained'))
        self.assertEqual(retained[0]['generation'], 0)
        produced = self.payloads('node.produced')
        self.assertEqual(len(produced), 1); self.assertEqual(produced[0]['generation'], 1)
        self.assertEqual(self.store.context(produced[0]['artifact'])['a.txt'], 'candidate ' + a2 + '\n')
        # nothing reset: both launches were charged on the same root budget, deadline unchanged
        self.assertEqual(self.operations(), ['launched ' + a1, 'launched ' + a2])
        after = self.root_group()
        self.assertEqual((after['used_calls'] - before['used_calls'], after['reserved_calls']), (2, 0))
        self.assertEqual(after['deadline'], before['deadline'])
        for attempt_id in (a1, a2):
            self.assertEqual(self.adapter.control.status(self.attempt(attempt_id)['task_id'])['used_calls'], 1)

    def test_t5_unconfirmed_tree_termination_stays_unknown_keeps_ownership_and_a_later_recover_settles(self):
        self.single()
        hung = self.controller(mode='step', seconds=40)
        (a1, pids), = self.wait_started(1, proc=hung)
        self.suspend_unlocked(hung.pid)
        self.adapter.stop(a1, 'The controller of this operation is hung; stop it')
        time.sleep(GRACE + .4)
        with patch.object(process_core.Job, 'stop', side_effect=LedgerError('injected: TerminateJobObject failed')):
            failed = self.adapter.recover(a1)
            self.assertEqual(failed['state'], 'stop_requested', failed)      # never "stopped" without the proof
            self.assertFalse(failed['tree_stopped'])
            self.assertEqual(failed.get('cleanup'), 'pending', failed)
            self.assertEqual(self.attempt(a1)['status'], 'unknown')           # the unconfirmed escalation is recorded as unknown
            self.assertIn('unconfirmed', json.loads(self.attempt(a1)['result'])['reason'])
            self.assertTrue(alive(pids['worker']) and alive(pids['grandchild']))
            # while the stop stays unconfirmed, ownership is kept: the next step's own sweep escalates again, fails again, and
            # neither re-issues the node nor frees its slot
            waiting = self.engine.step(self.ledger, 'P1', self.adapter)
            self.assertEqual(waiting['state'], 'waiting', waiting)
            self.assertEqual(self.launches, [])
            self.assertEqual(self.attempt(a1)['status'], 'unknown')
            self.assertEqual([u['attempt'] for u in managed_executor.unresolved(self.ledger, 'P1')], [a1])
            with self.ledger.transaction() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts WHERE status IN ('reserved','running','unknown')").fetchone()[0], 1)
            self.assertTrue(alive(pids['worker']) and alive(pids['grandchild']))
        # without the fault the same recovery confirms the stop and settles
        done = self.adapter.recover(a1)
        self.assertEqual((done['state'], done.get('cleanup')), ('stopped', 'confirmed'), done)
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild'], timeout=2))

    def test_t6_an_outside_process_of_the_same_executable_survives_stop_escalation_and_takeover(self):
        self.single()
        outsider, who = self.outsider()
        hung = self.controller(mode='step', seconds=40)
        (a1, pids), = self.wait_started(1, proc=hung)
        self.assertEqual(image(pids['worker']).lower(), image(outsider.pid).lower())     # the same executable as the worker
        self.suspend_unlocked(hung.pid)
        self.stopped_by_escalation(a1, pids)
        self.assertEqual(probe(who), 'alive', 'recovery terminates the attempt Job only, never a process by executable name')
        hung.kill(); hung.wait(timeout=20)
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'produced')
        self.assertEqual(probe(who), 'alive')
        self.assertIsNone(outsider.poll())

    def test_q4_a_suspended_lock_holder_means_nothing_is_recorded_and_nothing_is_terminated(self):
        self.single()
        hung = self.controller(mode='step', seconds=60)
        (a1, pids), = self.wait_started(1, proc=hung)
        self.suspend_unlocked(hung.pid)
        self.adapter.stop(a1, 'The controller of this operation is hung; stop it')
        time.sleep(GRACE + .4)
        flag = Path(self.temp.name) / 'lock-held'
        holder = subprocess.Popen([native_python(), '-c', 'import sqlite3,sys,time,pathlib\n'
                                   'c=sqlite3.connect(sys.argv[1],isolation_level=None); c.execute("BEGIN"); c.execute("SELECT COUNT(*) FROM events").fetchone()\n'
                                   'pathlib.Path(sys.argv[2]).write_text("held"); time.sleep(120)', str(self.ledger.path), str(flag)],
                                  creationflags=NO_WINDOW)
        self.addCleanup(self._kill, holder)
        until = time.monotonic() + 20
        while not flag.exists() and time.monotonic() < until: time.sleep(.05)
        self.assertTrue(flag.exists())
        with self.assertRaises(sqlite3.OperationalError):                    # the ledger cannot record the intent: nothing is done
            self.adapter.recover(a1)
        self.assertTrue(alive(pids['worker']) and alive(pids['grandchild']), 'no termination without a recorded intent')
        holder.kill(); holder.wait(timeout=20)
        self.assertEqual(self.attempt(a1)['status'], 'running')
        self.assertEqual(self.adapter.state(a1).get('cleanup'), 'pending')
        done = self.adapter.recover(a1)
        self.assertEqual((done['state'], done.get('cleanup')), ('stopped', 'confirmed'), done)


class CrashSweepTests(TakeoverFixture):
    def test_t2_crash_is_swept_held_and_replayed_once_then_a_second_crash_stays_held_without_a_third_launch(self):
        self.single()
        first = self.controller(mode='batch', seconds=30, crash_on_start=True)
        code, _, err = self.outcome(first)
        self.assertEqual(code, 41, err)
        (a1, pids), = self.wait_started(1)
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild']), 'KILL_ON_JOB_CLOSE took the tree with the controller')
        self.assertEqual(self.attempt(a1)['status'], 'running')                # nobody has reconciled it yet
        second = self.controller(mode='batch', seconds=30, crash_on_start=True)
        code, _, err = self.outcome(second)
        self.assertEqual(code, 41, err)                                        # the second controller swept a1, replayed, and crashed too
        settled = json.loads(self.attempt(a1)['result'])
        self.assertEqual((self.attempt(a1)['status'], settled['reason'], settled['tree_stopped']), ('settled', 'supervisor_interrupted', True))
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['generation'], view['nodes']['C']['phase']), (1, 'running'))
        a2 = view['nodes']['C']['attempt']; self.assertNotEqual(a2, a1)
        first_hold = [p for p in self.payloads('node.held') if p['node'] == 'C' and p['generation'] == 0]
        self.assertEqual(len(first_hold), 1)
        self.assertEqual((first_hold[0]['cleanup'], first_hold[0]['decision']), ('confirmed', 'replay'), first_hold[0])
        resumed = self.payloads('node.resumed')
        self.assertEqual(len(resumed), 1); self.assertFalse(resumed[0]['budget_reset'])
        # a third controller (this process): the second interruption is held for a decision, no third launch
        result = self.engine.run_batch(self.ledger, 'P1', self.adapter, slots=1)
        self.assertEqual(result['state'], 'waiting', result)
        self.assertEqual(self.launches, [])
        self.assertEqual(len(self.operations()), 2, self.operations())
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['phase'], view['nodes']['C']['generation'], view['nodes']['C']['classification']),
                         ('held', 1, 'executor_interrupted'))
        second_hold = [p for p in self.payloads('node.held') if p['node'] == 'C' and p['generation'] == 1]
        self.assertEqual(len(second_hold), 1)
        self.assertEqual((second_hold[0]['cleanup'], second_hold[0]['decision'], second_hold[0]['attempt']), ('confirmed', 'ask', a2))
        self.assertEqual(len(self.payloads('node.resumed')), 1)
        self.assertEqual(self.root_group()['used_calls'], 2)
        self.assertEqual(managed_executor.unresolved(self.ledger, 'P1'), [])   # cleanup confirmed and held: a replan is not blocked
        self.assertEqual(self.adapter.state(a2).get('cleanup'), 'confirmed')
        self.assertEqual(self.engine.run_batch(self.ledger, 'P1', self.adapter, slots=1)['state'], 'waiting')   # idempotent
        self.assertEqual(len([p for p in self.payloads('node.held') if p['node'] == 'C']), 2)


class IndependentNodeTests(TakeoverFixture):
    def test_t3_independent_node_keeps_running_in_its_own_controller_while_a_is_stopped(self):
        self.pair()
        ctl_a = self.controller(mode='step', target='A', slots=2, seconds=40)
        (a1, a_pids), = self.wait_started(1, proc=ctl_a)
        ctl_b = self.controller(mode='step', target='B', slots=2, seconds=10)
        rows = dict(self.wait_started(2, proc=ctl_b)); b1 = next(k for k in rows if k != a1); b_pids = rows[b1]
        self.suspend_unlocked(ctl_a.pid)
        # A cannot be re-issued while it is not settled
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter, slots=2, _target='A')['state'], 'waiting')
        self.stopped_by_escalation(a1, a_pids)
        self.assertTrue(alive(b_pids['worker']) and alive(b_pids['grandchild']), "terminating A's Job never touches B's Job")
        self.assertEqual(self.attempt(b1)['status'], 'running')
        code, result, err = self.outcome(ctl_b)                               # B's own controller finishes B
        self.assertEqual(code, 0, err)
        self.assertEqual((result['node'], result['state']), ('B', 'produced'), result)
        taken = self.engine.step(self.ledger, 'P1', self.adapter, slots=2, _target='A')
        self.assertEqual((taken['node'], taken['state']), ('A', 'produced'), taken)
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['A']['generation'], view['nodes']['B']['generation']), (1, 0))
        suspend(ctl_a.pid, resume=True)
        code, late, err = self.outcome(ctl_a)
        self.assertEqual(code, 0, err)
        self.assertEqual([p['node'] for p in self.payloads('node.produced')], ['B', 'A'])
        self.assertEqual(len(self.operations()), 3)

    def test_t3b_two_attempts_in_one_hung_controller_a_is_terminated_alone_and_the_same_sweep_recovers_both(self):
        self.pair()
        shared = self.controller(mode='batch', slots=2, seconds=40)
        rows = dict(self.wait_started(2, proc=shared))
        view = self.engine.state(self.ledger, 'P1')
        a1, b1 = view['nodes']['A']['attempt'], view['nodes']['B']['attempt']
        self.suspend_unlocked(shared.pid)
        self.stopped_by_escalation(a1, rows[a1])
        self.assertTrue(alive(rows[b1]['worker']) and alive(rows[b1]['grandchild']), "B's own Job is untouched")
        self.assertEqual(self.attempt(b1)['status'], 'running')
        # B shares the hung controller and cannot progress (documented limit). Ending that controller ends B's tree with its Job.
        shared.kill(); shared.wait(timeout=20)
        self.assertTrue(self.wait_dead(rows[b1]['worker'], rows[b1]['grandchild']))
        result = self.engine.run_batch(self.ledger, 'P1', self.adapter, slots=2)
        self.assertEqual(sorted((r['node'], r['state']) for r in result['results']), [('A', 'produced'), ('B', 'produced')], result)
        held = sorted((p['node'], p['attempt'], p['cleanup']) for p in self.payloads('node.held'))
        self.assertEqual(held, sorted([('A', a1, 'confirmed'), ('B', b1, 'confirmed')]))
        self.assertEqual(json.loads(self.attempt(b1)['result'])['reason'], 'supervisor_interrupted')
        self.assertEqual(len(self.launches), 2)


class ConcurrentCallerTests(TakeoverFixture):
    def test_t8_two_controller_processes_stepping_the_same_ready_node_run_one_executor_body(self):
        self.single()
        go = Path(self.temp.name) / 'go'
        outs = [Path(self.temp.name) / f'out-{i}.json' for i in (1, 2)]
        procs = [self.controller(mode='step', seconds=1, go=str(go), out=str(out)) for out in outs]
        until = time.monotonic() + 60                                         # both interpreters are up and waiting for the go file
        while len(list(go.parent.glob('go.ready-*'))) < 2 and time.monotonic() < until: time.sleep(.02)
        self.assertEqual(len(list(go.parent.glob('go.ready-*'))), 2)
        go.write_text('go')
        results = []
        for proc in procs:
            code, result, err = self.outcome(proc)
            self.assertEqual(code, 0, err)
            results.append(result)
        self.assertEqual(sorted(r['state'] for r in results), ['produced', 'waiting'], results)
        self.assertEqual(len(self.operations()), 1, self.operations())     # one executor body
        attempt = self.engine.state(self.ledger, 'P1')['nodes']['C']['attempt']
        self.assertEqual(self.adapter.control.status(self.attempt(attempt)['task_id'])['used_calls'], 1)
        self.assertEqual(self.root_group()['used_calls'], 1)
