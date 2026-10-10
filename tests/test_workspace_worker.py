import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_native_change as fixtures
from onecrew.ledger import LedgerError,canonical
from onecrew.snapshots import durable_write
from onecrew.workspace_worker import invocation_context,collect_candidate,WorkspaceClaude,edit_permissions
from onecrew.workspace_tools import execute


class WorkspaceWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.NativeChangeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.runtime=self.f.run;self.task=self.f.task
        self.state=self.runtime.state(self.task)[1];self.recipe=dict(self.f.recipe,execution='workspace')
        self.profile=invocation_context(self.runtime,self.task,self.state,self.recipe)
        self.path=Path(self.state['native_change']['tool_context'])
        self.workspace=Path(self.state['native_change']['workspace'])

    def edit(self):
        for value in self.f.candidate()['files']:
            durable_write(self.workspace/value['path'],value['text'].encode())

    def test_collect_checks_unowned_and_requires_real_test_receipt(self):
        self.edit()
        with self.assertRaisesRegex(LedgerError,'did not invoke'):collect_candidate(self.runtime,self.state,self.f.candidate(),self.recipe)
        self.path.with_suffix('.receipt.json').write_text('{"results":[{"status":"started"}]}')
        with self.assertRaisesRegex(LedgerError,'no finished'):collect_candidate(self.runtime,self.state,self.f.candidate(),self.recipe)
        self.path.with_suffix('.receipt.json').write_text('{"results":[{"status":"finished","passed":false}]}')
        result=collect_candidate(self.runtime,self.state,{'report':'report','question':''},self.recipe)
        self.assertEqual(len(result['files']),2)
        (self.workspace/'app/pubspec.yaml').write_text('tampered')
        with self.assertRaisesRegex(LedgerError,'unowned'):collect_candidate(self.runtime,self.state,result,self.recipe)

    def test_new_unowned_files_rejected_and_user_source_unchanged(self):
        self.edit();(self.workspace/'injected.dart').write_text('bad')
        with self.assertRaisesRegex(LedgerError,'unowned'):collect_candidate(self.runtime,self.state,{},self.recipe,require_test=False)
        self.assertIn('a-b',(self.runtime.ledger.project/'app/lib/main.dart').read_text())

    def test_test_command_runs_gate_without_persisting_parent_state(self):
        self.edit();before=self.runtime.state(self.task)
        with patch('onecrew.native_change.verify',return_value={'passed':False,'detail':'assertion failed'}) as gate:
            result=execute(self.path)
        self.assertFalse(result['passed']);self.assertEqual(gate.call_count,1)
        self.assertEqual(before,self.runtime.state(self.task))
        self.assertIn('a-b',(self.runtime.ledger.project/'app/lib/main.dart').read_text())
        self.assertEqual(json.loads(self.path.with_suffix('.receipt.json').read_text())['results'][0]['status'],'finished')

    def test_same_failure_stops_after_three_checkpoints_and_hard_cap_survives_reload(self):
        self.edit()
        with patch('onecrew.native_change.verify',return_value={'passed':False,'detail':'same failure'}) as gate:
            for _ in range(3):execute(self.path)
            with self.assertRaisesRegex(LedgerError,'identical'):execute(self.path)
            self.assertEqual(gate.call_count,3)
        self.path.with_suffix('.receipt.json').write_text(canonical({'results':[{'fingerprint':str(i)} for i in range(8)]}))
        with self.assertRaisesRegex(LedgerError,'limit'):execute(self.path)

    def test_result_recovery_reuses_context_and_baseline(self):
        original=self.state['native_change']['tool_baseline'].copy()
        self.state['native_change']['result_pending']={'report':'already paid','question':''}
        self.edit()
        recovered=invocation_context(self.runtime,self.task,self.state,self.recipe)
        self.assertEqual(recovered,self.profile)
        self.assertEqual(original,self.state['native_change']['tool_baseline'])
        self.state['native_change'].pop('result_pending');self.state['pending']='attempt-id'
        self.assertEqual(invocation_context(self.runtime,self.task,self.state,self.recipe),self.profile)

    def test_permissions_only_exact_owned_files_and_recipe(self):
        worker=WorkspaceClaude(self.runtime.control)
        profile=dict(self.profile,native_workspace=str(self.workspace),model='sonnet',native_resume=False,
                     native_session='session',native_instructions='scope',step_seconds=60)
        directory=self.workspace/'probe';directory.mkdir()
        with patch.object(worker,'prepare',return_value=directory),patch('onecrew.workspace_worker.Supervisor') as supervisor:
            worker.run({},'prompt',{},profile)
        argv=supervisor.return_value.run.call_args.args[1]
        self.assertIn(edit_permissions(self.workspace,['app/lib/main.dart'])[0],argv)
        self.assertIn('Bash('+self.profile['test_command']+')',argv)
        self.assertNotIn('Edit',argv);self.assertNotIn('Bash',argv)
        self.assertIn('--restricted',argv);self.assertIn('dontAsk',argv)

    def test_absolute_rules_escape_patterns_and_are_independent_of_cwd(self):
        rules=edit_permissions(self.workspace,['app/lib/main.dart','app/test/[case].dart'])
        self.assertIn('edit(//c/',rules[0].lower())
        self.assertIn('/app/lib/main.dart)',rules[0])
        self.assertIn(r'\[case\]',rules[1])
        with self.assertRaises(LedgerError):edit_permissions(self.workspace,['../outside.dart'])

    def permission_failure(self,denied_path=None):
        control=self.runtime.control.status(self.task)
        attempt=self.runtime.control.reserve(self.task,control['revision'],'permission-fixture',{'stage':'native_change_work'})
        events=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'edit-1','name':'Edit',
            'input':{'file_path':str(denied_path or self.workspace/'app/lib/main.dart')}}]}},
            {'type':'system','subtype':'permission_denied','message':'denied','tool_use_id':'edit-1'},
            {'type':'result','subtype':'success','is_error':False,'session_id':self.state['native_change']['worker_session'],
             'structured_output':{'report':'Permission was denied; no changes.','question':'Need existing Edit permission.'},'usage':{}}]
        log=self.path.with_suffix('.log');log.write_text('\n'.join(json.dumps(e) for e in events))
        self.runtime.control.finish(attempt['id'],attempt['generation'],{'exit_code':0,'stdout':str(log)})
        seq,_=self.runtime.state(self.task);self.state['pending']=attempt['id']
        self.runtime.persist(self.task,seq,self.state)
        control=self.runtime.control.status(self.task)
        control['configuration']['profile']['native_change']['execution']='workspace'
        return control

    def test_explicit_permission_recovery_preserves_paid_response_budget_and_usage(self):
        from onecrew.workspace_worker import recover_permissions
        control=self.permission_failure()
        with patch.object(self.runtime.control,'status',return_value=control):
            result=recover_permissions(self.runtime,self.task,'User explicitly requested fixing existing permissions and retrying.')
        state=self.runtime.state(self.task)[1]
        self.assertIsNone(state['pending']);self.assertTrue(state['native_change']['worker_started'])
        self.assertEqual(result['new_model_calls'],0);self.assertEqual(self.runtime.control.status(self.task)['used_calls'],1)
        self.assertEqual(len(state['usage']),1);self.assertEqual(state['assistance'],'entry-runtime-repair')
        self.assertEqual(state['native_change']['permission_recoveries'][0]['response']['question'],'Need existing Edit permission.')
        self.assertEqual(self.f.worker.calls,[])
        with self.assertRaises(LedgerError):recover_permissions(self.runtime,self.task,'Duplicate explicit retry')

    def test_permission_recovery_refuses_out_of_scope_denial_and_changed_candidate(self):
        from onecrew.workspace_worker import recover_permissions
        control=self.permission_failure(self.workspace/'unowned.dart')
        with patch.object(self.runtime.control,'status',return_value=control),self.assertRaisesRegex(LedgerError,'No proven denial'):
            recover_permissions(self.runtime,self.task,'User authorized only existing scoped writes')
        self.assertIsNotNone(self.runtime.state(self.task)[1]['pending'])

    def test_permission_recovery_refuses_modified_owned_file(self):
        from onecrew.workspace_worker import recover_permissions
        control=self.permission_failure();self.edit()
        with patch.object(self.runtime.control,'status',return_value=control),self.assertRaises(LedgerError):
            recover_permissions(self.runtime,self.task,'User requested permission recovery')
        self.assertIsNotNone(self.runtime.state(self.task)[1]['pending'])

    def test_permission_recovery_cannot_answer_pending_user_request(self):
        from onecrew.workspace_worker import recover_permissions
        control=self.permission_failure()
        with patch.object(self.runtime.control,'status',return_value=control),\
             patch.object(self.runtime.ledger,'requests',return_value=[{'id':'REQ-pending'}]),\
             self.assertRaisesRegex(LedgerError,'Pending requests'):
            recover_permissions(self.runtime,self.task,'Repair existing permissions only')
        self.assertIsNotNone(self.runtime.state(self.task)[1]['pending'])

    def test_independent_verification_still_runs_after_workspace_result(self):
        # Store the opt-in profile as the fixture's original configuration.
        from onecrew.native_change import advance
        seq,state=self.runtime.state(self.task)
        def native_invoke(task,seq,state,stage,prompt,schema,profile):
            self.edit()
            path=Path(state['native_change']['tool_context'])
            path.with_suffix('.receipt.json').write_text('{"results":[{"status":"finished","passed":true}]}')
            return seq,{'report':'Actual native edit and test complete; device unverified.','question':''}
        with patch.object(self.runtime,'_invoke',side_effect=native_invoke):
            advance(self.runtime,self.task,seq,state,{'native_change':self.recipe})
        seq,state=self.runtime.state(self.task)
        self.assertEqual(state['native_change']['stage'],'verify')
        self.assertFalse(state.get('workspace_applied',False))
        result={'passed':False,'detail':'independent failure','failure_kind':'test','evidence':{}}
        with patch('onecrew.native_change.verify',return_value=result) as gate:
            advance(self.runtime,self.task,seq,state,{'native_change':self.recipe})
        self.assertEqual(gate.call_count,1);self.assertEqual(state['native_change']['stage'],'work')


if __name__=='__main__':unittest.main()
