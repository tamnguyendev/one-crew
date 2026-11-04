"""2.4-S1 / SF-01: a user reports an error once and gets one feedback id (FB-...), recorded on the project's support anchor.

Counterexamples (ROADMAP-DESIGN §7, S1/SF-01): a resend and a restart import exactly one feedback; the same key with other content is refused;
a report without a task or about a closed root is accepted and writes only the support anchor; a feedback about an old revision does not touch
the current one; the same text under another version or other conditions is not merged; an unreproduced report stays reported/unknown and no
failure is invented (no node.verification, finding, receipt or attempt). The fixtures here are shared by the other tests/test_v24_s1_*.py.
"""
import contextlib
import io
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import plan as plans
from onecrew.v2.cli import main as cli_main
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node


def support():
    from onecrew.v2 import support as module
    return module


class Helpers:
    """Mixed into a Fixture: the CLI in-process, the support anchor's events, and a snapshot of every other row of the ledger."""

    def cli(self, *args, project=None, state=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_main(['--project', str(project or self.root), '--state-root', str(state or self.ledger.state_root), *args])
        text = out.getvalue()
        try:
            return code, json.loads(text)
        except ValueError:
            return code, text

    def report(self, *args, **kw):
        return self.cli('support', 'report', '--json', *args, **kw)

    def support_events(self, kind='support.feedback'):
        with self.ledger.transaction() as conn:
            if conn is None: return []
            return [json.loads(r['payload']) for r in conn.execute(
                'SELECT e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.request_key=? AND e.kind=? ORDER BY e.seq',
                (support().ANCHOR_KEY, kind))]

    def others(self):
        """Every row of every table, except the support anchor's own task row and events: what a report must never change."""
        if not self.ledger.path.exists(): return {}
        conn = sqlite3.connect(self.ledger.path)
        try:
            anchors = {r[0] for r in conn.execute('SELECT id FROM tasks WHERE request_key=?', (support().ANCHOR_KEY,))}
            out = {}
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                rows = conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                if table == 'events': rows = [r for r in rows if r[1] not in anchors]
                if table == 'tasks': rows = [r for r in rows if r[0] not in anchors]
                out[table] = rows
            return out
        finally:
            conn.close()

    def blobs(self):
        folder = self.ledger.state_root / 'snapshots' / 'blobs'
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


class S1Fixture(Helpers, Fixture):
    pass


class FailedNodeFixture(Helpers, EngineFixture):
    """A real engine root P1 whose node C ran (a real attempt of a real child task) and whose check failed: one failed node."""

    def failing(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': check['id'], 'result': 'fail', 'evidence': self.store.blob(b'fixture check failed')}
                                                for check in item['checks']]}

    def setUp(self):
        super().setUp()
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        self.step()
        self.verify('C', self.failing)
        view = self.engine.state(self.ledger, 'P1')
        self.attempt = view['nodes']['C']['attempt']
        self.child = view['nodes']['C']['child']
        self.root_task = view['root']


class IntakeTests(S1Fixture):
    def test_resend_and_restart_import_exactly_one_feedback(self):
        from onecrew.v2 import support_spool
        code, first = self.report('--text', 'The build fails at step 3', '--key', 'k1')
        self.assertEqual(code, 0, first)
        self.assertTrue(first['recorded']); self.assertRegex(first['id'], r'^FB-[0-9a-f]{32}$'); self.assertFalse(first['spooled'])
        code, again = self.report('--text', 'The build fails at step 3', '--key', 'k1')         # the user sends it again
        self.assertEqual((code, again['id'], again['duplicate']), (0, first['id'], True))
        # a restart: the same report also reached the spool while the ledger was down; importing it (twice) adds nothing
        record = support_spool.record(text='The build fails at step 3', key='k1', project=self.root, state_root=self.ledger.state_root,
                                      reason='fixture: ledger was down')
        written = support_spool.spool(record, project=self.root, state_root=self.ledger.state_root)
        self.assertTrue(written['recorded'], written)
        for _ in range(2):
            code, imported = self.cli('support', 'import-spool')
            self.assertEqual(code, 0, imported)
        self.assertEqual([e['id'] for e in self.support_events() if e['client_key'] == 'k1'], [first['id']])
        # a spooled report without a key: its spool id is the client key and becomes the feedback id, once
        lone = support_spool.record(text='Hook crashed on start', project=self.root, state_root=self.ledger.state_root, reason='fixture')
        support_spool.spool(lone, project=self.root, state_root=self.ledger.state_root)
        self.cli('support', 'import-spool'); self.cli('support', 'import-spool')
        self.assertEqual([e['id'] for e in self.support_events() if e['text'] == 'Hook crashed on start'], [lone['id']])
        self.assertEqual(len(self.support_events()), 2)

    def test_same_key_different_content_is_refused(self):
        code, first = self.report('--text', 'Wrong output in b.txt', '--key', 'k2')
        self.assertEqual(code, 0, first)
        code, refused = self.report('--text', 'Something else entirely', '--key', 'k2')
        self.assertEqual(code, 2, refused)
        self.assertEqual(refused['type'], 'ReportRefused'); self.assertIn('different', refused['error'])
        self.assertEqual(len(self.support_events()), 1)
        self.assertFalse((self.ledger.state_root / 'support-spool').exists())                  # a refusal is not a broken ledger: nothing spooled

    def test_report_without_task_and_on_closed_root_writes_support_anchor_only(self):
        code, alone = self.report('--text', 'onecrew init printed nothing')
        self.assertEqual(code, 0, alone)
        self.assertEqual(alone['refs'], {})
        self.approved('P1')
        with self.ledger.transaction(write=True) as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            plans.emit(self.ledger, conn, task, 'plan.accepted', {'plan': 'P1', 'revision': 1, 'by': 'owner', 'reference': 'fixture'})
        before = self.others()
        code, closed = self.report('--text', 'After acceptance the result is wrong', '--plan', 'P1')
        self.assertEqual(code, 0, closed)
        self.assertEqual(closed['refs']['root_task'], task); self.assertEqual(closed['refs_source']['plan'], 'user')
        self.assertEqual(self.others(), before)                                                 # the ended root is never written to
        with self.ledger.transaction() as conn:
            anchors = conn.execute("SELECT COUNT(*) FROM tasks WHERE request_key=?", (support().ANCHOR_KEY,)).fetchone()[0]
        self.assertEqual(anchors, 1)

    def test_old_revision_feedback_does_not_touch_current_revision(self):
        self.approved('P1')
        code, old = self.report('--text', 'Milestone M1 gives the wrong file', '--plan', 'P1', '--key', 'k3')
        self.assertEqual(code, 0, old)
        self.assertEqual(old['refs']['revision'], 1)
        plans.amend(self.ledger, 'P1', plan_json(title='Sample 2'), 'new title', 'claude')
        before, shown = self.others(), plans.show(self.ledger, 'P1')
        code, again = self.report('--text', 'Milestone M1 gives the wrong file', '--plan', 'P1', '--key', 'k3')
        self.assertEqual((code, again['id'], again['duplicate'], again['refs']['revision']), (0, old['id'], True, 1))
        self.assertEqual(self.others(), before)
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], shown['status'])
        code, view = self.cli('support', 'show', old['id'], '--json')
        self.assertEqual(view['feedback']['refs']['revision'], 1)
        code, current = self.report('--text', 'Milestone M1 gives the wrong file', '--plan', 'P1')
        self.assertEqual(current['refs']['revision'], 2)

    def test_same_text_other_version_or_conditions_not_merged(self):
        code, a = self.report('--text', 'The verifier  hangs on   M1', '--key', 'a')
        code, b = self.report('--text', 'the verifier hangs on M1', '--key', 'b')
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(b['possible_duplicates'], [a['id']])                                   # suggested, never merged
        probe = support().runtime_probe()
        with patch.object(support(), 'runtime_probe', lambda *a, **k: dict(probe, dist_version='9.9.9')):
            code, c = self.report('--text', 'the verifier hangs on M1', '--key', 'c')
        self.assertEqual(c['possible_duplicates'], [])                                          # another version: not even suggested
        self.approved('P1')
        code, d = self.report('--text', 'the verifier hangs on M1', '--key', 'd', '--plan', 'P1')
        self.assertEqual(d['possible_duplicates'], [])                                          # other conditions (a plan): not suggested
        self.assertEqual(len(self.support_events()), 4)

    def test_report_needs_text_and_valid_refs(self):
        code, empty = self.report('--text', '   ')
        self.assertEqual(code, 2, empty)
        code, bad = self.report('--text', 'x', '--attempt', '..\\..\\attempts')
        self.assertEqual(code, 2, bad)
        self.assertEqual(self.support_events(), [])


class DerivedRefsTests(FailedNodeFixture):
    def test_unreproduced_stays_reported_unknown_no_fail_receipt(self):
        before, blobs = self.others(), self.blobs()
        code, made = self.report('--text', 'Node C rejected a correct file', '--plan', 'P1')
        self.assertEqual(code, 0, made)
        self.assertEqual(self.others(), before)                     # no node.verification, finding, attempt, request: no fake failure
        self.assertEqual(self.blobs(), blobs)                       # and no receipt blob
        code, state = self.cli('support', 'status', made['id'], '--json')
        self.assertEqual(code, 0, state)
        self.assertEqual((state['reported']['value'], state['reproduced']['value']), (True, 'unknown'))
        self.assertEqual(state['stage'], 'reported')

    def test_refs_attach_only_what_is_provable(self):
        code, made = self.report('--text', 'Node C failed', '--plan', 'P1')
        self.assertEqual((made['refs']['node'], made['refs']['root_task']), ('C', self.root_task))
        self.assertTrue(made['refs_source']['node'].startswith('derived:'), made['refs_source'])
        self.assertEqual(made['refs']['status'], plans.show(self.ledger, 'P1')['status'])
        code, by_attempt = self.report('--text', 'The attempt printed an error', '--attempt', self.attempt)
        self.assertEqual((by_attempt['refs']['attempt'], by_attempt['refs']['task'], by_attempt['refs']['node']), (self.attempt, self.child, 'C'))
        self.assertEqual(by_attempt['refs_source']['attempt'], 'user'); self.assertTrue(by_attempt['refs_source']['task'].startswith('derived:'))
        self.assertEqual(by_attempt['refs']['root_task'], self.root_task)
        self.assertTrue(made['runtime']['tree'])
        code, nothing = self.report('--text', 'A plan that is not there', '--plan', 'P9')
        self.assertEqual(code, 0, nothing)
        self.assertNotIn('root_task', nothing['refs']); self.assertIn('plan', nothing['refs_unresolved'])


if __name__ == '__main__':
    unittest.main()
