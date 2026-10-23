"""T48a (W12a) — plan-name validation before any write, and the same-name refusal across two projects in one state root (R00).

New code only (no old binary). A state root shared by P1 and P2 (the real layout: many projects, one state root). Forbidden names
(`:`, path chars, drive form, absolute) are rejected before anything is written; a second project creating a name P1 already owns is
refused, naming P1, with nothing written; P1's plan is untouched.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import plan as plans
import tests.wf_oldversion as ov          # reuse contract() only


BAD_NAMES = ['a:b', '../x', 'x/y', 'x\\y', 'C:x', 'D:\\x', '/abs/x', '..']
GOOD = 'beta'


class Fixture:
    def __init__(self, case):
        tmp = tempfile.TemporaryDirectory(); case.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.state_root = self.base / 'state'
        self.p1 = self.base / 'P1'; self.p1.mkdir(parents=True)
        self.p2 = self.base / 'P2'; self.p2.mkdir(parents=True)
        for n in ('ONECREW_ACTOR', 'CLAUDE_CODE_CHILD_SESSION'):
            os.environ.pop(n, None)
        self.l1 = Ledger(self.p1, self.state_root)
        self.l2 = Ledger(self.p2, self.state_root)

    def state_files(self):
        if not self.state_root.exists():
            return {}
        return {str(p.relative_to(self.state_root)).replace('\\', '/'): p.stat().st_size for p in self.state_root.rglob('*') if p.is_file()}

    def parent_files(self):
        return sorted(p.name for p in self.base.iterdir())

    def plan_events(self):
        db = sqlite3.connect(self.state_root / 'ledger.sqlite3')
        try:
            return db.execute("SELECT COUNT(*) FROM events WHERE kind='plan.proposed'").fetchone()[0]
        finally:
            db.close()


def _raw(name):
    return json.dumps(ov.contract(name.upper() if name.isalnum() else 'X'))


class PlanNameValidationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    # E1 / E5 / E6: every forbidden name is rejected before any write, on the propose path; message names the forbidden char; the state
    # root and the parent dir are unchanged. (The workflow-root create path is W12b/R04; R00 validates propose.)
    def test_e1_forbidden_names_rejected_before_any_write(self):
        before_state = self.f.state_files()
        before_parent = self.f.parent_files()
        for name in BAD_NAMES:
            with self.assertRaises(LedgerError, msg=name) as c:
                plans.propose(self.f.l1, name, ov.contract('X'), 'claude')
            self.assertTrue(any(w in str(c.exception).lower() for w in ('colon', 'path', 'drive', 'absolute', 'refused')), str(c.exception))
        # nothing written: no ledger grew a plan.proposed, no stray file in state root or the parent
        self.assertEqual(self.f.state_files(), before_state)
        self.assertEqual(self.f.parent_files(), before_parent)

    # E5 (counter): a drive-form name does not create a file outside the state root.
    def test_e5_drive_form_writes_nothing_outside(self):
        before_parent = self.f.parent_files()
        with self.assertRaises(LedgerError):
            plans.propose(self.f.l1, 'C:evil', ov.contract('X'), 'claude')
        self.assertEqual(self.f.parent_files(), before_parent)
        self.assertFalse((self.f.base / 'evil').exists())

    def test_valid_name_is_accepted(self):
        plans.propose(self.f.l1, GOOD, ov.contract('Beta'), 'claude')
        self.assertTrue((self.f.state_root / 'plans' / GOOD / 'v1.json').exists())


class SameNameAcrossProjectsTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    # E10 / E11: two projects, same state root, same name -> the SECOND create is refused, names the other project, writes nothing;
    # the first project's plan is unchanged.
    def test_e10_second_project_same_name_is_refused(self):
        plans.propose(self.f.l1, 'gamma', ov.contract('Gamma'), 'claude')
        plan_dir = self.f.state_root / 'plans' / 'gamma'
        before_hash = (plan_dir / 'v1.json').read_bytes()
        before_events = self.f.plan_events()
        before_files = self.f.state_files()

        with self.assertRaises(LedgerError) as c:
            plans.propose(self.f.l2, 'gamma', ov.contract('Gamma P2', 'P2 goal'), 'claude')
        msg = str(c.exception).lower()
        self.assertIn('another project', msg)
        self.assertIn('nothing was written', msg)

        # nothing written for the second create: event count and file set unchanged, P1's file byte-identical
        self.assertEqual(self.f.plan_events(), before_events)
        self.assertEqual(self.f.state_files(), before_files)
        self.assertEqual((plan_dir / 'v1.json').read_bytes(), before_hash)   # E11: P1's dir untouched

    # counter: the same project re-creating its own name hits the ordinary 'already exists', not the cross-project message.
    def test_same_project_recreate_is_already_exists(self):
        plans.propose(self.f.l1, 'delta', ov.contract('Delta'), 'claude')
        with self.assertRaises(LedgerError) as c:
            plans.propose(self.f.l1, 'delta', ov.contract('Delta'), 'claude')
        self.assertIn('already exists', str(c.exception).lower())


if __name__ == '__main__':
    unittest.main()
