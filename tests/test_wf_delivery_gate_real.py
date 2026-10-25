"""Delivery-gate tests that need artifacts present only on the development machine (the real R00 gate output and the 6366137 snapshot).
Kept OUT of the gate registry on purpose: the snapshot gate forbids skipped tests, and these must skip elsewhere. Run by hand:
    python -m unittest tests.test_wf_delivery_gate_real
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import LedgerError
from wfkit import delivery_gate, development_gate, gate_history, release_bundle, release_check
from test_wf_delivery_gate import R00_DIR, SNAPSHOT, REVIEW, bundle_verdict

SNAPSHOT_C18 = Path(tempfile.gettempdir()) / 'wf-snapshot-gate-20261025-c18c46e' / 'decision.json'


@unittest.skipUnless((R00_DIR / 'decision.json').exists(), 'the real R00 gate output is not on this machine')
class DeriveHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wf-derive-'); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)

    def copy(self):
        dst = self.root / 'gate'
        for name in ('decision.json', 'build.json'): (dst).mkdir(exist_ok=True); shutil.copy2(R00_DIR / name, dst / name)
        shutil.copytree(R00_DIR / 'wheel', dst / 'wheel'); return dst

    def test_the_real_r00_pass_derives_a_proven_history_receipt_without_touching_the_source(self):
        before = (R00_DIR / 'decision.json').read_bytes()
        receipt = gate_history.derive(R00_DIR, self.root / 'CG-R00.json')
        self.assertEqual((R00_DIR / 'decision.json').read_bytes(), before)
        self.assertEqual((receipt['gate'], receipt['decision']), ('CG-R00', 'pass'))
        self.assertEqual(receipt['commit'], 'd467546c18650b5d798b76d378eac15655bf1521')
        self.assertEqual(receipt['provenance']['decision']['sha256'], gate_history.sha(R00_DIR / 'decision.json'))
        self.assertGreater(receipt['provenance']['wheel']['files_equal_to_commit_blobs'], 0)
        self.assertFalse(receipt['delivered']); self.assertFalse(receipt['owner_acceptance'])
        # it is history of d467546, NOT of the d3120c6 compat baseline: the drill cannot use it as previous build
        with self.assertRaises(LedgerError) as caught:
            release_bundle.Producer('R01', Path(tempfile.gettempdir()) / f'wf-derive-prod-{os.getpid()}', gate_history=[self.root / 'CG-R00.json'])
        shutil.rmtree(Path(tempfile.gettempdir()) / f'wf-derive-prod-{os.getpid()}', True)
        self.assertIn('compatibility scanner models only', str(caught.exception))

    def test_derivation_is_refused_when_identity_is_not_proven_on_disk(self):
        mutations = {'wheel bytes differ': lambda d: (d / 'wheel' / next((d / 'wheel').glob('*.whl')).name).write_bytes(b'x'),
                     'dirty build': lambda d: (d / 'build.json').write_text(json.dumps({**json.loads((d / 'build.json').read_text()), 'dirty': ['a.py']})),
                     'build names another commit': lambda d: (d / 'build.json').write_text(json.dumps({**json.loads((d / 'build.json').read_text()), 'commit': 'c' * 40})),
                     'gate refused': lambda d: (d / 'decision.json').write_text(json.dumps({**json.loads((d / 'decision.json').read_text(encoding='utf-8')), 'decision': 'refused'}))}
        for label, fn in mutations.items():
            with self.subTest(label):
                shutil.rmtree(self.root / 'gate', True); d = self.copy(); fn(d)
                with self.assertRaises((LedgerError, ValueError)): gate_history.derive(d, self.root / f'{len(label)}-{label[:4]}.json')
        (self.root / 'exists.json').write_text('{}')
        with self.assertRaises(LedgerError): gate_history.derive(R00_DIR, self.root / 'exists.json')


class RealSnapshotTests(unittest.TestCase):
    @unittest.skipUnless(SNAPSHOT.exists(), 'the 6366137 snapshot gate decision is not on this machine')
    def test_on_the_real_snapshot_every_cg_gate_is_refused_honestly(self):
        snap = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
        for release in release_check.PARTS:
            with self.subTest(release):
                verdict = {**bundle_verdict(release), 'commit': snap['commit'], 'wheel_sha256': snap['wheel_sha256']}
                result = delivery_gate.decide(release, snap, verdict, {**REVIEW, 'commit': snap['commit']})
                self.assertEqual(result['decision'], 'refused')
                self.assertTrue({r['code'] for r in result['reasons']} & {'acceptance-partial', 'acceptance-blocked'}, result['reasons'])
                self.assertNotIn('problem-unknown', {r['code'] for r in result['reasons']})
                self.assertNotIn('snapshot-contradictory', {r['code'] for r in result['reasons']})

    @unittest.skipUnless(SNAPSHOT_C18.exists(), 'the c18c46e snapshot gate decision is not on this machine')
    def test_the_real_c18c46e_snapshot_refuses_every_gate_and_names_its_global_problems(self):
        """Codex round 6 P1-2 on the real refused snapshot: every global problem it records (implementation failures in particular) is
        named in EVERY release's delivery gate, with the failing check ids, whatever that release's own acceptance is."""
        snap = json.loads(SNAPSHOT_C18.read_text(encoding='utf-8'))
        self.assertEqual(snap['decision'], 'refused')
        global_kinds = {p['kind'] for p in snap['problems'] if development_gate.problem_scope(p) == 'global'}
        failed = [f['check'] for p in snap['problems'] if p.get('kind') == 'implementation-checks' for f in p.get('failures', [])]
        for release in release_check.PARTS:
            with self.subTest(release):
                verdict = {**bundle_verdict(release), 'commit': snap['commit'], 'wheel_sha256': snap['wheel_sha256']}
                result = delivery_gate.decide(release, snap, verdict, {**REVIEW, 'commit': snap['commit']})
                codes = {r['code'] for r in result['reasons']}
                self.assertEqual(result['decision'], 'refused'); self.assertFalse(gate_history.is_passing_delivery_gate(result))
                self.assertLessEqual(global_kinds, codes, result['reasons'])
                self.assertNotIn('problem-unknown', codes); self.assertNotIn('snapshot-contradictory', codes, result['reasons'])
                detail = ' '.join(r['detail'] for r in result['reasons'] if r['code'] == 'implementation-checks')
                for check in failed: self.assertIn(check, detail)
                if failed: self.assertIn('implementation', codes)


if __name__ == '__main__':
    unittest.main()
