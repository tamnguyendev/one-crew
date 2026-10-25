"""Delivery-gate receipt chain (92-task audit, W40-R01...RX2): (1) wfkit.gate writes CG-<release> receipts that wfkit.release_check accepts as
gate_history; a real old decision is only turned into history by derivation with provenance, never rewritten; (2) wfkit.delivery_gate runs
CG-Rnn from the development registry's acceptance, AI-run without the owner (03 section 4), refused while any part is partial/blocked;
(3) the producer uses the latest PASSING CG- receipt as previous build when gate history is given (the normal rule)."""
import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import LedgerError
from wfkit import delivery_gate, gate, gate_history, release_bundle, release_check
from wfkit.finalgate import identity

from test_wf_release_check import ReleaseCheckTests

R00_DIR = Path(r'D:\OneCrewRuns\wf-dev-logs\cg-r00')
SNAPSHOT = Path(tempfile.gettempdir()) / 'wf-snapshot-gate-20261025-6366137' / 'decision.json'


def load_tests(loader, tests, pattern):          # do not re-run the imported ReleaseCheckTests here
    suite = unittest.TestSuite()
    for case in (GateReceiptRoundTripTests, DeliveryGateTests, ProducerHistoryTests):
        own = sorted(n for n in vars(case) if n.startswith('test_'))      # only the tests this module defines (not the inherited fixture's)
        suite.addTests(case(n) for n in own)
    return suite


def gate_pass(artifact, release='R00'):
    build = {'release': release, 'commit': artifact['commit'], 'wheel_sha256': artifact['wheel_sha256'], 'dirty': []}
    install = {'ok': True, 'control_refused': True, 'wheel_sha256': artifact['wheel_sha256'], 'loaded': {}}
    return gate.decide(release, {'releases': {release: {'testcases': {}}}}, build, {}, install, {'ok': True})


class GateReceiptRoundTripTests(ReleaseCheckTests):
    def test_gate_decision_is_a_cg_receipt_release_check_accepts_as_history(self):
        decision = gate_pass(self.previous)
        self.assertEqual((decision['gate'], decision['decision']), ('CG-R00', 'pass'))
        self.assertEqual(identity(decision), identity(self.previous))
        decision['at'] = '2026-10-24T11:00:00Z'                              # before the fixture upgrade receipts
        self.bundle['gate_history'] = [self.ref(decision)]
        result = self.result(); self.assertEqual(result['decision'], 'pass', result); self.assertTrue(result['conditions']['INPUTS'])

    def test_the_old_shape_without_gate_id_is_not_history(self):
        decision = gate_pass(self.previous); decision['at'] = '2026-10-24T11:00:00Z'; del decision['gate']
        self.bundle['gate_history'] = [self.ref(decision)]
        self.refused('INPUTS'); self.assertIn('history has no passing delivery gate', ' '.join(r['detail'] for r in self.result()['reasons']))

    def test_a_refused_gate_or_another_build_is_not_history(self):
        refused = gate_pass(self.previous); refused['decision'] = 'refused'; refused['at'] = '2026-10-24T11:00:00Z'
        self.bundle['gate_history'] = [self.ref(refused)]; self.refused('INPUTS')
        other = gate_pass(self.current); other['at'] = '2026-10-24T11:00:00Z'
        self.bundle['gate_history'] = [self.ref(other)]; self.refused('INPUTS')


def snapshot(release='R01', statuses=('complete', 'complete')):
    return {'commit': 'b' * 40, 'wheel_sha256': '5' * 64, 'snapshot': {'intact': True},
            'implementation_checks': {'expected': 3, 'receipted': 3, 'failed': []},
            'acceptance': {release: {f'T9{i}': {'status': s, 'gaps': [] if s == 'complete' else [{'detail': 'not certified'}]} for i, s in enumerate(statuses)}}}


def bundle_verdict(release='R01', first_release=True):
    code = 'INPUTS(bootstrap)' if first_release else 'INPUTS'
    return {'decision': 'pass', 'release': release, 'commit': 'b' * 40, 'wheel_sha256': '5' * 64, 'first_release': first_release,
            'conditions': {code: True, **{f'T54.{i}': True for i in range(1, 6)}}, 'reasons': []}


REVIEW = {'result': 'pass', 'reviewer_model': 'gpt-5-codex', 'author_model': 'claude-opus', 'commit': 'b' * 40}


class DeliveryGateTests(unittest.TestCase):
    def test_all_complete_reviewed_and_packaged_passes_without_owner_and_chains_as_history(self):
        result = delivery_gate.decide('R01', snapshot(), bundle_verdict(), REVIEW)
        self.assertEqual(result['decision'], 'pass', result['reasons'])
        self.assertEqual((result['gate'], result['owner_acceptance'], result['delivered']), ('CG-R01', False, False))
        self.assertEqual(result['inputs_rule'], 'INPUTS(bootstrap)'); self.assertTrue(result['not_judged'])
        self.assertTrue(gate_history.is_passing_delivery_gate(result)); self.assertEqual(identity(result), {'commit': 'b' * 40, 'wheel_sha256': '5' * 64})

    def test_refused_while_any_part_is_partial_or_blocked_or_evidence_is_missing(self):
        cases = {'partial testcase': ('acceptance-partial', snapshot(statuses=('complete', 'partial')), bundle_verdict(), REVIEW),
                 'blocked testcase': ('acceptance-blocked', snapshot(statuses=('blocked',)), bundle_verdict(), REVIEW),
                 'no acceptance for the release': ('acceptance-missing', snapshot('R02'), bundle_verdict(), REVIEW),
                 'no independent review': ('independent-review', snapshot(), bundle_verdict(), None),
                 'reviewer is the author model': ('independent-review', snapshot(), bundle_verdict(), {**REVIEW, 'reviewer_model': 'claude-opus'}),
                 'review of another commit': ('independent-review', snapshot(), bundle_verdict(), {**REVIEW, 'commit': 'c' * 40}),
                 'bundle refused': ('packaging', snapshot(), {**bundle_verdict(), 'decision': 'refused'}, REVIEW),
                 'bundle of another build': ('packaging', snapshot(), {**bundle_verdict(), 'wheel_sha256': '6' * 64}, REVIEW),
                 'implementation check failed': ('implementation', {**snapshot(), 'implementation_checks': {'expected': 3, 'receipted': 3, 'failed': ['x']}}, bundle_verdict(), REVIEW),
                 'snapshot not intact': ('snapshot', {**snapshot(), 'snapshot': {'intact': False}}, bundle_verdict(), REVIEW),
                 'R00 is not this producer': ('unknown-release', snapshot('R00'), bundle_verdict('R00'), REVIEW)}
        for label, (code, snap, verdict, review) in cases.items():
            with self.subTest(label):
                release = 'R00' if label.startswith('R00') else 'R01'
                result = delivery_gate.decide(release, snap, verdict, review)
                self.assertEqual(result['decision'], 'refused'); self.assertIn(code, {r['code'] for r in result['reasons']})
                self.assertFalse(result['owner_acceptance']); self.assertFalse(gate_history.is_passing_delivery_gate(result))

class ProducerHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='wf-prod-history-'); cls.root = Path(cls.temp.name)
        cls.pin = release_bundle.build_baseline_wheel(cls.root / 'pin')
        decision = gate_pass({'commit': cls.pin['commit'], 'wheel_sha256': cls.pin['wheel_sha256']})
        decision.update(at='2026-10-20T00:00:00Z', wheel=cls.pin['wheel'], simulated=True, provenance={'kind': 'fixture', 'source': 'test fixture history'})
        cls.history = cls.root / 'CG-R00-fixture.json'; cls.history.write_text(json.dumps(decision), encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def out(self, tag):
        path = Path(tempfile.gettempdir()) / f'wf-prod-history-{os.getpid()}-{tag}'
        self.addCleanup(shutil.rmtree, path, True); return path

    def test_the_latest_passing_cg_receipt_is_the_previous_build(self):
        older = json.loads(self.history.read_text(encoding='utf-8')); older.update(decision='refused', at='2026-10-21T00:00:00Z')
        refused = self.root / 'CG-R00-refused.json'; refused.write_text(json.dumps(older), encoding='utf-8')
        producer = release_bundle.Producer('R01', self.out('ok'), gate_history=[self.history, refused])
        self.assertTrue(producer.baseline_pin['from_history'])
        producer.build()
        self.assertEqual(producer.identity('previous'), {'commit': self.pin['commit'], 'wheel_sha256': self.pin['wheel_sha256']})
        refs = producer.history_refs()
        self.assertEqual(len(refs), 2)
        for ref in refs: self.assertEqual(gate_history.sha(producer.out / ref['path']), ref['sha256'])

    def test_history_and_first_release_together_or_no_passing_history_are_refused(self):
        with self.assertRaises(LedgerError): release_bundle.Producer('R01', self.out('both'), first_release=True, gate_history=[self.history])
        refused = self.root / 'only-refused.json'
        refused.write_text(json.dumps({**json.loads(self.history.read_text(encoding='utf-8')), 'decision': 'refused'}), encoding='utf-8')
        with self.assertRaises(LedgerError): release_bundle.Producer('R01', self.out('none'), gate_history=[refused])
        missing = self.root / 'no-wheel.json'
        missing.write_text(json.dumps({**json.loads(self.history.read_text(encoding='utf-8')), 'wheel': str(self.root / 'absent.whl')}), encoding='utf-8')
        with self.assertRaises(LedgerError): release_bundle.Producer('R01', self.out('nowheel'), gate_history=[missing])

    def test_without_history_the_producer_keeps_the_bootstrap_or_old_behaviour(self):
        producer = release_bundle.Producer('R01', self.out('plain'))
        self.assertEqual(producer.history_paths, []); self.assertIsNone(producer.baseline_pin)
        self.assertIsNone(release_bundle.parser().parse_args(['R01', '--out', 'x']).gate_history)


if __name__ == '__main__':
    unittest.main()
