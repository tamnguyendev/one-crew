import json
import unittest
from unittest.mock import patch

import test_workflow as fixtures
import test_parallel as dag_fixtures
from onecrew.branch_inbox import blocks
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.workflow import Workflow


class BranchWorker(fixtures.FixtureWorker):
    def __init__(self, ledger):
        super().__init__(ledger, [])
        self.unknown_b = False
        self.always_bad = False

    def run(self, attempt, prompt, schema, profile):
        stage = json.loads(attempt['operation'])['stage']
        self.calls.append(stage)
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        bad = stage == 'B' and (self.always_bad or self.calls.count('B') == 1)
        if bad and self.unknown_b:
            self.control.unknown(attempt['id'], 'fixture launch acknowledgement lost')
            raise LedgerError('Old writer identity needs reconciliation')
        value = fixtures.artifact('D.txt' if bad else stage+'.txt', stage)
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': value})


class BranchInboxTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.worker = BranchWorker(self.f.ledger)
        self.workflow = Workflow(self.f.ledger, self.worker)
        profile = dag_fixtures.profile()
        profile['context'].append('E.txt')
        profile['owned'].append('E.txt')
        profile['acceptance'].append({'id':'AC-E','description':'Independent follow-up to C'})
        profile['checks'].append({'id':'CHECK-E','acceptance':['AC-E'],'kind':'text_equal','path':'E.txt','expected':'E'})
        plan = dag_fixtures.dag()
        plan['tasks'].append({'id':'E','title':'E','owned':['E.txt'],'depends_on':['C'],'acceptance':['AC-E']})
        state = self.workflow.enable(self.f.task['id'], self.f.task['revision'], profile)
        self.workflow.set_plan(self.f.task['id'], content_hash(state), plan)

    def tearDown(self):
        self.f.tearDown()

    def question(self):
        return self.f.ledger.requests(self.f.task['id'], pending=True)[0]

    def test_independent_descendant_continues_while_b_and_d_wait_then_restart_reply(self):
        task_id = self.f.task['id']
        old_deadline = self.workflow.control.status(task_id)['deadline']
        state = self.workflow.run(task_id)
        self.assertEqual(state['phase'], 'waiting_branches')
        self.assertEqual(set(state['done']), {'A','C','E'})
        self.assertNotIn('D', self.worker.calls)
        question = self.question()
        self.assertEqual(question['question']['action']['parameters']['affected_tasks'], ['B','D'])
        self.assertEqual(self.workflow.control.status(task_id)['used_calls'], 4)
        with self.f.ledger.transaction() as conn:
            self.assertTrue(blocks(conn, task_id, 'root'))
            self.assertTrue(blocks(conn, task_id, 'task:D'))
            self.assertFalse(blocks(conn, task_id, 'task:E'))
        restored = Workflow(Ledger(self.f.project, self.f.base/'state'), self.worker)
        for _ in range(3):
            self.assertEqual(restored.run(task_id)['phase'], 'waiting_branches')
        self.assertEqual(len(self.worker.calls), 4)
        self.f.ledger.reply(question['id'], question['revision'], 'retry', source='another local entry')
        done = restored.run(task_id)
        self.assertEqual(done['phase'], 'completed')
        self.assertEqual(self.worker.calls.count('C'), 1)
        self.assertEqual(self.worker.calls.count('E'), 1)
        self.assertEqual(self.worker.calls.count('B'), 2)
        self.assertEqual(restored.control.status(task_id)['used_calls'], 6)
        self.assertEqual(restored.control.status(task_id)['deadline'], old_deadline)
        self.assertEqual(self.f.ledger.request(question['id'])['controller_effect']['effect'], 'branch_resumed_existing_scope')
        restored.run(task_id)
        self.assertEqual(len(self.worker.calls), 6)

    def test_retry_answer_waits_for_unknown_old_writer_without_holding_independent_work(self):
        self.worker.unknown_b = True
        task_id = self.f.task['id']
        state = self.workflow.run(task_id)
        self.assertEqual(set(state['done']), {'A','C','E'})
        question = self.question()
        self.f.ledger.reply(question['id'], question['revision'], 'retry')
        self.workflow.run(task_id)
        self.assertEqual(len(self.worker.calls), 4)
        self.assertIsNone(self.f.ledger.request(question['id'])['controller_effect'])
        old = self.workflow.control.attempt(state['branch_errors']['B']['attempt'])
        self.assertEqual(old['status'], 'unknown')
        self.workflow.control.finish(old['id'], old['generation'], {'fixture': 'confirmed old writer stopped'})
        self.assertEqual(self.workflow.run(task_id)['phase'], 'completed')
        self.assertEqual(len(self.worker.calls), 6)

    def test_second_failure_keeps_retry_cap_and_offers_inspection(self):
        self.worker.always_bad = True
        task_id = self.f.task['id']
        self.workflow.run(task_id)
        question = self.question()
        self.f.ledger.reply(question['id'], question['revision'], 'retry')
        state = self.workflow.run(task_id)
        self.assertEqual(state['phase'], 'waiting_branches')
        self.assertEqual(state['failed_calls'], 1)
        newer = self.question()
        self.assertNotEqual(newer['id'], question['id'])
        self.assertEqual(newer['question']['recommendation'], 'inspect')
        self.assertEqual(len(self.worker.calls), 5)
        self.f.ledger.reply(newer['id'], newer['revision'], 'stop')
        self.workflow.run(task_id)
        self.assertTrue(self.workflow.control.status(task_id)['cancel_requested'])

    def test_global_question_still_blocks_independent_dispatch(self):
        task_id = self.f.task['id']
        self.workflow.run(task_id, steps=2)
        question = self.f.ledger.create_request(task_id, 'global', {'schema_version':1,
            'question':'Global requirement needs clarification', 'reason':'Affects all tasks', 'impact':'Wait',
            'options':[{'id':'a','label':'A'},{'id':'b','label':'B'}], 'recommendation':'a',
            'action':{'type':'clarify','parameters':{}}})
        self.workflow.run(task_id)
        self.assertNotIn('E', self.worker.calls)
        self.f.ledger.reply(question['id'], question['revision'], 'a')
        self.workflow.run(task_id)
        self.assertIn('E', self.worker.calls)
        self.assertNotIn('D', self.worker.calls)

    def test_background_controller_waits_then_resumes_only_answered_branch(self):
        from onecrew.runner import loop
        waits = []

        def reply(_):
            waits.append(True)
            self.assertEqual(set(self.workflow.state(self.f.task['id'])[1]['done']), {'A','C','E'})
            question = self.question()
            self.f.ledger.reply(question['id'], question['revision'], 'retry')

        with patch('onecrew.runner.Workflow', return_value=self.workflow), patch('onecrew.runner.time.sleep', side_effect=reply):
            self.assertEqual(loop(self.f.ledger, self.f.task['id']), 'completed')
        self.assertEqual(len(waits), 1)
        self.assertEqual(self.worker.calls.count('B'), 2)
        self.assertEqual(len(self.worker.calls), 6)


if __name__ == '__main__':
    unittest.main()
