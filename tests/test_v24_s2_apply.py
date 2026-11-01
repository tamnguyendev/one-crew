"""2.4-S2 / SF-03..05: feedback -> fix plan (another project) -> artifact of the right identity -> install at a declared target -> recheck
of the original error -> resume, with evidence, on a test environment. Missing authority is shown as blocked, never as PASS.

The venv operations of onecrew.v2.hotfix (create a venv, pip install, read its identity, run its `onecrew`, list processes) are replaced
here by fakes: the "new runtime" is this checkout's code run in-process, the old venv a folder with an `onecrew.exe` file. The same chain with
real venvs and real wheels runs in tests/test_v24_s2_installed.py.

Counterexamples (ROADMAP-DESIGN §7, S2 rows): a project edit grant does not allow a OneCrew fix or install; a valid support policy is not
re-asked; a missing grant or budget blocks the effect only, the bundle and the trial still complete; the old root is never extended; a wrong
wheel/hash/source or an unchecked reader pair is refused; a scan of other data grants no switch; a running process, an unknown effect, a shared
consumer or data changed after the drill blocks the switch; a crash between steps never doubles an effect; a ledger the old reader cannot read
refuses rollback and keeps the new ledger; an independent consumer keeps running; green patch tests are not installed/fixed/accepted; the
recheck runs on the target or a named copy; a lesson has its source and certainty and a recurrence links the history.
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

from onecrew.control_core import Control, migrate
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import hook_cli, plan as plans, verdict, where
from onecrew.v2.cli import main as cli_main
from tests.test_v2_l1 import plan_json
from tests.test_v24_s1_intake import Helpers
from tests.test_wf_candidate_handoff import CandidateFixture

VERSION = '2.4.0.dev2'


def hotfix():
    from onecrew.v2 import hotfix as module
    return module


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class FakeRuntime:
    """The venv side of hotfix, faked: counts every effect so a test can prove it happened once (or not at all)."""

    def __init__(self, case):
        self.case, self.venvs, self.installs, self.calls = case, [], [], []
        self.processes, self.old_reader_ok, self.scan_override = [], True, None

    def make_venv(self, base, path):
        path = Path(path)
        self.venvs.append(str(path))
        (path / 'Scripts').mkdir(parents=True)
        for name in ('python.exe', 'onecrew.exe'): (path / 'Scripts' / name).write_bytes(b'fake')
        (path / 'pyvenv.cfg').write_text('home = fake\n')

    def pip_install(self, python, wheel):
        self.installs.append((str(python), hashlib.sha256(Path(wheel).read_bytes()).hexdigest()))
        (Path(python).parent.parent / 'installed.txt').write_text(hashlib.sha256(Path(wheel).read_bytes()).hexdigest())

    def identity(self, venv):
        marker = Path(venv) / 'installed.txt'
        if not marker.is_file(): return {'version': 'unknown', 'record_sha256': 'unknown', 'version_line': ''}
        return {'version': VERSION, 'record_sha256': 'f' * 64, 'version_line': f'onecrew {VERSION}', 'wheel_sha256': marker.read_text()}

    def run_onecrew(self, exe, args, cwd=None, env=None):
        self.calls.append((str(exe), list(args)))
        old = Path(exe).resolve().is_relative_to(self.case.old_venv.resolve())
        if old and not self.old_reader_ok: return 2, '', 'Unrecognized database (the old reader cannot read this ledger)'
        if 'compat' in args and self.scan_override:
            return 0, json.dumps(self.scan_override(args)), ''
        out = io.StringIO()
        saved = os.environ.get('ONECREW_ACTOR')
        os.environ['ONECREW_ACTOR'] = 'codex'
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = cli_main(list(args))
        finally:
            if saved is None: os.environ.pop('ONECREW_ACTOR', None)
            else: os.environ['ONECREW_ACTOR'] = saved
        return code, out.getvalue(), ''

    def processes_under(self, venv):
        return self.processes


class S2Fixture(Helpers, CandidateFixture):
    """Customer project (this Fixture's repo) with engine root P1 whose node C produced the right file but failed its check (the "old
    runtime" defect); the OneCrew project (another git repo, same state root) with fix plan FIX1 whose milestone passed on its committed tree."""

    grant = ('support_install:lab',)

    def failing(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'old runtime: check failed')}
                                                for c in item['checks']]}

    def setUp(self):
        super().setUp()
        os.environ['LOCALAPPDATA'] = str(Path(self.temp.name) / 'localappdata')        # the hook registry of this test only
        self.revise(self.definition())
        self.step()
        self.assertEqual(self.engine.verify(self.ledger, 'P1', 'C', self.failing)['result'], 'fail')
        # the old venv: the declared target, used by this project's hooks
        self.old_venv = Path(self.temp.name) / 'venvs' / 'prod'
        (self.old_venv / 'Scripts').mkdir(parents=True)
        self.old_exe = self.old_venv / 'Scripts' / 'onecrew.exe'; self.old_exe.write_bytes(b'old')
        self.hook(self.root, self.old_exe)
        # the OneCrew project and its fix plan
        self.repo = Path(self.temp.name) / 'onecrew-repo'; self.repo.mkdir()
        git(self.repo, 'init', '-q'); git(self.repo, 'config', 'user.name', 'T'); git(self.repo, 'config', 'user.email', 't@localhost')
        (self.repo / 'a.txt').write_text('fixed code\n'); git(self.repo, 'add', '.'); git(self.repo, 'commit', '-q', '-m', 'fix')
        self.fix = Ledger(self.repo, self.ledger.state_root)
        self.fix_plan(self.grant)
        self.runtime = FakeRuntime(self)
        for name in ('make_venv', 'pip_install', 'identity', 'run_onecrew', 'processes_under'):
            target = patch.object(hotfix(), name, getattr(self.runtime, name)); target.start(); self.addCleanup(target.stop)
        code, made = self.report('--text', 'Node C fails although a.txt is right', '--plan', 'P1')
        self.fb = made['id']
        self.cli('support', 'classify', self.fb, '--class', 'onecrew_runtime', '--basis', 'receipt of node C')
        code, linked = self.cli('support', 'link', self.fb, '--plan', 'FIX1', '--project-id', self.fix.project_id)
        self.assertEqual(code, 0, linked)

    def hook(self, project, exe):
        settings = project / '.claude' / 'settings.local.json'
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(hook_cli.portable_settings(exe, self.ledger.state_root), indent=2), encoding='utf-8')
        where.register_project(project, self.ledger.state_root)

    def fix_plan(self, granted):
        actor = os.environ.pop('ONECREW_ACTOR', None)
        try:
            plans.propose(self.fix, 'FIX1', plan_json(authority={'edit': True, 'commands': True, 'apply_to_project': True,
                                                                 'granted_actions': list(granted)}), 'claude', workflow=True)
            plans.approve(self.fix, 'FIX1', 'owner', 'fixture owner approves the OneCrew fix plan')
            self.assertEqual(verdict.run(self.fix, 'FIX1', 'M1', self.repo)['milestones'][0]['state'], 'passed')
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor

    def wheel(self, version=VERSION, commit=None, tamper=False):
        folder = Path(self.temp.name) / 'pkg' / version; folder.mkdir(parents=True, exist_ok=True)
        wheel = folder / f'onecrew-{version}-py3-none-any.whl'
        with zipfile.ZipFile(wheel, 'w') as z:
            z.writestr(f'onecrew-{version}.dist-info/METADATA', f'Metadata-Version: 2.1\nName: onecrew\nVersion: {version}\n')
            z.writestr('onecrew/__init__.py', '')
        sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
        manifest = folder / 'manifest.json'
        manifest.write_text(json.dumps({'kind': 'fixture-package', 'version': version, 'code_commit': commit or git(self.repo, 'rev-parse', 'HEAD'),
                                        'wheel': {'name': wheel.name, 'sha256': '0' * 64 if tamper else sha}}), encoding='utf-8')
        return wheel, manifest

    def owner(self, *args):
        actor = os.environ.pop('ONECREW_ACTOR', None)
        try:
            return self.cli(*args)
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor

    def target(self):
        code, made = self.owner('support', 'target', 'add', '--id', 'lab', '--venv', str(self.old_venv))
        self.assertEqual(code, 0, made)

    def artifact(self, **kw):
        wheel, manifest = self.wheel(**kw)
        return self.cli('support', 'artifact', self.fb, '--wheel', str(wheel), '--manifest', str(manifest))

    def ready(self):
        self.target()
        code, made = self.artifact()
        self.assertEqual(code, 0, made)
        return made

    def install(self):
        return self.cli('support', 'install', self.fb, '--target', 'lab')

    def settings_exe(self, project=None):
        data = json.loads(((project or self.root) / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
        return {h['command'] for entries in data['hooks'].values() for e in entries for h in e['hooks']}

    def status(self):
        return self.cli('support', 'status', self.fb, '--json')[1]

    def root_rows(self):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            events = [tuple(r) for r in conn.execute('SELECT seq, kind, payload FROM events WHERE task_id=? ORDER BY seq', (task,))]
            budget = [tuple(r) for r in conn.execute("SELECT * FROM executions WHERE task_id=?", (task,))]
            deadline = conn.execute('SELECT deadline FROM tasks WHERE id=?', (task,)).fetchone()[0]
        return events, budget, deadline


class AuthorityTests(S2Fixture):
    grant = ()

    def test_project_edit_grant_does_not_allow_onecrew_fix_or_install(self):
        # also test_missing_grant_or_budget_blocks_effect_but_prepares_bundle_and_trial and the owner-only target declaration
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            code, refused = self.cli('support', 'target', 'add', '--id', 'lab', '--venv', str(self.old_venv))
        self.assertEqual(code, 2, refused); self.assertIn('refused', refused['error'])
        self.assertEqual(self.support_events('support.target'), [])
        code, bad = self.owner('support', 'target', 'add', '--id', 'Lab Box', '--venv', str(self.old_venv))
        self.assertEqual(code, 2, bad)
        self.ready()
        code, made = self.install()
        self.assertEqual(code, 0, made)
        self.assertEqual(made['result'], 'blocked_by_authority', made)
        self.assertIn('support_install:lab', made['reason'])
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})          # nothing switched
        self.assertFalse(Path(str(self.old_venv) + '-' + VERSION).exists())          # no venv at the target
        self.assertEqual(len(self.runtime.venvs), 1)                                  # only the trial, under the state root
        self.assertTrue(Path(self.runtime.venvs[0]).is_relative_to(self.ledger.state_root))
        state = self.status()
        self.assertFalse(state['installed']['value']); self.assertTrue(state['trial_build']['value'])
        self.assertEqual(state['install_blocked']['value'], 'blocked_by_authority')
        code, bundle = self.cli('support', 'bundle', self.fb)                         # the bundle is still prepared
        self.assertEqual(code, 0, bundle)
        first = made
        code, again = self.install()                                                  # asking again changes nothing, creates no request
        self.assertEqual((first['result'], again['result']), ('blocked_by_authority', 'blocked_by_authority'))
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)
        self.assertEqual(len(self.runtime.venvs), 1)
        prepared = self.support_events('support.install_prepared')
        self.assertTrue(prepared and prepared[-1]['blocked_by'] == 'authority' and prepared[-1]['drill'])
        self.assertNotIn(first['result'], ('pass', 'passed', 'switched')); self.assertIn('not a PASS', first['note'])

class BudgetTests(S2Fixture):
    def test_exhausted_budget_blocks_the_install_only(self):
        self.ready()
        with patch('onecrew.v2.internal_plan.ceilings', lambda *a, **k: {'remaining_calls': 0, 'remaining_seconds': 0, 'deadline': '2000-01-01T00:00:00+00:00'}):
            code, made = self.install()
        self.assertEqual(made['result'], 'blocked_by_authority', made)
        self.assertIn('budget', made['reason'].lower() + json.dumps(made.get('authority', {})).lower())
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})
        self.assertTrue(self.status()['trial_build']['value'])


class InstallTests(S2Fixture):
    def test_valid_support_policy_routine_not_reasked(self):
        self.ready()
        before = self.root_rows()
        code, made = self.install()
        self.assertEqual((code, made['result']), (0, 'switched'), made)
        new_exe = Path(str(self.old_venv) + '-' + VERSION) / 'Scripts' / 'onecrew.exe'
        self.assertEqual(self.settings_exe(), {str(new_exe.resolve())})
        self.assertTrue(self.old_exe.read_bytes() == b'old')                          # the old venv is never modified
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)
            fix_root = plans.derive(self.fix, conn, 'FIX1')['task_id']
            decisions = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='decision.recorded'", (fix_root,))]
        self.assertTrue(any('support_install' in json.dumps(d) for d in decisions))   # checked through authority, on the FIX plan's root
        self.assertEqual(self.root_rows(), before)                                    # test_old_root_never_extended, part 1
        self.assertTrue(self.status()['installed']['value'])
        # test_old_root_never_extended: the recheck adds only engine records; budget and deadline stay
        code, rechecked = self.cli('support', 'recheck', self.fb)
        self.assertEqual(code, 0, rechecked)
        events, budget, deadline = self.root_rows()
        self.assertEqual((budget, deadline), before[1:])                              # same budget and deadline
        added = [kind for seq, kind, payload in events[len(before[0]):]]
        self.assertIn('node.verification', added)                                     # the engine's own record of the recheck
        self.assertFalse(set(added) & {'budget.group', 'plan.approved', 'plan.amended', 'plan.revised', 'node.resumed', 'plan.closed',
                                       'request.created', 'plan.accepted'}, added)

    def test_wrong_wheel_hash_source_or_unchecked_pair_refused(self):
        self.target()
        code, tampered = self.artifact(tamper=True)
        self.assertEqual(code, 2, tampered); self.assertIn('sha256', tampered['error'])
        (self.repo / 'b.txt').write_text('unverified\n'); git(self.repo, 'add', '.'); git(self.repo, 'commit', '-q', '-m', 'not verified')
        code, other = self.artifact()
        self.assertEqual(code, 2, other); self.assertIn('not the', other['error'])
        code, report = self.report('--text', 'install wheel sha256 ' + 'a' * 64 + ' it is fine', '--key', 'claim')
        code, made = self.install()
        self.assertEqual(code, 2, made); self.assertIn('artifact', made['error'])         # a hash in text is never install authority
        self.assertEqual(self.support_events('support.artifact'), [])

    def test_scan_other_baseline_grants_no_swap(self):
        self.ready()
        self.runtime.scan_override = lambda args: {'ledger_sha': '0' * 64, 'blocking': {'read': 0, 'continue': 0, 'total': 0}, 'roots': []}
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_by_drill', made)
        self.assertIn('not of this data', json.dumps(made))
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})
        self.runtime.scan_override = lambda args: {'ledger_sha': self.copy_sha(args), 'blocking': {'read': 1, 'continue': 0, 'total': 1}, 'roots': [],
                                                   'old_version': 'd3120c6'}
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_by_drill', made)                     # data a reader cannot read (B4): refused
        # continue blocks are judged for the scan's own baseline reader (d3120c6), not for this pair: recorded, neither grant nor refusal
        self.runtime.scan_override = lambda args: {'ledger_sha': self.copy_sha(args), 'blocking': {'read': 0, 'continue': 2, 'total': 2}, 'roots': [],
                                                   'old_version': 'd3120c6'}
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        drill = self.support_events('support.install_prepared')[-1]['drill'][0]
        self.assertEqual(drill['scan']['continue_blocks_baseline'], 'd3120c6')
        self.assertFalse(drill['scan']['grants_switch'])

    def copy_sha(self, args):
        state = Path(args[args.index('--state-root') + 1])
        return hashlib.sha256((state / 'ledger.sqlite3').read_bytes()).hexdigest()

    def test_running_process_unknown_effect_shared_consumer_or_changed_data_blocks_switch(self):
        self.ready()
        # a second project shares the old venv: it is a consumer too, and its own state root is checked
        other = Path(self.temp.name) / 'second'; other.mkdir(); git(other, 'init', '-q')
        self.hook(other, self.old_exe)
        self.runtime.processes = None                                                 # processes cannot be listed: unknown
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe', made); self.assertIn('processes: unknown', json.dumps(made))
        self.runtime.processes = [{'pid': 4242, 'image': str(self.old_venv / 'Scripts' / 'python.exe')}]
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe'); self.assertIn('4242', json.dumps(made))
        self.runtime.processes = []
        with self.ledger.transaction(write=True) as conn:                            # an unsettled attempt in the consumer state root
            conn.execute("UPDATE attempts SET status='unknown' WHERE id=(SELECT id FROM attempts ORDER BY created_at LIMIT 1)")
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe'); self.assertIn('attempt', json.dumps(made))
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE attempts SET status='settled'")
        consumers = {c['project'] for c in made['consumers']}
        self.assertIn(os.path.normcase(str(other.resolve())), consumers)
        # data changed after the drill: the fence differs at the switch
        real = hotfix().safe_point
        def changed(*args, **kwargs):
            with self.ledger.transaction(write=True) as conn:
                task = plans.derive(self.ledger, conn, 'P1')['task_id']
                plans.emit(self.ledger, conn, task, 'notice.exception', {'version': 1, 'category': 'deadline', 'cause': 'x', 'reason': 'x',
                                                                        'evidence': ['fixture'], 'plan': 'P1'})
            return real(*args, **kwargs)
        with patch.object(hotfix(), 'safe_point', changed):
            code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe'); self.assertIn('fence', json.dumps(made))
        self.assertEqual(self.settings_exe(other), {str(self.old_exe.resolve())})
        code, made = self.install()                                                   # nothing in the way any more: both consumers switch
        self.assertEqual(made['result'], 'switched', made)
        new_exe = str((Path(str(self.old_venv) + '-' + VERSION) / 'Scripts' / 'onecrew.exe').resolve())
        self.assertEqual((self.settings_exe(), self.settings_exe(other)), ({new_exe}, {new_exe}))

    def test_independent_branch_keeps_running(self):
        self.ready()
        independent = Path(self.temp.name) / 'independent'; independent.mkdir(); git(independent, 'init', '-q')
        elsewhere = Path(self.temp.name) / 'venvs' / 'other' / 'Scripts'; elsewhere.mkdir(parents=True)
        (elsewhere / 'onecrew.exe').write_bytes(b'other')
        self.hook(independent, elsewhere / 'onecrew.exe')                              # uses another venv: not a consumer
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        self.assertEqual(self.settings_exe(independent), {str((elsewhere / 'onecrew.exe').resolve())})
        self.assertNotIn(os.path.normcase(str(independent.resolve())), {c['project'] for c in made['consumers']})

    def test_crash_between_prepare_install_switch_resume_no_double_effect(self):
        self.ready()
        second = Path(self.temp.name) / 'second'; second.mkdir(); git(second, 'init', '-q')
        self.hook(second, self.old_exe)
        for point in ('after_venv', 'after_prepared', 'mid_switch'):
            with patch.dict(os.environ, {'ONECREW_SUPPORT_CRASH': point}):
                with self.assertRaises(hotfix().Crash):
                    hotfix().install(self.ledger, self.fb, 'lab')
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        code, again = self.install()
        self.assertEqual(again['result'], 'switched'); self.assertTrue(again.get('already'))
        self.assertEqual(len(self.runtime.venvs), 1); self.assertEqual(len(self.runtime.installs), 1)       # one venv, one install
        self.assertEqual(len([e for e in self.support_events('support.install') if e['result'] == 'switched']), 1)
        new_exe = str((Path(str(self.old_venv) + '-' + VERSION) / 'Scripts' / 'onecrew.exe').resolve())
        self.assertEqual((self.settings_exe(), self.settings_exe(second)), ({new_exe}, {new_exe}))

    def test_unreadable_by_old_refuses_rollback_and_keeps_new_ledger(self):
        self.ready()
        self.install()
        before = self.others()
        self.runtime.old_reader_ok = False
        code, made = self.cli('support', 'rollback', self.fb)
        self.assertEqual(code, 0, made)
        self.assertEqual(made['result'], 'refused', made); self.assertIn('old reader', made['reason'])
        new_exe = str((Path(str(self.old_venv) + '-' + VERSION) / 'Scripts' / 'onecrew.exe').resolve())
        self.assertEqual(self.settings_exe(), {new_exe})                               # the current state is kept
        self.assertEqual(self.others(), before)                                        # the newer ledger is kept as it is (only support records added)
        self.runtime.old_reader_ok = True
        code, back = self.cli('support', 'rollback', self.fb)
        self.assertEqual(back['result'], 'rolled_back', back)
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})
        self.assertFalse(self.status()['installed']['value'])

    def test_recheck_on_target_or_named_copy_only(self):
        self.ready()
        # test_green_patch_tests_are_not_installed_or_fixed_or_accepted
        state = self.status()
        self.assertFalse(state['installed']['value']); self.assertFalse(state['verified_at_target']['value'])
        self.assertFalse(state['user_confirmed']['value'])
        self.assertEqual(state['still_blocked']['value'], True)
        artifact = self.support_events('support.artifact')[0]
        self.assertEqual(artifact['bound_to']['record'], 'milestone.passed')
        code, refused = self.cli('support', 'recheck', self.fb)
        self.assertEqual(code, 2, refused)                                            # no runtime prepared yet
        with patch.object(hotfix().authority, 'decide', lambda *a, **k: {'in_authority': False, 'class': 'U2', 'kind': 'support_install',
                                                                          'q': None, 'reason': 'fixture: not granted', 'nodes': []}):
            self.install()
        events_before = self.root_rows()[0]
        code, on_copy = self.cli('support', 'recheck', self.fb)
        self.assertEqual(code, 0, on_copy)
        self.assertEqual((on_copy['environment'], on_copy['result']), ('copy', 'pass'), on_copy)
        self.assertNotEqual(Path(on_copy['state_root']), self.ledger.state_root)
        self.assertEqual(self.root_rows()[0], events_before)                          # the target's ledger untouched by a copy recheck
        self.assertFalse(self.status()['verified_at_target']['value'])
        self.install()
        code, on_target = self.cli('support', 'recheck', self.fb)
        self.assertEqual((on_target['environment'], on_target['result']), ('target', 'pass'), on_target)
        self.assertTrue(self.status()['verified_at_target']['value'])
        self.assertFalse(self.status()['still_blocked']['value'])
        receipt = on_target['receipt']
        body = json.loads(self.store.read_blob(receipt))
        self.assertEqual((body['kind'], body['node'], body['result']), ('node-verifier-receipt', 'C', 'pass'))

    def test_lesson_has_source_and_certainty_recurrence_links_history(self):
        self.ready()
        code, early = self.cli('support', 'learn', self.fb, '--text', 'Verifier env leaked a variable')
        self.assertEqual(code, 2, early)                                              # not before a verified recheck at the target
        code, early = self.cli('support', 'resume', self.fb)
        self.assertEqual(code, 2, early)                                              # no passing recheck at the target: no resume
        self.install()
        self.cli('support', 'recheck', self.fb)
        # test_resume_only_through_the_engine_guards
        code, resumed = self.cli('support', 'resume', self.fb)
        self.assertEqual(code, 0, resumed)
        self.assertEqual(resumed['mode'], 'not_held')                                 # nothing held: the root simply continues
        self.assertFalse(resumed['budget_reset']); self.assertFalse(resumed['grants_authority'])
        self.assertEqual(len(self.support_events('support.resumed')), 1)
        code, lesson = self.cli('support', 'learn', self.fb, '--text', 'The verifier environment of 2.4.0.dev1 leaked a variable into checks')
        self.assertEqual(code, 0, lesson)
        from onecrew.v2 import knowledge
        found = [r for r in knowledge.records(self.fix) if 'leaked a variable' in r['text']]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['evidence']['cause'], 'not_established')
        sources = found[0].get('sources') or found[0]['evidence'].get('sources') or []
        self.assertTrue(any(s.get('type') == 'receipt' for s in sources), found[0])
        self.assertEqual(found[0]['evidence']['status'], 'verified')
        self.assertEqual(lesson['root'], 'plan-ns:FIX1')
        code, again = self.report('--text', 'node C fails although a.txt is right!', '--plan', 'P1')
        self.assertEqual(again['recurrence_of'], [self.fb])                          # a recurrence after a fix names the earlier report
        code, view = self.cli('support', 'show', again['id'], '--json')
        self.assertEqual(view['feedback']['recurrence_of'], [self.fb])
        code, unrelated = self.report('--text', 'something else broke', '--plan', 'P1')
        self.assertEqual(unrelated['recurrence_of'], [])

