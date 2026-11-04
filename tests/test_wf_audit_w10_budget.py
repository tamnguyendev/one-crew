"""Audit W10 (T03/T32 subset): jobs bound to a root without root-budget share its one approved call budget.

Kept apart from tests/test_wf_root_budget.py, whose bytes are pinned by wfkit/development-manifest.json.
"""
import datetime as dt
import unittest

from onecrew import budget_core, solution_gate
from onecrew.control import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.task_intake import submit
from onecrew.v2 import plan as plans
from tests.test_v2_l1 import Fixture, plan_json


class BoundJobsWithoutRootBudgetTests(Fixture):
    """Audit W10: a root without the root-budget capability keeps its old budget semantics (no shared counter, no budget.group), but
    jobs bound to it with plan_selector under NEW keys may together be granted at most the one approved budget: a new key is not a
    new budget. Before: three bound jobs of 100 calls each under one 100-call approval were all admitted."""

    ROOTS = (('schema2', {}), ('storage-only', {'workflow': True, 'capabilities': ['namespaced-storage']}))

    def make(self, name, options, calls=100):
        plans.propose(self.ledger, name, plan_json(budget={'max_calls': calls, 'time': 30}), 'codex', **options)
        plans.approve(self.ledger, name, 'owner', 'fixture root without root-budget')

    def bound(self, name, key, calls, seconds=600):
        return submit(self.ledger, 'Inspect the document', key, plan_selector='plan-ns:' + name, max_calls=calls, max_seconds=seconds)

    def tasks(self):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]

    def test_w10_new_keys_cannot_multiply_one_approved_budget(self):
        for name, options in self.ROOTS:
            with self.subTest(root=name):
                self.make(name, options)
                first = self.bound(name, name + '-one', 100)
                self.assertNotIn('goal', first['budget'])
                before = self.tasks()
                for key in ('-two', '-three'):
                    with self.assertRaisesRegex(LedgerError, 'approved budget of 100 calls'):
                        self.bound(name, name + key, 100)
                self.assertEqual(self.tasks(), before)
                replay = self.bound(name, name + '-one', 100)                     # idempotent replay is the same grant, not a new one
                self.assertEqual(replay['id'], first['id'])
                with self.ledger.transaction() as conn:
                    state = plans.derive(self.ledger, conn, name)
                    self.assertIsNone(budget_core.group(conn, first['id']))
                    self.assertFalse(conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='budget.group'", (state['task_id'],)).fetchone())

    def test_w10_split_grants_sum_to_the_approved_budget(self):
        self.make('split', {})
        self.bound('split', 'part-one', 40); self.bound('split', 'part-two', 60)
        with self.assertRaisesRegex(LedgerError, 'approved budget of 100 calls'):
            self.bound('split', 'part-three', 1)

    def test_w10_gate_and_extension_count_sibling_grants(self):
        from onecrew import budget
        from onecrew.v2 import gate
        self.make('gated', {})
        child = self.bound('gated', 'bound-child', 40)
        gate.set_enforced(self.ledger, True, 'owner', 'fixture enforcement')
        migrate(self.ledger)
        control = Control(self.ledger)
        control.configure(child['id'], child['revision'], {'mode': 'test'})     # admitted: 40 of 100
        implicit = submit(self.ledger, 'Inspect the document', 'gated', max_calls=70, max_seconds=600)   # the old same-name job
        with self.assertRaisesRegex(LedgerError, 'approved plan budget of 100 calls'):
            solution_gate.check(self.ledger, implicit['id'])
        current = self.ledger.task(child['id'])['budget']
        end = dt.datetime.fromisoformat(child['created_at']) + dt.timedelta(minutes=20)
        with self.assertRaisesRegex(LedgerError, 'approved plan budget of 100'):
            budget.extend(control, child['id'], current['revision'], 'too-many', 50, end.isoformat(), 'fixture extension')


if __name__ == '__main__':
    unittest.main()
