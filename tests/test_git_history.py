import json
import unittest
from unittest.mock import patch
import tests.test_owned as fixtures
from tests.test_owned import action
from onecrew.git_history import History
from onecrew.ledger import LedgerError
from onecrew.owned_intake import submit


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.setup_git()
        self.base=self.f.git('rev-parse','HEAD').decode().strip()
        (self.f.root/'screen.dart').write_text('class Screen { final color = "blue"; }\n')
        self.f.git('add','screen.dart');self.f.git('commit','-m','Update UI palette')
        self.change=self.f.git('rev-parse','HEAD').decode().strip()
        self.run,self.task,self.worker=self.f.runtime([],mode='branch',branch='onecrew/pre-ui')
        self.profile=self.run.control.status(self.task)['configuration']['profile']
        self.history=History(self.run,self.task,self.profile,'')

    def test_history_actual_diff_filter_and_path_guards(self):
        rows=self.history.log(self.change,query='UI')
        self.assertEqual(rows['commits'][0]['commit'],self.change)
        self.assertEqual(self.history.show(self.change,self.change)['parents'],[self.base])
        self.assertIn('+class Screen',self.history.show(self.change,self.change,'screen.dart')['diff'])
        with self.assertRaises(LedgerError): self.history.show(self.change,self.change,'../outside')
        with self.assertRaises(LedgerError): self.history.show(self.change,'HEAD')

    def test_authority_local_only(self):
        with self.assertRaises(LedgerError): submit(self.f.ledger,'Branch','bad',mode='branch',branch='onecrew/test',remote='origin')
        with self.assertRaises(LedgerError): History(self.run,self.task,dict(self.profile,mode='audit'),'').branch_before(self.change,self.change,'deny')

    def test_create_parent_ref_preserve_checkout_index_and_dirty_bytes(self):
        before=(self.f.root/'.git/index').read_bytes();source=(self.f.root/'calc.py').read_bytes()
        receipt=self.history.branch_before(self.change,self.change,'branch')
        self.assertEqual(receipt['status'],'verified');self.assertEqual(receipt['result']['commit'],self.base)
        self.assertEqual(self.f.git('rev-parse','HEAD').decode().strip(),self.change)
        self.assertEqual((self.f.root/'.git/index').read_bytes(),before)
        self.assertEqual((self.f.root/'calc.py').read_bytes(),source)
        with self.assertRaises(LedgerError): self.history.branch_before(self.change,self.change,'different')

    def test_lost_ack_only_observes(self):
        self.history.branch_before(self.change,self.change,'branch')
        with self.f.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE actions SET status='unknown',receipt=NULL WHERE task_id=?",(self.task,))
        with patch.object(self.history,'git',wraps=self.history.git) as calls:
            receipt=self.history.branch_before(self.change,self.change,'branch')
        self.assertTrue(receipt['reconciled'])
        self.assertFalse(any('update-ref' in c.args for c in calls.call_args_list))

    def test_worker_owns_inspection_branch_and_report(self):
        self.worker.responses=[action('git_log'),action('git_show',commit=self.change,path='screen.dart'),
            action('branch_before',first_change=self.change),{'accepted':True,'feedback':'Boundary backed by diff.'},
            action('finish',report='Created local branch before the UI palette change; original checkout retained.'),
            {'accepted':True,'feedback':'Receipt verified.'}]
        with patch.object(self.worker,'run',wraps=self.worker.run) as invoke:
            state=self.run.run(self.task)
        review_calls=[c for c in invoke.call_args_list if 'review_phase' in c.args[1]]
        before=json.loads(review_calls[0].args[1].split('\n',1)[1].split('\nAPPROVED SOLUTION CONTRACT')[0])
        after=json.loads(review_calls[1].args[1].split('\n',1)[1].split('\nAPPROVED SOLUTION CONTRACT')[0])
        self.assertEqual(before['review_phase'],'pre_execution');self.assertEqual(before['branch_receipts'],[])
        self.assertEqual(after['review_phase'],'completion');self.assertEqual(len(after['branch_receipts']),1)
        self.assertEqual(state['phase'],'completed',state['message'])
        self.assertEqual(state['branches'][0]['result']['commit'],self.base)
        self.assertEqual(len(self.worker.calls),6)

    def test_history_index_survives_recent_window_and_normalizes_empty_path(self):
        state=self.run.state(self.task)[1]
        result=self.run._tool(self.task,state,'git_show',{'commit':self.change,'path':''},self.profile)
        self.assertEqual(result['commit'],self.change)
        blob=self.run.store.blob(json.dumps({'action':'git_show','result':result}).encode())
        state['receipts']=[{'index':0,'action':'git_show','blob':blob}]+[
            {'index':i,'action':'list','blob':self.run.store.blob(b'{"action":"list","result":{}}')} for i in range(1,8)]
        self.assertEqual(self.run.evidence_index(state)[0]['commit'],self.change)
        seq,_=self.run.state(self.task)
        state.update(phase='blocked',context_prompt='stale',review_prompt='stale')
        self.run.persist(self.task,seq,state)
        resumed=self.run.resume(self.task)
        self.assertIsNone(resumed['context_prompt']);self.assertIsNone(resumed['review_prompt'])


if __name__=='__main__': unittest.main()
