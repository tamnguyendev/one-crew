import contextlib
import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_workflow as fixtures
from test_ledger import QUESTION
from onecrew import entry
from onecrew.cli import main
from onecrew.ledger import Ledger, LedgerError


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.id = self.f.task['id']

    def tearDown(self):
        self.f.tearDown()

    def connect(self):
        return entry.connect(self.f.ledger, self.id)

    def note(self, packet, key='one', **changes):
        values = dict(kind='decision', summary='Keep the approved scope.', source='kiro', reference='user discussion')
        values.update(changes)
        return entry.note(self.f.ledger, self.id, packet['revision'], key, **values)

    def test_readonly_portable_packet_uses_persisted_spec_without_dispatch(self):
        first = self.connect()
        self.assertIsNone(first['phase'])
        self.f.enable()
        self.f.workflow.run(self.id, steps=2)
        before = self.f.ledger.path.read_bytes()
        (self.f.project/'specs/SPEC-001-duyet-spec.md').unlink()
        with patch('onecrew.workflow.Workflow.run', side_effect=AssertionError('must not dispatch')):
            packet = self.connect()
            restarted = entry.connect(Ledger(self.f.project, self.f.base/'state'), self.id)
        self.assertEqual(packet, restarted)
        self.assertEqual(before, self.f.ledger.path.read_bytes())
        self.assertTrue(packet['plan']['items'][0]['done'])
        self.assertFalse(packet['plan']['items'][1]['done'])
        self.assertEqual(packet['task']['budget']['used_calls'], 2)
        self.assertEqual(packet['outputs']['total'], 1)
        self.assertIn('SPEC-001', packet['spec']['brief']['text'])

    def test_notes_idempotent_across_restart_without_authority(self):
        packet = self.connect()
        receipt = self.note(packet)
        self.assertEqual(self.note(packet), receipt)
        next_packet = entry.connect(Ledger(self.f.project, self.f.base/'state'), self.id)
        self.assertEqual(next_packet['notes']['items'], [receipt])
        self.assertFalse(receipt['action_applied'])
        self.assertEqual(receipt['provenance']['trust'], 'local_attribution_only')
        self.assertFalse(next_packet['task']['dispatch_enabled'])
        with self.assertRaisesRegex(LedgerError, 'Conflicting'):
            self.note(packet, summary='Approve everything')
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.note(packet, key='two')

    def test_progress_and_pending_question_revision_invalidate_context(self):
        before = self.connect()
        self.f.enable()
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.note(before)
        question = self.f.ledger.create_request(self.id, 'question', QUESTION)
        packet = self.connect()
        self.assertEqual(packet['pending_questions']['items'][0]['revision'], question['revision'])
        self.f.ledger.reply(question['id'], question['revision'], 'seven', 'claude', 'user chose seven')
        after = self.connect()
        self.assertEqual(after['pending_questions']['total'], 0)
        self.assertEqual(after['recent_answers'][0]['choice'], 'seven')
        self.assertIsNone(after['recent_answers'][0]['controller_effect'])
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.note(packet)

    def test_project_isolation_and_empty_read_never_create_state(self):
        other = self.f.base/'other'
        other.mkdir()
        ledger = Ledger(other, self.f.base/'state')
        with self.assertRaises(LedgerError):
            entry.connect(ledger, self.id)
        with self.assertRaises(LedgerError):
            entry.note(ledger, self.id, self.connect()['revision'], 'key', 'decision', 'Text', 'codex', 'chat')
        absent = self.f.base/'absent'
        with self.assertRaises(LedgerError):
            entry.connect(Ledger(other, absent), self.id)
        self.assertFalse(absent.exists())

    def test_bounded_history_and_explicit_detail_links(self):
        for i in range(7):
            self.note(self.connect(), key=str(i), summary='x'*2000)
        for i in range(12):
            self.f.ledger.create_request(self.id, str(i), dict(QUESTION, question='q'*2000))
        packet = self.connect()
        self.assertEqual(packet['notes']['total'], 7)
        self.assertEqual(len(packet['notes']['items']), 5)
        self.assertEqual(packet['pending_questions']['total'], 12)
        self.assertEqual(len(packet['pending_questions']['items']), 10)
        question = packet['pending_questions']['items'][0]
        self.assertTrue(question['question']['truncated'])
        self.assertTrue(question['details_command'].startswith('request show REQ-'))
        with self.assertRaises(LedgerError):
            self.note(packet, key='long', summary='x'*2001)

    def test_cli_connect_and_note_no_model_calls(self):
        prefix = ['--project', str(self.f.project), '--state-root', str(self.f.base/'state'), 'entry']
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(main([*prefix, 'connect', self.id, '--json']), 0)
        packet = json.loads(stream.getvalue())
        path = self.f.base/'note.txt'
        path.write_text('Keep review in small parts.', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([*prefix, 'note', self.id, '--revision', packet['revision'], '--request-id', 'cli',
                                   '--kind', 'proposal', '--file', str(path), '--source', 'codex', '--reference', 'current chat']), 0)
        self.assertEqual(self.connect()['notes']['total'], 1)
        self.assertEqual(self.f.worker.calls, [])

    def test_concurrent_entries_cannot_record_two_decisions_from_same_revision(self):
        packet = self.connect()
        def record(key):
            try:
                return self.note(packet, key=key)['request_id']
            except LedgerError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(record, ['codex', 'claude']))
        self.assertEqual(sum(x in ('codex', 'claude') for x in results), 1)
        self.assertEqual(sum('Stale' in x for x in results), 1)
        self.assertEqual(self.connect()['notes']['total'], 1)
