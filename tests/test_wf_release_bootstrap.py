"""Directive section 6 follow-ups: (1) the first-release baseline is ONE stored, verified wheel the drills reuse (stable identity across runs);
(2) the consumers (release notes, handover package) read INPUTS(bootstrap) as well as INPUTS and compute their sentence from the bundles."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from onecrew.ledger import LedgerError
from wfkit import release_bundle, release_check

ROOT = Path(__file__).resolve().parents[1]


def tree_hash(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).rglob('*')) if p.is_file()}


class BaselinePinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='wf-pin-test-')
        cls.root = Path(cls.temp.name)
        cls.pin = release_bundle.build_baseline_wheel(cls.root / 'pin')
        cls.baseline = cls.pin['commit']

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def copy_pin(self, name, sidecar_change=None, wheel_from=None):
        folder = self.root / name; folder.mkdir()
        src = Path(wheel_from or self.pin['wheel']); dst = folder / Path(self.pin['wheel']).name
        shutil.copy2(src, dst)
        sidecar = json.loads(Path(self.pin['sidecar']).read_text(encoding='utf-8'))
        sidecar['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()
        sidecar.update(sidecar_change or {})
        Path(str(dst) + '.json').write_text(json.dumps(sidecar), encoding='utf-8')
        return dst

    def test_the_stored_pin_verifies_and_the_builder_refuses_to_overwrite_it(self):
        again = release_bundle.verify_baseline_wheel(self.pin['wheel'], self.baseline)
        self.assertEqual(again['wheel_sha256'], self.pin['wheel_sha256'])
        sidecar = json.loads(Path(self.pin['sidecar']).read_text(encoding='utf-8'))
        self.assertEqual(sidecar['commit'], self.baseline); self.assertTrue(sidecar['source'].startswith('release_bundle baseline builder at '))
        with self.assertRaises(LedgerError): release_bundle.build_baseline_wheel(self.root / 'pin')

    def test_two_producer_builds_with_the_same_pin_have_the_same_previous_identity(self):
        identities = []
        # gate 73be6ee (25/10): the reused PREVIOUS wheel must not be recorded in the gate's used-log as a wheel this check consumed
        used_log = self.root / 'used.log'; saved = os.environ.get('WF_WHEEL_USED_LOG'); os.environ['WF_WHEEL_USED_LOG'] = str(used_log)
        def restore():
            if saved is None: os.environ.pop('WF_WHEEL_USED_LOG', None)
            else:
                os.environ['WF_WHEEL_USED_LOG'] = saved
                if used_log.is_file():
                    with open(saved, 'a', encoding='utf-8') as f: f.write(used_log.read_text(encoding='utf-8'))
        self.addCleanup(restore)
        for i in range(2):
            producer = release_bundle.Producer('R01', Path(tempfile.gettempdir()) / f'wf-pin-run-{os.getpid()}-{i}', baseline_wheel=self.pin['wheel'])
            self.addCleanup(shutil.rmtree, producer.out, True)
            before = used_log.read_text(encoding='utf-8') if used_log.is_file() else ''
            producer.build()
            recorded = set(used_log.read_text(encoding='utf-8')[len(before):].split()) if used_log.is_file() else set()
            self.assertNotIn(self.pin['wheel_sha256'], recorded, 'the pinned baseline (rollback target) was recorded as the consumed wheel')
            self.assertLessEqual(recorded, {producer.artifact('current')['wheel_sha256']}, recorded)
            identities.append(producer.identity('previous'))
            self.assertEqual(producer.artifact('previous')['wheel_sha256'], self.pin['wheel_sha256'])
            self.assertEqual(producer.artifact('previous')['pinned_from'], self.pin['wheel'])
            fields, _ = release_bundle.prerequisite_fields(True, producer.identity('previous'))
            self.assertEqual(fields['first_release']['baseline']['wheel_sha256'], self.pin['wheel_sha256'])
        self.assertEqual(identities[0], identities[1])
        self.assertEqual(identities[0], {'commit': self.baseline, 'wheel_sha256': self.pin['wheel_sha256']})

    def test_a_wheel_whose_sidecar_or_content_is_not_the_baseline_is_refused(self):
        cases = {'sidecar names another commit': self.copy_pin('other-commit', {'commit': 'c' * 40}),
                 'sidecar sha256 differs': self.copy_pin('other-sha', {'sha256': 'e' * 64}),
                 'sidecar version differs': self.copy_pin('other-version', {'version': '9.9.9'})}
        # a wheel of ANOTHER commit (this checkout) with a forged sidecar that names the baseline: refused by the git-blob check
        current = self.root / 'current-build'; current.mkdir()
        from tests import wf_wheel as wheel
        from wfkit.upgrade_drill import build_source
        with build_source(ROOT):
            other, _, _ = wheel.build_wheel(current)
        cases['forged sidecar on another build'] = self.copy_pin('forged', wheel_from=other)
        for label, path in cases.items():
            with self.subTest(label):
                with self.assertRaises(LedgerError): release_bundle.verify_baseline_wheel(path, self.baseline)
        with self.assertRaises(LedgerError):
            release_bundle.Producer('R01', Path(tempfile.gettempdir()) / f'wf-pin-bad-{os.getpid()}', baseline_wheel=cases['sidecar names another commit'])
        shutil.rmtree(Path(tempfile.gettempdir()) / f'wf-pin-bad-{os.getpid()}', True)
        missing = self.root / 'no-sidecar'; missing.mkdir(); shutil.copy2(self.pin['wheel'], missing / Path(self.pin['wheel']).name)
        with self.assertRaises(LedgerError): release_bundle.verify_baseline_wheel(missing / Path(self.pin['wheel']).name, self.baseline)

    def test_without_a_pin_the_behaviour_is_unchanged(self):
        out = Path(tempfile.gettempdir()) / f'wf-pin-none-{os.getpid()}'
        self.addCleanup(shutil.rmtree, out, True)
        producer = release_bundle.Producer('R01', out)
        self.assertIsNone(producer.baseline_pin)
        self.assertIsNone(release_bundle.parser().parse_args(['R01', '--out', 'x']).baseline_wheel)


def check_result(first_release, ok=True):
    baseline = {'commit': 'd3120c65baa846a84f5c177e117d9d93fd77f2a0', 'wheel_sha256': '5' * 64, 'role': 'compat-baseline', 'delivered': False, 'accepted': False}
    code = 'INPUTS(bootstrap)' if first_release else 'INPUTS'
    reasons = [] if ok else [{'code': code, 'detail': 'previous delivered gate history missing' if not first_release else 'not a first release'}]
    result = {'decision': 'pass' if ok else 'refused', 'conditions': {code: ok, **{f'T54.{i}': True for i in range(1, 6)}}, 'reasons': reasons,
              'first_release': first_release and ok, 'owner_acceptance': False, 'bundle': 'x/bundle.json'}
    if first_release and ok: result['first_release_baseline'] = baseline
    return result


class ConsumerTests(unittest.TestCase):
    def test_sentence_is_computed_from_the_bundles(self):
        self.assertEqual(release_check.inputs_sentence({'R01': check_result(False, ok=False), 'R02': check_result(False, ok=False)}), release_check.ORDINARY_REFUSED)
        self.assertEqual(release_check.inputs_sentence({'R01': check_result(True), 'R02': check_result(True)}),
                         'bản giao đầu tiên: INPUTS(bootstrap) với baseline d3120c6 ghim, chưa giao/chưa nghiệm thu')
        mixed = release_check.inputs_sentence({'R01': check_result(True), 'R02': check_result(False, ok=False)})
        self.assertIn('INPUTS(bootstrap)', mixed); self.assertIn('R02 INPUTS', mixed); self.assertNotIn(release_check.ORDINARY_REFUSED, mixed)
        refused_boot = release_check.inputs_sentence({'R01': check_result(True, ok=False)})
        self.assertIn('R01 INPUTS(bootstrap) — not a first release', refused_boot)
        self.assertEqual(release_check.inputs_summary(check_result(True))['code'], 'INPUTS(bootstrap)')
        self.assertEqual(release_check.inputs_summary(check_result(False))['code'], 'INPUTS')

    def test_build_package_no_longer_hard_codes_the_inputs_sentence(self):
        text = (ROOT / 'docs' / 'wf' / 'audit' / 'tools' / 'build_package.py').read_text(encoding='utf-8')
        self.assertNotIn('INPUTS luôn không đạt vì chưa có release nào được giao', text)
        self.assertIn('inputs_sentence(bundles)', text); self.assertIn("'first_release'", text)
        self.assertIn('verify_kit.build_verify_dir(pkg)', text)                     # the verify/ shipping logic is kept

    def test_release_notes_render_which_inputs_rule_applied_into_an_override_dir(self):
        notes = ROOT / 'docs' / 'wf' / 'release-notes'; before = tree_hash(notes)
        with tempfile.TemporaryDirectory(prefix='wf-notes-test-') as temp:
            temp = Path(temp); index = {}
            for rel, first in (('R01', True), ('R02', False)):
                path = temp / rel / 'release-check.json'; path.parent.mkdir()
                path.write_text(json.dumps(check_result(first, ok=first)), encoding='utf-8'); index[rel] = str(path)
            (temp / 'index.json').write_text(json.dumps(index), encoding='utf-8')
            out = temp / 'notes'
            env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE', 'ONECREW_ACTOR')}
            done = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'docs' / 'wf' / 'audit' / 'tools' / 'gen_release_notes.py'), 'gate-x', 'abc1234', 'passed',
                                   str(temp / 'index.json'), str(out)], cwd=str(ROOT), env=env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(done.returncode, 0, done.stderr)
            r01 = (out / 'R01.md').read_text(encoding='utf-8'); r02 = (out / 'R02.md').read_text(encoding='utf-8')
        self.assertIn('INPUTS(bootstrap) — bản giao đầu tiên, baseline compat ghim: đạt', r01)
        self.assertIn('Quy tắc INPUTS đã áp dụng: `INPUTS(bootstrap)`; first_release: true.', r01)
        self.assertIn('KHÔNG phải bản đã giao, chưa nghiệm thu', r01)
        self.assertIn('INPUTS — lịch sử cổng giao của bản trước: không đạt — previous delivered gate history missing', r02)
        self.assertIn('first_release: false.', r02)
        self.assertIn('nên điều kiện INPUTS chỉ có thể đạt sau khi chủ sở hữu giao một release', r02)
        for text in (r01, r02):
            for title in release_check.SECTIONS: self.assertIn('## ' + title, text)
            self.assertIn('Acceptance: not-requested', text)
        self.assertEqual(tree_hash(notes), before)                                   # the checkout's release notes are not overwritten


if __name__ == '__main__':
    unittest.main()
