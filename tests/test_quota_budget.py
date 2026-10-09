from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import datetime as dt
import unittest

import test_workflow as fixtures
from onecrew.ledger import LedgerError, content_hash
from onecrew.quota_budget import bind
from onecrew.workflow import Workflow


def evidence(now, remaining=13):
    return {'account':'subscription-main', 'bucket':'codex', 'provider':'codex', 'model':'fixture', 'quota': {
        'source':'operator-fixture', 'observed_at':now.isoformat(), 'expires_at':(now+dt.timedelta(minutes=2)).isoformat(),
        'windows':[{'name':'weekly', 'remaining':remaining, 'reserved':0, 'keep_for_chat':10,
                    'estimated_call':2, 'resets_at':(now+dt.timedelta(days=7)).isoformat()}]}}


class QuotaBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.f.enable()
        self.now = dt.datetime.now(dt.timezone.utc)
        self.f.workflow.control.clock = lambda: self.now
        self.binding = evidence(self.now)
        self.attach(self.f.workflow, self.f.task, self.binding)

    def tearDown(self):
        self.f.tearDown()

    def attach(self, workflow, task, binding):
        return bind(workflow, task['id'], content_hash(workflow.state(task['id'])[1]), binding)

    def second(self, binding=None):
        task = self.f.ledger.submit('SPEC-001', self.f.task['spec_revision'], 'second',
            {'schema_version':1,'permissions':['artifact.generate'],'limits':{'max_calls':6,'max_seconds':300},'source':'fixture'})
        workflow = Workflow(self.f.ledger, self.f.worker)
        workflow.enable(task['id'], task['revision'], fixtures.profile())
        workflow.control.clock = lambda: self.now
        self.attach(workflow, task, binding or self.binding)
        return workflow, task

    def reserve(self, workflow=None, task=None, key='one', callback=None):
        workflow, task = workflow or self.f.workflow, task or self.f.task
        config = workflow.control.status(task['id'])
        return workflow.control.reserve(task['id'], config['revision'], key,
            {'stage':'fixture','provider':'codex','model':'fixture'}, on_reserved=callback)

    def test_concurrent_roots_cannot_spend_the_same_remaining_quota(self):
        workflow, task = self.second()
        def invoke(w, t):
            try:
                return self.reserve(w,t)
            except LedgerError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair:invoke(*pair), [(self.f.workflow,self.f.task),(workflow,task)]))
        self.assertEqual(sum(isinstance(r,dict) for r in results), 1)
        self.assertIn('Shared account quota insufficient', next(r for r in results if isinstance(r,str)))
        with self.f.ledger.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='quota.reserved'").fetchone()[0], 1)

    def test_known_not_started_releases_but_unknown_and_settled_spend_are_retained(self):
        workflow, task = self.second()
        first = self.reserve()
        self.f.workflow.control.finish(first['id'], first['generation'], {'not_started':True}, not_started=True)
        row = self.reserve(workflow,task)
        workflow.control.unknown(row['id'],'No launch acknowledgement')
        with self.assertRaisesRegex(LedgerError,'Shared account quota'):
            self.reserve(key='two')
        workflow.control.finish(row['id'],row['generation'],{'stopped':True})
        with self.assertRaisesRegex(LedgerError,'Shared account quota'):
            self.reserve(key='two')
        self.assertEqual(workflow.control.status(task['id'])['used_calls'],1)

    def test_reservation_dedup_rollback_and_launch_freshness(self):
        def failed_checkpoint(conn, attempt):
            raise OSError('checkpoint failed')
        with self.assertRaises(OSError):
            self.reserve(callback=failed_checkpoint)
        with self.f.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='quota.reserved'").fetchone()[0],0)
        row = self.reserve()
        self.assertEqual(self.reserve()['id'],row['id'])
        self.now += dt.timedelta(minutes=2,seconds=1)
        with self.assertRaisesRegex(LedgerError,'stale'):
            self.f.workflow.control.launched(row['id'],row['generation'],{'fixture':True})
        self.f.workflow.control.finish(row['id'],row['generation'],{'not_started':True},not_started=True)
        self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['used_calls'],0)

    def test_reset_requires_new_observation_and_unknown_crossing_reset_stays_held(self):
        binding = deepcopy(self.binding)
        binding['quota']['windows'][0]['resets_at'] = (self.now+dt.timedelta(seconds=1)).isoformat()
        self.attach(self.f.workflow,self.f.task,binding)
        row = self.reserve()
        self.f.workflow.control.unknown(row['id'],'ambiguous')
        self.now += dt.timedelta(seconds=2)
        workflow, task = self.second(evidence(self.now))
        with self.assertRaisesRegex(LedgerError,'Shared account quota'):
            self.reserve(workflow,task)
        self.f.workflow.control.finish(row['id'],row['generation'],{'stopped':True})
        with self.assertRaisesRegex(LedgerError,'Shared account quota'):
            self.reserve(workflow,task)

    def test_spend_settled_before_old_reset_does_not_reserve_the_next_window(self):
        binding = deepcopy(self.binding)
        binding['quota']['windows'][0]['resets_at'] = (self.now+dt.timedelta(seconds=1)).isoformat()
        self.attach(self.f.workflow,self.f.task,binding)
        row = self.reserve()
        self.f.workflow.control.finish(row['id'],row['generation'],{'stopped':True})
        self.now += dt.timedelta(seconds=2)
        workflow, task = self.second(evidence(self.now))
        self.assertIn('id',self.reserve(workflow,task))

    def test_full_workflow_uses_bound_quota_and_cannot_refresh_away_identity(self):
        self.attach(self.f.workflow,self.f.task,evidence(self.now,remaining=16))
        done = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(done['phase'],'completed')
        with self.f.ledger.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='quota.reserved'").fetchone()[0],3)
        for field,value in (('account','different'),('bucket','different')):
            binding = evidence(self.now,remaining=16)
            binding[field] = value
            with self.assertRaisesRegex(LedgerError,'pinned'):
                self.attach(self.f.workflow,self.f.task,binding)
        binding = evidence(self.now,remaining=16)
        binding['quota']['windows'][0]['name'] = 'other-window'
        with self.assertRaisesRegex(LedgerError,'removed or renamed'):
            self.attach(self.f.workflow,self.f.task,binding)


if __name__ == '__main__':
    unittest.main()
