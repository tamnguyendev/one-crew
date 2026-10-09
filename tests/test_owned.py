import json
import subprocess
import tempfile
from pathlib import Path
import unittest
import time
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from onecrew.owned_git import GitDelivery
from onecrew.snapshots import bytes_hash
from tests.test_workflow import FixtureWorker


def action(name,**args):
    return {'plan':'Inspect, execute within scope, verify, report.','action':name,'arguments':json.dumps(args)}


class OwnedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        self.ledger=Ledger(self.root,Path(self.temp.name)/'state')
        (self.root/'calc.py').write_text('def add(a,b): return a-b\n')
        (self.root/'test_calc.py').write_text('import unittest\nfrom calc import add\nclass Tests(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n')

    def runtime(self,responses,**kwargs):
        if kwargs.get('mode','audit')!='audit' and not kwargs.get('solution_id'):
            from tests.test_solution_gate import approve_fixture
            kwargs.update(approve_fixture(self.ledger))
        task=submit(self.ledger,'Inspect/fix scoped fixture','job',**kwargs)
        expanded=[]
        for response in responses:
            expanded.append(response)
            if response['action']=='finish': expanded.append({'accepted':True,'feedback':'Evidence consistent.'})
        worker=FixtureWorker(self.ledger,expanded)
        runtime=Owned(self.ledger,worker);runtime.enable(task['id'])
        return runtime,task['id'],worker

    def test_audit_discovers_no_prepared_files_and_entry_handoff(self):
        run,task,worker=self.runtime([action('list'),action('read',path='calc.py'),
            action('finish',report='calc.py implements subtraction instead of addition; source was inspected.')])
        state=run.run(task)
        self.assertEqual(state['phase'],'completed');self.assertEqual(len(worker.calls),4)
        self.assertEqual(run.control.status(task)['used_calls'],4)
        from onecrew.entry import connect
        self.assertEqual(connect(self.ledger,task)['phase'],'completed')

    def test_resume_response_without_duplicate_call(self):
        run,task,worker=self.runtime([])
        seq,state=run.state(task);state['response']=action('read',path='calc.py');run.persist(task,seq,state)
        restored=Owned(Ledger(self.root,self.ledger.state_root),worker)
        state=restored.run(task,steps=1)
        self.assertEqual(worker.calls,[]);self.assertIn('calc.py',state['files'])

    def test_question_restart_and_reply_without_authority_upgrade(self):
        run,task,worker=self.runtime([action('ask',question='Which part?',reason='Need focus',
            options=[{'id':'a','label':'Calculation'},{'id':'b','label':'Docs'}],recommendation='a'),
            action('write',path='evil.py',expected_hash=None,text='pass'),action('read',path='calc.py')])
        self.assertEqual(run.run(task)['phase'],'waiting')
        request=self.ledger.requests(task)[0]
        restored=Owned(Ledger(self.root,self.ledger.state_root),worker)
        restored.run(task);self.assertEqual(len(worker.calls),1)
        self.ledger.reply(request['id'],request['revision'],'a')
        state=restored.run(task,steps=2)
        result=json.loads(run.store.read_blob(state['receipts'][1]['blob']))
        self.assertIn('not authorized',result['result']['error'])
        self.assertFalse((self.root/'evil.py').exists())

    def test_candidate_failure_repair_pass_and_stale_receipt(self):
        old=(self.root/'calc.py').read_bytes();h=bytes_hash(old)
        run,task,worker=self.runtime([action('read',path='calc.py'),action('read',path='test_calc.py'),
            action('test',path='test_calc.py'),action('write',path='calc.py',expected_hash=h,text='def add(a,b): return a+b\n'),
            action('finish',report='I claim all tests pass but have not run them on this candidate.'),
            action('test',path='test_calc.py'),action('finish',report='Fixed addition and original unittest passes on the current candidate.')],
            mode='change',image='sha256:'+'a'*64)
        def gate(snapshot,check,guard=None):
            text=run.store.context(snapshot)['calc.py']
            passed='a+b' in text
            return {'passed':passed,'evidence':{'snapshot':snapshot,'exit_code':0 if passed else 1,
                    'stdout':'','stderr':'Ran 1 test in 0.001s'}}
        with patch('onecrew.sandbox_gate.ContainerGate.evaluate',side_effect=gate): state=run.run(task)
        self.assertEqual(state['phase'],'completed');self.assertEqual([x['passed'] for x in state['tests']],[False,True])
        self.assertEqual((self.root/'calc.py').read_bytes(),old)
        rejected=json.loads(run.store.read_blob(state['receipts'][4]['blob']))
        self.assertIn('no passing',rejected['result']['error'])

    def test_cancel_prevents_model_dispatch(self):
        run,task,worker=self.runtime([])
        run.control.cancel(task);run.run(task)
        self.assertEqual(worker.calls,[])

    def test_budget_exhaustion_is_blocked_not_complete(self):
        run,task,worker=self.runtime([action('list')],max_calls=1)
        self.assertEqual(run.run(task)['phase'],'blocked')
        self.assertEqual(len(worker.calls),1)

    def test_final_review_rejects_claim_then_worker_corrects_report(self):
        run,task,worker=self.runtime([])
        worker.responses=[action('read',path='calc.py'),action('finish',report='All behavior is correct and tests passed.'),
            {'accepted':False,'feedback':'Source subtracts; no tests were run.'},
            action('finish',report='Source subtracts in add; tests have not been run. Correctness issue remains.'),
            {'accepted':True,'feedback':'Accurate evidence and limitation.'}]
        state=run.run(task)
        self.assertEqual(state['phase'],'completed')
        self.assertEqual([r['accepted'] for r in state['reviews']],[False,True])
        self.assertEqual(run.control.status(task)['used_calls'],5)

    def test_repetition_stops_without_spending_remaining_budget(self):
        run,task,worker=self.runtime([action('list')]*3,max_calls=20)
        state=run.run(task)
        self.assertEqual(state['phase'],'blocked');self.assertIn('without progress',state['message'])
        self.assertEqual(len(worker.calls),3)

    def test_failed_tool_does_not_publish_partial_candidate_state(self):
        run,task,worker=self.runtime([action('read',path='calc.py'),action('write',path='calc.py',
            expected_hash=bytes_hash((self.root/'calc.py').read_bytes()),text='def add(a,b): return a+b\n')],
            mode='change',image='sha256:'+'a'*64)
        before=run.run(task,steps=1)
        with patch.object(run,'_snapshot',side_effect=LedgerError('storage failure')):
            after=run.run(task,steps=1)
        self.assertEqual(after['snapshot'],before['snapshot']);self.assertEqual(after['files'],before['files'])

    def test_settled_provider_failure_has_one_bounded_retry(self):
        run,task,worker=self.runtime([])
        worker.responses=[{},action('read',path='calc.py')]
        state=run.run(task,steps=2)
        self.assertEqual(state['phase'],'running');self.assertEqual(state['provider_failures'],1)
        self.assertEqual(len(worker.calls),2)
        self.assertIn('calc.py',state['files'])

    def test_native_owned_runner_survives_launcher_and_cancel(self):
        from onecrew.runner import start,status
        from onecrew.supervisor import probe
        run,task,worker=self.runtime([])
        run.control.pause(task)
        record=start(self.ledger,task)
        try:
            self.assertEqual(record['status'],'alive',record)
            self.assertEqual(probe(record['identity']),'alive')
            self.assertEqual(start(self.ledger,task)['identity'],record['identity'])
            self.assertEqual(run.control.status(task)['used_calls'],0)
        finally:
            run.control.cancel(task)
            end=time.monotonic()+8
            while time.monotonic()<end and status(self.ledger,task)['status']!='stopped': time.sleep(.1)
        self.assertEqual(status(self.ledger,task)['status'],'stopped')

    def git(self,*args,cwd=None):
        return subprocess.check_output(['git','-C',str(cwd or self.root),*args],stderr=subprocess.PIPE)

    def setup_git(self):
        self.git('init');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@localhost')
        self.git('add','.');self.git('commit','-m','baseline')
        bare=Path(self.temp.name)/'remote.git'
        self.git('init','--bare',str(bare))
        self.git('remote','add','origin',str(bare))
        (self.root/'calc.py').write_text('def add(a,b): return a+b\n')
        return bare

    def test_git_delivery_preserves_checkout_and_index_and_reconciles_lost_ack(self):
        bare=self.setup_git();before=self.git('status','--porcelain=v1');head=self.git('rev-parse','HEAD')
        run,task,_=self.runtime([],mode='delivery',branch='onecrew/fixture',remote='origin')
        profile=run.control.status(task)['configuration']['profile'];adapter=GitDelivery(run,task,profile,'')
        receipt=adapter.deliver(['calc.py'],'Fix addition','deliver')
        self.assertEqual(receipt['status'],'verified')
        self.assertEqual(self.git('status','--porcelain=v1'),before);self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(self.git('show','onecrew/fixture:calc.py',cwd=bare),(self.root/'calc.py').read_bytes())
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE actions SET status='unknown',receipt=NULL WHERE task_id=?",(task,))
        with patch.object(adapter,'git',wraps=adapter.git) as calls:
            receipt=adapter.deliver(['calc.py'],'Fix addition','deliver')
            self.assertTrue(receipt['reconciled'])
            self.assertFalse(any('push' in c.args or 'update-ref' in c.args for c in calls.call_args_list))

    def test_git_rejects_changed_remote_and_source(self):
        self.setup_git()
        run,task,_=self.runtime([],mode='delivery',branch='onecrew/fixture',remote='origin')
        adapter=GitDelivery(run,task,run.control.status(task)['configuration']['profile'],'')
        original=run.control.propose_action
        def race(*args,**kwargs):
            result=original(*args,**kwargs);(self.root/'calc.py').write_text('new user edit');return result
        with patch.object(run.control,'propose_action',side_effect=race):
            result=adapter.deliver(['calc.py'],'Fix','race')
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(self.git('ls-remote','--refs','origin','refs/heads/onecrew/fixture'),b'')

    def test_candidate_git_delivery_uses_candidate_not_dirty_checkout(self):
        bare=self.setup_git()
        run,task,_=self.runtime([],mode='change',image='sha256:'+'a'*64,branch='onecrew/candidate',remote='origin')
        state=run.state(task)[1]
        run._read(state,{'path':'calc.py'})
        source=(self.root/'calc.py').read_bytes()
        state['files']['calc.py']=run.store.blob(b'def add(a,b): return a+b+0\n');run._snapshot(state)
        adapter=GitDelivery(run,task,run.control.status(task)['configuration']['profile'],'')
        receipt=adapter.deliver(['calc.py'],'Candidate','candidate',candidate=state)
        self.assertEqual(receipt['status'],'verified')
        self.assertEqual(self.git('show','onecrew/candidate:calc.py',cwd=bare),b'def add(a,b): return a+b+0\n')
        self.assertEqual((self.root/'calc.py').read_bytes(),source)
        self.assertEqual(receipt['result']['candidate_snapshot'],state['snapshot'])

    def test_git_diff_and_tracked_deletion(self):
        bare=self.setup_git();(self.root/'test_calc.py').unlink()
        run,task,_=self.runtime([],mode='delivery',branch='onecrew/deletion',remote='origin')
        adapter=GitDelivery(run,task,run.control.status(task)['configuration']['profile'],'')
        self.assertIn('-import unittest',adapter.diff('test_calc.py')['diff'])
        receipt=adapter.deliver(['test_calc.py'],'Remove obsolete test','delete')
        self.assertEqual(receipt['status'],'verified')
        self.assertEqual(self.git('ls-tree','onecrew/deletion','--','test_calc.py',cwd=bare),b'')

    def test_unknown_delivery_resume_observes_same_intent_without_new_model(self):
        self.setup_git()
        run,task,worker=self.runtime([action('deliver',paths=['calc.py'],message='Fix addition')],
            mode='delivery',branch='onecrew/recovery',remote='origin')
        with patch.object(GitDelivery,'_observe',side_effect=LedgerError('Lost acknowledgement')):
            state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertIsNotNone(state['response'])
        restored=Owned(Ledger(self.root,self.ledger.state_root),worker);restored.resume(task)
        state=restored.run(task,steps=1)
        self.assertEqual(len(worker.calls),1)
        self.assertEqual(state['deliveries'][0]['status'],'verified')
        self.assertTrue(state['deliveries'][0]['reconciled'])

    def test_git_status_preserves_exact_index_bytes_after_stat_change(self):
        import os
        self.setup_git()
        run,task,_=self.runtime([],mode='delivery',branch='onecrew/stat',remote='origin')
        adapter=GitDelivery(run,task,run.control.status(task)['configuration']['profile'],'')
        index=(self.root/'.git/index').read_bytes()
        path=self.root/'test_calc.py';stat=path.stat()
        os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns+10000000000))
        adapter.status()
        self.assertEqual((self.root/'.git/index').read_bytes(),index)


if __name__=='__main__': unittest.main()
