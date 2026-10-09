import unittest
from unittest.mock import patch
from tests import test_owned as fixtures
from onecrew.notifications import ack
from onecrew.notification_watch import watch,lifecycle
from onecrew.ledger import LedgerError


class NotificationWatchTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.run,self.task,self.worker=self.f.runtime([])
        self.consumer='chat-watch';self.tasks=[self.task]
        self.probe=patch('onecrew.notification_watch.runner_status',return_value={'status':'alive'})
        self.probe.start();self.addCleanup(self.probe.stop)

    def event(self,phase):
        seq,state=self.run.state(self.task);state.update(phase=phase,message='fixture '+phase)
        self.run.persist(self.task,seq,state)

    def tick(self):return watch(self.f.ledger,self.consumer,self.tasks)

    def acknowledge(self,batch):
        if batch['notifications']:
            from onecrew.notification_receipts import begin,confirm
            from tests.test_notification_receipts import host_evidence
            delivery=begin(self.f.ledger,self.consumer,batch['id'],'thread-fixture','automation-fixture','Fixture notification')
            confirm(self.f.ledger,self.consumer,batch['id'],host_evidence(delivery))
        return ack(self.f.ledger,self.consumer,batch['id'],all_projects=True)

    def test_running_to_done_notifies_once_then_host_can_pause(self):
        first=self.tick();self.assertTrue(first['active']);self.assertEqual(first['notifications'],[])
        self.acknowledge(first)
        self.assertFalse(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])
        self.event('completed');batch=self.tick()
        self.assertEqual([n['status'] for n in batch['notifications']],['completed'])
        self.assertFalse(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])
        self.acknowledge(batch)
        self.assertTrue(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])
        again=self.tick();self.assertEqual(again['notifications'],[])
        self.assertEqual(self.worker.calls,[])

    def test_completion_between_read_and_ack_remains_unread(self):
        first=self.tick();self.event('completed');self.acknowledge(first)
        current=lifecycle(self.f.ledger,self.consumer,self.tasks)
        self.assertTrue(current['unread']);self.assertFalse(current['should_pause'])
        self.assertEqual(self.tick()['notifications'][0]['status'],'completed')

    def test_question_ack_does_not_answer_and_host_pauses_until_explicit_resume(self):
        import tests.test_ledger as lf
        req=self.f.ledger.create_request(self.task,'question',lf.QUESTION)
        batch=self.tick();self.assertFalse(batch['active'])
        self.assertEqual(batch['notifications'][0]['request'],req['id'])
        self.acknowledge(batch)
        self.assertTrue(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])
        self.assertEqual(self.f.ledger.request(req['id'])['state'],'pending')

    def test_unrelated_tasks_are_filtered_and_one_active_task_keeps_watch_on(self):
        from onecrew.owned_intake import submit
        other=submit(self.f.ledger,'Other task','other')['id'];self.run.enable(other)
        seq,state=self.run.state(other);state['phase']='completed';self.run.persist(other,seq,state)
        batch=self.tick();self.assertFalse(any(n.get('task')==other for n in batch['notifications']))
        self.acknowledge(batch)
        self.tasks.append(other);self.assertTrue(self.tick()['active'])

    def test_blocked_dead_and_unknown_runner_alert_once_without_relaunch(self):
        for status in ('stopped','unknown'):
            self.consumer='chat-'+status
            with patch('onecrew.notification_watch.runner_status',return_value={'status':status}):
                batch=self.tick();self.assertEqual(len(batch['notifications']),1)
                self.acknowledge(batch)
                self.assertTrue(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])
                self.assertEqual(self.tick()['notifications'],[])
        self.consumer='blocked';self.event('blocked')
        batch=self.tick();self.assertEqual(batch['notifications'][0]['status'],'blocked')
        self.acknowledge(batch);self.assertTrue(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])
        self.assertEqual(self.worker.calls,[])

    def test_stale_failures_filtered_and_watch_scope_cannot_change_before_ack(self):
        self.event('blocked');self.event('completed')
        batch=self.tick();self.assertEqual([n['status'] for n in batch['notifications']],['completed'])
        self.assertEqual(self.tick()['id'],batch['id'])
        with self.assertRaises(LedgerError):watch(self.f.ledger,self.consumer,[])
        with self.assertRaises(LedgerError):watch(self.f.ledger,self.consumer,['TASK-unknown'])

    def test_paused_execution_does_not_keep_host_running(self):
        self.run.control.pause(self.task)
        batch=self.tick();self.assertFalse(batch['active'])
        self.acknowledge(batch)
        self.assertTrue(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])

    def test_autonomous_build_keeps_watch_alive_after_parent_completed(self):
        self.event('completed')
        with self.f.ledger.transaction(write=True) as conn:
            self.f.ledger._event(conn,self.task,'android.job',{'request':{'key':'apk'},'status':'running','identity':{'fixture':True}})
        with patch('onecrew.notification_watch.probe',return_value='alive'),patch('onecrew.notifications.reconcile_builds'):
            batch=self.tick();self.assertTrue(batch['active'])
            self.acknowledge(batch)
            self.assertFalse(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])

    def test_conversation_event_arriving_during_ack_keeps_one_more_tick(self):
        from onecrew.conversations import create
        from onecrew.solution_gate import question
        cid=create(self.f.ledger,'Discussion','c','codex')['id']
        self.event('completed');batch=self.tick()
        question(self.f.ledger,cid,'q','Which behavior?','Requirement',[],'codex')
        self.acknowledge(batch)
        self.assertFalse(lifecycle(self.f.ledger,self.consumer,self.tasks)['should_pause'])


if __name__=='__main__':unittest.main()
