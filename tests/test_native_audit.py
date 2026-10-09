import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_owned as fixtures
from onecrew.native_audit import capture,enable,citations,NativeClaude,workspace_path
from onecrew.ledger import LedgerError


class NativeAuditTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def setup_native(self):
        run,task,worker=self.f.runtime([],provider='claude',model='sonnet')
        # The fixture worker uses the same explicit provider while preserving grants.
        enable(run,task,'fixture authorization')
        return run,task,worker

    def report(self):
        return {'report':'calc.py subtracts instead of adding. Source-only audit; tests were not executed.',
                'citations':[{'path':'calc.py','start':1,'end':1,'quote':'return a-b'}],'question':''}

    def test_capture_omits_sensitive_and_binary_preserves_dirty_git_metadata(self):
        self.f.setup_git();(self.f.root/'.env').write_text('DO_NOT_COPY')
        (self.f.root/'app_secrets.dart').write_text('DO_NOT_COPY')
        (self.f.root/'data.txt').write_text('sk-ant-'+('x'*25))
        (self.f.root/'image.png').write_bytes(b'fake image')
        run,_,_=self.f.runtime([])
        destination=Path(self.f.temp.name)/'capture';result=capture(run,destination)
        self.assertEqual(set(result['files']),{'calc.py','test_calc.py'})
        self.assertTrue(result['metadata']['repositories'][0]['dirty'])
        self.assertFalse((destination/'.git').exists())
        self.assertNotIn('DO_NOT_COPY',''.join(p.read_text() for p in destination.rglob('*') if p.is_file()))

    def test_repair_reuses_session_preserves_budget_and_independent_review(self):
        run,task,worker=self.setup_native();profiles=[];old=worker.run
        def record(attempt,prompt,schema,profile):
            profiles.append(profile);return old(attempt,prompt,schema,profile)
        worker.run=record
        worker.responses=[self.report(),{'accepted':False,'feedback':'Clarify source-only scope'},self.report(),{'accepted':True,'feedback':'Verified.'}]
        for _ in range(4): state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'completed');self.assertEqual(run.control.status(task)['used_calls'],4)
        self.assertEqual(profiles[0]['native_session'],profiles[2]['native_session'])
        self.assertNotEqual(profiles[0]['native_session'],profiles[1]['native_session'])
        self.assertFalse(profiles[0]['native_resume']);self.assertTrue(profiles[2]['native_resume'])
        self.assertEqual((self.f.root/'calc.py').read_text(),'def add(a,b): return a-b\n')

    def test_invalid_citation_or_changed_snapshot_cannot_complete(self):
        run,task,_=self.setup_native();state=run.state(task)[1]
        for change in ({'path':'../outside.py'},{'start':0},{'quote':'fabricated'}):
            report=self.report();report['citations'][0].update(change)
            with self.assertRaises(LedgerError): citations(run,state,report)
        (Path(state['native_audit']['workspace'])/'calc.py').write_text('changed')
        with self.assertRaises(LedgerError): citations(run,state,self.report())

    def test_request_stops_native_calls_until_answer_and_restart_keeps_session(self):
        run,task,worker=self.setup_native()
        worker.responses=[dict(self.report(),question='Which deployed version is involved?')]
        state=run.run(task,steps=1);self.assertEqual(state['phase'],'waiting')
        session=state['native_audit']['worker_session']
        run.run(task);self.assertEqual(len(worker.calls),1)
        from onecrew.owned import Owned
        restored=Owned(self.f.ledger,worker)
        self.assertEqual(restored.state(task)[1]['native_audit']['worker_session'],session)

    def test_native_argv_has_native_tools_and_persistent_session_without_shell(self):
        run,task,_=self.setup_native();adapter=NativeClaude(run.control)
        directory=Path(self.f.temp.name)/'attempt';directory.mkdir()
        with patch.object(adapter,'prepare',return_value=directory),patch('onecrew.native_audit.Supervisor.run') as launch:
            adapter.run({},'audit',{},dict(model='sonnet',step_seconds=600,native_workspace=str(self.f.root),
                native_session='00000000-0000-0000-0000-000000000001',native_resume=False))
        argv=launch.call_args.args[1]
        self.assertIn('Read,Glob,Grep',argv);self.assertIn('--restricted',argv);self.assertIn('--safe-mode',argv)
        self.assertIn('--session-id',argv);self.assertNotIn('--no-session-persistence',argv)
        self.assertEqual(launch.call_args.kwargs['cwd'],self.f.root)

    def test_invalid_report_is_blocked_after_accounting_without_replaying_pending_attempt(self):
        run,task,worker=self.setup_native();report=self.report();report['citations'][0]['quote']='wrong'
        worker.responses=[report]
        state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertIsNone(state['pending'])
        self.assertTrue(state['native_audit']['worker_started'])
        self.assertEqual(run.control.status(task)['used_calls'],1)

    def test_settled_result_recovery_reuses_attempt_instead_of_launching_again(self):
        run,task,worker=self.setup_native();worker.responses=[self.report()]
        original=run.persist
        def crash(task_id,seq,state,**kw):
            if state.get('native_audit',{}).get('result_pending'): raise RuntimeError('simulated crash after result')
            return original(task_id,seq,state,**kw)
        with patch.object(run,'persist',side_effect=crash):
            with self.assertRaises(RuntimeError): run.run(task,steps=1)
        state=run.run(task,steps=1)
        self.assertEqual(state['native_audit']['stage'],'review');self.assertEqual(len(worker.calls),1)

    def test_crash_after_consumed_result_checkpoint_does_not_call_native_again(self):
        run,task,worker=self.setup_native();worker.responses=[self.report()]
        original=run.persist
        def crash(task_id,seq,state,**kw):
            saved=original(task_id,seq,state,**kw)
            if state.get('native_audit',{}).get('result_pending'): raise RuntimeError('simulated crash after commit')
            return saved
        with patch.object(run,'persist',side_effect=crash):
            with self.assertRaises(RuntimeError): run.run(task,steps=1)
        state=run.run(task,steps=1)
        self.assertEqual(state['native_audit']['stage'],'review');self.assertEqual(len(worker.calls),1)

    def test_long_windows_state_root_uses_short_bound_workspace(self):
        with patch('onecrew.native_audit.os.name','nt'),patch('onecrew.native_audit.Path.home',return_value=self.f.root):
            target=workspace_path(self.f.root/('long'*40),'TASK-'+('a'*32))
        self.assertTrue(target.is_relative_to(self.f.root/'.onecrew/workspaces'))
        self.assertNotIn('longlong',str(target));self.assertLess(len(target.name),20)


if __name__=='__main__': unittest.main()
