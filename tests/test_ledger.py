from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError, read_json, validate_grant, validate_question
from onecrew.specs import Project

REPO = Path(__file__).resolve().parents[1]
SANDBOXES = REPO / '.onecrew' / 'test-sandboxes'
SAMPLE = (REPO / 'specs/SPEC-001-duyet-spec.md').read_text(encoding='utf-8')
GRANT = {'schema_version': 1, 'permissions': ['read_repo'],
         'limits': {'max_calls': 4, 'max_seconds': 600}, 'source': 'User requested local pilot'}
QUESTION = {'schema_version': 1, 'question': 'Giữ dữ liệu bao lâu?', 'reason': 'Cần chốt retention.',
            'impact': 'Storage chờ; giao diện có thể tiếp tục.',
            'options': [{'id': 'seven', 'label': '7 ngày'}, {'id': 'thirty', 'label': '30 ngày'}],
            'recommendation': 'seven', 'action': {'type': 'retention', 'parameters': {'unit': 'days'}}}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        SANDBOXES.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix='ledger tiếng Việt ', dir=SANDBOXES)).resolve()
        self.project = self.base / 'project'
        (self.project / 'specs').mkdir(parents=True)
        self.spec_path = self.project / 'specs/SPEC-001-duyet-spec.md'
        self.spec_path.write_text(SAMPLE, encoding='utf-8')
        self.state = self.base / 'state'
        self.ledger = Ledger(self.project, self.state)
        self.revision = Project(self.project).find('SPEC-001').revision
        self.grant_file = self.base / 'grant.json'
        self.grant_file.write_text(json.dumps(GRANT), encoding='utf-8')
        self.question_file = self.base / 'question.json'
        self.question_file.write_text(json.dumps(QUESTION), encoding='utf-8')

    def tearDown(self):
        target = self.base.resolve()
        self.assertTrue(target.is_relative_to(SANDBOXES.resolve()))
        self.assertNotEqual(target, SANDBOXES.resolve())
        shutil.rmtree(target)

    def submit(self, key='submission'):
        return self.ledger.submit('SPEC-001', self.revision, key, GRANT)

    def question(self):
        task = self.submit()
        return task, self.ledger.create_request(task['id'], 'retention', QUESTION)

    def cli(self, *args, expected=0, project=None):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew',
                                 '--project', str(project or self.project), '--state-root', str(self.state),
                                 *args, '--json'], cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_empty_queries_do_not_create_state(self):
        self.assertEqual(self.ledger.tasks(), [])
        self.assertEqual(self.ledger.requests(), [])
        self.assertEqual(self.cli('task', 'queue'), {'tasks': []})
        self.assertEqual(self.cli('request', 'list', '--pending'), {'requests': []})
        with self.assertRaises(LedgerError):
            self.ledger.task('TASK-missing')
        self.assertFalse(self.state.exists())

    def test_submit_retry_is_durable_and_retains_original_deadline(self):
        task = self.submit()
        again = Ledger(self.project, self.state).submit('SPEC-001', self.revision, 'submission', GRANT)
        self.assertEqual(task, again)
        self.assertEqual(len(self.ledger.tasks()), 1)
        self.assertEqual(len(self.ledger.events(task['id'])), 1)
        self.assertFalse(task['dispatch_enabled'])
        self.assertEqual(task['grant_status'], 'unverified_local')
        self.assertEqual(task['budget']['used_calls'], 0)

    def test_submission_key_conflict_and_stale_spec_do_not_add_tasks(self):
        task = self.submit()
        changed = copy.deepcopy(GRANT)
        changed['limits']['max_calls'] = 5
        with self.assertRaisesRegex(LedgerError, 'different'):
            self.ledger.submit('SPEC-001', self.revision, 'submission', changed)
        self.spec_path.write_text(SAMPLE + '\nNew details.\n', encoding='utf-8')
        with self.assertRaisesRegex(LedgerError, 'stale'):
            self.submit('different-key')
        current = Project(self.project).find('SPEC-001').revision
        with self.assertRaisesRegex(LedgerError, 'different'):
            self.ledger.submit('SPEC-001', current, 'submission', GRANT)
        self.assertEqual(self.ledger.task(task['id'])['spec_revision'], self.revision)
        self.assertEqual(len(self.ledger.events(task['id'])), 1)

    def test_acknowledged_snapshot_survives_deleted_spec(self):
        task = self.submit()
        self.spec_path.unlink()
        self.assertEqual(self.submit(), task)
        self.assertEqual(self.ledger.task(task['id'], full=True)['handoff']['spec_text'], SAMPLE)
        self.assertEqual(self.cli('task', 'connect', task['id'])['spec_revision'], self.revision)

    def test_project_isolation_in_shared_database(self):
        task, request = self.question()
        other = self.base / 'other'
        (other / 'specs').mkdir(parents=True)
        (other / 'specs/SPEC-001-duyet-spec.md').write_text(SAMPLE, encoding='utf-8')
        ledger = Ledger(other, self.state)
        self.assertEqual(ledger.tasks(), [])
        self.assertEqual(ledger.requests(), [])
        for operation in (lambda: ledger.task(task['id']), lambda: ledger.request(request['id']),
                          lambda: ledger.reply(request['id'], request['revision'], 'seven'),
                          lambda: ledger.events(task['id'])):
            with self.assertRaises(LedgerError):
                operation()
        second = ledger.submit('SPEC-001', self.revision, 'submission', GRANT)
        self.assertNotEqual(second['id'], task['id'])
        self.assertNotEqual(second['project_id'], task['project_id'])

    def test_pending_reply_and_receipt_survive_fresh_cli_processes(self):
        task = self.cli('task', 'submit', '--spec', 'SPEC-001', '--revision', self.revision,
                        '--request-id', 'cli-start', '--grant', str(self.grant_file))
        request = self.cli('request', 'create', '--task', task['id'], '--request-id', 'question',
                           '--file', str(self.question_file))
        attached = self.cli('task', 'connect', task['id'])
        self.assertEqual(attached['execution'], 'waiting')
        self.assertIsNone(attached['requests'][0]['answer'])
        receipt = self.cli('request', 'reply', request['id'], '--revision', request['revision'],
                           '--choice', 'seven', '--source', 'claude', '--reference', 'user-message-42')
        self.assertFalse(receipt['action_applied'])
        self.assertEqual(receipt['provenance']['trust'], 'local_attribution_only')
        self.assertEqual(self.cli('request', 'show', request['id'])['answer'], receipt)
        self.assertEqual(self.cli('request', 'list', '--pending')['requests'], [])
        resumed = self.cli('task', 'status', task['id'])
        self.assertEqual(resumed['execution'], 'queued')
        self.assertFalse(resumed['dispatch_enabled'])
        self.assertEqual(resumed['deadline'], task['deadline'])

    def test_duplicate_reply_returns_original_receipt_not_new_provenance(self):
        task, request = self.question()
        one = self.ledger.reply(request['id'], request['revision'], 'seven', 'kiro', 'message-1')
        two = self.ledger.reply(request['id'], request['revision'], 'seven', 'codex', 'message-2')
        self.assertEqual(one, two)
        with self.assertRaisesRegex(LedgerError, 'Conflicting'):
            self.ledger.reply(request['id'], request['revision'], 'thirty')
        self.assertEqual(len(self.ledger.events(task['id'])), 3)

    def test_revision_binds_action_and_rejects_old_reply(self):
        task, request = self.question()
        changed = copy.deepcopy(QUESTION)
        changed['action']['parameters']['table'] = 'candidates'
        updated = self.ledger.revise_request(request['id'], request['revision'], changed)
        self.assertNotEqual(updated['revision'], request['revision'])
        self.assertEqual(self.ledger.revise_request(request['id'], request['revision'], changed), updated)
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.ledger.reply(request['id'], request['revision'], 'seven')
        self.assertIsNone(self.ledger.request(request['id'])['answer'])
        events = self.ledger.events(task['id'])
        self.assertEqual(events[1]['payload']['question'], QUESTION)
        self.assertEqual(events[2]['payload']['question'], changed)
        self.assertEqual(self.ledger.events(task['id'], after=events[-1]['seq']), [])

    def test_create_dedup_and_answered_request_cannot_be_rewritten(self):
        task, request = self.question()
        self.assertEqual(self.ledger.create_request(task['id'], 'retention', QUESTION), request)
        changed = copy.deepcopy(QUESTION)
        changed['question'] += ' Chọn lại?'
        with self.assertRaises(LedgerError):
            self.ledger.create_request(task['id'], 'retention', changed)
        self.ledger.reply(request['id'], request['revision'], 'seven')
        with self.assertRaises(LedgerError):
            self.ledger.revise_request(request['id'], request['revision'], changed)

    def test_multiple_pending_questions_keep_task_waiting(self):
        task, first = self.question()
        second = self.ledger.create_request(task['id'], 'other-question', QUESTION)
        self.ledger.reply(first['id'], first['revision'], 'seven')
        self.assertEqual(self.ledger.task(task['id'])['pending_requests'], 1)
        self.assertEqual(self.ledger.task(task['id'])['execution'], 'waiting')
        self.assertEqual(self.ledger.requests(task['id'], True)[0]['id'], second['id'])

    def test_concurrent_process_submissions_create_one_task_and_event(self):
        def submit(_):
            return self.cli('task', 'submit', '--spec', 'SPEC-001', '--revision', self.revision,
                            '--request-id', 'race', '--grant', str(self.grant_file))
        with ThreadPoolExecutor(max_workers=4) as pool:
            tasks = list(pool.map(submit, range(4)))
        self.assertEqual(len({t['id'] for t in tasks}), 1)
        # Every mutating CLI command is recorded (A2, 12/10); a replayed submit is the same single intervention.
        kinds = [e['kind'] for e in self.ledger.events(tasks[0]['id'])]
        self.assertEqual(sorted(kinds), ['control.intervention', 'task.submitted'])

    def test_conflicting_process_replies_have_one_winner(self):
        task, request = self.question()
        def reply(choice):
            return subprocess.run([sys.executable, '-m', 'onecrew', '--project', str(self.project),
                                   '--state-root', str(self.state), 'request', 'reply', request['id'],
                                   '--revision', request['revision'], '--choice', choice, '--json'],
                                  cwd=REPO, capture_output=True, timeout=20)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reply, ['seven', 'thirty']))
        self.assertEqual(sorted(r.returncode for r in results), [0, 2])
        # The winning CLI reply also records who answered (control.intervention); the loser writes nothing.
        kinds = [e['kind'] for e in self.ledger.events(task['id'])]
        self.assertEqual([k for k in kinds if k != 'control.intervention'].__len__(), 3)
        self.assertEqual(kinds.count('control.intervention'), 1)
        self.assertEqual(self.ledger.request(request['id'])['state'], 'answered')

    def test_failed_event_write_rolls_back_reply(self):
        task, request = self.question()
        with patch.object(self.ledger, '_event', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.ledger.reply(request['id'], request['revision'], 'seven')
        self.assertIsNone(self.ledger.request(request['id'])['answer'])
        self.assertEqual(len(self.ledger.events(task['id'])), 2)

    def test_failed_initial_commit_can_be_retried(self):
        with patch.object(self.ledger, '_event', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.submit()
        self.assertEqual(self.ledger.tasks(), [])
        self.assertEqual(len(self.ledger.events(self.submit()['id'])), 1)

    def test_process_death_before_commit_preserves_pending_question(self):
        task, request = self.question()
        script = """import os,sys
from onecrew.ledger import Ledger
ledger=Ledger(sys.argv[1],sys.argv[2])
with ledger.transaction(write=True) as conn:
    conn.execute("UPDATE requests SET state='answered' WHERE id=?",(sys.argv[3],))
    os._exit(17)
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.project), str(self.state), request['id']],
                                cwd=REPO, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 17, result.stderr)
        restored = Ledger(self.project, self.state).request(request['id'])
        self.assertEqual(restored['state'], 'pending')
        self.assertIsNone(restored['answer'])
        self.assertEqual(len(self.ledger.events(task['id'])), 2)

    def test_unknown_schema_is_not_migrated_or_overwritten(self):
        self.submit()
        with closing(sqlite3.connect(self.ledger.path)) as conn:
            conn.execute('PRAGMA user_version=999')
        for action in (self.ledger.tasks, lambda: self.submit('new')):
            with self.assertRaisesRegex(LedgerError, 'Unsupported ledger schema'):
                action()
        with closing(sqlite3.connect(self.ledger.path)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 999)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)

    def test_input_validation_no_model_or_state_mutation(self):
        for value in (True, '4', 0, -1):
            grant = copy.deepcopy(GRANT)
            grant['limits']['max_calls'] = value
            with self.assertRaises(LedgerError):
                self.ledger.submit('SPEC-001', self.revision, 'bad', grant)
        for content in ('{"a":1,"a":2}', '{"a":NaN}', 'not json'):
            self.grant_file.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                read_json(self.grant_file)
        question = copy.deepcopy(QUESTION)
        question['recommendation'] = 'unknown'
        with self.assertRaises(LedgerError):
            validate_question(question)
        self.assertFalse(self.state.exists())
        with self.assertRaisesRegex(LedgerError, 'outside'):
            Ledger(self.project, self.project / '.state')

    def test_json_cli_errors_are_structured_and_legacy_spec_still_works(self):
        self.assertIn('error', self.cli('task', 'status', 'TASK-unknown', expected=2))
        result = subprocess.run([sys.executable, '-m', 'onecrew', '--project', str(self.project),
                                 'spec', 'review', 'SPEC-001', '--json'], cwd=REPO,
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['revision'], self.revision)

    def test_powershell_launcher_emits_utf8_without_python_utf8_flag(self):
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(REPO / 'onecrew.ps1'), '--project', str(self.project),
                                 '--state-root', str(self.state), 'task', 'submit', '--spec', 'SPEC-001',
                                 '--revision', self.revision, '--request-id', 'powershell',
                                 '--grant', str(self.grant_file), '--json'], cwd=REPO,
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        task = json.loads(result.stdout)
        self.assertEqual(task['title'], Project(self.project).find('SPEC-001').title)
        self.assertEqual(self.ledger.task(task['id'])['revision'], task['revision'])


if __name__ == '__main__':
    unittest.main()
