import datetime as dt
import unittest
from unittest.mock import patch

from tests import test_owned as fixtures
from onecrew.owned_intake import submit
from onecrew.owned import Owned
from onecrew.effort_watch import check
from onecrew.budget_policy import recommend
from onecrew.ledger import content_hash
from onecrew.learning import outcomes, lessons


class BudgetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_defaults_explicit_override_and_replay_ignore_new_history(self):
        t=submit(self.f.ledger,'Inspect source','new')
        self.assertEqual(t['budget']['limits'],{'max_calls':100,'max_seconds':7200})
        with patch('onecrew.budget_policy.recommend',side_effect=AssertionError('Replay must not replan')):
            self.assertEqual(submit(self.f.ledger,'Inspect source','new')['id'],t['id'])
        t=submit(self.f.ledger,'Inspect source','small',max_calls=7,max_seconds=900)
        self.assertEqual(t['budget']['limits'],{'max_calls':7,'max_seconds':900})
        self.assertEqual(submit(self.f.ledger,'Inspect source','small')['id'],t['id'])

    def test_70_percent_calls_checkpoint_and_continue_uses_remaining_budget(self):
        run,task,worker=self.f.runtime([])
        seq,state=run.state(task);control=run.control.status(task)
        control['used_calls']=69
        with patch.object(run.control,'status',return_value=control):
            seq,wait=check(run,task,seq,state);self.assertFalse(wait)
        control['used_calls']=70
        with patch.object(run.control,'status',return_value=control):
            seq,wait=check(run,task,seq,state);self.assertTrue(wait)
        r=self.f.ledger.requests(task,pending=True)[0]
        self.assertIn('70%',r['question']['question'])
        self.assertEqual(state['effort_watch']['assessment']['remaining_calls'],30)
        self.f.ledger.reply(r['id'],r['revision'],'continue')
        with patch.object(run.control,'status',return_value=control):
            seq,wait=check(run,task,seq,state)
        self.assertFalse(wait);self.assertEqual(state['effort_watch']['policy']['calls'],21)
        self.assertEqual(run.control.status(task)['budget']['limits']['max_calls'],100)
        self.assertFalse(worker.calls)

    def test_wall_deadline_threshold_no_early_ten_minute_stop(self):
        run,task,worker=self.f.runtime([])
        seq,state=run.state(task)
        start=dt.datetime.fromisoformat(self.f.ledger.task(task)['created_at'])
        for minutes,expected in ((11,False),(83,False),(84,True)):
            with patch.object(run.control,'clock',return_value=start+dt.timedelta(minutes=minutes)):
                seq,wait=check(run,task,seq,state)
            self.assertEqual(wait,expected)
        self.assertFalse(worker.calls)

    def test_old_task_without_policy_retains_budget_and_warning(self):
        from onecrew.ledger import canonical
        t=submit(self.f.ledger,'Legacy','old',max_calls=20,max_seconds=1200)
        # Fixture for a task sealed before budget_policy existed, without runtime.
        with self.f.ledger.transaction(write=True) as conn:
            import json
            row=self.f.ledger._task(conn,t['id']);payload=json.loads(row['payload'])
            payload['owned_execution'].pop('budget_policy');payload['owned_execution'].pop('budget_advice')
            conn.execute('UPDATE tasks SET payload=?,revision=? WHERE id=?',(canonical(payload),content_hash(payload),t['id']))
        replay=submit(self.f.ledger,'Legacy','old')
        self.assertEqual(replay['budget']['limits'],{'max_calls':20,'max_seconds':1200})
        run=Owned(self.f.ledger,fixtures.FixtureWorker(self.f.ledger,[]));run.enable(t['id'])
        seq,state=run.state(t['id']);check(run,t['id'],seq,state)
        self.assertEqual(state['effort_watch']['policy'],{'calls':20,'seconds':600})

    def test_retrospective_is_proposed_and_time_measurements_honest(self):
        run,task,worker=self.f.runtime([])
        seq,state=run.state(task);state.update(phase='blocked')
        seq=run.persist(task,seq,state);run.persist(task,seq,state)
        rows=outcomes(self.f.ledger);self.assertEqual(len(rows),1)
        self.assertGreaterEqual(rows[0]['timing']['wall_seconds'],0)
        self.assertIsNone(rows[0]['timing']['active_compute_seconds'])
        self.assertIsNone(rows[0]['timing']['wait_seconds'])
        self.assertEqual(len(lessons(self.f.ledger)),1)
        self.assertFalse(lessons(self.f.ledger)[0]['automatic_promotion'])

    def test_advice_uses_unique_verified_exact_matches_and_never_applies(self):
        base={'spec_revision':content_hash('Goal'),'mode':'audit','provider':'claude','model':'sonnet',
              'phase':'completed','verification':'evidence_collected','managed_calls':12,
              'timing':{'wall_seconds':800}}
        rows=[dict(base,task=str(i),event=i+1) for i in range(3)]
        with patch('onecrew.learning.outcomes',return_value=rows):
            advice=recommend(self.f.ledger,'Goal','audit','claude','sonnet')
            self.assertEqual(advice['recommended'],{'max_calls':20,'max_seconds':1200})
            self.assertFalse(advice['automatic_application'])
            self.assertEqual(recommend(self.f.ledger,'Different','audit','claude','sonnet')['classification'],'insufficient_history')
        for history in (rows[:1]*3,[dict(rows[0],phase='blocked')]+rows, [dict(r,acceptance='changes_requested') for r in rows]):
            with patch('onecrew.learning.outcomes',return_value=history):
                self.assertEqual(recommend(self.f.ledger,'Goal','audit','claude','sonnet')['classification'],'insufficient_history')


if __name__=='__main__': unittest.main()
