import datetime as dt
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.ledger import Ledger, LedgerError
from onecrew.runner import loop
from onecrew.triage import ensure_request, fingerprint, handle
from onecrew.workflow import Workflow


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.f.enable()
        self.f.worker.responses[1] = fixtures.artifact('../outside', 'unsafe')
        self.assertEqual(self.f.workflow.run(self.f.task['id'])['phase'], 'blocked')

    def tearDown(self):
        self.f.tearDown()

    def reply(self, question, choice):
        return self.f.ledger.reply(question['id'], question['revision'], choice)

    def test_restart_wait_and_reply_resume_once_preserves_budget_deadline(self):
        f = self.f
        before = f.workflow.control.status(f.task['id'])
        question = ensure_request(f.workflow, f.task['id'])
        restored = Workflow(Ledger(f.project, f.base/'state'), f.worker)
        self.assertEqual(ensure_request(restored, f.task['id']), question)
        for _ in range(3):
            self.assertEqual(handle(restored, f.task['id'])['status'], 'waiting')
        self.assertEqual(len(f.worker.calls), 2)
        reply = self.reply(question, 'retry')
        self.assertFalse(reply['action_applied'])
        self.assertEqual(handle(restored, f.task['id'])['status'], 'resumed')
        self.assertEqual(handle(restored, f.task['id'])['status'], 'not_blocked')
        after = restored.control.status(f.task['id'])
        self.assertEqual((after['deadline'], after['used_calls']), (before['deadline'], before['used_calls']))
        effect = f.ledger.request(question['id'])['controller_effect']
        self.assertEqual(effect['reply_id'], reply['id'])
        self.assertFalse(effect['scope_expanded'])
        f.worker.responses[2] = fixtures.artifact('settings.json', '{"enabled":true,"workers":2}')
        f.worker.responses.append(fixtures.artifact('README.txt', 'Start OneCrew.\n'))
        self.assertEqual(restored.run(f.task['id'])['phase'], 'completed')
        self.assertEqual(restored.control.status(f.task['id'])['used_calls'], 4)
        effects = [e for e in f.ledger.events(f.task['id']) if e['kind'] == 'request.consumed']
        self.assertEqual(len(effects), 1)
        with self.assertRaises(LedgerError):
            self.reply(question, 'stop')

    def test_reply_cannot_resume_changed_blocker_inside_lock(self):
        f = self.f
        question = ensure_request(f.workflow, f.task['id'])
        self.reply(question, 'retry')
        original = f.workflow.resume

        def changed(task_id, **kwargs):
            seq, state = f.workflow.state(task_id)
            state['message'] = 'A different error after operator change'
            f.workflow.persist(task_id, seq, state)
            return original(task_id, **kwargs)

        with patch.object(f.workflow, 'resume', side_effect=changed):
            with self.assertRaisesRegex(LedgerError, 'Blocker changed'):
                handle(f.workflow, f.task['id'])
        self.assertIsNone(f.ledger.request(question['id'])['controller_effect'])
        self.assertEqual(f.workflow.state(f.task['id'])[1]['phase'], 'blocked')
        self.assertEqual(len(f.worker.calls), 2)

    def test_stop_preserves_output_and_consumes_no_calls(self):
        f = self.f
        before = f.workflow.state(f.task['id'])[1]['snapshot']
        question = ensure_request(f.workflow, f.task['id'])
        self.reply(question, 'stop')
        self.assertEqual(handle(f.workflow, f.task['id'])['status'], 'cancelled')
        self.assertTrue(f.workflow.control.status(f.task['id'])['cancel_requested'])
        self.assertEqual(f.workflow.state(f.task['id'])[1]['snapshot'], before)
        self.assertEqual(len(f.worker.calls), 2)
        seq = f.workflow.state(f.task['id'])[0]
        self.assertEqual(handle(f.workflow, f.task['id'])['status'], 'cancelled')
        self.assertEqual(f.workflow.state(f.task['id'])[0], seq)

    def test_extension_invalidates_old_answer_even_between_read_and_resume(self):
        from onecrew.budget import extend
        f = self.f
        question = ensure_request(f.workflow, f.task['id'])
        budget = f.ledger.task(f.task['id'])['budget']
        with self.assertRaisesRegex(LedgerError, 'pending question'):
            extend(f.workflow.control, f.task['id'], budget['revision'], 'extra', 7, budget['deadline'], 'Finish same scope')
        self.reply(question, 'retry')
        original = f.workflow.resume

        def changed(task_id, **kwargs):
            extend(f.workflow.control, task_id, budget['revision'], 'extra', 7, budget['deadline'], 'Finish same scope')
            return original(task_id, **kwargs)

        with patch.object(f.workflow, 'resume', side_effect=changed):
            with self.assertRaisesRegex(LedgerError, 'Budget changed'):
                handle(f.workflow, f.task['id'])
        new_question = ensure_request(f.workflow, f.task['id'])
        self.assertNotEqual(new_question['id'], question['id'])
        self.assertEqual(new_question['state'], 'pending')
        self.assertEqual(len(f.worker.calls), 2)

    def test_receipt_write_failure_rolls_back_checkpoint_and_can_retry(self):
        f = self.f
        question = ensure_request(f.workflow, f.task['id'])
        self.reply(question, 'retry')
        original = f.ledger._event

        def fail(conn, task_id, kind, payload):
            if kind == 'request.consumed':
                raise OSError('disk failure')
            return original(conn, task_id, kind, payload)

        with patch.object(f.ledger, '_event', side_effect=fail):
            with self.assertRaises(OSError):
                handle(f.workflow, f.task['id'])
        self.assertIsNone(f.ledger.request(question['id'])['controller_effect'])
        self.assertEqual(f.workflow.state(f.task['id'])[1]['phase'], 'blocked')
        self.assertEqual(handle(f.workflow, f.task['id'])['status'], 'resumed')

    def test_deadline_and_no_progress_offer_inspection_without_retry(self):
        f = self.f
        f.workflow.control.clock = lambda: dt.datetime.max.replace(tzinfo=dt.timezone.utc)
        question = ensure_request(f.workflow, f.task['id'])
        self.assertEqual(question['question']['recommendation'], 'inspect')
        with self.assertRaises(LedgerError):
            self.reply(question, 'retry')
        self.reply(question, 'inspect')
        self.assertEqual(handle(f.workflow, f.task['id'])['status'], 'blocked')
        self.assertEqual(len(f.worker.calls), 2)

    def test_reply_then_deadline_expiry_does_not_resume(self):
        f = self.f
        question = ensure_request(f.workflow, f.task['id'])
        self.reply(question, 'retry')
        f.workflow.control.clock = lambda: dt.datetime.max.replace(tzinfo=dt.timezone.utc)
        self.assertEqual(handle(f.workflow, f.task['id'])['status'], 'blocked')
        self.assertEqual(len(f.worker.calls), 2)

    def test_controller_waits_then_uses_reply_without_restarting_root(self):
        f = self.f
        f.worker.responses[2] = fixtures.artifact('settings.json', '{"enabled":true,"workers":2}')
        f.worker.responses.append(fixtures.artifact('README.txt', 'Start OneCrew.\n'))
        waits = []

        def user_reply(_):
            waits.append(True)
            self.assertEqual(len(f.worker.calls), 2)
            question = f.ledger.requests(f.task['id'], pending=True)[0]
            self.reply(question, 'retry')

        with patch('onecrew.runner.Workflow', return_value=f.workflow), patch('onecrew.runner.time.sleep', side_effect=user_reply):
            self.assertEqual(loop(f.ledger, f.task['id']), 'completed')
        self.assertEqual(len(waits), 1)
        self.assertEqual(f.workflow.control.status(f.task['id'])['used_calls'], 4)


if __name__ == '__main__':
    unittest.main()
