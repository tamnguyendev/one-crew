"""T47a/b owner answers use v1 requests; reads and replies never approve a plan."""
import os
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from tests.test_v2_l1 import Fixture, plan_json
from onecrew.ledger import LedgerError
from onecrew.v2 import plan, questions


class QuestionTests(Fixture):
    def setUp(self):
        super().setUp()
        self.propose()
        task = plan.show(self.ledger, 'P1')['anchor_task']
        self.question = self.ledger.create_request(task, 'fixture-question', {
            'schema_version': 1, 'question': 'Continue?', 'reason': 'fixture uncertainty',
            'impact': 'plan stays unchanged', 'options': [{'id': 'amend_plan', 'label': 'Amend'}, {'id': 'stop', 'label': 'Stop'}],
            'recommendation': 'amend_plan', 'action': {'type': 'v2.plan_stopped', 'parameters': {'key': 'fixture'}}})

    def test_read_leaves_every_event_and_request_unchanged(self):
        before = self.events()
        shown = questions.show(self.ledger, self.question['id'])
        self.assertEqual(shown['state'], 'pending')
        self.assertEqual(len(questions.list_for_plan(self.ledger, 'P1')), 1)
        self.assertEqual(before, self.events())

    def test_answer_is_idempotent_and_never_approves_or_closes(self):
        receipt = questions.answer(self.ledger, self.question['id'], self.question['revision'], 'amend_plan', 'fixture owner')
        self.assertEqual(receipt['choice'], 'amend_plan')
        self.assertFalse(receipt['action_applied'])
        self.assertEqual(receipt, questions.answer(self.ledger, self.question['id'], self.question['revision'], 'amend_plan', 'fixture owner'))
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'proposed')
        self.assertEqual(self.kinds().count('request.answered'), 1)
        self.assertNotIn('plan.closed', self.kinds())

    def test_ai_cannot_answer_even_with_resume_data(self):
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1', 'ONECREW_ACTOR': 'user'}):
            with self.assertRaises(LedgerError):
                questions.answer(self.ledger, self.question['id'], self.question['revision'], 'stop', 'data is not authority')
        self.assertEqual(questions.show(self.ledger, self.question['id'])['state'], 'pending')

    def test_stale_or_conflicting_answer_refused(self):
        with self.assertRaises(LedgerError): questions.answer(self.ledger, self.question['id'], 99, 'stop', 'fixture')
        questions.answer(self.ledger, self.question['id'], self.question['revision'], 'stop', 'fixture')
        with self.assertRaises(LedgerError): questions.answer(self.ledger, self.question['id'], self.question['revision'], 'amend_plan', 'fixture')

    def test_owner_cli_uses_the_actual_hash_revision_and_ai_cannot_replay_it(self):
        argv = [sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.cli', '--project', str(self.root),
                '--state-root', str(self.ledger.state_root), 'owner', 'answer', self.question['id'],
                '--revision', self.question['revision'], '--choice', 'stop', '--reference', 'fixture terminal']
        cwd = Path(__file__).resolve().parents[1]
        denied = subprocess.run(argv, cwd=cwd, env=dict(os.environ, CLAUDE_CODE_CHILD_SESSION='1'), capture_output=True, timeout=30)
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        allowed = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=30)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)['choice'], 'stop')
        self.assertEqual(self.kinds().count('request.answered'), 1)
