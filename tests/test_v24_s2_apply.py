"""2.4-S2 / SF-03..05: feedback -> fix plan (another project) -> artifact of the right identity -> install at a declared target -> recheck
of the original error -> resume, with evidence, on a test environment. Missing authority is shown as blocked, never as PASS.

The venv operations of onecrew.v2.hotfix (create a venv, pip install, read its identity, run its `onecrew`, classify kinds with it, list
processes) are replaced by fakes: the "new runtime" is this checkout's code run in-process, the old venv a folder with an `onecrew.exe` file.
The fake pip install keeps the wheel's own RECORD as the installed RECORD, so a venv that holds another wheel is visible (S2-R02). The fix
project is a small OneCrew-shaped repository (pyproject with py-modules) and its wheels are real wheels of its commits (tests/wf_wheel),
so the content of a wheel is checked against the verified commit (S2-R01). The same chain with real venvs runs in test_v24_s2_installed.py.

Counterexamples: ROADMAP-DESIGN §7 S2 rows and every probe of review-s2/review-s2.md (p01-p10), plus the review's missing cases.
"""
import contextlib
import csv
import hashlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

from onecrew.control_core import migrate
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import hook_cli, notification_cli, plan as plans, verdict, where
from onecrew.v2.cli import main as cli_main
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from tests.test_v24_s1_intake import Helpers
from tests.test_wf_candidate_handoff import CandidateFixture

VERSION = '2.4.0.dev2'
PYPROJECT = ('[project]\nname = "onecrew"\nversion = "VERSION"\n\n[tool.setuptools]\npackages = []\npy-modules = [\n'
             '    "onecrew.v2.fixmod",\n]\n')


def hotfix():
    from onecrew.v2 import hotfix as module
    return module


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def rows_of(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next(n for n in archive.namelist() if n.endswith('.dist-info/RECORD'))
        return [r[:2] for r in csv.reader(io.StringIO(archive.read(name).decode('utf-8'))) if r]


def craft(wheel, add=None, change=None):
    """A copy of `wheel` with files added or changed and a RECORD that matches them (so only the commit comparison can catch it)."""
    out = wheel.parent / ('crafted-' + hashlib.sha256(repr((add, change)).encode()).hexdigest()[:8]) / wheel.name
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(wheel) as source:
        files = {n: source.read(n) for n in source.namelist()}
    files.update(add or {}); files.update(change or {})
    record = next(n for n in files if n.endswith('.dist-info/RECORD'))
    text = io.StringIO(); writer = csv.writer(text)
    for name, data in files.items():
        if name != record: writer.writerow([name, hotfix()._hash(data), str(len(data))])
    writer.writerow([record, '', ''])
    files[record] = text.getvalue().encode()
    with zipfile.ZipFile(out, 'w') as target:
        for name, data in files.items(): target.writestr(name, data)
    return out


class FakeRuntime:
    """The venv side of hotfix, faked: counts every effect so a test can prove it happened once (or not at all)."""

    def __init__(self, case):
        self.case, self.venvs, self.installs, self.calls = case, [], [], []
        self.processes, self.old_reader_ok, self.scan_override, self.old_scan, self.unknown_kinds = [], True, None, None, set()

    def make_venv(self, base, path):
        path = Path(path)
        self.venvs.append(str(path))
        (path / 'Scripts').mkdir(parents=True)
        for name in ('python.exe', 'onecrew.exe'): (path / 'Scripts' / name).write_bytes(b'fake')
        (path / 'pyvenv.cfg').write_text('home = fake\n')

    def pip_install(self, python, wheel):
        data = Path(wheel).read_bytes()
        self.installs.append((str(python), hashlib.sha256(data).hexdigest()))
        version = Path(wheel).name.split('-')[1]
        rows = rows_of(data) + [[f'onecrew-{version}.dist-info/INSTALLER', 'sha256=pip']]
        (Path(python).parent.parent / 'installed.json').write_text(json.dumps({'version': version, 'rows': rows}))

    def identity(self, venv):
        marker = Path(venv) / 'installed.json'
        if not marker.is_file(): return {'version': 'unknown', 'rows': [], 'location': None, 'version_line': ''}
        value = json.loads(marker.read_text())
        return {'version': value['version'], 'rows': value['rows'], 'location': str(Path(venv) / 'Lib' / 'site-packages' / 'onecrew'),
                'version_line': f'onecrew {value["version"]}'}

    def is_old(self, exe):
        return Path(exe).resolve().is_relative_to(self.case.old_venv.resolve())

    def run_onecrew(self, exe, args, cwd=None, env=None):
        self.calls.append((str(exe), list(args)))
        old = self.is_old(exe)
        if old and not self.old_reader_ok: return 2, '', 'Unrecognized database (the old reader cannot read this ledger)'
        if 'compat' in args and old and self.old_scan: return 0, json.dumps(self.old_scan(args)), ''
        if 'compat' in args and not old and self.scan_override: return 0, json.dumps(self.scan_override(args)), ''
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

    def event_classes(self, venv, kinds):
        from onecrew.v2 import compat
        return {k: None if k in self.unknown_kinds else compat.event_class(k) for k in kinds}

    def processes_under(self, venv):
        return self.processes


class S2Fixture(Helpers, CandidateFixture):
    """Customer project (this Fixture's repo) with engine root P1 whose node C produced the right file but failed its check (the "old
    runtime" defect); the OneCrew project (a small package repository, same state root) with fix plan FIX1 whose milestone passed on its
    committed tree."""

    grant = ('support_install:lab',)

    def failing(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'old runtime: check failed')}
                                                for c in item['checks']]}

    def setUp(self):
        super().setUp()
        os.environ['LOCALAPPDATA'] = str(Path(self.temp.name) / 'localappdata')        # restored by the Fixture's environment patch
        os.environ.pop('WF_WHEEL', None)
        self.revise(self.definition())
        self.step()
        self.assertEqual(self.engine.verify(self.ledger, 'P1', 'C', self.failing)['result'], 'fail')
        self.old_venv = Path(self.temp.name) / 'venvs' / 'prod'
        (self.old_venv / 'Scripts').mkdir(parents=True)
        self.old_exe = self.old_venv / 'Scripts' / 'onecrew.exe'; self.old_exe.write_bytes(b'old')
        self.hook(self.root, self.old_exe)
        self.repo = Path(self.temp.name) / 'onecrew-repo'; self.repo.mkdir()
        git(self.repo, 'init', '-q'); git(self.repo, 'config', 'user.name', 'T'); git(self.repo, 'config', 'user.email', 't@localhost')
        (self.repo / 'onecrew' / 'v2').mkdir(parents=True)
        (self.repo / 'onecrew' / '__init__.py').write_text(''); (self.repo / 'onecrew' / 'v2' / '__init__.py').write_text('')
        (self.repo / 'onecrew' / 'v2' / 'fixmod.py').write_text('FIXED = True\n')
        (self.repo / 'pyproject.toml').write_text(PYPROJECT.replace('VERSION', VERSION))
        (self.repo / '.gitignore').write_text('.onecrew/\n')
        (self.repo / 'a.txt').write_text('fixed code\n'); git(self.repo, 'add', '.'); git(self.repo, 'commit', '-q', '-m', 'fix')
        self.fix = Ledger(self.repo, self.ledger.state_root)
        self.fix_plan(self.grant)
        self.runtime = FakeRuntime(self)
        self.real = {name: getattr(hotfix(), name) for name in ('processes_under', 'platform')}
        for name in ('make_venv', 'pip_install', 'identity', 'run_onecrew', 'processes_under', 'event_classes'):
            target = patch.object(hotfix(), name, getattr(self.runtime, name)); target.start(); self.addCleanup(target.stop)
        self.fb = self.new_fb('Node C fails although a.txt is right')

    def new_fb(self, text):
        code, made = self.report('--text', text, '--plan', 'P1')
        self.assertEqual(code, 0, made)
        self.cli('support', 'classify', made['id'], '--class', 'onecrew_runtime', '--basis', 'receipt of node C')
        code, linked = self.cli('support', 'link', made['id'], '--plan', 'FIX1', '--project-id', self.fix.project_id)
        self.assertEqual(code, 0, linked)
        return made['id']

    def hook(self, project, exe, state=None):
        settings = project / '.claude' / 'settings.local.json'
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(hook_cli.portable_settings(exe, state or self.ledger.state_root), indent=2), encoding='utf-8')
        where.register_project(project, state or self.ledger.state_root)

    def actor_free(self):
        actor = os.environ.pop('ONECREW_ACTOR', None)
        return contextlib.ExitStack() if actor is None else patch.dict(os.environ, {}, clear=False)

    def fix_plan(self, granted):
        actor = os.environ.pop('ONECREW_ACTOR', None)
        try:
            plans.propose(self.fix, 'FIX1', plan_json(authority={'edit': True, 'commands': True, 'apply_to_project': True,
                                                                 'granted_actions': list(granted)}), 'claude', workflow=True)
            plans.approve(self.fix, 'FIX1', 'owner', 'fixture owner approves the OneCrew fix plan')
            self.verified()
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor

    def verified(self):
        self.assertEqual(verdict.run(self.fix, 'FIX1', 'M1', self.repo)['milestones'][0]['state'], 'passed')

    def commit(self, text, verify=True):
        (self.repo / 'onecrew' / 'v2' / 'fixmod.py').write_text(text)
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-q', '-m', 'change')
        if verify: self.verified()

    def wheel(self, version=VERSION, commit=None, tamper=False, name='pkg'):
        folder = Path(self.temp.name) / name / git(self.repo, 'rev-parse', '--short', 'HEAD'); folder.mkdir(parents=True, exist_ok=True)
        with patch.object(wh, 'REPO', self.repo):
            built, _, _ = wh.build_wheel(folder)
        return built, self.manifest(built, commit, tamper)

    def manifest(self, wheel, commit=None, tamper=False):
        manifest = wheel.parent / 'manifest.json'
        manifest.write_text(json.dumps({'kind': 'fixture-package', 'version': VERSION, 'code_commit': commit or git(self.repo, 'rev-parse', 'HEAD'),
                                        'wheel': {'name': wheel.name, 'sha256': '0' * 64 if tamper else hashlib.sha256(wheel.read_bytes()).hexdigest()}}),
                            encoding='utf-8')
        return manifest

    def owner(self, *args):
        actor = os.environ.pop('ONECREW_ACTOR', None)
        try:
            return self.cli(*args)
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor

    def target(self):
        code, made = self.owner('support', 'target', 'add', '--id', 'lab', '--venv', str(self.old_venv))
        self.assertEqual(code, 0, made)

    def artifact(self, fb=None, **kw):
        wheel, manifest = self.wheel(**kw)
        return self.cli('support', 'artifact', fb or self.fb, '--wheel', str(wheel), '--manifest', str(manifest))

    def ready(self):
        self.target()
        code, made = self.artifact()
        self.assertEqual(code, 0, made)
        return made

    def install(self, fb=None):
        return self.cli('support', 'install', fb or self.fb, '--target', 'lab')

    def new_exe(self, fb=None):
        art = self.support_events('support.artifact')
        art = [a for a in art if a['feedback'] == (fb or self.fb)][-1]
        return str((Path(f'{self.old_venv}-{VERSION}-{art["wheel_sha256"][:8]}') / 'Scripts' / 'onecrew.exe').resolve())

    def settings_exe(self, project=None):
        data = json.loads(((project or self.root) / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
        return {h['command'] for entries in data['hooks'].values() for e in entries for h in e['hooks']}

    def status(self, fb=None):
        return self.cli('support', 'status', fb or self.fb, '--json')[1]

    def root_rows(self):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            events = [tuple(r) for r in conn.execute('SELECT seq, kind, payload FROM events WHERE task_id=? ORDER BY seq', (task,))]
            budget = [tuple(r) for r in conn.execute("SELECT * FROM executions WHERE task_id=?", (task,))]
            deadline = conn.execute('SELECT deadline FROM tasks WHERE id=?', (task,)).fetchone()[0]
        return events, budget, deadline

    def denied(self, reason='fixture: not granted'):
        return patch.object(hotfix().authority, 'decide', lambda *a, **k: {'in_authority': False, 'class': 'U2', 'kind': 'support_install',
                                                                           'q': None, 'reason': reason, 'nodes': []})


class AuthorityTests(S2Fixture):
    grant = ()

    def test_project_edit_grant_does_not_allow_onecrew_fix_or_install(self):
        # also: test_missing_grant_or_budget_blocks_effect_but_prepares_bundle_and_trial, the owner-only and immutable target (S2-R10)
        for markers in ({'CLAUDE_CODE_CHILD_SESSION': '1'}, {'CLAUDECODE': '1'}):
            with patch.dict(os.environ, markers):
                code, refused = self.cli('support', 'target', 'add', '--id', 'lab', '--venv', str(self.old_venv))
                self.assertEqual(code, 2, refused); self.assertIn('refused', refused['error'])
                with self.assertRaises(LedgerError): hotfix().target_add(self.ledger, 'lab', self.old_venv)
        self.assertEqual(self.support_events('support.target'), [])
        code, bad = self.owner('support', 'target', 'add', '--id', 'Lab Box', '--venv', str(self.old_venv))
        self.assertEqual(code, 2, bad)
        self.ready()
        other = Path(self.temp.name) / 'venvs' / 'elsewhere'; (other / 'Scripts').mkdir(parents=True); (other / 'Scripts' / 'onecrew.exe').write_bytes(b'x')
        code, again = self.owner('support', 'target', 'add', '--id', 'lab', '--venv', str(other))
        self.assertEqual(code, 2, again); self.assertIn('immutable', again['error'])
        code, replaced = self.owner('support', 'target', 'add', '--id', 'lab', '--venv', str(other), '--replace')
        self.assertEqual((code, replaced['replaces']['venv']), (0, str(self.old_venv.resolve())))
        self.owner('support', 'target', 'add', '--id', 'lab', '--venv', str(self.old_venv), '--replace')
        code, made = self.install()
        self.assertEqual((code, made['result']), (0, 'blocked_by_authority'), made)
        self.assertIn('support_install:lab', made['reason'])
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})
        self.assertEqual(len(self.runtime.venvs), 1)
        self.assertTrue(Path(self.runtime.venvs[0]).is_relative_to(self.ledger.state_root))
        state = self.status()
        self.assertFalse(state['installed']['value']); self.assertTrue(state['trial_build']['value'])
        self.assertEqual(state['install_blocked']['value'], 'blocked_by_authority')
        code, bundle = self.cli('support', 'bundle', self.fb)
        self.assertEqual(code, 0, bundle)
        code, again = self.install()
        self.assertEqual(again['result'], 'blocked_by_authority')
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)
        self.assertEqual(len(self.runtime.venvs), 1)
        self.assertNotIn(made['result'], ('pass', 'passed', 'switched')); self.assertIn('not a PASS', made['note'])


class BudgetTests(S2Fixture):
    def test_exhausted_budget_blocks_the_install_only(self):
        self.ready()
        with patch('onecrew.v2.internal_plan.ceilings', lambda *a, **k: {'remaining_calls': 0, 'remaining_seconds': 0, 'deadline': '2000-01-01T00:00:00+00:00'}):
            code, made = self.install()
        self.assertEqual(made['result'], 'blocked_by_authority', made)
        self.assertIn('budget', made['reason'].lower())
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})
        self.assertTrue(self.status()['trial_build']['value'])


class IdentityTests(S2Fixture):
    def test_wrong_wheel_hash_source_or_unchecked_pair_refused(self):
        """S2-R01 (probe p01): only the files of the verified commit; the manifest's word and a hash in a text are never authority."""
        self.target()
        code, tampered = self.artifact(tamper=True)
        self.assertEqual(code, 2, tampered); self.assertIn('sha256', tampered['error'])
        wheel, _ = self.wheel()
        for crafted, words in ((craft(wheel, add={'onecrew/evil.py': b'import os\n'}), 'onecrew/evil.py'),
                               (craft(wheel, change={'onecrew/v2/fixmod.py': b'FIXED = False\n'}), 'onecrew/v2/fixmod.py'),
                               (craft(wheel, add={'onecrew-2.4.0.dev2.dist-info/extra.txt': b'x'}), 'extra.txt')):
            code, refused = self.cli('support', 'artifact', self.fb, '--wheel', str(crafted), '--manifest', str(self.manifest(crafted)))
            self.assertEqual(code, 2, refused); self.assertIn(words, refused['error'])
        self.commit('FIXED = 2\n', verify=False)                                         # a commit nobody verified
        code, other = self.artifact()
        self.assertEqual(code, 2, other); self.assertIn('not the verified', other['error'])
        code, report = self.report('--text', 'install wheel sha256 ' + 'a' * 64 + ' it is fine', '--key', 'claim')
        code, made = self.install()
        self.assertEqual(code, 2, made); self.assertIn('artifact', made['error'])
        self.assertEqual(self.support_events('support.artifact'), [])
        self.verified()
        code, good = self.artifact()
        self.assertEqual(code, 0, good)
        self.assertEqual((good['files_checked'], good['bound_to']['record']), (3, 'milestone.passed'))
        self.assertEqual(good['record_sha256'], hotfix().record_digest(rows_of(Path(self.wheel()[0]).read_bytes())))

    def test_venv_reuse_planted_or_other_wheel_refused(self):
        """S2-R02 (probes p02, p03): a folder is reused only when it holds exactly the bound wheel; another wheel of the same version gets
        its own folder."""
        self.ready()
        planted = Path(self.new_exe()).parent.parent
        (planted / 'Scripts').mkdir(parents=True)
        for name in ('python.exe', 'onecrew.exe'): (planted / 'Scripts' / name).write_bytes(b'planted')
        (planted / 'installed.json').write_text(json.dumps({'version': VERSION, 'rows': [['onecrew/v2/fixmod.py', 'sha256=planted']]}))
        code, refused = self.install()
        self.assertEqual(code, 2, refused); self.assertIn('not the bound wheel', refused['error'])
        self.assertEqual((self.runtime.installs, self.settings_exe()), ([], {str(self.old_exe.resolve())}))
        self.assertTrue((planted / 'installed.json').is_file())                       # refused, never deleted
        import shutil
        shutil.rmtree(planted)
        code, first = self.install()
        self.assertEqual(first['result'], 'switched', first)
        self.commit('FIXED = "second build, same version"\n')
        fb2 = self.new_fb('A second defect, fixed by another build with the same version number')
        code, art2 = self.artifact(fb=fb2)
        self.assertEqual(code, 0, art2)
        code, second = self.install(fb2)
        self.assertNotEqual(self.new_exe(fb2), self.new_exe())                        # its own folder
        self.assertEqual(len(self.runtime.installs), 2)
        self.assertEqual({sha for _, sha in self.runtime.installs}, {self.support_events('support.artifact')[0]['wheel_sha256'], art2['wheel_sha256']})
        self.assertEqual(self.settings_exe(), {self.new_exe()})                       # FB1's runtime still runs; FB2 is not "installed"
        self.assertFalse(self.status(fb2)['installed']['value'])


class InstallTests(S2Fixture):
    def test_valid_support_policy_routine_not_reasked(self):
        self.ready()
        before = self.root_rows()
        code, made = self.install()
        self.assertEqual((code, made['result']), (0, 'switched'), made)
        self.assertEqual(self.settings_exe(), {self.new_exe()})
        self.assertTrue(self.old_exe.read_bytes() == b'old')
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)
            fix_root = plans.derive(self.fix, conn, 'FIX1')['task_id']
            decisions = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='decision.recorded'", (fix_root,))]
        self.assertTrue(any('support_install' in json.dumps(d) for d in decisions))
        intents = [e for e in self.support_events('support.install') if e.get('phase') == 'intent']
        self.assertEqual([os.path.normcase(i['file']) for i in intents], [os.path.normcase(str(self.root / '.claude' / 'settings.local.json'))])
        self.assertEqual(self.root_rows(), before)
        self.assertTrue(self.status()['installed']['value'])
        # test_old_root_never_extended: the recheck adds only engine records; budget and deadline stay
        code, rechecked = self.cli('support', 'recheck', self.fb)
        self.assertEqual(code, 0, rechecked)
        events, budget, deadline = self.root_rows()
        self.assertEqual((budget, deadline), before[1:])
        added = [kind for seq, kind, payload in events[len(before[0]):]]
        self.assertIn('node.verification', added)
        self.assertFalse(set(added) & {'budget.group', 'plan.approved', 'plan.amended', 'plan.revised', 'node.resumed', 'plan.closed',
                                       'request.created', 'plan.accepted'}, added)

    def test_scan_other_baseline_grants_no_swap(self):
        self.ready()
        self.runtime.scan_override = lambda args: {'ledger_sha': '0' * 64, 'blocking': {'read': 0, 'continue': 0, 'total': 0}, 'roots': []}
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_by_drill', made); self.assertIn('not of this data', json.dumps(made))
        self.runtime.scan_override = lambda args: {'ledger_sha': self.copy_sha(args), 'blocking': {'read': 1, 'continue': 0, 'total': 1}, 'roots': [],
                                                   'old_version': 'd3120c6'}
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_by_drill', made)
        self.runtime.scan_override = lambda args: {'ledger_sha': self.copy_sha(args), 'blocking': {'read': 0, 'continue': 2, 'total': 2}, 'roots': [],
                                                   'old_version': 'd3120c6'}
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        drill = self.support_events('support.install_prepared')[-1]['drill'][0]
        self.assertEqual((drill['scan']['continue_blocks_baseline'], drill['scan']['grants_switch']), ('d3120c6', False))
        self.assertIn('engine state', {r['command'] for r in drill['reads']})

    def copy_sha(self, args):
        state = Path(args[args.index('--state-root') + 1])
        return hashlib.sha256((state / 'ledger.sqlite3').read_bytes()).hexdigest()

    def test_running_process_unknown_effect_shared_consumer_or_changed_data_blocks_switch(self):
        self.ready()
        # a second consumer with its OWN state root, holding a running attempt
        other, other_state = Path(self.temp.name) / 'second', Path(self.temp.name) / 'second-state'
        other.mkdir(); git(other, 'init', '-q')
        second = Ledger(other, other_state)
        from onecrew import task_intake
        task = task_intake.submit(second, 'Work in the second project', 'second-job', mode='audit')['id']
        migrate(second)
        with second.transaction(write=True) as conn:
            conn.execute("INSERT INTO executions VALUES(?,?,?,?,0,0,0)", (task, '{}', 'r1', 'running'))
            conn.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ('ATT-' + 'e' * 32, task, 'k', '{}', 'h', 1, 'running', 0, None, None,
                                                                                   'now', 'now'))
        self.hook(other, self.old_exe, other_state)
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe', made); self.assertIn('ATT-' + 'e' * 32, json.dumps(made))
        with second.transaction(write=True) as conn:
            conn.execute("UPDATE attempts SET status='settled'")
        self.runtime.processes = None
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe', made); self.assertIn('processes: unknown', json.dumps(made))
        self.runtime.processes = [{'pid': 4242, 'image': str(self.old_venv / 'Scripts' / 'python.exe')}]
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe'); self.assertIn('4242', json.dumps(made))
        self.runtime.processes = []
        with patch.object(hotfix(), 'platform', lambda: 'posix'):                       # the non-Windows path: unknown, refused
            self.assertIsNone(self.real['processes_under'](self.old_venv))
        # an unreadable settings file of a registered project, then a corrupt registry: the consumer is unknown, the switch refused
        third = Path(self.temp.name) / 'third'; third.mkdir(); git(third, 'init', '-q')
        (third / '.claude').mkdir()
        (third / '.claude' / 'settings.local.json').write_text('// a comment the parser refuses\n{}', encoding='utf-8')
        where.register_project(third, self.ledger.state_root)
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe', made); self.assertIn('consumer unknown', json.dumps(made))
        (third / '.claude' / 'settings.local.json').write_text('{}', encoding='utf-8')
        registry = where.registry_file(); saved = registry.read_bytes()
        registry.write_text('{not json', encoding='utf-8')
        code, made = self.install()
        self.assertEqual(made['result'], 'refused_unsafe', made); self.assertIn('registry', json.dumps(made))
        registry.write_bytes(saved)
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
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        self.assertEqual((self.settings_exe(), self.settings_exe(other)), ({self.new_exe()}, {self.new_exe()}))

    def test_independent_branch_keeps_running(self):
        self.ready()
        independent = Path(self.temp.name) / 'independent'; independent.mkdir(); git(independent, 'init', '-q')
        elsewhere = Path(self.temp.name) / 'venvs' / 'other' / 'Scripts'; elsewhere.mkdir(parents=True)
        (elsewhere / 'onecrew.exe').write_bytes(b'other')
        self.hook(independent, elsewhere / 'onecrew.exe')
        code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        self.assertEqual(self.settings_exe(independent), {str((elsewhere / 'onecrew.exe').resolve())})
        self.assertNotIn(os.path.normcase(str(independent.resolve())), {c['project'] for c in made['consumers']})

    def test_crash_between_prepare_install_switch_resume_no_double_effect(self):
        """Also S2-R08 (probe p10: a crash mid-switch, then the grant is gone: the switch is completed under its own decision) and S2-R09
        (a second switch of the same target while one holds the claim is refused; a window violation is recorded, never hidden)."""
        self.ready()
        second = Path(self.temp.name) / 'second'; second.mkdir(); git(second, 'init', '-q')
        self.hook(second, self.old_exe)
        for point in ('after_venv', 'after_prepared'):
            with patch.dict(os.environ, {'ONECREW_SUPPORT_CRASH': point}):
                with self.assertRaises(hotfix().Crash):
                    hotfix().install(self.ledger, self.fb, 'lab')
        with patch.dict(os.environ, {'ONECREW_SUPPORT_CRASH': 'mid_switch'}):
            with self.assertRaises(hotfix().Crash):
                hotfix().install(self.ledger, self.fb, 'lab')
        mixed = (self.settings_exe(), self.settings_exe(second))
        self.assertEqual(sorted(len(x & {self.new_exe()}) for x in mixed), [0, 1])          # one switched, one not
        state = self.status()
        self.assertTrue(state['partially_switched']['value']); self.assertFalse(state['installed']['value'])
        with self.denied('the fix plan was accepted meanwhile'):
            code, made = self.install()
        self.assertEqual(made['result'], 'switched', made)
        self.assertIn('completing an interrupted switch', json.dumps(self.support_events('support.install_prepared')[-1]['authority']))
        code, again = self.install()
        self.assertTrue(again.get('already'))
        self.assertEqual(len(self.runtime.venvs), 1); self.assertEqual(len(self.runtime.installs), 1)
        self.assertEqual(len([e for e in self.support_events('support.install') if e.get('result') == 'switched']), 1)
        self.assertEqual((self.settings_exe(), self.settings_exe(second)), ({self.new_exe()}, {self.new_exe()}))
        self.assertFalse(self.status()['partially_switched']['value'])
        # S2-R09: a second feedback's install inside the claimed window of a running one is refused
        fb2 = self.new_fb('another report for the same target')
        self.cli('support', 'artifact', fb2, '--wheel', str(self.wheel()[0]), '--manifest', str(self.manifest(self.wheel()[0])))
        self.cli('support', 'rollback', self.fb)
        inside = {}
        real = hotfix().safe_point
        def during(*args, **kwargs):
            try:
                hotfix().install(self.ledger, fb2, 'lab')
            except LedgerError as error:
                inside['error'] = str(error)
            return real(*args, **kwargs)
        with patch.object(hotfix(), 'safe_point', during):
            code, made = self.install()
        self.assertIn('in progress', inside.get('error', ''))
        # a window violation: an attempt starts while the hooks are repointed
        self.cli('support', 'rollback', self.fb)
        realpoint = hotfix().repoint
        def racing(*args, **kwargs):
            done = realpoint(*args, **kwargs)
            with self.ledger.transaction(write=True) as conn:
                conn.execute("UPDATE attempts SET status='running', updated_at='later'")
            return done
        with patch.object(hotfix(), 'repoint', racing):
            code, made = self.install()
        self.assertEqual(made['result'], 'switch_window_violation', made)
        self.assertTrue(self.status()['still_blocked']['value'])
        code, refused = self.cli('support', 'recheck', self.fb)
        self.assertEqual(code, 2, refused)

    def test_unreadable_by_old_refuses_rollback_and_keeps_new_ledger(self):
        """Also S2-R03 (probe p04), S2-R04 (probe p05), S2-R06 and the notice of a re-install (S1-R22)."""
        self.ready()
        self.install()
        self.cli('support', 'recheck', self.fb)
        self.assertTrue(self.status()['verified_at_target']['value'])
        for markers in ({'CLAUDE_CODE_CHILD_SESSION': '1'}, {'CLAUDECODE': '1'}):
            with patch.dict(os.environ, markers):
                code, refused = self.cli('support', 'rollback', self.fb)
            self.assertEqual(code, 2, refused); self.assertIn('refused', refused['error'])
        with self.denied():
            code, blocked = self.owner('support', 'rollback', self.fb)
        self.assertEqual(blocked['result'], 'blocked_by_authority', blocked)
        before = self.others()
        self.runtime.old_reader_ok = False
        code, made = self.owner('support', 'rollback', self.fb)
        self.assertEqual((code, made['result']), (0, 'refused'), made); self.assertIn('old reader', made['reason'])
        self.runtime.old_reader_ok = True
        self.runtime.old_scan = lambda args: {'ledger_sha': self.copy_sha(args), 'blocking': {'read': 1, 'continue': 0, 'total': 1}}
        code, made = self.owner('support', 'rollback', self.fb)
        self.assertEqual(made['result'], 'refused'); self.assertIn('read block', json.dumps(made))
        self.runtime.old_scan = None
        self.runtime.unknown_kinds = {'node.verification'}                             # written by the recheck after the switch
        code, made = self.owner('support', 'rollback', self.fb)
        self.assertEqual(made['result'], 'refused'); self.assertIn('node.verification', json.dumps(made))
        self.runtime.unknown_kinds = set()
        self.assertEqual(self.settings_exe(), {self.new_exe()})
        with patch.dict(os.environ, {'ONECREW_SUPPORT_CRASH': 'rollback_after_repoint'}):
            with self.assertRaises(hotfix().Crash):
                self.owner('support', 'rollback', self.fb)
        code, back = self.owner('support', 'rollback', self.fb)
        self.assertEqual(back['result'], 'rolled_back', back)
        self.assertIn('continuation not proven', back['proven'])
        self.assertEqual(len([e for e in self.support_events('support.install') if e.get('result') == 'rolled_back']), 1)
        self.assertEqual(self.settings_exe(), {str(self.old_exe.resolve())})
        state = self.status()
        self.assertFalse(state['installed']['value']); self.assertTrue(state['rolled_back']['value'])
        self.assertFalse(state['verified_at_target']['value']); self.assertFalse(state['verified_at_target']['history']['current'])
        self.assertTrue(state['still_blocked']['value'])
        self.assertEqual(self.cli('support', 'resume', self.fb)[0], 2); self.assertEqual(self.cli('support', 'learn', self.fb, '--text', 'x')[0], 2)
        code, again = self.install()
        self.assertEqual(again['result'], 'switched', again)
        installed = [n for n in notification_cli.pull(self.ledger, 'chat')['notifications'] if n.get('feedback') == self.fb and
                     str(n.get('status')).startswith('installed')]
        self.assertEqual(len({n['id'] for n in installed}), 2, installed)

    def test_recheck_on_target_or_named_copy_only(self):
        self.ready()
        # test_green_patch_tests_are_not_installed_or_fixed_or_accepted
        state = self.status()
        self.assertFalse(state['installed']['value']); self.assertFalse(state['verified_at_target']['value'])
        self.assertFalse(state['user_confirmed']['value']); self.assertEqual(state['still_blocked']['value'], True)
        self.assertEqual(self.support_events('support.artifact')[0]['bound_to']['record'], 'milestone.passed')
        code, refused = self.cli('support', 'recheck', self.fb)
        self.assertEqual(code, 2, refused)
        Snapshots = __import__('onecrew.snapshots', fromlist=['x']).Snapshots
        big = Snapshots(self.ledger.state_root).blob(os.urandom(1_500_000))            # an unrelated blob: never copied by a drill
        with self.denied():
            self.install()
        drill = self.support_events('support.install_prepared')[-1]['drill'][0]
        self.assertLess(drill['copy_bytes'], 1_500_000); self.assertFalse(Path(drill['copy']).exists())
        events_before = self.root_rows()[0]
        code, on_copy = self.cli('support', 'recheck', self.fb, '--keep')
        self.assertEqual((code, on_copy['environment'], on_copy['result']), (0, 'copy', 'pass'), on_copy)
        self.assertEqual(self.root_rows()[0], events_before)
        self.assertFalse(self.status()['verified_at_target']['value'])
        code, cleaned = self.cli('support', 'cleanup')
        self.assertEqual(code, 0, cleaned); self.assertTrue(cleaned['removed']); self.assertFalse(Path(on_copy['state_root']).exists())
        self.install()
        with patch.dict(os.environ, {'ONECREW_SUPPORT_CRASH': 'recheck_after_verify'}):
            with self.assertRaises(hotfix().Crash):
                hotfix().recheck(self.ledger, self.fb)
        code, on_target = self.cli('support', 'recheck', self.fb)
        self.assertEqual((on_target['environment'], on_target['result']), ('target', 'pass'), on_target)
        events = [k for _, k, _ in self.root_rows()[0][len(events_before):]]
        self.assertEqual(events.count('node.verification'), 1)                         # the interrupted run's verification adopted, not repeated
        self.assertTrue(self.status()['verified_at_target']['value']); self.assertFalse(self.status()['still_blocked']['value'])
        body = json.loads(self.store.read_blob(on_target['receipt']))
        self.assertEqual((body['kind'], body['node'], body['result']), ('node-verifier-receipt', 'C', 'pass'))

    def test_lesson_has_source_and_certainty_recurrence_links_history(self):
        """Also S2-R05 (probe p07), a held node without the owner's answer, and the resume crash point."""
        self.ready()
        code, early = self.cli('support', 'learn', self.fb, '--text', 'Verifier env leaked a variable')
        self.assertEqual(code, 2, early)
        self.assertEqual(self.cli('support', 'resume', self.fb)[0], 2)
        self.install()
        self.cli('support', 'recheck', self.fb)
        with patch.dict(os.environ, {'ONECREW_SUPPORT_CRASH': 'resume_before_record'}):
            with self.assertRaises(hotfix().Crash):
                hotfix().resume(self.ledger, self.fb)
        code, resumed = self.cli('support', 'resume', self.fb)
        self.assertEqual((code, resumed['mode']), (0, 'not_held'), resumed)
        self.assertFalse(resumed['budget_reset']); self.assertFalse(resumed['grants_authority'])
        self.assertEqual(len(self.support_events('support.resumed')), 1)
        code, lesson = self.cli('support', 'learn', self.fb, '--text', 'The verifier environment of 2.4.0.dev1 leaked a variable into checks')
        self.assertEqual(code, 0, lesson)
        code, twice = self.cli('support', 'learn', self.fb, '--text', 'again')
        self.assertFalse(twice['recorded'])
        from onecrew.v2 import knowledge
        found = [r for r in knowledge.records(self.fix) if 'leaked a variable' in r['text']]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['evidence']['cause'], 'not_established'); self.assertEqual(found[0]['evidence']['status'], 'verified')
        self.assertEqual(lesson['root'], 'plan-ns:FIX1')
        # S2-R05: the identical text after the fix passed is a NEW feedback that names the old one; another version, another image: new
        code, again = self.report('--text', 'Node C fails although a.txt is right', '--plan', 'P1')
        self.assertNotEqual(again['id'], self.fb); self.assertFalse(again['duplicate']); self.assertEqual(again['recurrence_of'], [self.fb])
        from onecrew.v2 import support
        probe = support.runtime_probe()
        with patch.object(support, 'runtime_probe', lambda *a, **k: dict(probe, dist_version='9.9.9')):
            code, other = self.report('--text', 'Node C fails although a.txt is right', '--plan', 'P1')
        self.assertNotIn(other['id'], (self.fb, again['id'])); self.assertIn(self.fb, other['same_text_other_runtime'])
        one, two = Path(self.temp.name) / 'a.png', Path(self.temp.name) / 'b.png'; one.write_bytes(b'one'); two.write_bytes(b'two')
        code, a = self.report('--text', 'screen is blank', '--image', str(one))
        code, b = self.report('--text', 'screen is blank', '--image', str(two))
        self.assertEqual(code, 0, b); self.assertNotEqual(a['id'], b['id'])
        # a held node: resume never answers for the owner
        view = self.engine.state(self.ledger, 'P1')
        record = view['nodes']['C']
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, view['root'], 'node.held', {'node': 'C', 'generation': record['generation'],
                                                                      'internal_revision': view['internal_revision'], 'reason': 'fixture hold'})
        code, held = self.cli('support', 'resume', self.fb)
        self.assertEqual(code, 2, held); self.assertIn('held without a workflow hold question', held['error'])
        self.ledger.create_request(view['root'], 'wfhold-fixture', {'schema_version': 1, 'question': 'Continue node C?', 'reason': 'fixture',
            'impact': 'C only', 'options': [{'id': 'continue', 'label': 'Continue'}, {'id': 'stop', 'label': 'Stop'}], 'recommendation': 'continue',
            'action': {'type': 'v2.workflow_hold', 'parameters': {'affected': ['C'], 'generations': {'C': record['generation']}}}})
        code, waiting = self.cli('support', 'resume', self.fb)
        self.assertEqual(code, 2, waiting); self.assertIn('Waiting for the owner', waiting['error'])
