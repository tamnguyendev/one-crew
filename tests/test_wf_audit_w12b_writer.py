"""Audit W12b (T32 E4 / T26 E4): one live writer per write scope across roots, through actual Control admission.

Kept apart from tests/test_wf_root_writer.py, whose bytes are pinned by wfkit/development-manifest.json.
"""
import os
import unittest
from unittest.mock import patch

from onecrew.control import Control
from onecrew.ledger import LedgerError
from onecrew.owned_intake import submit
from onecrew.v2 import plan
from tests.test_wf_engine import EngineFixture
from tests.test_v2_l1 import plan_json


class CrossRootWriterTests(EngineFixture):
    """Audit W12b: one live writer per write scope across roots (T32 E4) and one approval source per write (T26 E4). P1 (fixture) owns
    a.txt and b.txt; P2 is a second approved root in the same project that also owns a.txt; P3 owns only c.txt. Before: a P2 writer on
    a.txt reserved while a P1 writer on a.txt was live (guard compared only the same root_task_id)."""

    def setUp(self):
        super().setUp()
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            for name, owned in (('P2', ['a.txt']), ('P3', ['c.txt'])):
                plan.propose(self.ledger, name, plan_json(scope={'owned': owned}, authority={'edit': True, 'commands': True}),
                             'codex', workflow=True)
                plan.approve(self.ledger, name, 'owner', 'temporary second-root fixture')

    def writer(self, key, root, paths):
        contract = {'schema_version': 1, 'goal': 'Edit files', 'acceptance': ['files corrected'], 'preserve': ['Other files'],
                    'authority': {'edit': True}, 'scope': {'repository': '', 'paths': list(paths)},
                    'authorized_by': {'source': 'user', 'reference': 'temporary fixture'}}
        task = submit(self.ledger, None, key, mode='work', contract=contract, plan_selector='plan-ns:' + root,
                      provider='codex', model='gpt-6.1-sol', max_calls=10, max_seconds=60)
        control = Control(self.ledger)
        return task, control, control.configure(task['id'], task['revision'], {'mode': 'fixture'})

    def reserve(self, job, key='open'):
        task, control, execution = job
        return control.reserve(task['id'], execution['revision'], key, {'stage': 'fixture'})

    def test_t32_e4_overlapping_writer_of_another_root_is_refused_naming_that_root(self):
        first = self.writer('p1-writer', 'P1', ['a.txt'])
        active = self.reserve(first)
        for key, paths in (('p2-same', ['a.txt']), ('p2-case', ['A.TXT'])):
            with self.subTest(paths=paths):
                other = self.writer(key, 'P2', paths)
                with self.assertRaises(LedgerError) as raised:
                    self.reserve(other)
                text = str(raised.exception)
                self.assertIn('plan-ns:P1', text); self.assertIn(self.root_view['anchor_task'], text); self.assertIn(first[0]['id'], text)
                self.assertEqual(other[1].status(other[0]['id'])['attempts'], [])
        first[1].finish(active['id'], active['generation'], {'fixture': 'not started'}, not_started=True)
        self.assertEqual(self.reserve(self.writer('p2-after', 'P2', ['a.txt']))['status'], 'reserved')

    def test_t32_e4_disjoint_scopes_of_different_roots_still_run_together(self):
        self.assertEqual(self.reserve(self.writer('p1-writer', 'P1', ['a.txt']))['status'], 'reserved')
        self.assertEqual(self.reserve(self.writer('p3-writer', 'P3', ['c.txt']))['status'], 'reserved')

    def approve_root(self, name, owned):
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            plan.propose(self.ledger, name, plan_json(scope={'owned': owned}, authority={'edit': True}), 'codex', workflow=True)
            return plan.approve(self.ledger, name, 'owner', 'temporary overlapping approval')

    def approvals(self, selector):
        with self.ledger.transaction() as conn:
            row = conn.execute('SELECT id FROM tasks WHERE project_id=? AND request_key=?', (self.ledger.project_id, selector)).fetchone()
            return conn.execute("SELECT COUNT(*) FROM events WHERE task_id=? AND kind='plan.approved'", (row['id'],)).fetchone()[0]

    def test_t26_e4_second_approval_overlapping_a_root_with_a_live_writer_is_refused_naming_it(self):
        # T26 E4 evidence: "a second approval for the same work: refused, the reason names the existing root; sources of authority = 1".
        first = self.writer('p1-writer', 'P1', ['a.txt'])
        active = self.reserve(first)
        with self.assertRaises(LedgerError) as raised:
            self.approve_root('P4', ['d.txt', 'A.TXT'])
        text = str(raised.exception)
        self.assertIn('plan-ns:P1', text); self.assertIn(self.root_view['anchor_task'], text); self.assertIn(first[0]['id'], text)
        self.assertEqual(self.approvals('plan-ns:P4'), 0)                     # no plan.approved: the work has one authority source
        first[1].finish(active['id'], active['generation'], {'fixture': 'not started'}, not_started=True)
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            plan.approve(self.ledger, 'P4', 'owner', 'approved once the other writer settled')
        self.assertEqual(self.approvals('plan-ns:P4'), 1)
        late = self.writer('p4-writer', 'P4', ['a.txt'])
        self.assertEqual(self.reserve(late)['status'], 'reserved')
        with self.assertRaisesRegex(LedgerError, 'plan-ns:P4'):                # defence in depth: the writer guard still serialises
            self.reserve(first, 'again')

    def test_t26_e4_overlapping_approval_without_a_live_writer_and_disjoint_approval_are_allowed(self):
        self.assertEqual(self.approve_root('P5', ['a.txt'])['status'], 'approved')         # no live writer anywhere
        self.reserve(self.writer('p1-writer', 'P1', ['a.txt']))
        self.assertEqual(self.approve_root('P6', ['d.txt'])['status'], 'approved')         # live writer, disjoint scope

    def test_t26_e4_legacy_plan_root_approval_is_unchanged(self):
        import json, tempfile
        from pathlib import Path
        from tests import wf_oldversion as ov
        with tempfile.TemporaryDirectory(prefix='ocw12b-old-') as temp:
            old = ov.OldVersion(ov.archive('d3120c6', Path(__file__).resolve().parents[1], temp))
            path = Path(temp) / 'legacy.json'
            path.write_text(json.dumps(ov.contract('Legacy root')), encoding='utf-8')            # owns a.txt
            code, output = old.run(self.root, self.ledger.state_root, 'plan', 'propose', 'legacy', '--file', str(path), '--author', 'codex')
            self.assertEqual(code, 0, output)
        self.reserve(self.writer('p1-writer', 'P1', ['a.txt']))
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            self.assertEqual(plan.approve(self.ledger, 'plan:legacy', 'owner', 'legacy approval')['status'], 'approved')


if __name__ == '__main__':
    unittest.main()
