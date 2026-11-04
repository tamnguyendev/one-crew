"""W05 audit counter-examples (T19/T25): changes of acceptance that the comparators classified routine.

(a) an internal-plan revise that splits/renames a node and drops its check, or moves a check to another node with a cut threshold;
(b) a weakened shared helper under the test directory (not itself discoverable) imported by an approved test;
(c) a contract amend that narrows a command verifier's cwd or changes the reviewer provider/model.
"""
import copy
import unittest
import sys

from onecrew.v2 import acceptance_diff as ad, plan as plans, verdict, test_integrity
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone
from tests.test_wf_engine import node


class NodeSplitTests(unittest.TestCase):
    def test_split_node_with_new_anything_checks_is_u1(self):
        before = [node('T'), node('I', ['T'], integration=True, write=())]
        t1, t2 = node('T1'), node('T2')
        t1['checks'] = [{'id': 'c1', 'spec': 'anything'}]; t2['checks'] = [{'id': 'c2', 'spec': 'anything'}]
        after = [t1, t2, node('I', ['T1', 'T2'], integration=True, write=())]
        result = ad.classify_nodes(before, after, ['O1'])
        self.assertEqual(result['classification'], 'U1')
        self.assertIn('T.checks.check-T', [c['path'] for c in result['changes'] if c['kind'] == 'removed_check'])

    def test_check_moved_to_a_renamed_node_with_a_cut_threshold_is_u1(self):
        a = node('A'); a['checks'] = [{'id': 'cov', 'spec': 'Coverage is at least 90%'}]
        a2 = node('A2'); a2['checks'] = [{'id': 'cov', 'spec': 'Coverage is at least 10%'}]
        result = ad.classify_nodes([a], [a2], ['O1'])
        self.assertEqual(result['classification'], 'U1')
        self.assertIn('threshold', [c['kind'] for c in result['changes']])

    def test_renamed_node_keeping_its_check_wording_is_routine(self):
        """Counter-example: a pure rename (check reappears, wording only) stays routine."""
        a = node('A'); a['checks'] = [{'id': 'cov', 'spec': 'Coverage is at least 90%'}]
        a2 = node('A2'); a2['checks'] = [{'id': 'cov-a2', 'spec': 'coverage is at least 90%.'}]
        result = ad.classify_nodes([a], [a2], ['O1'])
        self.assertEqual(result['classification'], 'routine', result['changes'])


class ContractVerifierTests(unittest.TestCase):
    def pair(self, before, mutate):
        after = copy.deepcopy(before); mutate(after)
        return ad.classify_contract(before, after)

    def test_narrowed_command_cwd_is_u1(self):
        before = plan_json(milestones=[milestone(argv=['python', '-m', 'unittest'], **{})])
        before['milestones'][0]['verifier']['config']['cwd'] = '.'
        result = self.pair(before, lambda c: c['milestones'][0]['verifier']['config'].__setitem__('cwd', 'tests/easy'))
        self.assertEqual(result['classification'], 'U1')
        self.assertIn('milestones.M1.cwd', [c['path'] for c in result['changes']])

    def test_changed_reviewer_provider_or_model_is_u1(self):
        before = plan_json(milestones=[reviewer_milestone()])
        model = self.pair(before, lambda c: c['milestones'][0]['verifier']['config'].__setitem__('model', 'claude-sonnet-5-5'))
        self.assertEqual(model['classification'], 'U1'); self.assertIn('milestones.M1.model', [c['path'] for c in model['changes']])
        provider = self.pair(before, lambda c: c['milestones'][0]['verifier']['config'].__setitem__('provider', 'codex'))
        self.assertEqual(provider['classification'], 'U1'); self.assertIn('milestones.M1.provider', [c['path'] for c in provider['changes']])

    def test_unchanged_verifier_stays_routine(self):
        before = plan_json(milestones=[reviewer_milestone()])
        self.assertEqual(self.pair(before, lambda c: None)['classification'], 'routine')


TEST_A = '\n'.join([
    'import unittest, sys, pathlib',
    'sys.path.insert(0, str(pathlib.Path(__file__).parent))',
    'from helpers import value',
    'class ATests(unittest.TestCase):',
    '    def test_a(self):',
    '        value()',
    'if __name__ == "__main__": unittest.main()', ''])
HELPER = '\n'.join(['def value():', '    x = 42', '    assert x == 42', ''])
WEAK = '\n'.join(['def value():', '    pass', ''])


class SharedHelperTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.root / 'tests').mkdir()
        (self.root / 'tests' / 'test_a.py').write_text(TEST_A)
        (self.root / 'tests' / 'helpers.py').write_text(HELPER)
        (self.root / '.gitignore').write_text('__pycache__/' + chr(10))
        self.git('add', '.'); self.git('commit', '-qm', 'tests')

    def test_weakened_shared_helper_is_insufficient(self):
        base = self.git('rev-parse', 'HEAD^{tree}')
        (self.root / 'tests' / 'helpers.py').write_text(WEAK); self.git('add', '-A'); self.git('commit', '-qm', 'weaken helper')
        report = test_integrity.compare(self.root, base, self.git('rev-parse', 'HEAD^{tree}'))
        self.assertEqual(report['weakened'], [])
        self.assertEqual([(i['file'], i['kind']) for i in report['insufficient']], [('tests/helpers.py', 'support_changed')])

    def test_weakened_shared_helper_does_not_pass_the_gate(self):
        import os
        value = plan_json(milestones=[milestone(argv=[sys.executable, 'tests/test_a.py'])], scope={'owned': ['a.txt', 'tests/']})
        value['understanding']['target']['paths'] = ['a.txt', 'tests/test_a.py']
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True)      # W11b/T25 [E4] (round 6): T19 is a workflow-root rule
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'
        (self.root / 'tests' / 'helpers.py').write_text(WEAK); self.git('add', '-A'); self.git('commit', '-qm', 'weaken helper')
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertNotEqual(shown['milestones'][0]['state'], 'passed')
        event = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        self.assertEqual(event['result'], 'inconclusive')

    def test_a_reformatted_helper_records_nothing(self):
        base = self.git('rev-parse', 'HEAD^{tree}')
        (self.root / 'tests' / 'helpers.py').write_text(HELPER.replace('x == 42', '(x == 42)')); self.git('add', '-A'); self.git('commit', '-qm', 'reformat')
        report = test_integrity.compare(self.root, base, self.git('rev-parse', 'HEAD^{tree}'))
        self.assertEqual(report['insufficient'], [])

    def test_unchanged_helper_records_nothing(self):
        base = self.git('rev-parse', 'HEAD^{tree}')
        (self.root / 'a.txt').write_text('two' + chr(10)); self.git('add', '-A'); self.git('commit', '-qm', 'a')
        report = test_integrity.compare(self.root, base, self.git('rev-parse', 'HEAD^{tree}'))
        self.assertEqual(report['insufficient'], [])
