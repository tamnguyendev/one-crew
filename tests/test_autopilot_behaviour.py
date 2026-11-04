"""Eval probes for coordinator recovery that use only APIs present on 356fb82 (Delivery, submit, ledger requests,
desktop snapshots), so the pre-autopilot runtime fails by behaviour, not by a missing module or attribute."""
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from tests import test_solution_delivery as base


class CoordinatorBehaviourTests(unittest.TestCase):
    setUp = base.DeliveryTests.setUp
    create = base.DeliveryTests.create

    def clear_backoff(self, r, t):
        seq, s = r.state(t); s['delivery']['retry_after'] = None; r.persist(t, seq, s)

    def test_transient_node_failure_is_retried_not_blocked(self):
        r, t = self.create(); r.run(t)
        source = r.state(t)[1]['delivery']['source']['hash']
        outcomes = iter([LedgerError('ADB operation failed; raw output withheld to protect private inputs.'),
                         {'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}}])
        def execute(*args):
            value = next(outcomes)
            if isinstance(value, Exception): raise value
            return value
        with patch('onecrew.delivery_steps.execute', side_effect=execute) as op:
            s = r.run(t)
            self.assertNotEqual(s['phase'], 'blocked', 'RED-AUTOPILOT-RETRY: transient failure blocked the root')
            self.clear_backoff(r, t); s = r.run(t)
        self.assertEqual(op.call_count, 2, 'RED-AUTOPILOT-RETRY: node was not retried')
        self.assertEqual(s['delivery']['nodes']['tests']['phase'], 'passed')
        self.assertEqual(self.ledger.requests(t, pending=True), [])

    def test_unrecoverable_failure_asks_one_typed_question(self):
        r, t = self.create(); r.run(t)
        (self.root / 'app/main.dart').write_text('external edit')  # drift: never auto-accepted
        with patch('onecrew.delivery_steps.execute') as op:
            for _ in range(3): s = r.run(t)
            op.assert_not_called()
        pending = self.ledger.requests(t, pending=True)
        self.assertEqual(len(pending), 1, 'RED-AUTOPILOT-ASK: no single recovery question was created')
        self.assertEqual({o['id'] for o in pending[0]['question']['options']}, {'retry', 'stop'})
        self.assertIn('drift', pending[0]['question']['reason'].lower())
        self.assertNotIn('report_file', s)

    def test_answer_continues_without_entry_resume(self):
        r, t = self.create(); r.run(t)
        with patch('onecrew.delivery_steps.execute', return_value={'passed': False, 'detail': 'Required test skipped'}): r.run(t)
        pending = self.ledger.requests(t, pending=True)
        self.assertEqual(len(pending), 1, 'RED-AUTOPILOT-ANSWER: failure did not raise a question')
        self.ledger.reply(pending[0]['id'], pending[0]['revision'], 'retry', 'test', 'suite fixed by the user')
        source = r.state(t)[1]['delivery']['source']['hash']
        with patch('onecrew.delivery_steps.execute', return_value={'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}}) as op:
            for _ in range(3): s = r.run(t)
        self.assertGreaterEqual(op.call_count, 1, 'RED-AUTOPILOT-ANSWER: answer did not continue the root')
        self.assertEqual(s['delivery']['nodes']['tests']['phase'], 'passed')

    def test_automatic_recovery_opens_no_window(self):
        from onecrew.desktop_notifications import snapshots
        r, t = self.create(); r.run(t)
        with patch('onecrew.delivery_steps.execute', side_effect=LedgerError('ADB operation failed.')): r.run(t)
        self.assertEqual(snapshots(self.ledger, task=t), [], 'RED-AUTOPILOT-SILENT: a self-recoverable failure raised a window')


if __name__ == '__main__': unittest.main()
