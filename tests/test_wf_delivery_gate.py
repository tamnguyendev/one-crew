"""Delivery-gate receipt chain (92-task audit, W40-R01...RX2): (1) wfkit.gate writes CG-<release> receipts that wfkit.release_check accepts as
gate_history; a real old decision is only turned into history by derivation with provenance, never rewritten; (2) wfkit.delivery_gate runs
CG-Rnn from the development registry's acceptance, AI-run without the owner (03 section 4), refused while any part is partial/blocked;
(3) the producer uses the latest PASSING CG- receipt as previous build when gate history is given (the normal rule)."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import LedgerError
from wfkit import delivery_gate, development_gate, gate, gate_history, release_bundle, release_check
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

    def test_a_cli_delivery_receipt_is_history_only_when_no_global_problem_blocks_it(self):
        """delivery_gate CLI receipt -> gate_history.is_passing_delivery_gate -> release_check INPUTS of the next release."""
        ident = identity(self.previous)
        def snap(problems=()):
            s = snapshot(problems=problems, others={'R02': ('partial',)}); s.update(ident); s['snapshot']['commit'] = ident['commit']; return s
        verdict, review = {**bundle_verdict(), **ident}, {**REVIEW, 'commit': ident['commit']}
        for label, problems, passing in (('valid, only R02 acceptance open', (), True), ('kit-guard', [GLOBAL['kit-guard']], False),
                                         ('selected-only', [GLOBAL['selected-only']], False), ('installed-origin', [GLOBAL['installed-origin']], False)):
            with self.subTest(label), tempfile.TemporaryDirectory(prefix='wf-cg-chain-') as tmp:
                code, receipt = run_cli(tmp, 'R01', snap(problems), verdict, review)
                self.assertEqual((code == 0, gate_history.is_passing_delivery_gate(receipt)), (passing, passing), receipt['reasons'])
                receipt['at'] = '2026-10-24T11:00:00Z'                      # before the fixture upgrade receipts (the CLI stamps now)
                self.bundle['gate_history'] = [self.ref(receipt)]
                if passing:
                    result = self.result(); self.assertEqual(result['decision'], 'pass', result); self.assertTrue(result['conditions']['INPUTS'])
                else:
                    self.refused('INPUTS')


COMMIT, WHEEL = 'b' * 40, '5' * 64
ROOT = Path(__file__).resolve().parents[1]


def real_global_problems():
    """{kind: problem} exactly as wfkit.development_gate.decide writes them (one call with every global fact wrong), plus the three kinds
    that development_gate.intact/finish add when the snapshot moved. The schema is the snapshot gate's own, not a test copy."""
    config = {'releases': {'R01': {'testcases': {'c1': {'kind': 'unittest', 'modules': ['tests.test_x']}}, 'acceptance': {'T90': {'status': 'complete'}}}}}
    decision = development_gate.decide(config, ['R01'], {'commit': COMMIT, 'dirty': ['a.py']}, {}, {}, {'ok': False}, only=['R01/c1'], document={})
    problems = {p['kind']: p for p in decision['problems']}
    problems.update({'snapshot-moved': {'kind': 'snapshot-moved', 'detail': 'HEAD moved'}, 'snapshot-dirty': {'kind': 'snapshot-dirty', 'detail': 'edited'},
                     'external-source-changed': {'kind': 'external-source-changed', 'detail': 'doc folder changed'}})
    return problems


GLOBAL = real_global_problems()
SNAPSHOT_KINDS = {'snapshot-moved', 'snapshot-dirty', 'external-source-changed'}


def criteria(statuses):
    return {f'T9{i}': {'status': s, 'gaps': [] if s == 'complete' else [{'detail': 'not certified'}]} for i, s in enumerate(statuses)}


def snapshot(release='R01', statuses=('complete', 'complete'), others=None, problems=()):
    """A snapshot-gate decision.json shaped like development_gate.decide + finish, internally consistent: every non-complete criterion has
    its acceptance problem, decision/release_delivery follow the problems, intact/failed follow the global problems given."""
    acceptance = {release: criteria(statuses), **{r: criteria(s) for r, s in (others or {}).items()}}
    found = [{'kind': 'acceptance-' + c['status'], 'release': r, 'testcase': t, 'gaps': c['gaps']}
             for r, body in acceptance.items() for t, c in body.items() if c['status'] != 'complete']
    problems = [copy.deepcopy(p) for p in problems] + found
    failed = [f for p in problems if p.get('kind') == 'implementation-checks' for f in p.get('failures', [])]
    return {'decision': 'refused' if problems else 'pass', 'release_delivery': not problems, 'releases': list(acceptance),
            'commit': COMMIT, 'wheel_sha256': WHEEL, 'owner_acceptance': False,
            'snapshot': {'commit': COMMIT, 'intact': not any(p.get('kind') in SNAPSHOT_KINDS for p in problems)},
            'implementation_checks': {'expected': 3, 'receipted': 3 - len(failed), 'failed': failed},
            'acceptance': acceptance, 'problems': problems}


def bundle_verdict(release='R01', first_release=True):
    code = 'INPUTS(bootstrap)' if first_release else 'INPUTS'
    return {'decision': 'pass', 'release': release, 'commit': COMMIT, 'wheel_sha256': WHEEL, 'first_release': first_release,
            'conditions': {code: True, **{f'T54.{i}': True for i in range(1, 6)}}, 'reasons': []}


REVIEW = {'result': 'pass', 'reviewer_model': 'gpt-5-codex', 'author_model': 'claude-opus', 'commit': COMMIT}


def run_cli(tmp, release, snap, verdict, review):
    """The real CLI (python -m wfkit.delivery_gate) in a subprocess; returns (exit code, receipt)."""
    tmp = Path(tmp); paths = {}
    for name, value in (('snapshot', snap), ('bundle', verdict), ('review', review)):
        paths[name] = tmp / f'{name}.json'; paths[name].write_text(json.dumps(value), encoding='utf-8')
    out = tmp / f'CG-{release}.json'
    env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE', 'ONECREW_ACTOR')}
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(ROOT / 'tests')])
    code = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'wfkit.delivery_gate', release, '--snapshot', str(paths['snapshot']),
                           '--bundle', str(paths['bundle']), '--review', str(paths['review']), '--out', str(out)],
                          cwd=str(ROOT), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300).returncode
    return code, json.loads(out.read_text(encoding='utf-8'))


class DeliveryGateTests(unittest.TestCase):
    def assertRefused(self, result, *codes):
        self.assertEqual(result['decision'], 'refused', result['reasons'])
        self.assertFalse(gate_history.is_passing_delivery_gate(result))
        for code in codes: self.assertIn(code, {r['code'] for r in result['reasons']}, result['reasons'])

    def test_classification_lives_in_the_snapshot_gate_and_covers_every_kind_it_writes(self):
        self.assertEqual(set(GLOBAL), set(development_gate.GLOBAL_PROBLEMS))
        for kind in ('kit-guard', 'installed-origin', 'document-selfcheck', 'dirty-build', 'selected-only', 'implementation-checks', 'missing-build'):
            self.assertEqual(development_gate.problem_scope(GLOBAL[kind]), 'global', kind)
        self.assertEqual(development_gate.problem_scope({'kind': 'acceptance-partial', 'release': 'R01', 'testcase': 'T1', 'gaps': []}), 'release')
        for bad in ({'kind': 'mystery'}, {'kind': 'acceptance-complete', 'release': 'R01', 'testcase': 'T1'}, {'kind': 'acceptance-partial'}, 'kit-guard', None):
            self.assertIsNone(development_gate.problem_scope(bad), bad)

    def test_each_global_problem_alone_refuses_every_release_gate(self):
        for kind, problem in sorted(GLOBAL.items()):
            for release in ('R01', 'R05', 'RX2'):
                with self.subTest(kind=kind, release=release):
                    self.assertRefused(delivery_gate.decide(release, snapshot(release, problems=[problem]), bundle_verdict(release), REVIEW), kind)
                    # Codex's literal mutation: the valid fixture, decision refused, problems = [that one global problem]
                    valid = snapshot(release); valid.update(decision='refused', release_delivery=False, problems=[copy.deepcopy(problem)])
                    self.assertRefused(delivery_gate.decide(release, valid, bundle_verdict(release), REVIEW), kind)

    def test_global_problems_in_combination_are_all_named(self):
        combo = [GLOBAL[k] for k in ('kit-guard', 'installed-origin', 'document-selfcheck', 'dirty-build', 'selected-only')]
        result = delivery_gate.decide('R01', snapshot(problems=combo, others={'R02': ('partial',)}), bundle_verdict(), REVIEW)
        self.assertRefused(result, 'kit-guard', 'installed-origin', 'document-selfcheck', 'dirty-build', 'selected-only')
        result = delivery_gate.decide('R01', snapshot(statuses=('partial',), problems=[GLOBAL['implementation-checks'], GLOBAL['snapshot-dirty']]), bundle_verdict(), REVIEW)
        self.assertRefused(result, 'implementation-checks', 'snapshot-dirty', 'acceptance-partial', 'snapshot', 'implementation')
        self.assertIn('R01/c1', ' '.join(r['detail'] for r in result['reasons'] if r['code'] == 'implementation-checks'))

    def test_unknown_or_malformed_problem_refuses(self):
        for label, problem in {'unknown kind': {'kind': 'mystery', 'detail': 'new check'}, 'no kind': {'detail': 'x'}, 'not an object': 'kit-guard',
                               'acceptance without release': {'kind': 'acceptance-partial', 'testcase': 'T1', 'gaps': []},
                               'acceptance-complete is not a problem kind': {'kind': 'acceptance-complete', 'release': 'R02', 'testcase': 'T1'}}.items():
            with self.subTest(label):
                snap = snapshot(); snap.update(decision='refused', release_delivery=False, problems=[problem])
                self.assertRefused(delivery_gate.decide('R01', snap, bundle_verdict(), REVIEW), 'problem-unknown')

    def test_missing_required_snapshot_fields_refuse(self):
        def drop(path):
            snap = snapshot(); node = snap
            for key in path[:-1]: node = node[key]
            del node[path[-1]]; return snap
        for path in (('problems',), ('decision',), ('snapshot',), ('snapshot', 'intact'), ('snapshot', 'commit'), ('implementation_checks',),
                     ('implementation_checks', 'failed'), ('implementation_checks', 'expected'), ('releases',), ('acceptance',), ('commit',), ('wheel_sha256',)):
            with self.subTest('/'.join(path)):
                self.assertEqual(delivery_gate.decide('R01', drop(path), bundle_verdict(), REVIEW)['decision'], 'refused')
        self.assertRefused(delivery_gate.decide('R01', None, bundle_verdict(), REVIEW), 'snapshot-malformed')
        self.assertRefused(delivery_gate.decide('R01', drop(('problems',)), bundle_verdict(), REVIEW), 'snapshot-malformed')
        self.assertRefused(delivery_gate.decide('R01', drop(('snapshot', 'intact')), bundle_verdict(), REVIEW), 'snapshot-malformed')

    def test_contradictory_snapshot_refuses(self):
        def other_partial(): return snapshot(others={'R02': ('partial',)})
        cases = {'pass with problems': lambda s: s.update(decision='pass', release_delivery=True),
                 'refused without problems': lambda s: s.update(decision='refused', release_delivery=False, problems=[]),
                 'release_delivery disagrees with decision': lambda s: s.update(release_delivery=True),
                 'unknown decision': lambda s: s.update(decision='maybe'),
                 'inner snapshot of another commit': lambda s: s['snapshot'].update(commit='c' * 40),
                 'failed checks without their problem': lambda s: s['implementation_checks'].update(failed=[{'check': 'R01/c1', 'reason': 'x'}]),
                 'not intact without a snapshot problem': lambda s: s['snapshot'].update(intact=False),
                 'other release problem names a complete criterion': lambda s: s['acceptance']['R02']['T90'].update(status='complete', gaps=[]),
                 'other release problem for a release not in the run': lambda s: s['problems'][0].update(release='R07'),
                 'own incomplete criterion without its problem': lambda s: (s['acceptance']['R01']['T90'].update(status='partial', gaps=[{'detail': 'x'}]))}
        for label, mutate in cases.items():
            with self.subTest(label):
                snap = other_partial(); mutate(snap)
                self.assertRefused(delivery_gate.decide('R01', snap, bundle_verdict(), REVIEW))
        snap = snapshot(); snap['releases'] = ['R02']
        self.assertRefused(delivery_gate.decide('R01', snap, bundle_verdict(), REVIEW), 'release-not-in-snapshot')

    def test_only_another_releases_acceptance_blocks_so_this_gate_passes(self):
        snap = snapshot(others={'R02': ('partial', 'complete'), 'PL': ('blocked',)})
        self.assertEqual(snap['decision'], 'refused')
        result = delivery_gate.decide('R01', snap, bundle_verdict(), REVIEW)
        self.assertEqual(result['decision'], 'pass', result['reasons']); self.assertTrue(gate_history.is_passing_delivery_gate(result))
        self.assertEqual(result['other_release_problems'], {'R02': 1, 'PL': 1})
        self.assertRefused(delivery_gate.decide('R02', snap, bundle_verdict('R02'), REVIEW), 'acceptance-partial')

    def test_build_identity_must_agree_across_snapshot_bundle_and_review(self):
        cases = {'bundle commit': ({**bundle_verdict(), 'commit': 'c' * 40}, REVIEW, 'packaging'),
                 'bundle wheel': ({**bundle_verdict(), 'wheel_sha256': '6' * 64}, REVIEW, 'packaging'),
                 'bundle of another release': (bundle_verdict('R02'), REVIEW, 'packaging'),
                 'review commit': (bundle_verdict(), {**REVIEW, 'commit': 'c' * 40}, 'independent-review'),
                 'review commit missing': (bundle_verdict(), {k: v for k, v in REVIEW.items() if k != 'commit'}, 'independent-review'),
                 'review wheel': (bundle_verdict(), {**REVIEW, 'wheel_sha256': '6' * 64}, 'independent-review')}
        for label, (verdict, review, code) in cases.items():
            with self.subTest(label): self.assertRefused(delivery_gate.decide('R01', snapshot(), verdict, review), code)
        bad = snapshot(); bad['wheel_sha256'] = 'not-a-hash'
        self.assertRefused(delivery_gate.decide('R01', bad, bundle_verdict(), REVIEW), 'identity')

    def test_the_cli_refuses_a_global_problem_and_passes_the_valid_case(self):
        with tempfile.TemporaryDirectory(prefix='wf-cg-cli-') as tmp:
            code, receipt = run_cli(Path(tmp), 'R01', snapshot(problems=[GLOBAL['kit-guard']]), bundle_verdict(), REVIEW)
            self.assertEqual((code, receipt['decision']), (1, 'refused')); self.assertIn('kit-guard', {r['code'] for r in receipt['reasons']})
            self.assertFalse(gate_history.is_passing_delivery_gate(receipt))
        with tempfile.TemporaryDirectory(prefix='wf-cg-cli-') as tmp:
            code, receipt = run_cli(Path(tmp), 'R01', snapshot(others={'R02': ('partial',)}), bundle_verdict(), REVIEW)
            self.assertEqual((code, receipt['decision']), (0, 'pass'), receipt['reasons']); self.assertTrue(gate_history.is_passing_delivery_gate(receipt))
            self.assertEqual(set(receipt['sources']), {'snapshot', 'bundle', 'review'})

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
