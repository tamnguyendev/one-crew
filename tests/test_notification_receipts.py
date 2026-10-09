import copy
import datetime as dt
import unittest
from unittest.mock import patch
from tests import test_owned as fixtures
from onecrew.ledger import LedgerError
from onecrew.notifications import ack,read_state,location
from onecrew.notification_watch import watch,lifecycle
from onecrew.notification_receipts import begin,confirm,missing,redeliver


def host_evidence(delivery):
    return {'schemaVersion':1,'thread':{'id':delivery['thread']},'turns':[{
        'id':'turn-fixture','status':'completed','startedAt':0,
        'completedAt':dt.datetime.now(dt.timezone.utc).timestamp()+1,'items':[
            {'type':'userMessage','content':[{'type':'text','text':'<heartbeat>\n<automation_id>'+delivery['automation']+'</automation_id>\n</heartbeat>'}]},
            {'id':'message-fixture','type':'agentMessage','phase':'final_answer','text':delivery['message']}]}]}


class NotificationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.run,self.task,self.worker=self.f.runtime([]);self.consumer='receipt-test'
        seq,state=self.run.state(self.task);state.update(phase='blocked',message='Fixture issue')
        self.run.persist(self.task,seq,state)
        self.batch=watch(self.f.ledger,self.consumer,[self.task]);self.bid=self.batch['id']

    def prepare(self):return begin(self.f.ledger,self.consumer,self.bid,'thread-fixture','automation-fixture','Task is blocked; tests not run.')

    def test_read_or_prepared_message_cannot_ack_or_pause(self):
        for prepared in (False,True):
            if prepared:self.prepare()
            with self.assertRaises(LedgerError):ack(self.f.ledger,self.consumer,self.bid,True)
            self.assertFalse(lifecycle(self.f.ledger,self.consumer,[self.task])['should_pause'])
            self.assertEqual(watch(self.f.ledger,self.consumer,[self.task])['id'],self.bid)

    def test_only_completed_automatic_final_in_bound_thread_is_delivery(self):
        delivery=self.prepare()
        for case in ('manual','commentary','wrong_thread','wrong_automation','in_progress','truncated','tool_output','old','duplicate'):
            with self.subTest(case=case):
                evidence=host_evidence(delivery);turn=evidence['turns'][0];message=turn['items'][1]
                if case=='manual':turn['items'][0]['content'][0]['text']='Please inspect status'
                elif case=='commentary':message['phase']='commentary'
                elif case=='wrong_thread':evidence['thread']['id']='other'
                elif case=='wrong_automation':turn['items'][0]['content'][0]['text']='<heartbeat><automation_id>other</automation_id></heartbeat>'
                elif case=='in_progress':turn['status']='inProgress'
                elif case=='truncated':message['text']=message['text'][:12]
                elif case=='tool_output':message['type']='commandExecution'
                elif case=='old':turn['completedAt']=1
                else:evidence['turns'].append(copy.deepcopy(turn))
                with self.assertRaises(LedgerError):confirm(self.f.ledger,self.consumer,self.bid,evidence)
        result=confirm(self.f.ledger,self.consumer,self.bid,host_evidence(delivery))
        self.assertEqual(result['receipt']['message'],'message-fixture')
        ack(self.f.ledger,self.consumer,self.bid,True)
        self.assertTrue(lifecycle(self.f.ledger,self.consumer,[self.task])['should_pause'])
        saved=read_state(location(self.f.ledger,self.consumer,True))
        self.assertEqual(saved['last_delivery']['status'],'host_message_observed')
        self.assertEqual(self.worker.calls,[])

    def test_crash_recovery_keeps_same_message_and_bound_destination(self):
        delivery=self.prepare();self.assertEqual(self.prepare(),delivery)
        with self.assertRaises(LedgerError):begin(self.f.ledger,self.consumer,self.bid,'other','automation-fixture','different')
        seen=confirm(self.f.ledger,self.consumer,self.bid,host_evidence(delivery))
        self.assertEqual(confirm(self.f.ledger,self.consumer,self.bid,host_evidence(delivery))['receipt'],seen['receipt'])
        ack(self.f.ledger,self.consumer,self.bid,True)
        self.assertEqual(ack(self.f.ledger,self.consumer,self.bid,True)['acked'],self.bid)

    def test_missing_receipt_stops_repeated_checks_without_claiming_delivery(self):
        self.prepare()
        self.assertFalse(missing(self.f.ledger,self.consumer,self.bid)['pause_due_error'])
        self.assertFalse(missing(self.f.ledger,self.consumer,self.bid)['pause_due_error'])
        self.assertTrue(missing(self.f.ledger,self.consumer,self.bid)['pause_due_error'])
        with self.assertRaises(LedgerError):ack(self.f.ledger,self.consumer,self.bid,True)

    def test_explicit_redelivery_keeps_cursor_and_history(self):
        delivery=self.prepare();confirm(self.f.ledger,self.consumer,self.bid,host_evidence(delivery))
        ack(self.f.ledger,self.consumer,self.bid,True)
        before=read_state(location(self.f.ledger,self.consumer,True))
        receipt=redeliver(self.f.ledger,self.consumer,self.task,'User requests the missed automatic notification')
        self.assertEqual(receipt['cursor_unchanged'],before['cursor'])
        after=watch(self.f.ledger,self.consumer,[self.task])
        self.assertEqual(len(after['notifications']),1);self.assertNotEqual(after['id'],self.bid)
        with self.assertRaises(LedgerError):ack(self.f.ledger,self.consumer,after['id'],True)
        with self.assertRaises(LedgerError):redeliver(self.f.ledger,self.consumer,self.task,'do not discard pending')

    def test_raw_pull_cannot_bypass_a_registered_watch_receipt(self):
        from onecrew.notifications import pull
        delivery=self.prepare();confirm(self.f.ledger,self.consumer,self.bid,host_evidence(delivery))
        ack(self.f.ledger,self.consumer,self.bid,True)
        seq,state=self.run.state(self.task);state['phase']='completed';self.run.persist(self.task,seq,state)
        raw=pull(self.f.ledger,self.consumer,True)
        self.assertNotIn('watch_tasks',raw)
        with self.assertRaises(LedgerError):ack(self.f.ledger,self.consumer,raw['id'],True)


if __name__=='__main__':unittest.main()
