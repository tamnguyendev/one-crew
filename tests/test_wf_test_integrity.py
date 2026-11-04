"""W05 / T19: the milestone gate is red when the suite was weakened (assert loosened, test deleted); a new test is accepted with provenance.

Real temporary Git project with its own small test file; the milestone command runs that file. The "worker" is the test itself editing
the file (interface only). Nothing asks the owner.
"""
import os
import sys

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, verdict, test_integrity
from tests.test_v2_l1 import Fixture, plan_json, milestone

TEST_FILE = '\n'.join([
    'import unittest, pathlib',
    'class ATests(unittest.TestCase):',
    '    def test_a_row_count(self):',
    '        self.assertEqual(pathlib.Path("a.txt").read_text(), "one" + chr(10))',
    '    def test_b_other(self):',
    '        self.assertTrue(True)',
    'if __name__ == "__main__": unittest.main()', ''])


class TestIntegrityTests(Fixture):
    WORKFLOW = True       # W11b/T25 [E4] (round 6): T19 is a workflow-root rule; a schema-2 root keeps the old verdict (tests/test_wf_w11b_schema2_integrity)

    def setUp(self):
        super().setUp()
        (self.root / 'tests').mkdir()
        (self.root / 'tests' / 'test_x.py').write_text(TEST_FILE)
        (self.root / '.gitignore').write_text('__pycache__/' + chr(10))
        self.git('add', '.'); self.git('commit', '-qm', 'tests')
        argv = [sys.executable, 'tests/test_x.py']
        value = plan_json(milestones=[milestone(argv=argv)], scope={'owned': ['a.txt', 'tests/test_x.py']})
        value['understanding']['target']['paths'] = ['a.txt', 'tests/test_x.py']
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=self.WORKFLOW)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'

    def rewrite(self, text):
        (self.root / 'tests' / 'test_x.py').write_text(text)
        self.git('add', 'tests/test_x.py'); self.git('commit', '-qm', 'edit tests')

    def last(self):
        return [p for k, p in self.events() if k == 'verdict.recorded'][-1]

    def test_a_loosened_assert_makes_the_gate_red_as_u1(self):
        self.rewrite(TEST_FILE.replace('self.assertEqual(pathlib.Path("a.txt").read_text(), "one" + chr(10))', 'self.assertTrue(True)'))
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'failed')                                     # [E1] (a), [E3]
        event = self.last()
        self.assertEqual(event['result'], 'fail')
        self.assertEqual(event['test_integrity']['classification'], 'U1')
        self.assertEqual([(w['test'], w['kind']) for w in event['test_integrity']['weakened']], [('ATests.test_a_row_count', 'changed')])
        self.assertNotEqual(event['test_integrity']['base'], event['artifact_sha'])

    def test_b_a_deleted_test_makes_the_gate_red(self):
        self.rewrite(TEST_FILE.replace('    def test_b_other(self):' + chr(10) + '        self.assertTrue(True)' + chr(10), ''))
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'failed')                                     # [E1] (b)
        self.assertEqual([(w['test'], w['kind']) for w in self.last()['test_integrity']['weakened']], [('ATests.test_b_other', 'removed')])

    def test_c_an_added_test_is_accepted_with_provenance_and_no_request(self):
        before = len(self.ledger.requests())
        self.rewrite(TEST_FILE.replace('if __name__', '    def test_c_new(self):' + chr(10) + '        self.assertEqual(1, 1)' + chr(10) + 'if __name__'))
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')                                     # [E2] (c)
        event = self.last()
        self.assertEqual([a['test'] for a in event['test_integrity']['added']], ['ATests.test_c_new'])
        self.assertIsNone(event['test_integrity']['classification'])
        receipt = self.store_read(event['test_integrity']['receipt'])
        self.assertEqual(receipt['provenance']['by'], 'codex'); self.assertIn('base_source', receipt)
        self.assertEqual(len(self.ledger.requests()), before)                                          # [E4]

    def test_unchanged_suite_records_nothing_extra(self):
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        self.assertNotIn('test_integrity', self.last())

    def test_compare_ignores_non_test_files_and_renames_keep_tests(self):
        base = self.git('rev-parse', 'HEAD^{tree}')
        (self.root / 'a.txt').write_text('two' + chr(10)); self.git('add', 'a.txt'); self.git('commit', '-qm', 'a')
        self.git('mv', 'tests/test_x.py', 'tests/test_y.py'); self.git('commit', '-qm', 'rename')
        report = test_integrity.compare(self.root, base, self.git('rev-parse', 'HEAD^{tree}'))
        self.assertEqual((report['weakened'], report['added']), ([], []))
        self.assertEqual([f['status'] for f in report['files']], ['R'])

    def store_read(self, ref):
        import json
        from onecrew.snapshots import Snapshots
        return json.loads(Snapshots(self.ledger.state_root).read_blob(ref))
