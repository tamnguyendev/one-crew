"""Round 7 / T47b (KN-R02-R03, W30b + W23b) — E10: the resume pack is not authority to answer.

Case (d) of 05 T47 on a stopped plan (stopped_with_report: a milestone reached its repair cap, which raised the owner's question with the two
choices). From an AI session (CLAUDE_CODE_CHILD_SESSION, the simulated marker of the v2 tests — interface/permission proof only):
  1. a first answer attempt BEFORE any pack is refused;
  2. the AI session generates the resume pack of THAT plan (`onecrew continue`, exit 0, the open question listed);
  3. the second answer attempt RIGHT AFTER the pack is refused the same way (CLI `owner answer` exit 2, and the function raises), and the
     `requests` table and the ledger events are identical before/after: the request stays pending, no request.answered.
Counter-example: the same command from the owner's (simulated) terminal succeeds and writes exactly one request.answered — so the
before/after check would be red if the refusal were missing.
"""
import os
import sqlite3
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, questions, verdict
from wf_r02 import BAD, Sandbox, approved, milestone, plan_json, run_cli

AI = {'CLAUDE_CODE_CHILD_SESSION': '1'}


class PackIsNotAnswerAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox(); self.addCleanup(self.sandbox.close)
        self.root = self.sandbox.project('P1')
        self.state = self.sandbox.state('S')
        self.ledger = self.sandbox.ledger(self.root, self.state)
        approved(self.ledger, 'stp', plan_json(title='Stopped plan', milestones=[milestone(argv=BAD, max_repairs=0)]))
        verdict.run(self.ledger, 'stp', 'M1', self.root)
        self.assertEqual(plans.show(self.ledger, 'stp')['status'], 'stopped_with_report')
        pending = questions.list_for_plan(self.ledger, 'stp', pending=True)
        self.assertEqual(len(pending), 1)
        self.req = pending[0]
        self.assertEqual({o['id'] for o in self.req['question']['options']} >= {'stop'}, True)

    def cli(self, *args):
        return run_cli(['--project', str(self.root), '--state-root', str(self.state), *args])

    def answer_argv(self, choice='stop'):
        return ('owner', 'answer', self.req['id'], '--revision', self.req['revision'], '--choice', choice, '--reference', 'the pack says stop')

    def tables(self):
        """requests rows and the events, straight from sqlite (not through the code under test)."""
        conn = sqlite3.connect(str(self.state / 'ledger.sqlite3'))
        try:
            return (conn.execute('SELECT * FROM requests ORDER BY id').fetchall(), conn.execute('SELECT seq, task_id, kind, payload FROM events ORDER BY seq').fetchall())
        finally:
            conn.close()

    def answered_count(self):
        return sum(1 for row in self.tables()[1] if row[2] == 'request.answered')

    def test_e10_answer_after_the_pack_is_still_refused_and_changes_nothing(self):
        with patch.dict(os.environ, AI):
            before_first = self.tables()
            code, out, err = self.cli(*self.answer_argv())                          # (d) first attempt, before the pack
            self.assertEqual(code, 2, out + err)
            self.assertEqual(self.tables(), before_first)
            code, out, err = self.cli('continue', 'stp', '--json')                    # the AI session builds the pack of THIS plan
            self.assertEqual(code, 0, out + err)
            self.assertIn(self.req['id'], out)                                       # the open question is in the pack it holds
            before = self.tables()
            code2, out2, err2 = self.cli(*self.answer_argv())                        # (d) second attempt, right after the pack
            self.assertEqual(code2, 2, out2 + err2)
            self.assertEqual((out2 + err2).strip() != '', True)
            with self.assertRaises(LedgerError):
                questions.answer(self.ledger, self.req['id'], self.req['revision'], 'stop', 'the pack says stop')
            after = self.tables()
        self.assertEqual(after, before)
        self.assertEqual(questions.show(self.ledger, self.req['id'])['state'], 'pending')
        self.assertEqual(self.answered_count(), 0)
        self.assertEqual(plans.show(self.ledger, 'stp')['status'], 'stopped_with_report')

    def test_e10_the_refusal_after_the_pack_is_the_same_as_before_it(self):
        """'refused as [E5]': the same exit code and message as an AI answer without any pack (as when approving)."""
        with patch.dict(os.environ, AI):
            first = self.cli(*self.answer_argv())
            self.cli('continue', 'stp')
            second = self.cli(*self.answer_argv())
        self.assertEqual(first, second)
        self.assertEqual(first[0], 2)

    def test_e10_counter_the_owner_terminal_answer_is_written(self):
        with patch.dict(os.environ, AI):
            self.assertEqual(self.cli('continue', 'stp', '--json')[0], 0)
        before = self.tables()
        code, out, err = self.cli(*self.answer_argv())                               # the owner's terminal: markers removed by the Sandbox
        self.assertEqual(code, 0, out + err)
        self.assertNotEqual(self.tables(), before, 'the before/after comparison sees a real answer')
        self.assertEqual(self.answered_count(), 1)
        self.assertEqual(questions.show(self.ledger, self.req['id'])['state'], 'answered')


if __name__ == '__main__':
    unittest.main()
