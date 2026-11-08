"""Audit W12a (T48a follow-up): plan names in job-submit request keys, Windows device names and trailing dot/space.

Kept apart from tests/test_wf_plan_names.py, whose bytes are pinned by wfkit/namespace-lineage.json.
"""
import sqlite3
import unittest

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans
import tests.wf_oldversion as ov
from tests.test_wf_plan_names import Fixture


class AuditW12aNameTests(unittest.TestCase):
    """Audit W12a: (a) a plan:/plan-ns: request key given to job submit is a plan name too; (b) Windows reserved device names and
    (c) a trailing dot or space are refused everywhere names are validated, before any write (no orphan anchor)."""

    DEVICE = ['NUL', 'nul', 'CON', 'Prn', 'aux', 'COM1', 'com9', 'LPT1', 'lpt9', 'NUL.txt', 'con.json', 'Com1.log']
    TRAILING = ['x.', 'x..', 'x ', 'x. ']

    def setUp(self):
        self.f = Fixture(self)

    def tasks(self):
        if not (self.f.state_root / 'ledger.sqlite3').exists():
            return 0
        db = sqlite3.connect(self.f.state_root / 'ledger.sqlite3')
        try:
            return db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        finally:
            db.close()

    def test_a_submit_with_a_plan_key_validates_the_plan_name(self):
        from onecrew.task_intake import submit
        before = self.tasks()
        for key in ('plan:a:b', 'plan-ns:a:b', 'plan:NUL', 'plan-ns:con', 'plan:x.', 'plan-ns:COM1.txt', 'plan:-x'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(LedgerError, 'plan name'):
                    submit(self.f.l1, 'Inspect', key)
        self.assertEqual(self.tasks(), before)
        submit(self.f.l1, 'Inspect', 'ordinary:v1:key')          # a v1 key that names no plan keeps its old rule

    def test_b_device_names_are_refused_before_any_write(self):
        for name in self.DEVICE:
            with self.subTest(name=name):
                self.assertRaisesRegex(LedgerError, 'reserved', plans.valid_plan_name, name)
        before_state, before_tasks = self.f.state_files(), self.tasks()
        for name in ('NUL', 'con.json'):
            with self.assertRaises(LedgerError):
                plans.propose(self.f.l1, name, ov.contract('X'), 'claude')
        self.assertEqual(self.tasks(), before_tasks)                # no orphan plan-ns:NUL anchor
        self.assertEqual(self.f.state_files(), before_state)
        for name in ('NULL', 'CONSOLE', 'COM10', 'LPT0', 'nul_x', 'xcon'):
            self.assertEqual(plans.valid_plan_name(name), name)

    def test_c_trailing_dot_or_space_is_refused_so_x_and_x_dot_never_collide(self):
        for name in self.TRAILING:
            with self.subTest(name=name):
                self.assertRaises(LedgerError, plans.valid_plan_name, name)
        with self.assertRaises(LedgerError):
            plans.propose(self.f.l1, 'x.', ov.contract('X'), 'claude')
        plans.propose(self.f.l1, 'x', ov.contract('X'), 'claude')
        self.assertTrue((self.f.state_root / 'plans' / self.f.l1.project_id / 'x' / 'v1.json').exists())
        self.assertEqual(plans.valid_plan_name('x.y'), 'x.y')


from tests.test_v2_l3 import Step0, step0_json


class ProposeLeavesNothingOnRefusalTests(Step0):
    """Follow-up of W12a/W31a: plan.propose created the anchor task before write_revision, so a refusal there (an unscoped open unknown
    on plan-ns, a device name) left an anchor with no revision. Validation now runs before any write, and the anchor, its plan.proposed
    event and the first revision file are one write transaction: a refusal anywhere leaves no task row and no event."""

    def counts(self):
        with self.ledger.transaction() as conn:
            if conn is None: return (0, 0)
            return (conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], conn.execute('SELECT COUNT(*) FROM events').fetchone()[0])

    def test_unscoped_open_unknown_is_refused_with_no_anchor_and_a_corrected_propose_succeeds(self):
        bare = step0_json(size='S', unknowns=['U1'])
        for unknown in bare['understanding']['unknowns']:
            unknown.pop('affected', None); unknown.pop('required_by', None)
        before = self.counts()
        with self.assertRaisesRegex(LedgerError, 'required_by'):
            plans.propose(self.ledger, 'P1', bare, 'claude')
        self.assertEqual(self.counts(), before)
        with self.ledger.transaction() as conn:
            self.assertIsNone(plans.derive(self.ledger, conn, 'P1'))
        with self.assertRaisesRegex(LedgerError, 'No plan named'):
            plans.show(self.ledger, 'P1')
        bare['understanding']['unknowns'][0].update(affected=['O1'], required_by='approval')
        self.assertEqual(plans.propose(self.ledger, 'P1', bare, 'claude')['revision'], 1)

    def test_a_refused_revision_write_rolls_the_anchor_back(self):
        from unittest.mock import patch
        before = self.counts()
        with patch('onecrew.v2.contract.write_revision', side_effect=LedgerError('injected write failure')):
            with self.assertRaisesRegex(LedgerError, 'injected'):
                plans.propose(self.ledger, 'P1', step0_json(size='S'), 'claude')
        self.assertEqual(self.counts(), before)
        self.assertEqual(plans.propose(self.ledger, 'P1', step0_json(size='S'), 'claude')['revision'], 1)

    def test_device_name_still_leaves_nothing(self):
        before = self.counts()
        with self.assertRaisesRegex(LedgerError, 'reserved'):
            plans.propose(self.ledger, 'NUL', step0_json(size='S'), 'claude')
        self.assertEqual(self.counts(), before)
        self.assertFalse((self.ledger.state_root / 'plans' / self.ledger.project_id / 'NUL').exists())


if __name__ == '__main__':
    unittest.main()
