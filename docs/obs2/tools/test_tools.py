"""Focused tooling checks using a miniature Git snapshot, never a final OBS-2 package."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class FixedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='obs2-tool-test-'); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.repo = self.base / 'repo'; self.repo.mkdir()
        self.builder, self.verify = load('build_obs2'), load('verify_obs2')
        self.builder.ROOT = self.repo
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        self.git('init', '-q'); self.git('config', 'user.name', 'Fixture'); self.git('config', 'user.email', 'fixture@localhost')
        modules = self.builder.MODULES
        for name in modules:
            path = self.repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# committed module\n', encoding='utf-8')
        for name in ('onecrew/__init__.py', 'onecrew/v2/__init__.py'):
            (self.repo / name).write_text('', encoding='utf-8')
        project = '[project]\nname="onecrew"\nversion = "0.0.0"\n[tool.setuptools]\npy-modules = [' + ','.join(json.dumps(p[:-3].replace('/', '.')) for p in modules) + ']\npackages = []\n'
        (self.repo / 'pyproject.toml').write_text(project, encoding='utf-8')
        (self.repo / 'tests').mkdir(); shutil.copyfile(REPO / 'tests/wf_wheel.py', self.repo / 'tests/wf_wheel.py')
        for name in ('obs1_ux_harness.py', 'obs2_ux_harness.py', 'obs2_artifact_browser.py'):
            (self.repo / 'tests' / name).write_text('# synthetic browser harness stub\n', encoding='utf-8')
        for folder, names in (('docs/obs2/tools', ('verify_obs2.py', 'check_owner_human.py', 'check_review_fixes.py', 'check_unbound_browser.py', 'scenario_obs2.py', 'viewer_obs2.ps1', 'mo-trang-obs2.ps1', 'dung-trang-obs2.ps1')),
                              ('docs/obs1/tools', ('mo-trang-obs1.ps1', 'dung-trang-obs1.ps1'))):
            dest = self.repo / folder; dest.mkdir(parents=True, exist_ok=True)
            for name in names: (dest / name).write_text('# synthetic tooling stub\n', encoding='utf-8')
        (self.repo / 'docs/obs2/README.vi.md').write_text('Synthetic tooling test only', encoding='utf-8')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'miniature fixture')
        self.commit = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], env=self.env, stderr=subprocess.PIPE, text=True).strip()

    def test_dirty_checkout_cannot_enter_pinned_wheel_and_existing_out_is_refused(self):
        (self.repo / 'onecrew/v2/tracking_work.py').write_text('# uncommitted bytes\n', encoding='utf-8')
        out = self.base / 'package'
        record = self.builder.build(self.commit, out)
        self.assertEqual(record['code_commit'], self.commit)
        with zipfile.ZipFile(out / 'wheel' / record['wheel']['name']) as zipped:
            committed = subprocess.check_output(['git', '-C', str(self.repo), 'show', self.commit + ':onecrew/v2/tracking_work.py'], env=self.env)
            self.assertEqual(zipped.read('onecrew/v2/tracking_work.py'), committed)
        self.verify.package_identity(out)
        with self.assertRaisesRegex(ValueError, 'exists'): self.builder.build(self.commit, out)

    def test_tampered_package_fails_and_work_env_is_isolated(self):
        out = self.base / 'package'; self.builder.build(self.commit, out)
        (out / 'verify/scenario_obs2.py').write_text('# tampered\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): self.verify.package_identity(out)
        work = self.base / 'work'; work.mkdir()
        env = self.verify.isolated_env(work)
        self.assertEqual(env['LOCALAPPDATA'], str(work / 'local'))
        self.assertEqual(env['ONECREW_TRACK_MARKER_DIR'], str(work / 'markers'))
        self.assertEqual(env['GIT_CONFIG_GLOBAL'], os.devnull)


if __name__ == '__main__': unittest.main()
