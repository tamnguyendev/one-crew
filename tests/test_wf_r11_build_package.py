"""Round 11 finding D: the final package must be in step with its snapshot and carry the evidence.

build_package.py refuses mixed inputs (audit table of another commit, bundles of another wheel/commit, receipts of another commit), takes the
previous wheel's provenance from evidence (never a hard-coded string), and keeps EVERY bundle result, refused ones included.
run_bundles.py keeps a refused/blocked release in its index instead of dropping it.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'docs' / 'wf' / 'audit' / 'tools'
FULL = '73d6c770875a1947aac68bb1268e085f5a675556'
OTHER = 'abb570a1b2c3d4e5f60718293a4b5c6d7e8f9012'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


build_package = _load('build_package')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def wheel(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(f'onecrew-{version}.dist-info/METADATA', f'Metadata-Version: 2.1\nName: onecrew\nVersion: {version}\n\n')
    return path


def jwrite(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    return path

PREV_COMMIT = 'd3120c6' + '0' * 33
PREV_SHA = 'b' * 64


def bundle_evidence(bdir, rel, commit, wsha, prev_commit=PREV_COMMIT, prev_sha=PREV_SHA, first_release=True):
    """Round 13 P2-B: the evidence set of a produced bundle as wfkit.release_bundle writes it: bundle.json (artifacts, the five `checks` pinned by
    sha256, first_release baseline) + receipts/ (installed, upgrade, events, rollback -> old_run/forward_run, notes), roles as the producer fixes them."""
    bdir = Path(bdir)
    cur, prv = {'commit': commit, 'wheel_sha256': wsha}, {'commit': prev_commit, 'wheel_sha256': prev_sha}

    def put(name, body):
        raw = json.dumps({'kind': name, 'release': rel, 'result': 'pass', 'simulated': False, **body}, ensure_ascii=False, sort_keys=True, indent=1).encode('utf-8')
        (bdir / 'receipts').mkdir(parents=True, exist_ok=True)
        (bdir / 'receipts' / (name + '.json')).write_bytes(raw)
        return {'path': f'receipts/{name}.json', 'sha256': hashlib.sha256(raw).hexdigest()}

    old = put('rollback-old-run', {**prv})
    fwd = put('rollback-forward-run', {**cur})
    checks = {'installed': put('installed', {**cur, 'scenarios': [dict(cur), dict(cur)]}),
              'upgrade': put('upgrade', {**cur, 'from': dict(prv), 'to': dict(cur)}),
              'events': put('events', {**cur, 'old_artifact': dict(prv)}),
              'rollback': put('rollback', {**cur, 'allowed': {'scan': {'old_version': prev_commit}, 'old_run': old}, 'rejected': {'scan': {'old_version': prev_commit}},
                                           'forward_run': fwd}),
              'notes': put('notes', {**cur, 'gate_decision': {**cur, 'snapshot': {'commit': commit}}})}
    bundle = {'schema': 1, 'release': rel, 'mode': 'real', 'artifacts': {'previous': dict(prv, wheel='wheels/previous/p.whl'), 'current': dict(cur, wheel='wheels/current/c.whl')},
              'gate_history': [], 'deliveries': [], 'checks': checks}
    if first_release:
        bundle['first_release'] = {'baseline': {**prv, 'role': 'compat-baseline', 'delivered': False, 'accepted': False}, 'reason': 'no delivered build'}
    jwrite(bdir / 'bundle.json', bundle)
    return bundle


class BuildPackageBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wf r11 build '))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        t = self.tmp
        self.gate = t / 'gate out'
        cur = wheel(self.gate / 'gate' / 'wheel' / 'onecrew-2.2.0.dev11-py3-none-any.whl', '2.2.0.dev11')
        self.wsha = sha(cur)
        jwrite(self.gate / 'gate' / 'build.json', {'commit': FULL, 'wheel_sha256': self.wsha, 'version': '2.2.0.dev11', 'wheel': str(cur)})
        jwrite(self.gate / 'decision.json', {'decision': 'refused', 'implementation_checks': {'expected': 2, 'receipted': 2, 'failed': []}, 'snapshot': {'intact': True}})
        jwrite(self.gate / 'snapshot.json', {'prepared_at': 'now', 'commit': FULL})
        # round 12 P2-D: a receipt carries the commit AND the wheel of the build; an installed check also the wheel it consumed
        jwrite(self.gate / 'gate' / 'receipts' / 'KN-a.json', {'check': 'KN/a', 'commit': FULL, 'wheel_sha256': self.wsha, 'wheel_used': []})
        jwrite(self.gate / 'gate' / 'receipts' / 'KN-i.json', {'check': 'KN/i', 'commit': FULL, 'wheel_sha256': self.wsha, 'wheel_used': [self.wsha]})
        self.audit = self.write_audit(FULL[:7])
        # previous package (evidence) + its wheel
        self.prevpkg = t / 'prevpkg'
        self.prevwheel = wheel(self.prevpkg / 'wheel' / 'onecrew-2.2.0.dev8-py3-none-any.whl', '2.2.0.dev8')
        jwrite(self.prevpkg / 'manifest.json', {'commit': '4b1b7b15a7b7514dc71cab5592d768fd70743dce', 'version': '2.2.0.dev8',
                                                 'wheel': {'file': 'wheel/onecrew-2.2.0.dev8-py3-none-any.whl', 'sha256': sha(self.prevwheel)}})
        # bundles
        self.bdir = t / 'bundles'
        self.index = {}
        self.add_bundle('R01', 'pass')
        self.add_refused('RP')
        self.index_path = jwrite(t / 'bundles-index.json', self.index)

    def write_audit(self, commit):
        d = self.tmp / ('audit-' + commit)
        jwrite(d / 'audit-92.json', {'commit': commit, 'counts': {'Done': 62, 'Partial': 26, 'Blocked': 4}, 'rows': []})
        (d / 'AUDIT-92.md').write_text(f'# t\nCommit kiểm: `{commit}`.\n', encoding='utf-8')
        return d / 'audit-92.json'

    def add_bundle(self, rel, decision, commit=FULL, wsha=None):
        p = jwrite(self.bdir / rel / 'release-check.json', {'decision': decision, 'conditions': {'INPUTS(bootstrap)': True}, 'reasons': [], 'release': rel,
                                                             'commit': commit, 'wheel_sha256': wsha or self.wsha, 'first_release': True,
                                                             'first_release_baseline': {'commit': PREV_COMMIT, 'wheel_sha256': PREV_SHA}})
        bundle_evidence(self.bdir / rel, rel, commit, wsha or self.wsha)          # round 13 P2-B: a produced bundle carries its declared receipts
        self.index[rel] = str(p)

    def add_refused(self, rel):
        p = jwrite(self.bdir / rel / 'bundle-result.json', {'release': rel, 'decision': 'refused', 'produced': False, 'conditions': {},
                                                             'reasons': [{'code': 'PRODUCER', 'detail': 'RP needs --matrix'}], 'reason': 'RP needs --matrix'})
        self.index[rel] = str(p)

    def build(self, *extra, name='pkg', previous=True, audit=None):
        args = [str(self.gate), str(self.tmp / name), '--bundles', str(jwrite(self.tmp / 'bundles-index.json', self.index)), '--audit', str(audit or self.audit)]
        args += ['--previous-wheel', str(self.prevwheel)] if previous else ['--first-release']
        build_package.main(args + list(extra))
        return self.tmp / name

    def manifest(self, pkg):
        return json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))


class ConsistencyTests(BuildPackageBase):
    def test_consistent_inputs_build_and_pass_the_identity_step(self):
        pkg = self.build()
        from wfkit import package_check as pc
        sc = pc.package_scope(pkg)
        self.assertEqual(sc['reasons'], [])
        self.assertEqual(self.manifest(pkg)['tasks_92_commit'], FULL[:7])

    def test_audit_of_another_commit_is_refused_before_anything_is_written(self):
        bad = self.write_audit('abb570a')
        with self.assertRaises(SystemExit) as cm:
            self.build(audit=bad)
        self.assertIn('audit-92.json', str(cm.exception))
        self.assertIn('abb570a', str(cm.exception))
        self.assertFalse((self.tmp / 'pkg').exists())

    def test_audit_md_of_another_commit_is_refused(self):
        (self.audit.parent / 'AUDIT-92.md').write_text('Commit kiểm: `abb570a`.\n', encoding='utf-8')
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('AUDIT-92.md', str(cm.exception))

    def test_bundle_of_another_wheel_is_refused(self):
        self.add_bundle('R02', 'pass', wsha='9' * 64)
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('R02', str(cm.exception))
        self.assertIn('wheel', str(cm.exception))

    def test_bundle_of_another_commit_is_refused(self):
        self.add_bundle('R02', 'pass', commit=OTHER)
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('R02', str(cm.exception))
        self.assertIn('commit', str(cm.exception))

    def test_receipt_of_another_commit_is_refused(self):
        jwrite(self.gate / 'gate' / 'receipts' / 'KN-b.json', {'check': 'KN/b', 'commit': OTHER, 'wheel_sha256': self.wsha, 'wheel_used': []})
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('KN-b.json', str(cm.exception))

    def test_gate_snapshot_of_another_commit_is_refused(self):
        jwrite(self.gate / 'snapshot.json', {'prepared_at': 'now', 'commit': OTHER})
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('snapshot.json', str(cm.exception))


class BundlesKeepEveryResultTests(BuildPackageBase):
    def test_refused_bundle_is_in_manifest_and_package_with_its_reason(self):
        pkg = self.build()
        b = self.manifest(pkg)['bundles']
        self.assertEqual(sorted(b), ['R01', 'RP'])
        self.assertEqual(b['R01']['decision'], 'pass')
        self.assertEqual(b['RP']['decision'], 'refused')
        self.assertIs(b['RP']['produced'], False)
        self.assertIn('--matrix', json.dumps(b['RP']['reasons']) + b['RP'].get('reason', ''))
        self.assertTrue((pkg / 'bundles' / 'RP' / 'bundle-result.json').is_file())
        self.assertEqual(b['R01']['commit'], FULL)
        self.assertEqual(b['R01']['wheel_sha256'], self.wsha)

    def test_readme_shows_92_counts_with_commit_and_the_bundle_table_with_refused(self):
        readme = (self.build() / 'README.md').read_text(encoding='utf-8')
        self.assertIn(f'Done 62 · Partial 26 · Blocked 4 (commit `{FULL[:7]}`;', readme)
        self.assertRegex(readme, r'\| RP \| refused \|')
        self.assertRegex(readme, r'\| R01 \| pass \|')
        self.assertIn('RP needs --matrix', readme)


class PreviousWheelProvenanceTests(BuildPackageBase):
    def test_provenance_comes_from_the_previous_package_manifest(self):
        pw = self.manifest(self.build())['previous_wheel']
        self.assertEqual(pw['commit'], '4b1b7b15a7b7514dc71cab5592d768fd70743dce')
        self.assertEqual(pw['version'], '2.2.0.dev8')
        self.assertEqual(pw['sha256'], sha(self.prevwheel))
        self.assertEqual(pw['source'], 'previous package manifest.json')
        self.assertNotIn('d3120c6', json.dumps(pw))

    def test_manifest_naming_other_wheel_bytes_is_refused(self):
        m = json.loads((self.prevpkg / 'manifest.json').read_text(encoding='utf-8'))
        m['wheel']['sha256'] = '1' * 64
        jwrite(self.prevpkg / 'manifest.json', m)
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('sha256', str(cm.exception))
        self.assertFalse((self.tmp / 'pkg').exists())

    def test_version_in_evidence_must_match_the_wheel_metadata(self):
        m = json.loads((self.prevpkg / 'manifest.json').read_text(encoding='utf-8'))
        m['version'] = '2.2.0.dev3'
        jwrite(self.prevpkg / 'manifest.json', m)
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('version', str(cm.exception))

    def test_no_evidence_falls_back_to_the_wheel_metadata_and_says_so(self):
        (self.prevpkg / 'manifest.json').unlink()
        pw = self.manifest(self.build())['previous_wheel']
        self.assertEqual(pw['version'], '2.2.0.dev8')
        self.assertEqual(pw['source'], 'wheel METADATA')
        self.assertIsNone(pw['commit'])

    def test_sidecar_evidence_is_checked_against_the_wheel(self):
        (self.prevpkg / 'manifest.json').unlink()
        side = jwrite(Path(str(self.prevwheel) + '.json'), {'commit': 'd3120c6' + '0' * 33, 'sha256': sha(self.prevwheel), 'version': '2.2.0.dev8', 'source': 'baseline build'})
        pw = self.manifest(self.build())['previous_wheel']
        self.assertEqual(pw['source'], 'wheel sidecar')
        self.assertTrue(pw['commit'].startswith('d3120c6'))
        jwrite(side, {'commit': 'd3120c6' + '0' * 33, 'sha256': '2' * 64, 'version': '2.2.0.dev8'})
        with self.assertRaises(SystemExit):
            self.build(name='pkg2')

    def test_unreadable_previous_wheel_without_evidence_is_refused(self):
        (self.prevpkg / 'manifest.json').unlink()
        self.prevwheel.write_bytes(b'not a wheel')
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertIn('evidence', str(cm.exception))


class RunBundlesKeepsRefusalTests(unittest.TestCase):
    def test_refused_release_is_indexed_with_its_reason(self):
        out = Path(tempfile.gettempdir()) / ('wf-r11-runbundles-' + hashlib.sha1(os.urandom(8)).hexdigest()[:8])
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        r = subprocess.run([sys.executable, '-X', 'utf8', str(TOOLS / 'run_bundles.py'), str(out), '--only', 'RP'], cwd=str(ROOT),
                           capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'PYTHONPATH': '.'})
        self.assertEqual(r.returncode, 0, r.stderr)
        index = json.loads((out / 'bundles-index.json').read_text(encoding='utf-8'))
        self.assertEqual(list(index), ['RP'])
        res = json.loads(Path(index['RP']).read_text(encoding='utf-8'))
        self.assertEqual(res['decision'], 'refused')
        self.assertIs(res['produced'], False)
        self.assertIn('--matrix', res['reason'])


if __name__ == '__main__':
    unittest.main()
