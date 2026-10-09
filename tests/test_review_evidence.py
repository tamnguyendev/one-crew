import json
import unittest
from tests import test_owned as fixtures
from onecrew.review_evidence import ReviewRejected, packet, requests
from onecrew.progress import classify, observe
from onecrew.owned import Owned
from onecrew.ledger import LedgerError, canonical


class ReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_feedback_keywords_are_review_not_infrastructure_and_repair_continues(self):
        run,task,worker=self.f.runtime([])
        worker.responses=[fixtures.action('read',path='calc.py'),fixtures.action('finish',report='Incorrect unverified claim about production code.'),
            {'accepted':False,'feedback':'Check HTTP 429, OAuth authentication, quota, SDK unavailable and timeout in source.'},
            fixtures.action('finish',report='calc.py subtracts; tests were not run. This is a source audit only.'),
            {'accepted':True,'feedback':'Verified.'}]
        state=run.run(task)
        self.assertEqual(state['phase'],'completed');self.assertEqual(run.control.status(task)['used_calls'],5)
        failure=json.loads(run.store.read_blob(state['receipts'][1]['blob']))['result']
        self.assertEqual(failure['failure_kind'],'review')
        self.assertEqual(classify(ReviewRejected('429 OAuth SDK unavailable')),'review')

    def test_full_read_after_1000_chars_and_pagination_are_not_hidden(self):
        (self.f.root/'long.py').write_text('# pad\n'*210+'EVIDENCE_AFTER_1000=True\n')
        run,task,worker=self.f.runtime([fixtures.action('read',path='long.py')])
        state=run.run(task,steps=1);bundle=packet(run,state)
        record=bundle['full_receipts'][0]['record']['result']
        self.assertIn('EVIDENCE_AFTER_1000',record['text'])
        self.assertEqual(record['start_line'],1);self.assertIsNone(record['next_cursor'])
        self.assertEqual(run.evidence_index(state)[0]['path'],'long.py')

    def test_bounded_retrieval_resumes_without_reexecuting_finish(self):
        run,task,worker=self.f.runtime([])
        worker.responses=[fixtures.action('read',path='calc.py'),fixtures.action('finish',report='calc.py subtracts in the add function. No tests run.'),
            {'accepted':False,'feedback':'Need receipt 0','evidence_requests':[0]},
            {'accepted':True,'feedback':'Source confirmed.','evidence_requests':[]}]
        state=run.run(task,steps=2)
        self.assertEqual(state['response']['action'],'finish');self.assertEqual(state['review_requests'],[0])
        state=Owned(self.f.ledger,worker).run(task)
        self.assertEqual(state['phase'],'completed')
        self.assertEqual(worker.calls,['owned','owned','owned_review','owned_review'])
        self.assertEqual([r['action'] for r in state['receipts']],['read','finish'])

    def test_packet_budget_prioritizes_requested_receipt_and_invalid_ids_fail_closed(self):
        run,task,worker=self.f.runtime([]);seq,state=run.state(task)
        for i in range(7):
            blob=run.store.blob(canonical({'action':'read','result':{'path':str(i),'text':str(i)*10000}}).encode())
            state['receipts'].append({'index':i,'action':'read','blob':blob})
        state['review_requests']=[0]
        bundle=packet(run,state)
        self.assertEqual(bundle['full_receipts'][0]['index'],0)
        self.assertLessEqual(sum(len(canonical(x['record'])) for x in bundle['full_receipts']),45000)
        self.assertEqual(len(bundle['manifest']),7)
        for wanted in ([999],[True],list(range(5))):
            with self.assertRaises(LedgerError): requests({'accepted':False,'evidence_requests':wanted},state)
        with self.assertRaises(LedgerError): requests({'accepted':True,'evidence_requests':[0]},state)

    def test_new_review_limit_preserves_legacy_failures_but_is_still_bounded(self):
        state={'phase':'running','snapshot':None}
        result={'error':'Final evidence review: legacy'}
        observe(state,'finish',{},result);observe(state,'finish',{},dict(result,error='Final evidence review: legacy two'))
        for i in range(2): observe(state,'finish',{}, {'error':'Final evidence review: new '+str(i),'review_protocol':2})
        self.assertEqual(state['phase'],'running');self.assertEqual(state['progress']['review_rejections'],4)
        observe(state,'finish',{}, {'error':'Final evidence review: new three','review_protocol':2})
        self.assertEqual(state['phase'],'blocked')

    def test_adopt_warning_on_explicit_legacy_resume_keeps_usage(self):
        run,task,worker=self.f.runtime([fixtures.action('read',path='calc.py')])
        run.run(task,steps=1);seq,state=run.state(task)
        state.pop('effort_watch',None);state['phase']='blocked';run.persist(task,seq,state)
        before=run.control.status(task)
        state=run.resume(task)
        self.assertEqual(state['effort_watch']['calls'],1)
        self.assertEqual(run.control.status(task)['used_calls'],before['used_calls'])

    def test_git_status_reports_branch_dirty_and_detached_without_index_writes(self):
        from onecrew.owned_git import GitDelivery
        self.f.setup_git()
        run,task,_=self.f.runtime([])
        adapter=GitDelivery(run,task,{},'')
        before=(self.f.root/'.git/index').read_bytes()
        result=adapter.status()
        self.assertEqual(result['branch'],self.f.git('branch','--show-current').decode().strip())
        self.assertTrue(result['dirty']);self.assertFalse(result['detached'])
        self.assertEqual((self.f.root/'.git/index').read_bytes(),before)
        self.f.git('checkout','--detach')
        result=adapter.status()
        self.assertIsNone(result['branch']);self.assertTrue(result['detached'])


if __name__=='__main__': unittest.main()
