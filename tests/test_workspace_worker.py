import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_native_change as fixtures
from onecrew.ledger import LedgerError,canonical
from onecrew.snapshots import durable_write
from onecrew.workspace_worker import invocation_context,collect_candidate,WorkspaceClaude
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
        self.assertIn('Edit(./app/lib/main.dart)',argv)
        self.assertIn('Bash('+self.profile['test_command']+')',argv)
        self.assertNotIn('Edit',argv);self.assertNotIn('Bash',argv)
        self.assertIn('--restricted',argv);self.assertIn('dontAsk',argv)

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
