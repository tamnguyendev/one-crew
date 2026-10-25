"""Codex P2-2: the verification tool ships INSIDE the handover package (verify/), hash-pinned, and runs with system Python only."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'docs' / 'wf' / 'audit' / 'tools'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


verify_kit = _load('verify_kit')
build_package = _load('build_package')


def clean_env():
    keep = ('SYSTEMROOT', 'SystemRoot', 'TEMP', 'TMP', 'PATH', 'USERPROFILE', 'COMSPEC', 'PATHEXT', 'WINDIR')
    return {k: v for k, v in os.environ.items() if k in keep}


def make_package(base):
    """A tiny fake package: manifest.json + SHA256SUMS + verify/ built by build_package's helper."""
    pkg = Path(base) / 'pkg'
    pkg.mkdir()
    (pkg / 'README.md').write_text('x', encoding='utf-8')
    verifier = verify_kit.build_verify_dir(pkg)
    (pkg / 'manifest.json').write_text(json.dumps({'schema': 1, 'verifier': verifier}), encoding='utf-8')
    verify_kit.write_sums(pkg)
    return pkg, verifier


def launcher(pkg, *args, cwd=None):
    return subprocess.run([sys.executable, str(pkg / 'verify' / 'verify_package.py'), *args], capture_output=True, text=True, encoding='utf-8',
                          cwd=str(cwd or pkg.parent), env=clean_env())


class SelfCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wf verify test '))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pkg, self.verifier = make_package(self.tmp)

    def test_1_selfcheck_passes_and_pins_all_files(self):
        self.assertEqual(sorted(self.verifier['files']), ['verify/legacy_continuation.py', 'verify/legacy_core.py', 'verify/package_check.py', 'verify/verify_package.py'])
        sums = (self.pkg / 'SHA256SUMS').read_text(encoding='utf-8')
        for rel, h in self.verifier['files'].items():
            self.assertIn(f'{h}  {rel}', sums)
        r = launcher(self.pkg, '--self-check-only')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_2a_corrupt_byte_refused_naming_file(self):
        f = self.pkg / 'verify' / 'package_check.py'
        f.write_bytes(f.read_bytes() + b'\n# tamper')
        r = launcher(self.pkg, '--self-check-only')
        self.assertEqual(r.returncode, 3)
        self.assertIn('verify/package_check.py', r.stderr)
        self.assertIn('modified', r.stderr)

    def test_2b_missing_file_refused(self):
        (self.pkg / 'verify' / 'legacy_core.py').unlink()
        r = launcher(self.pkg, '--self-check-only')
        self.assertEqual(r.returncode, 3)
        self.assertIn('missing: verify/legacy_core.py', r.stderr)

    def test_2c_manifest_mismatch_refused(self):
        m = json.loads((self.pkg / 'manifest.json').read_text(encoding='utf-8'))
        m['verifier']['files']['verify/package_check.py'] = '0' * 64
        (self.pkg / 'manifest.json').write_text(json.dumps(m), encoding='utf-8')
        r = launcher(self.pkg, '--self-check-only')
        self.assertEqual(r.returncode, 3)
        self.assertIn('verify/package_check.py', r.stderr)

    def test_2d_no_manifest_verifier_or_extra_file_refused(self):
        (self.pkg / 'verify' / 'wfkit.py').write_text('x=1', encoding='utf-8')
        r = launcher(self.pkg, '--self-check-only')
        self.assertEqual(r.returncode, 3)
        self.assertIn('unlisted file', r.stderr)
        (self.pkg / 'verify' / 'wfkit.py').unlink()
        (self.pkg / 'manifest.json').write_text(json.dumps({'schema': 1}), encoding='utf-8')
        r = launcher(self.pkg, '--self-check-only')
        self.assertEqual(r.returncode, 3)
        self.assertIn('verifier.files', r.stderr)

    def test_2e_refused_run_creates_no_work_dir(self):
        f = self.pkg / 'verify' / 'package_check.py'
        f.write_bytes(f.read_bytes() + b'#')
        work = self.tmp / 'work dir'
        r = launcher(self.pkg, str(self.pkg), str(work))
        self.assertEqual(r.returncode, 3)
        self.assertFalse(work.exists())

    def test_3_runs_from_new_spaced_cwd_with_clean_env_and_records_origin(self):
        cwd = Path(tempfile.mkdtemp(prefix='wf verify cwd '))
        self.addCleanup(shutil.rmtree, cwd, ignore_errors=True)
        work = cwd / 'out dir'
        for tool in ('verify_package', 'legacy_continuation'):
            r = subprocess.run([sys.executable, str(self.pkg / 'verify' / (tool + '.py')), '--self-check-only', str(self.pkg), str(work)], capture_output=True, text=True,
                               encoding='utf-8', cwd=str(cwd), env=clean_env())
            self.assertEqual(r.returncode, 0, r.stderr)
            rec = json.loads(r.stdout)
            self.assertEqual(rec['result'], 'self-check-ok')
            self.assertEqual(rec['foreign'], [])
            names = {m['module'] for m in rec['modules']}
            self.assertIn('package_check', names)
            if tool == 'legacy_continuation':
                self.assertIn('legacy_core', names)
            vdir = (self.pkg / 'verify').resolve()
            for m in rec['modules']:
                self.assertTrue(Path(m['file']).resolve().is_relative_to(vdir), m)
                self.assertEqual(m['sha256'], hashlib.sha256(Path(m['file']).read_bytes()).hexdigest())
            self.assertEqual(rec, {**json.loads((work / 'verification' / 'verifier-origin.json').read_text(encoding='utf-8')), 'result': 'self-check-ok'})
        self.assertEqual([p.name for p in (self.pkg / 'verify').iterdir() if p.name == '__pycache__'], [])

    def test_3b_foreign_wfkit_refused(self):
        # a module named package_check/wfkit already resolved outside verify/ must be refused (simulated through the origin check)
        spec = importlib.util.spec_from_file_location('shipped_launcher_under_test', self.pkg / 'verify' / 'verify_package.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fake = type(sys)('wfkit')
        fake.__file__ = str(ROOT / 'wfkit' / '__init__.py')
        sys.modules['wfkit'] = fake
        self.addCleanup(sys.modules.pop, 'wfkit', None)
        rec = mod.origin_record(self.verifier['files'])
        foreign = [f['module'] for f in rec['foreign']]
        # other tests in this process may already have imported real wfkit submodules (build_package does); every one of them is
        # foreign to the package and must be listed, and the planted top-level module must be among them
        self.assertIn('wfkit', foreign)
        self.assertTrue(all(m == 'wfkit' or m.startswith('wfkit.') or m == 'package_check' for m in foreign), foreign)


class ReadmeTests(unittest.TestCase):
    def test_4_readme_points_only_at_shipped_files(self):
        tmp = Path(tempfile.mkdtemp(prefix='wf pkg build '))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        gate = tmp / 'gate out'
        (gate / 'gate' / 'receipts').mkdir(parents=True)
        wheel = gate / 'onecrew-0.0.0-py3-none-any.whl'
        wheel.write_bytes(b'not a real wheel')
        (gate / 'gate' / 'build.json').write_text(json.dumps({'commit': 'a' * 40, 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(), 'version': '0.0.0', 'wheel': str(wheel)}))
        (gate / 'decision.json').write_text(json.dumps({'decision': 'pass', 'implementation_checks': {}, 'snapshot': {'intact': True}}))
        (gate / 'snapshot.json').write_text(json.dumps({'prepared_at': 'now'}))
        pkg = tmp / 'built pkg'
        build_package.main([str(gate), str(pkg)])
        readme = (pkg / 'README.md').read_text(encoding='utf-8')
        self.assertNotIn('docs/wf/audit/tools/', readme)
        self.assertIn('python verify/verify_package.py', readme)
        self.assertIn('python verify/legacy_continuation.py', readme)
        for line in readme.splitlines():
            if 'wfkit.' in line:
                self.assertIn('KHÔNG nằm trong gói', line)
        # every verify/ path the README names exists in the package; the manifest pins them
        manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['verifier']['files'], {f'verify/{p.name}': hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((pkg / 'verify').iterdir())})
        self.assertTrue(manifest['verifier']['source_commit'])
        for name in ('verify_package', 'legacy_continuation'):
            self.assertTrue((pkg / 'verify' / (name + '.py')).is_file())
        r = launcher(pkg, '--self-check-only', cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
