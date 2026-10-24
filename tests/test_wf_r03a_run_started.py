"""T41a, T41b (W44, R03) - `verdict.run_started`, the Stop hook, and the four ends of a verdict run.

T41a  The Stop hook neither blocks nor reminds while a milestone is being checked in the background (a run_started with no end yet).
T41b  Four ends - completed, failed, timed out (verdict.receipt_issued + verdict.recorded, which already exist) and a killed process
      (verdict.run_abandoned) - are each a final state in the ledger; a lost run never hangs "checking"; the two new kinds are class A
      and the real old version (archive of ee46539, tests/wf_oldversion.py) keeps S, G, C and its repair count.

The background run is the real `onecrew verdict run` as a subprocess; the hook is the real `onecrew hook stop` with the documented stdin JSON
(interface only: not a real Claude Code session). The verifier command is a fake: it waits for a gate file, exits 3, or sleeps.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_l2 import HookFixture, owned_plan, REPO             # noqa: E402
from test_v2_l1 import milestone                                  # noqa: E402

from onecrew.ledger import LedgerError                            # noqa: E402
from onecrew.v2 import compat, plan as plans, verdict             # noqa: E402
from onecrew.v2.verifiers import command                          # noqa: E402
import tests.wf_oldversion as ov                                  # noqa: E402

PY = sys.executable
# a one-line -c script (a newline in argv would make the receipt "suspicious: control_char_argv"): waits for the gate file given as argv[1]
GATE = r"""exec("import os,sys,time\nwhile not os.path.exists(sys.argv[1]): time.sleep(0.05)\nprint('gate opened')")"""
SLEEP = [PY, '-c', 'import time; print("sleeping"); time.sleep(120)']
OK = [PY, '-c', 'print("ok")']
FAIL = [PY, '-c', 'print("nope"); raise SystemExit(3)']
NEW_KINDS = ('verdict.run_started', 'verdict.run_abandoned')
BASELINE = 'ee46539'


def _stop_event(session):
    return {'session_id': session, 'cwd': None, 'hook_event_name': 'Stop', 'stop_hook_active': False}


class RunFixture(HookFixture):
    """An enforced plan whose M1 is a command milestone; `background()` starts the real `verdict run` as a subprocess."""

    def setUp(self):
        super().setUp()
        self.procs = []
        self.addCleanup(self._cleanup)
        self.gate = Path(self.temp.name) / 'gate'

    def _cleanup(self):
        for proc in self.procs:                                  # the tree dies first: a gate opened now would let it start git in the project folder
            self.kill_tree(proc)
            try:
                proc.wait(timeout=20)
            except Exception:                                    # noqa: BLE001
                pass
            for stream in (proc.stdout, proc.stderr):
                if stream: stream.close()

    def plan_with(self, argv, **extra):
        self.enforce(value=owned_plan(milestones=[milestone('M1', argv=argv, **extra)]))
        return plans.show(self.ledger, 'P1')['anchor_task']

    def background(self, milestone_id='M1'):
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}
        proc = subprocess.Popen([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state),
                                 'verdict', 'run', '--plan', 'P1', '--milestone', milestone_id],
                                cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(env, PYTHONUTF8='1'),
                                **({} if os.name == 'nt' else {'start_new_session': True}))
        self.procs.append(proc)
        return proc

    def kill_tree(self, proc):
        if proc.poll() is not None: return
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()

    def wait_for(self, kind, timeout=60.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if kind in self.kinds(): return True
            time.sleep(0.2)
        return False

    def payloads(self, kind):
        return [p for k, p in self.events() if k == kind]

    def stop(self, session):
        event = _stop_event(session); event['cwd'] = str(self.root)
        return self.run_hook('stop', event)

    def hook_events(self):
        return [v['event'] for v in self.violations()]


class StopWhileRunningTests(RunFixture):
    """T41a."""

    # [E1] the ledger has verdict.run_started for the milestone, with plan, revision, milestone, time and the process id
    # [E2][E6] the Stop hook lets the session go: no block, no reminder
    def test_e1_e2_e6_stop_hook_does_not_block_or_remind_while_the_milestone_runs(self):
        self.plan_with([PY, '-c', GATE, str(self.gate)])
        proc = self.background()
        self.assertTrue(self.wait_for('verdict.run_started'), 'verdict run did not write verdict.run_started')       # [E1]
        started = self.payloads('verdict.run_started')
        self.assertEqual(len(started), 1)
        for field in ('plan', 'revision', 'milestone', 'pid', 'started'):
            self.assertIn(field, started[0])
        self.assertEqual((started[0]['plan'], started[0]['revision'], started[0]['milestone']), ('P1', 1, 'M1'))
        self.assertTrue(verdict.process_alive(started[0]['pid']))
        self.assertIsNone(proc.poll(), 'the run must still be going')
        for session in ('s-a', 's-b', 's-c'):                                                                             # more calls than the block cap
            code, out, err = self.stop(session)
            self.assertEqual((code, out.strip()), (0, ''), f'Stop hook said something while M1 runs: {out!r} {err!r}')     # [E2]
        events = self.hook_events()
        self.assertEqual([e for e in events if e in ('stop_blocked', 'reminded')], [])                                        # [E6]
        self.gate.write_text('go')
        out, err = proc.communicate(timeout=120)
        self.assertEqual(proc.returncode, 0, err.decode('utf-8', 'replace'))
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'passed')

    # [E5] after the run ended with a verdict, the hook handles the milestone by that state (a failed milestone is blocked again)
    def test_e5_after_a_failed_run_the_hook_blocks_again(self):
        self.plan_with(FAIL)
        proc = self.background()
        proc.communicate(timeout=120)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'failed')
        code, out, _ = self.stop('s-after-fail')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['decision'], 'block')
        self.assertIn('M1', json.loads(out)['reason'])

    # the hook also lets go while running in log mode, and does not leave a stop_blocked record in the ledger sync
    def test_a_running_milestone_leaves_no_blocked_or_reminded_event_in_the_ledger(self):
        self.plan_with([PY, '-c', GATE, str(self.gate)])
        self.background()
        self.assertTrue(self.wait_for('verdict.run_started'))
        self.stop('s-sync')
        self.run_hook('sync')
        kinds = self.kinds()
        self.assertNotIn('hook.stop_blocked', kinds)
        self.assertNotIn('hook.reminded', kinds)


class FourEndsTests(RunFixture):
    """T41b: every end is a final state; no run hangs `checking`."""

    def sequence(self):
        keep = ('verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded', 'verdict.run_abandoned', 'milestone.passed', 'milestone.failed')
        return [k for k in self.kinds() if k in keep]

    def checking(self):
        return verdict.status(self.ledger, 'P1')['checking']

    # [E3] completed
    def test_e3_completed_run(self):
        self.plan_with(OK)
        out = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(out['milestones'][0]['state'], 'passed')
        self.assertEqual(self.sequence(), ['verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded', 'milestone.passed'])
        status = verdict.status(self.ledger, 'P1')
        self.assertEqual([r['outcome'] for r in status['runs']], ['completed'])
        self.assertEqual(status['checking'], [])                                                                              # [E7]
        code, out, _ = self.stop('s-done')
        self.assertEqual((code, out.strip()), (0, ''))                                                                        # [E5] nothing pending
        self.assertNotIn('verdict.run_abandoned', self.kinds())

    # [E3] failed
    def test_e3_failed_run(self):
        self.plan_with(FAIL)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.sequence(), ['verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded', 'milestone.failed'])
        self.assertEqual(self.payloads('verdict.recorded')[0]['result'], 'fail')
        status = verdict.status(self.ledger, 'P1')
        self.assertEqual([r['outcome'] for r in status['runs']], ['failed'])
        self.assertEqual(status['checking'], [])
        self.assertEqual(json.loads(self.stop('s-fail')[1])['decision'], 'block')                                             # [E5]

    # [E3] timed out: the existing receipt (timed_out) and an inconclusive verdict; the clock is fast-forwarded, the command really times out
    def test_e3_timed_out_run(self):
        self.plan_with(SLEEP, max_repairs=3)
        real = command.subprocess

        class Fast(real.Popen):
            def communicate(self, input=None, timeout=None):          # the milestone's minute cap, shortened to a second
                return super().communicate(input, 1.0 if timeout and timeout >= 60 else timeout)
        shim = types.SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if not k.startswith('__')})
        shim.Popen = Fast
        with patch.object(command, 'subprocess', shim):
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.sequence(), ['verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded', 'milestone.failed'])
        recorded = self.payloads('verdict.recorded')[0]
        self.assertEqual(recorded['result'], 'inconclusive')
        receipt = json.loads(command.Snapshots(self.ledger.state_root).read_blob(recorded['receipt']).decode('utf-8'))
        self.assertTrue(receipt['timed_out'])
        status = verdict.status(self.ledger, 'P1')
        self.assertEqual([r['outcome'] for r in status['runs']], ['timed_out'])
        self.assertEqual(status['checking'], [])

    # [E3][E4][E7] a killed process: the next state read closes the run with verdict.run_abandoned; "checking" does not last
    def test_e3_e4_e7_killed_run_is_abandoned_and_never_hangs_checking(self):
        self.plan_with(SLEEP)
        proc = self.background()
        self.assertTrue(self.wait_for('verdict.run_started'))
        started = self.payloads('verdict.run_started')[0]
        self.assertEqual(verdict.status(self.ledger, 'P1')['checking'], ['M1'])                                               # alive: it is checking
        self.assertEqual(self.payloads('verdict.run_abandoned'), [])                                                          # a healthy run is not reaped
        self.kill_tree(proc)
        proc.wait(timeout=30)
        deadline = dt.datetime.fromisoformat(started['deadline'])
        before_deadline = dt.datetime.fromisoformat(started['started']) + dt.timedelta(seconds=30)                            # the fake clock: well inside the run's own deadline
        self.assertLess(before_deadline, deadline)
        status = verdict.status(self.ledger, 'P1', now=before_deadline)
        self.assertEqual(status['checking'], [])                                                                              # [E7]
        abandoned = self.payloads('verdict.run_abandoned')
        self.assertEqual(len(abandoned), 1)                                                                                   # [E4]
        self.assertEqual((abandoned[0]['run_id'], abandoned[0]['pid'], abandoned[0]['milestone'], abandoned[0]['reason']),
                         (started['run_id'], started['pid'], 'M1', 'process_gone'))
        self.assertEqual(self.sequence(), ['verdict.run_started', 'verdict.run_abandoned'])
        self.assertEqual([r['outcome'] for r in status['runs']], ['abandoned'])
        verdict.status(self.ledger, 'P1')
        self.assertEqual(len(self.payloads('verdict.run_abandoned')), 1)                                                      # closing is once

    # [E5] the hook after a killed run: not "running" any more, it blocks as for an unfinished milestone (and itself closes a lost run)
    def test_e4_e5_the_stop_hook_closes_a_lost_run_and_treats_the_milestone_by_its_final_state(self):
        self.plan_with(SLEEP)
        proc = self.background()
        self.assertTrue(self.wait_for('verdict.run_started'))
        self.assertEqual(self.stop('s-live')[1].strip(), '')                                                                  # running: let go
        self.kill_tree(proc)
        proc.wait(timeout=30)
        code, out, _ = self.stop('s-lost')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['decision'], 'block')
        self.assertEqual(len(self.payloads('verdict.run_abandoned')), 1)
        self.assertEqual(self.checking(), [])

    # [E7] a run whose process is alive but past its own deadline does not hang either; one inside it is left alone
    def test_e7_overdue_run_with_a_living_pid_is_abandoned_and_a_healthy_one_is_not(self):
        self.plan_with(OK)
        self.fabricate_run('r-live', pid=os.getpid(), minutes=1)
        started = dt.datetime.fromisoformat(self.payloads('verdict.run_started')[0]['started'])
        self.assertEqual(verdict.status(self.ledger, 'P1', now=started + dt.timedelta(seconds=20))['checking'], ['M1'])
        self.assertEqual(verdict.status(self.ledger, 'P1', now=started + dt.timedelta(minutes=1, seconds=30))['checking'], ['M1'])     # inside the grace
        late = verdict.status(self.ledger, 'P1', now=started + dt.timedelta(hours=2))
        self.assertEqual(late['checking'], [])
        abandoned = self.payloads('verdict.run_abandoned')
        self.assertEqual([(a['run_id'], a['reason']) for a in abandoned], [('r-live', 'overdue')])

    # a run from another machine cannot be probed by pid: only its deadline closes it
    def test_a_run_of_another_host_is_closed_by_its_deadline_only(self):
        self.plan_with(OK)
        self.fabricate_run('r-far', pid=1, minutes=1, host='another-machine')
        started = dt.datetime.fromisoformat(self.payloads('verdict.run_started')[0]['started'])
        self.assertEqual(verdict.status(self.ledger, 'P1', now=started + dt.timedelta(seconds=20), alive=lambda pid: False)['checking'], ['M1'])
        self.assertEqual(verdict.status(self.ledger, 'P1', now=started + dt.timedelta(hours=1), alive=lambda pid: False)['checking'], [])

    # a run that raises between its start and its receipt is closed by the run itself
    def test_a_run_that_raises_closes_itself(self):
        self.plan_with(OK)
        with patch.object(command, 'run', side_effect=LedgerError('git exploded')):
            with self.assertRaises(LedgerError):
                verdict.run(self.ledger, 'P1', 'M1', self.root)
        abandoned = self.payloads('verdict.run_abandoned')
        self.assertEqual([a['reason'] for a in abandoned], ['error'])
        self.assertIn('git exploded', abandoned[0]['detail'])
        self.assertEqual(verdict.status(self.ledger, 'P1')['checking'], [])
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['state'], 'passed')             # and the milestone can run again

    # one live run per milestone: a second one is refused while the first lives, a dead one is closed first and does not refuse
    def test_only_one_live_run_per_milestone(self):
        self.plan_with(OK)
        self.fabricate_run('r-one', pid=os.getpid(), minutes=10)
        with self.assertRaises(LedgerError) as caught:
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIn('already being checked', str(caught.exception))
        self.assertEqual(self.payloads('verdict.receipt_issued'), [])

    def test_a_dead_run_does_not_refuse_the_next_one(self):
        self.plan_with(OK)
        self.fabricate_run('r-dead', pid=2 ** 22 + 12345, minutes=10)
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['state'], 'passed')
        self.assertEqual([a['run_id'] for a in self.payloads('verdict.run_abandoned')], ['r-dead'])

    # [E8] no progress tracking, no notification: only the declared kinds are written around a run
    def test_e8_no_progress_events_or_notices(self):
        self.plan_with(OK)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        allowed = {'task.submitted', 'plan.proposed', 'plan.approved', 'plan.step0_closed', 'precondition.recorded', 'verdict.run_started',
                   'verdict.receipt_issued', 'verdict.recorded', 'milestone.passed'}
        extra = set(self.kinds()) - allowed
        self.assertEqual(extra, set(), f'unexpected events around a run: {extra}')
        self.assertFalse([k for k in self.kinds() if 'progress' in k or k.startswith('notice')])

    # the status is also a command of the installed CLI
    def test_verdict_status_command(self):
        self.plan_with(OK)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        done = subprocess.run([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state), 'verdict', 'status', '--plan', 'P1'],
                              cwd=REPO, capture_output=True, timeout=120, env=dict({k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}, PYTHONUTF8='1'))
        self.assertEqual(done.returncode, 0, done.stderr.decode('utf-8', 'replace'))
        body = json.loads(done.stdout.decode('utf-8'))
        self.assertEqual(body['checking'], [])
        self.assertEqual([r['outcome'] for r in body['runs']], ['completed'])

    # [E9] class A, and an abandoned run is not a failed verdict
    def test_e9_the_new_kinds_are_class_A_and_an_abandoned_run_costs_no_repair(self):
        for kind in NEW_KINDS: self.assertEqual(compat.event_class(kind), 'A')
        self.plan_with(FAIL, max_repairs=3)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        left = plans.show(self.ledger, 'P1')['milestones'][0]['repairs_left']
        self.assertEqual(left, 2)
        self.fabricate_run('r-gone', pid=2 ** 22 + 777, minutes=10)
        verdict.status(self.ledger, 'P1')
        view = plans.show(self.ledger, 'P1')['milestones'][0]
        self.assertEqual(view['repairs_left'], left)
        self.assertEqual((view['state'], view['failures']), ('failed', 1))
        self.assertEqual(plans.show(self.ledger, 'P1')['stop']['repairs_used'], 1)

    def fabricate_run(self, run_id, pid, minutes, host=None):
        """A run_started as verdict.run writes it, for a process that never existed (the fixture of the reaper, not of the writer)."""
        started = dt.datetime.now(dt.timezone.utc)
        with self.ledger.transaction(write=True) as conn:
            state = plans.derive(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, state['task_id'], 'verdict.run_started', {
                'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'run_id': run_id, 'kind': 'command', 'pid': pid,
                'host': host or verdict.this_host(), 'started': started.isoformat(), 'max_minutes': minutes,
                'deadline': (started + dt.timedelta(minutes=minutes, seconds=verdict.RUN_GRACE_SECONDS)).isoformat()})


def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git is required to archive the old version')
class OldVersionTests(RunFixture):
    """[E9][E10] against the REAL old version (archive of ee46539). The two kinds are produced by the real writer, then copied to a root the
    old binary reads; nothing about the old version is mocked."""

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, str(REPO), cls.runs))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def real_new_events(self):
        """(run_started, run_abandoned) payloads written by the real code: a run that raises after its start."""
        self.plan_with(OK)
        with patch.object(command, 'run', side_effect=LedgerError('fixture: the run died')):
            with self.assertRaises(LedgerError):
                verdict.run(self.ledger, 'P1', 'M1', self.root)
        return self.payloads('verdict.run_started')[0], self.payloads('verdict.run_abandoned')[0]

    def old_root(self, tag, failed=False):
        proj = ov.git_project(self.runs, 'proj-' + tag)
        cfile = self.runs / (tag + '.json')
        value = ov.contract('Old ' + tag)
        value['milestones'][0]['max_repairs'] = 3
        cfile.write_text(json.dumps(value), encoding='utf-8')
        state = self.runs / ('state-' + tag)
        code, out = self.old.run(proj, state, 'plan', 'propose', 'P1', '--file', str(cfile), '--author', 'claude-probe')
        self.assertEqual(code, 0, out)
        pid = ov.project_id(state, proj)
        task = ov.anchor_id(state, pid, 'plan:P1')
        ov.make_approved(state, task, 'P1')
        if failed:                                               # one failed verdict on M1 (what verdict.record writes), so a repair count exists
            ov.insert_event(state, task, 'verdict.receipt_issued', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'receipt': 'f' * 64})
            ov.insert_event(state, task, 'verdict.recorded', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'result': 'fail', 'by': 'command',
                                                              'receipt': 'f' * 64, 'artifact_sha': 'a' * 40, 'run': 1})
            ov.insert_event(state, task, 'milestone.failed', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'result': 'fail', 'failures': 1, 'repairs_left': 2})
        return proj, state, task

    def show(self, proj, state):
        code, out = self.old.run(proj, state, 'plan', 'show', 'P1')
        self.assertEqual(code, 0, out)
        body = json.loads(out)
        return {'status': body['status'], 'milestones': [(m['id'], m['state'], m['failures'], m['repairs_left']) for m in body['milestones']],
                'repairs_used': body['stop']['repairs_used']}

    def test_e9_e10_old_version_ignores_the_new_kinds_and_keeps_status_gate_continue_and_repairs(self):
        started, abandoned = self.real_new_events()
        for kind, payload in (('verdict.run_started', started), ('verdict.run_abandoned', abandoned)):
            self.assertEqual(compat.event_class(kind), 'A')
            self.assertIsNone(compat.check_write(kind, payload, 'plan:P1'))                  # the guard of every create path lets it onto a plan: anchor
        proj, state, task = self.old_root('plain', failed=True)
        base = ov.read(self.old, proj, state, 'P1')
        before = self.show(proj, state)
        self.assertEqual(before['milestones'], [('M1', 'failed', 1, 2)])
        shutil.copytree(state, self.runs / 'state-with')
        with_state = self.runs / 'state-with'
        for kind, payload in (('verdict.run_started', started), ('verdict.run_abandoned', abandoned)):
            ov.insert_event(with_state, task, kind, payload)
            after = ov.read(self.old, proj, with_state, 'P1')
            diff = ov.compare(base, after)
            self.assertTrue(diff['S'], f'S changed by {kind}: {base["S"]} vs {after["S"]}')
            self.assertTrue(diff['G'], f'G changed by {kind}')
            self.assertTrue(diff['C'], f'C changed by {kind}')
            self.assertFalse(after['read_blocked'])
            self.assertEqual(self.show(proj, with_state), before, f'the old version counted {kind} as a repair or changed the state')   # [E10]
        self.assertEqual(ov.kinds_on(with_state, task)[-2:], ['verdict.run_started', 'verdict.run_abandoned'])

    def test_e10_a_counter_example_that_counts_an_abandoned_run_as_a_failure_is_different(self):
        """The wrong rule (an abandoned run costs a repair) would have changed the count the old version shows; the comparison above detects it."""
        started, abandoned = self.real_new_events()
        proj, state, task = self.old_root('wrong', failed=True)
        before = self.show(proj, state)
        ov.insert_event(state, task, 'verdict.recorded', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'result': 'inconclusive', 'by': 'command',
                                                          'receipt': 'e' * 64, 'artifact_sha': 'a' * 40, 'run': 2})        # what "abandoned = a failure" would write
        self.assertNotEqual(self.show(proj, state), before)


if __name__ == '__main__':
    unittest.main()
