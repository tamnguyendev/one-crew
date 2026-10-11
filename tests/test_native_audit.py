import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_owned as fixtures
from onecrew.native_audit import capture,enable,citations,NativeClaude,workspace_path,source_roots
from onecrew.ledger import LedgerError
from onecrew.discovery import Discovery


class NativeAuditTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_flutter_context_keeps_dart_and_fixtures_without_database_and_html_exports(self):
        files={'resx/generated.dart':'void cloudAuthFailureMessage() {}',
               'resx/query.sql':'select 1;', 'resx/query.xsql':'select 2;',
               'docs/classes/Foo.html':'generated docs', 'docs/guide.md':'manual guide',
               'test/fixtures/input.sql':'select 3;', 'lib/data/query.sql':'select 4;',
               'web/index.html':'app entry', 'pubspec.yaml':'name: fixture'}
        for name,text in files.items():
            p=self.f.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        run,_,_=self.f.runtime([])
        progress=[]
        result=capture(run,Path(self.f.temp.name)/'flutter',flutter_context=True,progress=progress.append)
        excluded={'resx/query.sql','resx/query.xsql','docs/classes/Foo.html'}
        self.assertTrue((set(files)-excluded)<=set(result['files']))
        self.assertFalse(excluded&set(result['files']))
        self.assertEqual(result['metadata']['context_omissions'],{'database_resource':2,'html_documentation':1})
        audit=capture(run,Path(self.f.temp.name)/'audit')
        self.assertTrue(set(files)<=set(audit['files']))
        self.assertTrue(all((self.f.root/p).exists() for p in excluded))
        self.assertEqual(progress[0]['files'],0)
        self.assertEqual(progress[-1]['status'],'captured')
        self.assertEqual(progress[-1]['files'],len(result['files']))

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

    def bad_report(self):
        report=self.report();report['citations'][0]['quote']='wrong';return report

    def test_citation_error_becomes_repair_in_same_worker_session_without_replaying_result(self):
        run,task,worker=self.setup_native();profiles=[];old=worker.run
        def record(attempt,prompt,schema,profile):
            profiles.append((profile,prompt));return old(attempt,prompt,schema,profile)
        worker.run=record
        worker.responses=[self.bad_report(),self.report(),{'accepted':True,'feedback':'Verified.'}]
        state=run.run(task,steps=1)
        self.assertNotEqual(state['phase'],'blocked');self.assertIsNone(state['pending'])
        native=state['native_audit']
        self.assertEqual(native['stage'],'work');self.assertEqual(native['repairs'],1)
        self.assertNotIn('result_pending',native);self.assertIn('Citation #1 (calc.py:1-1)',native['feedback'])
        for _ in range(2): state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'completed');self.assertEqual(run.control.status(task)['used_calls'],3)
        self.assertEqual(profiles[0][0]['native_session'],profiles[1][0]['native_session'])
        self.assertTrue(profiles[1][0]['native_resume']);self.assertIn('failed the citation check',profiles[1][1])

    def test_citation_repairs_share_cap_then_block_with_accounting(self):
        run,task,worker=self.setup_native()
        worker.responses=[self.bad_report(),self.bad_report(),self.bad_report()]
        for _ in range(3): state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertIn('citation repair limit',state['message'])
        self.assertIsNone(state['pending']);self.assertNotIn('result_pending',state['native_audit'])
        self.assertEqual(run.control.status(task)['used_calls'],3);self.assertEqual(len(worker.calls),3)

    def test_report_length_defect_is_repairable(self):
        run,task,worker=self.setup_native();short=dict(self.report(),report='too short')
        worker.responses=[short]
        state=run.run(task,steps=1)
        self.assertEqual(state['native_audit']['repairs'],1);self.assertIn('report length invalid',state['native_audit']['feedback'])

    def test_citation_feedback_names_actual_line_only_for_unique_quote(self):
        from onecrew.native_audit import CitationError
        run,task,_=self.setup_native();state=run.state(task)[1]
        off=self.report();off['citations'][0].update(start=2,end=2)
        with self.assertRaises(CitationError) as caught: citations(run,state,off)
        self.assertIn('lines 1-1',str(caught.exception))
        missing=self.report();missing['citations'][0]['quote']='absent text'
        with self.assertRaises(CitationError) as caught: citations(run,state,missing)
        self.assertNotIn('occurs exactly once',str(caught.exception))
        (Path(state['native_audit']['workspace'])/'calc.py').write_text('changed')
        with self.assertRaises(LedgerError) as caught: citations(run,state,self.report())
        self.assertNotIsInstance(caught.exception,CitationError)

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

    def turn_limit_worker(self,worker):
        from onecrew.native_audit import NativeTurnLimit
        class TurnLimitWorker(type(worker)):
            def result(self,attempt):
                value=json.loads(attempt['result'])['fixture']
                if value=='TURN_LIMIT': raise NativeTurnLimit(attempt['id'],{'input_tokens':1,'output_tokens':1},30)
                return value,[]
        worker.__class__=TurnLimitWorker
        return worker

    def test_turn_limit_continues_same_session_then_completes(self):
        run,task,worker=self.setup_native();self.turn_limit_worker(worker);profiles=[];old=worker.run
        def record(attempt,prompt,schema,profile):
            profiles.append((profile,prompt));return old(attempt,prompt,schema,profile)
        worker.run=record
        worker.responses=['TURN_LIMIT',self.report(),{'accepted':True,'feedback':'Verified.'}]
        state=run.run(task,steps=1)
        native=state['native_audit']
        self.assertNotEqual(state['phase'],'blocked');self.assertIsNone(state['pending'])
        self.assertEqual(native['turn_continuations'],1);self.assertTrue(native['worker_started'])
        self.assertEqual(run.control.status(task)['used_calls'],1)
        for _ in range(2): state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'completed');self.assertEqual(run.control.status(task)['used_calls'],3)
        self.assertEqual(profiles[0][0]['native_session'],profiles[1][0]['native_session'])
        self.assertTrue(profiles[1][0]['native_resume']);self.assertIn('per-invocation turn limit',profiles[1][1])

    def test_turn_limit_is_bounded_then_blocks(self):
        run,task,worker=self.setup_native();self.turn_limit_worker(worker)
        worker.responses=['TURN_LIMIT']*3
        for _ in range(3): state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertIn('turn limit',state['message'])
        self.assertEqual(run.control.status(task)['used_calls'],3);self.assertEqual(len(worker.calls),3)

    def test_native_claude_recognizes_only_the_cli_turn_limit_result(self):
        from onecrew.native_audit import NativeTurnLimit,turn_limit
        run,task,_=self.setup_native()
        def attempt_with(subtype):
            log=Path(self.f.temp.name)/(subtype+'.jsonl')
            log.write_text(json.dumps({'type':'system'})+'\n'+json.dumps({'type':'result','subtype':subtype,'num_turns':31,
                'is_error':True,'usage':{'input_tokens':5}})+'\n')
            return {'id':'ATT-x','result':json.dumps({'exit_code':1,'reason':None,'stdout':str(log)})}
        with patch('onecrew.provider_limits.check_attempt'):
            with self.assertRaises(NativeTurnLimit) as caught: turn_limit('claude',attempt_with('error_max_turns'))
            self.assertEqual(caught.exception.turns,31)
            turn_limit('claude',attempt_with('error_during_execution'))  # other failures keep the generic path

    def test_native_audit_starts_on_never_started_task_without_model_calls(self):
        from onecrew.owned import Owned
        from onecrew.owned_intake import submit
        task=submit(self.f.ledger,'Native audit from the start','native-fresh',provider='claude',model='sonnet')['id']
        run=Owned(self.f.ledger,fixtures.FixtureWorker(self.f.ledger,[]))
        self.assertIsNone(run.state(task)[1])
        state=enable(run,task,'operator chose native from the start')
        self.assertEqual(state['native_audit']['stage'],'work');self.assertEqual(run.control.status(task)['used_calls'],0)

    def test_capture_reads_module_javascript_and_typescript_variants(self):
        for name in ('tool.mjs','lib.cjs','types.mts','legacy.cts'):
            (self.f.root/name).write_text('export const x = 1;\n')
        run,_,_=self.f.runtime([])
        result=capture(run,Path(self.f.temp.name)/'modules')
        self.assertTrue({'tool.mjs','lib.cjs','types.mts','legacy.cts'}<=set(result['files']))

    def test_capture_keeps_large_source_file_but_read_api_stays_200k(self):
        (self.f.root/'big.ts').write_text('export const x = 1;\n'+'// filler line for a large controller file\n'*6000)
        self.assertGreater((self.f.root/'big.ts').stat().st_size,200_000)
        run,_,_=self.f.runtime([])
        result=capture(run,Path(self.f.temp.name)/'big')
        self.assertIn('big.ts',result['files'])
        with self.assertRaises(LedgerError): Discovery(self.f.root).data('big.ts')

    def test_long_windows_state_root_uses_short_bound_workspace(self):
        with patch('onecrew.native_audit.os.name','nt'),patch('onecrew.native_audit.Path.home',return_value=self.f.root):
            target=workspace_path(self.f.root/('long'*40),'TASK-'+('a'*32))
        self.assertTrue(target.is_relative_to(self.f.root/'.onecrew/workspaces'))
        self.assertNotIn('longlong',str(target));self.assertLess(len(target.name),20)

    def test_capture_uses_prior_task_repo_discovery_not_entire_multi_repo_root(self):
        from onecrew.ledger import canonical
        (self.f.root/'app').mkdir();(self.f.root/'app/main.py').write_text('x=1')
        (self.f.root/'unrelated').mkdir();(self.f.root/'unrelated/many.py').write_text('x=2')
        run,task,_=self.f.runtime([])
        blob=run.store.blob(canonical({'action':'git_status','result':{'repository':'app','head':'abc'}}).encode())
        state={'receipts':[{'index':0,'blob':blob,'action':'git_status','successful':True}]}
        self.assertEqual(source_roots(run,state),['app'])
        result=capture(run,Path(self.f.temp.name)/'scoped',source_roots(run,state))
        self.assertEqual(list(result['files']),['app/main.py']);self.assertEqual(result['metadata']['source_roots'],['app'])

    def test_uppercase_json_credential_values_are_withheld_but_env_lookups_remain_readable(self):
        from onecrew.discovery import scan_text
        for key in ('AUTH_SERVICE_PASSWORD','AUTH_TOKEN','CLIENT_SECRET','api_key'):
            with self.assertRaises(LedgerError): scan_text(json.dumps({key:'fixture-value-123456'}).encode())
        self.assertIn('String.fromEnvironment',scan_text(b"const value = String.fromEnvironment('AUTH_SERVICE_PASSWORD');"))


if __name__=='__main__': unittest.main()
