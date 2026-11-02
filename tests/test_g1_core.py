"""G1 (OneCrew 2.2): the core + v2 can be installed alone. What the wheel ships imports nothing it does not ship, the Claude CLI is found
without assuming Windows, the default model lives in one module, and the metadata says what the package is.

This file also runs inside python:3.10-slim from a copy of the checkout (docker, no git): it needs nothing but the Python standard library
and the files of the checkout, and it parses pyproject.toml by hand because tomllib came with Python 3.11.
"""
import ast
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
V1_ONLY = ('delivery', 'android', 'solution_', 'native_', 'owned', 'notification', 'desktop_', 'host', 'runner', 'supervisor',
           'work_tools', 'worker_tools', 'workspace_worker', 'workflow', 'consultations', 'conversation', 'review_evidence', 'eval_',
           'jev', 'keeper', 'monitor', 'node_change', 'dart_scan', 'sandbox_gate', 'contain', 'qc_gate', 'budget_policy', 'learning',
           'goal_budget', 'cli')
SHARED_CORES = {'onecrew.notification_core', 'onecrew.desktop_core', 'onecrew.desktop_window_core', 'onecrew.host_status_core'}


def pyproject():
    return (ROOT / 'pyproject.toml').read_text(encoding='utf-8')


def shipped():
    """The module names pyproject lists in tool.setuptools.py-modules (plus the packages those modules live in)."""
    block = re.search(r'py-modules\s*=\s*\[(.*?)\]', pyproject(), re.S).group(1)
    modules = re.findall(r'"([\w.]+)"', block)
    packages = {'.'.join(m.split('.')[:i]) for m in modules for i in range(1, len(m.split('.')))}
    return set(modules), packages


def source(name):
    base = ROOT.joinpath(*name.split('.'))
    return base.with_suffix('.py') if base.with_suffix('.py').is_file() else base / '__init__.py'


def imports(name):
    """Every onecrew module the source of `name` imports, lazy imports in functions included: [(module, line)]."""
    path = source(name)
    package = name if path.name == '__init__.py' else name.rsplit('.', 1)[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split('.')
                target = '.'.join(parts[:len(parts) - (node.level - 1)] + ([node.module] if node.module else []))
            else:
                target = node.module or ''
            if not target.startswith('onecrew'): continue
            found.append((target, node.lineno))
            found += [(target + '.' + a.name, node.lineno) for a in node.names if source_exists(target + '.' + a.name)]
        elif isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names if a.name.startswith('onecrew')]
    return found


def source_exists(name):
    base = ROOT.joinpath(*name.split('.'))
    return base.with_suffix('.py').is_file() or (base / '__init__.py').is_file()


class ClosureTests(unittest.TestCase):
    def test_every_listed_module_exists(self):
        modules, _ = shipped()
        self.assertEqual([m for m in sorted(modules) if not source(m).is_file()], [])

    def test_the_closure_of_core_and_v2_stays_inside_the_list(self):
        modules, packages = shipped()
        known = modules | packages
        self.assertIn('onecrew.v2.plan', modules)
        outside = sorted(f'{m}:{line} -> {target}' for m in sorted(modules) for target, line in imports(m) if target not in known)
        self.assertEqual(outside, [], 'a shipped module imports (possibly lazily) a module the wheel does not ship')

    def test_no_v1_only_module_is_shipped(self):
        modules, _ = shipped()
        leaked = sorted(m for m in modules if m.split('.')[1].startswith(V1_ONLY)
                        and not m.startswith('onecrew.v2.') and m not in SHARED_CORES)
        self.assertEqual(leaked, [])

    def test_every_v2_module_is_shipped(self):
        modules, _ = shipped()
        on_disk = {'onecrew.v2.' + p.stem for p in (ROOT / 'onecrew' / 'v2').glob('*.py') if p.stem != '__init__'}
        on_disk |= {'onecrew.v2.verifiers.' + p.stem for p in (ROOT / 'onecrew' / 'v2' / 'verifiers').glob('*.py') if p.stem != '__init__'}
        self.assertEqual(sorted(on_disk - modules), [])

    def test_every_shipped_module_imports_alone(self):
        """Only the shipped files, in a directory of their own, in an isolated interpreter: each module imports."""
        modules, packages = shipped()
        with tempfile.TemporaryDirectory() as tmp:
            for name in sorted(modules | packages):
                target = Path(tmp).joinpath(*name.split('.'))
                if name in packages:
                    target.mkdir(parents=True, exist_ok=True)
                    target = target / '__init__.py'
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target = target.with_suffix('.py')
                target.write_text(source(name).read_text(encoding='utf-8'), encoding='utf-8')
            code = ('import importlib, sys\n'
                    f'sys.path.insert(0, {tmp!r})\n'
                    f'bad = []\nfor name in {sorted(modules | packages)!r}:\n'
                    '    try: importlib.import_module(name)\n'
                    '    except Exception as error: bad.append(name + ": " + repr(error)[:200])\n'
                    'print("\\n".join(bad)); sys.exit(1 if bad else 0)\n')
            done = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace')
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class ClaudeCliTests(unittest.TestCase):
    def setUp(self):
        from onecrew.v2 import claude_cli
        self.cli = claude_cli

    def find(self, osname, home, present, env, which=None):
        return self.cli.cli_argv(env, osname=osname, home=home, which=which or (lambda name, path: None), exists=lambda place: place in present)

    def test_path_comes_first(self):
        seen = []
        found = self.find('posix', '/home/u', {'/home/u/.local/bin/claude'}, {'PATH': '/x:/y'}, which=lambda name, path: seen.append((name, path)) or '/x/claude')
        self.assertEqual((found, seen), (['/x/claude'], [('claude', '/x:/y')]))

    def test_posix_fallbacks_in_order(self):
        places = self.cli.search_places({'NPM_CONFIG_PREFIX': '/opt/npm'}, 'posix', '/home/u')
        self.assertEqual(places[:2], ['/home/u/.local/bin/claude', '/home/u/.claude/local/claude'])
        self.assertIn('/opt/npm/bin/claude', places)
        self.assertIn('/home/u/.npm-global/bin/claude', places)
        self.assertTrue(all(p.startswith('/') and '\\' not in p and not p.endswith('.exe') for p in places), places)
        self.assertEqual(self.find('posix', '/home/u', {'/home/u/.local/bin/claude'}, {}), ['/home/u/.local/bin/claude'])
        self.assertEqual(self.find('posix', '/home/u', {'/opt/npm/bin/claude'}, {'NPM_CONFIG_PREFIX': '/opt/npm'}), ['/opt/npm/bin/claude'])
        self.assertEqual(self.find('posix', '/home/u', {'/usr/local/bin/claude'}, {}), ['/usr/local/bin/claude'])

    def test_windows_fallbacks_in_order(self):
        home = 'C:\\Users\\u'
        places = self.cli.search_places({'APPDATA': 'C:\\Users\\u\\AppData\\Roaming'}, 'nt', home)
        self.assertEqual(places[0], 'C:\\Users\\u\\.local\\bin\\claude.exe')
        self.assertIn('C:\\Users\\u\\AppData\\Roaming\\npm\\claude.cmd', places)
        self.assertTrue(all(p.startswith('C:\\') and '/' not in p for p in places), places)
        self.assertEqual(self.find('nt', home, {'C:\\Users\\u\\.local\\bin\\claude.exe'}, {}), ['C:\\Users\\u\\.local\\bin\\claude.exe'])
        self.assertEqual(self.find('nt', home, {'C:\\Users\\u\\AppData\\Roaming\\npm\\claude.cmd'}, {'APPDATA': 'C:\\Users\\u\\AppData\\Roaming'}),
                         ['C:\\Users\\u\\AppData\\Roaming\\npm\\claude.cmd'])
        self.assertEqual(self.find('nt', home, {'C:\\Users\\u\\AppData\\Roaming\\npm\\claude.cmd'}, {}),
                         ['C:\\Users\\u\\AppData\\Roaming\\npm\\claude.cmd'])    # APPDATA unset: the default Roaming folder of the home

    def test_not_found_names_every_place_searched(self):
        from onecrew.ledger import LedgerError
        for osname, home in (('posix', '/home/u'), ('nt', 'C:\\Users\\u')):
            with self.assertRaises(LedgerError) as caught:
                self.find(osname, home, set(), {'PATH': '/nowhere'})
            message = str(caught.exception)
            self.assertIn('PATH', message); self.assertIn('/nowhere', message)
            for place in self.cli.search_places({}, osname, home): self.assertIn(place, message)

    def test_the_reviewer_uses_this_finder(self):
        from onecrew.v2.verifiers import reviewer
        self.assertIs(reviewer.cli_argv, self.cli.cli_argv)

    def test_no_hardcoded_windows_fallback_is_left(self):
        for path in (ROOT / 'onecrew' / 'v2').rglob('*.py'):
            if path.name == 'claude_cli.py': continue
            self.assertNotIn('claude.exe', path.read_text(encoding='utf-8'), path.name)


class DefaultModelTests(unittest.TestCase):
    def test_default_and_override(self):
        from onecrew.v2 import claude_cli
        self.assertEqual(claude_cli.DEFAULT_MODEL, 'claude-opus-5-5')
        self.assertEqual(claude_cli.default_model({}), 'claude-opus-5-5')
        self.assertEqual(claude_cli.default_model({'ONECREW_DEFAULT_MODEL': 'claude-sonnet-5-5'}), 'claude-sonnet-5-5')
        self.assertEqual(claude_cli.default_model({'ONECREW_DEFAULT_MODEL': '  '}), 'claude-opus-5-5')
        with patch.dict(os.environ, {'ONECREW_DEFAULT_MODEL': 'claude-haiku-5-5'}):
            self.assertEqual(claude_cli.default_model(), 'claude-haiku-5-5')

    def test_the_advisor_and_plan_advise_take_it_from_there(self):
        import inspect
        from onecrew.v2 import plan_cli
        from onecrew.v2.verifiers import advisor
        self.assertIsNone(inspect.signature(advisor.advise).parameters['model'].default)
        self.assertFalse(hasattr(advisor, 'DEFAULT_MODEL'))
        parsed = plan_cli._parser().parse_args(['plan', 'advise', 'P1'])
        self.assertIsNone(parsed.model)

    def test_the_model_id_is_written_in_one_module_only(self):
        """Any mention of the default id outside claude_cli (a default, a help text, a message, an example, a docstring, a doc page) is a second
        place that goes stale when the default changes. Tests may name a model; the package and its docs may not."""
        files = list((ROOT / 'onecrew').rglob('*.py')) + list((ROOT / 'docs').rglob('*.md')) + [ROOT / 'pyproject.toml']
        holders = sorted(str(p.relative_to(ROOT)).replace('\\', '/') for p in files if 'claude-opus-5-5' in p.read_text(encoding='utf-8', errors='replace'))
        self.assertEqual(holders, ['onecrew/v2/claude_cli.py'])


class PackagingTests(unittest.TestCase):
    def test_metadata(self):
        text = pyproject()
        self.assertRegex(text, r'(?m)^version = "2\.4\.0\.dev\d+(\+[a-z0-9]+)?"$')     # a dev build of the 2.4 line; each milestone package bumps the number; a side slice (OBS-1) carries a local label
        self.assertRegex(text, r'(?m)^name = "onecrew"$')
        self.assertRegex(text, r'(?m)^onecrew = "onecrew\.console:main"$')
        self.assertRegex(text, r'(?m)^dependencies = \[\]$')
        self.assertRegex(text, r'(?m)^requires-python = ">=3\.10"$')
        self.assertNotIn('onecrew.cli:main', text)          # the full v1 router is not what an installed `onecrew` runs

    def test_help_lists_the_three_groups(self):
        from onecrew.v2 import cli
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(['--help'])
        self.assertEqual(code, 0)
        for group in ('plan', 'verdict', 'hook'): self.assertRegex(out.getvalue(), r'(?m)^  ' + group + r'\s')

    def test_an_unknown_group_is_refused_and_says_where_v1_runs(self):
        from onecrew.v2 import cli
        err = io.StringIO()
        with patch('sys.stderr', err):
            code = cli.main(['job', 'submit'])
        self.assertEqual(code, 2); self.assertIn('onecrew_cli.py', err.getvalue())

    def test_plan_digest_through_the_router(self):
        from onecrew.v2 import cli
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'; project.mkdir()
            state = Path(tmp) / 'state'
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(['--project', str(project), '--state-root', str(state), 'plan', 'digest'])
            self.assertEqual((code, 'ledger.sqlite3' in out.getvalue()), (2, True))     # no ledger yet: refused, in JSON, by the v2 code
            from onecrew import task_intake
            from onecrew.ledger import Ledger
            task_intake.submit(Ledger(project, state), 'Anything', 'anything', mode='audit')       # creates the ledger
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(['--project', str(project), '--state-root', str(state), 'plan', 'digest'])
            self.assertEqual(code, 0, out.getvalue())


class AnchorTests(unittest.TestCase):
    """The plan's anchor task goes through task_intake.submit; it writes what the v1 submit wrote."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / 'project'; self.project.mkdir()

    def ledger(self, name):
        from onecrew.ledger import Ledger
        return Ledger(self.project, Path(self.tmp.name) / name)

    def rows(self, ledger):
        db = sqlite3.connect(ledger.path)
        try:
            task = db.execute('SELECT project_id, request_key, revision, payload FROM tasks').fetchall()
            events = db.execute('SELECT kind, payload FROM events ORDER BY seq').fetchall()
        finally:
            db.close()
        return task, events

    def test_core_submit_writes_the_audit_task_and_its_event(self):
        from onecrew import task_intake
        ledger = self.ledger('core')
        view = task_intake.submit(ledger, 'Plan p: a title', 'plan-anchor:p', mode='audit')
        tasks, events = self.rows(ledger)
        self.assertEqual(len(tasks), 1)
        payload = json.loads(tasks[0][3])
        self.assertEqual((payload['owned_execution']['mode'], payload['grant']['permissions'], payload['solution_required']), ('audit', ['discover', 'report'], False))
        self.assertEqual([k for k, _ in events], ['task.submitted'])
        self.assertEqual(json.loads(events[0][1]), {'mode': 'owned_execution', 'request_key': 'plan-anchor:p', 'revision': tasks[0][2]})
        self.assertEqual(view['title'], 'Plan p: a title')

    def test_core_and_v1_submit_write_the_same_rows(self):
        try:
            from onecrew import owned_intake
        except ImportError:
            self.skipTest('v1 is not in this install')
        a, b = self.ledger('core'), self.ledger('v1')
        from onecrew import task_intake
        task_intake.submit(a, 'Plan p: a title', 'plan-anchor:p', mode='audit')
        owned_intake.submit(b, 'Plan p: a title', 'plan-anchor:p', mode='audit')
        (ta, ea), (tb, eb) = self.rows(a), self.rows(b)
        self.assertEqual(ta, tb)
        self.assertEqual(ea, eb)

    def test_core_alone_submits_audit_only(self):
        from onecrew import task_intake
        from onecrew.ledger import LedgerError
        ledger = self.ledger('core')
        for kwargs in ({'mode': 'change'}, {'mode': 'work'}, {'mode': 'audit', 'branch': 'onecrew/x'}, {'mode': 'audit', 'solution_id': 'SOL-1'}):
            with self.assertRaises(LedgerError, msg=str(kwargs)):
                task_intake.submit(ledger, 'Goal', 'k-' + str(len(str(kwargs))), **kwargs)

    def test_the_budget_reads_have_one_source(self):
        from onecrew import budget_core
        names = ('local_current', 'current', 'remaining', 'UNBOUNDED_DEADLINE')
        try:
            from onecrew import budget, delivery_store, goal_budget
        except ImportError:
            self.skipTest('v1 is not in this install')
        for name in names: self.assertIs(getattr(budget, name), getattr(budget_core, name), name)
        for name in ('group', 'cancellation_status'): self.assertIs(getattr(goal_budget, name), getattr(budget_core, name), name)
        for name in ('installed', 'root_id', 'shared'): self.assertIs(getattr(delivery_store, name), getattr(budget_core, name), name)

    def test_the_budget_warning_thresholds_have_one_source(self):
        """Codex round 6 P1-1: watch_policy lives in the shipped budget_core; v1's budget_policy re-exports that same function and v2's
        warning path imports it from the core, never from the v1-only module."""
        from onecrew import budget_core
        self.assertIn('def watch_policy', (ROOT / 'onecrew' / 'budget_core.py').read_text(encoding='utf-8'))
        self.assertNotIn('def watch_policy', (ROOT / 'onecrew' / 'budget_policy.py').read_text(encoding='utf-8'))
        self.assertEqual([t for t, _ in imports('onecrew.v2.estimates') if t.startswith('onecrew.budget_policy')], [])
        try:
            from onecrew import budget_policy
        except ImportError:
            self.skipTest('v1 is not in this install')
        self.assertIs(budget_policy.watch_policy, budget_core.watch_policy)

    def test_the_reviewer_independence_has_one_source(self):
        from onecrew import independence
        try:
            from onecrew import qc_gate
        except ImportError:
            self.skipTest('v1 is not in this install')
        for name in ('NATIVE_REVIEWERS', 'VENDORS', 'author_vendor', 'independence'): self.assertIs(getattr(qc_gate, name), getattr(independence, name), name)


if __name__ == '__main__':
    unittest.main()
