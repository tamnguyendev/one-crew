from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import unittest
from unittest.mock import patch

import test_control as fixtures
from onecrew.budget import extend, remove_deadline, UNBOUNDED_DEADLINE
from onecrew.control import Control
from onecrew.ledger import Ledger, LedgerError


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ControlTests()
        self.f.setUp()
        self.old = self.f.ledger.task(self.f.task['id'])['budget']
        self.end = (dt.datetime.fromisoformat(self.f.task['created_at'])+dt.timedelta(hours=1)).isoformat()

    def tearDown(self):
        self.f.tearDown()

    def extend(self, **kwargs):
        values = {'revision': self.old['revision'], 'request_key': 'extension-1', 'max_calls': 5,
                  'deadline': self.end, 'reason': 'Finish the approved scope.'}
        values.update(kwargs)
        return extend(self.f.control, self.f.task['id'], **values)

    def test_extend_exhausted_root_preserves_used_original_grant_and_duplicate_receipt(self):
        f = self.f
        for i in range(3):
            attempt = f.reserve(str(i))
            f.control.finish(attempt['id'], attempt['generation'], {'fixture': True})
        with self.assertRaisesRegex(LedgerError, 'budget'):
            f.reserve('four')
        receipt = self.extend()
        self.assertEqual(receipt['used_calls'], 3)
        self.assertFalse(receipt['automatic_resume'])
        self.assertEqual(self.extend(), receipt)
        restarted = Control(Ledger(f.project, f.base/'state'))
        self.assertEqual(restarted.status(f.task['id'])['deadline'], self.end)
        task = f.ledger.task(f.task['id'], full=True)
        self.assertEqual(task['handoff']['grant']['limits']['max_calls'], 3)
        self.assertEqual(task['budget']['limits']['max_calls'], 5)
        self.assertEqual(task['budget']['used_calls'], 3)
        attempt = restarted.reserve(f.task['id'], f.execution['revision'], 'four', {'stage': 'fixture'})
        restarted.finish(attempt['id'], attempt['generation'], {'fixture': True})
        self.assertEqual(restarted.status(f.task['id'])['used_calls'], 4)
        with self.assertRaisesRegex(LedgerError, 'another proposal'):
            self.extend(max_calls=6)
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.extend(request_key='stale')

    def test_old_deadline_only_changes_by_explicit_extension(self):
        f = self.f
        f.control.clock = lambda: dt.datetime.fromisoformat(self.old['deadline'])+dt.timedelta(seconds=1)
        with self.assertRaisesRegex(LedgerError, 'deadline'):
            f.reserve()
        self.extend()
        attempt = f.reserve()
        f.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        f.control.finish(attempt['id'], attempt['generation'], {'fixture': True})
        f.control.clock = lambda: dt.datetime.fromisoformat(self.end)+dt.timedelta(seconds=1)
        with self.assertRaisesRegex(LedgerError, 'deadline'):
            f.reserve('after-new-end')

    def test_no_unlimited_shrink_or_unknown_attempt_escape(self):
        f = self.f
        for change in ({'max_calls': True}, {'max_calls': 10001}, {'max_calls': 2},
                       {'deadline': self.end[:19]},
                       {'deadline': (dt.datetime.fromisoformat(f.task['created_at'])+dt.timedelta(hours=9)).isoformat()}):
            with self.assertRaises(LedgerError):
                self.extend(**change)
        attempt = f.reserve()
        f.control.unknown(attempt['id'], 'launch lost')
        with self.assertRaisesRegex(LedgerError, 'reconcile'):
            self.extend()
        self.assertEqual(f.control.status(f.task['id'])['reserved_calls'], 1)
        self.assertEqual(f.ledger.task(f.task['id'])['budget']['revision'], self.old['revision'])

    def test_explicit_next_day_restart_preserves_usage_and_original_grant(self):
        attempt=self.f.reserve()
        self.f.control.finish(attempt['id'],attempt['generation'],{'fixture':True})
        now=dt.datetime.fromisoformat(self.f.task['created_at'])+dt.timedelta(days=1)
        self.f.control.clock=lambda:now
        end=(now+dt.timedelta(minutes=30)).isoformat()
        with self.assertRaises(LedgerError): self.extend(deadline=end)
        receipt=self.extend(deadline=end,restart_expired=True)
        self.assertEqual(receipt['used_calls'],1)
        self.assertEqual(receipt['restart_window']['seconds'],1800)
        self.assertFalse(receipt['automatic_resume'])
        self.assertEqual(self.extend(deadline=end,restart_expired=True),receipt)
        self.assertEqual(self.f.ledger.task(self.f.task['id'],full=True)['handoff']['grant'],self.f.grant)
        self.assertEqual(self.f.control.status(self.f.task['id'])['used_calls'],1)
        self.f.reserve('next-day')

    def test_restart_window_requires_expiry_and_bounded_future_deadline(self):
        with self.assertRaisesRegex(LedgerError,'expired local'): self.extend(restart_expired=True)
        now=dt.datetime.fromisoformat(self.f.task['created_at'])+dt.timedelta(days=1)
        self.f.control.clock=lambda:now
        for seconds in (0,28801):
            with self.assertRaises(LedgerError):
                self.extend(restart_expired=True,deadline=(now+dt.timedelta(seconds=seconds)).isoformat())
        with patch('onecrew.budget.current',return_value=dict(self.old,goal={'remaining_calls':1})):
            with self.assertRaisesRegex(LedgerError,'shared goal'):
                self.extend(restart_expired=True,deadline=(now+dt.timedelta(minutes=30)).isoformat())

    def test_failed_commit_keeps_original_limits(self):
        with patch.object(self.f.ledger, '_event', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.extend()
        self.assertEqual(self.f.ledger.task(self.f.task['id'])['budget'], self.old)
        self.extend()

    def test_concurrent_extensions_have_one_revision_winner(self):
        def contender(key):
            try:
                return self.extend(request_key=key)['budget']['revision']
            except LedgerError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(contender, ['a', 'b']))
        self.assertEqual(sum(r is not None for r in results), 1)
        events = [r for r in self.f.ledger.events(self.f.task['id']) if r['kind'] == 'grant.extended']
        self.assertEqual(len(events), 1)

    def test_explicit_calls_only_survives_restart_and_still_exhausts_calls(self):
        f=self.f
        attempt=f.reserve('before');f.control.finish(attempt['id'],attempt['generation'],{'fixture':True})
        values=dict(revision=self.old['revision'],request_key='no-time',reason='User explicitly removes total time limit.')
        receipt=remove_deadline(f.control,f.task['id'],**values)
        self.assertEqual(remove_deadline(f.control,f.task['id'],**values),receipt)
        self.assertEqual(receipt['used_calls'],1)
        self.assertFalse(receipt['automatic_resume'])
        restarted=Control(Ledger(f.project,f.base/'state'))
        restarted.clock=lambda:dt.datetime.fromisoformat(f.task['created_at'])+dt.timedelta(days=90)
        current=restarted.status(f.task['id'])
        self.assertTrue(current['budget']['time_unlimited'])
        self.assertEqual(current['deadline'],UNBOUNDED_DEADLINE)
        self.assertIsNone(current['budget']['limits']['max_seconds'])
        self.assertEqual(f.ledger.task(f.task['id'],full=True)['handoff']['grant'],f.grant)
        for key in ('two','three'):
            a=restarted.reserve(f.task['id'],f.execution['revision'],key,{'stage':'fixture'})
            restarted.finish(a['id'],a['generation'],{'fixture':True})
        with self.assertRaisesRegex(LedgerError,'call budget'):
            restarted.reserve(f.task['id'],f.execution['revision'],'four',{'stage':'fixture'})

    def test_remove_deadline_rejects_unknown_stale_shared_and_cancelled(self):
        f=self.f
        def call(revision=None):
            return remove_deadline(f.control,f.task['id'],revision or self.old['revision'],'no-time','Actual user request')
        with self.assertRaisesRegex(LedgerError,'Stale'):call('stale')
        with patch('onecrew.budget.current',return_value=dict(self.old,goal={'remaining_calls':1})):
            with self.assertRaisesRegex(LedgerError,'shared goal'):call()
        a=f.reserve();f.control.unknown(a['id'],'unknown process outcome')
        with self.assertRaisesRegex(LedgerError,'reconcile'):call()
        f.control.finish(a['id'],a['generation'],{'fixture':True})
        f.control.cancel(f.task['id'])
        with self.assertRaisesRegex(LedgerError,'cancelled'):call()


if __name__ == '__main__':
    unittest.main()
