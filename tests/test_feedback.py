import unittest
from unittest.mock import patch

from onecrew.feedback import request_changes
from onecrew.ledger import LedgerError, content_hash
from onecrew.workflow import Workflow
import test_workflow as fixtures
from test_workflow import artifact, plan


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests()
        self.fixture.setUp()
        self.f = self.fixture
        independent = plan()
        independent['tasks'][1]['depends_on'] = []
        self.f.worker.responses[0] = independent
        self.f.enable()

    def tearDown(self):
        self.f.tearDown()

    def request(self, state, *, output=None, selected=None, key='correction-1', comment='Format the configuration for easier review.'):
        return request_changes(self.f.workflow, self.f.task['id'], content_hash(state), output or state['snapshot'],
                               selected or ['config'], comment, key)

    def test_partial_correction_then_remaining_work_uses_same_budget_and_source(self):
        state = self.f.workflow.run(self.f.task['id'], steps=2)
        before = self.f.workflow.control.status(self.f.task['id'])
        self.f.worker.responses.insert(2, artifact('settings.json', '{\n  "enabled": true,\n  "workers": 2\n}\n'))
        record = self.request(state)
        self.assertEqual(record['affected_tasks'], ['config'])
        _, scheduled = self.f.workflow.state(self.f.task['id'])
        self.assertEqual(scheduled['repairs'], 1)
        with self.assertRaises(LedgerError):
            self.f.workflow.review(self.f.task['id'], state['snapshot'], 'accept', 'Cannot accept while correction queued')
        done = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(done['phase'], 'completed')
        self.assertEqual(done['acceptance'], 'pending')
        self.assertEqual(self.f.worker.calls, ['plan', 'config', 'repair', 'doc'])
        self.assertEqual(done['reviews'][0]['status'], 'candidate_produced')
        self.assertFalse((self.f.project/'settings.json').exists())
        after = self.f.workflow.control.status(self.f.task['id'])
        self.assertEqual(after['deadline'], before['deadline'])
        self.assertEqual(after['used_calls'], 4)

    def test_completed_correction_preserves_sibling_and_reuses_receipt_after_crash(self):
        state = self.f.workflow.run(self.f.task['id'])
        sibling = self.f.workflow.store.load(state['snapshot'])['files']['README.txt']['working']
        self.f.worker.responses.append(artifact('settings.json', '{"workers":2,"enabled":true}\n'))
        self.request(state)
        original = self.f.worker.result
        with patch.object(self.f.worker, 'result', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.f.workflow.run(self.f.task['id'])
        self.f.workflow = Workflow(self.f.ledger, self.f.worker)
        with patch.object(self.f.worker, 'result', side_effect=original):
            done = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(done['phase'], 'completed')
        self.assertEqual(len(self.f.worker.calls), 4)
        self.assertEqual(self.f.workflow.store.load(done['snapshot'])['files']['README.txt']['working'], sibling)
        self.assertEqual(done['outputs'][1]['verification'], 'passed')
        again = self.request(state)
        self.assertEqual(again['status'], 'candidate_produced')
        self.assertEqual(len(done['reviews']), 1)
        with self.assertRaisesRegex(LedgerError, 'different correction'):
            self.request(state, comment='Different content')

    def test_scope_escape_is_rejected_and_cap_cannot_be_reset(self):
        state = self.f.workflow.run(self.f.task['id'])
        self.request(state)
        self.f.worker.responses.append(artifact('README.txt', 'Changed independent work'))
        failed = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(failed['phase'], 'blocked')
        self.assertEqual(failed['snapshot'], state['snapshot'])
        self.assertNotEqual(failed['verification'], 'passed')
        with self.assertRaises(LedgerError):
            self.f.workflow.review(self.f.task['id'], state['snapshot'], 'accept', 'Old evidence cannot accept')
        with self.assertRaises(LedgerError):
            self.request(failed, key='correction-2')

    def test_invalid_correction_fails_unchanged_gates_without_extra_repair(self):
        state = self.f.workflow.run(self.f.task['id'])
        self.request(state)
        self.f.worker.responses.append(artifact('settings.json', '{"workers":200,"enabled":true}'))
        failed = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(failed['phase'], 'blocked')
        self.assertEqual(failed['verification'], 'failed')
        self.assertEqual(failed['repairs'], 1)
        self.assertEqual(len(self.f.worker.calls), 4)

    def test_stale_review_active_writer_cancel_and_persistence_failure(self):
        early = self.f.workflow.run(self.f.task['id'], steps=2)
        state = self.f.workflow.run(self.f.task['id'])
        with self.assertRaisesRegex(LedgerError, 'Stale workflow'):
            self.request(early)
        with self.assertRaisesRegex(LedgerError, 'source changed'):
            self.request(state, output=early['snapshot'], selected=['doc'])
        with patch.object(self.f.workflow, 'persist', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.request(state)
        self.assertEqual(self.f.workflow.state(self.f.task['id'])[1], state)
        with patch.object(self.f.workflow.control, 'status', wraps=self.f.workflow.control.status) as status:
            original = status(task_id=self.f.task['id'])
            status.return_value = dict(original, attempts=[{'status':'unknown'}])
            with self.assertRaisesRegex(LedgerError, 'writers'):
                self.request(state)
        self.f.workflow.control.cancel(self.f.task['id'])
        with self.assertRaisesRegex(LedgerError, 'non-cancelled'):
            self.request(state)

    def test_repair_cap_and_deadline_and_budget_checked_before_scheduling(self):
        state = self.f.workflow.run(self.f.task['id'])
        original = self.f.workflow.control.status(self.f.task['id'])
        for changed, message in ((dict(original, deadline='2000-01-01T00:00:00+00:00'), 'deadline'),
                                 (dict(original, used_calls=6), 'budget')):
            with patch.object(self.f.workflow.control, 'status', return_value=changed):
                with self.assertRaisesRegex(LedgerError, message):
                    self.request(state)
        self.request(state)
        self.f.worker.responses.append(artifact('settings.json', '{"workers":2,"enabled":true}\n'))
        done = self.f.workflow.run(self.f.task['id'])
        with self.assertRaisesRegex(LedgerError, 'Repair cap'):
            self.request(done, key='correction-2')

    def test_dependent_paths_included_and_scheduled_correction_cannot_be_skipped(self):
        self.f.worker.responses[0] = plan()
        state = self.f.workflow.run(self.f.task['id'])
        record = self.request(state)
        self.assertEqual(record['affected_tasks'], ['config', 'doc'])
        _, scheduled = self.f.workflow.state(self.f.task['id'])
        self.assertEqual(scheduled['feedback_repair']['owned'], ['README.txt', 'settings.json'])
        with self.assertRaisesRegex(LedgerError, 'scheduled review correction'):
            self.f.workflow.recheck(self.f.task['id'], scheduled['snapshot'])
        from onecrew.amendment import apply
        from test_workflow import profile
        with self.assertRaisesRegex(LedgerError, 'scheduled review correction'):
            apply(self.f.workflow, self.f.task['id'], content_hash(scheduled), '0'*64, profile(), ['config'], 'Changed requirement')
        self.f.worker.responses.append(artifact('settings.json', '{"workers":2,"enabled":true}\n'))
        with patch.object(self.f.worker, 'run', wraps=self.f.worker.run) as run:
            done = self.f.workflow.run(self.f.task['id'])
        self.assertIn('Format the configuration', run.call_args.args[1])
        self.assertEqual(done['phase'], 'completed')


if __name__ == '__main__':
    unittest.main()
