"""T43c (W24b) [E20], [E21], [E23]: six hours without an exception produce no notice at all; nothing enables a heartbeat; no system-written "read".

Same fixture as tests/test_wf_exceptions. After the approved estimate, the exception observer is polled every hour for six hours of the
fake clock with nothing happening: zero notices, zero `notice.exception` events, no request. Counter-rule (E21): a notifier that wrote a
notice every hour would leave six. The delivery status of a published notice is "delivered"/"closed" by the window, never "read".
"""
from pathlib import Path

from onecrew import desktop_notifications as desktop
from onecrew.v2 import exceptions, plan
from tests.test_wf_exceptions import ExceptionTests


class QuietHoursTests(ExceptionTests):
    def test_e20_e21_six_quiet_hours_produce_no_notice_and_no_heartbeat(self):
        self.start()
        before = (len(self.notices()), self.kinds().count('notice.exception'), len(self.ledger.requests()))
        hourly = []
        for hour in range(7):                                                                    # 10:00 .. 16:00 of the fake clock
            hourly.append(exceptions.observe(self.ledger, 'P1', f'2026-10-24T{10 + hour:02d}:00:00+07:00'))
        self.assertEqual(hourly, [[]] * 7)                                                       # [E20] nothing to say, nothing said
        self.assertEqual((len(self.notices()), self.kinds().count('notice.exception'), len(self.ledger.requests())), before)   # [E21] not six
        desktop.configure(self.ledger, True); desktop.publish(self.ledger)
        self.assertEqual(desktop.status(self.ledger)['records'], [])
        state_root = Path(self.ledger.state_root)
        self.assertEqual([p.name for p in state_root.rglob('*') if p.is_file() and 'heartbeat' in p.name.lower()], [])   # [E21] no heartbeat enabled
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')

    def test_e23_delivery_status_is_never_a_system_written_read(self):
        desktop.configure(self.ledger, True)
        self.propose()
        desktop.publish(self.ledger)
        records = desktop.status(self.ledger)['records']
        self.assertEqual(len(records), 1)
        self.assertIn(records[0]['status'], ('launching', 'delivered', 'pending', 'closed'))            # transport states only
        self.assertNotIn('read', records[0]['status'])
        self.assertFalse(records[0].get('user_attention_verified', False))                        # [E23] attention is never inferred
