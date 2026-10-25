"""T43c (W24b) [E20], [E21], [E23]: six hours without an exception produce no notice at all; nothing enables a heartbeat; no system-written "read".

Same fixture as tests/test_wf_exceptions. After the approved estimate, the exception observer is polled every hour for six hours of the
fake clock with nothing happening: zero notices, zero `notice.exception` events, no request. Counter-rule (E21): a notifier that wrote a
notice every hour would leave six. The delivery status of a published notice is "delivered"/"closed" by the window, never "read".
"""
from pathlib import Path
from unittest.mock import patch

from onecrew import desktop_notifications as desktop
from onecrew.v2 import estimates, exceptions, plan
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

    # ---- W24b: one baseline exceedance, many small reforecasts (each with its own evidence) -> one notice, one desktop card --------------
    def test_w24b_small_reforecasts_over_baseline_notify_once(self):
        self.start(span=(3600, 7200))
        desktop.configure(self.ledger, True)
        for n, span in enumerate(([8000, 9000], [9000, 9500], [9000, 9600]), 1):              # each under the 25% change policy
            estimates.reforecast(self.ledger, 'P1', f'r{n}', span, f'reforecast {n}', [f'evidence:r{n}'])
            exceptions.observe(self.ledger, 'P1', f'2026-10-24T1{n}:00:00+07:00')
        self.assertEqual(self.kinds().count('notice.exception'), 1)                           # was 3: cause keyed on hash(evidence)
        cards = self.notices()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['eta']['remaining_seconds'], [9000, 9600])                  # live ETA, first notice
        desktop.publish(self.ledger)
        self.assertEqual(len(desktop.status(self.ledger)['records']), 1)

    def test_w24b_renotify_after_policy_crossed_again_supersedes_undelivered_card(self):
        self.start(span=(3600, 7200))
        def reforecast(key, span, reason):
            with patch.object(exceptions, 'observe'):                                         # observed below on the fake clock
                estimates.reforecast(self.ledger, 'P1', key, span, reason, ['evidence:' + key])
        reforecast('r1', [8000, 9000], 'first over baseline')
        first = exceptions.observe(self.ledger, 'P1', '2026-10-24T10:00:00+07:00')
        reforecast('r2', [9000, 11000], 'under 25% of the last notified 9000')
        self.assertEqual(exceptions.observe(self.ledger, 'P1', '2026-10-24T11:00:00+07:00'), [])
        reforecast('r3', [9000, 11500], 'over 25% of the last notified 9000')
        again = exceptions.observe(self.ledger, 'P1', '2026-10-24T12:00:00+07:00')
        self.assertEqual((len(first), len(again)), (1, 1))
        self.assertEqual(self.kinds().count('notice.exception'), 2)
        cards = self.notices()                                                                # nothing delivered yet: newest only
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['reason'], 'over 25% of the last notified 9000')
        self.assertEqual(cards[0]['event_at'], '2026-10-24T10:00:00+07:00')                   # the time of the first notice
        self.assertEqual(exceptions.observe(self.ledger, 'P1', '2026-10-24T13:00:00+07:00'), [])

    def test_w24b_budget_warning_has_one_desktop_card(self):
        from onecrew.v2 import executors
        from tests.test_v2_l1 import plan_json
        self.approved('P1', plan_json(budget={'max_calls': 100, 'time': 180}),
                      estimate={'execution_seconds': [21600, 28800], 'evidence': ['fixture:baseline']})
        desktop.configure(self.ledger, True)
        managed = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))
        for attempt, start, end in (('m1', 8, 11), ('m2', 11, 12)):
            for what, hour in (('start', start), ('end', end)):
                executors.observe(self.ledger, 'P1', managed, attempt, what, source='executor_clock',
                                  ref=f'clock:{attempt}:{what}', at=f'2026-10-25T{hour:02d}:00:00+07:00')
        self.assertEqual([p['category'] for k, p in self.events() if k == 'notice.exception'], ['budget_warning'])
        cards = self.notices()
        self.assertEqual([(c['status'], c['user_action'], c.get('request')) for c in cards], [('budget_warning', None, None)])
        self.assertIn('Không cần bạn làm gì.', cards[0]['open_content'])
        desktop.publish(self.ledger)
        self.assertEqual(len(desktop.status(self.ledger)['records']), 1)
        self.assertEqual(self.ledger.requests(), [])
