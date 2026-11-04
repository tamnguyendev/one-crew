"""T19 [E1] (b) gap (R04 W05): a DELETED approved test makes the milestone gate red AND is classified U1.

The existing tests/test_wf_test_integrity.test_b asserts only the red state and the 'removed' kind; the U1 classification, the
fail result, the stored integrity receipt (diff names the deleted case) and the different suite trees were not asserted for (b).
Same fixture as tests/test_wf_test_integrity (temporary Git project; the "worker" is the test editing the file). The reason
"lam yeu bo kiem" is recorded structurally (weakened[].kind == 'removed' + classification 'U1'); there is no free-text reason field.
"""
import os
import sys
from unittest import mock

from onecrew.v2 import plan as plans, verdict, test_integrity
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_test_integrity import TEST_FILE

DELETED = TEST_FILE.replace('    def test_b_other(self):' + chr(10) + '        self.assertTrue(True)' + chr(10), '')


class DeletedTestIsU1(Fixture):
    def setUp(self):
        super().setUp()
        (self.root / 'tests').mkdir()
        (self.root / 'tests' / 'test_x.py').write_text(TEST_FILE)
        (self.root / '.gitignore').write_text('__pycache__/' + chr(10))
        self.git('add', '.'); self.git('commit', '-qm', 'tests')
        value = plan_json(milestones=[milestone(argv=[sys.executable, 'tests/test_x.py'])], scope={'owned': ['a.txt', 'tests/test_x.py']})
        value['understanding']['target']['paths'] = ['a.txt', 'tests/test_x.py']
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True)      # W11b/T25 [E4] (round 6): T19 is a workflow-root rule
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'
        (self.root / 'tests' / 'test_x.py').write_text(DELETED)
        self.git('add', 'tests/test_x.py'); self.git('commit', '-qm', 'delete a test')

    def store_read(self, ref):
        import json
        from onecrew.snapshots import Snapshots
        return json.loads(Snapshots(self.ledger.state_root).read_blob(ref))

    def last(self):
        return [p for k, p in self.events() if k == 'verdict.recorded'][-1]

    def test_e1_b_deleted_test_is_red_fail_and_classified_u1_with_receipt(self):
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'failed')                      # [E1] red
        event = self.last()
        self.assertEqual(event['result'], 'fail')                                         # [E3] no green receipt
        self.assertNotIn('milestone.passed', self.kinds())
        integrity = event['test_integrity']
        self.assertEqual(integrity['classification'], 'U1')                               # [E1] classified U1
        self.assertEqual([(w['test'], w['kind']) for w in integrity['weakened']], [('ATests.test_b_other', 'removed')])
        self.assertNotEqual(integrity['base'], event['artifact_sha'])                     # suite tree before/after differ
        receipt = self.store_read(integrity['receipt'])                                   # stored diff names the deleted case
        self.assertEqual(receipt['classification'], 'U1')
        self.assertEqual([(w['test'], w['kind']) for w in receipt['weakened']], [('ATests.test_b_other', 'removed')])
        self.assertEqual(receipt['provenance']['by'], 'codex')

    def test_e1_b_mutant_hiding_the_deletion_turns_the_gate_green(self):
        """Counter-example: if the comparison stops reporting the removal, the same run passes -> the U1 test above is load-bearing."""
        real = test_integrity.compare
        def blind(directory, base, current):
            report = real(directory, base, current)
            return dict(report, weakened=[w for w in report['weakened'] if w['kind'] != 'removed'])
        with mock.patch.object(test_integrity, 'compare', blind):
            shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        self.assertNotEqual((self.last().get('test_integrity') or {}).get('classification'), 'U1')

    def test_e1_integrity_result_maps_a_weakened_suite_to_fail(self):
        self.assertEqual(verdict.integrity_result('pass', {'weakened': [{'kind': 'removed'}]}), 'fail')
        self.assertEqual(verdict.integrity_result('pass', None), 'pass')                 # counter-example: unweakened stays pass
