"""T12 gaps (R03 W24): on a VERIFIED root waiting for acceptance, a failed send, its retry and closing the window are notice states
only - the root stays verified, never failed, never accepted.

Precondition built for real: an approved root whose only milestone passed through `verdict run` (all milestones passed, status
approved, the v2 'verified' notice is due, no plan.accepted). Fixture: the real v1 desktop outbox and records; the launcher is a fake
that first fails and then succeeds; the Tk window is the recording fake of tests/test_wf_t43_gaps. Nothing is shown on screen.
"""
import os
from pathlib import Path
from unittest.mock import patch

from onecrew import desktop_notifications as desktop, desktop_window
from onecrew.v2 import exceptions, plan, verdict
from tests.test_v2_l1 import Fixture
from tests.test_wf_t43_gaps import fake_tk

PRODUCT_RUNS = ('verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded', 'milestone.passed', 'milestone.failed')


class VerifiedRootNoticeTests(Fixture):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, ONECREW_DESKTOP_HOME=str(Path(self.temp.name) / 'desktop'))
        env.start(); self.addCleanup(env.stop)
        self.launch = patch.object(desktop, 'launch').start()
        self.addCleanup(patch.stopall)
        desktop.configure(self.ledger, True)
        self.approved()
        verdict.run(self.ledger, 'P1', 'M1')
        self.assert_verified()
        notices = [i['notice'] for i in exceptions.desktop_snapshots(self.ledger)]
        self.assertEqual([n['status'] for n in notices], ['verified'])                   # one notice to send
        self.assertTrue(notices[0]['delivery_is_not_acceptance'])

    def assert_verified(self):
        shown = plan.show(self.ledger, 'P1')
        self.assertEqual(shown['status'], 'approved')                                    # [E4] never failed / stopped
        self.assertTrue(shown['milestones'] and all(m['state'] == 'passed' for m in shown['milestones']))   # [E1] still verified
        self.assertNotIn('plan.accepted', self.kinds())                                  # [E3]/[E6] no acceptance without the verb

    def record(self):
        records = desktop.status(self.ledger)['records']
        self.assertEqual(len(records), 1)
        return records[0]

    def test_e1_e4_failed_send_is_undelivered_notice_state_and_the_root_stays_verified(self):
        before = self.events()
        self.launch.side_effect = OSError('fixture transport unavailable')
        desktop.publish(self.ledger)
        self.assertEqual(self.record()['status'], 'pending')                             # "chua giao": a separate record
        self.assertIn('fixture transport unavailable', self.record()['error'])
        self.assert_verified()                                                           # [E4] not failed because of the notice
        self.assertEqual(self.events(), before)                                          # the ledger is untouched by the failure
        self.launch.side_effect = None
        desktop.publish(self.ledger)                                                     # retry
        self.assertEqual(self.record()['status'], 'launching')                           # "da giao" (handed to the window)
        self.assertEqual(self.launch.call_count, 2)
        self.assert_verified()
        self.assertEqual(self.events(), before)
        self.assertEqual([k for k in self.kinds() if k in PRODUCT_RUNS].count('verdict.recorded'), 1)   # no product re-run

    def test_e3_e6_closing_the_window_of_a_verified_root_is_not_acceptance(self):
        desktop.publish(self.ledger)
        record = self.record()
        before = self.events()
        with patch.dict('sys.modules', fake_tk(self)):
            desktop_window.show(desktop.directory(self.ledger), record['id'])
        closed = self.record()
        self.assertEqual(closed['status'], 'closed')
        self.assertFalse(closed['answers_recorded'])
        self.assertFalse(closed['user_attention_verified'])
        self.assertEqual(self.events(), before)                                          # [E3] no accepted (no event at all)
        self.assert_verified()
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')             # [E6] 'accepted' needs the accept verb
        desktop.publish(self.ledger)
        self.assertEqual(self.launch.call_count, 1)                                      # a closed notice is not re-sent by itself
