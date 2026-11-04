"""2.3-B (L1): cleanup completes BEFORE another controller takes over X; real OS processes and real Windows Job objects, no provider.

Every controller is a separate Python process (tests/v23_b_controller.py) running the real engine with the real ManagedExecutor; every
worker runs under the real Supervisor (named per-attempt Job, KILL_ON_JOB_CLOSE) and has a sleeping grandchild in the same Job. A
"hung" controller is a real controller suspended with NtSuspendProcess (never while it holds the ledger lock, except in the lock test).
The test process only ever kills processes it started itself (by handle), never by name.

Design §7 cases: 1 (T8), 2 (T3), 4 (T1, T5, Q4), 6 (T6), 7 (T1); survey T1-T3, T5, T6, T8.
Independent review of 72b1b22 (D:\\OneCrewRuns\\v23\\review-b.md): F1 copied root, F2 stop/cap ends held, F3 orphan Job, F4 grace floor,
F5 held inputs release the attempt, F10 Job gone while the controller lives (ReviewFindingTests, GraceBoundTests).
"""
import ctypes
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import process_core
from onecrew.budget_core import group
from onecrew.ledger import Ledger, LedgerError
from onecrew.process_core import Supervisor, identity, native_python, probe
from onecrew.subscription import environment
from onecrew.task_intake import submit
from onecrew.v2 import engine, managed_executor, runtime_unknowns
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


class _SessionInfo(ctypes.Structure):
    _fields_ = [('id', ctypes.c_ulong), ('name', ctypes.c_wchar_p), ('state', ctypes.c_int)]


def sessions():
    """The Windows session ids that exist now (WTSEnumerateSessionsW); the test's own helper so it also runs on older builds."""
    wts = ctypes.WinDLL('wtsapi32')
    pointer, count = ctypes.POINTER(_SessionInfo)(), ctypes.c_ulong()
    if not wts.WTSEnumerateSessionsW(None, 0, 1, ctypes.byref(pointer), ctypes.byref(count)):
        raise OSError('WTSEnumerateSessionsW failed')
    try:
        return sorted(int(pointer[i].id) for i in range(count.value))
    finally:
        wts.WTSFreeMemory(pointer)


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
        for name in ('ESCALATION_GRACE_MAX', 'ESCALATION_GRACE_FLOOR'):      # the floor exists from the review fix F4 on
            grace = patch.object(process_core, name, GRACE, create=True); grace.start(); self.addCleanup(grace.stop)

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

    def end_own_job(self, name):
        job = process_core.Job.open(name)                                    # only the Job this test's own processes live in
        if job is not None:
            try: job.stop()
            except LedgerError: pass
            finally: job.close()

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

    def token(self, attempt_id):
        return json.loads(self.attempt(attempt_id)['identity'])

    def held(self, nid, generation):
        return [p for p in self.payloads('node.held') if p['node'] == nid and p['generation'] == generation]

    def replan_wording(self, nid):
        """The operator's replan after a held stop: a wording-only change of `nid` gives it a new generation (B takes X over)."""
        nodes = self.ip.current(self.ledger, 'P1')['definition']['nodes']
        for item in nodes:
            if item['id'] == nid: item['goal'] += ' (taken over after a confirmed stop)'
        return self.revise(nodes)

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
    def test_t1_hung_controller_is_escalated_only_after_stop_and_grace_held_then_b_takes_over_and_late_output_is_retained(self):
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
        with self.assertRaises(LedgerError):                                  # X is still owned: no replan can take it over yet
            self.replan_wording('C')
        done = self.stopped_by_escalation(a1, pids)
        settled = json.loads(self.attempt(a1)['result'])
        self.assertEqual(settled['reason'], 'stopped_by_recovery')
        self.assertTrue(settled['tree_stopped'])
        self.assertEqual(settled['job']['active_after'], 0)                   # Q7: the Job's own count is the proof
        self.assertTrue({pids['worker'], pids['grandchild']} <= set(settled['job']['members_before']), settled['job'])
        self.assertEqual(done['cleanup'], 'confirmed')
        self.assertEqual(settled['trigger'], 'stop_requested')
        # a stop ends HELD, exactly like a healthy controller that honours it (review F2): no automatic replay, no new charge
        stopped = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(stopped['state'], 'waiting', stopped)
        self.assertEqual(self.launches, [])
        held = self.held('C', 0)
        self.assertEqual(len(held), 1, held)
        self.assertEqual((held[0]['classification'], held[0]['attempt'], held[0]['cleanup'], held[0]['trigger']),
                         ('executor_stopped', a1, 'confirmed', 'stop_requested'))
        self.assertEqual(self.payloads('node.resumed'), [])
        # B takes over X only now: cleanup is confirmed, so the attempt no longer blocks the operator's replan; generation 1 runs
        self.assertEqual(managed_executor.unresolved(self.ledger, 'P1'), [])
        self.replan_wording('C')
        taken = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(taken['state'], 'produced', taken)
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['generation'], view['nodes']['C']['state']), (1, 'produced'))
        a2 = view['nodes']['C']['attempt']
        self.assertNotEqual(a2, a1); self.assertEqual(self.launches, [a2])
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
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'waiting')     # the stopped node is held
        self.assertEqual(self.held('C', 0)[0]['classification'], 'executor_stopped')
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
        stopped = self.engine.step(self.ledger, 'P1', self.adapter, slots=2, _target='A')
        self.assertEqual(stopped['state'], 'waiting', stopped)                # the stopped A is held, nothing replayed
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['A']['phase'], view['nodes']['A']['classification'], view['nodes']['B']['state']),
                         ('held', 'executor_stopped', 'produced'))
        suspend(ctl_a.pid, resume=True)
        code, late, err = self.outcome(ctl_a)
        self.assertEqual(code, 0, err)
        self.assertEqual([p['node'] for p in self.payloads('node.produced')], ['B'])
        self.assertEqual([p['attempt'] for p in self.payloads('node.result_retained')], [a1])   # A's late outcome
        self.assertEqual(len(self.operations()), 2)

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
        # A was stopped -> held; B lost its controller without any stop or cap -> the one policy replay
        self.assertEqual([(r['node'], r['state']) for r in result['results']], [('B', 'produced')], result)
        held = sorted((p['node'], p['attempt'], p['cleanup'], p['classification']) for p in self.payloads('node.held'))
        self.assertEqual(held, [('A', a1, 'confirmed', 'executor_stopped'), ('B', b1, 'confirmed', 'executor_interrupted')])
        self.assertEqual(json.loads(self.attempt(b1)['result'])['reason'], 'supervisor_interrupted')
        self.assertEqual(len(self.launches), 1)


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


class ReviewFindingTests(TakeoverFixture):
    """The reviewer's cases of review-b.md, each red on 72b1b22."""

    def copy_state_root(self):
        original = Path(self.ledger.state_root)
        copy = original.with_name('state-copy')
        shutil.copytree(original, copy, ignore=shutil.ignore_patterns(self.ledger.path.name, self.ledger.path.name + '-journal'))
        source, target = sqlite3.connect(str(self.ledger.path)), sqlite3.connect(str(copy / self.ledger.path.relative_to(original)))
        try: source.backup(target)
        finally: source.close(); target.close()
        return Ledger(self.root, copy)

    def test_f1_a_copied_state_root_never_terminates_the_original_roots_live_tree(self):
        self.single()
        ctl = self.controller(mode='step', seconds=40)                       # a HEALTHY controller of the original root
        (a1, pids), = self.wait_started(1, proc=ctl)
        copied = self.copy_state_root()
        other = managed_executor.ManagedExecutor(copied, initialize=False)
        self.assertEqual(other.stop(a1, 'Stop this operation in the copy only')['state'], 'stop_requested')
        time.sleep(GRACE + .4)
        recovered = other.recover(a1)                                          # due by the copy's own stop request, but not its Job
        self.assertEqual((recovered['state'], recovered['cleanup']), ('stop_requested', 'pending'), recovered)
        escalation = [p for p in other._history(a1) if p['phase'] == 'reconciled'][-1]['result']['escalation']
        self.assertIn('another state root', escalation['reason'])
        self.assertEqual(engine.step(copied, 'P1', other)['state'], 'waiting')     # the copy's sweep does not terminate it either
        self.assertTrue(alive(pids['worker']) and alive(pids['grandchild']), "a copy never terminates the original root's tree")
        self.assertEqual(self.attempt(a1)['status'], 'running')
        # the original root still owns A: its own stop is honoured by its healthy controller and ends held, as before 2.3-B
        self.adapter.stop(a1, 'Stop this operation in the original root')
        code, result, err = self.outcome(ctl)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.attempt(a1)['result'])['reason'], 'cancelled')
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['phase'], 'held')

    def test_f2_a_controller_that_dies_after_the_stop_request_ends_held_not_replayed(self):
        self.single()
        ctl = self.controller(mode='step', seconds=40)
        (a1, pids), = self.wait_started(1, proc=ctl)
        self.suspend_unlocked(ctl.pid)
        self.adapter.stop(a1, 'Stop this operation')
        ctl.kill(); ctl.wait(timeout=20)                                       # killed while suspended: it never saw the request
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild']))
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'waiting', result)
        self.assertEqual(json.loads(self.attempt(a1)['result'])['reason'], 'supervisor_interrupted')
        held = self.held('C', 0)
        self.assertEqual([(h['classification'], h['trigger'], h['cleanup']) for h in held], [('executor_stopped', 'stop_requested', 'confirmed')])
        self.assertEqual(self.payloads('node.resumed'), [])
        self.assertEqual((self.launches, len(self.operations())), ([], 1))

    def test_f2_a_passed_cap_of_a_hung_controller_ends_held_not_replayed(self):
        self.single()
        hung = self.controller(mode='step', seconds=40, timeout=6)
        (a1, pids), = self.wait_started(1, proc=hung)
        self.suspend_unlocked(hung.pid)                                        # the hung controller cannot enforce its own cap
        token = self.token(a1)
        capped = dt.datetime.fromisoformat(token['started_at']) + dt.timedelta(seconds=token['timeout'] + GRACE + .4)
        while dt.datetime.now(dt.timezone.utc) < capped: time.sleep(.1)
        self.assertTrue(alive(pids['worker']))
        done = self.adapter.recover(a1)                                        # no stop request: the passed cap is the trigger
        self.assertEqual(done['cleanup'], 'confirmed', done)
        self.assertEqual(json.loads(self.attempt(a1)['result'])['trigger'], 'execution_cap')
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'waiting')
        self.assertEqual([(h['classification'], h['trigger']) for h in self.held('C', 0)], [('executor_stopped', 'execution_cap')])
        self.assertEqual((self.payloads('node.resumed'), self.launches), ([], []))

    def test_f3_dead_controller_whose_job_outlives_it_is_terminated_settled_and_replayed_once(self):
        self.single()
        ctl = self.controller(mode='step', seconds=40, hold_job=True)
        (a1, pids), = self.wait_started(1, proc=ctl)
        work = Path(self.ledger.state_root) / 'worker-io' / a1
        (work / 'holdjob.txt').write_text(self.token(a1)['job_name'])
        self.addCleanup(self.end_own_job, self.token(a1)['job_name'])       # whatever happens, the test's own orphan tree ends
        until = time.monotonic() + 30
        while not (work / 'held.txt').exists() and time.monotonic() < until: time.sleep(.05)
        self.assertEqual((work / 'held.txt').read_text(), 'True')            # a member now holds a handle to its own Job
        ctl.kill(); ctl.wait(timeout=20)                                       # the owner dies; KILL_ON_JOB_CLOSE cannot fire
        time.sleep(1.0)
        self.assertTrue(alive(pids['worker']) and alive(pids['grandchild']), 'the orphan tree outlives its controller')
        result = self.engine.step(self.ledger, 'P1', self.adapter)            # the sweep terminates the orphan Job, then the policy replay
        self.assertEqual(result['state'], 'produced', result)
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild'], timeout=2))
        settled = json.loads(self.attempt(a1)['result'])
        self.assertEqual((settled['reason'], settled['tree_stopped'], settled['job']['active_after']), ('supervisor_interrupted', True, 0))
        self.assertTrue({pids['worker'], pids['grandchild']} <= set(settled['job']['members_before']), settled['job'])
        self.assertTrue(settled['job']['terminated_after_owner_death'])
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts WHERE status IN ('reserved','running','unknown')").fetchone()[0], 0)

    def test_f3b_job_not_found_is_no_proof_when_the_controller_ran_in_another_session(self):
        self.single()
        code, _, err = self.outcome(self.controller(mode='step', seconds=30, crash_on_start=True))
        self.assertEqual(code, 41, err)
        (a1, pids), = self.wait_started(1)
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild']))
        token = self.token(a1)
        other = [s for s in sessions() if s != token.get('session')]
        if not other: self.skipTest('no other live Windows session on this machine')
        with self.ledger.transaction(write=True) as conn:                      # fixture: the controller ran in ANOTHER, still live session
            conn.execute('UPDATE attempts SET identity=? WHERE id=?', (json.dumps(dict(token, session=other[0])), a1))
        waiting = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(waiting['state'], 'waiting', waiting)
        self.assertEqual(self.attempt(a1)['status'], 'running')                # "Local\ name not found here" proves nothing there
        with self.ledger.transaction(write=True) as conn:
            conn.execute('UPDATE attempts SET identity=? WHERE id=?', (json.dumps(token), a1))
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'produced')

    def test_f5_cleanup_confirmed_while_inputs_are_held_releases_the_attempt_and_resumes_when_clear(self):
        self.single()
        code, _, err = self.outcome(self.controller(mode='step', seconds=30, crash_on_start=True))
        self.assertEqual(code, 41, err)
        (a1, pids), = self.wait_started(1)
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild']))
        runtime_unknowns.open_unknown(self.ledger, 'P1', 'late-fact', question='Which input is required?', affected=['C', 'I'],
                                      required_by=['C'], resolver='doc', evidence=['a.txt:1'])
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'waiting')
        self.assertEqual(self.attempt(a1)['status'], 'settled')
        retained = [p for p in self.payloads('node.result_retained') if p.get('attempt') == a1]
        self.assertEqual([(r['cleanup'], r['generation']) for r in retained], [('confirmed', 0)], retained)
        self.assertEqual(managed_executor.unresolved(self.ledger, 'P1'), [])   # a revise that clears the blocker is not refused
        self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(len([p for p in self.payloads('node.result_retained') if p.get('attempt') == a1]), 1)   # idempotent
        runtime_unknowns.resolve(self.ledger, 'P1', 'late-fact', by='doc', evidence='a.txt:1', answer='Existing text format confirmed')
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'produced')   # lost owner, no trigger: one replay

    def test_f10_job_gone_while_its_controller_lives_settles_once_without_repeated_unknown_events(self):
        task = submit(self.ledger, 'F10 fixture', 'v23b-f10', plan_selector='plan-ns:P1', max_calls=2, max_seconds=60,
                      provider='codex', model='fixture-model')
        execution = self.control.configure(task['id'], task['revision'], {'mode': 'v23b-f10'})
        attempt = self.control.reserve(task['id'], execution['revision'], 'f10', {'unit': 'task:Z', 'stage': 'Z'})
        work = Path(self.temp.name) / 'f10'; work.mkdir()
        # this process is the controller: its own unconfirmed-stop path records unknown and closes the Job, and the process lives on
        with patch.object(process_core.Job, 'stop', side_effect=LedgerError('injected: tree stop unconfirmed')):
            with self.assertRaises(LedgerError):
                Supervisor(self.control).run(attempt, [native_python(), '-c', 'print(1)'], cwd=work, timeout=30, env=environment())
        self.assertEqual(self.control.attempt(attempt['id'])['status'], 'unknown')
        self.control.cancel(task['id'])
        time.sleep(GRACE + .4)
        unknowns = lambda: [e['kind'] for e in self.ledger.events(task['id'])].count('attempt.unknown')
        before = unknowns()
        supervisor = Supervisor(self.control)
        supervisor.terminate(attempt['id']); supervisor.terminate(attempt['id'])
        row = self.control.attempt(attempt['id'])
        self.assertEqual(row['status'], 'settled', row)
        body = json.loads(row['result'])
        self.assertEqual((body['tree_stopped'], body['job']['exists'], body['trigger']), (True, False, 'stop_requested'))
        self.assertEqual(unknowns(), before, 'no repeated attempt.unknown per escalation')


class ReviewRound2Tests(TakeoverFixture):
    """review-b-r2.md (on c690f3a = d55e4a7): N1 session ended / reboot, N2 token without session, N3 alive worker, N4 result_unknown."""

    def crashed(self, **cfg):
        code, _, err = self.outcome(self.controller(mode='step', seconds=30, crash_on_start=True, **cfg))
        self.assertEqual(code, 41, err)
        (a1, pids), = self.wait_started(1)
        self.assertTrue(self.wait_dead(pids['worker'], pids['grandchild']))
        return a1

    def rewrite(self, attempt_id, change):
        token = self.token(attempt_id)
        change(token)
        with self.ledger.transaction(write=True) as conn:                      # fixture only: what another build/session recorded
            conn.execute('UPDATE attempts SET identity=? WHERE id=?', (json.dumps(token), attempt_id))
        return token

    def other_live_session(self, token):
        other = [s for s in sessions() if s != token.get('session')]
        if not other: self.skipTest('no other live Windows session on this machine')
        return other[0]

    def test_n1_job_gone_in_a_session_that_no_longer_exists_is_proof_and_the_lost_owner_is_replayed_once(self):
        self.single()
        a1 = self.crashed()
        gone = max(sessions()) + 7
        self.rewrite(a1, lambda t: t.update(session=gone))
        result = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(result['state'], 'produced', result)                  # settled, then Q1: lost owner without trigger -> one replay
        body = json.loads(self.attempt(a1)['result'])
        self.assertEqual((self.attempt(a1)['status'], body['reason'], body['job']['proof']), ('settled', 'supervisor_interrupted', 'session_ended'))

    def test_r3_1_a_forward_clock_step_never_claims_a_reboot(self):
        """A wall-clock estimate of the boot (now - uptime) moves with every clock step: after a forward step it lies after the
        controller's start although nothing rebooted. Simulated by moving that estimate (the 2.3-B rule up to f38d118 read it) a year
        past the controller's creation; the recorded session is another LIVE session, so only a reboot rule could settle it."""
        self.single()
        a1 = self.crashed()
        token = self.token(a1)
        self.rewrite(a1, lambda t: t.update(session=self.other_live_session(token)))
        stepped = token['supervisor']['created'] + 365 * 24 * 3600 * 10 ** 7
        with patch.object(process_core, 'boot_filetime', lambda: stepped, create=True):
            self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'waiting')
        self.assertEqual(self.attempt(a1)['status'], 'running')                # no reboot proof from the clock: pending

    def test_r3_1_an_uptime_lower_than_at_launch_is_the_reboot_proof_and_a_token_without_it_has_none(self):
        self.single()
        a1 = self.crashed()
        token = self.token(a1)
        self.assertIsInstance(token.get('uptime_ms'), int)                     # recorded at launch
        live = self.other_live_session(token)
        rebooted = patch.object(process_core, 'uptime_ms', lambda: 1000, create=True)   # a new boot: the uptime went backwards
        self.rewrite(a1, lambda t: (t.update(session=live), t.pop('uptime_ms', None)))  # a token without the launch uptime ...
        with rebooted:
            self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'waiting')   # ... gets no reboot proof
        self.assertEqual(self.attempt(a1)['status'], 'running')
        self.rewrite(a1, lambda t: t.update(uptime_ms=token['uptime_ms']))
        with rebooted:
            self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'produced')
        self.assertEqual(json.loads(self.attempt(a1)['result'])['job']['proof'], 'rebooted_since_controller_start')

    def test_r3_2_an_unreadable_session_list_is_never_reported_as_a_live_session(self):
        self.single()
        a1 = self.crashed()
        self.rewrite(a1, lambda t: t.update(session=max(sessions()) + 7))
        with patch.object(process_core, 'live_sessions', lambda: None):
            result = Supervisor(self.control).reconcile(a1)
        self.assertEqual(result['status'], 'unknown', result)
        self.assertIn('cannot be shown', result['reason'])
        self.assertNotIn('still exists', result['reason'])
        self.assertEqual(Supervisor(self.control).reconcile(a1)['status'], 'settled')   # readable again: the session has ended

    def test_n2_a_token_without_session_or_launch_uptime_never_gets_a_proof_from_a_clock_or_uptime(self):
        self.single()
        a1 = self.crashed()
        token = self.rewrite(a1, lambda t: (t.pop('session', None), t.pop('uptime_ms', None), t.update(job_name='Local\\OneCrew-' + a1)))
        stepped = token['supervisor']['created'] + 365 * 24 * 3600 * 10 ** 7   # the 72b1b22 token format; any clock, any uptime
        with patch.object(process_core, 'boot_filetime', lambda: stepped, create=True), \
                patch.object(process_core, 'uptime_ms', lambda: 1000, create=True):
            self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'waiting')
            self.assertEqual(Supervisor(self.control).reconcile(a1)['status'], 'unknown')
        self.assertEqual(self.attempt(a1)['status'], 'running')                # documented limit: such a token stays pending

    def test_n3_a_recorded_worker_that_is_alive_is_never_proof_of_a_stopped_tree(self):
        self.single()
        outsider, who = self.outsider()
        ctl = self.controller(mode='step', seconds=40)
        (a1, pids), = self.wait_started(1, proc=ctl)
        token = self.token(a1)
        held = process_core.Job.open(token['job_name'])                         # this test keeps the Job alive past its controller
        self.addCleanup(lambda: held.close() if held.handle else None)
        ctl.kill(); ctl.wait(timeout=20)
        held.stop()                                                            # ends the test's own tree; the Job now exists with 0 members
        self.assertEqual(held.counts().active, 0)
        self.rewrite(a1, lambda t: t.update(worker=who))                         # fixture: the recorded worker is a process that lives
        supervisor = Supervisor(self.control)
        self.assertNotEqual(supervisor.reconcile(a1)['status'], 'settled')       # 0 active members, but the worker lives: no proof
        self.assertEqual(self.attempt(a1)['status'], 'running')
        held.close()                                                           # the Job is gone now: still no proof while the worker lives
        self.assertNotEqual(supervisor.reconcile(a1)['status'], 'settled')
        self.assertEqual(self.attempt(a1)['status'], 'running')
        self.rewrite(a1, lambda t: t.update(worker=token['worker']))
        self.assertEqual(supervisor.reconcile(a1)['status'], 'settled')
        self.assertIsNone(outsider.poll())

    def test_n4_a_successful_process_without_candidate_is_not_released_while_inputs_are_held_and_is_adopted_later(self):
        self.single()
        code, _, err = self.outcome(self.controller(mode='step', seconds=0.2, crash_before_candidate=True))
        self.assertEqual(code, 42, err)
        a1 = self.engine.state(self.ledger, 'P1')['nodes']['C']['attempt']
        body = json.loads(self.attempt(a1)['result'])
        self.assertEqual((self.attempt(a1)['status'], body['exit_code'], body['reason']), ('settled', 0, None))
        runtime_unknowns.open_unknown(self.ledger, 'P1', 'late-fact', question='Which input is required?', affected=['C', 'I'],
                                      required_by=['C'], resolver='doc', evidence=['a.txt:1'])
        recovery_only = managed_executor.ManagedExecutor(self.ledger, initialize=False)       # a caller that cannot rebuild
        self.assertEqual(self.engine.step(self.ledger, 'P1', recovery_only)['state'], 'waiting')
        self.assertEqual([p for p in self.payloads('node.result_retained') if p.get('attempt') == a1], [])   # not released
        runtime_unknowns.resolve(self.ledger, 'P1', 'late-fact', by='doc', evidence='a.txt:1', answer='Existing text format confirmed')
        result = self.engine.run_batch(self.ledger, 'P1', self.adapter, slots=1)   # W37b (c): rebuilt from durable outputs, adopted
        self.assertEqual(result['state'], 'adopted', result)
        self.assertEqual([(r['state'], r['adopted_after_crash']) for r in result['results']], [('produced', True)])
        self.assertEqual((self.launches, len(self.operations())), ([], 1))       # no second launch


class CrossedScopeTests(TakeoverFixture):
    def test_t9_a_holds_x_needs_y_b_holds_y_needs_x_both_extensions_refused_and_neither_live_attempt_released(self):
        """Design §7 case 3 (survey T9, in-process): two live attempts on disjoint scopes; an extension that would give each the other's
        file is refused while they run (a revise and a new reservation), the cleanup sweep leaves both live attempts alone, and both
        finish under their original scopes. No hold-and-wait exists: a running attempt can never grow its sealed scope."""
        import threading
        nodes = [node('A'), node('B', write=('b.txt',)), node('I', ['A', 'B'], integration=True, write=())]
        for item in nodes:
            item['executor'] = dict(PIN); item['budget_calls'] = 3                # review R3-3: spare calls, so only the fences can refuse
        self.revise(nodes)
        release, started = threading.Event(), []
        def body(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            started.append(item['id'])
            release.wait(20)
            result = {'artifact': self.store.blob(('crossed-' + item['id']).encode()), 'receipt': self.store.blob(b'crossed fixture')}
            control.finish(attempt['id'], attempt['generation'], result)
            return result
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.update(batch=self.engine.run_batch(self.ledger, 'P1', self.isolated(body), slots=2)))
        worker.start(); self.addCleanup(lambda: (release.set(), worker.join(20)))
        until = time.monotonic() + 20
        while len(started) < 2 and time.monotonic() < until: time.sleep(.02)
        self.assertEqual(sorted(started), ['A', 'B'])
        live = {n: self.engine.state(self.ledger, 'P1')['nodes'][n]['attempt'] for n in ('A', 'B')}
        crossed = self.ip.current(self.ledger, 'P1')['definition']['nodes']
        for item in crossed:
            if item['id'] == 'A': item['write'] = ['a.txt', 'b.txt']
            if item['id'] == 'B': item['write'] = ['a.txt', 'b.txt']
        revision = self.ip.current(self.ledger, 'P1')['internal_revision']
        with self.assertRaisesRegex(LedgerError, 'Reconcile the affected active workflow attempt before revising'):
            self.revise(crossed)                                               # neither may extend into the other's file while both live
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], revision)
        child = self.attempt(live['A'])['task_id']
        status = self.control.status(child)
        self.assertLess(status['used_calls'] + status['reserved_calls'], status['budget']['limits']['max_calls'])   # calls to spare
        with self.assertRaisesRegex(LedgerError, 'Previous attempt must stop and reconcile first'):   # the live-attempt fence itself
            self.control.reserve(child, self.control.status(child)['revision'], 'extend-a', {'unit': 'task:A', 'stage': 'A'})
        sweep = getattr(self.engine, 'reconcile_orphans', None)                 # 2.3-B; absent in 2.2, where nothing sweeps at all
        if sweep is not None:
            swept = sweep(self.ledger, 'P1', self.isolated(body), control=self.control)
            self.assertTrue(all(row.get('cleanup') == 'pending' and not row.get('state') for row in swept), swept)   # nothing released
        self.assertEqual({n: self.attempt(a)['status'] for n, a in live.items()}, {'A': 'running', 'B': 'running'})
        release.set(); worker.join(20)
        self.assertEqual(sorted((r['node'], r['state']) for r in outcome['batch']['results']), [('A', 'produced'), ('B', 'produced')])
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual({n: (view['nodes'][n]['attempt'], view['nodes'][n]['generation']) for n in ('A', 'B')},
                         {n: (a, 0) for n, a in live.items()})
        self.assertEqual(self.engine.state(self.ledger, 'P1')['definition']['nodes'][0]['write'], ['a.txt'])


class GraceBoundTests(unittest.TestCase):
    def test_f4_grace_is_never_shorter_than_the_controllers_own_bounded_stop(self):
        # a healthy controller stopping by itself may take Job.stop (10 s) + child.wait (10 s) + a busy ledger (10 s)
        for cap in (1, 30, 60, 120, 299, 300, 600, 3600, None):
            self.assertGreaterEqual(process_core.grace_seconds(cap), 30 + 5, cap)
        self.assertEqual(process_core.grace_seconds(3600), 60)
