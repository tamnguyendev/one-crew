"""Round 14 (Codex review 28/10 on dev17 b522c24): the `onecrew` executable a user gets from the delivered wheel.

P1: tests/wf_wheel.py wrote its own entry point (`onecrew = onecrew.v2.cli:main`) into every wheel instead of pyproject's [project.scripts]
(`onecrew = onecrew.console:main`, the UTF-8 wrapper since round 10), so the installed executable skipped the wrapper: under cp1252 its
Vietnamese --help died with UnicodeEncodeError and `init` printed '?' (dev16 and dev17 wheels). The builder now writes pyproject's scripts, and a
reused wheel (WF_WHEEL) whose scripts differ from pyproject's is refused.
P2: no check ran the executable pip generates from the wheel under a non-UTF-8 encoding: tests/test_wf_r10_console_utf8.py runs the wrapper from
the checkout, and the package verifier ran every child with PYTHONUTF8=1. The verifier now has three mandatory console steps
(wfkit/package_check.console_checks); the installed cases below run that same function on the wheel installed into a venv outside the checkout,
with the gate's environment (PYTHONPATH on the checkout) as the base it must clean. This module's oracle reads pyproject.toml with tomllib, never
through the builder."""
import base64
import copy
import csv
import hashlib
import io
import os
import shutil
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from wfkit import package_check as pc
import tests.wf_wheel as wh
from tests import test_wf_package_check as base_judge

ROOT = Path(__file__).resolve().parents[1]
GATE_KEYS = ('WF_WHEEL', 'WF_WHEEL_SHA256', 'WF_WHEEL_USED_LOG')


def declared(root=ROOT):
    """pyproject's [project.scripts], read here independently of the builder."""
    return dict(tomllib.loads((Path(root) / 'pyproject.toml').read_text(encoding='utf-8'))['project']['scripts'])


def retarget(src, dst, scripts):
    """A copy of wheel `src` whose dist-info/entry_points.txt declares `scripts` (None: no entry_points.txt), RECORD rewritten to match so pip
    installs it; every other file, onecrew/console.py included, is byte-identical."""
    with zipfile.ZipFile(src) as z:
        files = {n: z.read(n) for n in z.namelist()}
    ep = next(n for n in files if n.endswith('.dist-info/entry_points.txt'))
    rec = next(n for n in files if n.endswith('.dist-info/RECORD'))
    if scripts is None:
        del files[ep]
    else:
        files[ep] = ('[console_scripts]\n' + ''.join(f'{k} = {v}\n' for k, v in scripts.items())).encode()
    rows = []
    for row in csv.reader(io.StringIO(files[rec].decode())):
        if row and row[0] == ep:
            if scripts is None:
                continue
            row = [ep, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(files[ep]).digest()).rstrip(b'=').decode(), str(len(files[ep]))]
        rows.append(row)
    out = io.StringIO(); csv.writer(out).writerows(rows); files[rec] = out.getvalue().encode()
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, data in files.items():
            z.writestr(n, data)
    return Path(dst)


class _Env:
    """Set/clear the gate's wheel variables for one block and restore them after (the gate's used-log must only see the wheel under test)."""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in GATE_KEYS}
        for k in GATE_KEYS:
            os.environ.pop(k, None)
        os.environ.update({k: str(v) for k, v in self.values.items()})

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def _tmp(prefix):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    assert not d.resolve().is_relative_to(ROOT.resolve()), d
    return d


class BuilderFollowsPyprojectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = _tmp('wf r14 build ')
        cls.whl, cls.version, _ = wh.build_wheel(cls.runs)               # honours WF_WHEEL: under the gate this is the gate's wheel

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_a_the_wheel_declares_the_pyproject_scripts(self):
        self.assertEqual(pc.wheel_console_scripts(self.whl), declared())

    def test_b_the_builder_takes_the_scripts_from_the_tree_it_builds(self):
        """A tree whose pyproject names other scripts (another target, a second script, the pre-round-10 target of the dev3 baseline)
        builds a wheel declaring exactly those: the builder holds no entry point of its own."""
        pj = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        current = 'onecrew = "onecrew.console:main"'
        self.assertIn(current, pj)
        cases = {'second script': ('onecrew = "onecrew.console:main"\nonecrew-v2 = "onecrew.v2.cli:main"',
                                   {'onecrew': 'onecrew.console:main', 'onecrew-v2': 'onecrew.v2.cli:main'}),
                 'baseline target': ('onecrew = "onecrew.v2.cli:main"', {'onecrew': 'onecrew.v2.cli:main'})}
        for label, (line, want) in cases.items():
            with self.subTest(label):
                tree = self.runs / ('tree ' + label)
                spec = tomllib.loads(pj)['tool']['setuptools']
                for m in spec['py-modules']:
                    rel = m.replace('.', '/') + '.py'
                    (tree / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / rel, tree / rel)
                for init in ROOT.glob('onecrew/**/__init__.py'):
                    dst = tree / init.relative_to(ROOT); dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(init, dst)
                (tree / 'pyproject.toml').write_text(pj.replace(current, line), encoding='utf-8')
                out = self.runs / ('out ' + label); out.mkdir()
                original = wh.REPO
                with _Env():                                               # build from the tree, nothing recorded as the gate's wheel
                    wh.REPO = tree
                    try:
                        built, _, _ = wh.build_wheel(out)
                    finally:
                        wh.REPO = original
                self.assertEqual(pc.wheel_console_scripts(built), want)

    def test_d_a_reused_wheel_with_other_scripts_is_refused(self):
        """WF_WHEEL (the gate's, a bundle's or a drill's reused wheel) must declare pyproject's scripts; the wrapper module being in the
        wheel does not make a wheel whose entry point skips it acceptable."""
        cases = {'pre-round-10 target': {'onecrew': 'onecrew.v2.cli:main'},
                 'extra script': {**declared(), 'onecrew-v2': 'onecrew.v2.cli:main'},
                 'no entry_points.txt': None}
        for label, scripts in cases.items():
            with self.subTest(label):
                folder = self.runs / ('bad ' + label); folder.mkdir()
                bad = retarget(self.whl, folder / f'onecrew-{self.version}-py3-none-any.whl', scripts)
                with zipfile.ZipFile(bad) as z:
                    self.assertIn('onecrew/console.py', z.namelist())      # the wrapper is shipped; only the entry point is off
                into = self.runs / ('into ' + label); into.mkdir()
                with _Env(WF_WHEEL=bad):
                    with self.assertRaises(RuntimeError) as cm:
                        wh.build_wheel(into)
                self.assertIn('console scripts', str(cm.exception))
                self.assertIn('onecrew.console:main', str(cm.exception))
                self.assertFalse(list(into.glob('*.whl')))                 # refused before anything is copied or logged as used

    def test_d_the_reuse_of_a_matching_wheel_is_unchanged(self):
        into = self.runs / 'into same'; into.mkdir()
        with _Env(WF_WHEEL=self.whl, WF_WHEEL_SHA256=hashlib.sha256(Path(self.whl).read_bytes()).hexdigest()):
            got, version, _ = wh.build_wheel(into)
        self.assertEqual(hashlib.sha256(Path(got).read_bytes()).digest(), hashlib.sha256(Path(self.whl).read_bytes()).digest())
        self.assertEqual(version, self.version)


class InstalledExecutableTests(unittest.TestCase):
    """The executable pip generates from the wheel, run through the verifier's own console_checks (P2 a, b, c, f)."""

    @classmethod
    def setUpClass(cls):
        cls.runs = _tmp('wf r14 console ')                               # a path with spaces, outside the checkout
        cls.whl, _, _ = wh.build_wheel(cls.runs)
        cls.py = wh.make_venv(cls.runs)
        wh.install(cls.py, cls.whl)
        cls.venv = cls.py.parent.parent
        work = cls.runs / 'work'; work.mkdir()
        base = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONPATH=str(ROOT))    # what must NOT reach the console runs
        cls.steps = {sid: (ok, facts) for sid, _, ok, facts in pc.console_checks(cls.venv, cls.py, work, base)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_entry_metadata_and_generated_executable_follow_pyproject(self):
        ok, f = self.steps['console_entry']
        self.assertEqual(f['installed'], declared())
        self.assertEqual(f['launcher'], declared())                       # what the generated executable really imports
        self.assertEqual(f['outside'], {})
        for module in {t.split(':')[0] for t in declared().values()}:
            self.assertTrue(Path(f['origins'][module]).resolve().is_relative_to(self.venv.resolve()), f['origins'])
        self.assertTrue(ok, f)

    def test_a_b_help_in_vietnamese_under_cp1252(self):
        ok, f = self.steps['console_cp1252_help']
        self.assertEqual(f['env'], pc.CONSOLE_ENV['cp1252'])               # set explicitly: the base's PYTHONUTF8/PYTHONIOENCODING are gone
        self.assertNotIn('UnicodeEncodeError', f['stderr_tail'])
        self.assertNotIn('Traceback', f['stderr_tail'])
        self.assertEqual(f['exit'], 0, f['stderr_tail'])
        self.assertTrue(f['utf8_strict'])
        self.assertTrue(f['needles']['help_vi'], f['stdout_tail'])
        self.assertTrue(ok, f)

    def test_c_utf8_control_gives_the_same_bytes(self):
        ok, f = self.steps['console_cp1252_help']
        self.assertEqual(f['utf8_exit'], 0)
        self.assertEqual(f['stdout_sha256'], f['utf8_stdout_sha256'])
        self.assertTrue(f['same_as_utf8'])

    def test_f_init_in_vietnamese_under_cp1252_writes_nothing(self):
        ok, f = self.steps['console_cp1252_init']
        self.assertEqual(f['env'], pc.CONSOLE_ENV['cp1252'])
        self.assertEqual(f['init_exit'], 2, f['stdout_tail'] + f['stderr_tail'])     # no stdin: the question gets no yes, init cancels
        self.assertTrue(f['utf8_strict'], f['stdout_tail'])
        self.assertEqual(f['needles'], {'init_plan': True, 'init_cancelled': True}, f['stdout_tail'])
        self.assertEqual(f['wrote'], [])
        self.assertTrue(ok, f)

    def test_the_console_env_is_built_not_inherited(self):
        home = self.runs / 'h'
        env = pc.console_env({'PATH': 'p', 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONLEGACYWINDOWSSTDIO': '1', 'PYTHONPATH': str(ROOT),
                              'PYTHONHOME': 'x', 'ONECREW_LANG': 'en', 'LOCALAPPDATA': 'real'}, 'cp1252', home)
        self.assertEqual(env, {'PATH': 'p', 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp1252', 'ONECREW_LANG': 'vi', 'LOCALAPPDATA': str(home)})


def _report_with(sid, **facts):
    r = base_judge.good_report()
    step = next(s for s in r['steps'] if s['id'] == sid)
    step.update(copy.deepcopy(facts))
    return r, step


class ConsoleOracleTests(unittest.TestCase):
    """The judge recomputes each console step from its facts; a report cannot pass a console step on facts that show the defect."""

    def test_the_good_report_passes(self):
        self.assertEqual(base_judge.judge(base_judge.good_report())['result'], 'pass')

    def test_each_defect_is_refused_as_a_failed_or_contradicted_step(self):
        cases = [
            ('console_entry', {'installed': {'onecrew': 'onecrew.v2.cli:main'}}),         # metadata off what the executable imports
            ('console_entry', {'launcher': {'onecrew': None}}),
            ('console_entry', {'installed': {}, 'launcher': {}}),
            ('console_entry', {'outside': {'onecrew.console': str(ROOT / 'onecrew' / 'console.py')}}),
            ('console_entry', {'origins': {'onecrew': 'x'}}),                              # the target module was never located
            ('console_cp1252_help', {'env': pc.CONSOLE_ENV['utf8']}),                      # ran under UTF-8: proves nothing about cp1252
            ('console_cp1252_help', {'env': {**pc.CONSOLE_ENV['cp1252'], 'PYTHONIOENCODING': 'utf-8'}}),
            ('console_cp1252_help', {'utf8_strict': False}),
            ('console_cp1252_help', {'needles': {'help_vi': False}}),
            ('console_cp1252_help', {'same_as_utf8': False}),
            ('console_cp1252_help', {'utf8_exit': 1}),
            ('console_cp1252_init', {'utf8_strict': False}),                               # exit 2 as expected, but '?' instead of Vietnamese
            ('console_cp1252_init', {'needles': {'init_plan': True, 'init_cancelled': False}}),
            ('console_cp1252_init', {'wrote': ['state']}),
            ('console_cp1252_init', {'init_exit': 0}),
        ]
        for sid, facts in cases:
            with self.subTest(sid=sid, facts=facts):
                r, _ = _report_with(sid, **facts)
                v = base_judge.judge(r)
                self.assertEqual(v['result'], 'refused', v)
                self.assertTrue(any(sid in x for x in v['reasons']), v)
                r, _ = _report_with(sid, ok=False, **facts)
                v = base_judge.judge(r)
                self.assertIn(f'mandatory step failed: {sid}', v['reasons'])

    def test_a_crash_in_the_tails_is_refused(self):
        r, _ = _report_with('console_cp1252_help', exit=1, ok=False, stderr_tail="UnicodeEncodeError: 'charmap' codec can't encode character")
        v = base_judge.judge(r)
        self.assertEqual(v['result'], 'refused')
        self.assertTrue(any('UnicodeEncodeError' in x for x in v['reasons']), v)

    def test_each_console_step_is_mandatory(self):
        for sid in ('console_entry', 'console_cp1252_help', 'console_cp1252_init'):
            with self.subTest(sid):
                self.assertIn(sid, pc.BASE_REQUIRED)
                r = base_judge.good_report()
                r['steps'] = [s for s in r['steps'] if s['id'] != sid]
                self.assertIn(f'expected step missing: {sid}', base_judge.judge(r)['reasons'])
                r, _ = _report_with(sid, mandatory=False)
                self.assertTrue(any('demoted' in x for x in base_judge.judge(r)['reasons']))


if __name__ == '__main__':
    unittest.main()
