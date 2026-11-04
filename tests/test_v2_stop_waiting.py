"""v2.1 job 11a, item 3: the Stop hook lets the session end its turn while the plan waits for something that is not the session's to do
(a receipt without its verdict, an open owner question), and keeps blocking an unfinished plan otherwise."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_l2 imports test_v2_l1 by its plain name
from test_v2_l2 import HookFixture, owned_plan                      # noqa: E402

from onecrew.snapshots import Snapshots                             # noqa: E402
from onecrew.v2 import plan as plans, verdict                       # noqa: E402
from onecrew.v2.verifiers import command                            # noqa: E402
from tests.test_v2_l1 import milestone                              # noqa: E402


class StopWaitingTests(HookFixture):
    def setUp(self):
        super().setUp()
        clock = patch.object(command, 'MIN_SECONDS', 0.0); clock.start(); self.addCleanup(clock.stop)
        self.enforce(value=owned_plan(milestones=[milestone('M1'), milestone('M2')]))
        self.anchor = plans.show(self.ledger, 'P1')['anchor_task']

    def stop(self, session):
        return self.run_hook('stop', {'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'Stop', 'stop_hook_active': False})

    def last(self):
        return self.violations()[-1]

    def stray_receipt(self, milestone_id='M1'):
        self.issue(Snapshots(self.ledger.state_root).blob(b'{}'), milestone_id)       # verdict.run announces a receipt just before it records

    def open_question(self):
        self.ledger.create_request(self.anchor, 'v2q-waiting', {
            'schema_version': 1, 'question': 'Milestone M1 failed. What now?', 'reason': 'A stop limit was reached.', 'impact': 'Nothing is dispatched.',
            'options': [{'id': 'amend_plan', 'label': 'Amend'}, {'id': 'stop', 'label': 'End'}], 'recommendation': 'amend_plan',
            'action': {'type': 'v2.plan_stopped', 'parameters': {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'key': 'v2q-waiting'}}})

    def test_an_unfinished_plan_with_nothing_in_flight_is_still_blocked(self):
        code, out, _ = self.stop('s-blocked')
        self.assertEqual(code, 0); self.assertEqual(json.loads(out)['decision'], 'block')
        self.assertEqual(self.last()['event'], 'stop_blocked')

    def test_a_receipt_without_a_verdict_lets_the_session_go_and_is_logged_not_blocked(self):
        self.stray_receipt()
        code, out, err = self.stop('s-receipt')
        self.assertEqual((code, out.strip(), err), (0, '', ''))
        self.assertEqual((self.last()['event'], self.last()['rule']), ('logged', 'stop_waiting'))
        self.assertIn('receipt without a verdict for M1', self.last()['reason'])
        self.assertNotIn('stop_blocked', [v['event'] for v in self.violations()])

    def test_an_open_owner_question_lets_the_session_go(self):
        self.open_question()
        code, out, err = self.stop('s-question')
        self.assertEqual((code, out.strip(), err), (0, '', ''))
        self.assertEqual((self.last()['event'], self.last()['rule']), ('logged', 'stop_waiting'))
        self.assertIn('open owner question', self.last()['reason'])

    def test_a_receipt_that_has_its_verdict_no_longer_lets_go(self):
        self.stray_receipt()
        self.assertEqual(self.stop('s-one')[1].strip(), '')
        verdict.run(self.ledger, 'P1', 'M1', self.root)                            # a later receipt and its verdict.recorded for the same milestone
        code, out, _ = self.stop('s-two')
        self.assertEqual(code, 0); self.assertEqual(json.loads(out)['decision'], 'block')       # M2 still has no verdict, nothing is waiting
        self.assertEqual(self.last()['rule'], 'stop_pending_milestone')

    def test_the_block_cap_still_applies_to_an_unfinished_plan(self):
        for _ in range(2): self.assertEqual(json.loads(self.stop('s-cap')[1])['decision'], 'block')
        self.assertEqual(self.stop('s-cap')[1].strip(), '')
        self.assertIn('stop_cap', [v['rule'] for v in self.violations()])
