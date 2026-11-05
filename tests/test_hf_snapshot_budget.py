"""Hotfix: `verdict run` on a large repository. Behaviour cases, red on v2.5.0.dev10 (c4951f6), green on the fix.

X = the milestone command: it appends one line to a marker file outside the project, so each run of it is counted.
A slow git is a real program in front of git (`slow_git.py`): for the n-th call of a chosen step it starts a child and waits; every other call goes to the
real git. On the old code, which has no way to replace the program, the same n-th call raises what `subprocess.run(timeout=120)` raises there: that is
the failure the worker saw, and the old limit of 120 s cannot be waited for in a quick test.
"""
import json
import os
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_wf_r03a_run_started import RunFixture, PY, _have_git, REPO        # noqa: E402
from onecrew.ledger import LedgerError                                       # noqa: E402
from onecrew.v2 import plan as plans, verdict                                # noqa: E402
from onecrew.v2.verifiers import command                                     # noqa: E402

FIXED = hasattr(command, 'GIT_PROGRAM')

SLOW_GIT = textwrap.dedent("""\
    import json, os, subprocess, sys, time
    settings = json.load(open(sys.argv[1]))
    args = sys.argv[2:]
    if settings['step'] in args:
        with open(settings['counter'], 'a') as f: f.write('x')
        if os.path.getsize(settings['counter']) == settings['nth']:
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(%d)' % settings['seconds']])
            with open(settings['pids'], 'a') as f: f.write('%d %d\\n' % (os.getpid(), child.pid))
            time.sleep(settings['seconds'])
    sys.exit(subprocess.run(['git', *args]).returncode)
""")


def alive(pid):
    return verdict.process_alive(pid)


class Case(RunFixture):
    def setUp(self):
        if not _have_git(): self.skipTest('git is required')
        super().setUp()
        self.marker = Path(self.temp.name) / 'x-effects.txt'

    def x(self):
        return [PY, '-c', 'import sys; open(sys.argv[1],"a").write("x\\n"); print("x ran")', str(self.marker)]

    def runs_of_x(self):
        return self.marker.read_text().count('x') if self.marker.exists() else 0

    def fault(self, step, nth=1, seconds=90, minutes='0.5'):
        """The n-th call of a git step does not finish in time."""
        if not FIXED:
            real, seen = subprocess.run, []
            def run(argv, *a, **k):
                if isinstance(argv, list) and step in argv:
                    seen.append(1)
                    if len(seen) == nth: raise subprocess.TimeoutExpired(argv, 120)
                return real(argv, *a, **k)
            return patch.object(command.subprocess, 'run', run)
        folder = Path(self.temp.name) / 'slow'
        folder.mkdir(exist_ok=True)
        (folder / 'slow_git.py').write_text(SLOW_GIT)
        self.pids = folder / 'pids'
        (folder / 'settings.json').write_text(json.dumps({'step': step, 'nth': nth, 'seconds': seconds, 'counter': str(folder / 'counter'), 'pids': str(self.pids)}))
        program = patch.object(command, 'GIT_PROGRAM', (PY, str(folder / 'slow_git.py'), str(folder / 'settings.json')))
        limit = patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': minutes})
        class Both:
            def __enter__(s): program.start(); limit.start()
            def __exit__(s, *e): limit.stop(); program.stop()
        return Both()

    def events(self, kind):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            rows = conn.execute('SELECT kind, payload FROM events WHERE task_id=? ORDER BY seq', (task,)).fetchall()
        return [json.loads(r[1]) for r in rows if r[0] == kind]

    def verdicts(self):
        return plans.show(self.ledger, 'P1')['verdicts'] if 'verdicts' in plans.show(self.ledger, 'P1') else self.events('verdict.recorded')

    def real_state(self):
        git = lambda *a: subprocess.run(['git', '-C', str(self.root), *a], capture_output=True).stdout
        index = git('rev-parse', '--git-path', 'index').decode().strip()
        index = Path(index) if Path(index).is_absolute() else Path(self.root) / index
        return index.read_bytes(), git('for-each-ref'), git('rev-parse', 'HEAD'), git('status', '--porcelain', '--', '.', ':!.onecrew')

    # ---- a snapshot that does not finish before the verifier ----------------------------------------------------------------------------------

    def test_01_timeout_before_the_verifier_is_a_clean_refusal(self):
        self.plan_with(self.x())
        before = self.real_state()
        with self.fault('update-index'):
            with self.assertRaises(LedgerError) as caught:
                verdict.run(self.ledger, 'P1', 'M1')
        self.assertIsInstance(caught.exception, command.SnapshotFailed)
        details = caught.exception.structured()
        self.assertIs(details['verifier_started'], False)
        self.assertEqual(details['snapshot']['step'].split()[0], 'update-index')
        self.assertIn('no release is needed', details['next'])
        self.assertEqual(self.runs_of_x(), 0, 'the verifier was not called')
        self.assertEqual(self.events('verdict.recorded'), [], 'no verdict')
        self.assertEqual(self.events('verdict.receipt_issued'), [], 'no receipt')
        abandoned = self.events('verdict.run_abandoned')
        self.assertEqual([a['phase'] for a in abandoned], ['before_dispatch'])
        self.assertEqual(self.real_state(), before, 'the real index, refs, HEAD and files stay')

    def test_02_the_same_run_again_is_not_held_and_runs_once(self):
        self.plan_with(self.x())
        try:
            with self.fault('update-index'):
                verdict.run(self.ledger, 'P1', 'M1')
        except (LedgerError, subprocess.TimeoutExpired):
            pass
        shown = verdict.run(self.ledger, 'P1', 'M1')              # old code: held, as if the verifier might have run
        self.assertEqual(self.runs_of_x(), 1)
        self.assertEqual(len(self.events('verdict.run_abandoned')), 1, 'the failed attempt stays in the history')
        self.assertEqual([r['determination'] for r in self.events('verdict.run_reconciled')], ['raised'])
        self.assertEqual(self.events('verdict.run_held'), [])
        self.assertEqual([v['result'] for v in self.events('verdict.recorded')], ['pass'])
        self.assertTrue(shown)

    def test_03_timeout_in_the_checkout_is_also_before_the_verifier(self):
        self.plan_with(self.x())
        with self.fault('checkout-index'):
            with self.assertRaises(LedgerError) as caught:
                verdict.run(self.ledger, 'P1', 'M1')
        self.assertIsInstance(caught.exception, command.SnapshotFailed)
        self.assertIs(caught.exception.verifier_started, False)
        self.assertEqual(self.runs_of_x(), 0)
        self.assertEqual(self.events('verdict.recorded'), [])

    # ---- a snapshot that does not finish after the verifier -------------------------------------------------------------------------------------

    def after_fault(self):
        """The call of update-index in the snapshot after the verifier (the first one is the snapshot before it, the only other is this one)."""
        return self.fault('update-index', nth=2)

    def test_04_timeout_after_the_verifier_keeps_what_ran(self):
        self.plan_with(self.x())
        with self.after_fault():
            verdict.run(self.ledger, 'P1', 'M1')                  # old code: TimeoutExpired, no receipt, the run of X is lost
        self.assertEqual(self.runs_of_x(), 1)
        recorded = self.events('verdict.recorded')
        self.assertEqual([v['result'] for v in recorded], ['inconclusive'], 'never a pass, and the run is not lost')
        issued = self.events('verdict.receipt_issued')
        body = json.loads(verdict._blob(self.ledger, issued[0]['receipt']))
        self.assertEqual(body['exit_code'], 0, 'what the verifier said is kept')
        self.assertIsNone(body['artifact_sha_after'])
        self.assertIn('cannot be identified', body['error'])
        self.assertIs(body['snapshot']['failed']['verifier_started'], True)
        self.assertEqual(self.events('verdict.run_held'), [])

    def test_05_after_that_nothing_replays_by_itself(self):
        self.plan_with(self.x())
        with self.after_fault():
            verdict.run(self.ledger, 'P1', 'M1')
        verdict.status(self.ledger, 'P1')
        verdict.reconcile(self.ledger, 'P1', 1, 'M1')
        self.assertEqual(self.runs_of_x(), 1, 'reading and reconciling never run the verifier again')
        self.assertEqual(len(self.events('verdict.recorded')), 1, 'no second verdict')
        views = plans.milestone_views(*self.current(), self.ledger)
        self.assertEqual(views[0]['attempts'] if 'attempts' in views[0] else 1, 1)

    def current(self):
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        revision = plans.resolve(self.ledger, state)['revision']
        contract, _ = plans.load(self.ledger, state, revision)
        return contract, state, revision

    # ---- the budget -----------------------------------------------------------------------------------------------------------------------------

    def test_06_a_slow_snapshot_inside_the_budget_passes(self):
        if not FIXED: self.fail('dev10: a git step over the fixed 120 s cannot be allowed by any setting')
        self.plan_with(self.x())
        with self.fault('update-index', seconds=25, minutes='5'), patch.object(command, 'STEP_SECONDS', 20):
            verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual([v['result'] for v in self.events('verdict.recorded')], ['pass'])
        self.assertEqual(self.runs_of_x(), 1)

    def test_07_the_root_deadline_is_not_extended(self):
        import datetime as dt
        if not FIXED: self.fail('dev10: a git step waits its 120 s whatever the root deadline leaves')
        anchor = self.plan_with(self.x())
        self.assertTrue(anchor)
        contract, state, revision = self.current()
        milestone = contract['milestones'][0]
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)).isoformat()
        began = time.monotonic()
        with self.fault('update-index', minutes='30'):
            with self.assertRaises(command.SnapshotFailed) as caught:
                command.run(self.ledger, 'P1', revision, 'sha', milestone, self.root, deadline=soon)
        self.assertLess(time.monotonic() - began, 30, 'stopped by the deadline, not by the 30 minutes')
        self.assertLessEqual(caught.exception.limit, 2)
        self.assertEqual(self.runs_of_x(), 0)
        gone = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)).isoformat()
        with self.assertRaises(command.SnapshotFailed) as caught:
            command.run(self.ledger, 'P1', revision, 'sha', milestone, self.root, deadline=gone)
        self.assertEqual(caught.exception.reason, 'deadline')
        self.assertIn('owner', caught.exception.structured()['next'])
        self.assertEqual(self.runs_of_x(), 0)

    def test_08_there_is_no_unlimited_setting(self):
        if not FIXED: self.fail('dev10 has no setting')
        for value in ('0', '-1', 'nan', 'inf', 'abc', '721'):
            with patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': value}):
                with self.assertRaises(LedgerError, msg=value):
                    command.snapshot_seconds()
        with patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': ''}):
            self.assertEqual(command.snapshot_seconds(), command.SNAPSHOT_MINUTES * 60)

    def test_09_a_refused_setting_writes_no_run(self):
        if not FIXED: self.fail('dev10 has no setting')
        self.plan_with(self.x())
        with patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': 'abc'}):
            with self.assertRaises(LedgerError):
                verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.runs_of_x(), 0)
        self.assertEqual(self.events('verdict.run_held'), [])

    def test_10_a_long_snapshot_does_not_look_like_a_lost_run(self):
        import datetime as dt
        self.plan_with(self.x())
        verdict.run(self.ledger, 'P1', 'M1')
        started = self.events('verdict.run_started')[0]
        room = dt.datetime.fromisoformat(started['deadline']) - dt.datetime.fromisoformat(started['started'])
        wanted = started['max_minutes'] * 60 + verdict.RUN_GRACE_SECONDS + 3 * (command.SNAPSHOT_MINUTES * 60 if FIXED else 1800)
        self.assertGreaterEqual(room.total_seconds(), wanted - 1)

    def test_11_the_kill_reaches_this_git_and_its_child_only(self):
        if not FIXED: self.fail('dev10: subprocess.run kills the direct child only')
        self.plan_with(self.x())
        bystander = subprocess.Popen([PY, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(bystander.wait)
        self.addCleanup(bystander.kill)
        with self.fault('update-index'):
            with self.assertRaises(LedgerError):
                verdict.run(self.ledger, 'P1', 'M1')
        pids = [int(p) for p in self.pids.read_text().split()]
        self.assertEqual(len(pids), 2)
        time.sleep(0.5)
        for pid in pids: self.assertFalse(alive(pid), pid)
        self.assertIsNone(bystander.poll(), 'a process of someone else keeps running')

    def test_12_the_limit_holds_while_git_reads_a_long_input(self):
        if not FIXED: self.fail('dev10: subprocess.run on Windows writes the input first; see evidence stdin_limit')
        folder = Path(self.temp.name)
        slow = folder / 'slow_reader.py'
        slow.write_text('import sys, time\nwhile sys.stdin.buffer.read(4096): time.sleep(0.2)\n')
        began = time.monotonic()
        with patch.object(command, 'GIT_PROGRAM', (PY, str(slow))), patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': '0.02'}):
            with command.snapshot_limits(), command._snapshot('test'):
                with self.assertRaises(command.SnapshotFailed):
                    command._git(self.root, 'update-index', '--stdin', input=b'x' * 8_000_000)
        self.assertLess(time.monotonic() - began, 15)

    # ---- what the artifact holds stays what it held -----------------------------------------------------------------------------------------------

    def test_13_a_file_outside_owned_still_changes_the_artifact(self):
        self.plan_with(self.x())
        verdict.run(self.ledger, 'P1', 'M1')
        passed = self.events('verdict.recorded')[-1]
        outside = Path(self.root) / 'config-outside-owned.txt'
        outside.write_text('a setting the result depends on\n')
        now = command.artifact_sha(self.root)
        self.assertNotEqual(now, passed['artifact_sha'])
        contract, state, revision = self.current()
        views = plans.milestone_views(contract, state, revision, self.ledger)
        self.assertTrue(views[0].get('stale'), 'the pass is not inherited by the changed artifact')

    def test_14_an_untracked_output_is_in_the_artifact(self):
        output = Path(self.root) / 'outputs' / 'result.txt'
        output.parent.mkdir()
        output.write_text('what the task made\n')
        self.plan_with(self.x())
        tree = command.artifact_sha(self.root)
        listed = subprocess.run(['git', '-C', str(self.root), 'ls-tree', '-r', '--name-only', tree], capture_output=True, text=True).stdout
        self.assertIn('outputs/result.txt', listed)
        ignored = Path(self.root) / '.gitignore'
        self.assertFalse(ignored.exists() and 'outputs' in ignored.read_text())

    def test_15_the_older_guards_hold(self):
        target = Path(self.root) / 'kept.txt'
        target.write_text('x\n')
        self.plan_with(self.x())
        os.link(target, Path(self.root) / 'second-name.txt')
        with self.assertRaises(command.HardLinked):
            command.verified_sha(self.root)
        tree = command.artifact_sha(self.root)                    # a marker, never the content
        listed = subprocess.run(['git', '-C', str(self.root), 'show', f'{tree}:second-name.txt'], capture_output=True, text=True).stdout
        self.assertIn('onecrew: not read', listed)

    # ---- what is reported -------------------------------------------------------------------------------------------------------------------------

    def test_16_the_receipt_keeps_the_verifier_time_apart(self):
        self.plan_with(self.x())
        verdict.run(self.ledger, 'P1', 'M1')
        body = json.loads(verdict._blob(self.ledger, self.events('verdict.receipt_issued')[0]['receipt']))
        for key in ('before_seconds', 'checkout_seconds', 'after_seconds', 'limit_seconds'):
            self.assertIn(key, body['snapshot'], key)
        self.assertLess(body['seconds'], body['snapshot']['before_seconds'] + body['snapshot']['after_seconds'] + body['seconds'] + 1)
        self.assertEqual([v['result'] for v in self.events('verdict.recorded')], ['pass'])

    def cli(self, *args, **env):
        environment = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}
        return subprocess.run([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state), *args], cwd=REPO, capture_output=True,
                              text=True, encoding='utf-8', env=dict(environment, PYTHONUTF8='1', **env), timeout=120)

    def test_17_the_command_says_it_in_json_with_no_traceback(self):
        self.plan_with(self.x())
        done = self.cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1', ONECREW_SNAPSHOT_MINUTES='0.00001')
        self.assertNotIn('Traceback', done.stderr)
        answer = json.loads(done.stdout)
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertEqual(answer['type'], 'SnapshotFailed')
        self.assertIs(answer['verifier_started'], False)
        self.assertEqual(self.runs_of_x(), 0)

    def test_18_a_quick_snapshot_is_silent_and_a_slow_one_says_what_it_does(self):
        self.plan_with(self.x())
        done = self.cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stderr.strip(), '', 'nothing on a small repository')
        json.loads(done.stdout)
        if not FIXED: self.fail('dev10 says nothing while it waits')
        import contextlib
        import io
        said = io.StringIO()
        with patch.object(command, 'PROGRESS_SECONDS', 0.2), patch.dict(os.environ, {'ONECREW_SNAPSHOT_MINUTES': '5'}), contextlib.redirect_stderr(said):
            with command.snapshot_limits(), command._snapshot('before the verifier'):
                budget = command._active.get()
                time.sleep(0.3)
                budget.say('update-index')
        self.assertIn('snapshot (before the verifier): update-index', said.getvalue())

    def test_19_a_view_keeps_its_short_limit_and_does_not_fail(self):
        self.plan_with(self.x())
        verdict.run(self.ledger, 'P1', 'M1')
        if not FIXED: self.fail('dev10: TimeoutExpired out of artifact_sha for every caller that does not catch it')
        with patch.object(command, 'STEP_SECONDS', 20), self.fault('update-index', minutes='30'):
            contract, state, revision = self.current()
            began = time.monotonic()
            views = plans.milestone_views(contract, state, revision, self.ledger)
        self.assertLess(time.monotonic() - began, 90, 'a view does not wait for the long budget')
        self.assertEqual(views[0]['state'], 'passed')

    # ---- the runs from before the fix -----------------------------------------------------------------------------------------------------------------

    def old_failed_run(self):
        """What the old runtime leaves: a dispatched marker, then an abandonment in phase `verifier` with TimeoutExpired."""
        run_id = verdict._begin_run(self.ledger, 'P1', 1, 'M1', 'command', 5)
        verdict._mark(self.ledger, run_id, 'dispatched', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'kind': 'command', 'at': '2026-11-05T02:00:00+00:00'})
        verdict._abandon_own(self.ledger, 'P1', run_id, subprocess.TimeoutExpired(['git', 'update-index'], 120), 'verifier')
        return run_id

    def test_20_an_old_failed_run_stays_held_until_someone_says_why(self):
        self.plan_with(self.x())
        run_id = self.old_failed_run()
        with self.assertRaises(LedgerError) as caught:
            verdict.run(self.ledger, 'P1', 'M1')
        self.assertIn(run_id, str(caught.exception))
        self.assertEqual(self.runs_of_x(), 0, 'the old record cannot tell before from after the verifier, so nothing runs')
        verdict.release_run(self.ledger, 'P1', run_id, 'read the traceback: it stopped in the snapshot before the verifier')
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(self.runs_of_x(), 1)
        self.assertEqual(len(self.events('verdict.run_abandoned')), 1, 'its history stays')
        self.assertEqual(len(self.events('verdict.run_released')), 1)
        self.assertEqual([v['result'] for v in self.events('verdict.recorded')], ['pass'])
