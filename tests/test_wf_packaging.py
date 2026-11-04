"""T33a (W40) — packaging + the runtime install-boundary check on the INSTALLED wheel.

The wheel is built from pyproject (pure-python, by hand — no setuptools) and installed offline into a fresh venv. Then the eight boundary
cases M1-M8 run as subprocess interpreters and are judged by onecrew.v2.boundary against the installed distribution's RECORD and the
interpreter's stdlib markers. The previous T33a rule (only py-modules names, only the single stdlib dir) misflags M1/M2 — the counter-example.
A checkout carrying v1 modules is the archive of ee46539 (same tree used by the old-version tests).
"""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import tests.wf_wheel as wh
import tests.wf_oldversion as ov
from onecrew.v2 import boundary

REPO = str(Path(__file__).resolve().parents[1])


def _have(tool):
    try:
        return subprocess.run([tool, '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have('git'), 'git required for the checkout archive')
class InstallBoundaryTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.whl, cls.version, (cls.modules, cls.packages) = wh.build_wheel(cls.runs)
        cls.py = wh.make_venv(cls.runs)
        wh.install(cls.py, cls.whl)
        cls.ctx = wh.build_ctx(cls.py, cls.modules, cls.packages)
        cls.checkout = ov.archive('ee46539', REPO, cls.runs)             # a checkout with v1 modules
        cls.site = cls._site_of(cls.py)
        # a fake stdlib module (csv) and a startup sitecustomize that loads onecrew from the checkout
        cls.fake = cls.runs / 'fake'; (cls.fake / 'csv').mkdir(parents=True); (cls.fake / 'csv' / '__init__.py').write_text('reader = None\n')
        cls.pre = cls.runs / 'pre'; cls.pre.mkdir()
        (cls.pre / 'sitecustomize.py').write_text('import sys\nsys.path.insert(0, r"' + str(cls.checkout) + '")\nimport onecrew.v2.plan\n')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    @classmethod
    def _site_of(cls, python):
        import json
        r = subprocess.run([str(python), '-c', 'import json,site; print(json.dumps(site.getsitepackages()))'], capture_output=True, text=True)
        return json.loads(r.stdout)[0]

    def _violations(self, body, *, env_extra=None, flags=('-I',)):
        data, tail = wh.run_case(self.py, body, env_extra=env_extra, flags=flags)
        self.assertIsNotNone(data, f'case produced no module dump: {tail}')
        return boundary.violations(data['end'], self.ctx), data

    # ---- PASS cases ----
    def test_m1_parent_packages_pass(self):
        body = 'import onecrew, onecrew.v2, onecrew.v2.verifiers, onecrew.v2.plan, onecrew.v2.contract, onecrew.v2.compat'
        bad, data = self._violations(body)
        self.assertEqual(bad, [], f'M1 parent packages should pass: {bad}')
        # the parent packages are present and classed onecrew (not misflagged)
        for pkg in ('onecrew', 'onecrew.v2', 'onecrew.v2.verifiers'):
            self.assertIn(pkg, data['end'])
            self.assertEqual(boundary.classify(pkg, data['end'][pkg], self.ctx)[0], 'onecrew')

    def test_m2_sqlite_socket_in_dlls_pass(self):
        bad, _ = self._violations('import sqlite3, socket, json, pathlib')
        self.assertEqual(bad, [], f'M2 _sqlite3/_socket (DLLs) should pass: {bad}')

    def test_m3_builtin_and_frozen_pass(self):
        bad, _ = self._violations('import builtins, sys, _imp, zipimport, codecs')
        self.assertEqual(bad, [], f'M3 built-in/frozen should pass: {bad}')

    # ---- FAIL cases ----
    def test_m4_checkout_shadows_onecrew_fails(self):
        body = f'import sys\nsys.path.insert(0, r"{self.checkout}")\nimport onecrew.v2.plan'
        bad, _ = self._violations(body)
        names = [n for n, _ in bad]
        self.assertTrue(any(n.startswith('onecrew') for n in names), f'M4 should flag onecrew from the checkout: {bad}')

    def test_m5_v1_module_from_checkout_fails(self):
        body = (f'import onecrew\nonecrew.__path__.append(r"{Path(self.checkout) / "onecrew"}")\n'
                'import onecrew.delivery')
        bad, _ = self._violations(body)
        self.assertTrue(any(n.startswith('onecrew.delivery') for n, _ in bad), f'M5 should flag onecrew.delivery: {bad}')

    def test_m6_undeclared_dependency_fails(self):
        bad, _ = self._violations('import onecrew.ledger, pip')
        self.assertTrue(any(n == 'pip' or n.startswith('pip.') for n, _ in bad), f'M6 should flag pip (undeclared): {bad}')

    def test_m7_fake_stdlib_source_fails(self):
        body = f'import sys\nsys.path.insert(0, r"{self.fake}")\nimport csv'
        bad, _ = self._violations(body)
        self.assertTrue(any(n == 'csv' for n, _ in bad), f'M7 should flag the fake csv: {bad}')

    def test_m8_startup_loaded_checkout_is_not_exempt(self):
        # sitecustomize on PYTHONPATH loads onecrew.v2.plan from the checkout at startup; -s keeps sitecustomize active
        body = 'import sys'  # nothing extra: the startup import already happened
        bad, data = self._violations(body, env_extra={'PYTHONPATH': str(self.pre)}, flags=('-s',))
        self.assertTrue(any(n.startswith('onecrew') for n, _ in bad),
                        f'M8 should flag the startup-loaded checkout onecrew (not exempt): {bad}')

    # ---- counter-example: the previous rule (py-modules only, single stdlib dir, startup-exempt) misflags M1/M2 ----
    def test_counter_old_rule_misflags_parents_and_dlls(self):
        import sysconfig
        old_ctx = dict(self.ctx, parents=set(), packages=set(),
                       marker_dirs=[boundary.norm(sysconfig.get_paths()['stdlib'])])
        data, _ = wh.run_case(self.py, 'import onecrew, onecrew.v2, onecrew.v2.plan, sqlite3, socket')
        old_bad = boundary.violations(data['end'], old_ctx)
        names = [n for n, _ in old_bad]
        # the old rule wrongly flags the build-added parent packages and the DLLs extensions...
        self.assertTrue(any(n in ('onecrew', 'onecrew.v2') for n in names), f'old rule should misflag parents: {names}')
        self.assertTrue(any(n in ('_sqlite3', '_socket') for n in names), f'old rule should misflag DLLs extensions: {names}')
        # ...while the new rule does not
        new_bad = boundary.violations(data['end'], self.ctx)
        self.assertEqual([n for n, _ in new_bad if n in ('onecrew', 'onecrew.v2', '_sqlite3', '_socket')], [])

    # ---- E1/E5: an R00 scenario runs from the INSTALLED command and every end-module is valid ----
    def test_r00_scenario_runs_from_installed_command_clean(self):
        import tempfile, json
        state = Path(tempfile.mkdtemp(dir=self.runs))
        # run `onecrew compat scan` through the installed module, dumping sys.modules at the end
        body = (f'import sys\nsys.argv = ["onecrew"]\nfrom onecrew.v2 import cli\n'
                f'cli.main(["--state-root", r"{state}", "compat", "scan"])')
        bad, data = self._violations(body)
        # every onecrew module loaded came from the installed RECORD (no checkout leak); no undeclared deps
        self.assertEqual([n for n, _ in bad if n.startswith('onecrew')], [], f'installed R00 scenario leaked a non-RECORD onecrew module: {bad}')


if __name__ == '__main__':
    unittest.main()
