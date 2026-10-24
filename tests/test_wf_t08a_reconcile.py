"""T08a (W37a, R05): a verifier run of unknown outcome is reconciled BEFORE any retry in the sequential repair loop; undeterminable -> held and
reported, not run again. X = the milestone command, which appends one line to a marker file outside the ledger (its effect) and is counted by it.

Crash points (fixture of tests/test_wf_r03a_run_started: the real `onecrew verdict run` as a subprocess, killed by the harness):
  (b) killed after dispatch while X runs      -> reconcile: unknown -> `verdict.run_held`, 0 new dispatch, marker still 1 line; a recorded
                                                 release (`verdict release-run --reason`) is the only way to a second run;
  (c) X finished, crash before the receipt    -> reconcile: completed from the receipt marker, the receipt of the OLD run is issued and recorded,
                                                 X is not run again (marker still 1 line);
  (a) a run that never dispatched             -> not_dispatched: a new run starts.
Counter-rule [E4]: a reconcile that re-dispatches X at (b) would make the marker 2 lines; [E6]: nothing says exactly-once.
"""
import json
import sys
import time
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.v2 import verdict
from onecrew.v2.verifiers import command
from test_wf_r03a_run_started import RunFixture, PY, _have_git   # noqa: E402

RUN_KINDS = ('verdict.run_started', 'verdict.run_abandoned', 'verdict.run_reconciled', 'verdict.run_held', 'verdict.run_released',
             'verdict.receipt_issued', 'verdict.recorded')


class ReconcileTests(RunFixture):
    def setUp(self):
        if not _have_git(): self.skipTest('git is required')
        super().setUp()
        self.marker = Path(self.temp.name) / 'x-effects.txt'

    def x(self, then_sleep):
        # one -c line: append a line to the marker (the effect of X), then optionally sleep (the harness kills during the sleep)
        body = f'import sys,time; open(sys.argv[1],"a").write("x\\n"); print("x ran")' + ('; time.sleep(120)' if then_sleep else '')
        return [PY, '-c', body, str(self.marker)]

    def fabricate_run(self, run_id, pid, minutes):
        import datetime as dt
        from onecrew.v2 import plan as plans
        started = dt.datetime.now(dt.timezone.utc)
        with self.ledger.transaction(write=True) as conn:
            state = plans.derive(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, state['task_id'], 'verdict.run_started', {
                'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'run_id': run_id, 'kind': 'command', 'pid': pid, 'host': verdict.this_host(),
                'started': started.isoformat(), 'max_minutes': minutes,
                'deadline': (started + dt.timedelta(minutes=minutes, seconds=verdict.RUN_GRACE_SECONDS)).isoformat()})

    def lines(self):
        return self.marker.read_text().count('x') if self.marker.exists() else 0

    def seq(self):
        return [k for k in self.kinds() if k in RUN_KINDS]

    def wait_marker(self, run_id, marker, timeout=60.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if (Path(self.state) / verdict.RUNS_DIR / run_id / (marker + '.json')).exists(): return True
            time.sleep(0.1)
        return False

    def test_b_killed_during_x_is_held_not_rerun_until_a_recorded_release(self):
        self.plan_with(self.x(then_sleep=True))
        proc = self.background()
        self.assertTrue(self.wait_for('verdict.run_started'))
        started = self.payloads('verdict.run_started')[0]
        self.assertTrue(self.wait_marker(started['run_id'], 'dispatched'))
        end = time.monotonic() + 60
        while self.lines() < 1 and time.monotonic() < end: time.sleep(0.1)
        self.assertEqual(self.lines(), 1)
        self.kill_tree(proc); proc.wait(timeout=30)                                               # crash point (b)
        with self.assertRaises(LedgerError) as caught:
            verdict.run(self.ledger, 'P1', 'M1', self.root)                                       # the restart of the loop
        self.assertIn('unknown outcome', str(caught.exception)); self.assertIn('release-run', str(caught.exception))
        self.assertEqual(self.seq(), ['verdict.run_started', 'verdict.run_abandoned', 'verdict.run_reconciled', 'verdict.run_held'])   # [E2]: reconcile before any new dispatch
        reconciled = self.payloads('verdict.run_reconciled')[0]
        self.assertEqual((reconciled['run_id'], reconciled['determination']), (started['run_id'], 'unknown'))
        self.assertEqual(self.lines(), 1)                                                         # [E4]: X not dispatched again
        status = verdict.status(self.ledger, 'P1')
        self.assertEqual(status['held'], [started['run_id']])
        self.assertEqual([r['outcome'] for r in status['runs']], ['held_unknown_outcome'])
        with self.assertRaises(LedgerError):
            verdict.run(self.ledger, 'P1', 'M1', self.root)                                       # a second restart changes nothing by itself
        self.assertEqual(len(self.payloads('verdict.run_started')), 1)
        self.assertEqual(len(self.payloads('verdict.run_held')), 1)
        with self.assertRaises(LedgerError):
            verdict.release_run(self.ledger, 'P1', 'no-such-run', 'typo')
        released = verdict.release_run(self.ledger, 'P1', started['run_id'], 'Checked: the marker file shows one line; a second run is acceptable here.')
        self.assertIn('not promised', released['note'])                                           # [E6]
        self.assertEqual(verdict.status(self.ledger, 'P1')['held'], [])
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        self.assertEqual(self.lines(), 2)                                                         # the release is what let X run again
        self.assertEqual(self.seq()[:5], ['verdict.run_started', 'verdict.run_abandoned', 'verdict.run_reconciled', 'verdict.run_held', 'verdict.run_released'])
        self.assertEqual(self.seq()[5], 'verdict.run_started')
        for text in (json.dumps(self.payloads('verdict.run_reconciled')), json.dumps(self.payloads('verdict.run_held')), str(caught.exception)):
            self.assertNotIn('exactly-once', text.replace('not promised', '')); self.assertNotIn('exactly once', text)   # [E6]

    def test_c_x_finished_before_the_receipt_is_completed_from_its_marker_without_a_second_run(self):
        task = self.plan_with(self.x(then_sleep=False))
        # X ran once (the verifier itself, outside any run) and its receipt reached the disk; the run then died before `verdict.receipt_issued`
        from onecrew.v2 import plan as plans
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
            contract, sha = plans.load(self.ledger, state, 1)
        milestone = contract['milestones'][0]
        blob, receipt = command.run(self.ledger, 'P1', 1, sha, milestone, self.root)
        self.assertEqual(self.lines(), 1)
        self.fabricate_run('r-c', pid=2 ** 22 + 4321, minutes=10)
        verdict._mark(self.ledger, 'r-c', 'dispatched', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'kind': 'command', 'at': 'fixture'})
        verdict._mark(self.ledger, 'r-c', 'receipt', {'blob': blob, 'receipt': receipt, 'integrity': None, 'cwd': str(self.root)})
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)                                   # the restart
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        self.assertEqual(self.lines(), 1)                                                         # X did not run again
        self.assertEqual(self.seq(), ['verdict.run_started', 'verdict.run_abandoned', 'verdict.run_reconciled', 'verdict.receipt_issued', 'verdict.recorded'])
        issued = self.payloads('verdict.receipt_issued')[0]
        self.assertEqual((issued['run_id'], issued['receipt'], issued.get('reconciled')), ('r-c', blob, True))
        self.assertEqual(self.payloads('verdict.run_reconciled')[0]['determination'], 'completed')
        self.assertEqual(self.payloads('verdict.recorded')[0]['receipt'], blob)
        self.assertFalse((Path(self.state) / verdict.RUNS_DIR / 'r-c').exists())
        self.assertEqual(verdict.status(self.ledger, 'P1')['held'], [])

    def test_a_a_run_that_never_dispatched_and_one_that_raised_let_a_new_run_start(self):
        self.plan_with(self.x(then_sleep=False))
        self.fabricate_run('r-a', pid=2 ** 22 + 999, minutes=10)                                  # no marker at all: X never started
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed'); self.assertEqual(self.lines(), 1)
        self.assertEqual([(p['run_id'], p['determination']) for p in self.payloads('verdict.run_reconciled')], [('r-a', 'not_dispatched')])
        self.assertEqual(self.payloads('verdict.run_held'), [])

    def test_the_markers_of_a_finished_run_are_removed_and_a_held_run_is_visible_in_status(self):
        self.plan_with(self.x(then_sleep=False))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        run_id = self.payloads('verdict.run_started')[0]['run_id']
        self.assertFalse((Path(self.state) / verdict.RUNS_DIR / run_id).exists())
        self.assertEqual(verdict.status(self.ledger, 'P1')['held'], [])
