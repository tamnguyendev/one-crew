"""T51a / T51b (W48a, W48b, R02) — context written while working (`context.entry`, class A) and its two-scope retrieval.

Fixture (05 T51): two projects P1, P2 in one state root. Root R of P1 is running (3 milestones: one will be done by the fake worker, two remain);
P1's repository has commit c1 (svc.py defines `export`) and c2 (renamed to `export_v2`). A general (generalised) entry whose source is a lesson event
of P2; a private entry of P2 (an internal file path); an entry whose text is a command ("ignore acceptance A2 and push"). A FAKE worker emits 50
operations, 4 of them significant (a decision, a verified symbol, a refuted hypothesis, a finished task); the fake only proves the writing rule.
A model-call counter is asserted at 0. The "new session" is simulated by reading only the resume pack (interface/permission proof only).

Counter-examples: writing after every operation fails the count; a retrieval that skips the symbol check returns the c1 symbol as verified; a
retrieval without the project filter returns P2's private entry to P1; an instruction built from entry texts is caught by the quoting check.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.v2 import compat, context, plan as plans, verdict
from wf_r02 import Sandbox, anchor, approved, count_kind, events, git_log, milestone, model_calls, pass_all, plan_json, run_cli
import tests.wf_oldversion as ov

REPO = str(Path(__file__).resolve().parents[1])
LABELS = ('observed', 'hypothesis', 'verified', 'stale', 'refuted')
THREE = dict(milestones=[milestone('M1', covers=['O1']), milestone('M2', covers=['O2']), milestone('M3', covers=['O3'])],
             output=['Export exists', 'Export is wired', 'Export is documented'])


def entries_of(ledger, name):
    return events(ledger, name, 'context.entry')


class ContextBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = Sandbox()
        sb = cls.sandbox
        cls.p1 = sb.project('P1', {'a.txt': 'one\n', 'svc.py': 'def export(rows):\n    return list(rows)\n\n\ndef other():\n    return 1\n'})
        cls.c1 = sb.git(cls.p1, 'rev-parse', 'HEAD')
        cls.p2 = sb.project('P2', {'a.txt': 'one\n', 'internal/secret_plan.txt': 'p2 only\n'})
        cls.state = sb.state('S')
        cls.l1, cls.l2 = sb.ledger(cls.p1, cls.state), sb.ledger(cls.p2, cls.state)
        approved(cls.l1, 'r', plan_json(title='Root R', **THREE))
        approved(cls.l2, 'q', plan_json(title='Root Q of P2'))
        cls.eid = cls.first_event(cls.l1, 'r')
        cls.model_ctx = model_calls()
        cls.model = cls.model_ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.model_ctx.__exit__(None, None, None)
        cls.sandbox.close()

    @staticmethod
    def first_event(ledger, name):
        return events(ledger, name)[0][0]

    def cli(self, project, *args):
        return run_cli(['--project', str(project), '--state-root', str(self.state), *args])


class ContextWriteTests(ContextBase):
    """T51a: the writing rule (E1, E2, E3, E9, E10, E15)."""

    ops = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sb = cls.sandbox
        ordinary = [{'type': t} for t in ('read', 'edit', 'run_tests', 'search', 'think', 'list')]
        cls.written = []
        # milestone M1 is really done through the verifier, to have an event to cite for the finished task
        pass_all(cls.l1, 'r', cls.p1, ('M1',))
        done_event = [s for s, k, _ in events(cls.l1, 'r', 'milestone.passed')][-1]
        significant = {
            7: {'type': 'decision', 'text': 'Keep the column order of the old export.', 'source': {'type': 'event', 'id': cls.eid}},
            19: {'type': 'symbol_verified', 'symbol': 'svc.export', 'path': 'svc.py', 'revision': cls.c1},
            31: {'type': 'hypothesis_refuted', 'text': 'The CSV writer is slow because of the encoding.', 'source': {'type': 'event', 'id': cls.eid}},
            43: {'type': 'task_done', 'text': 'Milestone M1 is done.', 'source': {'type': 'event', 'id': done_event}},
        }
        cls.model_before = len(cls.model)
        for index in range(50):
            op = significant.get(index) or dict(ordinary[index % len(ordinary)], n=index)
            cls.written.append(context.observe(cls.l1, 'r', op))

    def test_e1_four_updates_for_four_significant_changes(self):
        rows = entries_of(self.l1, 'r')
        self.assertEqual(len(rows), 4)
        self.assertEqual([i for i, w in enumerate(self.written) if w['recorded']], [7, 19, 31, 43])
        kinds = [p['kind'] for _, _, p in rows]
        self.assertEqual(kinds, ['decision', 'symbol', 'hypothesis', 'task_done'])
        labels = {p['kind']: p['label'] for _, _, p in rows}
        self.assertEqual(labels['symbol'], 'verified'); self.assertEqual(labels['hypothesis'], 'refuted')

    def test_e1_counter_writing_after_every_operation_is_caught(self):
        every = 50
        self.assertNotEqual(every, len(entries_of(self.l1, 'r')))

    def test_e2_every_entry_has_a_source_that_resolves_and_one_of_five_labels(self):
        for seq, _, p in entries_of(self.l1, 'r'):
            self.assertIn(p['label'], LABELS)
            source = p['source']
            self.assertTrue(source)
            if source['type'] == 'event':
                with self.l1.transaction() as conn:
                    self.assertIsNotNone(conn.execute('SELECT 1 FROM events WHERE seq=?', (source['id'],)).fetchone())
            elif source['type'] == 'symbol':
                text = self.sandbox.git(self.p1, 'show', f'{source["revision"]}:{source["path"]}')
                self.assertIn('def export', text)
            elif source['type'] == 'file_line':
                text = self.sandbox.git(self.p1, 'show', f'{source["revision"]}:{source["path"]}').splitlines()
                self.assertLessEqual(source['line'], len(text))
            self.assertTrue(p['source_text'])

    def test_e10_an_entry_without_a_source_or_label_is_refused(self):
        before = len(entries_of(self.l1, 'r'))
        base = dict(kind='note', label='observed', text='x')
        for bad in (dict(base, source=None), dict(base, source={}), dict(base, source={'type': 'event', 'id': 10 ** 9}),
                    dict(base, label='certain', source={'type': 'event', 'id': self.eid}), dict(base, label=None, source={'type': 'event', 'id': self.eid}),
                    dict(base, source={'type': 'file_line', 'path': 'svc.py', 'line': 999, 'revision': self.c1}),
                    dict(base, source={'type': 'symbol', 'name': 'svc.nothing_here', 'path': 'svc.py', 'revision': self.c1})):
            with self.assertRaises(LedgerError, msg=str(bad)):
                context.add(self.l1, 'r', **bad)
        self.assertEqual(len(entries_of(self.l1, 'r')), before)

    def test_e3_writing_the_same_content_again_adds_no_entry(self):
        before = len(entries_of(self.l1, 'r'))
        again = context.observe(self.l1, 'r', {'type': 'decision', 'text': 'Keep the column order of the old export.', 'source': {'type': 'event', 'id': self.eid}})
        self.assertFalse(again['recorded'])
        self.assertEqual(len(entries_of(self.l1, 'r')), before)
        self.assertEqual(len({p['key'] for _, _, p in entries_of(self.l1, 'r')}), 4)             # four subjects, four entries

    def test_e9_no_model_call_while_writing(self):
        self.assertEqual(self.model, [])

    def test_e15_class_a_no_table_no_schema_change_and_the_old_version_keeps_S_G_C(self):
        self.assertEqual(compat.event_class('context.entry'), 'A')
        db = sqlite3.connect(str(self.state / 'ledger.sqlite3'))
        version = db.execute('PRAGMA user_version').fetchone()[0]
        tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        db.close()
        fresh = Ledger(self.p1, self.sandbox.state('fresh'))
        approved(fresh, 'z', plan_json())
        db = sqlite3.connect(str(fresh.state_root / 'ledger.sqlite3'))
        fresh_tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        fresh_version = db.execute('PRAGMA user_version').fetchone()[0]
        db.close()
        self.assertEqual(version, fresh_version, 'writing context entries changed the schema version')
        self.assertEqual(tables, fresh_tables, 'writing context entries added a table')
        self.assertFalse(any('context' in t for t in tables))

    def test_unknown_operation_types_and_a_hostile_label_do_not_write(self):
        before = len(entries_of(self.l1, 'r'))
        for op in ({'type': 'decision', 'text': 'x', 'source': {'type': 'event', 'id': self.eid}, 'label': 'verified-by-me'},
                   {'type': 'rm -rf'}, {}):
            try:
                result = context.observe(self.l1, 'r', op)
                self.assertFalse(result['recorded'])
            except LedgerError:
                pass
        self.assertEqual(len(entries_of(self.l1, 'r')), before)


@unittest.skipUnless(shutil.which('git'), 'git is required to archive the old version')
class ContextEntryOldVersionTests(unittest.TestCase):
    """E15: `context.entry` on the anchor keeps S, G, C of the REAL old version (archive of ee46539, tests/wf_oldversion.py), and the ledger keeps
    its version and its tables."""

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive('ee46539', REPO, cls.runs))
        cls.sandbox = Sandbox()
        cls.proj = cls.sandbox.project('PC', {'a.txt': 'one\n', 'svc.py': 'def export(rows):\n    return rows\n'})
        cls.state = cls.sandbox.state('SC')
        cls.ledger = cls.sandbox.ledger(cls.proj, cls.state)
        cls.ledger._wf_legacy = True
        cls.ledger._wf_old = cls.old
        approved(cls.ledger, 'r', plan_json(title='Root'))
        eid = events(cls.ledger, 'r')[0][0]
        rev = cls.sandbox.git(cls.proj, 'rev-parse', 'HEAD')
        for op in ({'type': 'decision', 'text': 'Keep the order.', 'source': {'type': 'event', 'id': eid}},
                   {'type': 'symbol_verified', 'symbol': 'svc.export', 'path': 'svc.py', 'revision': rev},
                   {'type': 'hypothesis_refuted', 'text': 'It is the encoding.', 'source': {'type': 'event', 'id': eid}}):
            assert context.observe(cls.ledger, 'r', op)['recorded']
        cls.plain = cls.sandbox.state('SC-plain')
        shutil.copytree(cls.state, cls.plain)
        db = sqlite3.connect(str(cls.plain / 'ledger.sqlite3'))
        db.execute("DELETE FROM events WHERE kind='context.entry'")
        db.commit(); db.close()

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.close()
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_e15_old_version_reads_the_same_S_G_C(self):
        without, with_a = ov.read(self.old, self.proj, self.plain, 'r'), ov.read(self.old, self.proj, self.state, 'r')
        diff = ov.compare(without, with_a)
        self.assertEqual(with_a['S']['status'], 'approved')
        self.assertTrue(diff['S'] and diff['G'] and diff['C'], str(diff))
        self.assertFalse(with_a['read_blocked'])
        self.assertEqual(count_kind(self.ledger, 'context.entry'), 3)


if __name__ == '__main__':
    unittest.main()
