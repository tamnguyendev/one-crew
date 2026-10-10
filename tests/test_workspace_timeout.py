import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_native_change as fixtures
from onecrew.ledger import LedgerError, canonical
from onecrew.workspace_worker import checkpoint_timeout, invocation_context, WorkspaceClaude
from onecrew.workspace_tools import execute


class WorkspaceTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.NativeChangeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.recipe=dict(self.f.recipe,execution='workspace')
        from onecrew.owned_intake import submit
        from onecrew.owned import Owned
        from tests.test_workflow import FixtureWorker
        from tests.test_solution_gate import approve_fixture
        task=submit(self.f.f.ledger,'Timeout fixture','timeout-job',mode='change',provider='claude',model='sonnet',native_change=self.recipe,**approve_fixture(self.f.f.ledger,key='timeout-solution'))
        self.task=task['id'];self.worker=FixtureWorker(self.f.f.ledger,[])
        self.runtime=Owned(self.f.f.ledger,self.worker);self.runtime.enable(self.task)
        self.runtime.run(self.task,steps=1)
        self.seq,self.state=self.runtime.state(self.task)
        invocation_context(self.runtime,self.task,self.state,self.recipe)
        self.path=Path(self.state['native_change']['tool_context'])
        self.workspace=Path(self.state['native_change']['workspace'])

    def timeout(self,*,progress=True,stopped=True,session=None,terminal=False,truncated=False):
        if progress:
            target=self.workspace/'app/lib/main.dart';target.write_text('int add(int a,int b)=>a+b;\n')
        control=self.runtime.control.status(self.task)
        attempt=self.runtime.control.reserve(self.task,control['revision'],'timeout-'+str(control['used_calls']),{'stage':'native_change_work'})
        events=[{'type':'system','subtype':'init','session_id':session or self.state['native_change']['worker_session'],'tools':['Read','Edit']}]
        if terminal:events.append({'type':'result','subtype':'success'})
        log=self.path.with_suffix('.log');log.write_text('\n'.join(map(json.dumps,events))+'\n'+('{"type":' if truncated else ''))
        self.runtime.control.finish(attempt['id'],attempt['generation'],{'exit_code':1,'reason':'timeout','tree_stopped':stopped,'stdout':str(log)})
        self.state['pending']=attempt['id'];self.runtime.persist(self.task,self.seq,self.state)
        return attempt

    def test_checkpoint_is_idempotent_preserves_budget_scope_and_session(self):
        self.timeout(truncated=True)
        before=self.runtime.control.status(self.task)
        self.assertTrue(checkpoint_timeout(self.runtime,self.task))
        self.assertFalse(checkpoint_timeout(self.runtime,self.task))
        state=self.runtime.state(self.task)[1];native=state['native_change']
        self.assertIsNone(state['pending']);self.assertTrue(native['worker_started'])
        self.assertEqual(len(native['timeout_checkpoints']),1)
        self.assertEqual(native['workspace'],str(self.workspace))
        self.assertEqual(native['worker_session'],self.state['native_change']['worker_session'])
        after=self.runtime.control.status(self.task)
        self.assertEqual(after['budget'],before['budget']);self.assertEqual(after['used_calls'],1)
        self.assertEqual(after['configuration'],before['configuration']);self.assertFalse(self.worker.calls)
        self.assertIn('a-b',(self.runtime.ledger.project/'app/lib/main.dart').read_text())
        profile=invocation_context(self.runtime,self.task,state,self.recipe)
        self.assertNotEqual(state['native_change']['tool_context'],str(self.path))
        profile.update(native_workspace=str(self.workspace),model='sonnet',native_resume=native['worker_started'],native_session=native['worker_session'],native_instructions='unchanged scope')
        argv=WorkspaceClaude(self.runtime.control).arguments(self.workspace,{},profile)
        self.assertEqual(argv[argv.index('--resume')+1],native['worker_session'])

    def test_same_progress_again_blocks_even_with_fresh_test_log(self):
        self.timeout();checkpoint_timeout(self.runtime,self.task)
        self.seq,self.state=self.runtime.state(self.task)
        self.timeout()
        with self.assertRaisesRegex(LedgerError,'no new'):checkpoint_timeout(self.runtime,self.task)
        self.assertEqual(self.runtime.control.status(self.task)['used_calls'],2)
        self.assertIsNotNone(self.runtime.state(self.task)[1]['pending'])

    def test_no_progress_does_not_spend_another_call(self):
        self.timeout(progress=False)
        with self.assertRaisesRegex(LedgerError,'no new'):checkpoint_timeout(self.runtime,self.task)
        self.assertFalse(self.worker.calls)

    def test_workspace_drift_between_checkpoint_and_dispatch_blocks(self):
        self.timeout();checkpoint_timeout(self.runtime,self.task)
        state=self.runtime.state(self.task)[1]
        (self.workspace/'app/lib/main.dart').write_text('concurrent change')
        with self.assertRaisesRegex(LedgerError,'changed after timeout'):
            invocation_context(self.runtime,self.task,state,self.recipe)

    def test_fresh_timeout_is_checkpointed_inside_normal_advance(self):
        def fail(task,seq,state,*args):
            self.seq,self.state=seq,state
            self.path=Path(state['native_change']['tool_context'])
            self.timeout()
            raise LedgerError('Worker timeout')
        with patch.object(self.runtime,'_invoke',side_effect=fail):
            state=self.runtime.run(self.task,steps=1)
        self.assertEqual(state['phase'],'running');self.assertIsNone(state['pending'])
        self.assertEqual(len(state['native_change']['timeout_checkpoints']),1)

    def test_solution_question_cannot_be_hidden_by_timeout(self):
        self.timeout()
        log=self.path.with_suffix('.log')
        with log.open('a') as stream:
            stream.write(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','id':'question','name':'StructuredOutput','input':{'question':'Change scope?'}}]}})+'\n')
        with self.assertRaisesRegex(LedgerError,'solution question'):checkpoint_timeout(self.runtime,self.task)

    def test_unknown_process_status_blocks(self):
        self.timeout(stopped=False)
        with self.assertRaisesRegex(LedgerError,'process tree'):checkpoint_timeout(self.runtime,self.task)

    def test_session_mismatch_blocks(self):
        self.timeout(session='different-session')
        with self.assertRaisesRegex(LedgerError,'session identity'):checkpoint_timeout(self.runtime,self.task)

    def test_terminal_result_is_not_replayed(self):
        self.timeout(terminal=True)
        with self.assertRaisesRegex(LedgerError,'terminal result'):checkpoint_timeout(self.runtime,self.task)

    def test_unowned_change_blocks(self):
        self.timeout();(self.workspace/'app/pubspec.yaml').write_text('tampered')
        with self.assertRaisesRegex(LedgerError,'unowned'):checkpoint_timeout(self.runtime,self.task)

    def test_root_budget_exhaustion_blocks(self):
        self.timeout();control=self.runtime.control.status(self.task)
        control['used_calls']=control['budget']['limits']['max_calls']
        with patch.object(self.runtime.control,'status',return_value=control),self.assertRaisesRegex(LedgerError,'budget exhausted'):
            checkpoint_timeout(self.runtime,self.task)

    def test_pending_decision_and_guard_block(self):
        self.timeout()
        with patch.object(self.runtime.ledger,'requests',return_value=[{'id':'REQ'}]),self.assertRaisesRegex(LedgerError,'Pending user'):
            checkpoint_timeout(self.runtime,self.task)
        from onecrew.sandbox_gate import GateUnavailable
        with patch('onecrew.sandbox_gate.task_guard',return_value=lambda: (_ for _ in ()).throw(GateUnavailable('deadline'))),self.assertRaisesRegex(GateUnavailable,'deadline'):
            checkpoint_timeout(self.runtime,self.task)

    def test_restart_continues_then_independent_verify_review_and_apply(self):
        self.timeout()
        # Same durable pending timeout consumed through the normal runtime path.
        state=self.runtime.run(self.task,steps=1)
        self.assertEqual(state['phase'],'running');self.assertIsNone(state['pending'])
        def response(task,seq,state,stage,prompt,schema,profile):
            self.assertTrue(profile['native_resume'])
            self.assertEqual(profile['native_workspace'],str(self.workspace))
            self.assertIn('time slice',prompt)
            for row in self.f.candidate()['files']:
                p=self.workspace/row['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_text(row['text'])
            Path(state['native_change']['tool_context']).with_suffix('.receipt.json').write_text(canonical({'results':[{'status':'finished','passed':True}]}))
            return seq,{'report':'Fixed arithmetic and tested; device remains unverified.','question':''}
        with patch.object(self.runtime,'_invoke',side_effect=response):state=self.runtime.run(self.task,steps=1)
        self.assertEqual(state['native_change']['stage'],'verify')
        result={'passed':True,'detail':'All tests passed!','evidence':{'snapshot':state['snapshot'],'exit_code':0}}
        with patch('onecrew.native_change.verify',return_value=result) as gate:self.runtime.run(self.task,steps=1)
        self.assertEqual(gate.call_count,1)
        self.worker.responses=[{'accepted':True,'feedback':'Independent review accepted.'}]
        self.runtime.run(self.task,steps=1);state=self.runtime.run(self.task,steps=1)
        self.assertEqual(state['phase'],'completed');self.assertTrue(state['workspace_applied'])
        self.assertEqual(len(state['outputs']),1)

    def test_repeated_test_failure_is_retained_across_time_slices(self):
        for row in self.f.candidate()['files']:
            p=self.workspace/row['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_text(row['text'])
        with patch('onecrew.native_change.verify',return_value={'passed':False,'detail':'same failure'}):
            for _ in range(3):execute(self.path)
        self.timeout();checkpoint_timeout(self.runtime,self.task)
        state=self.runtime.state(self.task)[1]
        invocation_context(self.runtime,self.task,state,self.recipe)
        with self.assertRaisesRegex(LedgerError,'identical'):execute(Path(state['native_change']['tool_context']))
