"""W11b / T25 [E4] (round 6, decided 25/10 under delegated authority): the T19 test-integrity rule is a workflow-root rule.

Sources: 04-TASKS W11b "plan schema 2 giữ semantics", not-done "Root schema 2 bị áp luật mới"; 05 T25 [E4] (forbidden) "Root schema 2 bị
đối xử theo luật mới"; 00 §6 "plan schema 2 (v2.1/v2.2) giữ nguyên nghĩa".

Counter-example pair on the same fixture as tests/test_wf_test_integrity (real temporary Git project, the "worker" is the test editing the file):
  - a schema-2 root (plain propose/approve, no workflow_version) whose assert is loosened -> old behaviour: the command's own result (pass),
    no test_integrity record, no U1;
  - a workflow root with the same loosened assert -> T19 as today: red, U1.
  - mutant: if the gate is removed (integrity_applies always true), the schema-2 root turns red -> the gate is load-bearing.
"""
import os
import sys
from unittest import mock

from onecrew.v2 import plan as plans, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_test_integrity import TEST_FILE

LOOSENED = TEST_FILE.replace('self.assertEqual(pathlib.Path("a.txt").read_text(), "one" + chr(10))', 'self.assertTrue(True)')
DELETED = TEST_FILE.replace('    def test_b_other(self):' + chr(10) + '        self.assertTrue(True)' + chr(10), '')


class Schema2KeepsTheOldVerdictRule(Fixture):
    def make(self, workflow):
        (self.root / 'tests').mkdir()
        (self.root / 'tests' / 'test_x.py').write_text(TEST_FILE)
        (self.root / '.gitignore').write_text('__pycache__/' + chr(10))
        self.git('add', '.'); self.git('commit', '-qm', 'tests')
        value = plan_json(milestones=[milestone(argv=[sys.executable, 'tests/test_x.py'])], scope={'owned': ['a.txt', 'tests/test_x.py']})
        value['understanding']['target']['paths'] = ['a.txt', 'tests/test_x.py']
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=workflow)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'

    def rewrite(self, text):
        (self.root / 'tests' / 'test_x.py').write_text(text)
        self.git('add', 'tests/test_x.py'); self.git('commit', '-qm', 'edit tests')

    def last(self):
        return [p for k, p in self.events() if k == 'verdict.recorded'][-1]

    def test_schema2_root_loosened_assert_keeps_the_old_rule(self):
        self.make(workflow=False)
        self.assertNotIn('workflow_version', plans.show(self.ledger, 'P1'))
        self.rewrite(LOOSENED)
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')            # the command passed: old rule, nothing new applied
        event = self.last()
        self.assertEqual(event['result'], 'pass')
        self.assertNotIn('test_integrity', event)
        self.assertNotIn('plan.revised', self.kinds())

    def test_schema2_root_deleted_test_keeps_the_old_rule(self):
        self.make(workflow=False)
        self.rewrite(DELETED)
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        self.assertNotIn('test_integrity', self.last())

    def test_workflow_root_loosened_assert_is_u1_as_today(self):
        self.make(workflow=True)
        self.rewrite(LOOSENED)
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'failed')
        event = self.last()
        self.assertEqual(event['result'], 'fail')
        self.assertEqual(event['test_integrity']['classification'], 'U1')

    def test_mutant_without_the_gate_turns_the_schema2_root_red(self):
        self.make(workflow=False)
        self.rewrite(LOOSENED)
        with mock.patch.object(verdict, 'integrity_applies', return_value=True):
            shown = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'failed')            # the gate above is what keeps schema 2 on the old rule


if __name__ == '__main__':
    import unittest
    unittest.main()
