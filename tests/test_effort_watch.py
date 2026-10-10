import datetime as dt
import unittest
from unittest.mock import patch
from tests import test_owned as fixtures
from onecrew.owned import Owned
from onecrew.effort_watch import check


class EffortWatchTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.run,self.task,self.worker=self.f.runtime([fixtures.action('read',path='calc.py')],max_calls=30,max_seconds=3600)

    def due(self):
        seq,state=self.run.state(self.task)
        state['effort_watch']={'round':0,'started_at':(self.run.control.clock()-dt.timedelta(minutes=11)).isoformat(),
                               'calls':0,'policy':{'calls':20,'seconds':600},'request':None}
        self.run.persist(self.task,seq,state)

    def answer(self,choice):
        request=self.f.ledger.requests(self.task,pending=True)[0]
        return self.f.ledger.reply(request['id'],request['revision'],choice)

    def test_elapsed_warning_no_model_silence_defer_and_restart(self):
        self.due();state=self.run.run(self.task)
        self.assertEqual(state['phase'],'waiting');self.assertEqual(self.worker.calls,[])
        request=self.f.ledger.requests(self.task,pending=True)[0]
        self.f.ledger.defer(request['id'],request['revision'])
        restarted=Owned(self.f.ledger,self.worker)
        for _ in range(3): restarted.run(self.task)
        self.assertEqual(len(self.f.ledger.requests(self.task)),1)
        self.assertEqual(self.worker.calls,[])
        self.assertEqual(self.f.ledger.request(request['id'])['state'],'pending')

    def test_continue_retains_budget_and_sets_next_warning_window(self):
        self.due();self.run.run(self.task)
        before=self.run.control.status(self.task)['budget'];answer=self.answer('continue')
        state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'running');self.assertEqual(len(self.worker.calls),1)
        self.assertEqual(state['effort_watch']['round'],1)
        self.assertEqual(self.run.control.status(self.task)['budget'],before)
        self.assertEqual(self.f.ledger.request(answer['request_id'])['controller_effect']['reply_id'],answer['id'])
        seq,state=self.run.state(self.task)
        future=dt.datetime.fromisoformat(state['effort_watch']['started_at'])+dt.timedelta(minutes=11)
        with patch.object(self.run.control,'clock',return_value=future): seq,waiting=check(self.run,self.task,seq,state)
        self.assertTrue(waiting);self.assertEqual(len(self.f.ledger.requests(self.task)),2)

    def test_pause_stays_paused_until_explicit_resume(self):
        self.due();self.run.run(self.task);self.answer('pause')
        state=self.run.run(self.task)
        self.assertEqual(state['phase'],'paused');self.assertFalse(self.worker.calls)
        self.run.run(self.task);self.assertFalse(self.worker.calls)
        self.run.resume(self.task);self.run.run(self.task,steps=1)
        self.assertEqual(len(self.worker.calls),1)

    def test_stop_preserves_evidence_and_launches_nothing(self):
        self.due();self.run.run(self.task);self.answer('stop')
        before=self.run.state(self.task)[1]['snapshot'];state=self.run.run(self.task)
        self.assertEqual(state['phase'],'cancelled');self.assertEqual(state['snapshot'],before)
        self.assertTrue(self.run.control.status(self.task)['cancel_requested'])
        self.assertFalse(self.worker.calls)

    def test_call_threshold_not_only_elapsed_time_and_budget_increase_does_not_disable(self):
        # Existing tasks retain their original absolute warning policy.
        self.due()
        seq,state=self.run.state(self.task);control=self.run.control.status(self.task)
        control['used_calls']=20;control['budget']['limits']['max_calls']=10000
        with patch.object(self.run.control,'status',return_value=control): seq,waiting=check(self.run,self.task,seq,state)
        self.assertTrue(waiting);self.assertFalse(self.worker.calls)
        reason=self.f.ledger.requests(self.task)[0]['question']['reason']
        self.assertIn('20 lượt model',reason)

    def test_crash_after_request_creation_before_checkpoint_does_not_duplicate(self):
        self.due();seq,state=self.run.state(self.task)
        with patch.object(self.run,'persist',side_effect=OSError('checkpoint crash')):
            with self.assertRaises(OSError): check(self.run,self.task,seq,state)
        self.assertEqual(len(self.f.ledger.requests(self.task)),1)
        state=Owned(self.f.ledger,self.worker).run(self.task)
        self.assertEqual(state['phase'],'waiting');self.assertEqual(len(self.f.ledger.requests(self.task)),1)

    def test_no_warning_for_native_pending_or_build(self):
        self.due();seq,state=self.run.state(self.task)
        for changes in ({'pending':'inflight'},{'phase':'waiting_operation'}):
            trial=dict(state,**changes)
            self.assertFalse(check(self.run,self.task,seq,trial)[1])
        self.assertEqual(self.f.ledger.requests(self.task),[])

    def test_notification_feed_preserves_pending_decision_after_ack(self):
        self.due();self.run.run(self.task)
        from onecrew.notifications import pull,ack
        batch=pull(self.f.ledger,'warning-test',False)
        self.assertTrue(any(m.get('status')=='waiting_input' for m in batch['notifications']))
        ack(self.f.ledger,'warning-test',batch['id'],False)
        self.assertEqual(len(self.f.ledger.requests(self.task,pending=True)),1)


if __name__=='__main__': unittest.main()
