import json
import unittest

import tests.test_ledger as fixtures
from onecrew.ledger import Ledger, LedgerError
from onecrew.notifications import pull, ack


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.LedgerTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.ledger=self.f.ledger;self.task=self.f.submit()['id']

    def event(self,kind,payload):
        with self.ledger.transaction(write=True) as c: self.ledger._event(c,self.task,kind,payload)

    def test_defer_persists_pending_revision_recommendation_and_deadline(self):
        req=self.ledger.create_request(self.task,'required',fixtures.QUESTION)
        old=self.ledger.task(self.task)
        result=self.f.cli('request','defer',req['id'],'--revision',req['revision'],'--source','codex')
        self.assertEqual(result['state'],'pending');self.assertIsNone(result['answer'])
        self.assertEqual(result['revision'],req['revision'])
        other=Ledger(self.f.project,self.f.state)
        self.assertEqual(other.task(self.task)['deadline'],old['deadline'])
        with self.assertRaises(LedgerError): other.defer(req['id'],'stale')
        reply=other.reply(req['id'],req['revision'],'thirty',source='kiro')
        self.assertEqual(reply['choice'],'thirty')
        with self.assertRaises(LedgerError): other.defer(req['id'],req['revision'])

    def test_repeated_pull_restart_and_ack_do_not_answer_or_lose_new_events(self):
        req=self.ledger.create_request(self.task,'required',fixtures.QUESTION)
        batch=pull(self.ledger,'codex')
        self.assertEqual(len(batch['notifications']),1)
        self.assertEqual(batch['notifications'][0]['skip_behavior'],'remain_pending')
        self.event('workflow.checkpoint',{'phase':'blocked','message':'Need tool'})
        self.assertEqual(pull(Ledger(self.f.project,self.f.state),'codex'),batch)
        with self.assertRaises(LedgerError): ack(self.ledger,'codex','fake')
        ack(self.ledger,'codex',batch['id']);ack(self.ledger,'codex',batch['id'])
        self.assertEqual(self.ledger.request(req['id'])['state'],'pending')
        next_batch=pull(self.ledger,'codex')
        self.assertEqual([n['status'] for n in next_batch['notifications']],['blocked'])
        self.assertEqual(pull(self.ledger,'claude')['notifications'][0]['request'],req['id'])

    def test_empty_batch_ack_does_not_pin_future_updates(self):
        for _ in range(3):
            batch=pull(self.ledger,'empty');ack(self.ledger,'empty',batch['id'])
        self.event('workflow.checkpoint',{'phase':'completed','message':'done'})
        self.assertEqual(pull(self.ledger,'empty')['notifications'][0]['status'],'completed')

    def test_no_progress_spam_and_no_duplicate_build_completion(self):
        self.event('workflow.checkpoint',{'phase':'working'})
        self.event('workflow.checkpoint',{'phase':'completed','message':'ok'})
        self.event('workflow.checkpoint',{'phase':'completed','message':'same'})
        self.event('android.job',{'request':{'key':'apk'},'status':'queued'})
        self.event('android.build',{'request':{'key':'apk'},'status':'succeeded','apk':{'path':'test.apk'}})
        self.event('android.job',{'request':{'key':'apk'},'status':'succeeded','apk':{'path':'test.apk'}})
        batch=pull(self.ledger,'events')
        self.assertEqual([n['kind'] for n in batch['notifications']],['workflow.checkpoint','android.job'])

    def test_revised_or_answered_questions_are_not_new_delivery(self):
        req=self.ledger.create_request(self.task,'required',fixtures.QUESTION)
        q=dict(fixtures.QUESTION,question='New question')
        req=self.ledger.revise_request(req['id'],req['revision'],q)
        batch=pull(self.ledger,'new')
        self.assertEqual(len(batch['notifications']),1)
        self.assertEqual(batch['notifications'][0]['question'],'New question')
        self.ledger.reply(req['id'],req['revision'],'seven')
        self.assertEqual(pull(self.ledger,'another')['notifications'],[])

    def test_from_now_is_explicit_and_cannot_reset_existing_consumer(self):
        self.event('workflow.checkpoint',{'phase':'failed'})
        batch=pull(self.ledger,'future',from_now=True)
        self.assertEqual(batch['notifications'],[])
        with self.assertRaises(LedgerError): pull(self.ledger,'future',from_now=True)
        ack(self.ledger,'future',batch['id'])
        self.event('workflow.checkpoint',{'phase':'completed'})
        self.assertEqual(pull(self.ledger,'future')['notifications'][0]['status'],'completed')

    def test_bounded_pages_retain_tail_and_scope_isolation(self):
        with self.ledger.transaction(write=True) as c:
            for _ in range(505): self.ledger._event(c,self.task,'test.progress',{})
        self.event('workflow.checkpoint',{'phase':'completed'})
        first=pull(self.ledger,'pages');self.assertTrue(first['has_more'])
        ack(self.ledger,'pages',first['id'])
        self.assertEqual(pull(self.ledger,'pages')['notifications'][0]['status'],'completed')
        other=self.f.base/'other';other.mkdir();other_ledger=Ledger(other,self.f.state)
        self.assertEqual(pull(other_ledger,'pages')['notifications'],[])
        self.assertEqual(pull(other_ledger,'global',all_projects=True)['has_more'],True)
        with self.assertRaises(LedgerError): ack(other_ledger,'pages',first['id'])


if __name__=='__main__': unittest.main()
