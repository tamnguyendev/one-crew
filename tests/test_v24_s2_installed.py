"""2.4-S2 end to end with REAL wheels and venvs, outside the checkout (ROADMAP-DESIGN §7, S2/SF-04 and the packaging row).

Two wheels are built from copies of this checkout (tests/wf_wheel.build_wheel with REPO pointed at the copy):
  * "prod" 2.4.0.dev1 with a deliberate runtime defect: its command verifier leaks ONECREW_FIXTURE_DEFECT into the check environment;
  * the hotfix 2.4.0.dev2 (this checkout's code, version bumped).
The prod venv runs the customer's root P1: node C writes the right file, but its check fails because of the defect (a real failing
node.verification). The user reports it once; the OneCrew project (another git repo) has fix plan FIX1, approved with
granted_actions ['support_install:lab'], whose milestone passed on the committed tree. Then, all through the INSTALLED prod `onecrew`:
target add (owner) -> classify -> link -> artifact (wheel bytes + manifest bound to FIX1's verified tree) -> install (a NEW venv beside the
prod one, drill on a copy, safe point, hooks repointed) -> recheck (the original check, run by the new runtime at the target: pass) -> status.
The new venv is created by the product itself. Module origins of the new venv are checked with boundary.violations.

Codex review r1 (D:/OneCrewRuns/v24/codex-r1/plan.md): F1, REAL runtime with fixture tampering: the product's own new venv (left by an
install refused for an unreadable registry) gets one file changed with its installed RECORD kept -> the reuse path refuses before any
repoint; restored -> reused and switched. F2, REAL runtime (the old prod executable drills a copy of the real temporary ledger) with FAULT
INJECTION of the write timing: a write on P1 right after the drill -> rollback refused; run again -> rolled_back on data holding the write.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import boundary, hook_cli, where
from tests import wf_wheel as wh
from tests.test_v2_l1 import milestone, plan_json
from tests.test_wf_engine import node

REPO = Path(__file__).resolve().parents[1]
DEFECT = "return dict(env, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')"


def tree_copy(into, version=None, defect=False):
    """The files the wheel builder reads (pyproject + onecrew/), optionally with another version or the verifier defect."""
    shutil.copytree(REPO / 'onecrew', into / 'onecrew', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.onecrew'))
    text = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
    if version:                                # the hotfix wheel always gets its own version, whatever this checkout's version is
        text, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', text, count=1)
        assert count == 1, 'pyproject.toml has no version line'
    (into / 'pyproject.toml').write_text(text, encoding='utf-8')
    if defect:
        command = into / 'onecrew' / 'v2' / 'verifiers' / 'command.py'
        source = command.read_text(encoding='utf-8')
        assert source.count(DEFECT) == 1
        command.write_text(source.replace(DEFECT, "return dict(env, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', ONECREW_FIXTURE_DEFECT='1')"),
                           encoding='utf-8')
    return into


def build(runs, name, repo=False, **kw):
    source = tree_copy(runs / ('src-' + name), **kw)
    if repo:                                  # S2-R01: the hotfix wheel is built from a commit of the OneCrew repository it is bound to
        (source / 'a.txt').write_text('the fix\n')
        for args in (('init', '-q'), ('config', 'user.name', 'T'), ('config', 'user.email', 't@localhost'), ('add', '-A'), ('commit', '-qm', 'the fix')):
            subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
    out = runs / ('wheel-' + name); out.mkdir()
    with patch.object(wh, 'REPO', source):
        wheel, version, _ = wh.build_wheel(out)
    return (wheel, version, source) if repo else (wheel, version)


PROD = r'''
import json, os, subprocess, sys
from pathlib import Path
from onecrew.ledger import Ledger, canonical
from onecrew.snapshots import Snapshots
from onecrew.control_core import migrate
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import plan, engine, internal_plan, verdict
root, state, repo = Path(PROJECT), Path(STATE), Path(REPOX)
def git(where, *args): return subprocess.run(['git', '-C', str(where), *args], check=True, capture_output=True, text=True).stdout.strip()
root.mkdir()
git(root, 'init', '-q'); git(root, 'config', 'user.name', 'T'); git(root, 'config', 'user.email', 't@localhost')
(root / 'a.txt').write_text('base\n'); git(root, 'add', '.'); git(root, 'commit', '-qm', 'base')
ledger = Ledger(root, state)
caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
plan.propose(ledger, 'P1', json.loads(CONTRACT), 'codex', workflow=True, capabilities=caps)
plan.approve(ledger, 'P1', 'owner', 'fixture owner approves the customer root')
fix = Ledger(repo, state)
plan.propose(fix, 'FIX1', json.loads(FIXPLAN), 'claude', workflow=True)
plan.approve(fix, 'FIX1', 'owner', 'fixture owner approves the OneCrew fix plan and its install grant')
assert verdict.run(fix, 'FIX1', 'M1', repo)['milestones'][0]['state'] == 'passed'
os.environ['ONECREW_ACTOR'] = 'codex'
migrate(ledger)
internal_plan.revise(ledger, 'P1', json.loads(NODES), reason='one producer and the integration', evidence=['a.txt:1'])
store = Snapshots(ledger.state_root)
def execute(ledger, control, task, item, attempt):
    control.launched(attempt['id'], attempt['generation'], {'fixture': True})
    artifact = store.overlay(store.capture(root, ['a.txt']), {'a.txt': b'candidate\n'}, ['a.txt'])
    receipt = store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
    control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
    return {'artifact': artifact, 'receipt': receipt}
from onecrew.control_core import Control
assert engine.step(ledger, 'P1', execute, control=Control(ledger))['state'] == 'produced'
result = engine.verify(ledger, 'P1', 'C', CandidateChecker(ledger, 'P1'))['result']
Path(OUT).write_text(json.dumps({'first_verify': result, 'fix_project_id': fix.project_id, 'head': git(repo, 'rev-parse', 'HEAD')}))
'''

STATUS = r'''
import contextlib, io, json
from onecrew.v2.cli import main
out = io.StringIO()
with contextlib.redirect_stdout(out): code = main(['--project', PROJECT, '--state-root', STATE, 'support', 'status', FB, '--json'])
assert code == 0, out.getvalue()
'''


class InstalledS2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = Path(wh._runs())
        cls.prod_wheel, _ = build(cls.runs, 'prod', defect=True)
        cls.fix_wheel, cls.fix_version, cls.fix_repo = build(cls.runs, 'fix', repo=True, version='2.4.0.dev2')
        cls.prod_python = wh.make_venv(cls.runs / 'venvs prod')
        wh.install(cls.prod_python, cls.prod_wheel)
        cls.prod_venv = cls.prod_python.parent.parent
        cls.prod_exe = cls.prod_python.parent / 'onecrew.exe'

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def env(self, base):
        drop = {'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'PYTHONUTF8', 'PYTHONIOENCODING',
                'ONECREW_DESKTOP_HOME', 'ONECREW_FIXTURE_DEFECT'}
        env = {k: v for k, v in os.environ.items() if k.upper() not in drop}
        for name in ('localappdata', 'appdata', 'temp'): (base / name).mkdir(exist_ok=True)
        env.update(LOCALAPPDATA=str(base / 'localappdata'), APPDATA=str(base / 'appdata'), TEMP=str(base / 'temp'), TMP=str(base / 'temp'),
                   ONECREW_ACTOR='codex')
        return env

    def run_prod(self, *args):
        done = subprocess.run([str(self.prod_exe), '--project', str(self.project), '--state-root', str(self.state), 'support', *args],
                              capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=self.cwd, env=self.environment)
        try:
            return done.returncode, json.loads(done.stdout)
        except ValueError:
            return done.returncode, done.stdout + done.stderr

    def test_s2_chain_from_the_installed_runtime_outside_the_checkout(self):
        base = self.runs / 'chain'; base.mkdir()
        self.cwd = base / 'cwd'; self.cwd.mkdir()
        self.project, self.state, repo = base / 'customer', base / 'state', self.fix_repo
        self.environment = self.env(base)
        check = [sys.executable, '-c', 'import os; from pathlib import Path; assert Path("a.txt").read_text() == "candidate\\n"; '
                                       'assert "ONECREW_FIXTURE_DEFECT" not in os.environ, "the runtime leaked a variable"; print("candidate tested")']
        contract = plan_json(milestones=[milestone(argv=check)], authority={
            'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True,
            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        nodes = [node('C'), node('I', ['C'], integration=True, write=())]
        for item in nodes: item['checks'] = [{'id': 'M1', 'spec': 'The exact approved root command M1'}]
        fix_plan = plan_json(authority={'edit': True, 'commands': True, 'granted_actions': ['support_install:lab']})
        out = base / 'prod.json'
        body = (PROD.replace('PROJECT', repr(str(self.project))).replace('STATE', repr(str(self.state))).replace('REPOX', repr(str(repo)))
                .replace('CONTRACT', repr(json.dumps(contract))).replace('FIXPLAN', repr(json.dumps(fix_plan)))
                .replace('NODES', repr(json.dumps(nodes))).replace('OUT', repr(str(out))))
        env = dict(self.environment); env.pop('ONECREW_ACTOR')
        dump, tail = wh.run_case(self.prod_python, body, env_extra=env, cwd=self.cwd)
        self.assertIsNotNone(dump, tail)
        prod = json.loads(out.read_text())
        self.assertEqual(prod['first_verify'], 'fail')                              # the defect of the prod runtime
        # the prod venv runs this project's hooks (as `onecrew init` writes them) and the registry knows the project
        (self.project / '.claude').mkdir()
        (self.project / '.claude' / 'settings.local.json').write_text(json.dumps(hook_cli.portable_settings(self.prod_exe, self.state)), encoding='utf-8')
        with patch.dict(os.environ, {'LOCALAPPDATA': self.environment['LOCALAPPDATA']}):
            where.register_project(self.project, self.state)
        code, made = self.run_prod('report', '--text', 'Node C fails although a.txt is right', '--plan', 'P1', '--json')
        self.assertEqual(code, 0, made); fb = made['id']
        self.assertEqual(made['refs']['node'], 'C')
        env = dict(self.environment); env.pop('ONECREW_ACTOR')
        done = subprocess.run([str(self.prod_exe), '--project', str(self.project), '--state-root', str(self.state), 'support', 'target', 'add',
                               '--id', 'lab', '--venv', str(self.prod_venv)], capture_output=True, text=True, cwd=self.cwd, env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.run_prod('classify', fb, '--class', 'onecrew_runtime', '--basis', 'node C receipt')[0], 0)
        code, linked = self.run_prod('link', fb, '--plan', 'FIX1', '--project-id', prod['fix_project_id'])
        self.assertEqual(code, 0, linked)
        manifest = base / 'manifest.json'
        manifest.write_text(json.dumps({'kind': 'v24-milestone-package', 'version': self.fix_version, 'code_commit': prod['head'],
                                        'wheel': {'name': self.fix_wheel.name, 'sha256': hashlib.sha256(self.fix_wheel.read_bytes()).hexdigest()}}))
        code, artifact = self.run_prod('artifact', fb, '--wheel', str(self.fix_wheel), '--manifest', str(manifest))
        self.assertEqual(code, 0, artifact)
        self.assertGreater(artifact['files_checked'], 100)                        # every shipped file equals the bound commit
        # Codex r1 F1, REAL runtime: the product creates the new venv; an install refused for another reason (an unreadable hook
        # registry) leaves that venv in place. A file of it is then changed with its installed RECORD kept (fixture tampering): the
        # reuse path must refuse before any repoint; with the bytes restored the same venv is reused and switched.
        registry = Path(self.environment['LOCALAPPDATA']) / 'OneCrew' / 'hook-projects.json'
        saved = registry.read_bytes()
        registry.write_text('{not json', encoding='utf-8')
        code, first = self.run_prod('install', fb, '--target', 'lab')
        registry.write_bytes(saved)
        self.assertEqual((code, first['result']), (0, 'refused_unsafe'), first)
        made = Path(first['new_venv'])
        self.assertTrue((made / 'Scripts' / 'onecrew.exe').is_file())
        tampered = made / 'Lib' / 'site-packages' / 'onecrew' / 'v2' / 'diagnostics.py'
        record = next((made / 'Lib' / 'site-packages').glob('onecrew-*.dist-info')) / 'RECORD'
        original, record_bytes = tampered.read_bytes(), record.read_bytes()
        tampered.write_bytes(original + b'\n# isolated corruption probe\n')
        code, refused = self.run_prod('install', fb, '--target', 'lab')
        self.assertEqual(code, 2, refused); self.assertIn('not the bound wheel', json.dumps(refused))
        self.assertIn('onecrew/v2/diagnostics.py', json.dumps(refused))
        hooks = json.loads((self.project / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
        self.assertEqual({h['command'] for entries in hooks['hooks'].values() for e in entries for h in e['hooks']}, {str(self.prod_exe.resolve())})
        self.assertEqual(record.read_bytes(), record_bytes)
        tampered.write_bytes(original)
        code, installed = self.run_prod('install', fb, '--target', 'lab')
        self.assertEqual(code, 0, installed)
        self.assertEqual(installed['result'], 'switched', json.dumps(installed)[:3000])
        new_venv = Path(installed['new_venv'])
        self.assertEqual(new_venv.parent, self.prod_venv.parent)                     # side by side, a new folder
        self.assertEqual(installed['identity']['version'], '2.4.0.dev2')
        self.assertNotEqual(installed['processes'], 'unknown', installed)
        hooks = json.loads((self.project / '.claude' / 'settings.local.json').read_text(encoding='utf-8'))
        commands = {h['command'] for entries in hooks['hooks'].values() for e in entries for h in e['hooks']}
        self.assertEqual(commands, {str((new_venv / 'Scripts' / 'onecrew.exe').resolve())})
        code, rechecked = self.run_prod('recheck', fb)
        self.assertEqual(code, 0, rechecked)
        self.assertEqual((rechecked['environment'], rechecked['result'], rechecked['version']), ('target', 'pass', '2.4.0.dev2'), rechecked)
        code, state = self.run_prod('status', fb, '--json')
        self.assertTrue(state['installed']['value']); self.assertTrue(state['verified_at_target']['value'])
        self.assertFalse(state['still_blocked']['value']); self.assertFalse(state['user_confirmed']['value'])
        # module origins of the runtime the product installed
        new_python = new_venv / 'Scripts' / 'python.exe'
        ctx = wh.build_ctx(new_python, *self._shipped())
        dump, tail = wh.run_case(new_python, STATUS.replace('PROJECT', repr(str(self.project))).replace('STATE', repr(str(self.state)))
                                 .replace('FB', repr(fb)), env_extra=self.environment, cwd=self.cwd)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], ctx), [], tail)
        self.assertFalse([n for n in dump['end'] if n.split('.')[0] in ('tests', 'wfkit')])
        for name, info in dump['end'].items():
            if name.startswith('onecrew') and info.get('file'):
                self.assertTrue(Path(info['file']).resolve().is_relative_to(new_venv.resolve()), (name, info['file']))
        self.rollback_window(fb, new_venv)

    def rollback_window(self, fb, new_venv):
        """Codex r1 F2. REAL runtime: the rollback runs in this process (checkout code) and drives the real old runtime (the prod
        `onecrew` executable) on a copy of the real temporary ledger; FAULT INJECTION: a write on P1 right after that drill. The decision
        must be bound to the drilled data: refused, the hooks stay on the new runtime; run again without the write, the real old runtime
        drills data that holds the write and the hooks go back to the prod venv."""
        from onecrew.v2 import hotfix, plan as plans
        ledger = Ledger(self.project, self.state)
        real = hotfix._read_check
        def drill_then_write(*args, **kwargs):
            done = real(*args, **kwargs)
            with ledger.transaction(write=True) as conn:
                task = plans.derive(ledger, conn, 'P1')['task_id']
                plans.emit(ledger, conn, task, 'notice.exception', {'version': 1, 'category': 'deadline', 'cause': 'fault injection',
                                                                    'reason': 'written after the drill', 'evidence': ['fixture'], 'plan': 'P1'})
            return done
        isolated = {k: self.environment[k] for k in ('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP')}
        settings = self.project / '.claude' / 'settings.local.json'
        commands = lambda: {h['command'] for entries in json.loads(settings.read_text(encoding='utf-8'))['hooks'].values() for e in entries
                            for h in e['hooks']}
        with patch.dict(os.environ, isolated), patch.object(hotfix, '_read_check', drill_then_write):
            refused = hotfix.rollback(ledger, fb)
        self.assertEqual(refused['result'], 'refused', json.dumps(refused)[:3000])
        self.assertIn('changed', json.dumps(refused['problems']))
        self.assertEqual(commands(), {str((new_venv / 'Scripts' / 'onecrew.exe').resolve())})
        with patch.dict(os.environ, isolated):
            back = hotfix.rollback(ledger, fb)
        self.assertEqual(back['result'], 'rolled_back', json.dumps(back)[:3000])
        self.assertIn('notice.exception', json.dumps(back['reader_pair']))       # the real old runtime drilled data holding the write
        self.assertEqual(back['fences']['drilled'], back['fences']['at_switch'])
        self.assertEqual(commands(), {str(self.prod_exe.resolve())})

    def _shipped(self):
        import re
        text = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
        modules = set(re.findall(r'"([\w.]+)"', re.search(r'py-modules\s*=\s*\[(.*?)\]', text, re.S).group(1)))
        packages = set(re.findall(r'"([\w.]+)"', re.search(r'^\s*packages\s*=\s*\[(.*?)\]', text, re.M | re.S).group(1)))
        return modules, packages


if __name__ == '__main__':
    unittest.main()
