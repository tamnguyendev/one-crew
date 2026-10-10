import contextlib
import io
import json
import unittest
from unittest.mock import patch

from onecrew.workflow import Workflow
from onecrew.workflow_cli import main as work_cli
from onecrew.owned_cli import main as job_cli
from onecrew.notifications import ack
from onecrew.notification_watch import watch, lifecycle
from onecrew.notification_receipts import begin, confirm
from tests.test_notification_receipts import host_evidence
from tests import test_native_change, test_owned
from tests.test_owned import action


class OwnedHandoffTests(unittest.TestCase):
    def cli(self, entry, ledger, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = entry(['--project', str(ledger.project), '--state-root', str(ledger.state_root), *args])
        self.assertEqual(code, 0, output.getvalue())
        return output.getvalue()

    def test_native_completion_outputs_and_notification_receipt_lifecycle(self):
        fixture = test_native_change.NativeChangeTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        run, task, worker = fixture.run, fixture.task, fixture.worker
        worker.responses = [fixture.candidate(), {'accepted': True, 'feedback': 'Verified fixture.'}]
        def gate(runtime, task_id, state, recipe):
            return {'passed': True, 'detail': '1 fixture test passed; no device test.',
                    'evidence': {'snapshot': state['snapshot'], 'exit_code': 0}}
        with patch('onecrew.native_change.verify', side_effect=gate):
            for _ in range(4): state = run.run(task, steps=1)
        self.assertEqual(state['phase'], 'completed')
        before = run.state(task)
        calls = list(worker.calls)
        # The previously broken entry uses Workflow, not Owned.
        card = Workflow(run.ledger).outputs(task)
        self.assertEqual(card['verification'], 'passed')
        self.assertTrue(card['original_workspace_modified'])
        self.assertEqual(len(card['changes']), 2)
        self.assertIn('+int add', card['changes'][0]['diff'])
        self.assertTrue(card['review'][0]['accepted'])
        self.assertNotIn('tool_baseline', card['native_change'])
        work = json.loads(self.cli(work_cli, run.ledger, 'work', 'outputs', task, '--json'))
        job = json.loads(self.cli(job_cli, run.ledger, 'job', 'outputs', task))
        self.assertEqual(work, job)
        for args in [('work', 'outputs', task), ('work', 'outputs', task, '--full'), ('work', 'status', task)]:
            text = self.cli(work_cli, run.ledger, *args)
            self.assertIn(task, text)
            self.assertIn('passed', text)
        consumer = 'native-handoff'
        batch = watch(run.ledger, consumer, [task])
        self.assertTrue(batch['notifications'])
        delivery = begin(run.ledger, consumer, batch['id'], 'thread-fixture', 'automation-fixture',
                         card['report'])
        from onecrew.ledger import LedgerError
        with self.assertRaises(LedgerError): ack(run.ledger, consumer, batch['id'], True)
        confirm(run.ledger, consumer, batch['id'], host_evidence(delivery))
        ack(run.ledger, consumer, batch['id'], True)
        self.assertTrue(lifecycle(run.ledger, consumer, [task])['should_pause'])
        self.assertEqual(run.state(task), before)
        self.assertEqual(worker.calls, calls)

    def test_audit_and_running_checkpoints_need_no_legacy_backlog(self):
        fixture = test_owned.OwnedTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        run, task, worker = fixture.runtime([action('read', path='calc.py'),
            action('finish', report='Subtraction found. No tests run.')])
        for completed in (False, True):
            if completed: run.run(task)
            card = Workflow(run.ledger).outputs(task)
            self.assertEqual(card['changes'], [])
            self.assertEqual(card['tests'], [])
            self.assertFalse(card['original_workspace_modified'])
            self.assertIn(task, self.cli(work_cli, run.ledger, 'work', 'outputs', task, '--full'))
        self.assertIn('No tests run', card['report'])
