import json
from unittest.mock import patch
from tests.test_conversations import ConversationTests,solution
from onecrew import conversations as c,consultations as q,discussion
from onecrew.ledger import LedgerError
from onecrew.mcp_entry import Server


class ReviewWorker:
    def __init__(self,control):self.control=control;self.calls=0
    def capability(self):return {'fixture':True}
    def run(self,a,prompt,schema,profile):
        self.calls+=1
        self.control.launched(a['id'],1,{'fixture':True})
        self.control.finish(a['id'],1,{'output':{k:'Fixture '+k for k in q.SCHEMA['required']}})
    def result(self,a):return json.loads(a['result'])['output'],[{'test_only':True}]


class DiscussionTests(ConversationTests):
    def setup_consult(self,key='review'):
        cid=c.create(self.ledger,'Review solution','conv','codex')['id']
        sol=c.propose(self.ledger,cid,'draft',solution(),'codex')
        args=dict(conversation=cid,key=key,solution=sol['id'],revision=sol['revision'],question='Review risks',entry='codex',reference='User asks Claude review',provider='claude')
        return args,q.submit(self.ledger,**args)

    def test_default_no_call_and_pin_is_independent_of_execution(self):
        with patch('onecrew.model_advisor.advise') as ai:
            self.assertFalse(discussion.route('codex')['dispatch'])
            route=discussion.route('kiro','consult','claude','haiku','user request',jev=True)
            self.assertEqual(route['model'],'haiku');ai.assert_not_called()
        with self.assertRaises(LedgerError):discussion.route('codex','local','claude')
        with self.assertRaises(LedgerError):discussion.route('codex','auto',reference='user')
        with self.assertRaises(LedgerError):discussion.route('codex',jev='false')

    def test_consultation_is_not_task_and_replay_is_exact(self):
        args,receipt=self.setup_consult()
        self.assertEqual(q.submit(self.ledger,**args)['id'],receipt['id'])
        with self.ledger.transaction() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        with self.assertRaises(LedgerError):q.submit(self.ledger,**dict(args,question='different'))

    def test_crash_after_receipt_reuses_result_and_stale_flag_tracks_solution(self):
        args,receipt=self.setup_consult();cid=receipt['id'];worker=ReviewWorker(q.ConsultationControl(self.ledger,cid))
        with patch.object(worker,'result',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):q.run(self.ledger,cid,worker)
        self.assertEqual(worker.calls,1)
        self.assertEqual(q.run(self.ledger,cid,worker)['status'],'completed')
        q.run(self.ledger,cid,worker);self.assertEqual(worker.calls,1)
        c.propose(self.ledger,args['conversation'],'revised',dict(solution(),detail='new'),'kiro',args['solution'])
        self.assertTrue(q.view(self.ledger,cid)['stale'])
        events=c.read(self.ledger,args['conversation'])['events']
        self.assertEqual(len([e for e in events if e['kind']=='consultation.output']),1)
        q.feedback(self.ledger,cid,'actual user review',True,0,0,'fixture checked')

    def test_cancel_before_launch_and_failed_provider_do_not_fallback(self):
        args,receipt=self.setup_consult();cid=receipt['id']
        worker=ReviewWorker(q.ConsultationControl(self.ledger,cid))
        q.cancel(self.ledger,cid);self.assertEqual(q.run(self.ledger,cid,worker)['status'],'cancelled');self.assertEqual(worker.calls,0)
        other=q.submit(self.ledger,**dict(args,key='other'));worker=ReviewWorker(q.ConsultationControl(self.ledger,other['id']))
        with patch.object(worker,'capability',side_effect=LedgerError('no auth')):result=q.run(self.ledger,other['id'],worker)
        self.assertEqual(result['status'],'failed');self.assertEqual(worker.calls,0)

    def test_shared_mcp_discussion_has_no_decision_authority_by_default(self):
        codex=Server(self.ledger,source='codex',allow_discussion=True)
        claude=Server(self.ledger,source='claude',allow_discussion=True)
        conv=codex.call('conversation_create',{'title':'Shared','key':'mcp'})
        message=claude.call('conversation_append',{'conversation':conv['id'],'key':'review','text':'Review from another host'})
        read=codex.call('conversation_read',{'conversation':conv['id']})
        self.assertIn(message['id'],[e['id'] for e in read['events']])
        self.assertNotIn('solution_decide',{t['name'] for t in claude.tools()})
        with self.assertRaises(LedgerError):claude.call('solution_decide',{})

    def test_conversation_notices_share_ack_without_approving(self):
        from onecrew.notifications import pull,ack
        from onecrew.solution_gate import question
        args,result=self.setup_consult()
        initial=pull(self.ledger,'entry',from_now=True);ack(self.ledger,'entry',initial['id'])
        req=question(self.ledger,args['conversation'],'need-input','Which behavior?','Open requirement',[],'codex')
        batch=pull(self.ledger,'entry')
        self.assertEqual(batch['notifications'][0]['request'],req['id'])
        self.assertEqual(pull(self.ledger,'entry')['id'],batch['id'])
        ack(self.ledger,'entry',batch['id'])
        self.assertEqual(pull(self.ledger,'entry')['notifications'],[])
        self.assertEqual(c.read(self.ledger,args['conversation'])['pending_questions'][0]['state'],'pending')

    def test_dead_prelaunch_owner_settles_without_duplicate_inference(self):
        _,receipt=self.setup_consult();cid=receipt['id'];control=q.ConsultationControl(self.ledger,cid)
        attempt=control.reserve()
        with patch('onecrew.supervisor.probe',return_value='dead'):
            self.assertEqual(q.reconcile(self.ledger,cid)['status'],'settled')
        self.assertEqual(control.attempt(attempt['id'])['charged'],0)
        self.assertEqual(control.attempt(attempt['id'])['status'],'settled')

    def test_oversized_review_fails_before_reserving_global_capacity(self):
        args,receipt=self.setup_consult()
        sol=c.propose(self.ledger,args['conversation'],'large',dict(solution(),detail='x'*15000),'codex',args['solution'])
        result=q.submit(self.ledger,**dict(args,key='large',solution=sol['id'],revision=sol['revision']))
        worker=ReviewWorker(q.ConsultationControl(self.ledger,result['id']))
        result=q.run(self.ledger,result['id'],worker)
        self.assertEqual(result['status'],'failed');self.assertIsNone(result['attempt']);self.assertEqual(worker.calls,0)

    def test_atomic_shared_capacity_and_no_jev_replay_after_uncertain_result(self):
        from concurrent.futures import ThreadPoolExecutor
        from onecrew.control import CapacityWait
        args,first=self.setup_consult()
        ids=[first['id']]+[q.submit(self.ledger,**dict(args,key='parallel-'+str(i)))['id'] for i in range(2)]
        def reserve(cid):
            try:return q.ConsultationControl(self.ledger,cid).reserve()
            except CapacityWait:return None
        with ThreadPoolExecutor(max_workers=3) as pool:receipts=list(pool.map(reserve,ids))
        self.assertEqual(sum(r is not None for r in receipts),2)
        for cid,r in zip(ids,receipts):
            if r:q.ConsultationControl(self.ledger,cid).finish(r['id'],1,{'reason':'fixture release'},not_started=True)
        import datetime as dt
        now=dt.datetime.now(dt.timezone.utc)
        quota={'observed_at':now.isoformat(),'expires_at':(now+dt.timedelta(minutes=3)).isoformat(),'source':'fixture',
            'windows':[{'name':'test','remaining':100,'reserved':0,'keep_for_chat':0,'estimated_call':1,'resets_at':(now+dt.timedelta(hours=1)).isoformat()}]}
        policy={'workload':{'complexity':1,'risk':'low','allowed_providers':['claude']},
            'candidates':[{'id':str(i),'provider':'claude','model':'fixture-'+str(i),'tier':1,'cost_rank':i,
                'capability_verified':True,'auth_mode':'subscription','quota':quota} for i in range(2)]}
        auto=q.submit(self.ledger,**dict(args,key='auto',provider=None,intent='auto',jev=True,brief='Review pure arithmetic',policy=policy))
        worker=ReviewWorker(q.ConsultationControl(self.ledger,auto['id']))
        with patch('onecrew.model_advisor.advise',side_effect=KeyboardInterrupt) as evaluator:
            with self.assertRaises(KeyboardInterrupt):q.run(self.ledger,auto['id'],worker)
            self.assertEqual(evaluator.call_count,1)
        with patch('onecrew.model_advisor.advise') as evaluator:
            result=q.run(self.ledger,auto['id'],worker);evaluator.assert_not_called()
        self.assertEqual(result['status'],'completed');self.assertEqual(worker.calls,1)
        self.assertEqual(result['evaluator']['status'],'started_outcome_unknown')
